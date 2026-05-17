"""Benchmark research planning against real article pulls."""

from __future__ import annotations

import asyncio
import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.clients.ncbi import NcbiClient
from app.core.config import Settings, get_settings
from app.llm import resolve_chat_model_target
from app.schemas.article import Article
from app.schemas.helper import HelperChatRequest
from app.schemas.pubmed import PubMedSearchRequest
from app.services.agent.helper_ai_service import HelperAIService
from app.services.helper_log_service import HelperLogService
from app.services.pubmed_service import PubMedService
from app.services.research_execution_service import ResearchExecutionService
from app.utils.cache import TTLCache

DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT = (
    "Create the best research plan to find real papers about nanoplastics or microplastics "
    "and dopamine D-series receptors/signaling. We want papers that can later answer: in "
    "nanoplastic-related studies, what dopamine D receptor or dopaminergic interactions, "
    "binding/signaling effects, cellular effects, oxidative stress, neurotoxicity, or pathway "
    "changes were observed? Prefer queries likely to retrieve primary studies and mechanistic "
    "evidence. Do not execute screening or PDF analysis in planning."
)

NANOPLASTIC_TERMS = {
    "nanoplastic",
    "nanoplastics",
    "microplastic",
    "microplastics",
    "polystyrene",
    "plastic particle",
    "plastic particles",
    "nano-plastic",
    "micro-plastic",
}
DOPAMINE_TERMS = {
    "dopamine",
    "dopaminergic",
    "dopamine receptor",
    "d1 receptor",
    "d2 receptor",
    "d3 receptor",
    "d4 receptor",
    "d5 receptor",
    "drd1",
    "drd2",
    "drd3",
    "drd4",
    "drd5",
}
INTERACTION_TERMS = {
    "interaction",
    "binding",
    "signaling",
    "pathway",
    "neurotoxicity",
    "oxidative",
    "inflammation",
    "expression",
    "uptake",
    "transport",
    "behavior",
}


@dataclass
class BenchmarkModelSpec:
    model: str
    thinking_level: str = "off"
    label: str | None = None

    @property
    def run_id(self) -> str:
        raw = self.label or f"{self.model}_{self.thinking_level}"
        return "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_").lower()


@dataclass
class BenchmarkConfig:
    prompt: str = DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT
    models: list[BenchmarkModelSpec] = field(default_factory=list)
    max_articles: int = 5
    per_query_limit: int = 5
    max_queries: int = 8
    databases: list[str] | None = None
    criteria_enabled: bool = True
    planner_mode: str = "staged"
    out_dir: Path = Path("output/benchmarks/research_plan")
    api_key: str = ""
    tps_probe_tokens: int = 220
    stall_gap_threshold_s: float = 15.0
    require_preflight: bool = True
    llamacpp_log_path: Path | None = None


