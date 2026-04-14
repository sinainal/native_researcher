#!/usr/bin/env python3
"""Standalone single-article downloader prototype with hard time budgets."""

from __future__ import annotations

import argparse
import asyncio
import io
import ipaddress
import json
import math
import re
import tarfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse, urlunparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_USER_AGENT = "new_method/0.1 single-article downloader"
PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
NCBI_ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"
EUROPE_PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_REPO_URL = "https://europepmc.org/api/fulltextRepo"
OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
DOAJ_SEARCH_URL = "https://doaj.org/api/search/articles"
DOI_BASE_URL = "https://doi.org"
TRUSTED_DIRECT_HOSTS = {
    "link.springer.com",
    "www.nature.com",
    "tandfonline.com",
    "www.tandfonline.com",
    "cdn.ncbi.nlm.nih.gov",
    "ftp.ncbi.nlm.nih.gov",
    "europepmc.org",
}
RANGE_OPTIMIZED_HOSTS = {
    "link.springer.com",
    "www.nature.com",
}


@dataclass
class ArticleRef:
    pmid: str | None = None
    doi: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    year: str | None = None
    journal: str | None = None
    oa_pdf_url: str | None = None
    landing_page_url: str | None = None


@dataclass
class Candidate:
    source: str
    url: str
    priority: int


@dataclass
class AttemptLog:
    step: str
    source: str
    status: str
    elapsed_ms: int
    url: str | None = None
    detail: str | None = None
    status_code: int | None = None


@dataclass
class Result:
    article: dict[str, Any]
    mode: str
    success: bool
    source: str | None
    url: str | None
    file_path: str | None
    total_ms: int
    attempts: list[dict[str, Any]] = field(default_factory=list)
    candidate_count: int = 0
    note: str | None = None


