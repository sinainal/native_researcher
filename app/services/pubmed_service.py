"""Discovery service backed by modular search adapters."""

from __future__ import annotations

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
        result = await self.orchestrator.search_source(source, effective_request, max_results=effective_request.max_results)
        filtered = self._apply_request_filters(result.articles, effective_request)[: effective_request.max_results]
        self._enrich_journal_metrics(filtered)
        response = PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=effective_request.query.strip(),
                total_results_found=len(filtered),
                fetched_results=len(filtered),
                batch_size_used=effective_request.max_results,
                request_count=result.request_count,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                oa_only=self.settings.pubmed_oa_only,
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
                str(bool(getattr(self.client.settings, "pubmed_oa_only", False))),
                "search_orchestrator_v5",
            ]
        )

    @staticmethod
    def _normalize_search_resource(value: str | None, default: str = "openalex") -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"openalex", "pubmed", "europe_pmc", "pmc"}:
            return normalized
        return default

    @staticmethod
    def _apply_request_filters(articles: list[Article], request: PubMedSearchRequest) -> list[Article]:
        filtered = list(articles)
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

    def _enrich_journal_metrics(self, articles: list[Article]) -> None:
        if self.journal_metrics_service is None:
            return
        self.journal_metrics_service.enrich_articles(articles)
