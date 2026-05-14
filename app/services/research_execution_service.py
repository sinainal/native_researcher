"""Deterministic execution pipeline for research agent plans."""

from __future__ import annotations

import time
import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4
from collections.abc import Awaitable, Callable

from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchRequest
from app.schemas.research_execution import (
    ResearchPlanExecuteResponse,
    ResearchPlanRunTrace,
    ResearchQueryTrace,
    ResearchSelectionTrace,
)
from app.services.pubmed_service import PubMedService
from app.services.research_candidate_normalizer import (
    NormalizedResearchCandidate,
    candidate_trace,
    normalize_database_source,
    normalize_research_candidates,
)
from app.services.research_screening_service import ResearchScreeningService

ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
MAX_RAW_QUERIES = 120


class ResearchExecutionService:
    def __init__(
        self,
        *,
        pubmed_service: PubMedService,
        screening_service: ResearchScreeningService | None = None,
    ) -> None:
        self.pubmed_service = pubmed_service
        self.screening_service = screening_service or ResearchScreeningService()

    async def execute_plan(self, plan: dict[str, Any]) -> ResearchPlanExecuteResponse:
        return await self.execute_plan_with_screening(plan)

    async def execute_plan_with_screening(
        self,
        plan: dict[str, Any],
        *,
        screening_model: str | None = None,
        api_key: str = "",
        thinking_level: str = "off",
        progress: ProgressCallback | None = None,
    ) -> ResearchPlanExecuteResponse:
        started = time.perf_counter()
        timestamp = datetime.now(UTC).replace(microsecond=0).isoformat()
        raw_queries = self._raw_search_queries(plan)[:MAX_RAW_QUERIES]
        if progress is not None:
            await progress(
                {
                    "stage": "start",
                    "message": f"Executing {len(raw_queries)} generated queries.",
                    "total_queries": len(raw_queries),
                }
            )
        executed_queries: list[ResearchQueryTrace] = []
        query_results: list[tuple[dict[str, Any], list[Article]]] = []
        query_positions = {id(raw_query): index for index, raw_query in enumerate(raw_queries, start=1)}

        async def run_database_queries(database: str, database_queries: list[dict[str, Any]]) -> tuple[list[ResearchQueryTrace], list[tuple[dict[str, Any], list[Article]]]]:
            local_traces: list[ResearchQueryTrace] = []
            local_results: list[tuple[dict[str, Any], list[Article]]] = []
            for raw_query in database_queries:
                index = query_positions.get(id(raw_query), 0)
                trace, articles = await self._execute_raw_query(
                    raw_query,
                    plan,
                    index=index,
                    total_queries=len(raw_queries),
                    progress=progress,
                )
                local_traces.append(trace)
                if articles is not None:
                    local_results.append((raw_query, articles))
            return local_traces, local_results

        grouped_queries: dict[str, list[dict[str, Any]]] = {}
        for raw_query in raw_queries:
            source = normalize_database_source(str(raw_query.get("database") or raw_query.get("source") or "pubmed"))
            grouped_queries.setdefault(source, []).append(raw_query)
        grouped_results = await asyncio.gather(
            *[
                run_database_queries(database, database_queries)
                for database, database_queries in grouped_queries.items()
            ]
        )
        for traces, results in grouped_results:
            executed_queries.extend(traces)
            query_results.extend(results)
        executed_queries.sort(key=lambda item: _trace_position(item, raw_queries, query_positions))
        query_results.sort(key=lambda item: query_positions.get(id(item[0]), 10**9))

        if progress is not None:
            await progress({"stage": "normalize", "message": "Normalizing and deduplicating candidates."})
        candidates = normalize_research_candidates(query_results)
        if progress is not None:
            await progress(
                {
                    "stage": "screening_start",
                    "message": f"Screening {len(candidates)} normalized candidates with {screening_model or 'default model'}.",
                    "candidate_count": len(candidates),
                    "screening_model": screening_model or "",
                }
            )
        screening = await self.screening_service.screen_candidates(
            candidates,
            plan,
            model=screening_model,
            api_key=api_key,
            thinking_level=thinking_level,
            progress=progress,
        )
        if progress is not None:
            await progress({"stage": "selection", "message": "Selecting final articles per branch."})
        screening_by_id = {item.candidate_id: item for item in screening}
        selections = self._select_candidates(candidates, plan, screening_by_id)
        selected_ids = []
        backup_ids = []
        excluded_ids = []
        for selection in selections:
            selected_ids.extend(selection.selected_candidate_ids)
            backup_ids.extend(selection.backup_candidate_ids)
            excluded_ids.extend(selection.excluded_candidate_ids)
        selected_ids = _ordered_unique(selected_ids)
        backup_ids = _ordered_unique(backup_ids)
        excluded_ids = _ordered_unique(excluded_ids)

        selected_lookup = set(selected_ids)
        selected_articles = [
            candidate.article.model_copy(deep=True)
            for candidate in candidates
            if candidate.candidate_id in selected_lookup
        ]
        for index, article in enumerate(selected_articles, start=1):
            article.id = index

        trace = ResearchPlanRunTrace(
            id=f"research_run_{uuid4().hex[:12]}",
            created_at=timestamp,
            topic=str(plan.get("topic") or ""),
            objective=str(plan.get("objective") or ""),
            target_count_per_branch=self._target_count(plan),
            executed_queries=executed_queries,
            candidates=[candidate_trace(candidate) for candidate in candidates],
            screening=screening,
            selections=selections,
            selected_candidate_ids=selected_ids,
            backup_candidate_ids=backup_ids,
            excluded_candidate_ids=excluded_ids,
            meta={
                "candidate_count": len(candidates),
                "selected_count": len(selected_articles),
                "raw_query_count": len(raw_queries),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "screening_model": screening_model or "",
            },
        )
        return ResearchPlanExecuteResponse(
            meta=PubMedSearchMeta(
                full_query=str(plan.get("topic") or plan.get("objective") or "Research plan execution"),
                total_results_found=sum(item.total_results_found for item in executed_queries),
                fetched_results=len(selected_articles),
                batch_size_used=self._target_count(plan),
                request_count=sum(item.request_count for item in executed_queries),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                oa_only=False,
                primary_source="research_plan",
                sources_used=sorted({item.source for item in executed_queries if item.source}),
                fallback_used=False,
            ),
            articles=selected_articles,
            run_trace=trace,
        )

    async def _execute_raw_query(
        self,
        raw_query: dict[str, Any],
        plan: dict[str, Any],
        *,
        index: int,
        total_queries: int,
        progress: ProgressCallback | None,
    ) -> tuple[ResearchQueryTrace, list[Article] | None]:
        source = normalize_database_source(str(raw_query.get("database") or raw_query.get("source") or "pubmed"))
        candidate_limit = self._candidate_limit(raw_query, plan)
        if progress is not None:
            await progress(
                {
                    "stage": "query_start",
                    "message": f"Query {index}/{total_queries}: {raw_query.get('database') or source} · {raw_query.get('branch_label') or 'Branch'}",
                    "query_index": index,
                    "total_queries": total_queries,
                    "database": raw_query.get("database") or source,
                    "branch_label": raw_query.get("branch_label") or "",
                    "category_label": raw_query.get("category_label") or "",
                }
            )
        try:
            response = await self.pubmed_service.search(
                PubMedSearchRequest(
                    query=str(raw_query.get("query") or "").strip(),
                    year_start=self._year_start(plan),
                    year_end=self._year_end(plan),
                    max_results=candidate_limit,
                    batch_size=None,
                    min_cite=None,
                    article_type=None,
                    use_cache=True,
                    preferred_source=source,  # type: ignore[arg-type]
                )
            )
        except Exception as exc:
            trace = self._query_trace(
                raw_query,
                source,
                candidate_limit,
                status="error",
                error=str(exc),
            )
            if progress is not None:
                await progress(
                    {
                        "stage": "query_error",
                        "message": f"Query {index} failed: {exc}",
                        "query_index": index,
                        "error": str(exc),
                    }
                )
            return trace, None

        trace = self._query_trace(
            raw_query,
            source,
            candidate_limit,
            fetched_results=response.meta.fetched_results,
            total_results_found=response.meta.total_results_found,
            request_count=response.meta.request_count,
            elapsed_ms=response.meta.elapsed_ms,
        )
        if progress is not None:
            await progress(
                {
                    "stage": "query_done",
                    "message": f"Query {index}/{total_queries} returned {response.meta.fetched_results} candidates.",
                    "query_index": index,
                    "fetched_results": response.meta.fetched_results,
                }
            )
        return trace, response.articles

    def _raw_search_queries(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        databases = self._databases(plan)
        branches = self._branches(plan)
        concepts = self._shared_concepts(plan)
        per_database = self._per_database(plan)
        raw_queries: list[dict[str, Any]] = []
        for database in databases:
            for branch in branches:
                category_query = " OR ".join(f"({concept['query']})" for concept in concepts if concept.get("query"))
                parts = [branch["query"] or branch["label"], category_query]
                query = " AND ".join(f"({part})" for part in parts if part)
                raw_queries.append(
                    {
                        "database": database,
                        "branch_id": branch["id"],
                        "branch_label": branch["label"],
                        "category_ids": [concept["id"] for concept in concepts],
                        "category_labels": [concept["label"] for concept in concepts],
                        "category_id": "",
                        "category_label": "Combined categories" if concepts else "",
                        "query": query or branch["label"],
                        "candidate_limit": per_database,
                    }
                    )
        return raw_queries

    def _select_candidates(
        self,
        candidates: list[NormalizedResearchCandidate],
        plan: dict[str, Any],
        screening_by_id: dict[str, Any],
    ) -> list[ResearchSelectionTrace]:
        target_count = self._target_count(plan)
        selections: list[ResearchSelectionTrace] = []
        for branch in self._branches(plan):
            branch_id = branch["id"]
            branch_candidates = [
                candidate
                for candidate in candidates
                if any(match.branch_id == branch_id for match in candidate.matches)
            ]
            eligible = [
                candidate
                for candidate in branch_candidates
                if not screening_by_id.get(candidate.candidate_id).excluded
            ]
            eligible.sort(
                key=lambda candidate: (
                    screening_by_id.get(candidate.candidate_id).final_score,
                    _year_sort(candidate.article.year),
                ),
                reverse=True,
            )
            selected = eligible[:target_count]
            backup = eligible[target_count:]
            excluded = [
                candidate
                for candidate in branch_candidates
                if screening_by_id.get(candidate.candidate_id).excluded
            ]
            selections.append(
                ResearchSelectionTrace(
                    branch_id=branch_id,
                    branch_label=branch["label"],
                    selected_candidate_ids=[candidate.candidate_id for candidate in selected],
                    backup_candidate_ids=[candidate.candidate_id for candidate in backup],
                    excluded_candidate_ids=[candidate.candidate_id for candidate in excluded],
                )
            )
        return selections

    def _query_trace(
        self,
        raw_query: dict[str, Any],
        source: str,
        candidate_limit: int,
        *,
        status: str = "success",
        fetched_results: int = 0,
        total_results_found: int = 0,
        request_count: int = 0,
        elapsed_ms: int = 0,
        error: str | None = None,
    ) -> ResearchQueryTrace:
        return ResearchQueryTrace(
            database=str(raw_query.get("database") or source),
            source=source,
            branch_id=str(raw_query.get("branch_id") or ""),
            branch_label=str(raw_query.get("branch_label") or ""),
            category_id=str(raw_query.get("category_id") or ""),
            category_label=str(raw_query.get("category_label") or ""),
            query=str(raw_query.get("query") or ""),
            candidate_limit=candidate_limit,
            status=status,
            fetched_results=fetched_results,
            total_results_found=total_results_found,
            request_count=request_count,
            elapsed_ms=elapsed_ms,
            error=error,
        )

    def _databases(self, plan: dict[str, Any]) -> list[str]:
        databases = plan.get("active_databases") or plan.get("databases") or ["PubMed"]
        return [str(item).strip() for item in databases if str(item).strip()] or ["PubMed"]

    def _branches(self, plan: dict[str, Any]) -> list[dict[str, str]]:
        branches = []
        for index, item in enumerate(plan.get("search_branches") or [], start=1):
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("query") or f"Branch {index}").strip()
            query = str(item.get("query") or label).strip()
            branches.append(
                {
                    "id": str(item.get("id") or _slug(label) or f"branch_{index}"),
                    "label": label,
                    "query": query,
                }
            )
        if branches:
            return branches
        topic = str(plan.get("topic") or "Main topic").strip()
        return [{"id": "main_branch", "label": topic, "query": topic}]

    def _shared_concepts(self, plan: dict[str, Any]) -> list[dict[str, str]]:
        concepts: list[dict[str, str]] = []
        for index, item in enumerate(plan.get("shared_query_concepts") or [], start=1):
            if isinstance(item, str):
                query = item.strip()
                label = f"Shared query {index}"
            elif isinstance(item, dict):
                query = str(item.get("query") or item.get("label") or "").strip()
                label = str(item.get("label") or f"Shared query {index}").strip()
            else:
                continue
            if not query:
                continue
            concepts.append({"id": _slug(label) or f"concept_{index}", "label": label, "query": query})
        return concepts

    def _target_count(self, plan: dict[str, Any]) -> int:
        return max(1, min(500, _int_value(plan.get("target_count_per_branch") or plan.get("target_count"), 20)))

    def _per_database(self, plan: dict[str, Any]) -> int:
        budget = plan.get("candidate_budget") if isinstance(plan.get("candidate_budget"), dict) else {}
        return max(1, min(5000, _int_value(budget.get("per_database"), self._target_count(plan) * 2)))

    def _candidate_limit(self, raw_query: dict[str, Any], plan: dict[str, Any]) -> int:
        return max(1, min(5000, _int_value(raw_query.get("candidate_limit"), self._per_database(plan))))

    def _year_start(self, plan: dict[str, Any]) -> int:
        return max(1000, min(9999, _int_value(plan.get("year_start"), 1900)))

    def _year_end(self, plan: dict[str, Any]) -> int:
        return max(1000, min(9999, _int_value(plan.get("year_end"), datetime.now(UTC).year)))


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _year_sort(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


def _trace_position(
    trace: ResearchQueryTrace,
    raw_queries: list[dict[str, Any]],
    query_positions: dict[int, int],
) -> int:
    for query in raw_queries:
        if query.get("query") != trace.query:
            continue
        if normalize_database_source(str(query.get("database") or query.get("source") or "pubmed")) != trace.source:
            continue
        return query_positions.get(id(query), 10**9)
    return 10**9


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value.lower()).strip("_")
