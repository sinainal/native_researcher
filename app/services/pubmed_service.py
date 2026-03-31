"""PubMed service with caching."""

from __future__ import annotations

from app.clients.ncbi import NcbiClient
from app.schemas.article import Article
from app.schemas.pubmed import (
    PubMedCitationItem,
    PubMedCitationRequest,
    PubMedCitationResponse,
    PubMedSearchMeta,
    PubMedSearchRequest,
    PubMedSearchResponse,
)
from app.utils.cache import TTLCache


class PubMedService:
    def __init__(
        self,
        client: NcbiClient,
        cache: TTLCache[str, PubMedSearchResponse],
    ) -> None:
        self.client = client
        self.cache = cache

    async def search(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        cache_key = self._cache_key(request)
        if request.use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                cached_copy = cached.model_copy(deep=True)
                cached_copy.meta.cache_hit = True
                return cached_copy

        result = await self.client.search_articles(
            query=request.query,
            year_start=request.year_start,
            year_end=request.year_end,
            max_results=request.max_results,
            batch_size=request.batch_size,
            min_cite=request.min_cite,
            article_type=request.article_type,
        )
        response = PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=result.full_query,
                total_results_found=result.total_results_found,
                fetched_results=len(result.articles),
                batch_size_used=result.batch_size_used,
                request_count=result.request_count,
                elapsed_ms=result.elapsed_ms,
                cache_hit=False,
                oa_only=result.oa_only,
            ),
            articles=result.articles,
        )
        if request.use_cache:
            self.cache.set(cache_key, response.model_copy(deep=True))
        return response

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
                str(bool(getattr(self.client.settings, "pubmed_oa_only", False))),
            ]
        )

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
