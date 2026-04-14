"""Modular search adapters for literature discovery."""

from __future__ import annotations

import asyncio
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
import random

import httpx

from app.clients.ncbi import NcbiClient
from app.core.config import Settings
from app.schemas.article import Article
from app.schemas.pubmed import PubMedSearchRequest
from app.utils.rate_limit import AsyncRateLimiter


@dataclass
class SearchResult:
    articles: list[Article]
    request_count: int


class BaseSearchAdapter:
    source_name: str

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        raise NotImplementedError


class PubMedSearchAdapter(BaseSearchAdapter):
    source_name = "pubmed"

    def __init__(self, client: NcbiClient) -> None:
        self.client = client

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        result = await self.client.search_articles(
            query=request.query,
            year_start=request.year_start,
            year_end=request.year_end,
            max_results=max_results,
            batch_size=request.batch_size,
            min_cite=request.min_cite,
            article_type=request.article_type,
        )
        return SearchResult(articles=result.articles, request_count=result.request_count)


class OpenAlexSearchAdapter(BaseSearchAdapter):
    source_name = "openalex"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.openalex_requests_per_second)

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        await self.rate_limiter.wait()
        await asyncio.sleep(0.05 + random.uniform(0.0, 0.03))
        params: dict[str, Any] = {
            "search": request.query.strip(),
            "per-page": min(max_results, 200),
            "select": (
                "id,display_name,publication_year,publication_date,doi,ids,primary_location,best_oa_location,"
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
            response = await self.http_client.get(
                f"{self.settings.openalex_base_url}/works",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError:
            return SearchResult(articles=[], request_count=1)

        rows = payload.get("results", []) if isinstance(payload, dict) else []
        articles = [self._article_from_openalex(index + 1, row) for index, row in enumerate(rows)]
        return SearchResult(articles=articles[:max_results], request_count=1)

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.settings.request_user_agent}
        if self.settings.openalex_api_key:
            headers["Authorization"] = f"Bearer {self.settings.openalex_api_key}"
        return headers

    @staticmethod
    def _openalex_text_list(items: list[dict[str, Any]] | None) -> list[str]:
        labels: list[str] = []
        for item in items or []:
            label = str(item.get("display_name") or "").strip()
            if label and label not in labels:
                labels.append(label)
        return labels

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
        if not inverted_index:
            return ""
        indexed_tokens: list[tuple[int, str]] = []
        for token, positions in inverted_index.items():
            for position in positions:
                indexed_tokens.append((position, token))
        indexed_tokens.sort()
        return " ".join(token for _position, token in indexed_tokens)

    @staticmethod
    def _extract_pmid(ids: dict[str, Any] | None) -> str:
        pmid_url = str((ids or {}).get("pmid") or "")
        return pmid_url.rstrip("/").rsplit("/", 1)[-1] if pmid_url else ""

    def _article_from_openalex(self, index: int, raw: dict[str, Any]) -> Article:
        doi = str(raw.get("doi") or "").replace("https://doi.org/", "") or None
        primary_location = raw.get("primary_location") or raw.get("best_oa_location") or {}
        source = primary_location.get("source") if isinstance(primary_location, dict) else {}
        authors = []
        for authorship in raw.get("authorships", []) or []:
            author_name = ((authorship or {}).get("author") or {}).get("display_name")
            if author_name:
                authors.append(str(author_name))
        topics = self._openalex_text_list(raw.get("topics"))
        primary_topic = str(((raw.get("primary_topic") or {}).get("display_name") or "")).strip() or None
        keywords = topics[1:] if len(topics) > 1 else []
        mesh_terms = [primary_topic] if primary_topic else []
        related = [str(item).rstrip("/").rsplit("/", 1)[-1] for item in raw.get("related_works", []) or []]
        return Article(
            id=index,
            pmid=self._extract_pmid(raw.get("ids")),
            title=str(raw.get("display_name") or "Title not available"),
            abstract=self._reconstruct_abstract(raw.get("abstract_inverted_index")),
            year=str(raw.get("publication_year") or "") or None,
            journal=((source or {}).get("display_name") if isinstance(source, dict) else None),
            publication_date=str(raw.get("publication_date") or "") or None,
            article_type=str(raw.get("type") or "") or None,
            article_types=[str(raw.get("type") or "")] if raw.get("type") else [],
            citation_count=int(raw.get("cited_by_count") or 0),
            authors=authors,
            keywords=keywords,
            mesh_terms=mesh_terms,
            related_articles=related,
            reference_count=int(raw.get("referenced_works_count") or 0),
            doi=doi,
            oa_pdf_url=((primary_location or {}).get("pdf_url") if isinstance(primary_location, dict) else None),
            landing_page_url=((primary_location or {}).get("landing_page_url") if isinstance(primary_location, dict) else None),
        )


class EuropePMCSearchAdapter(BaseSearchAdapter):
    source_name = "europe_pmc"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.europe_pmc_requests_per_second)

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        await self.rate_limiter.wait()
        await asyncio.sleep(0.05 + random.uniform(0.0, 0.03))
        query = request.query.strip()
        if self.settings.pubmed_oa_only:
            query = f"({query}) AND OPEN_ACCESS:y"
        params = {
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
            return SearchResult(articles=[], request_count=1)
        rows = ((payload.get("resultList") or {}).get("result") or []) if isinstance(payload, dict) else []
        articles = [self._article_from_europe_pmc(index + 1, row) for index, row in enumerate(rows)]
        return SearchResult(articles=articles[:max_results], request_count=1)

    @staticmethod
    def _article_from_europe_pmc(index: int, raw: dict[str, Any]) -> Article:
        author_string = str(raw.get("authorString") or "")
        authors = [item.strip() for item in author_string.split(",") if item.strip()]
        fulltext_urls = ((raw.get("fullTextUrlList") or {}).get("fullTextUrl") or []) if isinstance(raw, dict) else []
        oa_pdf_url = None
        landing_page_url = None
        for entry in fulltext_urls:
            url = str((entry or {}).get("url") or "").strip()
            if not url:
                continue
            style = str((entry or {}).get("documentStyle") or "").lower()
            if oa_pdf_url is None and ("pdf" in style or url.lower().endswith(".pdf") or "pdf" in url.lower()):
                oa_pdf_url = url
            if landing_page_url is None and ("html" in style or "abstract" not in style):
                landing_page_url = url
        return Article(
            id=index,
            pmid=str(raw.get("pmid") or ""),
            title=str(raw.get("title") or "Title not available"),
            abstract=str(raw.get("abstractText") or ""),
            year=str(raw.get("pubYear") or "") or None,
            journal=str(raw.get("journalTitle") or "") or None,
            publication_date=str(raw.get("firstPublicationDate") or "") or None,
            citation_count=int(raw.get("citedByCount") or 0),
            authors=authors,
            doi=str(raw.get("doi") or "") or None,
            pmc_id=str(raw.get("pmcid") or "") or None,
            oa_pdf_url=oa_pdf_url,
            landing_page_url=landing_page_url,
        )


class PMCSearchAdapter(BaseSearchAdapter):
    source_name = "pmc"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.pubmed_requests_per_second)

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        await self.rate_limiter.wait()
        await asyncio.sleep(0.08 + random.uniform(0.0, 0.04))
        params = {
            "db": "pmc",
            "term": request.query.strip(),
            "retmode": "json",
            "retmax": min(max_results, 100),
            "sort": "relevance",
        }
        try:
            search_response = await self.http_client.get("/esearch.fcgi", params=self._augment_params(params))
            search_response.raise_for_status()
            id_list = (((search_response.json() or {}).get("esearchresult") or {}).get("idlist") or [])
        except httpx.HTTPError:
            return SearchResult(articles=[], request_count=1)
        if not id_list:
            return SearchResult(articles=[], request_count=1)
        await self.rate_limiter.wait()
        try:
            fetch_response = await self.http_client.get(
                "/efetch.fcgi",
                params=self._augment_params(
                    {
                        "db": "pmc",
                        "id": ",".join(str(item) for item in id_list),
                        "retmode": "xml",
                    }
                ),
            )
            fetch_response.raise_for_status()
        except httpx.HTTPError:
            return SearchResult(articles=[], request_count=2)
        return SearchResult(articles=self._parse_pmc_fetch(fetch_response.text)[:max_results], request_count=2)

    def _augment_params(self, params: dict[str, str | int]) -> dict[str, str | int]:
        if self.settings.ncbi_api_key:
            params = dict(params)
            params["api_key"] = self.settings.ncbi_api_key
        return params

    @staticmethod
    def _parse_pmc_fetch(xml_text: str) -> list[Article]:
        root = ET.fromstring(xml_text)
        articles: list[Article] = []
        for index, article in enumerate(root.findall(".//article"), start=1):
            title = "".join(article.findtext(".//article-title") or "").strip() or "Title not available"
            journal = (article.findtext(".//journal-title") or "").strip() or None
            year = (article.findtext(".//pub-date/year") or "").strip() or None
            abstract_parts = [part.text or "" for part in article.findall(".//abstract//p")]
            abstract = " ".join(part.strip() for part in abstract_parts if part.strip())
            doi = None
            pmc_id = None
            pmid = ""
            for identifier in article.findall(".//article-id"):
                id_type = str(identifier.attrib.get("pub-id-type") or "").lower()
                value = (identifier.text or "").strip()
                if not value:
                    continue
                if id_type == "doi":
                    doi = value
                elif id_type == "pmc":
                    pmc_id = value if value.startswith("PMC") else f"PMC{value}"
                elif id_type == "pmid":
                    pmid = value
            articles.append(
                Article(
                    id=index,
                    pmid=pmid,
                    title=title,
                    abstract=abstract,
                    year=year,
                    journal=journal,
                    doi=doi,
                    pmc_id=pmc_id,
                    landing_page_url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/" if pmc_id else None,
                )
            )
        return articles
