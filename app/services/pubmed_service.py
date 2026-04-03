"""Discovery service with single-source search selection."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.clients.ncbi import NcbiClient
from app.schemas.article import Article
from app.core.config import Settings
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
from app.utils.cache import TTLCache
from app.utils.rate_limit import AsyncRateLimiter


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
        self.openalex_rate_limiter = AsyncRateLimiter(self.settings.openalex_requests_per_second)
        self.europe_pmc_rate_limiter = AsyncRateLimiter(self.settings.europe_pmc_requests_per_second)

    async def search(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        effective_request = self._with_default_year_window(request)
        cache_key = self._cache_key(effective_request)
        if effective_request.use_cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                cached_copy = cached.model_copy(deep=True)
                cached_copy.meta.cache_hit = True
                return cached_copy

        response = await self._search_preferred_source_only(effective_request)
        if effective_request.use_cache:
            self.cache.set(cache_key, response.model_copy(deep=True))
        return response

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
                "search_orchestrator_v4",
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

    async def _search_preferred_source_only(self, request: PubMedSearchRequest) -> PubMedSearchResponse:
        started = time.perf_counter()
        preferred_source = self._normalize_search_resource(request.preferred_source, "openalex")
        if self.http_client is None and preferred_source == "pubmed":
            return await self._search_pubmed_only(request, started)

        articles, request_count = await self._search_source(
            preferred_source,
            request,
            max_results=request.max_results,
        )
        filtered = self._apply_request_filters(articles, request)[: request.max_results]
        self._enrich_journal_metrics(filtered)

        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=request.query.strip(),
                total_results_found=len(filtered),
                fetched_results=len(filtered),
                batch_size_used=request.max_results,
                request_count=request_count,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                oa_only=self.settings.pubmed_oa_only,
                primary_source=preferred_source,
                sources_used=[preferred_source],
                fallback_used=False,
            ),
            articles=filtered,
        )

    async def _search_pubmed_only(
        self,
        request: PubMedSearchRequest,
        started: float,
    ) -> PubMedSearchResponse:
        result = await self.client.search_articles(
            query=request.query,
            year_start=request.year_start,
            year_end=request.year_end,
            max_results=request.max_results,
            batch_size=request.batch_size,
            min_cite=request.min_cite,
            article_type=request.article_type,
        )
        self._enrich_journal_metrics(result.articles)
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=result.full_query,
                total_results_found=result.total_results_found,
                fetched_results=len(result.articles),
                batch_size_used=result.batch_size_used,
                request_count=result.request_count,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                cache_hit=False,
                oa_only=result.oa_only,
                primary_source="pubmed",
                sources_used=["pubmed"],
                fallback_used=False,
            ),
            articles=result.articles,
        )

    async def _search_pubmed_articles(
        self,
        request: PubMedSearchRequest,
        *,
        max_results: int,
    ) -> tuple[list[Article], int]:
        result = await self.client.search_articles(
            query=request.query,
            year_start=request.year_start,
            year_end=request.year_end,
            max_results=max_results,
            batch_size=request.batch_size,
            min_cite=request.min_cite,
            article_type=request.article_type,
        )
        return result.articles, result.request_count

    async def _search_source(
        self,
        source: str,
        request: PubMedSearchRequest,
        *,
        max_results: int,
    ) -> tuple[list[Article], int]:
        if source == "openalex":
            if self.http_client is None:
                return [], 0
            return await self._search_openalex(request, max_results=max_results)
        if source == "pubmed":
            return await self._search_pubmed_articles(request, max_results=max_results)
        if source == "europe_pmc":
            if self.http_client is None:
                return [], 0
            return await self._search_europe_pmc(request, max_results=max_results)
        return [], 0

    async def _search_openalex(
        self,
        request: PubMedSearchRequest,
        *,
        max_results: int,
    ) -> tuple[list[Article], int]:
        await self.openalex_rate_limiter.wait()
        params: dict[str, Any] = {
            "search": request.query.strip(),
            "per-page": min(max_results, 200),
            "select": (
                "id,display_name,publication_year,publication_date,doi,ids,primary_location,"
                "authorships,cited_by_count,type,abstract_inverted_index,referenced_works_count,"
                "primary_topic,topics,related_works"
            ),
        }
        filters: list[str] = []
        if self.settings.pubmed_oa_only:
            filters.append("is_oa:true")
        if request.year_start:
            filters.append(f"from_publication_date:{request.year_start}-01-01")
        if request.year_end:
            filters.append(f"to_publication_date:{request.year_end}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        try:
            response = await self.http_client.get(f"{self.settings.openalex_base_url}/works", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return [], 1
        rows = payload.get("results", [])
        articles = [self._article_from_openalex(index + 1, row) for index, row in enumerate(rows)]
        return self._apply_request_filters(articles, request), 1

    async def _search_europe_pmc(
        self,
        request: PubMedSearchRequest,
        *,
        max_results: int,
    ) -> tuple[list[Article], int]:
        await self.europe_pmc_rate_limiter.wait()
        query = request.query.strip()
        if self.settings.pubmed_oa_only:
            query = f"({query}) AND OPEN_ACCESS:y"
        params: dict[str, Any] = {
            "query": query,
            "format": "json",
            "pageSize": min(max_results, 100),
            "resultType": "core",
        }
        try:
            response = await self.http_client.get(f"{self.settings.europe_pmc_base_url}/search", params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return [], 1
        rows = payload.get("resultList", {}).get("result", [])
        articles = [self._article_from_europe_pmc(index + 1, row) for index, row in enumerate(rows)]
        return self._apply_request_filters(articles, request), 1

    def _article_from_openalex(self, index: int, raw: dict[str, Any]) -> Article:
        ids = raw.get("ids") or {}
        primary_location = raw.get("primary_location") or {}
        source = primary_location.get("source") or {}
        authorships = raw.get("authorships") or []
        authors = [
            (authorship.get("author") or {}).get("display_name")
            for authorship in authorships
            if (authorship.get("author") or {}).get("display_name")
        ]
        raw_pmid = ids.get("pmid")
        raw_pmcid = ids.get("pmcid")
        source_issn_l = self._normalize_issn(source.get("issn_l"))
        source_issns = self._normalize_issn_list(source.get("issn"))
        primary_topic = self._openalex_primary_topic_label(raw)
        return Article(
            id=index,
            pmid=self._extract_numeric_id(raw_pmid),
            title=raw.get("display_name") or "Title not available",
            abstract=self._reconstruct_openalex_abstract(raw.get("abstract_inverted_index")),
            year=str(raw.get("publication_year")) if raw.get("publication_year") is not None else None,
            journal=source.get("display_name"),
            publication_date=raw.get("publication_date"),
            article_type=self._format_article_type(raw.get("type")),
            article_types=[self._format_article_type(raw.get("type"))] if raw.get("type") else [],
            citation_count=self._safe_int(raw.get("cited_by_count")),
            authors=authors,
            keywords=self._openalex_topic_labels(raw),
            mesh_terms=[primary_topic] if primary_topic else [],
            related_articles=self._openalex_related_work_labels(raw),
            reference_count=self._safe_int(raw.get("referenced_works_count")) or 0,
            doi=self._normalize_doi(raw.get("doi")),
            pmc_id=self._extract_pmcid(raw_pmcid),
            issn_l=source_issn_l,
            issns=source_issns,
        )

    def _article_from_europe_pmc(self, index: int, raw: dict[str, Any]) -> Article:
        author_string = str(raw.get("authorString") or "").strip()
        authors = [item.strip() for item in author_string.split(",") if item.strip()]
        article_types: list[str] = []
        for entry in raw.get("pubTypeList", {}).get("pubType", []) if isinstance(raw.get("pubTypeList"), dict) else []:
            value = str(entry or "").strip()
            if value:
                article_types.append(value)
        article_type = article_types[0] if article_types else None
        return Article(
            id=index,
            pmid=self._extract_numeric_id(raw.get("pmid")),
            title=raw.get("title") or "Title not available",
            abstract=str(raw.get("abstractText") or "").strip(),
            year=str(raw.get("pubYear")) if raw.get("pubYear") is not None else None,
            journal=raw.get("journalTitle"),
            publication_date=raw.get("firstPublicationDate"),
            article_type=article_type,
            article_types=article_types,
            citation_count=self._safe_int(raw.get("citedByCount")),
            authors=authors,
            reference_count=0,
            doi=self._normalize_doi(raw.get("doi")),
            pmc_id=self._extract_pmcid(raw.get("pmcid")),
        )

    def _merge_articles(self, primary: list[Article], secondary: list[Article]) -> list[Article]:
        merged: list[Article] = []
        key_to_index: dict[str, int] = {}
        for article in [*primary, *secondary]:
            key = self._article_key(article)
            existing_index = key_to_index.get(key) if key else None
            if existing_index is None:
                if key:
                    key_to_index[key] = len(merged)
                merged.append(article.model_copy(deep=True))
                continue
            merged[existing_index] = self._merge_article_pair(merged[existing_index], article)
        for idx, article in enumerate(merged, start=1):
            article.id = idx
        return merged

    def _merge_article_pair(self, preferred: Article, fallback: Article) -> Article:
        data = preferred.model_dump()
        if not data.get("pmid") and fallback.pmid:
            data["pmid"] = fallback.pmid
        if not data.get("doi") and fallback.doi:
            data["doi"] = fallback.doi
        if not data.get("pmc_id") and fallback.pmc_id:
            data["pmc_id"] = fallback.pmc_id
        if not data.get("abstract") and fallback.abstract:
            data["abstract"] = fallback.abstract
        if not data.get("journal") and fallback.journal:
            data["journal"] = fallback.journal
        if not data.get("publication_date") and fallback.publication_date:
            data["publication_date"] = fallback.publication_date
        if not data.get("article_type") and fallback.article_type:
            data["article_type"] = fallback.article_type
        if not data.get("article_types") and fallback.article_types:
            data["article_types"] = fallback.article_types
        if not data.get("authors") and fallback.authors:
            data["authors"] = fallback.authors
        if not data.get("issn_l") and fallback.issn_l:
            data["issn_l"] = fallback.issn_l
        if not data.get("issns") and fallback.issns:
            data["issns"] = fallback.issns
        if not data.get("mesh_terms") and fallback.mesh_terms:
            data["mesh_terms"] = fallback.mesh_terms
        if not data.get("keywords") and fallback.keywords:
            data["keywords"] = fallback.keywords
        if not data.get("related_articles") and fallback.related_articles:
            data["related_articles"] = fallback.related_articles
        if not data.get("journal_quartile") and fallback.journal_quartile:
            data["journal_quartile"] = fallback.journal_quartile
        if not data.get("journal_metric_year") and fallback.journal_metric_year:
            data["journal_metric_year"] = fallback.journal_metric_year
        if not data.get("journal_sjr") and fallback.journal_sjr is not None:
            data["journal_sjr"] = fallback.journal_sjr
        if not data.get("journal_metrics_source") and fallback.journal_metrics_source:
            data["journal_metrics_source"] = fallback.journal_metrics_source
        if (data.get("citation_count") or 0) < (fallback.citation_count or 0):
            data["citation_count"] = fallback.citation_count
        if (data.get("reference_count") or 0) < (fallback.reference_count or 0):
            data["reference_count"] = fallback.reference_count
        return Article(**data)

    def _apply_request_filters(self, articles: list[Article], request: PubMedSearchRequest) -> list[Article]:
        filtered = articles
        if request.article_type:
            query = request.article_type.strip().lower()
            filtered = [
                article
                for article in filtered
                if any(query in item.lower() for item in article.article_types)
                or (article.article_type and query in article.article_type.lower())
            ]
        if request.min_cite is not None:
            filtered = [article for article in filtered if (article.citation_count or 0) >= request.min_cite]
        return filtered

    @staticmethod
    def _normalize_search_resource(value: str | None, default: str = "openalex") -> str:
        normalized = (value or "").strip().lower()
        if normalized in {"openalex", "pubmed", "europe_pmc"}:
            return normalized
        return default

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_doi(value: str | None) -> str | None:
        if not value:
            return None
        lowered = value.strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if lowered.startswith(prefix):
                lowered = lowered[len(prefix):]
        return lowered or None

    @staticmethod
    def _normalize_issn(value: Any) -> str | None:
        text = str(value or "").strip().upper()
        if not text:
            return None
        normalized = "".join(ch for ch in text if ch.isdigit() or ch == "X")
        return normalized or None

    @classmethod
    def _normalize_issn_list(cls, values: Any) -> list[str]:
        if not values:
            return []
        normalized: list[str] = []
        for item in values if isinstance(values, list) else [values]:
            issn = cls._normalize_issn(item)
            if issn and issn not in normalized:
                normalized.append(issn)
        return normalized

    @staticmethod
    def _extract_numeric_id(value: Any) -> str:
        if not value:
            return ""
        text = str(value)
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits

    @staticmethod
    def _extract_pmcid(value: Any) -> str | None:
        if not value:
            return None
        text = str(value).upper()
        if "PMC" in text:
            suffix = text[text.index("PMC") :]
            digits = "".join(ch for ch in suffix if ch.isdigit())
            return f"PMC{digits}" if digits else suffix
        digits = "".join(ch for ch in text if ch.isdigit())
        return f"PMC{digits}" if digits else None

    @staticmethod
    def _article_key(article: Article) -> str | None:
        if article.doi:
            return f"doi:{article.doi.lower()}"
        if article.pmid:
            return f"pmid:{article.pmid}"
        if article.pmc_id:
            return f"pmcid:{article.pmc_id.upper()}"
        title = " ".join((article.title or "").lower().split())
        if not title:
            return None
        return f"title:{title}|year:{article.year or ''}"

    @staticmethod
    def _format_article_type(value: str | None) -> str | None:
        if not value:
            return None
        return str(value).replace("-", " ").title()

    @staticmethod
    def _reconstruct_openalex_abstract(inverted_index: dict[str, list[int]] | None) -> str:
        if not inverted_index:
            return ""
        positions: dict[int, str] = {}
        for token, indexes in inverted_index.items():
            for index in indexes:
                positions[int(index)] = token
        return " ".join(token for _, token in sorted(positions.items()))

    def _enrich_journal_metrics(self, articles: list[Article]) -> None:
        if self.journal_metrics_service is None or not articles:
            return
        self.journal_metrics_service.enrich_articles(articles)

    @staticmethod
    def _openalex_primary_topic_label(raw: dict[str, Any]) -> str | None:
        primary_topic = raw.get("primary_topic") or {}
        label = str(primary_topic.get("display_name") or "").strip()
        return label or None

    @classmethod
    def _openalex_topic_labels(cls, raw: dict[str, Any]) -> list[str]:
        labels: list[str] = []
        primary = cls._openalex_primary_topic_label(raw)
        for topic in raw.get("topics") or []:
            label = str((topic or {}).get("display_name") or "").strip()
            if label and label != primary and label not in labels:
                labels.append(label)
        return labels[:12]

    @staticmethod
    def _openalex_related_work_labels(raw: dict[str, Any]) -> list[str]:
        labels: list[str] = []
        for item in raw.get("related_works") or []:
            text = str(item or "").strip()
            if not text:
                continue
            short = text.rsplit("/", 1)[-1] if "/" in text else text
            if short and short not in labels:
                labels.append(short)
        return labels[:8]
