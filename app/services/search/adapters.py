"""Modular search adapters for literature discovery."""

from __future__ import annotations

import asyncio
import re
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
    total_results_found: int | None = None


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
        return SearchResult(
            articles=result.articles,
            request_count=result.request_count,
            total_results_found=result.total_results_found,
        )


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
        total_results = int(((payload or {}).get("meta") or {}).get("count") or len(rows) or len(articles))
        return SearchResult(articles=articles[:max_results], request_count=1, total_results_found=total_results)

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
            source_name="openalex",
            source_record_id=str(raw.get("id") or "").rstrip("/").rsplit("/", 1)[-1] or None,
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
        total_results = int((payload.get("hitCount") or payload.get("hitcount") or len(rows) or len(articles)) if isinstance(payload, dict) else len(articles))
        return SearchResult(articles=articles[:max_results], request_count=1, total_results_found=total_results)

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
            source_name="europe_pmc",
            source_record_id=str(raw.get("id") or raw.get("pmcid") or raw.get("pmid") or "") or None,
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
            search_payload = search_response.json() or {}
            search_result = search_payload.get("esearchresult") or {}
            id_list = search_result.get("idlist") or []
            total_results = int(search_result.get("count", 0) or 0)
        except httpx.HTTPError:
            return SearchResult(articles=[], request_count=1)
        if not id_list:
            return SearchResult(articles=[], request_count=1, total_results_found=total_results)
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
            return SearchResult(articles=[], request_count=2, total_results_found=total_results)
        return SearchResult(
            articles=self._parse_pmc_fetch(fetch_response.text)[:max_results],
            request_count=2,
            total_results_found=total_results,
        )

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
                    source_name="pmc",
                    source_record_id=pmc_id or pmid or None,
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


