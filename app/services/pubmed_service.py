"""Discovery service backed by modular search adapters."""

from __future__ import annotations

import re
import time

import httpx

from app.clients.ncbi import NcbiClient
from app.core.config import Settings
from app.schemas.article import Article
from app.schemas.pubmed import (
    PubMedCitationItem,
    PubMedCitationRequest,
    PubMedCitationResponse,
    PubMedSearchMeta,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.services.agent.search_policy import apply_default_year_window
from app.services.journal_metrics_service import JournalMetricsService
from app.services.search.adapters import (
    ArxivSearchAdapter,
    CoreSearchAdapter,
    EuropePMCSearchAdapter,
    OpenAlexSearchAdapter,
    PMCSearchAdapter,
    PubMedSearchAdapter,
)
from app.services.search.orchestrator import SearchOrchestrator
from app.utils.cache import TTLCache


class PubMedService:
    def __init__(
        self,
        client: NcbiClient,
        cache: TTLCache[str, PubMedSearchResponse],
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
        journal_metrics_service: JournalMetricsService | None = None,
    ) -> None:
        self.client = client
        self.cache = cache
        self.http_client = http_client
        self.settings = settings or client.settings
        self.journal_metrics_service = journal_metrics_service
        adapters = [PubMedSearchAdapter(client)]
        if http_client is not None:
            adapters.extend(
                [
                    OpenAlexSearchAdapter(http_client, self.settings),
                    EuropePMCSearchAdapter(http_client, self.settings),
                    PMCSearchAdapter(client.http_client, self.settings),
                    CoreSearchAdapter(http_client, self.settings),
                    ArxivSearchAdapter(http_client, self.settings),
                ]
            )
        self.orchestrator = SearchOrchestrator(adapters)

    async def search(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        effective_request = self._with_default_year_window(request)
        cache_key = self._cache_key(effective_request)
        if effective_request.use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                cached_copy = cached.model_copy(deep=True)
                cached_copy.meta.cache_hit = True
                return cached_copy

        source = self._normalize_search_resource(effective_request.preferred_source, "openalex")
        if not self.orchestrator.has_source(source):
            source = "pubmed"

        started = time.perf_counter()
        candidate_limit = effective_request.max_results
        if effective_request.relevance_groups:
            candidate_limit = min(5000, max(effective_request.max_results * 5, effective_request.max_results))
        result = await self.orchestrator.search_source(source, effective_request, max_results=candidate_limit)
        filtered = self._apply_request_filters(result.articles, effective_request)
        filtered = self._rank_by_relevance(filtered, effective_request)[: effective_request.max_results]
        self._enrich_journal_metrics(filtered)
        response = PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=effective_request.query.strip(),
                total_results_found=int(result.total_results_found or len(result.articles) or len(filtered)),
                fetched_results=len(filtered),
                batch_size_used=effective_request.max_results,
                request_count=result.request_count,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                oa_only=effective_request.resolved_oa_only(self.settings.pubmed_oa_only),
                primary_source=source,
                sources_used=[source],
                fallback_used=False,
            ),
            articles=filtered,
        )
        if effective_request.use_cache:
            self.cache.set(cache_key, response.model_copy(deep=True))
        return response

    async def enrich_citations(self, request: PubMedCitationRequest) -> PubMedCitationResponse:
        articles = [
            Article(
                id=index + 1,
                pmid=item.pmid or "",
                title=item.title or "",
                year=item.year,
                doi=item.doi,
                pmc_id=item.pmc_id,
            )
            for index, item in enumerate(request.articles)
            if item.pmid or item.doi
        ]
        enriched = await self.client.enrich_citation_counts(articles)
        return PubMedCitationResponse(
            items=[
                PubMedCitationItem(
                    pmid=article.pmid or None,
                    doi=article.doi,
                    citation_count=article.citation_count,
                )
                for article in enriched
            ]
        )

    @staticmethod
    def _with_default_year_window(request: PubMedSearchRequest) -> PubMedSearchRequest:
        year_start, year_end = apply_default_year_window(request.year_start, request.year_end)
        if year_start == request.year_start and year_end == request.year_end:
            return request
        return request.model_copy(update={"year_start": year_start, "year_end": year_end})

    def _cache_key(self, request: PubMedSearchRequest) -> str:
        return "|".join(
            [
                request.query.strip().lower(),
                str(request.year_start or ""),
                str(request.year_end or ""),
                str(request.max_results),
                str(request.batch_size or ""),
                str(request.min_cite or ""),
                (request.article_type or "").strip().lower(),
                request.preferred_source,
                str(request.resolved_oa_only(self.settings.pubmed_oa_only)),
                repr(request.relevance_groups),
                str(request.require_all_relevance_groups),
                str(request.require_relevance_cooccurrence),
                repr(request.relevance_exclude_terms),
                "search_orchestrator_v8",
            ]
        )

    @staticmethod
    def _normalize_search_resource(value: str | None, default: str = "openalex") -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"}:
            return normalized
        return default

    @staticmethod
    def _apply_request_filters(articles: list[Article], request: PubMedSearchRequest) -> list[Article]:
        filtered = list(articles)
        if request.year_start is not None:
            filtered = [item for item in filtered if (item.year or "").isdigit() and int(item.year) >= request.year_start]
        if request.year_end is not None:
            filtered = [item for item in filtered if (item.year or "").isdigit() and int(item.year) <= request.year_end]
        if request.min_cite is not None:
            filtered = [item for item in filtered if (item.citation_count or 0) >= request.min_cite]
        if request.article_type:
            expected = request.article_type.strip().lower()
            filtered = [
                item
                for item in filtered
                if expected == (item.article_type or "").lower()
                or expected in {value.lower() for value in item.article_types}
            ]
        return filtered

    @classmethod
    def _rank_by_relevance(cls, articles: list[Article], request: PubMedSearchRequest) -> list[Article]:
        groups = [
            [str(term).strip() for term in group if str(term).strip()]
            for group in request.relevance_groups
            if group
        ]
        if not groups:
            return articles

        ranked: list[tuple[int, int, int, Article]] = []
        for original_index, article in enumerate(articles):
            title = cls._normalized_search_text(article.title)
            raw_body = " ".join([article.title, article.abstract, *article.keywords, *article.mesh_terms])
            body = cls._normalized_search_text(
                raw_body
            )
            excluded_terms = [
                term for term in request.relevance_exclude_terms if cls._contains_term(body, term)
            ]
            if excluded_terms:
                continue
            matched_groups: list[list[str]] = []
            title_groups = 0
            for group in groups:
                matched_terms = [term for term in group if cls._contains_term(body, term)]
                matched_groups.append(matched_terms)
                if any(cls._contains_term(title, term) for term in group):
                    title_groups += 1
            matched_count = sum(bool(group) for group in matched_groups)
            if request.require_all_relevance_groups and matched_count != len(groups):
                continue
            cooccurrence_passage = None
            if request.require_relevance_cooccurrence:
                passages = [article.title, *re.split(r"(?<=[.!?;])\s+|\n+", raw_body)]
                for passage in passages:
                    normalized_passage = cls._normalized_search_text(passage)
                    if all(any(cls._contains_term(normalized_passage, term) for term in group) for group in groups):
                        cooccurrence_passage = passage.strip()[:500]
                        break
                if cooccurrence_passage is None:
                    continue
            score = round(matched_count / len(groups), 3)
            article.research_meta = {
                **article.research_meta,
                "score": score,
                "relevance": {
                    "matched_group_count": matched_count,
                    "total_group_count": len(groups),
                    "matched_terms": matched_groups,
                    "all_groups_present": matched_count == len(groups),
                    "title_group_count": title_groups,
                    "cooccurrence_passage": cooccurrence_passage,
                },
            }
            ranked.append((matched_count, title_groups, -original_index, article))
        ranked.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        return [row[3] for row in ranked]

    @staticmethod
    def _normalized_search_text(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))

    @classmethod
    def _contains_term(cls, normalized_text: str, term: str) -> bool:
        normalized_term = cls._normalized_search_text(term)
        if not normalized_term:
            return False
        return f" {normalized_term} " in f" {normalized_text} "

    def _enrich_journal_metrics(self, articles: list[Article]) -> None:
        if self.journal_metrics_service is None:
            return
        self.journal_metrics_service.enrich_articles(articles)