class SingleArticleDownloader:
    def __init__(self, *, mode: str, output_dir: Path, budget_seconds: float = 60.0, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.mode = mode
        self.output_dir = output_dir
        self.budget_seconds = budget_seconds
        self.user_agent = user_agent
        self.attempts: list[AttemptLog] = []
        self._started = time.perf_counter()
        self._metadata_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=4.0, read=4.0, write=4.0, pool=2.0),
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )
        self._download_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=25.0, write=25.0, pool=5.0),
            headers={"User-Agent": user_agent},
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._metadata_client.aclose()
        await self._download_client.aclose()

    def _elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._started) * 1000)

    def _remaining_budget(self) -> float:
        remaining = self.budget_seconds - (time.perf_counter() - self._started)
        return max(0.0, remaining)

    def _log(self, *, step: str, source: str, status: str, started: float, url: str | None = None,
             detail: str | None = None, status_code: int | None = None) -> None:
        self.attempts.append(
            AttemptLog(
                step=step,
                source=source,
                status=status,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                url=url,
                detail=detail,
                status_code=status_code,
            )
        )

    async def _with_outer_timeout(self, seconds: float, coro: Awaitable[Any]) -> Any:
        timeout_value = min(seconds, self._remaining_budget())
        if timeout_value <= 0:
            close = getattr(coro, "close", None)
            if callable(close):
                close()
            raise TimeoutError("No remaining budget.")
        return await asyncio.wait_for(coro, timeout=timeout_value)

    async def _get_text(self, url: str, *, params: dict[str, str] | None = None) -> str | None:
        return await self._request_text_with_retry(url, params=params)

    async def _get_json(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        response = await self._request_response_with_retry(url, params=params)
        if response is None:
            return None
        try:
            return response.json()
        except Exception as exc:
            self._log(step="metadata_parse", source=urlparse(url).netloc or url, status="error", started=time.perf_counter(), url=str(response.url), detail=type(exc).__name__)
            return None

    async def _request_text_with_retry(self, url: str, *, params: dict[str, str] | None = None) -> str | None:
        response = await self._request_response_with_retry(url, params=params)
        return None if response is None else response.text

    async def _request_response_with_retry(self, url: str, *, params: dict[str, str] | None = None) -> httpx.Response | None:
        source = urlparse(url).netloc or url
        last_error: Exception | None = None
        parsed = urlparse(url)
        max_attempts = 2
        if parsed.netloc.lower() == "europepmc.org" and parsed.path == "/api/fulltextRepo" and (params or {}).get("type") == "METADATA":
            max_attempts = 3
        for attempt in range(max_attempts):
            started = time.perf_counter()
            try:
                response = await self._with_outer_timeout(5.0, self._metadata_client.get(url, params=params))
                response.raise_for_status()
                detail = f"attempt={attempt + 1}" if attempt else None
                self._log(step="metadata", source=source, status="ok", started=started, url=str(response.url), detail=detail, status_code=response.status_code)
                return response
            except Exception as exc:
                last_error = exc
                detail = type(exc).__name__
                if attempt:
                    detail = f"{detail};attempt={attempt + 1}"
                self._log(step="metadata", source=source, status="error", started=started, url=url, detail=detail)
                if attempt < (max_attempts - 1) and isinstance(exc, httpx.TimeoutException):
                    await asyncio.sleep(0.15 * (attempt + 1))
                    continue
                break
        return None

    async def _pmc_oa_candidates(self, pmc_id: str) -> list[Candidate]:
        xml_text = await self._get_text(PMC_OA_URL, params={"id": pmc_id})
        if xml_text is None:
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        candidates: list[Candidate] = []
        for link in root.findall(".//record/link"):
            href = link.attrib.get("href")
            if not href:
                continue
            if href.startswith("ftp://"):
                href = "https://" + href[len("ftp://") :]
            if href.endswith(".pdf"):
                candidates.append(Candidate("pmc_oa_pdf", href, 0))
            elif href.endswith(".tar.gz"):
                candidates.append(Candidate("pmc_oa_tgz", href, 1))
        return sorted(candidates, key=lambda item: (item.priority, item.url))

    async def _crossref_candidates(self, doi: str) -> list[Candidate]:
        payload = await self._get_json(f"{CROSSREF_URL}/{quote(doi, safe='')}")
        if payload is None:
            return []
        message = payload.get("message", {})
        candidates: list[Candidate] = []
        for item in message.get("link", []):
            url = item.get("URL")
            if not url:
                continue
            content_type = (item.get("content-type") or "").lower()
            host = urlparse(url).netloc.lower()
            if "pdf" in content_type or "pdf" in url.lower():
                candidates.append(Candidate("crossref", url, 10))
            elif host == "api.elsevier.com" and "text/xml" in content_type:
                candidates.append(Candidate("crossref_elsevier_xml", url, 12))
        return candidates

    async def _ncbi_linkout_candidates(self, pmid: str) -> list[Candidate]:
        payload = await self._get_json(
            NCBI_ELINK_URL,
            params={
                "dbfrom": "pubmed",
                "id": pmid,
                "cmd": "prlinks",
                "retmode": "json",
            },
        )
        if payload is None:
            return []
        candidates: list[Candidate] = []
        linksets = payload.get("linksets", [])
        for linkset in linksets:
            for idurllist in linkset.get("idurllist", []):
                for objurl in idurllist.get("objurls", []):
                    url_value = ((objurl.get("url") or {}).get("value") or "").strip()
                    if not url_value:
                        continue
                    categories = [str(item).lower() for item in objurl.get("categories") or []]
                    if "full text sources" not in categories:
                        continue
                    lower = url_value.lower()
                    if ".pdf" in lower or "/pdf" in lower:
                        candidates.append(Candidate("ncbi_linkout", url_value, 13))
                        continue
                    candidates.extend(await self._landing_page_candidates_from_url("ncbi_linkout", url_value, 14))
        return candidates

    async def _openalex_candidates(self, doi: str) -> list[Candidate]:
        payload = await self._get_json(
            OPENALEX_URL,
            params={
                "filter": f"doi:https://doi.org/{doi}",
                "select": "best_oa_location,primary_location",
            },
        )
        if payload is None:
            return []
        results = payload.get("results", [])
        if not results:
            return []
        first = results[0]
        candidates: list[Candidate] = []
        for field in ("best_oa_location", "primary_location"):
            location = first.get(field) or {}
            pdf_url = location.get("pdf_url")
            if pdf_url:
                candidates.append(Candidate("openalex", pdf_url, 20))
        return candidates

    async def _europe_pmc_candidates(self, article: ArticleRef) -> list[Candidate]:
        query_parts: list[str] = []
        if article.pmc_id:
            query_parts.append(f"PMCID:{article.pmc_id}")
        if article.doi:
            query_parts.append(f'DOI:"{article.doi}"')
        if not query_parts:
            return []
        payload = await self._get_json(
            EUROPE_PMC_URL,
            params={
                "query": " OR ".join(query_parts),
                "format": "json",
                "pageSize": "1",
                "resultType": "core",
            },
        )
        if payload is None:
            return []
        result_list = payload.get("resultList", {})
        results = result_list.get("result", [])
        if not results:
            return []
        record = results[0]
        candidates: list[Candidate] = []
        if article.pmc_id:
            metadata = await self._get_json(
                EUROPE_PMC_REPO_URL,
                params={"pmcId": article.pmc_id, "type": "METADATA"},
            )
            if metadata:
                version = int(float(metadata.get("version") or 1))
                for file_item in metadata.get("files") or []:
                    filename = str(file_item.get("filename") or "")
                    mime_type = str(file_item.get("mimeType") or "")
                    file_type = str(file_item.get("type") or "").lower()
                    if not filename or not mime_type:
                        continue
                    if file_type == "pdf" or "pdf" in mime_type.lower():
                        url = (
                            f"{EUROPE_PMC_REPO_URL}?pmcId={article.pmc_id}&type=FILE"
                            f"&fileName={quote(filename, safe='')}"
                            f"&mimeType={quote(mime_type, safe='')}"
                            f"&version={version}&pmc_pageType=pdf&pmc_domain=null"
                        )
                        candidates.append(Candidate("europe_pmc_repo_pdf", url, 2))
        block = record.get("fullTextUrlList", {})
        fulltext_urls = block.get("fullTextUrl", [])
        for item in fulltext_urls:
            url = item.get("url")
            if not url:
                continue
            style = str(item.get("documentStyle", "")).lower()
            if "pdf" in style or "pdf" in url.lower():
                candidates.append(Candidate("europe_pmc", url, 30))
        if article.pmc_id:
            candidates.append(Candidate("europe_pmc_render", f"https://europepmc.org/articles/{article.pmc_id}?pdf=render", 31))
        return candidates

    async def _landing_page_candidates_from_url(self, source: str, landing_url: str, priority_base: int) -> list[Candidate]:
        started = time.perf_counter()
        try:
            response = await self._with_outer_timeout(
                4.0,
                self._metadata_client.get(
                    landing_url,
                    headers={"Accept": "text/html,*/*"},
                ),
            )
            response.raise_for_status()
            base_url = str(response.url)
            html = response.text
            self._log(step="landing", source=source, status="ok", started=started, url=base_url, status_code=response.status_code)
        except Exception as exc:
            self._log(step="landing", source=source, status="error", started=started, url=landing_url, detail=type(exc).__name__)
            return []

        candidates: list[Candidate] = []
        seen: set[str] = set()
        for match in re.finditer(r'citation_pdf_url[^>]+content=["\']([^"\']+)', html, flags=re.I):
            url = urljoin(base_url, match.group(1))
            if url not in seen:
                seen.add(url)
                candidates.append(Candidate(f"{source}_citation_pdf_url", url, priority_base))
        for match in re.finditer(r'href=["\']([^"\']+)', html, flags=re.I):
            href = match.group(1)
            lower = href.lower()
            if ".pdf" not in lower and "/pdf" not in lower and "downloadpdf" not in lower and "article-pdf" not in lower:
                continue
            url = urljoin(base_url, href)
            if url not in seen:
                seen.add(url)
                candidates.append(Candidate(f"{source}_page_pdf", url, priority_base + 1))
        if self._looks_like_fulltext_html(base_url, html):
            candidates.append(Candidate(f"{source}_html_fulltext", base_url, priority_base + 2))
        return candidates

    async def _doi_landing_candidates(self, doi: str) -> list[Candidate]:
        return await self._landing_page_candidates_from_url(
            "doi_landing",
            f"{DOI_BASE_URL}/{quote(doi, safe='')}",
            11,
        )

    async def _doaj_candidates(self, doi: str) -> list[Candidate]:
        payload = await self._get_json(f"{DOAJ_SEARCH_URL}/{quote(f'doi:{doi}', safe='')}")
        if payload is None:
            return []
        results = payload.get("results", [])
        if not results:
            return []
        candidates: list[Candidate] = []
        for result in results:
            bibjson = result.get("bibjson", {})
            for item in bibjson.get("link", []):
                url = item.get("url")
                if not url:
                    continue
                lower = url.lower()
                link_type = str(item.get("type") or "").lower()
                if ".pdf" in lower or "/pdf" in lower:
                    candidates.append(Candidate("doaj_pdf", url, 16))
                    continue
                if "fulltext" in link_type or "html" in link_type or "/doi/" in lower:
                    candidates.extend(await self._landing_page_candidates_from_url("doaj", url, 17))
        return candidates

    def _nature_direct_candidates(self, doi: str) -> list[Candidate]:
        lower_doi = (doi or "").lower()
        if not lower_doi.startswith("10.1038/"):
            return []
        _, _, suffix = doi.partition("/")
        suffix = suffix.strip()
        if not suffix:
            return []
        article_url = f"https://www.nature.com/articles/{quote(suffix, safe='-._~')}"
        return [
            Candidate("nature_direct_pdf", f"{article_url}.pdf", 8),
            Candidate("nature_html_fulltext", article_url, 9),
        ]

    def _article_metadata_candidates(self, article: ArticleRef) -> list[Candidate]:
        url = (article.oa_pdf_url or "").strip()
        if not url:
            return []
        normalized = self._normalize_candidate_url(url)
        if "doi.org/" in normalized.lower():
            return []
        return [Candidate("article_oa_pdf", normalized, 9)]

    def _dedupe_candidates(self, candidates: list[Candidate]) -> list[Candidate]:
        best: dict[str, Candidate] = {}
        for candidate in candidates:
            normalized_url = self._normalize_candidate_url(candidate.url)
            normalized = Candidate(candidate.source, normalized_url, candidate.priority)
            existing = best.get(normalized.url)
            if existing is None or candidate.priority < existing.priority:
                best[normalized.url] = normalized
        return sorted(best.values(), key=lambda item: (item.priority, item.url))

    def _normalize_candidate_url(self, url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme
        hostname = (parsed.hostname or "").lower()
        is_ip_host = False
        if hostname:
            try:
                ipaddress.ip_address(hostname)
                is_ip_host = True
            except ValueError:
                is_ip_host = False
        if parsed.scheme in {"http", "https"} and not is_ip_host:
            scheme = "https"
        netloc = parsed.netloc.lower()
        return urlunparse((scheme, netloc, parsed.path, "", parsed.query, ""))

    def _classify_non_pdf_response(self, body: bytes, content_type: str, status_code: int | None) -> str:
        detail = content_type or "non_pdf_response"
        if "html" not in content_type:
            return detail
        text = body[:12000].decode("utf-8", errors="ignore").lower()
        if "just a moment" in text or "security verification" in text or "verify you are not a bot" in text or "cloudflare" in text:
            return "cloudflare_challenge"
        if status_code == 403:
            return "html_access_block"
        return detail

    def _looks_like_fulltext_html(self, url: str, html: str) -> bool:
        lower_html = html.lower()
        lower_url = url.lower()
        if "cloudflare" in lower_html or "security verification" in lower_html or "just a moment" in lower_html:
            return False
        if "unauthorizeddownload" in lower_url:
            return False
        if "citation_title" not in lower_html:
            return False
        if "/html" not in lower_url and "citation_xml_url" not in lower_html and "citation_pdf_url" not in lower_html:
            return False
        text = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\\s+", " ", text).strip()
        return len(text) >= 12000

    async def _download_html_fulltext(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        try:
            response = await self._with_outer_timeout(
                20.0 if self.mode == "fast" else 30.0,
                self._download_client.get(candidate.url, headers={"Accept": "text/html,*/*"}),
            )
            body = response.content
            content_type = (response.headers.get("content-type") or "").lower()
            html = body.decode("utf-8", errors="ignore")
            if response.status_code == 200 and "html" in content_type and self._looks_like_fulltext_html(str(response.url), html):
                path = self._write_file(article, candidate.source, body, ".html")
                self._log(
                    step="download",
                    source=candidate.source,
                    status="ok",
                    started=started,
                    url=str(response.url),
                    status_code=response.status_code,
                    detail="html_fulltext",
                )
                return True, str(path), str(response.url)
            detail = self._classify_non_pdf_response(body, content_type, response.status_code)
            self._log(step="download", source=candidate.source, status="reject", started=started, url=str(response.url), detail=detail, status_code=response.status_code)
            return False, None, None
        except Exception as exc:
            self._log(step="download", source=candidate.source, status="error", started=started, url=candidate.url, detail=type(exc).__name__)
            return False, None, None

    async def _probe_direct_pdf(self, candidate: Candidate) -> tuple[bool, bytes | None, str | None, int | None]:
        started = time.perf_counter()
        try:
            async def _fetch_probe() -> tuple[int, bytes, str, int | None, str]:
                async with self._download_client.stream(
                    "GET",
                    candidate.url,
                    headers={"Accept": "application/pdf,*/*", "Range": "bytes=0-16383"},
                ) as response:
                    content_type = (response.headers.get("content-type") or "").lower()
                    total_size: int | None = None
                    content_range = response.headers.get("content-range") or ""
                    match = re.search(r"/(\d+)$", content_range)
                    if match:
                        total_size = int(match.group(1))
                    buffer = bytearray()
                    read_limit = 16384
                    if "html" in content_type:
                        read_limit = 8192
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) >= read_limit:
                            break
                    return response.status_code, bytes(buffer), content_type, total_size, str(response.url)

            status_code, body, content_type, total_size, final_url = await self._with_outer_timeout(3.0, _fetch_probe())
            if status_code in {200, 206} and ("pdf" in content_type or body.startswith(b"%PDF")):
                self._log(step="probe", source=candidate.source, status="ok", started=started, url=final_url, status_code=status_code)
                return True, body, content_type, total_size
            detail = self._classify_non_pdf_response(body, content_type, status_code)
            self._log(step="probe", source=candidate.source, status="reject", started=started, url=final_url, detail=detail, status_code=status_code)
            return False, None, content_type, total_size
        except Exception as exc:
            self._log(step="probe", source=candidate.source, status="error", started=started, url=candidate.url, detail=type(exc).__name__)
            return False, None, None, None

    async def _download_segmented_pdf(
        self,
        candidate: Candidate,
        article: ArticleRef,
        *,
        first_chunk: bytes,
        total_size: int,
    ) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        host = urlparse(candidate.url).netloc.lower()
        if total_size > 20_000_000:
            segments = 6
            range_timeout = 45.0 if self.mode == "fast" else 50.0
        elif total_size > 6_000_000:
            segments = 4
            range_timeout = 25.0 if self.mode == "fast" else 30.0
        else:
            segments = 3
            range_timeout = 20.0 if self.mode == "fast" else 25.0
        chunk_size = math.ceil(total_size / segments)

        async def _fetch_range(range_start: int, range_end: int) -> tuple[int, bytes]:
            response = await self._with_outer_timeout(
                range_timeout,
                self._download_client.get(
                    candidate.url,
                    headers={
                        "Accept": "application/pdf,*/*",
                        "Range": f"bytes={range_start}-{range_end}",
                    },
                ),
            )
            body = response.content
            if response.status_code not in {200, 206} or not body:
                raise ValueError(f"range_status={response.status_code}")
            return range_start, body

        chunks: list[tuple[int, bytes]] = [(0, first_chunk)]
        jobs = []
        for index in range(1, segments):
            range_start = index * chunk_size
            range_end = min(total_size - 1, ((index + 1) * chunk_size) - 1)
            jobs.append(_fetch_range(range_start, range_end))

        try:
            results = await asyncio.gather(*jobs)
        except Exception as exc:
            self._log(step="download", source=candidate.source, status="error", started=started, url=candidate.url, detail=f"segmented:{type(exc).__name__}")
            return False, None, None

        chunks.extend(results)
        chunks.sort(key=lambda item: item[0])
        body = b"".join(chunk for _, chunk in chunks)
        if not body.startswith(b"%PDF"):
            self._log(step="download", source=candidate.source, status="reject", started=started, url=candidate.url, detail="segmented_not_pdf")
            return False, None, None

        path = self._write_file(article, candidate.source, body, ".pdf")
        self._log(
            step="download",
            source=candidate.source,
            status="ok",
            started=started,
            url=candidate.url,
            detail=f"segmented:{segments};host={host}",
            status_code=206,
        )
        return True, str(path), candidate.url

    async def _download_direct_pdf(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        host = urlparse(candidate.url).netloc.lower()
        range_optimized = host in RANGE_OPTIMIZED_HOSTS
        can_skip_probe = (
            not range_optimized
            and
            host in TRUSTED_DIRECT_HOSTS
            and candidate.source in {
                "crossref",
                "openalex",
                "citation_pdf_url",
                "pmc_oa_pdf",
                "europe_pmc",
                "europe_pmc_render",
                "europe_pmc_repo_pdf",
            }
        )
        probe_body: bytes | None = None
        total_size: int | None = None
        if not can_skip_probe:
            probe_ok, probe_body, _, total_size = await self._probe_direct_pdf(candidate)
            if not probe_ok:
                return False, None, None
            if range_optimized and probe_body and total_size and total_size > len(probe_body):
                return await self._download_segmented_pdf(candidate, article, first_chunk=probe_body, total_size=total_size)
        try:
            download_timeout = 20.0 if self.mode == "fast" else 35.0
            if self.mode == "fast" and host in TRUSTED_DIRECT_HOSTS:
                download_timeout = 30.0
            if candidate.source == "europe_pmc_repo_pdf":
                download_timeout = 45.0 if self.mode == "fast" else 50.0
            response = await self._with_outer_timeout(
                download_timeout,
                self._download_client.get(candidate.url, headers={"Accept": "application/pdf,*/*"}),
            )
            body = response.content
            content_type = (response.headers.get("content-type") or "").lower()
            if response.status_code == 200 and ("pdf" in content_type or body.startswith(b"%PDF")):
                path = self._write_file(article, candidate.source, body, ".pdf")
                self._log(
                    step="download",
                    source=candidate.source,
                    status="ok",
                    started=started,
                    url=candidate.url,
                    status_code=response.status_code,
                    detail="probe_skipped" if can_skip_probe else None,
                )
                return True, str(path), candidate.url
            detail = self._classify_non_pdf_response(body, content_type, response.status_code)
            self._log(step="download", source=candidate.source, status="reject", started=started, url=candidate.url, detail=detail, status_code=response.status_code)
            return False, None, None
        except Exception as exc:
            self._log(step="download", source=candidate.source, status="error", started=started, url=candidate.url, detail=type(exc).__name__)
            return False, None, None

    async def _download_tgz_pdf(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        try:
            response = await self._with_outer_timeout(
                10.0 if self.mode == "fast" else 18.0,
                self._download_client.get(candidate.url, headers={"Accept": "application/gzip,application/x-gzip,*/*"}),
            )
            body = response.content
            response.raise_for_status()
        except Exception as exc:
            self._log(step="download", source=candidate.source, status="error", started=started, url=candidate.url, detail=type(exc).__name__)
            return False, None, None
        try:
            archive = tarfile.open(fileobj=io.BytesIO(body), mode="r:gz")
        except tarfile.TarError:
            self._log(step="download", source=candidate.source, status="reject", started=started, url=candidate.url, detail="invalid_tgz")
            return False, None, None
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".pdf"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            pdf_bytes = extracted.read()
            if pdf_bytes.startswith(b"%PDF"):
                path = self._write_file(article, candidate.source, pdf_bytes, ".pdf")
                self._log(step="download", source=candidate.source, status="ok", started=started, url=candidate.url, status_code=response.status_code)
                return True, str(path), candidate.url
        self._log(step="download", source=candidate.source, status="reject", started=started, url=candidate.url, detail="no_pdf_in_archive", status_code=response.status_code)
        return False, None, None

    async def _download_elsevier_xml(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        try:
            response = await self._with_outer_timeout(
                10.0 if self.mode == "fast" else 15.0,
                self._download_client.get(candidate.url, headers={"Accept": "application/xml,text/xml,*/*"}),
            )
            body = response.content
            content_type = (response.headers.get("content-type") or "").lower()
            if response.status_code == 200 and "xml" in content_type and b"full-text-retrieval-response" in body and len(body) > 500:
                path = self._write_file(article, candidate.source, body, ".xml")
                self._log(
                    step="download",
                    source=candidate.source,
                    status="ok",
                    started=started,
                    url=candidate.url,
                    status_code=response.status_code,
                    detail="content_first",
                )
                return True, str(path), candidate.url
            self._log(
                step="download",
                source=candidate.source,
                status="reject",
                started=started,
                url=candidate.url,
                status_code=response.status_code,
                detail=content_type or "non_xml_response",
            )
            return False, None, None
        except Exception as exc:
            self._log(step="download", source=candidate.source, status="error", started=started, url=candidate.url, detail=type(exc).__name__)
            return False, None, None

    async def _download_tgz_xml(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        try:
            response = await self._with_outer_timeout(15.0, self._download_client.get(candidate.url))
            if response.status_code != 200:
                return False, None, None
            archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz")
        except Exception:
            return False, None, None
        for member in archive.getmembers():
            if member.isfile() and member.name.lower().endswith(".nxml"):
                extracted = archive.extractfile(member)
                if extracted:
                    xml_bytes = extracted.read()
                    path = self._write_file(article, candidate.source, xml_bytes, ".xml")
                    self._log(step="download", source=candidate.source, status="ok", started=started, url=candidate.url)
                    return True, str(path), candidate.url
        return False, None, None

    async def _download_direct_xml(self, candidate: Candidate, article: ArticleRef) -> tuple[bool, str | None, str | None]:
        started = time.perf_counter()
        try:
            r = await self._download_client.get(candidate.url, timeout=10.0)
            if r.status_code == 200 and (b"<?xml" in r.content or b"<article" in r.content):
                path = self._write_file(article, candidate.source, r.content, ".xml")
                self._log(step="download", source=candidate.source, status="ok", started=started, url=candidate.url)
                return True, str(path), candidate.url
        except Exception:
            pass
        return False, None, None

    async def _download_candidate(self, candidate: Candidate, article: ArticleRef) -> tuple[Candidate, bool, str | None, str | None]:
        is_xml_source = "_xml" in candidate.source or "xml" in candidate.url.lower() or "efetch" in candidate.url.lower()
        
        if self.mode == "xml" and not is_xml_source and candidate.source != "pmc_oa_tgz":
            return candidate, False, None, None

        if candidate.source == "pmc_oa_tgz":
            # If XML mode, extract .nxml, otherwise extract .pdf
            if self.mode == "xml":
                success, file_path, final_url = await self._download_tgz_xml(candidate, article)
            else:
                success, file_path, final_url = await self._download_tgz_pdf(candidate, article)
        elif candidate.source == "crossref_elsevier_xml":
            success, file_path, final_url = await self._download_elsevier_xml(candidate, article)
        elif candidate.source.endswith("_html_fulltext"):
            if self.mode == "xml": return candidate, False, None, None
            success, file_path, final_url = await self._download_html_fulltext(candidate, article)
        elif "efetch" in candidate.url:
            success, file_path, final_url = await self._download_direct_xml(candidate, article)
        else:
            if self.mode == "xml": return candidate, False, None, None
            success, file_path, final_url = await self._download_direct_pdf(candidate, article)
            
        return candidate, success, file_path, final_url

    def _write_file(self, article: ArticleRef, source: str, body: bytes, suffix: str) -> Path:
        stem = article.pmid or article.doi or article.pmc_id or "article"
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80]
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{stem}_{source}{suffix}"
        path.write_bytes(body)
        return path

    def _failure_note(self) -> str:
        for attempt in self.attempts:
            if attempt.detail == "cloudflare_challenge":
                return "upstream_waf_blocked"
        for attempt in self.attempts:
            if attempt.status_code == 403:
                return "blocked_403"
        return "budget_exhausted" if self._remaining_budget() <= 0 else "no_successful_candidate"

    def _success_result(
        self,
        *,
        article: ArticleRef,
        started: float,
        candidate: Candidate,
        file_path: str | None,
        final_url: str | None,
        candidate_count: int,
    ) -> Result:
        host = urlparse(candidate.url).netloc.lower()
        return Result(
            article=asdict(article),
            mode=self.mode,
            success=True,
            source=candidate.source,
            url=final_url,
            file_path=file_path,
            total_ms=int((time.perf_counter() - started) * 1000),
            attempts=[asdict(item) for item in self.attempts],
            candidate_count=candidate_count,
            note="trusted_direct_host" if host in TRUSTED_DIRECT_HOSTS else None,
        )

    async def _resolve_missing_ids(self, article: ArticleRef) -> None:
        """DOI/PMID varsa ve PMCID eksikse NCBI API kullanarak tamamlar."""
        if article.pmc_id:
            return
        ids = []
        if article.doi: ids.append(article.doi)
        if article.pmid: ids.append(article.pmid)
        if not ids:
            return
            
        try:
            url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/?ids={','.join(ids)}&format=json&tool=NativeResearcher&email=bot@example.com"
            r = await self._metadata_client.get(url, timeout=5.0)
            if r.status_code == 200:
                for rec in r.json().get("records", []):
                    if rec.get("pmcid"):
                        article.pmc_id = rec["pmcid"]
                        break
        except Exception:
            pass

    async def run(self, article: ArticleRef) -> Result:
        started = time.perf_counter()
        await self._resolve_missing_ids(article)

        all_candidates: list[Candidate] = []
        checked_urls: set[str] = set()
        precomputed_europe_candidates: list[Candidate] = []
        fast_direct_candidates: list[Candidate] = []
        if article.pmc_id:
            pmc_candidates = await self._pmc_oa_candidates(article.pmc_id)
            all_candidates.extend(pmc_candidates)
            if self.mode == "fast" and pmc_candidates:
                pmc_fast_candidates = self._dedupe_candidates(pmc_candidates)
                for candidate in pmc_fast_candidates:
                    checked_urls.add(candidate.url)
                    candidate_ref, success, file_path, final_url = await self._download_candidate(candidate, article)
                    if success:
                        return self._success_result(
                            article=article,
                            started=started,
                            candidate=candidate_ref,
                            file_path=file_path,
                            final_url=final_url,
                            candidate_count=len(pmc_fast_candidates),
                        )
                    if self._remaining_budget() <= 0:
                        return Result(
                            article=asdict(article),
                            mode=self.mode,
                            success=False,
                            source=None,
                            url=None,
                            file_path=None,
                            total_ms=int((time.perf_counter() - started) * 1000),
                            attempts=[asdict(item) for item in self.attempts],
                            candidate_count=len(pmc_fast_candidates),
                            note=self._failure_note(),
                        )
            if self.mode == "fast":
                precomputed_europe_candidates = await self._europe_pmc_candidates(article)
                europe_repo_fast_candidates = self._dedupe_candidates(
                    [candidate for candidate in precomputed_europe_candidates if candidate.source == "europe_pmc_repo_pdf"]
                )
                for candidate in europe_repo_fast_candidates:
                    checked_urls.add(candidate.url)
                    candidate_ref, success, file_path, final_url = await self._download_candidate(candidate, article)
                    if success:
                        return self._success_result(
                            article=article,
                            started=started,
                            candidate=candidate_ref,
                            file_path=file_path,
                            final_url=final_url,
                            candidate_count=len(europe_repo_fast_candidates),
                        )
                    if self._remaining_budget() <= 0:
                        return Result(
                            article=asdict(article),
                            mode=self.mode,
                            success=False,
                            source=None,
                            url=None,
                            file_path=None,
                            total_ms=int((time.perf_counter() - started) * 1000),
                            attempts=[asdict(item) for item in self.attempts],
                            candidate_count=len(europe_repo_fast_candidates),
                            note=self._failure_note(),
                        )
                all_candidates.extend(precomputed_europe_candidates)

        if article.doi and self.mode == "fast":
            fast_direct_candidates = self._dedupe_candidates(self._nature_direct_candidates(article.doi))
            for candidate in fast_direct_candidates:
                checked_urls.add(candidate.url)
                candidate_ref, success, file_path, final_url = await self._download_candidate(candidate, article)
                if success:
                    return self._success_result(
                        article=article,
                        started=started,
                        candidate=candidate_ref,
                        file_path=file_path,
                        final_url=final_url,
                        candidate_count=len(fast_direct_candidates),
                    )
                if self._remaining_budget() <= 0:
                    return Result(
                        article=asdict(article),
                        mode=self.mode,
                        success=False,
                        source=None,
                        url=None,
                        file_path=None,
                        total_ms=int((time.perf_counter() - started) * 1000),
                        attempts=[asdict(item) for item in self.attempts],
                        candidate_count=len(fast_direct_candidates),
                        note=self._failure_note(),
                        )
            all_candidates.extend(fast_direct_candidates)

        article_metadata_candidates = self._article_metadata_candidates(article)
        all_candidates.extend(article_metadata_candidates)

        if article.doi:
            if self.mode == "fast":
                crossref_candidates, openalex_candidates, doaj_candidates, ncbi_linkout_candidates, europe_candidates = await asyncio.gather(
                    self._crossref_candidates(article.doi),
                    self._openalex_candidates(article.doi),
                    self._doaj_candidates(article.doi),
                    asyncio.sleep(0, result=[]) if fast_direct_candidates else (
                        self._ncbi_linkout_candidates(article.pmid) if article.pmid and not article.pmc_id else asyncio.sleep(0, result=[])
                    ),
                    asyncio.sleep(0, result=precomputed_europe_candidates) if article.pmc_id else asyncio.sleep(0, result=[]),
                )
                all_candidates.extend(crossref_candidates)
                all_candidates.extend(openalex_candidates)
                all_candidates.extend(doaj_candidates)
                all_candidates.extend(ncbi_linkout_candidates)
                all_candidates.extend(europe_candidates)
            else:
                crossref_candidates, openalex_candidates, doaj_candidates, ncbi_linkout_candidates, europe_candidates, landing_candidates = await asyncio.gather(
                    self._crossref_candidates(article.doi),
                    self._openalex_candidates(article.doi),
                    self._doaj_candidates(article.doi),
                    self._ncbi_linkout_candidates(article.pmid) if article.pmid else asyncio.sleep(0, result=[]),
                    self._europe_pmc_candidates(article),
                    self._doi_landing_candidates(article.doi),
                )
                all_candidates.extend(crossref_candidates)
                all_candidates.extend(openalex_candidates)
                all_candidates.extend(doaj_candidates)
                all_candidates.extend(ncbi_linkout_candidates)
                all_candidates.extend(europe_candidates)
                all_candidates.extend(landing_candidates)
        elif self.mode == "balanced" and article.pmc_id:
            all_candidates.extend(await self._europe_pmc_candidates(article))

        candidates = self._dedupe_candidates(all_candidates)

        if self.mode == "fast":
            europe_repo_candidates = [candidate for candidate in candidates if candidate.source == "europe_pmc_repo_pdf"]
            for candidate in europe_repo_candidates:
                checked_urls.add(candidate.url)
                candidate_ref, success, file_path, final_url = await self._download_candidate(candidate, article)
                if success:
                    return self._success_result(
                        article=article,
                        started=started,
                        candidate=candidate_ref,
                        file_path=file_path,
                        final_url=final_url,
                        candidate_count=len(candidates),
                    )
                if self._remaining_budget() <= 0:
                    return Result(
                        article=asdict(article),
                        mode=self.mode,
                        success=False,
                        source=None,
                        url=None,
                        file_path=None,
                        total_ms=int((time.perf_counter() - started) * 1000),
                        attempts=[asdict(item) for item in self.attempts],
                        candidate_count=len(candidates),
                        note=self._failure_note(),
                    )

        # Optimization choices:
        # 1. Prefer PMC OA package/pdf first, never try pmc_direct.
        # 2. Treat trusted direct PDF hosts as direct download candidates.
        # 3. Keep DOI landing parsing only in balanced mode.
        parallel_candidates = candidates[:2] if self.mode == "fast" else []
        if len(parallel_candidates) > 1:
            tasks = [asyncio.create_task(self._download_candidate(candidate, article)) for candidate in parallel_candidates]
            try:
                for finished in asyncio.as_completed(tasks):
                    candidate, success, file_path, final_url = await finished
                    checked_urls.add(candidate.url)
                    if success:
                        for task in tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        return self._success_result(
                            article=article,
                            started=started,
                            candidate=candidate,
                            file_path=file_path,
                            final_url=final_url,
                            candidate_count=len(candidates),
                        )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        for candidate in candidates:
            if candidate.url in checked_urls:
                continue
            candidate_ref, success, file_path, final_url = await self._download_candidate(candidate, article)
            if success:
                return self._success_result(
                    article=article,
                    started=started,
                    candidate=candidate_ref,
                    file_path=file_path,
                    final_url=final_url,
                    candidate_count=len(candidates),
                )
            if self._remaining_budget() <= 0:
                break

        return Result(
            article=asdict(article),
            mode=self.mode,
            success=False,
            source=None,
            url=None,
            file_path=None,
            total_ms=int((time.perf_counter() - started) * 1000),
            attempts=[asdict(item) for item in self.attempts],
            candidate_count=len(candidates),
            note=self._failure_note(),
        )


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--article-json", required=True)
    parser.add_argument("--mode", choices=["fast", "balanced"], default="fast")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--budget-seconds", type=float, default=60.0)
    args = parser.parse_args()

    article_payload = json.loads(Path(args.article_json).read_text(encoding="utf-8"))
    article = ArticleRef(
        pmid=article_payload.get("pmid"),
        doi=article_payload.get("doi"),
        pmc_id=article_payload.get("pmc_id"),
        title=article_payload.get("title"),
        year=article_payload.get("year"),
    )
    output_dir = Path(args.output_dir).resolve()
    result_json = Path(args.result_json).resolve()
    result_json.parent.mkdir(parents=True, exist_ok=True)

    downloader = SingleArticleDownloader(mode=args.mode, output_dir=output_dir, budget_seconds=args.budget_seconds)
    try:
        result = await downloader.run(article)
    finally:
        await downloader.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **asdict(result),
    }
    result_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "mode": result.mode,
        "success": result.success,
        "source": result.source,
        "total_ms": result.total_ms,
        "file_path": result.file_path,
        "candidate_count": result.candidate_count,
        "note": result.note,
    }, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(_main())