class CoreSearchAdapter(BaseSearchAdapter):
    source_name = "core"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.core_requests_per_second)

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        if not self.settings.core_api_key:
            return SearchResult(articles=[], request_count=0, total_results_found=0)
        headers = {
            "User-Agent": self.settings.request_user_agent,
            "Authorization": self.settings.core_api_key,
        }
        page_size = min(max(max_results * 2, 25), 100)
        query = self._build_core_query(request)
        max_pages = 4 if (request.year_start is not None or request.year_end is not None or self.settings.pubmed_oa_only) else 6
        request_count = 0
        total_results: int | None = None
        articles: list[Article] = []
        recent_matches = 0
        consecutive_failures = 0

        for offset in range(0, page_size * max_pages, page_size):
            await self.rate_limiter.wait()
            await asyncio.sleep(0.05 + random.uniform(0.0, 0.03))
            request_count += 1
            try:
                response = await self.http_client.get(
                    f"{self.settings.core_base_url.rstrip('/')}/search/works",
                    params={"q": query, "limit": page_size, "offset": offset},
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json() or {}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in {429, 500, 502, 503, 504} and consecutive_failures < 2:
                    consecutive_failures += 1
                    await asyncio.sleep(0.4 * consecutive_failures)
                    continue
                if request_count == 1:
                    return SearchResult(articles=[], request_count=1)
                break
            except ValueError:
                if consecutive_failures < 2:
                    consecutive_failures += 1
                    continue
                break
            except httpx.HTTPError:
                break

            rows = payload.get("results") or []
            consecutive_failures = 0
            total_results = int(payload.get("totalHits") or payload.get("total_hits") or total_results or 0)
            page_articles = [
                self._article_from_core(len(articles) + index + 1, row)
                for index, row in enumerate(rows)
                if isinstance(row, dict)
            ]
            articles.extend(page_articles)
            recent_matches += sum(
                1 for article in page_articles if self._matches_year_window(article, request.year_start, request.year_end)
            )

            if recent_matches >= max_results:
                break
            if not rows or (total_results is not None and offset + page_size >= total_results):
                break

        return SearchResult(
            articles=articles,
            request_count=request_count,
            total_results_found=total_results or len(articles),
        )

    def _build_core_query(self, request: PubMedSearchRequest) -> str:
        parts = [request.query.strip()]
        year_filter = self._core_year_filter(request.year_start, request.year_end)
        if year_filter:
            parts.append(year_filter)
        if self.settings.pubmed_oa_only:
            parts.append("fullText:true")
        return " AND ".join(part for part in parts if part)

    @staticmethod
    def _core_year_filter(year_start: int | None, year_end: int | None) -> str | None:
        if year_start is None and year_end is None:
            return None
        start = year_start if year_start is not None else year_end
        end = year_end if year_end is not None else year_start
        if start is None or end is None:
            return None
        if start > end:
            start, end = end, start
        if end - start > 10:
            return None
        return "(" + " OR ".join(f"yearPublished:{year}" for year in range(end, start - 1, -1)) + ")"

    @staticmethod
    def _matches_year_window(article: Article, year_start: int | None, year_end: int | None) -> bool:
        year_value = str(article.year or "").strip()
        if not year_value.isdigit():
            return False
        year = int(year_value)
        if year_start is not None and year < year_start:
            return False
        if year_end is not None and year > year_end:
            return False
        return True

    @staticmethod
    def _core_authors(raw: dict[str, Any]) -> list[str]:
        authors: list[str] = []
        for item in raw.get("authors") or []:
            if isinstance(item, str):
                label = item.strip()
            elif isinstance(item, dict):
                label = str(item.get("name") or item.get("displayName") or "").strip()
            else:
                label = ""
            if label and label not in authors:
                authors.append(label)
        return authors

    @staticmethod
    def _core_journal(raw: dict[str, Any]) -> tuple[str | None, list[str]]:
        journals = raw.get("journals") or []
        journal_name: str | None = None
        identifiers: list[str] = []
        for item in journals:
            if not isinstance(item, dict):
                continue
            if journal_name is None:
                journal_name = str(item.get("title") or item.get("name") or "").strip() or None
            for identifier in item.get("identifiers") or []:
                value = str(identifier or "").strip()
                if value and value not in identifiers:
                    identifiers.append(value)
        if journal_name is None:
            journal_name = str(raw.get("publisher") or "").strip() or None
        return journal_name, identifiers

    @staticmethod
    def _core_identifier(raw: dict[str, Any], target_type: str) -> str | None:
        expected = target_type.strip().upper()
        for item in raw.get("identifiers") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").strip().upper() != expected:
                continue
            value = str(item.get("identifier") or "").strip()
            if value:
                return value
        return None

    @staticmethod
    def _core_document_types(raw: dict[str, Any]) -> tuple[str | None, list[str]]:
        value = raw.get("documentType")
        if isinstance(value, list):
            types = [str(item).strip() for item in value if str(item).strip()]
        else:
            text = str(value or "").strip()
            types = [text] if text else []
        return (types[0] if types else None), types

    @staticmethod
    def _core_keywords(raw: dict[str, Any]) -> list[str]:
        for key in ("topics", "subjects", "keywords"):
            values = raw.get(key) or []
            labels: list[str] = []
            for item in values:
                if isinstance(item, str):
                    label = item.strip()
                elif isinstance(item, dict):
                    label = str(item.get("name") or item.get("label") or item.get("display_name") or "").strip()
                else:
                    label = ""
                if label and label not in labels:
                    labels.append(label)
            if labels:
                return labels
        return []

    @staticmethod
    def _normalize_core_download_url(url: str) -> str:
        value = url.strip()
        if not value:
            return ""
        lowered = value.lower()
        if "arxiv.org/abs/" in lowered:
            record_id = value.rstrip("/").rsplit("/", 1)[-1]
            return f"https://arxiv.org/pdf/{record_id}.pdf"
        return value

    @staticmethod
    def _core_fulltext_urls(raw: dict[str, Any]) -> tuple[str | None, str | None]:
        download_url = CoreSearchAdapter._normalize_core_download_url(str(raw.get("downloadUrl") or ""))
        download_url = download_url or None
        landing_url: str | None = None
        for item in raw.get("links") or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            link_type = str(item.get("type") or "").strip().lower()
            normalized_url = CoreSearchAdapter._normalize_core_download_url(url)
            if link_type == "download" and normalized_url and download_url is None:
                download_url = normalized_url
            if link_type in {"display", "reader"} and landing_url is None:
                landing_url = url
        for item in raw.get("sourceFulltextUrls") or []:
            if isinstance(item, str):
                url = item.strip()
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
            else:
                url = ""
            if not url:
                continue
            normalized_url = CoreSearchAdapter._normalize_core_download_url(url)
            if landing_url is None and ".pdf" not in url.lower():
                landing_url = url
            if download_url is None:
                download_url = normalized_url or url
        return download_url, landing_url

    def _article_from_core(self, index: int, raw: dict[str, Any]) -> Article:
        doi = (
            str(raw.get("doi") or "").strip().removeprefix("https://doi.org/").removeprefix("doi:")
            or self._core_identifier(raw, "DOI")
            or None
        )
        journal, issns = self._core_journal(raw)
        article_type, article_types = self._core_document_types(raw)
        oa_pdf_url, landing_page_url = self._core_fulltext_urls(raw)
        published = str(raw.get("publishedDate") or "").strip() or None
        year = str(raw.get("yearPublished") or "").strip() or None
        pmid = str(raw.get("pubmedId") or self._core_identifier(raw, "PMID") or "").strip()
        if landing_page_url is None and doi:
            landing_page_url = f"https://doi.org/{doi}"
        return Article(
            id=index,
            source_name="core",
            source_record_id=str(raw.get("id") or "").strip() or None,
            pmid=pmid,
            title=str(raw.get("title") or "Title not available"),
            abstract=str(raw.get("abstract") or ""),
            year=year or (published[:4] if published else None),
            journal=journal,
            publication_date=published,
            article_type=article_type,
            article_types=article_types,
            citation_count=int(raw.get("citationCount") or 0),
            authors=self._core_authors(raw),
            keywords=self._core_keywords(raw),
            doi=doi,
            oa_pdf_url=oa_pdf_url,
            landing_page_url=landing_page_url,
            issns=issns,
        )


class ArxivSearchAdapter(BaseSearchAdapter):
    source_name = "arxiv"

    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.arxiv_requests_per_second)

    async def search(self, request: PubMedSearchRequest, *, max_results: int) -> SearchResult:
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
            "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
        }
        page_size = min(max(max_results * 4, 25), 100)
        request_count = 0
        total_results: int | None = None
        articles: list[Article] = []
        recent_matches = 0
        max_pages = 4

        for start in range(0, page_size * max_pages, page_size):
            await self.rate_limiter.wait()
            await asyncio.sleep(0.05 + random.uniform(0.0, 0.03))
            request_count += 1
            params = {
                "search_query": self._build_arxiv_query(request.query),
                "start": start,
                "max_results": page_size,
                "sortBy": "submittedDate" if (request.year_start is not None or request.year_end is not None) else "relevance",
                "sortOrder": "descending",
            }
            try:
                response = await self.http_client.get(
                    self.settings.arxiv_base_url,
                    params=params,
                    headers={"User-Agent": self.settings.request_user_agent},
                )
                response.raise_for_status()
                root = ET.fromstring(response.text)
            except (httpx.HTTPError, ET.ParseError):
                if request_count == 1:
                    return SearchResult(articles=[], request_count=1)
                break

            entries = root.findall("atom:entry", ns)
            total_results = int(root.findtext("opensearch:totalResults", default=str(len(entries)), namespaces=ns) or len(entries))
            page_articles = [
                self._article_from_arxiv(len(articles) + index + 1, entry, ns)
                for index, entry in enumerate(entries)
            ]
            articles.extend(page_articles)
            recent_matches += sum(
                1 for article in page_articles if self._matches_year_window(article, request.year_start, request.year_end)
            )

            if recent_matches >= max_results:
                break
            if len(entries) < page_size or (total_results is not None and start + page_size >= total_results):
                break

        return SearchResult(
            articles=articles,
            request_count=request_count,
            total_results_found=total_results or len(articles),
        )

    @staticmethod
    def _clean_text(value: str | None) -> str:
        return " ".join((value or "").split()).strip()

    @classmethod
    def _build_arxiv_query(cls, query: str) -> str:
        normalized = cls._clean_text(query)
        if not normalized:
            return "all:*"
        lowered = normalized.lower()
        if any(token in lowered for token in ("all:", "ti:", "au:", "abs:", "cat:", "and", "or", "not")):
            return normalized
        terms = [term for term in re.findall(r"[a-z0-9]+", lowered) if term]
        if not terms:
            return normalized
        return " AND ".join(f"all:{term}" for term in terms[:8])

    @staticmethod
    def _matches_year_window(article: Article, year_start: int | None, year_end: int | None) -> bool:
        year_value = str(article.year or "").strip()
        if not year_value.isdigit():
            return False
        year = int(year_value)
        if year_start is not None and year < year_start:
            return False
        if year_end is not None and year > year_end:
            return False
        return True

    def _article_from_arxiv(
        self,
        index: int,
        entry: ET.Element,
        ns: dict[str, str],
    ) -> Article:
        entry_id = self._clean_text(entry.findtext("atom:id", default="", namespaces=ns))
        record_id = entry_id.rstrip("/").rsplit("/", 1)[-1] or None
        authors = [
            self._clean_text(author.findtext("atom:name", default="", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        authors = [name for name in authors if name]
        categories: list[str] = []
        for category in entry.findall("atom:category", ns):
            term = self._clean_text(category.attrib.get("term"))
            if term and term not in categories:
                categories.append(term)
        primary_category_element = entry.find("arxiv:primary_category", ns)
        primary_category = self._clean_text(
            primary_category_element.attrib.get("term") if primary_category_element is not None else ""
        ) or None
        doi = self._clean_text(entry.findtext("arxiv:doi", default="", namespaces=ns)) or None
        journal_ref = self._clean_text(entry.findtext("arxiv:journal_ref", default="", namespaces=ns)) or None
        pdf_url = None
        for link in entry.findall("atom:link", ns):
            href = self._clean_text(link.attrib.get("href"))
            if link.attrib.get("type") == "application/pdf" and href:
                pdf_url = href
                break
        published = self._clean_text(entry.findtext("atom:published", default="", namespaces=ns)) or None
        return Article(
            id=index,
            source_name="arxiv",
            source_record_id=record_id,
            pmid="",
            title=self._clean_text(entry.findtext("atom:title", default="Title not available", namespaces=ns)),
            abstract=self._clean_text(entry.findtext("atom:summary", default="", namespaces=ns)),
            year=published[:4] if published else None,
            journal=journal_ref or "arXiv",
            publication_date=published,
            article_type="preprint",
            article_types=["preprint"],
            authors=authors,
            keywords=categories,
            mesh_terms=[primary_category] if primary_category else [],
            doi=doi,
            oa_pdf_url=pdf_url,
            landing_page_url=entry_id or None,
        )
