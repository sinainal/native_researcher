from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import get_settings
from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.services.research_plan_benchmark import (
    BenchmarkConfig,
    BenchmarkModelSpec,
    ResearchPlanBenchmarkRunner,
    approximate_token_count,
    article_relevance_heuristics,
    parse_model_specs,
    parse_llamacpp_engine_metrics,
    query_validity_metrics,
    stream_metrics,
    thinking_metrics,
)


def test_parse_model_specs_supports_thinking_and_labels() -> None:
    specs = parse_model_specs(
        [
            "llamacpp:gemma|think=off|label=gemma_off,"
            "ollama:qwen3.6:35b|thinking=on|label=qwen_on"
        ]
    )

    assert [spec.model for spec in specs] == ["llamacpp:gemma", "ollama:qwen3.6:35b"]
    assert [spec.thinking_level for spec in specs] == ["off", "on"]
    assert [spec.run_id for spec in specs] == ["gemma_off", "qwen_on"]


def test_article_relevance_heuristics_detects_target_groups() -> None:
    article = Article(
        id=1,
        pmid="1",
        title="Nanoplastics alter dopamine receptor signaling",
        abstract="Polystyrene nanoplastic exposure changed dopaminergic pathway expression and oxidative stress.",
        year="2024",
    )

    result = article_relevance_heuristics(article)

    assert result["all_groups_present"] is True
    assert result["matched_group_count"] == 3
    assert result["relevance_score"] == 1.0


def test_query_validity_metrics_flags_broken_queries() -> None:
    result = query_validity_metrics(
        [
            {"index": 1, "query": 'nanoplastic AND "dopamine receptor"', "error": ""},
            {"index": 2, "query": 'nanoplastic AND ("dopamine"', "error": ""},
            {"index": 3, "query": "nanoplastic OR", "error": "HTTPStatusError"},
        ]
    )

    assert result["valid_query_count"] == 1
    assert result["invalid_query_count"] == 2
    assert result["query_validity_score"] == 0.333
    assert result["issues"]


def test_parse_llamacpp_engine_metrics_reads_eval_tps(tmp_path) -> None:
    log_path = tmp_path / "llamacpp.log"
    log_path.write_text(
        """
prompt eval time =     234.36 ms /    25 tokens (    9.37 ms per token,   106.67 tokens per second)
       eval time =    2919.89 ms /   160 tokens (   18.25 ms per token,    54.80 tokens per second)
prompt eval time =     260.44 ms /    31 tokens (    8.40 ms per token,   119.03 tokens per second)
       eval time =    4866.14 ms /   220 tokens (   22.12 ms per token,    45.21 tokens per second)
""",
        encoding="utf-8",
    )

    result = parse_llamacpp_engine_metrics(log_path)

    assert result["available"] is True
    assert result["request_count"] == 2
    assert result["eval"]["last_tps"] == 45.21
    assert result["eval"]["max_tps"] == 54.8
    assert result["prompt_eval"]["average_tps"] == 112.85


def test_stream_metrics_reports_stall_gaps() -> None:
    result = stream_metrics(
        [
            {"elapsed_s": 0.0},
            {"elapsed_s": 2.0},
            {"elapsed_s": 22.5},
            {"elapsed_s": 23.0},
        ],
        threshold_s=10.0,
    )

    assert result["max_event_gap_s"] == 20.5
    assert result["stall_gap_count"] == 1
    assert result["stall_gaps_s"] == [20.5]


def test_thinking_metrics_counts_without_saving_content() -> None:
    result = thinking_metrics(["one two three four", " plus more"], thinking_level="off", leaked_think_tag_chunks=1)

    assert result["thinking_delta_count"] == 2
    assert result["thinking_chars"] > 0
    assert result["approx_thinking_tokens"] == approximate_token_count("one two three four plus more")
    assert result["leaked_think_tag_chunks"] == 1
    assert result["content_saved"] is False


