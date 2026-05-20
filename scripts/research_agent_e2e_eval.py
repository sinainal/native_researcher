#!/usr/bin/env python3
"""Run end-to-end Research Agent evals against local llama.cpp models."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import shlex
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, get_settings
from app.llm.llamacpp_profiles import build_llamacpp_server_args
from app.schemas.article import Article, ArticleReference
from app.schemas.helper import HelperChatRequest
from app.schemas.pdf import PDFDownloadResponse, PDFDownloadResult
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.schemas.research_execution import ResearchPlanExecuteRequest
from app.services.agent.helper_ai_service import HelperAIService
from app.services.helper_log_service import HelperLogService
from app.services.llamacpp_model_discovery import discover_llamacpp_model_files
from app.services.local_llamacpp_supervisor import ensure_llamacpp_ready, stop_local_llamacpp_servers
from app.services.pdf_extraction_service import PDFExtractionService
from app.services.research_candidate_normalizer import NormalizedResearchCandidate
from app.services.research_execution_service import ResearchExecutionService
from app.services.research_pdf_pipeline_service import ResearchPdfPipelineService
from app.services.research_plan_benchmark import (
    DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT,
    approximate_token_count,
    plan_quality_score,
    query_specificity_score,
)
from app.services.research_plan_payload_service import build_execution_plan
from app.services.research_screening_service import ResearchScreeningService
from app.utils.cache import TTLCache

import app.services.research_screening_service as screening_module


DEFAULT_MODELS = [
    "gemma-4-26B-A4B-it-UD-IQ4_NL",
    "Qwen3.6-35B-A3B-IQ3_S-merged",
]

DOPAMINE_SERIES_PROMPT = (
    "Create a precise research plan to find primary papers across the full dopamine D-series receptor family "
    "(D1, D2, D3, D4, and D5). The goal is to compare receptor-subtype-specific binding, signaling, residue, "
    "mutagenesis, ligand-interaction, cellular pathway, and functional assay evidence. Keep the plan focused on "
    "dopamine receptor evidence, not broad Parkinson disease models unless the receptor evidence is explicit. "
    "I want clear branches for the complete D1-D5 series, concise inclusion/exclusion criteria, and full-text "
    "questions that can extract subtype, ligand or perturbation, assay/model, measured endpoint, direction of effect, "
    "exact evidence quote, and uncertainty."
)

SCREENING_PLAN = {
    "topic": "Dopamine receptor residue interaction evidence",
    "objective": "Find primary papers that report exact dopamine receptor residue or binding-site interactions.",
    "target_count_per_branch": 1,
    "active_databases": ["PubMed"],
    "candidate_budget": {"per_database": 3},
    "search_branches": [{"id": "d1", "label": "D1 receptor residue evidence", "query": "dopamine D1 receptor residue"}],
    "screening_criteria": [
        {
            "id": "residue_evidence",
            "label": "Residue evidence",
            "description": "Reports a specific residue, binding site, or contact in dopamine receptor interaction.",
            "required": True,
            "weight": 1.0,
        },
        {
            "id": "primary_experiment",
            "label": "Primary experiment",
            "description": "Uses primary experimental, structural, docking, mutagenesis, or binding evidence.",
            "required": False,
            "weight": 0.7,
        },
    ],
    "exclusion_criteria": [
        "Exclude reviews, editorials, and papers without primary evidence.",
        "Exclude papers unrelated to dopamine receptors.",
    ],
    "extraction_questions": ["Which residue or binding-site contact is reported for dopamine receptor interaction?"],
    "extraction_fields": ["residue", "evidence_quote"],
}

DOPAMINE_SERIES_PLAN = {
    "topic": "Dopamine D-series receptor evidence",
    "objective": "Select primary papers covering specific dopamine receptor subtypes D1-D5 with receptor-level evidence.",
    "target_count_per_branch": 5,
    "active_databases": ["PubMed"],
    "candidate_budget": {"per_database": 8},
    "search_branches": [
        {"id": "d1", "label": "D1 receptor", "query": "dopamine D1 receptor DRD1"},
        {"id": "d2", "label": "D2 receptor", "query": "dopamine D2 receptor DRD2"},
        {"id": "d3", "label": "D3 receptor", "query": "dopamine D3 receptor DRD3"},
        {"id": "d4", "label": "D4 receptor", "query": "dopamine D4 receptor DRD4"},
        {"id": "d5", "label": "D5 receptor", "query": "dopamine D5 receptor DRD5"},
    ],
    "screening_criteria": [
        {
            "id": "dopamine_receptor_subtype",
            "label": "D-series subtype match",
            "description": "Clearly studies a dopamine D-series receptor subtype D1, D2, D3, D4, or D5.",
            "required": True,
            "weight": 1.0,
        },
        {
            "id": "primary_receptor_evidence",
            "label": "Primary receptor evidence",
            "description": "Reports primary binding, signaling, mutagenesis, residue, cellular pathway, or functional assay evidence.",
            "required": True,
            "weight": 1.0,
        },
        {
            "id": "subtype_specificity",
            "label": "Subtype specificity",
            "description": "The result is subtype-specific rather than only pan-dopamine or general neuroscience evidence.",
            "required": False,
            "weight": 0.5,
        },
    ],
    "exclusion_criteria": [
        "Exclude reviews, editorials, and non-primary summaries.",
        "Exclude papers about dopamine metabolism, transporters, or disease models without explicit D1-D5 receptor evidence.",
        "Exclude unrelated monoamine, serotonin, or adrenergic receptor papers.",
    ],
    "extraction_questions": [
        "Which dopamine receptor subtype is studied and what ligand, perturbation, or assay is used?",
        "What receptor-level binding, signaling, residue, pathway, or functional endpoint is reported?",
        "What exact evidence quote supports the subtype-specific conclusion?",
    ],
    "extraction_fields": [
        "receptor_subtype",
        "ligand_or_perturbation",
        "assay_or_model",
        "endpoint",
        "effect_direction",
        "evidence_quote",
        "uncertainty",
    ],
}


@dataclass
class ModelTarget:
    id: str
    path: str
    profile: str


class EvalPubMedService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def search(self, request: Any) -> PubMedSearchResponse:
        self.calls.append(request)
        articles = fixture_articles()
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=request.query,
                total_results_found=len(articles),
                fetched_results=min(len(articles), int(request.max_results or len(articles))),
                batch_size_used=int(request.max_results or len(articles)),
                request_count=1,
                elapsed_ms=1,
                cache_hit=False,
                primary_source=str(request.preferred_source or "pubmed"),
                sources_used=[str(request.preferred_source or "pubmed")],
            ),
            articles=articles[: int(request.max_results or len(articles))],
        )


class EvalPDFService:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.download_calls = 0

    async def download_articles(self, payload: Any) -> PDFDownloadResponse:
        self.download_calls += 1
        self.out_dir.mkdir(parents=True, exist_ok=True)
        results = []
        for index, article in enumerate(payload.articles, start=1):
            path = self.out_dir / f"full_text_{index}.xml"
            path.write_text(
                (
                    "<article><body><sec><title>Results</title>"
                    "<p>Structural analysis reported that residue Alpha123 in the dopamine D1 receptor "
                    "contacts dopamine in the binding pocket.</p>"
                    "</sec></body></article>"
                ),
                encoding="utf-8",
            )
            results.append(
                PDFDownloadResult(
                    article=article,
                    success=True,
                    file_path=str(path),
                    content_kind="xml_fulltext",
                )
            )
        return PDFDownloadResponse(
            total=len(results),
            success_count=len(results),
            failed_count=0,
            results=results,
        )


def fixture_articles() -> list[Article]:
    return [
        Article(
            id=1,
            source_name="pubmed",
            source_record_id="fixture-relevant",
            pmid="1001",
            title="Alpha123 residue contact in dopamine D1 receptor binding",
            abstract=(
                "A primary structural and mutagenesis study reports that residue Alpha123 in the dopamine D1 "
                "receptor contacts dopamine in the binding pocket and alters ligand interaction."
            ),
            year="2024",
            doi="10.1000/relevant",
            article_type="Journal Article",
        ),
        Article(
            id=2,
            source_name="pubmed",
            source_record_id="fixture-review",
            pmid="1002",
            title="Review of dopamine receptor signaling",
            abstract="This review summarizes dopamine receptor signaling but reports no primary residue contact evidence.",
            year="2023",
            doi="10.1000/review",
            article_type="Review",
        ),
        Article(
            id=3,
            source_name="pubmed",
            source_record_id="fixture-unrelated",
            pmid="1003",
            title="Serotonin transporter membrane trafficking",
            abstract="This primary study concerns serotonin transporters and does not investigate dopamine receptors.",
            year="2022",
            doi="10.1000/unrelated",
            article_type="Journal Article",
        ),
    ]


def fixture_candidates() -> list[NormalizedResearchCandidate]:
    return [
        NormalizedResearchCandidate(candidate_id=f"cand_{index}", article=article)
        for index, article in enumerate(fixture_articles(), start=1)
    ]


def dopamine_series_articles() -> list[Article]:
    return [
        Article(
            id=11,
            source_name="pubmed",
            source_record_id="series-d1",
            pmid="2001",
            title="DRD1 dopamine D1 receptor cAMP signaling after agonist binding",
            abstract="A primary cell assay shows dopamine D1 receptor DRD1 agonist binding increases cAMP signaling.",
            year="2024",
            doi="10.1000/d1",
            article_type="Journal Article",
        ),
        Article(
            id=12,
            source_name="pubmed",
            source_record_id="series-d2",
            pmid="2002",
            title="Dopamine D2 receptor DRD2 ligand binding and beta-arrestin signaling",
            abstract="Primary binding and signaling experiments report DRD2 ligand affinity and beta-arrestin pathway activation.",
            year="2023",
            doi="10.1000/d2",
            article_type="Journal Article",
        ),
        Article(
            id=13,
            source_name="pubmed",
            source_record_id="series-d3",
            pmid="2003",
            title="Mutagenesis identifies a dopamine D3 receptor DRD3 residue controlling ligand selectivity",
            abstract="A mutagenesis study identifies residue Gamma345 in dopamine D3 receptor DRD3 as controlling ligand selectivity.",
            year="2022",
            doi="10.1000/d3",
            article_type="Journal Article",
        ),
        Article(
            id=14,
            source_name="pubmed",
            source_record_id="series-d4",
            pmid="2004",
            title="Dopamine D4 receptor DRD4 calcium pathway response in neuronal cells",
            abstract="Primary neuronal-cell assays show dopamine D4 receptor DRD4 activation changes calcium pathway signaling.",
            year="2021",
            doi="10.1000/d4",
            article_type="Journal Article",
        ),
        Article(
            id=15,
            source_name="pubmed",
            source_record_id="series-d5",
            pmid="2005",
            title="Dopamine D5 receptor DRD5 functional assay maps ligand-dependent signaling",
            abstract="A primary functional assay maps dopamine D5 receptor DRD5 ligand-dependent signaling endpoints.",
            year="2020",
            doi="10.1000/d5",
            article_type="Journal Article",
        ),
        Article(
            id=16,
            source_name="pubmed",
            source_record_id="series-review",
            pmid="2006",
            title="Review of dopamine receptor family pharmacology",
            abstract="This review summarizes D1-D5 receptor pharmacology without new primary receptor experiments.",
            year="2024",
            doi="10.1000/d-review",
            article_type="Review",
        ),
        Article(
            id=17,
            source_name="pubmed",
            source_record_id="series-transporter",
            pmid="2007",
            title="Dopamine transporter DAT controls striatal dopamine uptake",
            abstract="A primary transporter study measures DAT dopamine uptake but does not study dopamine D1-D5 receptors.",
            year="2023",
            doi="10.1000/dat",
            article_type="Journal Article",
        ),
        Article(
            id=18,
            source_name="pubmed",
            source_record_id="series-serotonin",
            pmid="2008",
            title="Serotonin 5-HT2A receptor ligand binding in cortical neurons",
            abstract="This primary study reports serotonin receptor ligand binding and does not involve dopamine receptors.",
            year="2022",
            doi="10.1000/5ht",
            article_type="Journal Article",
        ),
    ]


def dopamine_series_candidates() -> list[NormalizedResearchCandidate]:
    return [
        NormalizedResearchCandidate(candidate_id=f"series_{index}", article=article)
        for index, article in enumerate(dopamine_series_articles(), start=1)
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-model Research Agent e2e evals.")
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS), help="Comma-separated discovered llama.cpp model IDs.")
    parser.add_argument("--batch-sizes", default="1,2,3,5", help="Comma-separated screening batch sizes.")
    parser.add_argument("--out", default="output/evals/research_agent_e2e", help="Output directory.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8098", help="llama.cpp base URL.")
    parser.add_argument("--planner-timeout-s", type=int, default=420, help="Per-model planner timeout.")
    parser.add_argument("--thinking-level", default="off", choices=["off", "on", "low", "max"], help="Thinking level for model calls.")
    parser.add_argument("--n-gpu-layers", default="", help="Optional llama.cpp -ngl override for tight-VRAM eval runs.")
    parser.add_argument("--skip-planner", action="store_true", help="Skip staged planner eval.")
    parser.add_argument("--skip-pdf-model", action="store_true", help="Use deterministic PDF extraction instead of model extraction.")
    return parser.parse_args()


def resolve_targets(settings: Settings, model_ids: list[str]) -> list[ModelTarget]:
    discovered = {item.id: item for item in discover_llamacpp_model_files(settings)}
    targets = []
    for model_id in model_ids:
        item = discovered.get(model_id)
        if item is None or not item.path or not item.profile:
            available = ", ".join(sorted(discovered)) or "none"
            raise SystemExit(f"Cannot resolve model '{model_id}'. Available discovered models: {available}")
        targets.append(ModelTarget(id=item.id, path=item.path, profile=item.profile))
    return targets


def configure_settings(
    settings: Settings,
    target: ModelTarget,
    out_dir: Path,
    base_url: str,
    thinking_level: str,
    n_gpu_layers: str,
) -> None:
    server_args = build_llamacpp_server_args(target.profile, alias=target.id)
    if str(thinking_level or "off").strip().lower() != "off":
        tokens = shlex.split(server_args)
        for index, token in enumerate(tokens[:-1]):
            if token == "--reasoning":
                tokens[index + 1] = "on"
                break
        server_args = shlex.join(tokens)
    if str(n_gpu_layers or "").strip():
        tokens = shlex.split(server_args)
        for index, token in enumerate(tokens[:-1]):
            if token == "-ngl":
                tokens[index + 1] = str(n_gpu_layers).strip()
                break
        server_args = shlex.join(tokens)
    object.__setattr__(settings, "llamacpp_base_url", base_url.rstrip("/"))
    object.__setattr__(settings, "llamacpp_model", target.id)
    object.__setattr__(settings, "llamacpp_model_path", target.path)
    object.__setattr__(settings, "llamacpp_server_args", server_args)
    object.__setattr__(settings, "llamacpp_log_path", str(out_dir / "llamacpp_server.log"))
    object.__setattr__(settings, "llamacpp_auto_start", True)


async def run_planner_eval(
    settings: Settings,
    target: ModelTarget,
    timeout_s: int,
    *,
    prompt_name: str,
    prompt: str,
    thinking_level: str,
) -> dict[str, Any]:
    service = HelperAIService(
        thread_cache=TTLCache(ttl_seconds=600, max_entries=8),
        pubmed_service=None,
        log_service=HelperLogService(Path("output/evals/research_agent_e2e/helper_log.jsonl")),
    )
    request = HelperChatRequest(
        message=prompt,
        model=f"llamacpp:{target.id}",
        mode="research_agent",
        thinking_level=thinking_level,
        research_planner_mode="staged",
        research_criteria_enabled=True,
    )
    events: list[dict[str, Any]] = []
    started = time.perf_counter()
    final_response: dict[str, Any] | None = None

    async def collect() -> None:
        nonlocal final_response
        async for event in service.chat_stream(request):
            compact = {
                "type": event.get("type"),
                "stage": ((event.get("action") or {}).get("details") or {}).get("stage"),
                "name": (event.get("action") or {}).get("name"),
                "elapsed_s": round(time.perf_counter() - started, 3),
            }
            if event.get("type") == "error":
                compact["message"] = event.get("message")
            events.append(compact)
            if event.get("type") == "final":
                final_response = dict(event.get("response") or {})

    try:
        await asyncio.wait_for(collect(), timeout=max(30, timeout_s))
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "events": events,
        }

    plan = extract_plan(final_response)
    query_blob = json.dumps(
        {
            "branches": (plan or {}).get("search_branches") or [],
            "shared": (plan or {}).get("shared_query_concepts") or [],
            "raw": (plan or {}).get("raw_search_queries") or [],
        },
        ensure_ascii=False,
    ).lower()
    stages = [event.get("stage") for event in events if event.get("type") == "tool_result" and event.get("stage")]
    series_metrics = dopamine_series_plan_metrics(plan)
    return {
        "prompt_name": prompt_name,
        "thinking_level": thinking_level,
        "ok": bool(plan),
        "elapsed_s": round(time.perf_counter() - started, 3),
        "stage_results": stages,
        "stage_count": len(stages),
        "tool_call_success": bool(plan),
        "plan_quality_score": plan_quality_score(plan, query_blob),
        "query_specificity_score": query_specificity_score(query_blob),
        "branch_count": len((plan or {}).get("search_branches") or []),
        "criteria_count": len((plan or {}).get("screening_criteria") or []),
        "question_count": len((plan or {}).get("extraction_questions") or []),
        "has_nanoplastic": "nanoplastic" in query_blob or "microplastic" in query_blob,
        "has_dopamine": "dopamine" in query_blob or "dopaminergic" in query_blob,
        "dopamine_series_metrics": series_metrics,
        "events": events[-80:],
        "plan": plan,
    }


async def run_screening_eval(
    settings: Settings,
    target: ModelTarget,
    batch_sizes: list[int],
    *,
    thinking_level: str,
) -> list[dict[str, Any]]:
    rows = []
    service = ResearchScreeningService(settings=settings)
    original_batch_size = screening_module.BATCH_SIZE
    try:
        for batch_size in batch_sizes:
            screening_module.BATCH_SIZE = max(1, batch_size)
            started = time.perf_counter()
            progress_events: list[dict[str, Any]] = []

            async def progress(event: dict[str, Any]) -> None:
                progress_events.append(dict(event))

            try:
                traces = await service.screen_candidates(
                    fixture_candidates(),
                    SCREENING_PLAN,
                    model=f"llamacpp:{target.id}",
                    thinking_level=thinking_level,
                    progress=progress,
                )
                error = ""
            except Exception as exc:
                traces = []
                error = f"{type(exc).__name__}: {exc}"
            elapsed_s = round(time.perf_counter() - started, 3)
            trace_by_id = {item.candidate_id: item for item in traces}
            scores = {item.candidate_id: item.final_score for item in traces}
            sorted_ids = [item.candidate_id for item in sorted(traces, key=lambda item: item.final_score, reverse=True)]
            relevant = trace_by_id.get("cand_1")
            review = trace_by_id.get("cand_2")
            unrelated = trace_by_id.get("cand_3")
            valid_output = len(traces) == 3 and not error
            relevant_selected = bool(relevant and relevant.final_score >= 0.5 and not relevant.excluded)
            review_rejected = bool(review and (review.excluded or review.final_score < 0.5))
            unrelated_rejected = bool(unrelated and (unrelated.excluded or unrelated.final_score < 0.5))
            ranking_ok = bool(sorted_ids and sorted_ids[0] == "cand_1")
            score = sum([valid_output, relevant_selected, review_rejected, unrelated_rejected, ranking_ok]) / 5
            rows.append(
                {
                    "batch_size": batch_size,
                    "scenario": "residue_triage",
                    "thinking_level": thinking_level,
                    "ok": score >= 0.8,
                    "score": round(score, 3),
                    "elapsed_s": elapsed_s,
                    "error": error,
                    "trace_count": len(traces),
                    "relevant_selected": relevant_selected,
                    "review_rejected": review_rejected,
                    "unrelated_rejected": unrelated_rejected,
                    "ranking_ok": ranking_ok,
                    "scores": scores,
                    "excluded": {item.candidate_id: item.excluded for item in traces},
                    "evidence": {item.candidate_id: item.evidence for item in traces},
                    "progress_stages": [event.get("stage") for event in progress_events],
                }
            )
    finally:
        screening_module.BATCH_SIZE = original_batch_size
    return rows


async def run_dopamine_series_screening_eval(
    settings: Settings,
    target: ModelTarget,
    batch_sizes: list[int],
    *,
    thinking_level: str,
) -> list[dict[str, Any]]:
    rows = []
    service = ResearchScreeningService(settings=settings)
    original_batch_size = screening_module.BATCH_SIZE
    expected_selected = {f"series_{index}" for index in range(1, 6)}
    expected_rejected = {"series_6", "series_7", "series_8"}
    try:
        for batch_size in batch_sizes:
            screening_module.BATCH_SIZE = max(1, batch_size)
            started = time.perf_counter()
            progress_events: list[dict[str, Any]] = []

            async def progress(event: dict[str, Any]) -> None:
                progress_events.append(dict(event))

            try:
                traces = await service.screen_candidates(
                    dopamine_series_candidates(),
                    DOPAMINE_SERIES_PLAN,
                    model=f"llamacpp:{target.id}",
                    thinking_level=thinking_level,
                    progress=progress,
                )
                error = ""
            except Exception as exc:
                traces = []
                error = f"{type(exc).__name__}: {exc}"
            elapsed_s = round(time.perf_counter() - started, 3)
            trace_by_id = {item.candidate_id: item for item in traces}
            candidate_by_id = {item.candidate_id: item for item in dopamine_series_candidates()}
            selected_ids = {
                item.candidate_id
                for item in traces
                if item.final_score >= 0.5 and not item.excluded
            }
            rejected_ids = {
                item.candidate_id
                for item in traces
                if item.excluded or item.final_score < 0.5
            }
            receptor_hits = {
                receptor: any(
                    receptor in " ".join(
                        [
                            candidate_by_id[candidate_id].article.title,
                            candidate_by_id[candidate_id].article.abstract or "",
                            " ".join(trace_by_id[candidate_id].evidence),
                        ]
                    ).lower()
                    for candidate_id in expected_selected
                    if candidate_id in trace_by_id
                )
                for receptor in ["d1", "d2", "d3", "d4", "d5"]
            }
            valid_output = len(traces) == 8 and not error
            selected_coverage = len(expected_selected & selected_ids) / len(expected_selected)
            rejection_coverage = len(expected_rejected & rejected_ids) / len(expected_rejected)
            no_false_positive = selected_ids <= expected_selected
            receptor_coverage = sum(receptor_hits.values()) / len(receptor_hits)
            criterion_score_coverage = (
                sum(1 for item in traces if item.criterion_scores) / len(traces)
                if traces
                else 0.0
            )
            evidence_coverage = (
                sum(1 for item in traces if item.evidence) / len(traces)
                if traces
                else 0.0
            )
            rationale_coverage = (
                sum(1 for item in traces if str(item.rationale or "").strip()) / len(traces)
                if traces
                else 0.0
            )
            score = (
                float(valid_output)
                + selected_coverage
                + rejection_coverage
                + float(no_false_positive)
                + receptor_coverage
                + criterion_score_coverage
                + evidence_coverage
                + rationale_coverage
            ) / 8
            rows.append(
                {
                    "batch_size": batch_size,
                    "scenario": "dopamine_d1_d5_series",
                    "thinking_level": thinking_level,
                    "ok": score >= 0.85,
                    "score": round(score, 3),
                    "elapsed_s": elapsed_s,
                    "error": error,
                    "trace_count": len(traces),
                    "selected_ids": sorted(selected_ids),
                    "rejected_ids": sorted(rejected_ids),
                    "selected_coverage": round(selected_coverage, 3),
                    "rejection_coverage": round(rejection_coverage, 3),
                    "no_false_positive": no_false_positive,
                    "receptor_hits": receptor_hits,
                    "receptor_coverage": round(receptor_coverage, 3),
                    "criterion_score_coverage": round(criterion_score_coverage, 3),
                    "evidence_coverage": round(evidence_coverage, 3),
                    "rationale_coverage": round(rationale_coverage, 3),
                    "scores": {item.candidate_id: item.final_score for item in traces},
                    "excluded": {item.candidate_id: item.excluded for item in traces},
                    "evidence": {item.candidate_id: item.evidence for item in traces},
                    "rationale": {item.candidate_id: item.rationale for item in traces},
                    "progress_stages": [event.get("stage") for event in progress_events],
                }
            )
    finally:
        screening_module.BATCH_SIZE = original_batch_size
    return rows


async def run_full_execution_eval(
    settings: Settings,
    target: ModelTarget,
    out_dir: Path,
    *,
    use_pdf_model: bool,
    thinking_level: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    pubmed = EvalPubMedService()
    execution_service = ResearchExecutionService(
        pubmed_service=pubmed,  # type: ignore[arg-type]
        screening_service=ResearchScreeningService(settings=settings),
    )
    pdf_service = EvalPDFService(out_dir / "pdf_artifacts")
    pipeline = ResearchPdfPipelineService(
        extraction_service=PDFExtractionService(pdf_service=pdf_service, settings=settings)
    )
    payload = ResearchPlanExecuteRequest(
        plan=SCREENING_PLAN,
        screening_model=f"llamacpp:{target.id}",
        criteria_enabled=True,
        pdf_extractor_enabled=True,
        autoprocess=True,
        pdf_scope="selected",
        full_text_model=f"llamacpp:{target.id}" if use_pdf_model else "",
        thinking_level=thinking_level,
    )
    plan = build_execution_plan(payload)
    progress_events: list[dict[str, Any]] = []

    async def progress(event: dict[str, Any]) -> None:
        progress_events.append(dict(event))

    try:
        response = await execution_service.execute_plan_with_screening(
            plan,
            screening_model=payload.screening_model,
            thinking_level=payload.thinking_level,
            progress=progress,
        )
        await pipeline.run_pdf_screening(payload, plan, response, progress=progress)
        error = ""
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "progress_stages": [event.get("stage") for event in progress_events],
        }
    pdf_screening = response.run_trace.meta.get("pdf_screening") or {}
    answers_text = json.dumps(pdf_screening, ensure_ascii=False).lower()
    selected_ok = response.run_trace.selected_candidate_ids[:1] == ["cand_1"]
    pdf_ok = "alpha123" in answers_text and int(pdf_screening.get("success_count") or 0) >= 1
    return {
        "ok": selected_ok and pdf_ok,
        "elapsed_s": round(time.perf_counter() - started, 3),
        "error": error,
        "selected_candidate_ids": response.run_trace.selected_candidate_ids,
        "backup_candidate_ids": response.run_trace.backup_candidate_ids,
        "excluded_candidate_ids": response.run_trace.excluded_candidate_ids,
        "run_status": response.run_trace.status,
        "stage_statuses": response.run_trace.meta.get("stage_statuses"),
        "screening_status": response.run_trace.meta.get("screening_status"),
        "pdf_success_count": pdf_screening.get("success_count"),
        "pdf_failed_count": pdf_screening.get("failed_count"),
        "pdf_contains_alpha123": "alpha123" in answers_text,
        "download_calls": pdf_service.download_calls,
        "progress_stages": [event.get("stage") for event in progress_events],
        "screening": [item.model_dump(mode="json") for item in response.run_trace.screening],
        "pdf_screening": pdf_screening,
    }


async def run_model_eval(args: argparse.Namespace, settings: Settings, target: ModelTarget, batch_sizes: list[int]) -> dict[str, Any]:
    model_out = Path(args.out) / safe_name(target.id)
    model_out.mkdir(parents=True, exist_ok=True)
    configure_settings(settings, target, model_out, args.base_url, args.thinking_level, args.n_gpu_layers)
    stop_local_llamacpp_servers(args.base_url)
    await ensure_llamacpp_ready(
        settings,
        model=target.id,
        request_user_agent=settings.request_user_agent,
        timeout_seconds=180.0,
    )
    started = time.perf_counter()
    try:
        planner_evals = (
            [{"skipped": True, "prompt_name": "skipped", "thinking_level": args.thinking_level}]
            if args.skip_planner
            else [
                await run_planner_eval(
                    settings,
                    target,
                    args.planner_timeout_s,
                    prompt_name="nanoplastic_dopamine",
                    prompt=DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT,
                    thinking_level=args.thinking_level,
                ),
                await run_planner_eval(
                    settings,
                    target,
                    args.planner_timeout_s,
                    prompt_name="dopamine_d1_d5_series",
                    prompt=DOPAMINE_SERIES_PROMPT,
                    thinking_level=args.thinking_level,
                ),
            ]
        )
        screening = await run_screening_eval(settings, target, batch_sizes, thinking_level=args.thinking_level)
        dopamine_series_screening = await run_dopamine_series_screening_eval(
            settings,
            target,
            batch_sizes,
            thinking_level=args.thinking_level,
        )
        full_execution = await run_full_execution_eval(
            settings,
            target,
            model_out,
            use_pdf_model=not args.skip_pdf_model,
            thinking_level=args.thinking_level,
        )
        result = {
            "model": target.id,
            "path": target.path,
            "profile": target.profile,
            "thinking_level": args.thinking_level,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "elapsed_s": round(time.perf_counter() - started, 3),
            "planner": planner_evals[0],
            "planner_evals": planner_evals,
            "screening": screening,
            "dopamine_series_screening": dopamine_series_screening,
            "full_execution": full_execution,
        }
        (model_out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        stop_local_llamacpp_servers(args.base_url)


def extract_plan(final_response: dict[str, Any] | None) -> dict[str, Any] | None:
    for action in (final_response or {}).get("executed_actions") or []:
        if action.get("name") == "create_research_plan":
            plan = (action.get("details") or {}).get("plan")
            return dict(plan) if isinstance(plan, dict) else None
    return None


def dopamine_series_plan_metrics(plan: dict[str, Any] | None) -> dict[str, Any]:
    if not plan:
        return {
            "series_coverage": 0.0,
            "branch_count": 0,
            "covered_receptors": [],
            "has_database_specific_warning": False,
            "field_question_coverage": 0.0,
        }
    branches = plan.get("search_branches") or []
    branch_text = json.dumps(branches, ensure_ascii=False).lower()
    covered = [
        receptor
        for receptor in ["d1", "d2", "d3", "d4", "d5"]
        if receptor in branch_text or f"drd{receptor[-1]}" in branch_text
    ]
    questions = " ".join(str(item) for item in (plan.get("extraction_questions") or [])).lower()
    field_terms = [
        ("subtype", "receptor"),
        ("ligand", "perturbation"),
        ("assay", "model"),
        ("endpoint", "pathway"),
        ("effect", "direction"),
        ("quote", "evidence"),
        ("uncertainty", "confidence"),
    ]
    field_hits = sum(any(term in questions for term in group) for group in field_terms)
    query_text = json.dumps(
        {
            "branches": branches,
            "shared_query_concepts": plan.get("shared_query_concepts") or [],
            "raw_search_queries": plan.get("raw_search_queries") or [],
        },
        ensure_ascii=False,
    ).lower()
    has_database_specific_warning = any(
        token in query_text
        for token in ["[tiab]", "mesh", "title-abs-key", "ts=("]
    )
    return {
        "series_coverage": round(len(set(covered)) / 5, 3),
        "branch_count": len(branches),
        "covered_receptors": sorted(set(covered)),
        "has_database_specific_warning": has_database_specific_warning,
        "field_question_coverage": round(field_hits / len(field_terms), 3),
    }


def write_summary(out_dir: Path, results: list[dict[str, Any]]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "e2e_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "screening_batches.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "model",
                "scenario",
                "thinking_level",
                "batch_size",
                "ok",
                "score",
                "elapsed_s",
                "trace_count",
                "relevant_selected",
                "review_rejected",
                "unrelated_rejected",
                "ranking_ok",
                "selected_coverage",
                "rejection_coverage",
                "receptor_coverage",
                "criterion_score_coverage",
                "evidence_coverage",
                "rationale_coverage",
                "error",
            ],
        )
        writer.writeheader()
        for result in results:
            for row in [*(result.get("screening") or []), *(result.get("dopamine_series_screening") or [])]:
                writer.writerow({key: row.get(key) for key in writer.fieldnames} | {"model": result["model"]})
    lines = [
        "# Research Agent E2E Eval",
        "",
        f"Created: {datetime.now(UTC).replace(microsecond=0).isoformat()}",
        "",
        "## Summary",
        "",
    ]
    for result in results:
        planner_evals = result.get("planner_evals") or [result.get("planner") or {}]
        full = result.get("full_execution") or {}
        best_batch = best_screening_batch(result.get("screening") or [])
        best_series_batch = best_screening_batch(result.get("dopamine_series_screening") or [])
        lines.extend(
            [
                f"### {result['model']}",
                "",
                f"- Profile: `{result.get('profile')}`",
                f"- Thinking level: `{result.get('thinking_level')}`",
                *[
                    (
                        f"- Planner `{planner.get('prompt_name')}`: ok=`{planner.get('ok')}` "
                        f"elapsed=`{planner.get('elapsed_s')}` score=`{planner.get('plan_quality_score')}` "
                        f"series_coverage=`{(planner.get('dopamine_series_metrics') or {}).get('series_coverage')}`"
                    )
                    for planner in planner_evals
                ],
                f"- Best residue triage batch: `{best_batch.get('batch_size')}` score=`{best_batch.get('score')}` elapsed=`{best_batch.get('elapsed_s')}`",
                f"- Best D1-D5 screening batch: `{best_series_batch.get('batch_size')}` score=`{best_series_batch.get('score')}` elapsed=`{best_series_batch.get('elapsed_s')}`",
                f"- Full execution: ok=`{full.get('ok')}` elapsed=`{full.get('elapsed_s')}` selected=`{full.get('selected_candidate_ids')}` pdf_alpha123=`{full.get('pdf_contains_alpha123')}`",
                "",
            ]
        )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def best_screening_batch(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return sorted(rows, key=lambda item: (float(item.get("score") or 0), -float(item.get("elapsed_s") or 9999)), reverse=True)[0]


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value).strip("_")


async def main() -> None:
    args = parse_args()
    model_ids = [item.strip() for item in args.models.split(",") if item.strip()]
    batch_sizes = [int(item) for item in args.batch_sizes.split(",") if item.strip()]
    out_dir = Path(args.out)
    settings = get_settings()
    targets = resolve_targets(settings, model_ids)
    results = []
    for target in targets:
        print(f"Running Research Agent e2e eval for {target.id} ({target.profile})")
        result = await run_model_eval(args, settings, target, batch_sizes)
        results.append(result)
        planner = result.get("planner") or {}
        full = result.get("full_execution") or {}
        print(
            f"{target.id}: planner_ok={planner.get('ok')} full_ok={full.get('ok')} "
            f"best_batch={best_screening_batch(result.get('screening') or []).get('batch_size')}"
        )
    write_summary(out_dir, results)
    print(f"Wrote Research Agent e2e eval outputs to {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