class ResearchPlanBenchmarkRunner:
    def __init__(
        self,
        *,
        helper_service: HelperAIService,
        pubmed_service: PubMedService,
        settings: Settings,
    ) -> None:
        self.helper_service = helper_service
        self.pubmed_service = pubmed_service
        self.settings = settings
        self.execution_service = ResearchExecutionService(pubmed_service=pubmed_service)

    async def run(self, config: BenchmarkConfig) -> dict[str, Any]:
        started_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        config.out_dir.mkdir(parents=True, exist_ok=True)
        runs = []
        for spec in config.models:
            runs.append(await self.run_model(config, spec))
        payload = {
            "created_at": started_at,
            "prompt": config.prompt,
            "config": {
                "max_articles": config.max_articles,
                "per_query_limit": config.per_query_limit,
                "max_queries": config.max_queries,
                "databases": config.databases or [],
                "criteria_enabled": config.criteria_enabled,
                "planner_mode": config.planner_mode,
                "llamacpp_log_path": str(config.llamacpp_log_path) if config.llamacpp_log_path else "",
            },
            "runs": runs,
            "engine_metrics": parse_llamacpp_engine_metrics(config.llamacpp_log_path),
            "comparison": self._comparison(runs),
        }
        self.write_outputs(config.out_dir, payload)
        return payload

    async def run_model(self, config: BenchmarkConfig, spec: BenchmarkModelSpec) -> dict[str, Any]:
        run_started = time.perf_counter()
        events: list[dict[str, Any]] = []
        stage_timings: dict[str, dict[str, float | None]] = {}
        errors: list[str] = []
        final_response: dict[str, Any] | None = None
        preflight = await self._model_preflight(spec)
        thinking_chunks: list[str] = []
        leaked_think_tag_chunks = 0

        request = HelperChatRequest(
            message=config.prompt,
            model=spec.model,
            mode="research_agent",
            thinking_level=spec.thinking_level,
            research_planner_mode=config.planner_mode,
            research_criteria_enabled=config.criteria_enabled,
            api_key=config.api_key,
        )
        plan_start = time.perf_counter()
        if config.require_preflight and not preflight.get("ok"):
            errors.append(str(preflight.get("error") or "Model preflight failed."))
        else:
            try:
                async for event in self.helper_service.chat_stream(request):
                    now = time.perf_counter()
                    event_type = str(event.get("type") or "")
                    compact = {
                        "type": event_type,
                        "elapsed_s": round(now - plan_start, 3),
                        "stage": ((event.get("action") or {}).get("details") or {}).get("stage"),
                        "name": (event.get("action") or {}).get("name"),
                        "text": "" if event_type == "thinking_delta" else event.get("text") or "",
                    }
                    if event_type == "thinking_delta":
                        thinking_text = str(event.get("text") or "")
                        thinking_chunks.append(thinking_text)
                        compact["text_chars"] = len(thinking_text)
                        compact["approx_tokens"] = approximate_token_count(thinking_text)
                    elif event_type == "answer_delta" and "<think" in str(event.get("text") or "").lower():
                        leaked_think_tag_chunks += 1
                    events.append(compact)
                    if event_type == "tool_call":
                        stage = str(compact.get("stage") or compact.get("name") or "unknown")
                        stage_timings.setdefault(stage, {"start_s": round(now - plan_start, 3), "end_s": None})
                    elif event_type == "tool_result":
                        stage = str(compact.get("stage") or compact.get("name") or "unknown")
                        stage_timings.setdefault(stage, {"start_s": None, "end_s": None})["end_s"] = round(now - plan_start, 3)
                    elif event_type == "error":
                        errors.append(str(event.get("message") or event))
                    elif event_type == "final":
                        final_response = dict(event.get("response") or {})
                        final_thinking = str(final_response.get("thinking") or "")
                        if final_thinking and not thinking_chunks:
                            thinking_chunks.append(final_thinking)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

        planning_elapsed = time.perf_counter() - plan_start
        plan = self._extract_plan(final_response)
        plan_metrics = self._plan_metrics(plan)
        pull = await self._pull_articles(plan, config) if plan else {"queries": [], "articles": [], "metrics": {}}
        quality_metrics = benchmark_quality_metrics(plan_metrics, pull)
        tps_probe = (
            await self._tps_probe(spec, max_tokens=config.tps_probe_tokens)
            if preflight.get("ok")
            else {"ok": False, "error": "Skipped because model preflight failed."}
        )
        status = "success" if plan and not errors else "error"

        return {
            "run_id": spec.run_id,
            "model": spec.model,
            "thinking_level": spec.thinking_level,
            "label": spec.label or "",
            "status": status,
            "preflight": preflight,
            "total_elapsed_s": round(time.perf_counter() - run_started, 3),
            "planning_elapsed_s": round(planning_elapsed, 3),
            "tool_call_success": bool(plan),
            "errors": errors,
            "events": events,
            "stream_metrics": stream_metrics(events, threshold_s=config.stall_gap_threshold_s),
            "thinking_metrics": thinking_metrics(
                thinking_chunks,
                thinking_level=spec.thinking_level,
                leaked_think_tag_chunks=leaked_think_tag_chunks,
            ),
            "stage_timings": self._finish_stage_timings(stage_timings),
            "plan": plan,
            "plan_metrics": plan_metrics,
            "article_pull": pull,
            "quality_metrics": quality_metrics,
            "tps_probe": tps_probe,
        }

    async def _pull_articles(self, plan: dict[str, Any], config: BenchmarkConfig) -> dict[str, Any]:
        raw_queries = self.execution_service._raw_search_queries(plan)[: config.max_queries]
        if config.databases:
            allowed = {normalize_database_name(item) for item in config.databases}
            raw_queries = [
                item
                for item in raw_queries
                if normalize_database_name(str(item.get("database") or item.get("source") or "")) in allowed
            ]
        queries: list[dict[str, Any]] = []
        articles: list[dict[str, Any]] = []
        seen: set[str] = set()
        duplicate_count = 0
        for index, raw_query in enumerate(raw_queries, start=1):
            database = normalize_database_name(str(raw_query.get("database") or raw_query.get("source") or "pubmed"))
            limit = config.per_query_limit
            started = time.perf_counter()
            error = ""
            response_articles: list[Article] = []
            total_found = 0
            request_count = 0
            try:
                response = await self.pubmed_service.search(
                    PubMedSearchRequest(
                        query=str(raw_query.get("query") or "").strip(),
                        year_start=optional_int(plan.get("year_start")),
                        year_end=optional_int(plan.get("year_end")),
                        max_results=limit,
                        use_cache=True,
                        preferred_source=database,  # type: ignore[arg-type]
                    )
                )
                response_articles = response.articles
                total_found = response.meta.total_results_found
                request_count = response.meta.request_count
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            elapsed_s = round(time.perf_counter() - started, 3)
            queries.append(
                {
                    "index": index,
                    "database": database,
                    "branch_label": raw_query.get("branch_label") or "",
                    "query": raw_query.get("query") or "",
                    "candidate_limit": limit,
                    "elapsed_s": elapsed_s,
                    "fetched_results": len(response_articles),
                    "total_results_found": total_found,
                    "request_count": request_count,
                    "error": error,
                }
            )
            for article in response_articles:
                key = article_key(article)
                if key in seen:
                    duplicate_count += 1
                    continue
                seen.add(key)
                if len(articles) >= config.max_articles:
                    continue
                row = article.model_dump(mode="json")
                row["matched_query_index"] = index
                row["matched_database"] = database
                row["matched_branch_label"] = raw_query.get("branch_label") or ""
                row["heuristics"] = article_relevance_heuristics(article)
                articles.append(row)
                if len(articles) >= config.max_articles:
                    break
        return {
            "queries": queries,
            "articles": articles,
            "metrics": {
                "raw_query_count": len(raw_queries),
                "executed_query_count": len(queries),
                "unique_article_count": len(articles),
                "duplicate_article_count": duplicate_count,
                "relevant_title_abstract_hits": sum(1 for item in articles if item["heuristics"]["all_groups_present"]),
                "partial_relevance_hits": sum(1 for item in articles if item["heuristics"]["matched_group_count"] >= 2),
                "total_query_elapsed_s": round(sum(float(item["elapsed_s"]) for item in queries), 3),
                "query_error_count": sum(1 for item in queries if item.get("error")),
                "average_article_relevance_score": round(
                    sum(float((item.get("heuristics") or {}).get("relevance_score") or 0.0) for item in articles) / len(articles),
                    3,
                )
                if articles
                else 0.0,
            },
        }

    async def _model_preflight(self, spec: BenchmarkModelSpec) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            target = resolve_chat_model_target(spec.model, settings=self.settings)
        except Exception as exc:
            return {"ok": False, "elapsed_s": 0.0, "error": f"{type(exc).__name__}: {exc}"}
        try:
            if target.provider == "llamacpp":
                async with httpx.AsyncClient(
                    base_url=str(getattr(self.settings, "llamacpp_base_url", "http://localhost:8098") or "http://localhost:8098"),
                    timeout=httpx.Timeout(4.0, connect=2.0),
                    follow_redirects=True,
                ) as client:
                    response = await client.get("/health")
                    if response.status_code >= 500:
                        response.raise_for_status()
                    models_response = await client.get("/v1/models")
                    models = []
                    if models_response.status_code < 400:
                        models_payload = models_response.json() or {}
                        models = [str(item.get("id") or "") for item in models_payload.get("data") or [] if isinstance(item, dict)]
                return {
                    "ok": True,
                    "provider": target.provider,
                    "model_name": target.model_name,
                    "elapsed_s": round(time.perf_counter() - started, 3),
                    "models": models,
                }
            if target.provider == "ollama":
                async with httpx.AsyncClient(
                    base_url=str(getattr(self.settings, "ollama_base_url", "http://localhost:11434") or "http://localhost:11434"),
                    timeout=httpx.Timeout(4.0, connect=2.0),
                    follow_redirects=True,
                ) as client:
                    response = await client.get("/api/tags")
                    response.raise_for_status()
                    payload = response.json() or {}
                models = [str(item.get("name") or "") for item in payload.get("models") or [] if isinstance(item, dict)]
                return {
                    "ok": True,
                    "provider": target.provider,
                    "model_name": target.model_name,
                    "elapsed_s": round(time.perf_counter() - started, 3),
                    "models": models,
                }
            return {
                "ok": True,
                "provider": target.provider,
                "model_name": target.model_name,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "models": [],
                "note": "Preflight is connectivity-only for this provider.",
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": target.provider,
                "model_name": target.model_name,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }

    async def _tps_probe(self, spec: BenchmarkModelSpec, *, max_tokens: int) -> dict[str, Any]:
        try:
            target = resolve_chat_model_target(spec.model, settings=self.settings)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        prompt = "Write exactly 160 short words about dopamine receptors and nanoplastic exposure. No bullets."
        started = time.perf_counter()
        try:
            if target.provider == "llamacpp":
                payload = {
                    "model": target.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                }
                async with httpx.AsyncClient(
                    base_url=str(getattr(self.settings, "llamacpp_base_url", "http://localhost:8098") or "http://localhost:8098"),
                    timeout=240.0,
                    follow_redirects=True,
                ) as client:
                    response = await client.post("/v1/chat/completions", json=payload)
                    response.raise_for_status()
                    data = response.json()
                usage = data.get("usage") or {}
                completion_tokens = int(usage.get("completion_tokens") or 0)
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                total_tokens = int(usage.get("total_tokens") or 0)
                message = ((data.get("choices") or [{}])[0].get("message") or {})
                text = str(message.get("content") or "")
                thinking_text = str(message.get("thinking") or message.get("reasoning_content") or "")
            elif target.provider == "ollama":
                payload = {
                    "model": target.model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "think": spec.thinking_level != "off",
                    "options": {"num_predict": max_tokens},
                }
                async with httpx.AsyncClient(
                    base_url=str(getattr(self.settings, "ollama_base_url", "http://localhost:11434") or "http://localhost:11434"),
                    timeout=240.0,
                    follow_redirects=True,
                ) as client:
                    response = await client.post("/api/chat", json=payload)
                    response.raise_for_status()
                    data = response.json()
                completion_tokens = int(data.get("eval_count") or 0)
                prompt_tokens = int(data.get("prompt_eval_count") or 0)
                total_tokens = 0
                message = data.get("message") or {}
                text = str(message.get("content") or "")
                thinking_text = str(message.get("thinking") or "")
            else:
                return {"ok": False, "provider": target.provider, "error": "TPS probe only supports local models."}
            elapsed_s = time.perf_counter() - started
            visible_tokens = approximate_token_count(text)
            thinking_tokens = approximate_token_count(thinking_text)
            output_tokens_including_thinking = max(completion_tokens, visible_tokens + thinking_tokens)
            api_total_output_tokens = max(0, total_tokens - prompt_tokens) if total_tokens and prompt_tokens else 0
            output_tokens_including_thinking = max(output_tokens_including_thinking, api_total_output_tokens)
            api_output_tokens = completion_tokens or api_total_output_tokens
            return {
                "ok": True,
                "provider": target.provider,
                "elapsed_s": round(elapsed_s, 3),
                "api_completion_tokens": completion_tokens,
                "completion_tokens": completion_tokens,
                "api_output_tokens": api_output_tokens,
                "api_tps": round(api_output_tokens / elapsed_s, 2) if api_output_tokens else None,
                "visible_output_tokens_estimate": visible_tokens,
                "thinking_output_tokens_estimate": thinking_tokens,
                "total_output_tokens_including_thinking": output_tokens_including_thinking,
                "estimated_total_tps": round(output_tokens_including_thinking / elapsed_s, 2)
                if output_tokens_including_thinking
                else None,
                "approx_tps": round(output_tokens_including_thinking / elapsed_s, 2) if output_tokens_including_thinking else None,
                "chars": len(text),
                "thinking_chars": len(thinking_text),
                "approx_thinking_tokens": thinking_tokens,
                "leaked_think_tag": "<think" in text.lower(),
                "prompt_tokens": prompt_tokens,
                "api_total_tokens": total_tokens,
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": target.provider,
                "elapsed_s": round(time.perf_counter() - started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }

    @staticmethod
    def _extract_plan(final_response: dict[str, Any] | None) -> dict[str, Any] | None:
        for action in (final_response or {}).get("executed_actions") or []:
            if action.get("name") == "create_research_plan":
                plan = (action.get("details") or {}).get("plan")
                return dict(plan) if isinstance(plan, dict) else None
        return None

    @staticmethod
    def _plan_metrics(plan: dict[str, Any] | None) -> dict[str, Any]:
        if not plan:
            return {}
        query_blob = json.dumps(
            {
                "branches": plan.get("search_branches") or [],
                "shared": plan.get("shared_query_concepts") or [],
                "raw": plan.get("raw_search_queries") or [],
            },
            ensure_ascii=False,
        ).lower()
        return {
            "search_branch_count": len(plan.get("search_branches") or []),
            "active_database_count": len(plan.get("active_databases") or plan.get("databases") or []),
            "has_year_filter": plan.get("year_start") is not None or plan.get("year_end") is not None,
            "nanoplastic_terms_present": contains_any(query_blob, NANOPLASTIC_TERMS),
            "dopamine_terms_present": contains_any(query_blob, DOPAMINE_TERMS),
            "interaction_terms_present": contains_any(query_blob, INTERACTION_TERMS),
            "query_specificity_score": query_specificity_score(query_blob),
            "plan_quality_score": plan_quality_score(plan, query_blob),
        }

    @staticmethod
    def _finish_stage_timings(stage_timings: dict[str, dict[str, float | None]]) -> dict[str, dict[str, float | None]]:
        for timing in stage_timings.values():
            start = timing.get("start_s")
            end = timing.get("end_s")
            timing["duration_s"] = round(float(end) - float(start), 3) if start is not None and end is not None else None
        return stage_timings

    @staticmethod
    def _comparison(runs: list[dict[str, Any]]) -> dict[str, Any]:
        ranked = sorted(
            runs,
            key=lambda item: (
                int((item.get("article_pull") or {}).get("metrics", {}).get("relevant_title_abstract_hits") or 0),
                int((item.get("article_pull") or {}).get("metrics", {}).get("partial_relevance_hits") or 0),
                float((item.get("plan_metrics") or {}).get("query_specificity_score") or 0),
                float((item.get("quality_metrics") or {}).get("overall_score") or 0),
            ),
            reverse=True,
        )
        return {
            "best_run_id": ranked[0]["run_id"] if ranked else "",
            "ranking": [
                {
                    "run_id": item["run_id"],
                    "model": item["model"],
                    "thinking_level": item["thinking_level"],
                    "status": item.get("status"),
                    "relevant_hits": (item.get("article_pull") or {}).get("metrics", {}).get("relevant_title_abstract_hits"),
                    "partial_hits": (item.get("article_pull") or {}).get("metrics", {}).get("partial_relevance_hits"),
                    "planning_elapsed_s": item.get("planning_elapsed_s"),
                    "tps": (item.get("tps_probe") or {}).get("approx_tps"),
                    "api_tps": (item.get("tps_probe") or {}).get("api_tps"),
                    "overall_score": (item.get("quality_metrics") or {}).get("overall_score"),
                    "query_validity_score": (item.get("quality_metrics") or {}).get("query_validity_score"),
                    "article_relevance_score": (item.get("quality_metrics") or {}).get("article_relevance_score"),
                    "max_event_gap_s": (item.get("stream_metrics") or {}).get("max_event_gap_s"),
                }
                for item in ranked
            ],
        }

    @staticmethod
    def write_outputs(out_dir: Path, payload: dict[str, Any]) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "benchmark.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        write_markdown_report(out_dir / "summary.md", payload)
        write_article_csv(out_dir / "articles.csv", payload)


def article_relevance_heuristics(article: Article) -> dict[str, Any]:
    text = " ".join([article.title or "", article.abstract or "", " ".join(article.keywords or []), " ".join(article.mesh_terms or [])]).lower()
    groups = {
        "nanoplastic": matched_terms(text, NANOPLASTIC_TERMS),
        "dopamine": matched_terms(text, DOPAMINE_TERMS),
        "interaction": matched_terms(text, INTERACTION_TERMS),
    }
    matched_count = sum(1 for values in groups.values() if values)
    return {
        "groups": groups,
        "matched_group_count": matched_count,
        "all_groups_present": matched_count == len(groups),
        "relevance_score": round(matched_count / len(groups), 3),
    }


def query_validity_metrics(queries: list[dict[str, Any]]) -> dict[str, Any]:
    if not queries:
        return {
            "query_count": 0,
            "valid_query_count": 0,
            "invalid_query_count": 0,
            "query_validity_score": 0.0,
            "issues": ["no executable queries"],
        }
    issues: list[str] = []
    valid_count = 0
    for query in queries:
        text = str(query.get("query") or "")
        query_issues = []
        if not text.strip():
            query_issues.append("empty")
        if len(text) > 1500:
            query_issues.append("overlong")
        if text.count("(") != text.count(")"):
            query_issues.append("unbalanced_parentheses")
        if text.count('"') % 2:
            query_issues.append("unbalanced_quotes")
        lowered = text.strip().lower()
        if lowered.endswith((" or", " and", " or)", " and)")):
            query_issues.append("dangling_boolean")
        if query.get("error"):
            query_issues.append("execution_error")
        if query_issues:
            issues.append(f"{query.get('index', '?')}: {','.join(query_issues)}")
        else:
            valid_count += 1
    score = valid_count / len(queries)
    return {
        "query_count": len(queries),
        "valid_query_count": valid_count,
        "invalid_query_count": len(queries) - valid_count,
        "query_validity_score": round(score, 3),
        "issues": issues[:20],
    }


def benchmark_quality_metrics(plan_metrics: dict[str, Any], pull: dict[str, Any]) -> dict[str, Any]:
    queries = list((pull or {}).get("queries") or [])
    article_metrics = (pull or {}).get("metrics") or {}
    query_metrics = query_validity_metrics(queries)
    plan_score = float(plan_metrics.get("plan_quality_score") or 0.0)
    query_score = float(query_metrics.get("query_validity_score") or 0.0)
    article_score = float(article_metrics.get("average_article_relevance_score") or 0.0)
    overall = (plan_score * 0.35) + (query_score * 0.3) + (article_score * 0.35)
    return {
        "overall_score": round(overall, 3),
        "plan_quality_score": round(plan_score, 3),
        "query_validity_score": round(query_score, 3),
        "article_relevance_score": round(article_score, 3),
        "query_validity": query_metrics,
    }


def parse_llamacpp_engine_metrics(log_path: Path | None) -> dict[str, Any]:
    if not log_path:
        return {}
    path = Path(log_path)
    if not path.exists():
        return {"log_path": str(path), "available": False, "error": "log file not found"}
    text = path.read_text(encoding="utf-8", errors="replace")
    eval_events = _parse_timing_events(
        text,
        r"^\s*eval time\s*=\s*([0-9.]+)\s*ms\s*/\s*(\d+)\s*tokens?.*?([0-9.]+)\s*tokens per second",
    )
    prompt_events = _parse_timing_events(
        text,
        r"^\s*prompt eval time\s*=\s*([0-9.]+)\s*ms\s*/\s*(\d+)\s*tokens?.*?([0-9.]+)\s*tokens per second",
    )
    return {
        "log_path": str(path),
        "available": True,
        "eval": timing_summary(eval_events),
        "prompt_eval": timing_summary(prompt_events),
        "request_count": max(len(eval_events), len(prompt_events)),
    }


def _parse_timing_events(text: str, pattern: str) -> list[dict[str, Any]]:
    events = []
    for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
        events.append(
            {
                "elapsed_ms": float(match.group(1)),
                "tokens": int(match.group(2)),
                "tokens_per_second": float(match.group(3)),
            }
        )
    return events


def timing_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"count": 0, "last_tps": None, "average_tps": None, "max_tps": None, "events": []}
    values = [float(event["tokens_per_second"]) for event in events]
    return {
        "count": len(events),
        "last_tps": round(values[-1], 2),
        "average_tps": round(sum(values) / len(values), 2),
        "max_tps": round(max(values), 2),
        "events": events[-10:],
    }


