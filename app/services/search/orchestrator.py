"""Search orchestration and article normalization."""

from __future__ import annotations

from typing import Iterable

from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchRequest
from app.services.search.adapters import BaseSearchAdapter, SearchResult


class SearchOrchestrator:
    def __init__(self, adapters: Iterable[BaseSearchAdapter]) -> None:
        self._adapters = {adapter.source_name: adapter for adapter in adapters}

    def has_source(self, source: str) -> bool:
        return source in self._adapters

    async def search_source(self, source: str, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        adapter = self._adapters[source]
        result = await adapter.search(request, max_results=max_results)
        return SearchResult(
            articles=self._dedupe_articles(result.articles)[:max_results],
            request_count=result.request_count,
            total_results_found=result.total_results_found,
        )

    @staticmethod
    def _dedupe_articles(articles: list[Article]) -> list[Article]:
        unique: list[Article] = []
        seen: set[tuple[str, str, str]] = set()
        for article in articles:
            key = (
                (article.doi or "").lower(),
                (article.pmc_id or "").upper(),
                (article.pmid or ""),
            )
            fallback = (
                key[0],
                key[1],
                key[2] or (article.title or "").strip().lower(),
            )
            final_key = fallback
            if final_key in seen:
                continue
            seen.add(final_key)
            unique.append(article)
        return unique
