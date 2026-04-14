"""NCBI E-utilities client."""

from __future__ import annotations

import asyncio
import time
import random
from dataclasses import dataclass

import httpx

from app.core.config import Settings
from app.schemas.article import Article
from app.utils.pubmed_xml import parse_pubmed_fetch_xml
from app.utils.rate_limit import AsyncRateLimiter


@dataclass
class PubMedFetchResult:
    full_query: str
    oa_only: bool
    total_results_found: int
    batch_size_used: int
    request_count: int
    elapsed_ms: int
    articles: list[Article]


class NcbiClient:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings
        self.rate_limiter = AsyncRateLimiter(settings.pubmed_requests_per_second)

    async def search_articles(
        self,
        query: str,
        year_start: int | None,
        year_end: int | None,
        max_results: int,
        batch_size: int | None,
        min_cite: int | None = None,
        article_type: str | None = None,
    ) -> PubMedFetchResult:
        started = time.perf_counter()
        request_count = 0
        citation_filter_mode = min_cite is not None
        requested_results = min(max_results * 4, 200) if citation_filter_mode else max_results
        batch_size_used = min(
            self.settings.pubmed_max_batch_size,
            requested_results,
        )
        full_query = build_pubmed_query(
            query,
            year_start,
            year_end,
            oa_only=self.settings.pubmed_oa_only,
        )
        oa_only = pubmed_query_has_oa_filter(full_query)

        async def request_json(path: str, params: dict[str, str | int]) -> dict:
            nonlocal request_count
            response = await request_response(path, params)
            return response.json()

        async def request_text(path: str, params: dict[str, str | int]) -> str:
            nonlocal request_count
            response = await request_response(path, params)
            return response.text

        async def request_response(path: str, params: dict[str, str | int]) -> httpx.Response:
            nonlocal request_count
            attempts = 3
            last_error: httpx.HTTPError | None = None
            for attempt in range(attempts):
                request_count += 1
                await self.rate_limiter.wait()
                await asyncio.sleep(0.08 + random.uniform(0.0, 0.05))
                try:
                    response = await self.http_client.get(path, params=self._augment_params(params))
                    response.raise_for_status()
                    return response
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    status = exc.response.status_code
                    retryable = status in {400, 408, 409, 425, 429, 500, 502, 503, 504}
                    if attempt >= attempts - 1 or not retryable:
                        raise
                    await asyncio.sleep(0.75 * (attempt + 1))
                except httpx.HTTPError as exc:
                    last_error = exc
                    if attempt >= attempts - 1:
                        raise
                    await asyncio.sleep(0.75 * (attempt + 1))
            assert last_error is not None
            raise last_error

        async def request_related_map(pmids: list[str]) -> dict[str, list[str]]:
            if not pmids:
                return {}
            try:
                xml_text = await asyncio.wait_for(
                    request_text(
                        "/elink.fcgi",
                        {
                            "dbfrom": "pubmed",
                            "db": "pubmed",
                            "id": ",".join(pmids),
                            "linkname": "pubmed_pubmed",
                            "retmode": "xml",
                        },
                    ),
                    timeout=4.0,
                )
            except (asyncio.TimeoutError, httpx.HTTPError):
                return {}
            return parse_related_articles_xml(xml_text)

        search_data = await request_json(
            "/esearch.fcgi",
            {
                "db": "pubmed",
                "term": full_query,
                "retmode": "json",
                "retmax": 0,
                "sort": "relevance",
                "usehistory": "y",
            },
        )
        esearch = search_data.get("esearchresult", {})
        total_results_found = int(esearch.get("count", 0))
        if total_results_found == 0:
            return PubMedFetchResult(
                full_query=full_query,
                oa_only=oa_only,
                total_results_found=0,
                batch_size_used=batch_size_used,
                request_count=request_count,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                articles=[],
            )

        query_key = esearch.get("querykey")
        webenv = esearch.get("webenv")
        results_to_fetch = min(requested_results, total_results_found)
        articles: list[Article] = []

        async def fetch_batch(retstart: int, current_batch: int, start_index: int) -> list[Article]:
            fetch_params = {
                "db": "pubmed",
                "query_key": query_key,
                "WebEnv": webenv,
                "retmode": "xml",
                "rettype": "abstract",
                "retstart": retstart,
                "retmax": current_batch,
            }
            try:
                fetch_text = await request_text("/efetch.fcgi", fetch_params)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if current_batch > 100 and status in {400, 408, 409, 425, 429, 500, 502, 503, 504}:
                    left_size = current_batch // 2
                    right_size = current_batch - left_size
                    left_articles = await fetch_batch(retstart, left_size, start_index)
                    right_articles = await fetch_batch(
                        retstart + left_size,
                        right_size,
                        start_index + len(left_articles),
                    )
                    return [*left_articles, *right_articles]
                raise
            parsed_fetch = parse_pubmed_fetch_xml(fetch_text)
            related_task = asyncio.create_task(request_related_map(list(parsed_fetch.keys())))
            batch_articles = self._merge_summary_and_fetch(None, parsed_fetch, start_index)
            related_map = await related_task
            for article in batch_articles:
                article.related_articles = related_map.get(article.pmid, [])
            return batch_articles

        for retstart in range(0, results_to_fetch, batch_size_used):
            current_batch = min(batch_size_used, results_to_fetch - retstart)
            batch_articles = await fetch_batch(retstart, current_batch, len(articles))
            articles.extend(batch_articles)

        filtered_articles = self._apply_type_filter(
            articles,
            article_type=article_type,
        )
        if citation_filter_mode:
            await self._enrich_citation_counts(filtered_articles)
            filtered_articles = [
                article for article in filtered_articles if (article.citation_count or 0) >= (min_cite or 0)
            ]
        filtered_articles = filtered_articles[:max_results]

        return PubMedFetchResult(
            full_query=full_query,
            oa_only=oa_only,
            total_results_found=total_results_found,
            batch_size_used=batch_size_used,
            request_count=request_count,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            articles=filtered_articles,
        )

    def _augment_params(self, params: dict[str, str | int]) -> dict[str, str | int]:
        if self.settings.ncbi_api_key:
            params = dict(params)
            params["api_key"] = self.settings.ncbi_api_key
        return params

    def _merge_summary_and_fetch(
        self, summary_data: dict | None, parsed_fetch: dict[str, dict[str, object]], start_index: int
    ) -> list[Article]:
        result = (summary_data or {}).get("result", {})
        uids = result.get("uids", []) or list(parsed_fetch.keys())
        articles: list[Article] = []
        for offset, uid in enumerate(uids, start=1):
            summary = result.get(uid, {})
            details = parsed_fetch.get(uid, {})
            articles.append(
                Article(
                    id=start_index + offset,
                    pmid=uid,
                    title=details.get("title") or summary.get("title") or "Title not available",
                    abstract=(details.get("abstract") or "").strip(),
                    year=extract_year(str(details.get("publication_date") or summary.get("pubdate") or "")),
                    journal=details.get("journal") or summary.get("fulljournalname"),
                    publication_date=(details.get("publication_date") or summary.get("pubdate") or None),
                    article_type=details.get("article_type"),
                    article_types=list(details.get("article_types") or []),
                    authors=list(details.get("authors") or []),
                    keywords=list(details.get("keywords") or []),
                    mesh_terms=list(details.get("mesh_terms") or []),
                    reference_count=int(details.get("reference_count") or 0),
                    doi=details.get("doi"),
                    pmc_id=details.get("pmc_id"),
                    issn_l=details.get("issn_l"),
                    issns=list(details.get("issns") or []),
                )
            )
        return articles

    @staticmethod
    def _apply_type_filter(
        articles: list[Article],
        *,
        article_type: str | None,
    ) -> list[Article]:
        filtered = articles
        if article_type:
            query = article_type.strip().lower()
            filtered = [
                article
                for article in filtered
                if any(query in item.lower() for item in article.article_types) or (article.article_type and query in article.article_type.lower())
            ]
        return filtered

    async def _enrich_citation_counts(
        self,
        articles: list[Article],
    ) -> None:
        semaphore = asyncio.Semaphore(8)

        async def worker(article: Article) -> None:
            async with semaphore:
                article.citation_count = await self._fetch_citation_count(article)

        await asyncio.gather(*(worker(article) for article in articles))

    async def _fetch_citation_count(self, article: Article) -> int | None:
        openalex = await self._openalex_citation_count(article)
        if openalex is not None:
            return openalex
        return await self._europe_pmc_citation_count(article)

    async def enrich_citation_counts(self, articles: list[Article]) -> list[Article]:
        await self._enrich_citation_counts(articles)
        return articles

    async def _openalex_citation_count(self, article: Article) -> int | None:
        filters: list[str] = []
        if article.doi:
            filters.append(f"doi:https://doi.org/{article.doi}")
        elif article.pmid:
            filters.append(f"pmid:{article.pmid}")
        if not filters:
            return None
        try:
            await self.rate_limiter.wait()
            headers = {"User-Agent": self.settings.request_user_agent}
            if self.settings.openalex_api_key:
                headers["Authorization"] = f"Bearer {self.settings.openalex_api_key}"
            response = await self.http_client.get(
                self.settings.openalex_base_url + "/works",
                params={"filter": filters[0], "select": "cited_by_count"},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])
            if not results:
                return None
            value = results[0].get("cited_by_count")
            return int(value) if value is not None else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None

    async def _europe_pmc_citation_count(self, article: Article) -> int | None:
        if not article.pmid and not article.doi:
            return None
        query = f"EXT_ID:{article.pmid} AND SRC:MED" if article.pmid else f'DOI:"{article.doi}"'
        try:
            await self.rate_limiter.wait()
            response = await self.http_client.get(
                self.settings.europe_pmc_base_url + "/search",
                params={
                    "query": query,
                    "format": "json",
                    "pageSize": "1",
                    "resultType": "core",
                },
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("resultList", {}).get("result", [])
            if not results:
                return None
            value = results[0].get("citedByCount")
            return int(value) if value is not None else None
        except (httpx.HTTPError, ValueError, TypeError):
            return None


def pubmed_query_has_oa_filter(query: str) -> bool:
    normalized = query.strip().lower()
    return any(
        marker in normalized
        for marker in (
            "free full text[sb]",
            '"free full text"[sb]',
            "loattrfree full text[sb]",
            "open access[filter]",
        )
    )


def build_pubmed_query(
    query: str,
    year_start: int | None,
    year_end: int | None,
    *,
    oa_only: bool = False,
) -> str:
    base_query = query.strip()
    if oa_only and not pubmed_query_has_oa_filter(base_query):
        base_query = f"({base_query}) AND free full text[sb]"
    if year_start is None and year_end is None:
        return base_query
    if year_start is not None and year_end is not None:
        return (
            f'{base_query} AND ("{year_start}/01/01"[Date - Publication] : '
            f'"{year_end}/12/31"[Date - Publication])'
        )
    if year_start is not None:
        return f'{base_query} AND ("{year_start}/01/01"[Date - Publication] : "3000"[Date - Publication])'
    return f'{base_query} AND ("1000/01/01"[Date - Publication] : "{year_end}/12/31"[Date - Publication])'


def extract_year(pubdate: str) -> str | None:
    for token in pubdate.split():
        if token.isdigit() and len(token) == 4:
            return token
    digits = "".join(ch if ch.isdigit() else " " for ch in pubdate).split()
    for token in digits:
        if len(token) == 4:
            return token
    return None


def parse_related_articles_xml(xml_text: str) -> dict[str, list[str]]:
    from xml.etree import ElementTree as ET

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    related_map: dict[str, list[str]] = {}
    for link_set in root.findall(".//LinkSet"):
        source_id = link_set.findtext("./IdList/Id")
        if not source_id:
            continue
        related_ids: list[str] = []
        seen: set[str] = set()
        for related in link_set.findall(".//LinkSetDb/Link/Id"):
            value = (related.text or "").strip()
            if not value or value == source_id or value in seen:
                continue
            seen.add(value)
            related_ids.append(value)
        related_map[source_id] = related_ids[:10]
    return related_map