def stream_metrics(events: list[dict[str, Any]], *, threshold_s: float) -> dict[str, Any]:
    elapsed_values = [float(event["elapsed_s"]) for event in events if event.get("elapsed_s") is not None]
    gaps = [
        round(current - previous, 3)
        for previous, current in zip(elapsed_values, elapsed_values[1:], strict=False)
        if current >= previous
    ]
    long_gaps = [gap for gap in gaps if gap >= threshold_s]
    return {
        "event_count": len(events),
        "first_event_latency_s": round(elapsed_values[0], 3) if elapsed_values else None,
        "last_event_elapsed_s": round(elapsed_values[-1], 3) if elapsed_values else None,
        "max_event_gap_s": max(gaps) if gaps else None,
        "average_event_gap_s": round(sum(gaps) / len(gaps), 3) if gaps else None,
        "stall_gap_threshold_s": threshold_s,
        "stall_gap_count": len(long_gaps),
        "stall_gaps_s": long_gaps[:10],
    }


def thinking_metrics(
    chunks: list[str],
    *,
    thinking_level: str,
    leaked_think_tag_chunks: int = 0,
) -> dict[str, Any]:
    text = "".join(chunks)
    return {
        "requested_thinking_level": thinking_level,
        "thinking_delta_count": len(chunks),
        "thinking_chars": len(text),
        "approx_thinking_tokens": approximate_token_count(text),
        "leaked_think_tag_chunks": leaked_think_tag_chunks,
        "content_saved": False,
        "note": "Thinking content is counted but not stored in benchmark events.",
    }


