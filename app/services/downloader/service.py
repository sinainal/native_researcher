"""Unified XML/PDF downloader service."""

from __future__ import annotations

import asyncio
import io
import re
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

from app.core.config import Settings
from app.schemas.article import ArticleReference
from app.schemas.pdf import (
    PDFAvailabilityItem,
    PDFAvailabilityResponse,
    PDFCandidate,
    PDFDownloadRequest,
    PDFDownloadResponse,
    PDFDownloadResult,
    PDFResolveResponse,
    PDFTestAttempt,
    PDFTestResult,
)
from app.services.app_event_log_service import AppEventLogService
from app.services.downloader.logging import DownloadLogger
from app.services.downloader.models import DownloadCandidate
from app.utils.cache import TTLCache
from app.utils.files import ensure_unique_path, sanitize_filename

EUROPE_PMC_REPO_URL = "https://europepmc.org/api/fulltextRepo"


class _BasePipeline:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings) -> None:
        self.http_client = http_client
        self.settings = settings

    async def resolve_candidates(self, article: ArticleReference, *, mode: str) -> list[DownloadCandidate]:
        raise NotImplementedError

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str,
        budget_seconds: float,
        save_file: bool = True,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        logger = DownloadLogger()
        candidates = await self.resolve_candidates(article, mode=mode)
        if not candidates:
            return self._failure_payload(
                article,
                started=started,
                logger=logger,
                candidate_count=0,
                note="no_candidates",
            )

        deadline = time.perf_counter() + max(5.0, budget_seconds)
        for candidate in candidates:
            if time.perf_counter() >= deadline:
                return self._failure_payload(
                    article,
                    started=started,
                    logger=logger,
                    candidate_count=len(candidates),
                    note="budget_exhausted",
                )
            payload = await self._try_candidate(
                article,
                candidate,
                output_dir=output_dir,
                logger=logger,
                save_file=save_file,
            )
            if payload is not None:
                payload["total_ms"] = int((time.perf_counter() - started) * 1000)
                payload["candidate_count"] = len(candidates)
                payload["attempts"] = logger.export()
                return payload
        return self._failure_payload(
            article,
            started=started,
            logger=logger,
            candidate_count=len(candidates),
            note=self._reason_from_attempts(logger.export()),
        )

    async def _try_candidate(
        self,
        article: ArticleReference,
        candidate: DownloadCandidate,
        *,
        output_dir: Path,
        logger: DownloadLogger,
        save_file: bool,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        headers = self._candidate_headers(candidate)
        try:
            response = await self.http_client.get(
                candidate.url,
                headers=headers,
                follow_redirects=True,
                timeout=self._candidate_timeout(candidate),
            )
        except Exception as exc:
            logger.record(
                step="download",
                source=candidate.source,
                url=candidate.url,
                status="error",
                started=started,
                detail=f"{type(exc).__name__}: {exc}",
            )
            return None

        content_type = (response.headers.get("content-type") or "").lower()
        if response.status_code in {401, 403, 429}:
            logger.record(
                step="download",
                source=candidate.source,
                url=str(response.url),
                status="reject",
                started=started,
                detail=f"http_{response.status_code}",
                status_code=response.status_code,
                content_type=content_type,
            )
            return None
        if response.status_code != 200:
            logger.record(
                step="download",
                source=candidate.source,
                url=str(response.url),
                status="reject",
                started=started,
                detail=f"http_{response.status_code}",
                status_code=response.status_code,
                content_type=content_type,
            )
            return None

        normalized = await self._normalize_payload(candidate, response)
        if normalized is None:
            logger.record(
                step="download",
                source=candidate.source,
                url=str(response.url),
                status="reject",
                started=started,
                detail="invalid_payload",
                status_code=response.status_code,
                content_type=content_type,
            )
            return None
        payload_bytes, content_kind, extension = normalized
        file_path = None
        if save_file:
            file_path = self._build_file_path(article, candidate.source, output_dir, extension)
            file_path.write_bytes(payload_bytes)
        logger.record(
            step="download",
            source=candidate.source,
            url=str(response.url),
            status="ok",
            started=started,
            status_code=response.status_code,
            content_type=content_type,
        )
        return {
            "article": article.model_dump(),
            "mode": "fast",
            "success": True,
            "source": candidate.source,
            "url": str(response.url),
            "file_path": str(file_path) if file_path is not None else None,
            "content_kind": content_kind,
            "content_type": "application/xml" if content_kind == "xml_fulltext" else "application/pdf",
            "note": None,
        }

    async def _normalize_payload(
        self,
        candidate: DownloadCandidate,
        response: httpx.Response,
    ) -> tuple[bytes, str, str] | None:
        content = response.content
        content_type = (response.headers.get("content-type") or "").lower()
        if candidate.file_type == "xml":
            if self._is_fulltext_xml(content_type, content):
                return content, "xml_fulltext", ".xml"
            return None
        if candidate.file_type == "tgzpdf":
            pdf_bytes = self._extract_pdf_from_tgz(content)
            if pdf_bytes is not None:
                return pdf_bytes, "pdf", ".pdf"
            return None
        if self._is_pdf_payload(content_type, content):
            return content, "pdf", ".pdf"
        return None

    def _candidate_headers(self, candidate: DownloadCandidate) -> dict[str, str]:
        if candidate.file_type == "xml":
            accept = "application/xml,text/xml,*/*"
        else:
            accept = "application/pdf,*/*"
        return {"User-Agent": self.settings.request_user_agent, "Accept": accept}

    @staticmethod
    def _candidate_timeout(candidate: DownloadCandidate) -> float:
        if candidate.file_type == "tgzpdf":
            return 25.0
        if candidate.file_type == "xml":
            return 20.0
        return 20.0

    def _failure_payload(
        self,
        article: ArticleReference,
        *,
        started: float,
        logger: DownloadLogger,
        candidate_count: int,
        note: str,
    ) -> dict[str, Any]:
        return {
            "article": article.model_dump(),
            "mode": "fast",
            "success": False,
            "source": None,
            "url": None,
            "file_path": None,
            "total_ms": int((time.perf_counter() - started) * 1000),
            "candidate_count": candidate_count,
            "attempts": logger.export(),
            "note": note,
        }

    @staticmethod
    def _reason_from_attempts(attempts: list[dict[str, Any]]) -> str:
        status_codes = [item.get("status_code") for item in attempts if item.get("status_code") is not None]
        if any(code == 403 for code in status_codes):
            return "blocked_403"
        if any(code == 429 for code in status_codes):
            return "rate_limited_429"
        if attempts:
            return "no_successful_candidate"
        return "no_candidates"

    async def _resolve_pmc_id(self, article: ArticleReference) -> str | None:
        if article.pmc_id:
            return article.pmc_id if article.pmc_id.startswith("PMC") else f"PMC{article.pmc_id}"
        if article.doi:
            pmcid = await self._pmcid_from_doi(article.doi)
            if pmcid:
                return pmcid
        if article.pmid:
            pmcid = await self._pmcid_from_pmid(article.pmid)
            if pmcid:
                return pmcid
        return await self._pmcid_from_europe_pmc(article)

    async def _pmcid_from_doi(self, doi: str) -> str | None:
        try:
            response = await self.http_client.get(
                "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
                params={"ids": doi, "format": "json", "tool": "native_researcher", "email": self.settings.unpaywall_email or "anon@example.com"},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            for record in response.json().get("records", []):
                pmcid = str(record.get("pmcid") or "").strip()
                if pmcid:
                    return pmcid if pmcid.startswith("PMC") else f"PMC{pmcid}"
        except Exception:
            return None
        return None

    async def _pmcid_from_pmid(self, pmid: str) -> str | None:
        try:
            response = await self.http_client.get(
                f"{self.settings.ncbi_base_url}/elink.fcgi",
                params={"dbfrom": "pubmed", "db": "pmc", "id": pmid, "retmode": "xml", "linkname": "pubmed_pmc"},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            match = re.search(r"<Id>(\d+)</Id>", response.text)
            if match:
                return f"PMC{match.group(1)}"
        except Exception:
            return None
        return None

    async def _pmcid_from_europe_pmc(self, article: ArticleReference) -> str | None:
        query_parts = []
        if article.doi:
            query_parts.append(f'DOI:"{article.doi}"')
        if article.pmid:
            query_parts.append(f"EXT_ID:{article.pmid}")
        if not query_parts:
            return None
        try:
            response = await self.http_client.get(
                f"{self.settings.europe_pmc_base_url}/search",
                params={"query": " OR ".join(query_parts), "format": "json", "pageSize": 1, "resultType": "core"},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            result = (((response.json() or {}).get("resultList") or {}).get("result") or [])
            if result:
                pmcid = str((result[0] or {}).get("pmcid") or "").strip()
                if pmcid:
                    return pmcid if pmcid.startswith("PMC") else f"PMC{pmcid}"
        except Exception:
            return None
        return None

    async def _crossref_links(self, doi: str, *, want_xml: bool) -> list[str]:
        try:
            response = await self.http_client.get(
                f"{self.settings.crossref_base_url}/works/{quote(doi, safe='')}",
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            links = ((response.json() or {}).get("message") or {}).get("link") or []
        except Exception:
            return []
        urls: list[str] = []
        for item in links:
            url = str(item.get("URL") or "").strip()
            content_type = str(item.get("content-type") or "").lower()
            if not url:
                continue
            if want_xml and ("xml" in content_type):
                urls.append(url)
            if not want_xml and ("pdf" in content_type or url.lower().endswith(".pdf")):
                urls.append(url)
        return urls

    async def _europe_pmc_repo_candidates(self, pmc_id: str, *, file_type: str) -> list[str]:
        try:
            response = await self.http_client.get(
                EUROPE_PMC_REPO_URL,
                params={"pmcId": pmc_id, "type": "METADATA"},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        version = int(float(payload.get("version") or 1))
        urls: list[str] = []
        for file_item in payload.get("files") or []:
            mime_type = str(file_item.get("mimeType") or "")
            current_type = str(file_item.get("type") or "").lower()
            filename = str(file_item.get("filename") or "")
            if not filename:
                continue
            if file_type == "xml" and ("xml" not in mime_type.lower() and current_type != "xml"):
                continue
            if file_type == "pdf" and ("pdf" not in mime_type.lower() and current_type != "pdf"):
                continue
            urls.append(
                f"{EUROPE_PMC_REPO_URL}?pmcId={pmc_id}&type=FILE"
                f"&fileName={quote(filename, safe='')}"
                f"&mimeType={quote(mime_type, safe='')}"
                f"&version={version}&pmc_pageType=pdf&pmc_domain=null"
            )
        return urls

    async def _europe_pmc_fulltext_links(self, article: ArticleReference, *, want_xml: bool) -> list[str]:
        query_parts = []
        if article.pmc_id:
            query_parts.append(f"PMCID:{article.pmc_id}")
        if article.doi:
            query_parts.append(f'DOI:"{article.doi}"')
        if article.pmid:
            query_parts.append(f"EXT_ID:{article.pmid}")
        if not query_parts:
            return []
        try:
            response = await self.http_client.get(
                f"{self.settings.europe_pmc_base_url}/search",
                params={"query": " OR ".join(query_parts), "format": "json", "pageSize": 1, "resultType": "core"},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            rows = (((response.json() or {}).get("resultList") or {}).get("result") or [])
        except Exception:
            return []
        urls: list[str] = []
        if not rows:
            return urls
        for entry in (((rows[0] or {}).get("fullTextUrlList") or {}).get("fullTextUrl") or []):
            url = str((entry or {}).get("url") or "").strip()
            style = str((entry or {}).get("documentStyle") or "").lower()
            if not url:
                continue
            if want_xml and ("xml" in style or "xml" in url.lower()):
                urls.append(url)
            if not want_xml and ("pdf" in style or url.lower().endswith(".pdf") or "pdf" in url.lower()):
                urls.append(url)
        return urls

    async def _pmc_oa_package_links(self, pmc_id: str) -> list[str]:
        try:
            response = await self.http_client.get(
                self.settings.pmc_oa_base_url,
                params={"id": pmc_id},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except Exception:
            return []
        urls = []
        for link in root.findall(".//record/link"):
            href = str(link.attrib.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("ftp://"):
                href = "https://" + href[6:]
            urls.append(href)
        return urls

    async def _doi_landing_pdf_links(self, doi: str, landing_url: str | None = None) -> list[str]:
        target_url = landing_url or f"{self.settings.doi_resolver_base_url}/{quote(doi, safe='')}"
        try:
            response = await self.http_client.get(
                target_url,
                headers={"User-Agent": self.settings.request_user_agent, "Accept": "text/html,*/*"},
                follow_redirects=True,
                timeout=10.0,
            )
            if response.status_code != 200:
                return []
            content_type = (response.headers.get("content-type") or "").lower()
            if "html" not in content_type:
                return []
        except Exception:
            return []
        html = response.text
        base_url = str(response.url)
        urls: list[str] = []
        for pattern in (
            r'citation_pdf_url[^>]+content=["\']([^"\']+)',
            r'href=["\']([^"\']*\.pdf[^"\']*)["\']',
            r'href=["\']([^"\']*type=printable[^"\']*)["\']',
        ):
            for match in re.finditer(pattern, html, re.IGNORECASE):
                urls.append(urljoin(base_url, match.group(1)))
        deduped: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            deduped.append(url)
        return deduped

    async def _ncbi_linkout_candidates(self, pmid: str) -> list[str]:
        try:
            response = await self.http_client.get(
                f"{self.settings.ncbi_base_url}/elink.fcgi",
                params={"dbfrom": "pubmed", "id": pmid, "cmd": "prlinks", "retmode": "json"},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []
        urls: list[str] = []
        for linkset in payload.get("linksets", []) if isinstance(payload, dict) else []:
            for idurllist in linkset.get("idurllist", []) if isinstance(linkset, dict) else []:
                for objurl in idurllist.get("objurls", []) if isinstance(idurllist, dict) else []:
                    url_value = ((objurl.get("url") or {}).get("value") or "").strip()
                    if url_value:
                        urls.append(url_value)
        return urls

    @staticmethod
    def _is_fulltext_xml(content_type: str, content: bytes) -> bool:
        lowered = content[:2000].lower()
        if "xml" not in content_type and b"<?xml" not in lowered and b"<article" not in lowered:
            return False
        return any(token in lowered for token in (b"<article", b"<body", b"<full-text-retrieval-response", b"<articleset"))

    @staticmethod
    def _is_pdf_payload(content_type: str, content: bytes) -> bool:
        return content.startswith(b"%PDF") and (
            "pdf" in content_type or "octet-stream" in content_type or not content_type or "application/" in content_type
        )

    @staticmethod
    def _extract_pdf_from_tgz(content: bytes) -> bytes | None:
        try:
            archive = tarfile.open(fileobj=io.BytesIO(content), mode="r:gz")
        except tarfile.TarError:
            return None
        for member in archive.getmembers():
            if not member.isfile() or not member.name.lower().endswith(".pdf"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            if data.startswith(b"%PDF"):
                return data
        return None

    @staticmethod
    def _build_file_path(article: ArticleReference, source: str, target_dir: Path, suffix: str) -> Path:
        year_part = article.year or "unknown_year"
        year_dir = target_dir / f"year_{year_part}"
        year_dir.mkdir(parents=True, exist_ok=True)
        title = article.title or article.pmid or article.doi or article.pmc_id or "article"
        stem = sanitize_filename(title)
        return ensure_unique_path(year_dir / f"{stem}_{source}{suffix}")

    @staticmethod
    def _dedupe_candidates(candidates: list[DownloadCandidate]) -> list[DownloadCandidate]:
        deduped: list[DownloadCandidate] = []
        seen: set[tuple[str, str]] = set()
        for candidate in sorted(candidates, key=lambda item: (item.priority, item.source, item.url)):
            key = (candidate.source, candidate.url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped


class XMLPipeline(_BasePipeline):
    async def resolve_candidates(self, article: ArticleReference, *, mode: str) -> list[DownloadCandidate]:
        candidates: list[DownloadCandidate] = []
        pmc_id = await self._resolve_pmc_id(article)
        enriched_article = article.model_copy(update={"pmc_id": pmc_id or article.pmc_id})
        if pmc_id:
            raw_id = pmc_id.replace("PMC", "")
            candidates.append(
                DownloadCandidate(
                    source="pmc_efetch_xml",
                    url=f"{self.settings.ncbi_base_url}/efetch.fcgi?db=pmc&id={raw_id}&retmode=xml",
                    file_type="xml",
                    priority=0,
                )
            )
            for url in await self._europe_pmc_repo_candidates(pmc_id, file_type="xml"):
                candidates.append(DownloadCandidate(source="europe_pmc_repo_xml", url=url, file_type="xml", priority=1))
        for url in await self._europe_pmc_fulltext_links(enriched_article, want_xml=True):
            candidates.append(DownloadCandidate(source="europe_pmc_xml", url=url, file_type="xml", priority=2))
        if article.doi:
            for url in await self._crossref_links(article.doi, want_xml=True):
                candidates.append(DownloadCandidate(source="crossref_xml", url=url, file_type="xml", priority=3))
        return self._dedupe_candidates(candidates)


class PDFPipeline(_BasePipeline):
    async def resolve_candidates(self, article: ArticleReference, *, mode: str) -> list[DownloadCandidate]:
        candidates: list[DownloadCandidate] = []
        pmc_id = await self._resolve_pmc_id(article)
        enriched_article = article.model_copy(update={"pmc_id": pmc_id or article.pmc_id})
        if article.oa_pdf_url:
            candidates.append(DownloadCandidate(source="article_oa_pdf", url=article.oa_pdf_url, file_type="pdf", priority=0))
        if pmc_id:
            candidates.append(
                DownloadCandidate(
                    source="pmc_direct_pdf",
                    url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/",
                    file_type="pdf",
                    priority=1,
                )
            )
            for url in await self._pmc_oa_package_links(pmc_id):
                file_type = "tgzpdf" if url.endswith(".tar.gz") else "pdf"
                priority = 0 if file_type == "tgzpdf" else 2
                candidates.append(DownloadCandidate(source="pmc_oa_package", url=url, file_type=file_type, priority=priority))
            for url in await self._europe_pmc_repo_candidates(pmc_id, file_type="pdf"):
                candidates.append(DownloadCandidate(source="europe_pmc_repo_pdf", url=url, file_type="pdf", priority=3))
            candidates.append(
                DownloadCandidate(
                    source="europe_pmc_render_pdf",
                    url=f"https://europepmc.org/articles/{pmc_id}?pdf=render",
                    file_type="pdf",
                    priority=4,
                )
            )
        if article.doi:
            for url in await self._crossref_links(article.doi, want_xml=False):
                candidates.append(DownloadCandidate(source="crossref_pdf", url=url, file_type="pdf", priority=5))
            for url in await self._doi_landing_pdf_links(article.doi, article.landing_page_url):
                candidates.append(DownloadCandidate(source="doi_landing_pdf", url=url, file_type="pdf", priority=6))
        if article.landing_page_url and article.doi:
            for url in await self._doi_landing_pdf_links(article.doi, article.landing_page_url):
                candidates.append(DownloadCandidate(source="article_landing_pdf", url=url, file_type="pdf", priority=6))
        if article.landing_page_url:
            candidates.append(
                DownloadCandidate(
                    source="landing_page_probe",
                    url=article.landing_page_url,
                    file_type="pdf",
                    priority=8,
                )
            )
        if article.pmid:
            for url in await self._ncbi_linkout_candidates(article.pmid):
                candidates.append(DownloadCandidate(source="ncbi_linkout_pdf", url=url, file_type="pdf", priority=7))
        return self._dedupe_candidates(candidates)


class BestAvailablePipeline:
    def __init__(self, xml_pipeline: XMLPipeline, pdf_pipeline: PDFPipeline) -> None:
        self.xml_pipeline = xml_pipeline
        self.pdf_pipeline = pdf_pipeline

    async def resolve_candidates(self, article: ArticleReference, *, mode: str) -> list[DownloadCandidate]:
        xml_candidates, pdf_candidates = await asyncio.gather(
            self.xml_pipeline.resolve_candidates(article, mode=mode),
            self.pdf_pipeline.resolve_candidates(article, mode=mode),
        )
        return [*xml_candidates, *pdf_candidates]

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str,
        budget_seconds: float,
        save_file: bool = True,
    ) -> dict[str, Any]:
        xml_payload = await self.xml_pipeline.run(
            article,
            output_dir=output_dir,
            mode=mode,
            budget_seconds=max(5.0, budget_seconds * 0.45),
            save_file=save_file,
        )
        pdf_payload = await self.pdf_pipeline.run(
            article,
            output_dir=output_dir,
            mode=mode,
            budget_seconds=max(5.0, budget_seconds * 0.55),
            save_file=save_file,
        )
        if pdf_payload.get("success"):
            merged_attempts = [*(xml_payload.get("attempts") or []), *(pdf_payload.get("attempts") or [])]
            pdf_payload["attempts"] = merged_attempts
            pdf_payload["candidate_count"] = int(xml_payload.get("candidate_count") or 0) + int(pdf_payload.get("candidate_count") or 0)
            return pdf_payload
        if xml_payload.get("success"):
            xml_payload["attempts"] = [*(xml_payload.get("attempts") or []), *(pdf_payload.get("attempts") or [])]
            xml_payload["candidate_count"] = int(xml_payload.get("candidate_count") or 0) + int(pdf_payload.get("candidate_count") or 0)
            return xml_payload
        return {
            "article": article.model_dump(),
            "mode": mode,
            "success": False,
            "source": None,
            "url": None,
            "file_path": None,
            "total_ms": int((xml_payload.get("total_ms") or 0) + (pdf_payload.get("total_ms") or 0)),
            "candidate_count": int(xml_payload.get("candidate_count") or 0) + int(pdf_payload.get("candidate_count") or 0),
            "attempts": [*(xml_payload.get("attempts") or []), *(pdf_payload.get("attempts") or [])],
            "note": pdf_payload.get("note") or xml_payload.get("note") or "no_successful_candidate",
        }


class PDFService:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        settings: Settings,
        candidate_cache: TTLCache[str, list[PDFCandidate]],
        event_log_service: AppEventLogService | None = None,
    ) -> None:
        self.http_client = http_client
        self.settings = settings
        self.candidate_cache = candidate_cache
        self.event_log_service = event_log_service
        self.xml_pipeline = XMLPipeline(http_client, settings)
        self.pdf_pipeline = PDFPipeline(http_client, settings)
        self.best_pipeline = BestAvailablePipeline(self.xml_pipeline, self.pdf_pipeline)

    @staticmethod
    def _exact_mode(mode: str) -> str:
        return mode if mode in {"fast", "balanced"} else "fast"

    def _downloader_mode(self, requested: str | None = None) -> str:
        normalized = (requested or self.settings.pdf_downloader_mode or "pdf_xml").strip().lower()
        aliases = {
            "best": "pdf_xml",
            "legacy": "pdf_xml",
            "article_downloader": "pdf_xml",
            "hybrid": "pdf_xml",
            "final_method": "pdf_xml",
            "perfect": "pdf_xml",
            "native": "pdf_xml",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized in {"xml", "pdf", "pdf_xml"}:
            return normalized
        return "pdf_xml"

    def _pipeline_for(self, downloader_mode: str) -> XMLPipeline | PDFPipeline | BestAvailablePipeline:
        if downloader_mode == "xml":
            return self.xml_pipeline
        if downloader_mode == "pdf":
            return self.pdf_pipeline
        return self.best_pipeline

    async def resolve(
        self,
        article: ArticleReference,
        *,
        mode: str = "fast",
        downloader_mode: str | None = None,
    ) -> PDFResolveResponse:
        exact_mode = self._exact_mode(mode)
        selected_mode = self._downloader_mode(downloader_mode)
        cache_key = self._candidate_cache_key(article, exact_mode, selected_mode)
        cached = self.candidate_cache.get(cache_key)
        if cached is not None:
            return PDFResolveResponse(article=article, candidates=cached, cache_hit=True)
        pipeline = self._pipeline_for(selected_mode)
        candidate_payloads = await pipeline.resolve_candidates(article, mode=exact_mode)
        candidates = [PDFCandidate(source=item.source, url=item.url) for item in candidate_payloads]
        self.candidate_cache.set(cache_key, candidates)
        return PDFResolveResponse(article=article, candidates=candidates, cache_hit=False)

    async def quick_availability(self, articles: list[ArticleReference]) -> PDFAvailabilityResponse:
        results: list[PDFAvailabilityItem] = []
        for article in articles:
            with tempfile.TemporaryDirectory() as temp_dir:
                payload = await self.best_pipeline.run(
                    article,
                    output_dir=Path(temp_dir),
                    mode="fast",
                    budget_seconds=30.0,
                    save_file=False,
                )
            results.append(
                PDFAvailabilityItem(
                    article=article,
                    ready=bool(payload.get("success")),
                    source=payload.get("source"),
                    candidate_count=int(payload.get("candidate_count") or 0),
                    detail="verified" if payload.get("success") else str(payload.get("note") or "not_downloadable"),
                )
            )
        return PDFAvailabilityResponse(items=results)

    async def download_articles(self, request: PDFDownloadRequest) -> PDFDownloadResponse:
        target_dir = self._resolve_target_dir(request.download_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        articles = request.articles[: request.max_articles] if request.max_articles else request.articles
        selected_mode = self._downloader_mode(request.downloader_mode)
        exact_mode = self._exact_mode(request.mode)
        pipeline = self._pipeline_for(selected_mode)
        semaphore = asyncio.Semaphore(self._download_concurrency_for_articles(exact_mode, articles))

        async def run_single(article: ArticleReference) -> PDFDownloadResult:
            async with semaphore:
                payload = await pipeline.run(article, output_dir=target_dir, mode=exact_mode, budget_seconds=60.0)
                return self._to_pdf_download_result(article, payload)

        results = await asyncio.gather(*(run_single(article) for article in articles))
        success_count = sum(1 for item in results if item.success)
        return PDFDownloadResponse(
            total=len(results),
            success_count=success_count,
            failed_count=len(results) - success_count,
            results=results,
        )

    async def diagnose_articles(
        self,
        articles: list[ArticleReference],
        *,
        download_dir: str | None = None,
        save_files: bool = True,
        mode: str = "fast",
        downloader_mode: str | None = None,
        use_browser_fallback: bool = False,
    ) -> list[PDFTestResult]:
        _ = use_browser_fallback
        temp_dir_context: tempfile.TemporaryDirectory[str] | None = None
        if save_files:
            target_dir = self._resolve_target_dir(download_dir)
        else:
            temp_dir_context = tempfile.TemporaryDirectory()
            target_dir = Path(temp_dir_context.name)
        target_dir.mkdir(parents=True, exist_ok=True)
        pipeline = self._pipeline_for(self._downloader_mode(downloader_mode))
        results: list[PDFTestResult] = []
        try:
            for article in articles:
                payload = await pipeline.run(
                    article,
                    output_dir=target_dir,
                    mode=self._exact_mode(mode),
                    budget_seconds=60.0,
                    save_file=save_files,
                )
                results.append(self._to_pdf_test_result(article, payload, expose_file_path=save_files))
            return results
        finally:
            if temp_dir_context is not None:
                temp_dir_context.cleanup()

    @staticmethod
    def _candidate_cache_key(article: ArticleReference, mode: str, downloader_mode: str) -> str:
        return "|".join(
            [
                downloader_mode,
                mode,
                article.doi or "",
                article.pmc_id or "",
                article.pmid or "",
                article.oa_pdf_url or "",
                article.landing_page_url or "",
            ]
        )

    @staticmethod
    def _download_concurrency_for_articles(mode: str, articles: list[ArticleReference]) -> int:
        batch_size = max(1, len(articles))
        return min(4 if mode == "fast" else 8, batch_size)

    def _resolve_target_dir(self, download_dir: str | None) -> Path:
        if download_dir:
            return Path(download_dir).expanduser().resolve()
        return self.settings.download_root.expanduser().resolve()

    @staticmethod
    def _result_content_metadata(file_path: str | None) -> tuple[str | None, str | None]:
        if not file_path:
            return None, None
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            return "pdf", "application/pdf"
        if suffix == ".xml":
            return "xml_fulltext", "application/xml"
        return None, None

    def _to_pdf_download_result(self, article: ArticleReference, payload: dict[str, Any]) -> PDFDownloadResult:
        content_kind, content_type = self._result_content_metadata(payload.get("file_path"))
        return PDFDownloadResult(
            article=article,
            success=bool(payload.get("success")),
            source=payload.get("source"),
            url=payload.get("url"),
            file_path=payload.get("file_path"),
            content_kind=content_kind,
            content_type=content_type,
            candidate_count=int(payload.get("candidate_count") or 0),
            error=None if payload.get("success") else str(payload.get("note") or "no_successful_candidate"),
        )

    def _to_pdf_test_result(self, article: ArticleReference, payload: dict[str, Any], *, expose_file_path: bool) -> PDFTestResult:
        content_kind, content_type = self._result_content_metadata(payload.get("file_path"))
        return PDFTestResult(
            article=article,
            success=bool(payload.get("success")),
            reason="downloadable" if payload.get("success") else str(payload.get("note") or "no_successful_candidate"),
            source=payload.get("source"),
            url=payload.get("url"),
            file_path=payload.get("file_path") if expose_file_path else None,
            content_kind=content_kind,
            content_type=content_type,
            candidate_count=int(payload.get("candidate_count") or 0),
            attempts=self._payload_attempts_to_test(payload),
        )

    @staticmethod
    def _payload_attempts_to_test(payload: dict[str, Any]) -> list[PDFTestAttempt]:
        return [
            PDFTestAttempt(
                source=str(item.get("source") or ""),
                url=str(item.get("url") or ""),
                status_code=item.get("status_code"),
                content_type=item.get("content_type"),
                success=str(item.get("status") or "") == "ok",
                error=None if str(item.get("status") or "") == "ok" else str(item.get("detail") or ""),
            )
            for item in payload.get("attempts") or []
        ]