class FakeHelperService:
    async def chat_stream(self, _request: Any):
        plan = {
            "topic": "nanoplastics dopamine",
            "objective": "Find nanoplastic dopamine interaction studies",
            "active_databases": ["PubMed"],
            "year_start": 2020,
            "year_end": 2026,
            "search_branches": [
                {"id": "b1", "label": "Dopamine receptors", "query": "nanoplastics dopamine receptor"},
                {"id": "b2", "label": "Dopaminergic signaling", "query": "microplastics dopaminergic signaling"},
            ],
            "shared_query_concepts": [{"id": "c1", "label": "Mechanism", "query": "binding OR signaling OR oxidative"}],
            "candidate_budget": {"per_database": 2},
        }
        yield {"type": "start"}
        yield {
            "type": "tool_call",
            "action": {"name": "create_research_plan", "details": {"stage": "merged"}},
        }
        yield {
            "type": "tool_result",
            "action": {"name": "create_research_plan", "details": {"plan": plan, "stage": "merged"}},
        }
        yield {"type": "thinking_delta", "text": "private reasoning text"}
        yield {"type": "final", "response": {"executed_actions": [{"name": "create_research_plan", "details": {"plan": plan}}]}}


class FakePubMedService:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search(self, request: Any) -> PubMedSearchResponse:
        self.queries.append(request.query)
        article_id = len(self.queries)
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=request.query,
                total_results_found=10,
                fetched_results=1,
                batch_size_used=1,
                request_count=1,
                elapsed_ms=12,
                cache_hit=False,
                primary_source=request.preferred_source,
            ),
            articles=[
                Article(
                    id=article_id,
                    pmid=str(article_id),
                    title=f"Nanoplastic dopamine signaling study {article_id}",
                    abstract="Dopaminergic pathway interaction and oxidative stress after polystyrene nanoplastic exposure.",
                    year="2024",
                )
            ],
        )


class FastBenchmarkRunner(ResearchPlanBenchmarkRunner):
    async def _model_preflight(self, spec: BenchmarkModelSpec) -> dict[str, Any]:
        return {"ok": True, "provider": "ollama", "model_name": spec.model, "elapsed_s": 0.001, "models": [spec.model]}

    async def _tps_probe(self, spec: BenchmarkModelSpec, *, max_tokens: int) -> dict[str, Any]:
        return {"ok": True, "provider": "ollama", "elapsed_s": 1.0, "completion_tokens": max_tokens, "approx_tps": max_tokens}


def test_benchmark_runner_writes_plan_and_probes_all_queries(tmp_path) -> None:
    asyncio.run(_run_benchmark_runner_writes_plan_and_probes_all_queries(tmp_path))


async def _run_benchmark_runner_writes_plan_and_probes_all_queries(tmp_path) -> None:
    pubmed = FakePubMedService()
    runner = FastBenchmarkRunner(
        helper_service=FakeHelperService(),
        pubmed_service=pubmed,  # type: ignore[arg-type]
        settings=get_settings(),
    )

    payload = await runner.run(
        BenchmarkConfig(
            models=[BenchmarkModelSpec(model="ollama:test", thinking_level="off", label="test")],
            max_articles=1,
            per_query_limit=1,
            max_queries=2,
            databases=["PubMed"],
            out_dir=tmp_path,
        )
    )

    run = payload["runs"][0]
    assert run["status"] == "success"
    assert run["tool_call_success"] is True
    assert run["article_pull"]["metrics"]["executed_query_count"] == 2
    assert run["article_pull"]["metrics"]["unique_article_count"] == 1
    assert run["article_pull"]["metrics"]["average_article_relevance_score"] == 1.0
    assert run["quality_metrics"]["overall_score"] > 0
    assert run["thinking_metrics"]["thinking_delta_count"] == 1
    assert run["thinking_metrics"]["approx_thinking_tokens"] > 0
    assert all(event.get("text") != "private reasoning text" for event in run["events"])
    assert len(pubmed.queries) == 2
    assert (tmp_path / "benchmark.json").exists()
    assert (tmp_path / "summary.md").exists()
    assert (tmp_path / "articles.csv").exists()