def approximate_token_count(text: str) -> int:
    cleaned = str(text or "").strip()
    if not cleaned:
        return 0
    whitespace_tokens = len(cleaned.split())
    char_estimate = max(1, round(len(cleaned) / 4))
    return max(whitespace_tokens, char_estimate)


def write_markdown_report(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Research Plan Benchmark",
        "",
        f"Created: {payload.get('created_at', '')}",
        "",
        "## Prompt",
        "",
        payload.get("prompt", ""),
        "",
        "## Ranking",
        "",
    ]
    for index, row in enumerate((payload.get("comparison") or {}).get("ranking") or [], start=1):
        lines.append(
            f"{index}. `{row['run_id']}` - {row['model']} / think={row['thinking_level']} "
            f"- status={row.get('status')} relevant={row['relevant_hits']} partial={row['partial_hits']} "
            f"- score={row.get('overall_score')} query_valid={row.get('query_validity_score')} "
            f"article_rel={row.get('article_relevance_score')} "
            f"- planning={row['planning_elapsed_s']}s api_tps={row.get('api_tps')} "
            f"estimated_tps={row['tps']} max_gap={row.get('max_event_gap_s')}"
        )
    engine = payload.get("engine_metrics") or {}
    if engine:
        lines.extend(
            [
                "",
                "## Engine Metrics",
                "",
                f"- Log: `{engine.get('log_path')}`",
                f"- Requests with eval timings: `{engine.get('request_count')}`",
                f"- Eval TPS last/avg/max: `{(engine.get('eval') or {}).get('last_tps')}` / `{(engine.get('eval') or {}).get('average_tps')}` / `{(engine.get('eval') or {}).get('max_tps')}`",
                f"- Prompt TPS last/avg/max: `{(engine.get('prompt_eval') or {}).get('last_tps')}` / `{(engine.get('prompt_eval') or {}).get('average_tps')}` / `{(engine.get('prompt_eval') or {}).get('max_tps')}`",
            ]
        )
    for run in payload.get("runs") or []:
        quality = run.get("quality_metrics") or {}
        lines.extend(
            [
                "",
                f"## {run['run_id']}",
                "",
                f"- Model: `{run['model']}`",
                f"- Thinking: `{run['thinking_level']}`",
                f"- Status: `{run.get('status')}`",
                f"- Preflight: `{(run.get('preflight') or {}).get('ok')}`",
                f"- Planning elapsed: `{run['planning_elapsed_s']}s`",
                f"- Total elapsed: `{run['total_elapsed_s']}s`",
                f"- Tool call success: `{run['tool_call_success']}`",
                f"- TPS probe API/estimated: `{(run.get('tps_probe') or {}).get('api_tps')}` / `{(run.get('tps_probe') or {}).get('approx_tps')}`",
                f"- Quality score: `{quality.get('overall_score')}`",
                f"- Plan/query/article score: `{quality.get('plan_quality_score')}` / `{quality.get('query_validity_score')}` / `{quality.get('article_relevance_score')}`",
                f"- Articles pulled: `{(run.get('article_pull') or {}).get('metrics', {}).get('unique_article_count')}`",
                f"- Max stream gap: `{(run.get('stream_metrics') or {}).get('max_event_gap_s')}`",
                f"- Thinking chunks/tokens: `{(run.get('thinking_metrics') or {}).get('thinking_delta_count')}` / `{(run.get('thinking_metrics') or {}).get('approx_thinking_tokens')}`",
                "",
                "### Queries",
                "",
            ]
        )
        if run.get("errors"):
            lines.extend(["### Errors", ""])
            for error in run.get("errors") or []:
                lines.append(f"- {error}")
            lines.append("")
        query_issues = ((quality.get("query_validity") or {}).get("issues") or [])
        if query_issues:
            lines.extend(["### Query Issues", ""])
            for issue in query_issues:
                lines.append(f"- {issue}")
            lines.append("")
        for query in (run.get("article_pull") or {}).get("queries") or []:
            lines.append(
                f"- [{query['database']}] {query['branch_label']} - {query['fetched_results']} results in "
                f"{query['elapsed_s']}s: `{query['query']}`"
            )
        lines.extend(["", "### Articles", ""])
        for article in (run.get("article_pull") or {}).get("articles") or []:
            heuristics = article.get("heuristics") or {}
            lines.append(
                f"- {article.get('year') or '-'} - {article.get('title') or '-'} "
                f"(PMID {article.get('pmid') or '-'}, PMC {article.get('pmc_id') or '-'}, DOI {article.get('doi') or '-'}) "
                f"- groups={heuristics.get('matched_group_count')} relevance={heuristics.get('relevance_score')}"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_article_csv(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "run_id",
                "model",
                "thinking_level",
                "title",
                "year",
                "pmid",
                "pmc_id",
                "doi",
                "matched_database",
                "matched_branch_label",
                "matched_group_count",
                "relevance_score",
                "all_groups_present",
            ],
        )
        writer.writeheader()
        for run in payload.get("runs") or []:
            for article in (run.get("article_pull") or {}).get("articles") or []:
                heuristics = article.get("heuristics") or {}
                writer.writerow(
                    {
                        "run_id": run.get("run_id"),
                        "model": run.get("model"),
                        "thinking_level": run.get("thinking_level"),
                        "title": article.get("title"),
                        "year": article.get("year"),
                        "pmid": article.get("pmid"),
                        "pmc_id": article.get("pmc_id"),
                        "doi": article.get("doi"),
                        "matched_database": article.get("matched_database"),
                        "matched_branch_label": article.get("matched_branch_label"),
                        "matched_group_count": heuristics.get("matched_group_count"),
                        "relevance_score": heuristics.get("relevance_score"),
                        "all_groups_present": heuristics.get("all_groups_present"),
                    }
                )


def parse_model_specs(values: list[str]) -> list[BenchmarkModelSpec]:
    specs: list[BenchmarkModelSpec] = []
    for value in values:
        for raw in value.split(","):
            item = raw.strip()
            if not item:
                continue
            parts = item.split("|")
            model = parts[0].strip()
            thinking = "off"
            label = None
            for part in parts[1:]:
                key, _, val = part.partition("=")
                if key.strip() in {"think", "thinking", "thinking_level"}:
                    thinking = val.strip() or "off"
                elif key.strip() == "label":
                    label = val.strip() or None
            specs.append(BenchmarkModelSpec(model=model, thinking_level=thinking, label=label))
    return specs


def normalize_database_name(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {"europepmc": "europe_pmc", "europe_pmc": "europe_pmc", "pmc": "pmc", "pubmed": "pubmed"}
    return aliases.get(normalized, normalized or "pubmed")


def optional_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def article_key(article: Article) -> str:
    return (article.doi or article.pmc_id or article.pmid or article.title or "").strip().lower()


def contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def matched_terms(text: str, terms: set[str]) -> list[str]:
    return sorted(term for term in terms if term in text)


def query_specificity_score(text: str) -> float:
    groups = [
        contains_any(text, NANOPLASTIC_TERMS),
        contains_any(text, DOPAMINE_TERMS),
        contains_any(text, INTERACTION_TERMS),
    ]
    quote_bonus = min(0.2, text.count('"') * 0.02)
    boolean_bonus = min(0.2, (text.count(" and ") + text.count(" or ")) * 0.03)
    return round((sum(groups) / len(groups)) + quote_bonus + boolean_bonus, 3)


def plan_quality_score(plan: dict[str, Any] | None, query_blob: str) -> float:
    if not plan:
        return 0.0
    score = 0.0
    branches = plan.get("search_branches") or []
    criteria = plan.get("screening_criteria") or plan.get("criteria") or []
    extraction = plan.get("extraction_plan") or {}
    questions = extraction.get("questions") if isinstance(extraction, dict) else []
    if branches:
        score += 0.2
    if len(branches) >= 2:
        score += 0.1
    if plan.get("year_start") is not None or plan.get("year_end") is not None:
        score += 0.1
    if contains_any(query_blob, NANOPLASTIC_TERMS):
        score += 0.15
    if contains_any(query_blob, DOPAMINE_TERMS):
        score += 0.15
    if contains_any(query_blob, INTERACTION_TERMS):
        score += 0.1
    if criteria:
        score += 0.1
    if questions:
        score += 0.1
    return round(min(score, 1.0), 3)


async def create_default_benchmark_runner(settings: Settings | None = None) -> tuple[ResearchPlanBenchmarkRunner, list[httpx.AsyncClient]]:
    resolved_settings = settings or get_settings()
    timeout = httpx.Timeout(resolved_settings.http_timeout_seconds)
    ncbi_http_client = httpx.AsyncClient(
        base_url=resolved_settings.ncbi_base_url,
        timeout=timeout,
        headers={"User-Agent": resolved_settings.request_user_agent},
        follow_redirects=True,
    )
    search_http_client = httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": resolved_settings.request_user_agent},
        follow_redirects=True,
    )
    pubmed_service = PubMedService(
        client=NcbiClient(ncbi_http_client, resolved_settings),
        cache=TTLCache(
            ttl_seconds=resolved_settings.search_cache_ttl_seconds,
            max_entries=resolved_settings.search_cache_max_entries,
        ),
        http_client=search_http_client,
        settings=resolved_settings,
        journal_metrics_service=None,
    )
    helper_service = HelperAIService(
        thread_cache=TTLCache(
            ttl_seconds=resolved_settings.helper_cache_ttl_seconds,
            max_entries=resolved_settings.helper_cache_max_entries,
        ),
        pubmed_service=pubmed_service,
        log_service=HelperLogService(resolved_settings.helper_log_path),
    )
    return (
        ResearchPlanBenchmarkRunner(
            helper_service=helper_service,
            pubmed_service=pubmed_service,
            settings=resolved_settings,
        ),
        [ncbi_http_client, search_http_client],
    )


async def close_clients(clients: list[httpx.AsyncClient]) -> None:
    await asyncio.gather(*(client.aclose() for client in clients), return_exceptions=True)
