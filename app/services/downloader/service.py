"""PDF resolution and download service."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import math
import re
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, TypeVar
from urllib.parse import quote, urljoin, urlparse, urlunparse
from uuid import uuid4

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
from app.services.downloader.article_downloader_bridge import ArticleDownloaderBridge
from app.services.downloader.hybrid_bridge import HybridDownloaderBridge
from app.services.downloader.final_method.orchestrator import FinalMethodBridge
from app.services.downloader.legacy_bridge import ExactNewMethodBridge
from app.utils.cache import TTLCache
from app.utils.files import ensure_unique_path, sanitize_filename
from app.utils.rate_limit import AsyncRateLimiter

_T = TypeVar("_T")

DOAJ_SEARCH_URL = "https://doaj.org/api/search/articles"
EUROPE_PMC_REPO_URL = "https://europepmc.org/api/fulltextRepo"


@dataclass
class _ProbeOutcome:
    candidate: PDFCandidate
    status_code: int | None = None
    content_type: str | None = None
    mode: str | None = None
    payload_bytes: bytes | None = None
    content_kind: str | None = None
    extension: str | None = None
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.status_code in {200, 206} and self.content_kind is not None and self.error is None

    def to_attempt(self) -> PDFTestAttempt:
        return PDFTestAttempt(
            source=self.candidate.source,
            url=self.candidate.url,
            status_code=self.status_code,
            content_type=self.content_type,
            mode=self.mode,
            success=self.success,
            error=self.error,
        )


class _BrowserFallbackRuntime:
    def __init__(self, settings: Settings, playwright, browser, timeout_error_cls) -> None:  # noqa: ANN001
        self.settings = settings
        self._playwright = playwright
        self._browser = browser
        self._timeout_error_cls = timeout_error_cls
        self._semaphore = asyncio.Semaphore(max(1, settings.pdf_browser_fallback_concurrency))

    @classmethod
    async def create(cls, settings: Settings) -> _BrowserFallbackRuntime | None:
        try:
            from playwright.async_api import TimeoutError as PlaywrightTimeoutError
            from playwright.async_api import async_playwright
        except ImportError:
            return None

        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception:
            await playwright.stop()
            return None
        return cls(settings, playwright, browser, PlaywrightTimeoutError)

    async def close(self) -> None:
        await self._browser.close()
        await self._playwright.stop()

    @staticmethod
    async def _filter_route(route) -> None:  # noqa: ANN001
        if route.request.resource_type in {"image", "media", "font", "stylesheet"}:
            await route.abort()
            return
        await route.continue_()

    async def download_article(
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        *,
        mode: str,
        candidates: list[PDFCandidate] | None = None,
    ) -> PDFDownloadResult | None:
        browser_targets = service._browser_target_pages(article, mode=mode, candidates=candidates)
        if not browser_targets:
            return None

        async with self._semaphore:
            context = await self._browser.new_context(
                accept_downloads=True,
                user_agent=service._download_headers()["User-Agent"],
                viewport={"width": 1440, "height": 1024},
            )
            await context.route("**/*", self._filter_route)
            try:
                for source_hint, article_url in browser_targets:
                    result = await self._download_from_page(
                        service,
                        article,
                        target_dir,
                        context,
                        source_hint,
                        article_url,
                    )
                    if result is not None:
                        return result
            except Exception:
                return None
            finally:
                await context.close()

        return None

    async def _download_from_page(  # noqa: PLR0912
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        context,  # noqa: ANN001
        source_hint: str,
        article_url: str,
    ) -> PDFDownloadResult | None:
        page = await context.new_page()
        probe_page = await context.new_page()
        try:
            response = await page.goto(article_url, wait_until="domcontentloaded", timeout=10_000)
            direct_result = await self._save_navigation_pdf(
                service,
                article,
                target_dir,
                source_hint,
                page.url,
                response,
            )
            if direct_result is not None:
                return direct_result

            await page.wait_for_timeout(250)
            raw_candidates = await page.evaluate(
                """
                () => {
                  const seen = new Set();
                  const values = [];
                  const add = (value) => {
                    if (!value || seen.has(value)) return;
                    seen.add(value);
                    values.push(value);
                  };
                  const hrefNodes = Array.from(document.querySelectorAll('a[href], link[href]'));
                  for (const node of hrefNodes) {
                    const href = node.href || node.getAttribute('href') || '';
                    const text = (node.textContent || '').toLowerCase();
                    const lower = href.toLowerCase();
                    if (
                      lower.includes('.pdf') ||
                      lower.includes('/pdf') ||
                      lower.includes('epdf') ||
                      lower.includes('pdfdirect') ||
                      lower.includes('downloadpdf') ||
                      lower.includes('article-pdf') ||
                      lower.includes('type=printable') ||
                      text.includes('pdf')
                    ) {
                      add(href);
                    }
                  }
                  const metaSelectors = [
                    "meta[name='citation_pdf_url']",
                    "meta[property='citation_pdf_url']",
                    "meta[name='wkhealth_pdf_url']",
                    "meta[name='citation_fulltext_html_url']",
                  ];
                  for (const selector of metaSelectors) {
                    const node = document.querySelector(selector);
                    if (node) add(node.getAttribute('content') || '');
                  }
                  const embeds = Array.from(document.querySelectorAll('iframe[src], embed[src], object[data]'));
                  for (const node of embeds) {
                    add(node.getAttribute('src') || node.getAttribute('data') || '');
                  }
                  return values.slice(0, 12);
                }
                """
            )
            pdf_links = service._expand_browser_pdf_candidates(raw_candidates, page.url, article)
            for pdf_url in pdf_links:
                result = await self._download_candidate_url(
                    service,
                    article,
                    target_dir,
                    context,
                    probe_page,
                    source_hint,
                    article_url,
                    pdf_url,
                )
                if result is not None:
                    return result

            return await self._click_pdf_actions(
                service,
                article,
                target_dir,
                page,
                source_hint,
            )
        except Exception:
            return None
        finally:
            await probe_page.close()
            await page.close()

    async def _download_candidate_url(
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        context,  # noqa: ANN001
        probe_page,  # noqa: ANN001
        source_hint: str,
        referer: str,
        pdf_url: str,
    ) -> PDFDownloadResult | None:
        try:
            response = await context.request.get(
                pdf_url,
                headers={"Referer": referer, "Accept": "application/pdf,*/*"},
                timeout=8_000,
            )
            content_type = (response.headers.get("content-type") or "").lower()
            content = await response.body()
            if response.status == 200 and service._is_pdf_payload(content_type, content):
                return service._save_browser_pdf(article, target_dir, source_hint, pdf_url, content)
        except Exception:
            pass

        try:
            navigation = await probe_page.goto(pdf_url, wait_until="domcontentloaded", timeout=8_000)
            direct_result = await self._save_navigation_pdf(
                service,
                article,
                target_dir,
                source_hint,
                probe_page.url,
                navigation,
            )
            if direct_result is not None:
                return direct_result
        except Exception:
            pass

        try:
            async with probe_page.expect_download(timeout=6_000) as download_info:
                await probe_page.goto(pdf_url, wait_until="domcontentloaded", timeout=8_000)
            download = await download_info.value
            return await self._save_download_file(service, article, target_dir, source_hint, pdf_url, download)
        except self._timeout_error_cls:
            return None
        except Exception:
            return None

    async def _click_pdf_actions(
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        page,  # noqa: ANN001
        source_hint: str,
    ) -> PDFDownloadResult | None:
        selectors = [
            "a[href*='.pdf']",
            "a[href*='/pdf/']",
            "a[href*='epdf']",
            "a[href*='pdfdirect']",
            "a[href*='article-pdf']",
            "a[href*='downloadpdf']",
            "a:has-text('Download PDF')",
            "a:has-text('View PDF')",
            "a:has-text('PDF')",
            "button:has-text('Download PDF')",
            "button:has-text('PDF')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                async with page.expect_download(timeout=6_000) as download_info:
                    await locator.click(timeout=2_500)
                download = await download_info.value
                return await self._save_download_file(
                    service,
                    article,
                    target_dir,
                    source_hint,
                    page.url,
                    download,
                )
            except self._timeout_error_cls:
                continue
            except Exception:
                continue
        return None

    async def _save_navigation_pdf(
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        source_hint: str,
        url: str,
        response,  # noqa: ANN001
    ) -> PDFDownloadResult | None:
        if response is None:
            return None
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            if "pdf" not in content_type and "octet-stream" not in content_type:
                return None
            content = await response.body()
        except Exception:
            return None
        if not service._is_pdf_payload(content_type, content):
            return None
        return service._save_browser_pdf(article, target_dir, source_hint, url, content)

    async def _save_download_file(
        self,
        service: PDFService,
        article: ArticleReference,
        target_dir: Path,
        source_hint: str,
        url: str,
        download,  # noqa: ANN001
    ) -> PDFDownloadResult | None:
        file_path = service._build_file_path(article, source_hint, target_dir)
        await download.save_as(str(file_path))
        file_bytes = file_path.read_bytes()
        if file_bytes.startswith(b"%PDF"):
            return PDFDownloadResult(
                article=article,
                success=True,
                source=source_hint,
                url=url,
                file_path=str(file_path),
                content_kind="pdf",
                content_type="application/pdf",
            )
        file_path.unlink(missing_ok=True)
        return None


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
        self.availability_cache: TTLCache[str, PDFAvailabilityItem] = TTLCache(
            ttl_seconds=min(settings.pdf_cache_ttl_seconds, 900),
            max_entries=max(512, settings.pdf_cache_max_entries * 4),
        )
        self.resolve_rate_limiter = AsyncRateLimiter(settings.pdf_resolve_requests_per_second)
        transport = getattr(http_client, "_transport", None)
        self.legacy_bridge = ExactNewMethodBridge(transport=transport)
        self.article_downloader_bridge = ArticleDownloaderBridge()
        self.hybrid_bridge = HybridDownloaderBridge(
            legacy_bridge=self.legacy_bridge,
            article_downloader_bridge=self.article_downloader_bridge,
        )
        self.final_method_bridge = FinalMethodBridge()

    @staticmethod
    def _resolve_timeout() -> httpx.Timeout:
        return httpx.Timeout(connect=4.0, read=4.0, write=4.0, pool=2.0)

    @staticmethod
    def _exact_mode(mode: str) -> str:
        return mode if mode in {"fast", "balanced"} else "fast"

    def _downloader_mode(self, requested: str | None = None) -> str:
        normalized = (requested or self.settings.pdf_downloader_mode or "legacy").strip().lower()
        if normalized in {"legacy", "article_downloader", "hybrid", "native", "final_method"}:
            return normalized
        return "legacy"

    def _bridge_for(self, downloader_mode: str):
        if downloader_mode == "article_downloader":
            return self.article_downloader_bridge
        if downloader_mode == "hybrid":
            return self.hybrid_bridge
        if downloader_mode == "final_method":
            return self.final_method_bridge
        return self.legacy_bridge

    @staticmethod
    def _result_content_metadata(file_path: str | None) -> tuple[str | None, str | None]:
        if not file_path:
            return None, None
        suffix = Path(file_path).suffix.lower()
        if suffix == ".pdf":
            return "pdf", "application/pdf"
        if suffix == ".xml":
            return "xml_fulltext", "application/xml"
        if suffix == ".html":
            return "html_fulltext", "text/html"
        if suffix == ".txt":
            return "text_fulltext", "text/plain"
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
            error=None if payload.get("success") else (payload.get("note") or "no_successful_candidate"),
        )

    def _to_pdf_test_result(self, article: ArticleReference, payload: dict[str, Any], *, expose_file_path: bool) -> PDFTestResult:
        content_kind, content_type = self._result_content_metadata(payload.get("file_path"))
        attempts = self._payload_attempts_to_test(payload)
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
            attempts=attempts,
        )

    @staticmethod
    def _payload_attempts_to_test(payload: dict[str, Any]) -> list[PDFTestAttempt]:
        return [
            PDFTestAttempt(
                source=str(item.get("source") or ""),
                url=str(item.get("url") or ""),
                status_code=item.get("status_code"),
                content_type=item.get("content_type"),
                mode=None,
                success=str(item.get("status") or "") == "ok",
                error=None if str(item.get("status") or "") == "ok" else item.get("detail"),
            )
            for item in payload.get("attempts") or []
        ]

    @staticmethod
    def _merge_hybrid_reason(bridge_payload: dict[str, Any], native_result: PDFTestResult) -> str:
        bridge_reason = str(bridge_payload.get("note") or "").strip()
        if native_result.success:
            return "downloadable"
        if native_result.reason and native_result.reason != "no_valid_pdf_payload":
            return native_result.reason
        if bridge_reason:
            return bridge_reason
        return native_result.reason or "no_successful_candidate"

    async def resolve(
        self,
        article: ArticleReference,
        *,
        mode: str = "fast",
        downloader_mode: str | None = None,
    ) -> PDFResolveResponse:
        exact_mode = self._exact_mode(mode)
        selected_downloader_mode = self._downloader_mode(downloader_mode)
        cache_key = self._candidate_cache_key(article, exact_mode, selected_downloader_mode)
        cached = self.candidate_cache.get(cache_key)
        if cached is not None:
            return PDFResolveResponse(article=article, candidates=cached, cache_hit=True)

        if selected_downloader_mode == "native":
            candidates = await self._build_candidates(article, mode=exact_mode)
        else:
            candidate_payloads = await self._bridge_for(selected_downloader_mode).resolve_candidates(article, mode=exact_mode)
            candidates = [PDFCandidate(**item) for item in candidate_payloads]
        self.candidate_cache.set(cache_key, candidates)
        return PDFResolveResponse(article=article, candidates=candidates, cache_hit=False)

    async def quick_availability(self, articles: list[ArticleReference]) -> PDFAvailabilityResponse:
        selected_downloader_mode = self._downloader_mode()
        bridge = self._bridge_for(selected_downloader_mode)
        semaphore = asyncio.Semaphore(1 if selected_downloader_mode == "article_downloader" else 8)

        async def run_single(article: ArticleReference) -> PDFAvailabilityItem:
            cache_key = self._availability_cache_key(article, selected_downloader_mode)
            cached = self.availability_cache.get(cache_key)
            if cached is not None:
                return cached.model_copy(deep=True)
            async with semaphore:
                with tempfile.TemporaryDirectory() as temp_dir:
                    payload = await bridge.run(
                        article,
                        output_dir=Path(temp_dir),
                        mode="fast",
                        budget_seconds=60.0,
                    )
                if not payload.get("success"):
                    result = PDFAvailabilityItem(
                        article=article,
                        ready=False,
                        candidate_count=int(payload.get("candidate_count") or 0),
                        detail=str(payload.get("note") or "Fast verification did not find a downloadable full text candidate."),
                    )
                    self.availability_cache.set(cache_key, result)
                    return result
                result = PDFAvailabilityItem(
                    article=article,
                    ready=True,
                    source=payload.get("source"),
                    candidate_count=int(payload.get("candidate_count") or 0),
                    detail="Fast verification confirmed downloadable full text.",
                )
                self.availability_cache.set(cache_key, result)
                return result

        return PDFAvailabilityResponse(items=await asyncio.gather(*(run_single(article) for article in articles)))

    async def _quick_verify_second_pass(
        self,
        article: ArticleReference,
        candidates: list[PDFCandidate],
    ) -> str | None:
        if not article.pmc_id:
            return None
        if not any(candidate.source == "openalex" for candidate in candidates):
            return None
        tgz_candidates = [candidate for candidate in candidates if candidate.source == "pmc_oa_tgz"]
        if not tgz_candidates:
            return None
        return await self._quick_verify_candidates(tgz_candidates[:1])

    async def _quick_verify_candidates(self, candidates: list[PDFCandidate]) -> str | None:
        if not candidates:
            return None
        semaphore = asyncio.Semaphore(6)

        async def run_single(candidate: PDFCandidate) -> str | None:
            async with semaphore:
                return await self._quick_probe_candidate(candidate)

        tasks = [asyncio.create_task(run_single(candidate)) for candidate in candidates]
        try:
            for completed in asyncio.as_completed(tasks):
                source = await completed
                if source is not None:
                    return source
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        return None

    async def _quick_probe_candidate(self, candidate: PDFCandidate) -> str | None:
        headers = self._candidate_request_headers(candidate.source)
        if not candidate.source.endswith("_html_fulltext") and candidate.source not in {"crossref_elsevier_xml", "europe_pmc_repo_xml"}:
            headers["Range"] = self._quick_probe_range_header(candidate.source)
        try:
            async with self.http_client.stream(
                "GET",
                candidate.url,
                headers=headers,
                follow_redirects=True,
                timeout=self._probe_timeout_seconds("fast", candidate.source),
            ) as response:
                if response.status_code not in {200, 206}:
                    return None
                content_type = (response.headers.get("content-type") or "").lower()
                if candidate.source == "pmc_oa_tgz" or "gzip" in content_type or "x-gzip" in content_type:
                    return candidate.source if await self._quick_probe_tgz_stream(response) else None
                buffer = bytearray()
                async for chunk in response.aiter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) >= self._quick_probe_read_limit(candidate.source, content_type):
                        break
                payload_bytes, _payload_mode, content_kind, _extension = self._extract_download_payload(
                    candidate.url,
                    content_type,
                    bytes(buffer),
                )
                if payload_bytes is not None and content_kind in {"pdf", "html_fulltext", "xml_fulltext", "text_fulltext"}:
                    return candidate.source
        except Exception:
            return None
        return None

    async def _quick_probe_tgz_stream(self, response: httpx.Response) -> bool:
        buffer = bytearray()
        async for chunk in response.aiter_bytes():
            buffer.extend(chunk)
            if len(buffer) >= self._quick_tgz_probe_max_bytes():
                break
        return self._tgz_payload_has_pdf_entry(bytes(buffer))

    async def download_articles(self, request: PDFDownloadRequest) -> PDFDownloadResponse:
        target_dir = self._resolve_target_dir(request.download_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        articles = request.articles[: request.max_articles] if request.max_articles else request.articles
        exact_mode = self._exact_mode(request.mode)
        selected_downloader_mode = self._downloader_mode(request.downloader_mode)
        bridge = self._bridge_for(selected_downloader_mode)
        concurrency = 1 if selected_downloader_mode == "article_downloader" else self._download_concurrency_for_articles(exact_mode, articles)
        semaphore = asyncio.Semaphore(concurrency)
        browser_runtime = await self._prepare_browser_runtime(selected_downloader_mode == "hybrid")
        batch_id = self._new_batch_id()
        batch_started = time.monotonic()
        self._log_download_event(
            "info",
            "pdf_download_batch_start",
            "PDF download batch started.",
            context={
                "batch": batch_id,
                "mode": exact_mode,
                "downloader": selected_downloader_mode,
                "total": len(articles),
                "browser": False,
            },
        )

        async def run_single(index: int, article: ArticleReference) -> tuple[int, PDFDownloadResult]:
            async with semaphore:
                payload = await bridge.run(
                    article,
                    output_dir=target_dir,
                    mode=exact_mode,
                    budget_seconds=60.0,
                )
                result = self._to_pdf_download_result(article, payload)
                if result.success or selected_downloader_mode != "hybrid":
                    return index, result
                native_result = await self._download_single_article(
                    article,
                    target_dir,
                    mode=exact_mode,
                    downloader_mode="native",
                    use_browser_fallback=True,
                    browser_runtime=browser_runtime,
                    batch_id=batch_id,
                    article_index=index + 1,
                    article_total=len(articles),
                )
                if native_result.success:
                    return index, native_result
                native_result.candidate_count = max(native_result.candidate_count, result.candidate_count)
                if result.error and not native_result.error:
                    native_result.error = result.error
                return index, native_result

        try:
            pending = {
                asyncio.create_task(run_single(index, article))
                for index, article in enumerate(articles)
            }
            results: list[PDFDownloadResult | None] = [None] * len(articles)
            success_count = 0
            completed_count = 0
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    self._log_download_event(
                        "info",
                        "pdf_download_batch_heartbeat",
                        "PDF download batch still running.",
                        context={
                            "batch": batch_id,
                            "mode": exact_mode,
                            "downloader": selected_downloader_mode,
                            "done": completed_count,
                            "total": len(articles),
                            "pending": len(pending),
                            "elapsed_ms": int((time.monotonic() - batch_started) * 1000),
                        },
                    )
                    continue
                for task in done:
                    index, result = await task
                    results[index] = result
                    completed_count += 1
                    if result.success:
                        success_count += 1
                    self._log_download_event(
                        "info",
                        "pdf_download_progress",
                        "PDF download article completed.",
                        context={
                            "batch": batch_id,
                            "mode": exact_mode,
                            "downloader": selected_downloader_mode,
                            "done": completed_count,
                            "total": len(articles),
                            "ok": result.success,
                            "article": self._article_log_key(result.article),
                            "source": result.source or "-",
                        },
                    )
            finalized = [item for item in results if item is not None]
            success_count = sum(1 for item in finalized if item.success)
            self._log_download_event(
                "info",
                "pdf_download_batch_done",
                "PDF download batch finished.",
                context={
                    "batch": batch_id,
                    "mode": exact_mode,
                    "downloader": selected_downloader_mode,
                    "total": len(finalized),
                    "ok": success_count,
                    "fail": len(finalized) - success_count,
                    "elapsed_ms": int((time.monotonic() - batch_started) * 1000),
                },
            )
            return PDFDownloadResponse(
                total=len(finalized),
                success_count=success_count,
                failed_count=len(finalized) - success_count,
                results=finalized,
            )
        finally:
            if browser_runtime is not None:
                await browser_runtime.close()

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
        temp_dir_context: tempfile.TemporaryDirectory[str] | None = None
        if save_files:
            target_dir = self._resolve_target_dir(download_dir)
        else:
            temp_dir_context = tempfile.TemporaryDirectory()
            target_dir = Path(temp_dir_context.name)
        target_dir.mkdir(parents=True, exist_ok=True)

        exact_mode = self._exact_mode(mode)
        selected_downloader_mode = self._downloader_mode(downloader_mode)
        bridge = self._bridge_for(selected_downloader_mode)
        concurrency = 1 if selected_downloader_mode == "article_downloader" else self._download_concurrency_for_articles(exact_mode, articles)
        semaphore = asyncio.Semaphore(concurrency)
        browser_runtime = await self._prepare_browser_runtime(selected_downloader_mode == "hybrid")
        batch_id = self._new_batch_id()
        batch_started = time.monotonic()
        self._log_download_event(
            "info",
            "pdf_diagnose_batch_start",
            "PDF diagnose batch started.",
            context={
                "batch": batch_id,
                "mode": exact_mode,
                "downloader": selected_downloader_mode,
                "total": len(articles),
                "browser": False,
                "save": save_files,
            },
        )

        async def run_single(index: int, article: ArticleReference) -> tuple[int, PDFTestResult]:
            async with semaphore:
                payload = await bridge.run(
                    article,
                    output_dir=target_dir,
                    mode=exact_mode,
                    budget_seconds=60.0,
                )
                result = self._to_pdf_test_result(article, payload, expose_file_path=save_files)
                if result.success or selected_downloader_mode != "hybrid":
                    return index, result
                native_result = await self._diagnose_single_article(
                    article,
                    target_dir,
                    mode=exact_mode,
                    downloader_mode="native",
                    use_browser_fallback=True,
                    expose_file_path=save_files,
                    browser_runtime=browser_runtime,
                    batch_id=batch_id,
                    article_index=index + 1,
                    article_total=len(articles),
                )
                native_result.attempts = [*result.attempts, *native_result.attempts]
                native_result.candidate_count = max(
                    native_result.candidate_count,
                    result.candidate_count,
                )
                if not native_result.success:
                    native_result.reason = self._merge_hybrid_reason(payload, native_result)
                return index, native_result

        try:
            pending = {
                asyncio.create_task(run_single(index, article))
                for index, article in enumerate(articles)
            }
            results: list[PDFTestResult | None] = [None] * len(articles)
            completed_count = 0
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=15.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    self._log_download_event(
                        "info",
                        "pdf_diagnose_batch_heartbeat",
                        "PDF diagnose batch still running.",
                        context={
                            "batch": batch_id,
                            "mode": exact_mode,
                            "downloader": selected_downloader_mode,
                            "done": completed_count,
                            "total": len(articles),
                            "pending": len(pending),
                            "elapsed_ms": int((time.monotonic() - batch_started) * 1000),
                        },
                    )
                    continue
                for task in done:
                    index, result = await task
                    results[index] = result
                    completed_count += 1
                    self._log_download_event(
                        "info",
                        "pdf_diagnose_progress",
                        "PDF diagnose article completed.",
                        context={
                            "batch": batch_id,
                            "mode": exact_mode,
                            "downloader": selected_downloader_mode,
                            "done": completed_count,
                            "total": len(articles),
                            "ok": result.success,
                            "article": self._article_log_key(result.article),
                            "reason": result.reason,
                        },
                    )
            finalized = [item for item in results if item is not None]
            self._log_download_event(
                "info",
                "pdf_diagnose_batch_done",
                "PDF diagnose batch finished.",
                context={
                    "batch": batch_id,
                    "mode": exact_mode,
                    "downloader": selected_downloader_mode,
                    "total": len(finalized),
                    "ok": sum(1 for item in finalized if item.success),
                    "fail": sum(1 for item in finalized if not item.success),
                    "elapsed_ms": int((time.monotonic() - batch_started) * 1000),
                },
            )
            return finalized
        finally:
            if browser_runtime is not None:
                await browser_runtime.close()
            if temp_dir_context is not None:
                temp_dir_context.cleanup()

    async def _download_single_article(
        self,
        article: ArticleReference,
        target_dir: Path,
        *,
        mode: str = "fast",
        downloader_mode: str | None = None,
        use_browser_fallback: bool = False,
        browser_runtime: _BrowserFallbackRuntime | None = None,
        batch_id: str | None = None,
        article_index: int | None = None,
        article_total: int | None = None,
    ) -> PDFDownloadResult:
        article_started = time.monotonic()
        self._log_download_event(
            "info",
            "pdf_download_article_start",
            "PDF download article started.",
            context=self._article_trace_context(
                article,
                batch_id=batch_id,
                mode=mode,
                article_index=article_index,
                article_total=article_total,
            ),
        )
        if mode == "fast" and article.pmc_id:
            pmc_preflight_candidates = await self._fast_pmc_preflight_candidates(article)
            if pmc_preflight_candidates:
                success_probe, _attempts = await self._probe_fast_candidates_in_order(
                    pmc_preflight_candidates,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                )
                if success_probe is not None and success_probe.payload_bytes is None:
                    success_probe = await self._await_stage_with_heartbeat(
                        self._download_candidate_payload(success_probe.candidate, mode=mode),
                        article=article,
                        mode=mode,
                        stage="fetch",
                        batch_id=batch_id,
                        article_index=article_index,
                        article_total=article_total,
                        extra_context={"source": success_probe.candidate.source},
                    )
                if success_probe is not None and success_probe.payload_bytes is not None:
                    file_path = self._build_file_path(
                        article,
                        success_probe.candidate.source,
                        target_dir,
                        suffix=success_probe.extension or ".pdf",
                    )
                    file_path.write_bytes(success_probe.payload_bytes)
                    self._log_download_event(
                        "info",
                        "pdf_download_article_done",
                        "PDF download article succeeded.",
                        context=self._article_trace_context(
                            article,
                            batch_id=batch_id,
                            mode=mode,
                            article_index=article_index,
                            article_total=article_total,
                            extra={
                                "source": success_probe.candidate.source,
                                "cand": len(pmc_preflight_candidates),
                                "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                            },
                        ),
                    )
                    return PDFDownloadResult(
                        article=article,
                        success=True,
                        source=success_probe.candidate.source,
                        url=success_probe.candidate.url,
                        file_path=str(file_path),
                        content_kind=success_probe.content_kind,
                        content_type=success_probe.content_type,
                        candidate_count=len(pmc_preflight_candidates),
                    )
        resolved = await self._await_stage_with_heartbeat(
            self.resolve(article, mode=mode, downloader_mode=downloader_mode),
            article=article,
            mode=mode,
            stage="resolve",
            batch_id=batch_id,
            article_index=article_index,
            article_total=article_total,
        )
        probe_candidates = self._download_probe_candidates(article, resolved.candidates, mode=mode)
        if mode == "fast":
            success_probe, _attempts = await self._probe_fast_candidates_in_order(
                probe_candidates,
                article=article,
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
            )
        else:
            success_probe, _attempts = await self._await_stage_with_heartbeat(
                self._probe_candidates(
                    probe_candidates,
                    mode=mode,
                    stop_on_first_success=True,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                ),
                article=article,
                mode=mode,
                stage="probe",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"cand": len(probe_candidates)},
            )
        if success_probe is not None and success_probe.payload_bytes is None:
            success_probe = await self._await_stage_with_heartbeat(
                self._download_candidate_payload(success_probe.candidate, mode=mode),
                article=article,
                mode=mode,
                stage="fetch",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"source": success_probe.candidate.source},
            )
        if success_probe is not None and success_probe.payload_bytes is not None:
            file_path = self._build_file_path(
                article,
                success_probe.candidate.source,
                target_dir,
                suffix=success_probe.extension or ".pdf",
            )
            file_path.write_bytes(success_probe.payload_bytes)
            self._log_download_event(
                "info",
                "pdf_download_article_done",
                "PDF download article succeeded.",
                context=self._article_trace_context(
                    article,
                    batch_id=batch_id,
                    mode=mode,
                    article_index=article_index,
                    article_total=article_total,
                    extra={
                        "source": success_probe.candidate.source,
                        "cand": len(resolved.candidates),
                        "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                    },
                ),
            )
            return PDFDownloadResult(
                article=article,
                success=True,
                source=success_probe.candidate.source,
                url=success_probe.candidate.url,
                file_path=str(file_path),
                content_kind=success_probe.content_kind,
                content_type=success_probe.content_type,
                candidate_count=len(resolved.candidates),
            )

        if use_browser_fallback and self._should_use_browser_fallback(resolved.candidates, _attempts, mode=mode):
            browser_result = await self._await_stage_with_heartbeat(
                self._download_with_browser_fallback(
                    article,
                    target_dir,
                    mode=mode,
                    browser_runtime=browser_runtime,
                    candidates=resolved.candidates,
                ),
                article=article,
                mode=mode,
                stage="browser",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
            )
            if browser_result is not None:
                browser_result.candidate_count = len(resolved.candidates)
                self._log_download_event(
                    "info",
                    "pdf_download_article_done",
                    "PDF download article succeeded via browser.",
                    context=self._article_trace_context(
                        article,
                        batch_id=batch_id,
                        mode=mode,
                        article_index=article_index,
                        article_total=article_total,
                        extra={
                            "source": browser_result.source or "browser",
                            "cand": len(resolved.candidates),
                            "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                        },
                    ),
                )
                return browser_result

        result = PDFDownloadResult(
            article=article,
            success=False,
            candidate_count=len(resolved.candidates),
            error="No downloadable full text candidate succeeded.",
        )
        self._log_download_event(
            "warning",
            "pdf_download_article_done",
            "PDF download article failed.",
            context=self._article_trace_context(
                article,
                batch_id=batch_id,
                mode=mode,
                article_index=article_index,
                article_total=article_total,
                extra={
                    "cand": len(resolved.candidates),
                    "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                },
            ),
        )
        return result

    async def _build_candidates(self, article: ArticleReference, *, mode: str) -> list[PDFCandidate]:
        candidates: list[PDFCandidate] = []
        seen: set[str] = set()

        def add_candidate(source: str, url: str | None) -> None:
            normalized_url = self._normalize_candidate_url(url)
            if not normalized_url or normalized_url in seen:
                return
            seen.add(normalized_url)
            candidates.append(PDFCandidate(source=source, url=normalized_url))

        pmc_task: asyncio.Task[list[str]] | None = None
        europe_pmc_repo_task: asyncio.Task[list[PDFCandidate]] | None = None
        europe_pmc_task: asyncio.Task[list[str]] | None = None
        doi_task: asyncio.Task[dict[str, list[str]]] | None = None
        doaj_task: asyncio.Task[list[PDFCandidate]] | None = None
        ncbi_linkout_task: asyncio.Task[list[PDFCandidate]] | None = None
        article_landing_task: asyncio.Task[list[PDFCandidate]] | None = None
        openalex_landing_tasks: list[asyncio.Task[list[PDFCandidate]]] = []
        openalex_pmc_link_tasks: list[asyncio.Task[list[str]]] = []
        openalex_pmc_repo_tasks: list[asyncio.Task[list[PDFCandidate]]] = []

        add_candidate("article_oa_pdf", article.oa_pdf_url)
        if article.landing_page_url:
            add_candidate("article_landing", article.landing_page_url)
            article_landing_task = asyncio.create_task(
                self._landing_page_candidates_from_url("article_landing", article.landing_page_url)
            )

        pmc = article.pmc_id.upper() if article.pmc_id else None
        if article.pmc_id:
            pmc_task = asyncio.create_task(self._pmc_oa_links(pmc))
            if mode == "balanced" or article.doi:
                europe_pmc_repo_task = asyncio.create_task(self._europe_pmc_repo_candidates(pmc))
            if mode == "balanced" or (mode == "fast" and article.doi):
                europe_pmc_task = asyncio.create_task(self._europe_pmc_fulltext_links(pmc_id=pmc))
            if mode == "balanced":
                add_candidate("europepmc", f"https://europepmc.org/articles/{pmc}?pdf=render")
                add_candidate("europe_pmc_article", f"https://europepmc.org/articles/{pmc}")
                add_candidate("pmc_article_html", f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/")
            add_candidate("pmc_direct", f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc}/pdf/")
        if article.doi:
            doi_task = asyncio.create_task(self._doi_source_map(article.doi, mode=mode))
            doaj_task = asyncio.create_task(self._doaj_candidates(article.doi))
        if article.pmid and not article.pmc_id:
            ncbi_linkout_task = asyncio.create_task(self._ncbi_linkout_candidates(article.pmid))

        pmc_links: list[str] = []
        if pmc_task is not None:
            pmc_links = await pmc_task
            for url in pmc_links:
                source = "pmc_oa_tgz" if url.endswith(".tar.gz") else "pmc_oa_pdf"
                add_candidate(source, url)

        if mode == "fast" and pmc_links and not article.doi:
            return candidates

        if article.pmc_id and europe_pmc_repo_task is None and not article.doi:
            europe_pmc_repo_task = asyncio.create_task(self._europe_pmc_repo_candidates(pmc))

        if europe_pmc_repo_task is not None:
            for candidate in await europe_pmc_repo_task:
                add_candidate(candidate.source, candidate.url)

        doi_source_map: dict[str, list[str]] = {}
        if doi_task is not None:
            doi_source_map = await doi_task
            if mode == "balanced":
                for url in doi_source_map.get("unpaywall", []):
                    add_candidate("unpaywall", url)
                for url in doi_source_map.get("europe_pmc", []):
                    add_candidate("europe_pmc", url)
            for url in doi_source_map.get("crossref", []):
                add_candidate("crossref", url)
            for url in doi_source_map.get("crossref_elsevier_xml", []):
                add_candidate("crossref_elsevier_xml", url)
            for url in doi_source_map.get("openalex", []):
                add_candidate("openalex", url)
            for url in doi_source_map.get("openalex_landing", []):
                add_candidate("openalex_landing", url)
                openalex_landing_tasks.append(
                    asyncio.create_task(self._landing_page_candidates_from_url("openalex_landing", url))
                )
            for pmc_id in doi_source_map.get("openalex_pmc_ids", []):
                normalized_pmc = pmc_id.upper()
                add_candidate("openalex_pmc_direct", f"https://pmc.ncbi.nlm.nih.gov/articles/{normalized_pmc}/pdf/")
                add_candidate("openalex_pmc_article", f"https://pmc.ncbi.nlm.nih.gov/articles/{normalized_pmc}/")
                add_candidate("openalex_europe_pmc_pdf", f"https://europepmc.org/articles/{normalized_pmc}?pdf=render")
                openalex_pmc_link_tasks.append(asyncio.create_task(self._pmc_oa_links(normalized_pmc)))
                openalex_pmc_repo_tasks.append(asyncio.create_task(self._europe_pmc_repo_candidates(normalized_pmc)))
            for url in doi_source_map.get("citation_pdf_url", []):
                add_candidate("citation_pdf_url", url)
            for url in doi_source_map.get("doi_page", []):
                add_candidate("doi_page", url)
            for url in doi_source_map.get("doi_landing", []):
                add_candidate("doi_landing", url)
            for url in doi_source_map.get("doi_guessed", []):
                add_candidate("doi_guessed", url)

        if europe_pmc_task is not None:
            for url in await europe_pmc_task:
                add_candidate("europe_pmc", url)

        if doaj_task is not None:
            for candidate in await doaj_task:
                add_candidate(candidate.source, candidate.url)

        if ncbi_linkout_task is not None:
            for candidate in await ncbi_linkout_task:
                add_candidate(candidate.source, candidate.url)

        if article_landing_task is not None:
            for candidate in await article_landing_task:
                add_candidate(candidate.source, candidate.url)

        for task in openalex_pmc_link_tasks:
            for url in await task:
                source = "pmc_oa_tgz" if url.endswith(".tar.gz") else "pmc_oa_pdf"
                add_candidate(source, url)

        for task in openalex_pmc_repo_tasks:
            for candidate in await task:
                add_candidate(candidate.source, candidate.url)

        for task in openalex_landing_tasks:
            for candidate in await task:
                add_candidate(candidate.source, candidate.url)

        return candidates

    @staticmethod
    def _normalize_candidate_url(url: str | None) -> str | None:
        if not url:
            return None
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

    async def _fast_pmc_preflight_candidates(self, article: ArticleReference) -> list[PDFCandidate]:
        if not article.pmc_id:
            return []
        pmc_links = await self._pmc_oa_links(article.pmc_id.upper())
        candidates = [
            PDFCandidate(
                source="pmc_oa_tgz" if url.endswith(".tar.gz") else "pmc_oa_pdf",
                url=self._normalize_candidate_url(url) or url,
            )
            for url in pmc_links
        ]
        return self._rank_fast_candidates(candidates)

    async def _diagnose_single_article(
        self,
        article: ArticleReference,
        target_dir: Path | None,
        *,
        mode: str = "fast",
        downloader_mode: str | None = None,
        use_browser_fallback: bool = False,
        expose_file_path: bool = True,
        browser_runtime: _BrowserFallbackRuntime | None = None,
        batch_id: str | None = None,
        article_index: int | None = None,
        article_total: int | None = None,
    ) -> PDFTestResult:
        article_started = time.monotonic()
        self._log_download_event(
            "info",
            "pdf_diagnose_article_start",
            "PDF diagnose article started.",
            context=self._article_trace_context(
                article,
                batch_id=batch_id,
                mode=mode,
                article_index=article_index,
                article_total=article_total,
            ),
        )
        preflight_attempts: list[PDFTestAttempt] = []
        if mode == "fast" and article.pmc_id:
            pmc_preflight_candidates = await self._fast_pmc_preflight_candidates(article)
            if pmc_preflight_candidates:
                success_probe, probe_attempts = await self._probe_fast_candidates_in_order(
                    pmc_preflight_candidates,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                )
                preflight_attempts = [outcome.to_attempt() for outcome in probe_attempts]
                if success_probe is not None and success_probe.payload_bytes is None:
                    success_probe = await self._await_stage_with_heartbeat(
                        self._download_candidate_payload(success_probe.candidate, mode=mode),
                        article=article,
                        mode=mode,
                        stage="fetch",
                        batch_id=batch_id,
                        article_index=article_index,
                        article_total=article_total,
                        extra_context={"source": success_probe.candidate.source},
                    )
                if success_probe is not None and success_probe.payload_bytes is not None:
                    file_path: str | None = None
                    if target_dir is not None:
                        output_path = self._build_file_path(
                            article,
                            success_probe.candidate.source,
                            target_dir,
                            suffix=success_probe.extension or ".pdf",
                        )
                        output_path.write_bytes(success_probe.payload_bytes)
                        file_path = str(output_path)
                    result = PDFTestResult(
                        article=article,
                        success=True,
                        reason="downloadable",
                        file_path=file_path if expose_file_path else None,
                        source=success_probe.candidate.source,
                        url=success_probe.candidate.url,
                        attempts=preflight_attempts,
                        candidate_count=len(pmc_preflight_candidates),
                        content_kind=success_probe.content_kind,
                        content_type=success_probe.content_type,
                    )
                    self._log_download_event(
                        "info",
                        "pdf_diagnose_article_done",
                        "PDF diagnose article succeeded.",
                        context=self._article_trace_context(
                            article,
                            batch_id=batch_id,
                            mode=mode,
                            article_index=article_index,
                            article_total=article_total,
                            extra={
                                "source": success_probe.candidate.source,
                                "cand": len(pmc_preflight_candidates),
                                "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                            },
                        ),
                    )
                    return result
        resolved = await self._await_stage_with_heartbeat(
            self.resolve(article, mode=mode, downloader_mode=downloader_mode),
            article=article,
            mode=mode,
            stage="resolve",
            batch_id=batch_id,
            article_index=article_index,
            article_total=article_total,
        )
        probe_candidates = self._download_probe_candidates(article, resolved.candidates, mode=mode)
        if mode == "fast":
            success_probe, probe_attempts = await self._probe_fast_candidates_in_order(
                probe_candidates,
                article=article,
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
            )
        else:
            success_probe, probe_attempts = await self._await_stage_with_heartbeat(
                self._probe_candidates(
                    probe_candidates,
                    mode=mode,
                    stop_on_first_success=True,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                ),
                article=article,
                mode=mode,
                stage="probe",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"cand": len(probe_candidates)},
            )
        attempts = [*preflight_attempts, *(outcome.to_attempt() for outcome in probe_attempts)]
        if success_probe is not None and success_probe.payload_bytes is None:
            success_probe = await self._await_stage_with_heartbeat(
                self._download_candidate_payload(success_probe.candidate, mode=mode),
                article=article,
                mode=mode,
                stage="fetch",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"source": success_probe.candidate.source},
            )
        if success_probe is not None and success_probe.payload_bytes is not None:
            file_path: str | None = None
            if target_dir is not None:
                output_path = self._build_file_path(
                    article,
                    success_probe.candidate.source,
                    target_dir,
                    suffix=success_probe.extension or ".pdf",
                )
                output_path.write_bytes(success_probe.payload_bytes)
                file_path = str(output_path)

            result = PDFTestResult(
                article=article,
                success=True,
                reason="downloadable",
                source=success_probe.candidate.source,
                url=success_probe.candidate.url,
                file_path=file_path,
                content_kind=success_probe.content_kind,
                content_type=success_probe.content_type,
                candidate_count=len(resolved.candidates),
                attempts=attempts,
            )
            self._log_download_event(
                "info",
                "pdf_diagnose_article_done",
                "PDF diagnose article succeeded.",
                context=self._article_trace_context(
                    article,
                    batch_id=batch_id,
                    mode=mode,
                    article_index=article_index,
                    article_total=article_total,
                    extra={
                        "reason": "downloadable",
                        "source": success_probe.candidate.source,
                        "cand": len(resolved.candidates),
                        "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                    },
                ),
            )
            return result

        if use_browser_fallback and target_dir is not None and self._should_use_browser_fallback(resolved.candidates, probe_attempts, mode=mode):
            browser_result = await self._await_stage_with_heartbeat(
                self._download_with_browser_fallback(
                    article,
                    target_dir,
                    mode=mode,
                    browser_runtime=browser_runtime,
                    candidates=resolved.candidates,
                ),
                article=article,
                mode=mode,
                stage="browser",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
            )
            if browser_result is not None:
                attempts.append(
                    PDFTestAttempt(
                        source=browser_result.source or "browser_pmc",
                        url=browser_result.url or f"https://pmc.ncbi.nlm.nih.gov/articles/{article.pmc_id or ''}/",
                        status_code=200,
                        content_type="application/pdf",
                        mode="browser_download",
                        success=True,
                    )
                )
                result = PDFTestResult(
                    article=article,
                    success=True,
                    reason="downloadable",
                    source=browser_result.source,
                    url=browser_result.url,
                    file_path=browser_result.file_path if expose_file_path else None,
                    content_kind=browser_result.content_kind,
                    content_type=browser_result.content_type,
                    candidate_count=len(resolved.candidates),
                    attempts=attempts,
                )
                self._log_download_event(
                    "info",
                    "pdf_diagnose_article_done",
                    "PDF diagnose article succeeded via browser.",
                    context=self._article_trace_context(
                        article,
                        batch_id=batch_id,
                        mode=mode,
                        article_index=article_index,
                        article_total=article_total,
                        extra={
                            "reason": "downloadable",
                            "source": browser_result.source or "browser",
                            "cand": len(resolved.candidates),
                            "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                        },
                    ),
                )
                return result

        result = PDFTestResult(
            article=article,
            success=False,
            reason=self._diagnostic_reason(attempts),
            candidate_count=len(resolved.candidates),
            attempts=attempts,
        )
        self._log_download_event(
            "warning",
            "pdf_diagnose_article_done",
            "PDF diagnose article failed.",
            context=self._article_trace_context(
                article,
                batch_id=batch_id,
                mode=mode,
                article_index=article_index,
                article_total=article_total,
                extra={
                    "reason": result.reason,
                    "cand": len(resolved.candidates),
                    "elapsed_ms": int((time.monotonic() - article_started) * 1000),
                },
            ),
        )
        return result

    async def _prepare_browser_runtime(
        self,
        use_browser_fallback: bool,
    ) -> _BrowserFallbackRuntime | None:
        if (
            not use_browser_fallback
            or not self._can_use_shared_browser_runtime()
            or self._uses_mock_transport()
        ):
            return None
        return await _BrowserFallbackRuntime.create(self.settings)

    async def _download_with_browser_fallback(
        self,
        article: ArticleReference,
        target_dir: Path,
        *,
        mode: str,
        browser_runtime: _BrowserFallbackRuntime | None,
        candidates: list[PDFCandidate] | None = None,
    ) -> PDFDownloadResult | None:
        if browser_runtime is not None:
            return await browser_runtime.download_article(self, article, target_dir, mode=mode, candidates=candidates)
        return self._browser_fallback_download_sync(article, target_dir, mode=mode, candidates=candidates)

    def _can_use_shared_browser_runtime(self) -> bool:
        return getattr(self._browser_fallback_download_sync, "__func__", None) is PDFService._browser_fallback_download_sync

    def _uses_mock_transport(self) -> bool:
        return isinstance(getattr(self.http_client, "_transport", None), httpx.MockTransport)

    async def _await_stage_with_heartbeat(
        self,
        awaitable: Awaitable[_T],
        *,
        article: ArticleReference,
        mode: str,
        stage: str,
        batch_id: str | None,
        article_index: int | None,
        article_total: int | None,
        extra_context: dict[str, Any] | None = None,
        heartbeat_seconds: float = 15.0,
    ) -> _T:
        should_trace = self.event_log_service is not None
        if not should_trace:
            return await awaitable

        started = time.monotonic()
        self._log_download_event(
            "info",
            "pdf_download_stage_start",
            f"Download stage {stage} started.",
            context=self._article_trace_context(
                article,
                batch_id=batch_id,
                mode=mode,
                article_index=article_index,
                article_total=article_total,
                stage=stage,
                extra=extra_context,
            ),
        )
        task = asyncio.create_task(awaitable)
        beats = 0
        try:
            while True:
                done, _pending = await asyncio.wait({task}, timeout=heartbeat_seconds)
                if task in done:
                    result = await task
                    self._log_download_event(
                        "info",
                        "pdf_download_stage_done",
                        f"Download stage {stage} finished.",
                        context=self._article_trace_context(
                            article,
                            batch_id=batch_id,
                            mode=mode,
                            article_index=article_index,
                            article_total=article_total,
                            stage=stage,
                            extra={
                                **(extra_context or {}),
                                "elapsed_ms": int((time.monotonic() - started) * 1000),
                            },
                        ),
                    )
                    return result
                beats += 1
                self._log_download_event(
                    "info",
                    "pdf_download_stage_wait",
                    f"Download stage {stage} still running.",
                    context=self._article_trace_context(
                        article,
                        batch_id=batch_id,
                        mode=mode,
                        article_index=article_index,
                        article_total=article_total,
                        stage=stage,
                        extra={
                            **(extra_context or {}),
                            "beat": beats,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                        },
                    ),
                )
        except Exception as exc:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self._log_download_event(
                "error",
                "pdf_download_stage_error",
                f"Download stage {stage} failed.",
                context=self._article_trace_context(
                    article,
                    batch_id=batch_id,
                    mode=mode,
                    article_index=article_index,
                    article_total=article_total,
                    stage=stage,
                    extra={
                        **(extra_context or {}),
                        "elapsed_ms": int((time.monotonic() - started) * 1000),
                        "err": f"{type(exc).__name__}: {exc}",
                    },
                ),
            )
            raise

    def _log_download_event(
        self,
        level: str,
        event: str,
        message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        if self.event_log_service is None:
            return
        self.event_log_service.log(level, event, message, context=context)

    @staticmethod
    def _new_batch_id() -> str:
        return uuid4().hex[:10]

    @staticmethod
    def _article_log_key(article: ArticleReference) -> str:
        return (
            article.pmid
            or article.pmc_id
            or article.doi
            or (article.title or "article")[:48]
        )

    def _article_trace_context(
        self,
        article: ArticleReference,
        *,
        batch_id: str | None,
        mode: str,
        article_index: int | None,
        article_total: int | None,
        stage: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "batch": batch_id or "-",
            "mode": mode,
            "article": self._article_log_key(article),
        }
        if article_index is not None and article_total is not None:
            context["idx"] = f"{article_index}/{article_total}"
        if stage:
            context["stage"] = stage
        if extra:
            context.update(extra)
        return context

    def _browser_fallback_download_sync(
        self,
        article: ArticleReference,
        target_dir: Path,
        *,
        mode: str = "balanced",
        candidates: list[PDFCandidate] | None = None,
    ) -> PDFDownloadResult | None:
        browser_targets = self._browser_target_pages(article, mode=mode, candidates=candidates)
        if not browser_targets:
            return None

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                accept_downloads=True,
                user_agent=self._download_headers()["User-Agent"],
                viewport={"width": 1440, "height": 1024},
            )
            try:
                for source_hint, article_url in browser_targets:
                    page = context.new_page()
                    probe_page = context.new_page()
                    try:
                        response = page.goto(article_url, wait_until="domcontentloaded", timeout=20_000)
                        direct_result = self._save_navigation_pdf_sync(
                            article,
                            target_dir,
                            source_hint,
                            page.url,
                            response,
                        )
                        if direct_result is not None:
                            return direct_result

                        page.wait_for_timeout(1_200)
                        raw_candidates = page.evaluate(
                            """
                            () => {
                              const seen = new Set();
                              const values = [];
                              const add = (value) => {
                                if (!value || seen.has(value)) return;
                                seen.add(value);
                                values.push(value);
                              };
                              const hrefNodes = Array.from(document.querySelectorAll('a[href], link[href]'));
                              for (const node of hrefNodes) {
                                const href = node.href || node.getAttribute('href') || '';
                                const text = (node.textContent || '').toLowerCase();
                                const lower = href.toLowerCase();
                                if (
                                  lower.includes('.pdf') ||
                                  lower.includes('/pdf') ||
                                  lower.includes('epdf') ||
                                  lower.includes('pdfdirect') ||
                                  lower.includes('downloadpdf') ||
                                  lower.includes('article-pdf') ||
                                  lower.includes('type=printable') ||
                                  text.includes('pdf')
                                ) {
                                  add(href);
                                }
                              }
                              const metaSelectors = [
                                "meta[name='citation_pdf_url']",
                                "meta[property='citation_pdf_url']",
                                "meta[name='wkhealth_pdf_url']",
                                "meta[name='citation_fulltext_html_url']",
                              ];
                              for (const selector of metaSelectors) {
                                const node = document.querySelector(selector);
                                if (node) add(node.getAttribute('content') || '');
                              }
                              const embeds = Array.from(document.querySelectorAll('iframe[src], embed[src], object[data]'));
                              for (const node of embeds) {
                                add(node.getAttribute('src') || node.getAttribute('data') || '');
                              }
                              return values.slice(0, 24);
                            }
                            """
                        )
                        pdf_links = self._expand_browser_pdf_candidates(raw_candidates, page.url, article)
                        for pdf_url in pdf_links:
                            result = self._download_candidate_url_sync(
                                article,
                                target_dir,
                                context,
                                probe_page,
                                source_hint,
                                article_url,
                                pdf_url,
                            )
                            if result is not None:
                                return result

                        result = self._click_pdf_actions_sync(
                            article,
                            target_dir,
                            page,
                            source_hint,
                        )
                        if result is not None:
                            return result
                    finally:
                        probe_page.close()
                        page.close()
            except Exception:
                return None
            finally:
                context.close()
                browser.close()

        return None

    def _download_candidate_url_sync(
        self,
        article: ArticleReference,
        target_dir: Path,
        context,  # noqa: ANN001
        probe_page,  # noqa: ANN001
        source_hint: str,
        referer: str,
        pdf_url: str,
    ) -> PDFDownloadResult | None:
        try:
            response = context.request.get(
                pdf_url,
                headers={"Referer": referer, "Accept": "application/pdf,*/*"},
                timeout=20_000,
            )
            content_type = (response.headers.get("content-type") or "").lower()
            content = response.body()
            if response.status == 200 and self._is_pdf_payload(content_type, content):
                return self._save_browser_pdf(article, target_dir, source_hint, pdf_url, content)
        except Exception:
            pass

        try:
            navigation = probe_page.goto(pdf_url, wait_until="domcontentloaded", timeout=20_000)
            direct_result = self._save_navigation_pdf_sync(
                article,
                target_dir,
                source_hint,
                probe_page.url,
                navigation,
            )
            if direct_result is not None:
                return direct_result
        except Exception:
            pass

        try:
            with probe_page.expect_download(timeout=10_000) as download_info:
                probe_page.goto(pdf_url, wait_until="domcontentloaded", timeout=20_000)
            download = download_info.value
            return self._save_download_file_sync(article, target_dir, source_hint, pdf_url, download)
        except Exception:
            return None

    def _click_pdf_actions_sync(
        self,
        article: ArticleReference,
        target_dir: Path,
        page,  # noqa: ANN001
        source_hint: str,
    ) -> PDFDownloadResult | None:
        selectors = [
            "a[href*='.pdf']",
            "a[href*='/pdf/']",
            "a[href*='epdf']",
            "a[href*='pdfdirect']",
            "a[href*='article-pdf']",
            "a[href*='downloadpdf']",
            "a:has-text('Download PDF')",
            "a:has-text('View PDF')",
            "a:has-text('PDF')",
            "button:has-text('Download PDF')",
            "button:has-text('PDF')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).first
                if locator.count() == 0:
                    continue
                with page.expect_download(timeout=10_000) as download_info:
                    locator.click(timeout=4_000)
                download = download_info.value
                return self._save_download_file_sync(article, target_dir, source_hint, page.url, download)
            except Exception:
                continue
        return None

    async def _crossref_pdf_links(self, doi: str) -> list[str]:
        result = await self._crossref_source_map(doi)
        return result["crossref"]

    async def _fast_pmc_doi_source_map(self, doi: str) -> dict[str, list[str]]:
        crossref_map = await self._crossref_source_map(doi)
        return {
            "unpaywall": [],
            "europe_pmc": [],
            "crossref": crossref_map["crossref"],
            "crossref_elsevier_xml": crossref_map["crossref_elsevier_xml"],
            "openalex": [],
            "citation_pdf_url": [],
            "doi_page": [],
            "doi_landing": [],
            "doi_guessed": [],
        }

    async def _crossref_source_map(self, doi: str) -> dict[str, list[str]]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.crossref_base_url}/works/{quote(doi, safe='')}",
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            message = response.json().get("message", {})
        except (httpx.HTTPError, ValueError):
            return {"crossref": [], "crossref_elsevier_xml": []}
        pdf_urls: list[str] = []
        elsevier_xml_urls: list[str] = []
        for item in message.get("link", []):
            url = item.get("URL")
            if not url:
                continue
            content_type = (item.get("content-type") or "").lower()
            host = urlparse(url).netloc.lower()
            if "pdf" in content_type or "pdf" in url.lower():
                pdf_urls.append(url)
            elif host == "api.elsevier.com" and "text/xml" in content_type:
                elsevier_xml_urls.append(url)
        return {"crossref": pdf_urls, "crossref_elsevier_xml": elsevier_xml_urls}

    async def _doi_source_map(self, doi: str, *, mode: str) -> dict[str, list[str]]:
        unpaywall_task = asyncio.create_task(self._unpaywall_pdf_links(doi)) if mode == "balanced" else None
        europe_pmc_task = (
            asyncio.create_task(self._europe_pmc_fulltext_links(doi=doi)) if mode == "balanced" else None
        )
        crossref_task = asyncio.create_task(self._crossref_source_map(doi))
        openalex_task = asyncio.create_task(self._openalex_source_map(doi))
        landing_task = asyncio.create_task(self._doi_landing_source_map(doi)) if mode == "balanced" else None
        if mode == "balanced":
            (
                unpaywall_links,
                europe_pmc_links,
                crossref_map,
                openalex_map,
                landing_map,
            ) = await asyncio.gather(
                unpaywall_task,
                europe_pmc_task,
                crossref_task,
                openalex_task,
                landing_task,
            )
        else:
            crossref_map, openalex_map = await asyncio.gather(crossref_task, openalex_task)
            unpaywall_links = []
            europe_pmc_links = []
            landing_map = {"citation_pdf_url": [], "doi_page": [], "doi_landing": [], "doi_guessed": []}

        return {
            "unpaywall": unpaywall_links,
            "europe_pmc": europe_pmc_links,
            "crossref": crossref_map["crossref"],
            "crossref_elsevier_xml": crossref_map["crossref_elsevier_xml"],
            "openalex": openalex_map["openalex"],
            "openalex_landing": openalex_map["openalex_landing"],
            "openalex_pmc_ids": openalex_map["openalex_pmc_ids"],
            "citation_pdf_url": landing_map["citation_pdf_url"],
            "doi_page": landing_map["doi_page"],
            "doi_landing": landing_map["doi_landing"],
            "doi_guessed": landing_map["doi_guessed"],
        }

    async def _landing_page_candidates_from_url(
        self,
        source: str,
        landing_url: str,
    ) -> list[PDFCandidate]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                landing_url,
                headers={"User-Agent": self.settings.request_user_agent, "Accept": "text/html,*/*"},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
        except Exception:
            return []

        base_url = str(response.url)
        html = response.text
        candidates: list[PDFCandidate] = []
        for url in self._extract_meta_pdf_urls_from_html(html, base_url):
            candidates.append(PDFCandidate(source=f"{source}_citation_pdf_url", url=url))
        meta_set = {candidate.url for candidate in candidates}
        for url in self._extract_pdf_urls_from_html(html, base_url, include_meta=False):
            if url in meta_set:
                continue
            candidates.append(PDFCandidate(source=f"{source}_page_pdf", url=url))
        if self._looks_like_fulltext(html):
            candidates.append(PDFCandidate(source=f"{source}_html_fulltext", url=base_url))
        return candidates

    async def _doaj_candidates(self, doi: str) -> list[PDFCandidate]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{DOAJ_SEARCH_URL}/{quote(f'doi:{doi}', safe='')}",
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        results = payload.get("results", []) if isinstance(payload, dict) else []
        candidates: list[PDFCandidate] = []
        for result in results:
            bibjson = result.get("bibjson", {}) if isinstance(result, dict) else {}
            for item in bibjson.get("link", []) if isinstance(bibjson, dict) else []:
                url = item.get("url")
                if not url:
                    continue
                link_type = str(item.get("type") or "").lower()
                lower = url.lower()
                if ".pdf" in lower or "/pdf" in lower:
                    candidates.append(PDFCandidate(source="doaj_pdf", url=url))
                    continue
                if "fulltext" in link_type or "html" in link_type or "/doi/" in lower:
                    candidates.extend(await self._landing_page_candidates_from_url("doaj", url))
        return candidates

    async def _ncbi_linkout_candidates(self, pmid: str) -> list[PDFCandidate]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.ncbi_base_url}/elink.fcgi",
                params={
                    "dbfrom": "pubmed",
                    "id": pmid,
                    "cmd": "prlinks",
                    "retmode": "json",
                },
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        candidates: list[PDFCandidate] = []
        linksets = payload.get("linksets", []) if isinstance(payload, dict) else []
        for linkset in linksets:
            for idurllist in linkset.get("idurllist", []) if isinstance(linkset, dict) else []:
                for objurl in idurllist.get("objurls", []) if isinstance(idurllist, dict) else []:
                    url_value = ((objurl.get("url") or {}).get("value") or "").strip()
                    if not url_value:
                        continue
                    categories = [str(item).lower() for item in objurl.get("categories") or []]
                    if "full text sources" not in categories:
                        continue
                    lower = url_value.lower()
                    if ".pdf" in lower or "/pdf" in lower:
                        candidates.append(PDFCandidate(source="ncbi_linkout", url=url_value))
                        continue
                    candidates.extend(await self._landing_page_candidates_from_url("ncbi_linkout", url_value))
        return candidates

    async def _europe_pmc_repo_candidates(self, pmc_id: str) -> list[PDFCandidate]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                EUROPE_PMC_REPO_URL,
                params={"pmcId": pmc_id, "type": "METADATA"},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        version = int(float(payload.get("version") or 1))
        candidates: list[PDFCandidate] = []
        for file_item in payload.get("files") or []:
            filename = str(file_item.get("filename") or "")
            mime_type = str(file_item.get("mimeType") or "")
            file_type = str(file_item.get("type") or "").lower()
            if not filename or not mime_type:
                continue
            url = (
                f"{EUROPE_PMC_REPO_URL}?pmcId={pmc_id}&type=FILE"
                f"&fileName={quote(filename, safe='')}"
                f"&mimeType={quote(mime_type, safe='')}"
                f"&version={version}&pmc_pageType=pdf&pmc_domain=null"
            )
            if file_type == "pdf" or "pdf" in mime_type.lower():
                candidates.append(PDFCandidate(source="europe_pmc_repo_pdf", url=url))
            elif "xml" in mime_type.lower():
                candidates.append(PDFCandidate(source="europe_pmc_repo_xml", url=url))
        return candidates

    async def _doi_landing_source_map(self, doi: str) -> dict[str, list[str]]:
        landing_page = await self._fetch_doi_landing_page(doi)
        if landing_page is None:
            return {"citation_pdf_url": [], "doi_page": [], "doi_landing": [], "doi_guessed": []}

        html, base_url = landing_page
        citation_urls = self._extract_meta_pdf_urls_from_html(html, base_url)
        doi_page_urls = self._extract_pdf_urls_from_html(html, base_url, include_meta=False)
        if citation_urls:
            citation_set = set(citation_urls)
            doi_page_urls = [url for url in doi_page_urls if url not in citation_set]

        landing_urls = [base_url] if self._looks_like_fulltext(html) else []
        guessed_urls = self._expand_http_pdf_candidates(base_url, doi)
        return {
            "citation_pdf_url": citation_urls,
            "doi_page": doi_page_urls,
            "doi_landing": landing_urls,
            "doi_guessed": guessed_urls,
        }

    async def _pmc_oa_links(self, pmc_id: str) -> list[str]:
        root: ET.Element | None = None
        for attempt in range(2):
            try:
                await self.resolve_rate_limiter.wait()
                response = await self.http_client.get(
                    self.settings.pmc_oa_base_url,
                    params={"id": pmc_id},
                    headers={"User-Agent": self.settings.request_user_agent},
                    follow_redirects=True,
                    timeout=self._resolve_timeout(),
                )
                response.raise_for_status()
                root = ET.fromstring(response.text)
                break
            except (httpx.HTTPError, ET.ParseError, ValueError):
                if attempt == 1:
                    return []
                await asyncio.sleep(0.2)
        if root is None:
            return []

        urls: list[str] = []
        for link in root.findall(".//record/link"):
            href = link.attrib.get("href")
            if not href:
                continue
            if href.startswith("ftp://"):
                href = "https://" + href[len("ftp://") :]
            urls.append(href)
        return urls

    @staticmethod
    def _extract_pmc_id_from_url(url: str | None) -> str | None:
        if not url:
            return None
        match = re.search(r"/articles/(?:PMC)?(\d+)", url, re.IGNORECASE)
        if match is None:
            return None
        return f"PMC{match.group(1)}"

    async def _openalex_source_map(self, doi: str) -> dict[str, list[str]]:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.openalex_base_url}/works",
                params={
                    "filter": f"doi:https://doi.org/{doi}",
                    "select": "best_oa_location,primary_location,locations",
                },
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError):
            return {"openalex": [], "openalex_landing": [], "openalex_pmc_ids": []}

        if not results:
            return {"openalex": [], "openalex_landing": [], "openalex_pmc_ids": []}

        payload = results[0]
        pdf_urls: list[str] = []
        landing_urls: list[str] = []
        pmc_ids: list[str] = []
        seen_pdf: set[str] = set()
        seen_landing: set[str] = set()
        seen_pmc: set[str] = set()

        locations: list[dict[str, Any]] = []
        for field in ("best_oa_location", "primary_location"):
            location = payload.get(field)
            if isinstance(location, dict):
                locations.append(location)
        for location in payload.get("locations", []):
            if isinstance(location, dict):
                locations.append(location)

        for location in locations:
            pdf_url = self._normalize_candidate_url(location.get("pdf_url"))
            landing_url = self._normalize_candidate_url(location.get("landing_page_url"))
            if pdf_url and pdf_url not in seen_pdf:
                seen_pdf.add(pdf_url)
                pdf_urls.append(pdf_url)
            if landing_url and "doi.org/" not in landing_url.lower() and landing_url not in seen_landing:
                seen_landing.add(landing_url)
                landing_urls.append(landing_url)
            for candidate_url in (pdf_url, landing_url):
                pmc_id = self._extract_pmc_id_from_url(candidate_url)
                if pmc_id and pmc_id not in seen_pmc:
                    seen_pmc.add(pmc_id)
                    pmc_ids.append(pmc_id)

        return {
            "openalex": pdf_urls,
            "openalex_landing": landing_urls,
            "openalex_pmc_ids": pmc_ids,
        }

    async def _unpaywall_pdf_links(self, doi: str) -> list[str]:
        if not self.settings.unpaywall_email:
            return []

        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.unpaywall_base_url}/{quote(doi, safe='')}",
                params={"email": self.settings.unpaywall_email},
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            if response.status_code == 404:
                return []
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []

        locations: list[dict] = []
        best = payload.get("best_oa_location")
        if isinstance(best, dict):
            locations.append(best)
        for location in payload.get("oa_locations", []):
            if isinstance(location, dict):
                locations.append(location)

        urls: list[str] = []
        seen: set[str] = set()
        for location in locations:
            for key in ("url_for_pdf", "url"):
                url = location.get(key)
                if not url or url in seen:
                    continue
                seen.add(url)
                urls.append(url)
        return urls

    async def _europe_pmc_fulltext_links(
        self,
        *,
        doi: str | None = None,
        pmc_id: str | None = None,
    ) -> list[str]:
        query_parts: list[str] = []
        if pmc_id:
            query_parts.append(f"PMCID:{pmc_id}")
        if doi:
            query_parts.append(f'DOI:"{doi}"')
        if not query_parts:
            return []

        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.europe_pmc_base_url}/search",
                params={
                    "query": " OR ".join(query_parts),
                    "format": "json",
                    "pageSize": "1",
                    "resultType": "core",
                },
                headers={"User-Agent": self.settings.request_user_agent},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return []

        result_list = payload.get("resultList", {}) if isinstance(payload, dict) else {}
        results = result_list.get("result", []) if isinstance(result_list, dict) else []
        if not results:
            return []

        record = results[0] if isinstance(results[0], dict) else {}
        fulltext_block = record.get("fullTextUrlList", {}) if isinstance(record, dict) else {}
        fulltext_urls = fulltext_block.get("fullTextUrl", []) if isinstance(fulltext_block, dict) else []

        urls: list[str] = []
        seen: set[str] = set()
        for item in fulltext_urls:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            document_style = str(item.get("documentStyle", "")).lower()
            site = str(item.get("site", "")).lower()
            if not url or url in seen:
                continue
            if "pdf" in document_style or url.lower().endswith(".pdf") or "pdf" in url.lower():
                seen.add(url)
                urls.append(url)
                continue
            if document_style in {"html", "fulltext-html", "xml", "fulltext-xml"} or any(
                token in url.lower() for token in ("fulltext", "/article/", "xml", "html")
            ):
                seen.add(url)
                urls.append(url)
                continue
            if "europe pmc" in site and pmc_id:
                render_url = f"https://europepmc.org/articles/{pmc_id}?pdf=render"
                if render_url not in seen:
                    seen.add(render_url)
                    urls.append(render_url)

        if pmc_id:
            render_url = f"https://europepmc.org/articles/{pmc_id}?pdf=render"
            if render_url not in seen:
                urls.append(render_url)
        return urls

    async def _citation_pdf_links(self, doi: str) -> list[str]:
        landing_page = await self._fetch_doi_landing_page(doi)
        if landing_page is None:
            return []
        html, base_url = landing_page
        return self._extract_pdf_urls_from_html(html, base_url, include_meta=True)

    async def _doi_page_pdf_links(self, doi: str) -> list[str]:
        landing_page = await self._fetch_doi_landing_page(doi)
        if landing_page is None:
            return []
        html, base_url = landing_page
        return self._extract_pdf_urls_from_html(html, base_url, include_meta=False)

    async def _fetch_doi_landing_page(self, doi: str) -> tuple[str, str] | None:
        try:
            await self.resolve_rate_limiter.wait()
            response = await self.http_client.get(
                f"{self.settings.doi_resolver_base_url}/{quote(doi, safe='')}",
                headers={"User-Agent": self.settings.request_user_agent, "Accept": "text/html,*/*"},
                follow_redirects=True,
                timeout=self._resolve_timeout(),
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200 or "html" not in response.headers.get("content-type", "").lower():
            return None

        return response.text, str(response.url)

    async def _probe_candidates(
        self,
        candidates: list[PDFCandidate],
        *,
        mode: str,
        stop_on_first_success: bool,
        article: ArticleReference | None = None,
        batch_id: str | None = None,
        article_index: int | None = None,
        article_total: int | None = None,
    ) -> tuple[_ProbeOutcome | None, list[_ProbeOutcome]]:
        if not candidates:
            return None, []

        semaphore = asyncio.Semaphore(self._candidate_concurrency(mode))
        tasks = [
            asyncio.create_task(
                self._bounded_probe_candidate(
                    candidate,
                    semaphore,
                    mode=mode,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                )
            )
            for candidate in candidates
        ]
        outcomes: list[_ProbeOutcome] = []
        success_outcome: _ProbeOutcome | None = None
        try:
            for completed in asyncio.as_completed(tasks):
                outcome = await completed
                outcomes.append(outcome)
                if stop_on_first_success and outcome.success:
                    success_outcome = outcome
                    break
        finally:
            if stop_on_first_success and success_outcome is not None:
                for task in tasks:
                    if not task.done():
                        task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        if success_outcome is None:
            success_outcome = next((outcome for outcome in outcomes if outcome.success), None)
        return success_outcome, outcomes

    async def _probe_fast_candidates_in_order(
        self,
        candidates: list[PDFCandidate],
        *,
        article: ArticleReference,
        batch_id: str | None,
        article_index: int | None,
        article_total: int | None,
    ) -> tuple[_ProbeOutcome | None, list[_ProbeOutcome]]:
        if not candidates:
            return None, []

        attempts: list[_ProbeOutcome] = []
        checked_urls: set[str] = set()
        first_wave = candidates[:2]
        if first_wave:
            success_outcome, outcomes = await self._await_stage_with_heartbeat(
                self._probe_candidates(
                    first_wave,
                    mode="fast",
                    stop_on_first_success=True,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                ),
                article=article,
                mode="fast",
                stage="probe",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"cand": len(first_wave)},
            )
            attempts.extend(outcomes)
            checked_urls.update(candidate.url for candidate in first_wave)
            if success_outcome is not None:
                return success_outcome, attempts

        for candidate in candidates:
            if candidate.url in checked_urls:
                continue
            success_outcome, outcomes = await self._await_stage_with_heartbeat(
                self._probe_candidates(
                    [candidate],
                    mode="fast",
                    stop_on_first_success=True,
                    article=article,
                    batch_id=batch_id,
                    article_index=article_index,
                    article_total=article_total,
                ),
                article=article,
                mode="fast",
                stage="probe",
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
                extra_context={"cand": 1, "source": candidate.source},
            )
            attempts.extend(outcomes)
            checked_urls.add(candidate.url)
            if success_outcome is not None:
                return success_outcome, attempts

        return None, attempts

    async def _bounded_probe_candidate(
        self,
        candidate: PDFCandidate,
        semaphore: asyncio.Semaphore,
        *,
        mode: str,
        article: ArticleReference | None,
        batch_id: str | None,
        article_index: int | None,
        article_total: int | None,
    ) -> _ProbeOutcome:
        async with semaphore:
            return await self._probe_candidate(
                candidate,
                mode=mode,
                article=article,
                batch_id=batch_id,
                article_index=article_index,
                article_total=article_total,
            )

    async def _probe_candidate(
        self,
        candidate: PDFCandidate,
        *,
        mode: str,
        article: ArticleReference | None,
        batch_id: str | None,
        article_index: int | None,
        article_total: int | None,
    ) -> _ProbeOutcome:
        started = time.monotonic()
        if article is not None:
            self._log_download_event(
                "info",
                "pdf_download_candidate_start",
                "Download candidate probe started.",
                context=self._article_trace_context(
                    article,
                    batch_id=batch_id,
                    mode=mode,
                    article_index=article_index,
                    article_total=article_total,
                    stage="candidate",
                    extra={"source": candidate.source},
                ),
            )
        try:
            if self._probe_uses_full_body(candidate.source):
                outcome = await self._download_candidate_payload(
                    candidate,
                    mode=mode,
                    timeout=self._probe_timeout_seconds(mode, candidate.source),
                )
            else:
                outcome = await self._probe_candidate_preview(candidate, mode=mode)
            if article is not None:
                self._log_download_event(
                    "info",
                    "pdf_download_candidate_done",
                    "Download candidate probe finished.",
                    context=self._article_trace_context(
                        article,
                        batch_id=batch_id,
                        mode=mode,
                        article_index=article_index,
                        article_total=article_total,
                        stage="candidate",
                        extra={
                            "source": candidate.source,
                            "ok": outcome.success,
                            "code": outcome.status_code,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                        },
                    ),
                )
            return outcome
        except Exception as exc:
            outcome = _ProbeOutcome(
                candidate=candidate,
                error=f"{type(exc).__name__}: {exc}",
            )
            if article is not None:
                self._log_download_event(
                    "warning",
                    "pdf_download_candidate_done",
                    "Download candidate probe failed.",
                    context=self._article_trace_context(
                        article,
                        batch_id=batch_id,
                        mode=mode,
                        article_index=article_index,
                        article_total=article_total,
                        stage="candidate",
                        extra={
                            "source": candidate.source,
                            "ok": False,
                            "elapsed_ms": int((time.monotonic() - started) * 1000),
                            "err": f"{type(exc).__name__}: {exc}",
                        },
                    ),
                )
            return outcome

    @classmethod
    def _probe_uses_full_body(cls, source: str) -> bool:
        return (
            source == "crossref_elsevier_xml"
            or source == "europe_pmc_repo_xml"
            or source.endswith("_html_fulltext")
            or source.endswith("_xml_fulltext")
        )

    @staticmethod
    def _response_looks_textual(content_type: str, preview_bytes: bytes) -> bool:
        lowered = preview_bytes[:512].lower()
        return (
            "html" in content_type
            or "xml" in content_type
            or "text/plain" in content_type
            or b"<html" in lowered
            or b"<?xml" in lowered
        )

    @staticmethod
    def _is_tls_cert_error(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        return "certificate verify failed" in text or "certificate_verify_failed" in text

    async def _probe_candidate_preview(
        self,
        candidate: PDFCandidate,
        *,
        mode: str,
        allow_insecure: bool = False,
    ) -> _ProbeOutcome:
        headers = self._candidate_request_headers(candidate.source)
        headers["Range"] = self._quick_probe_range_header(candidate.source)
        timeout = self._probe_timeout_seconds(mode, candidate.source)
        insecure_client: httpx.AsyncClient | None = None
        try:
            client = self.http_client
            if allow_insecure:
                insecure_client = httpx.AsyncClient(
                    verify=False,
                    follow_redirects=True,
                    headers={"User-Agent": self.settings.request_user_agent},
                    timeout=timeout,
                )
                client = insecure_client
            async with client.stream(
                "GET",
                candidate.url,
                headers=headers,
                follow_redirects=True,
                timeout=timeout,
            ) as response:
                content_type = response.headers.get("content-type", "").lower() or None
                preview = bytearray()
                limit = (
                    self._quick_tgz_probe_max_bytes()
                    if candidate.source == "pmc_oa_tgz"
                    else self._quick_probe_read_limit(candidate.source, content_type or "")
                )
                stream = response.aiter_bytes()
                async for chunk in stream:
                    if not chunk:
                        continue
                    remaining = limit - len(preview)
                    if remaining <= 0:
                        break
                    preview.extend(chunk[:remaining])
                    if len(preview) >= limit:
                        break
                preview_bytes = bytes(preview)
                if response.status_code in {200, 206} and (
                    candidate.source == "pmc_oa_tgz"
                    or "gzip" in (content_type or "")
                    or "x-gzip" in (content_type or "")
                ):
                    return _ProbeOutcome(
                        candidate=candidate,
                        status_code=response.status_code,
                        content_type=content_type,
                        mode="tgz_preview",
                        payload_bytes=None,
                        content_kind="pdf" if self._tgz_payload_has_pdf_entry(preview_bytes) else None,
                        extension=".pdf" if self._tgz_payload_has_pdf_entry(preview_bytes) else None,
                    )
                if self._response_looks_textual(content_type or "", preview_bytes):
                    async for chunk in stream:
                        if not chunk:
                            continue
                        preview.extend(chunk)
                    full_bytes = bytes(preview)
                    payload_bytes, payload_mode, content_kind, extension = await asyncio.to_thread(
                        self._extract_download_payload,
                        candidate.url,
                        content_type or "",
                        full_bytes,
                    )
                    if response.status_code not in {200, 206}:
                        payload_bytes = None
                        content_kind = None
                        extension = None
                    return _ProbeOutcome(
                        candidate=candidate,
                        status_code=response.status_code,
                        content_type=content_type,
                        mode=payload_mode,
                        payload_bytes=payload_bytes,
                        content_kind=content_kind,
                        extension=extension,
                    )
                payload_mode = "preview"
                content_kind: str | None = None
                extension: str | None = None
                if response.status_code in {200, 206} and self._is_pdf_payload(content_type or "", preview_bytes):
                    payload_mode = "pdf_preview"
                    content_kind = "pdf"
                    extension = ".pdf"
                return _ProbeOutcome(
                    candidate=candidate,
                    status_code=response.status_code,
                    content_type=content_type,
                    mode=payload_mode,
                    payload_bytes=None,
                    content_kind=content_kind,
                    extension=extension,
                )
        except Exception as exc:
            if not allow_insecure and self._is_tls_cert_error(exc):
                return await self._probe_candidate_preview(candidate, mode=mode, allow_insecure=True)
            raise
        finally:
            if insecure_client is not None:
                await insecure_client.aclose()

    async def _download_candidate_payload(
        self,
        candidate: PDFCandidate,
        *,
        mode: str,
        timeout: float | None = None,
        allow_insecure: bool = False,
    ) -> _ProbeOutcome:
        insecure_client: httpx.AsyncClient | None = None
        try:
            client = self.http_client
            request_timeout = timeout or self._download_timeout_seconds(mode, candidate.source)
            if allow_insecure:
                insecure_client = httpx.AsyncClient(
                    verify=False,
                    follow_redirects=True,
                    headers={"User-Agent": self.settings.request_user_agent},
                    timeout=request_timeout,
                )
                client = insecure_client
            response = await client.get(
                candidate.url,
                headers=self._candidate_request_headers(candidate.source),
                follow_redirects=True,
                timeout=request_timeout,
            )
            content_type = response.headers.get("content-type", "").lower() or None
            payload_bytes, payload_mode, content_kind, extension = await asyncio.to_thread(
                self._extract_download_payload,
                candidate.url,
                content_type or "",
                response.content,
            )
            if response.status_code not in {200, 206}:
                payload_bytes = None
                content_kind = None
                extension = None
            return _ProbeOutcome(
                candidate=candidate,
                status_code=response.status_code,
                content_type=content_type,
                mode=payload_mode,
                payload_bytes=payload_bytes,
                content_kind=content_kind,
                extension=extension,
            )
        except Exception as exc:
            if not allow_insecure and self._is_tls_cert_error(exc):
                return await self._download_candidate_payload(candidate, mode=mode, timeout=timeout, allow_insecure=True)
            raise
        finally:
            if insecure_client is not None:
                await insecure_client.aclose()

    def _resolve_target_dir(self, download_dir: str | None) -> Path:
        if download_dir:
            return Path(download_dir).expanduser().resolve()
        return self.settings.download_root.expanduser().resolve()

    def _build_file_path(
        self,
        article: ArticleReference,
        source: str,
        target_dir: Path,
        *,
        suffix: str = ".pdf",
    ) -> Path:
        year_part = article.year or "unknown_year"
        year_dir = target_dir / f"year_{year_part}"
        year_dir.mkdir(parents=True, exist_ok=True)
        title = article.title or article.pmid or article.doi or article.pmc_id or "article"
        stem = sanitize_filename(title)
        file_path = ensure_unique_path(year_dir / f"{stem}_{source}{suffix}")
        return file_path

    def _browser_target_pages(
        self,
        article: ArticleReference,
        *,
        mode: str = "balanced",
        candidates: list[PDFCandidate] | None = None,
    ) -> list[tuple[str, str]]:
        targets: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(source: str, url: str | None) -> None:
            normalized = self._normalize_candidate_url(url)
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            targets.append((source, normalized))

        if mode == "balanced" and article.pmc_id:
            add("browser_pmc", f"https://pmc.ncbi.nlm.nih.gov/articles/{article.pmc_id}/")

        for source, url in self._browser_candidate_targets(candidates or []):
            add(source, url)

        return targets

    @classmethod
    def _should_use_browser_fallback(
        cls,
        candidates: list[PDFCandidate],
        probe_attempts: list[_ProbeOutcome],
        *,
        mode: str,
    ) -> bool:
        if not cls._browser_candidate_targets(candidates):
            return False
        if mode != "fast":
            return True
        for attempt in probe_attempts:
            error = (attempt.error or "").lower()
            if "cloudflare_challenge" in error or "403" in error:
                return True
            if attempt.status_code in {401, 403}:
                return True
        return False

    @staticmethod
    def _browser_candidate_targets(candidates: list[PDFCandidate]) -> list[tuple[str, str]]:
        preferred_sources = {
            "article_oa_pdf",
            "article_landing",
            "crossref",
            "openalex",
            "openalex_landing",
            "openalex_pmc_article",
            "citation_pdf_url",
            "doaj_pdf",
            "ncbi_linkout",
            "doi_page",
            "doi_landing",
        }
        direct_targets: list[tuple[str, str]] = []
        fallback_targets: list[tuple[str, str]] = []
        seen: set[str] = set()
        for candidate in candidates:
            source = candidate.source
            if not (
                source in preferred_sources
                or source.endswith("_citation_pdf_url")
                or source.endswith("_page_pdf")
                or source.endswith("_html_fulltext")
            ):
                continue
            url = candidate.url
            lower = url.lower()
            if "api.openalex.org/" in lower or "api.crossref.org/" in lower or "doaj.org/api/" in lower:
                continue
            if "jstor.org/institutionsearch" in lower:
                continue
            if url in seen:
                continue
            seen.add(url)
            target = (source, url)
            if ".pdf" in lower or "/pdf" in lower or "pdfdirect" in lower or "viewfile" in lower:
                direct_targets.append(target)
            else:
                fallback_targets.append(target)

        targets = direct_targets[:3]
        if not targets:
            targets = fallback_targets[:2]
        return targets

    def _save_browser_pdf(
        self,
        article: ArticleReference,
        target_dir: Path,
        source: str,
        url: str,
        content: bytes,
    ) -> PDFDownloadResult:
        file_path = self._build_file_path(article, source, target_dir)
        file_path.write_bytes(content)
        return PDFDownloadResult(
            article=article,
            success=True,
            source=source,
            url=url,
            file_path=str(file_path),
            content_kind="pdf",
            content_type="application/pdf",
        )

    def _save_navigation_pdf_sync(
        self,
        article: ArticleReference,
        target_dir: Path,
        source_hint: str,
        url: str,
        response,  # noqa: ANN001
    ) -> PDFDownloadResult | None:
        if response is None:
            return None
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            if "pdf" not in content_type and "octet-stream" not in content_type:
                return None
            content = response.body()
        except Exception:
            return None
        if not self._is_pdf_payload(content_type, content):
            return None
        return self._save_browser_pdf(article, target_dir, source_hint, url, content)

    def _save_download_file_sync(
        self,
        article: ArticleReference,
        target_dir: Path,
        source_hint: str,
        url: str,
        download,  # noqa: ANN001
    ) -> PDFDownloadResult | None:
        file_path = self._build_file_path(article, source_hint, target_dir)
        download.save_as(str(file_path))
        file_bytes = file_path.read_bytes()
        if file_bytes.startswith(b"%PDF"):
            return PDFDownloadResult(
                article=article,
                success=True,
                source=source_hint,
                url=url,
                file_path=str(file_path),
            )
        file_path.unlink(missing_ok=True)
        return None

    @staticmethod
    def _download_headers() -> dict[str, str]:
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/pdf,*/*",
        }

    @classmethod
    def _candidate_request_headers(cls, source: str) -> dict[str, str]:
        headers = cls._download_headers()
        if source == "crossref_elsevier_xml" or source.endswith("_xml_fulltext") or source == "europe_pmc_repo_xml":
            headers["Accept"] = "application/xml,text/xml,*/*"
        elif source.endswith("_html_fulltext"):
            headers["Accept"] = "text/html,*/*"
        return headers

    @staticmethod
    def _is_pdf_payload(content_type: str, content: bytes) -> bool:
        if "pdf" in content_type or "octet-stream" in content_type:
            return content.startswith(b"%PDF")
        return content.startswith(b"%PDF")

    @classmethod
    def _extract_download_payload(
        cls,
        url: str,
        content_type: str,
        content: bytes,
    ) -> tuple[bytes | None, str, str | None, str | None]:
        if cls._is_pdf_payload(content_type, content):
            return content, "pdf", "pdf", ".pdf"

        if url.endswith(".tar.gz") or "gzip" in content_type or "x-gzip" in content_type:
            pdf_bytes = cls._extract_pdf_from_tgz(content)
            if pdf_bytes is not None:
                return pdf_bytes, "tgz_with_pdf", "pdf", ".pdf"

        if cls._is_fulltext_xml(content_type, content):
            return content, "xml_fulltext", "xml_fulltext", ".xml"

        if cls._is_fulltext_html(content_type, content):
            return content, "html_fulltext", "html_fulltext", ".html"

        if cls._is_plaintext_fulltext(content_type, content):
            return content, "text_fulltext", "text_fulltext", ".txt"

        return None, "not_fulltext", None, None

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
            pdf_bytes = extracted.read()
            if pdf_bytes.startswith(b"%PDF"):
                return pdf_bytes
        return None

    @staticmethod
    def _tgz_payload_has_pdf_entry(content: bytes) -> bool:
        try:
            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            preview = decompressor.decompress(content, 4 * 1024 * 1024)
        except zlib.error:
            return False

        offset = 0
        while offset + 512 <= len(preview):
            header = preview[offset:offset + 512]
            if header == b"\0" * 512:
                break
            name = header[:100].split(b"\0", 1)[0].decode("utf-8", errors="ignore").lower()
            size_raw = header[124:136].split(b"\0", 1)[0].strip() or b"0"
            try:
                size = int(size_raw, 8)
            except ValueError:
                break
            if name.endswith(".pdf"):
                return True
            offset += 512 + ((size + 511) // 512) * 512
        return False

    @staticmethod
    def _decode_text(content: bytes) -> str:
        return content.decode("utf-8", errors="ignore")

    @classmethod
    def _is_fulltext_html(cls, content_type: str, content: bytes) -> bool:
        if "html" not in content_type and b"<html" not in content[:500].lower():
            return False
        text = cls._decode_text(content)
        return cls._looks_like_fulltext(text)

    @classmethod
    def _is_fulltext_xml(cls, content_type: str, content: bytes) -> bool:
        lowered = content[:500].lower()
        if "xml" not in content_type and b"<?xml" not in lowered:
            return False
        text = cls._decode_text(content)
        return cls._looks_like_fulltext(text)

    @classmethod
    def _is_plaintext_fulltext(cls, content_type: str, content: bytes) -> bool:
        if "text/plain" not in content_type:
            return False
        return cls._looks_like_fulltext(cls._decode_text(content))

    @staticmethod
    def _looks_like_fulltext(text: str) -> bool:
        if PDFService._looks_like_elsevier_fulltext(text):
            return True
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"&[A-Za-z#0-9]+;", " ", cleaned)
        cleaned = re.sub(r"\\s+", " ", cleaned).strip()
        if len(cleaned) < 4000:
            return False
        word_count = len(cleaned.split())
        if word_count < 700:
            return False
        heading_hits = sum(
            1
            for token in ("introduction", "methods", "results", "discussion", "conclusion", "references")
            if token in cleaned.lower()
        )
        return heading_hits >= 2

    @staticmethod
    def _looks_like_elsevier_fulltext(text: str) -> bool:
        lowered = text.lower()
        if "sciencedirect" not in lowered and "elsevier" not in lowered:
            return False
        if "article preview" in lowered or "purchase pdf" in lowered:
            return False
        positive_hits = sum(
            token in lowered
            for token in (
                "open archive",
                "main text",
                "introduction",
                "results",
                "discussion",
                "references",
            )
        )
        if positive_hits < 3:
            return False
        cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\\1>", " ", text)
        cleaned = re.sub(r"(?s)<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"&[A-Za-z#0-9]+;", " ", cleaned)
        cleaned = re.sub(r"\\s+", " ", cleaned).strip()
        return len(cleaned) >= 2500 and len(cleaned.split()) >= 400

    @staticmethod
    def _extract_pdf_urls_from_html(
        html: str,
        base_url: str,
        *,
        include_meta: bool,
    ) -> list[str]:
        candidates: list[str] = []

        if include_meta:
            meta_patterns = [
                r'citation_pdf_url[^>]+content=["\']([^"\']+)',
                r'content=["\']([^"\']+type=printable[^"\']*)',
            ]
            for pattern in meta_patterns:
                for match in re.finditer(pattern, html, re.IGNORECASE):
                    candidates.append(urljoin(base_url, match.group(1)))

        for match in re.finditer(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            href = match.group(1)
            href_lower = href.lower()
            if (
                ".pdf" not in href_lower
                and "/pdf" not in href_lower
                and "type=printable" not in href_lower
                and "/download/file/" not in href_lower
            ):
                continue
            candidates.append(urljoin(base_url, href))

        unique: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    @staticmethod
    def _extract_meta_pdf_urls_from_html(html: str, base_url: str) -> list[str]:
        candidates: list[str] = []
        meta_patterns = [
            r'citation_pdf_url[^>]+content=["\']([^"\']+)',
            r'content=["\']([^"\']+type=printable[^"\']*)',
        ]
        for pattern in meta_patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                candidates.append(urljoin(base_url, match.group(1)))

        unique: list[str] = []
        seen: set[str] = set()
        for url in candidates:
            if url in seen:
                continue
            seen.add(url)
            unique.append(url)
        return unique

    @staticmethod
    def _expand_http_pdf_candidates(page_url: str, doi: str) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()

        def add(url: str | None) -> None:
            if not url:
                return
            absolute = urljoin(page_url, url)
            if absolute in seen:
                return
            seen.add(absolute)
            unique.append(absolute)

        parsed = urlparse(page_url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else page_url
        host = parsed.netloc.lower()

        if "wiley.com" in host:
            add(f"{base}/doi/pdfdirect/{doi}")
            add(f"{base}/doi/pdf/{doi}")
            add(f"{base}/doi/epdf/{doi}")
        if "pubs.acs.org" in host:
            add(f"{base}/doi/pdf/{doi}")
            add(f"{base}/doi/pdfplus/{doi}")
        if "academic.oup.com" in host:
            add(f"{base}/journals/downloadpdf/{doi}")
        if "journals.lww.com" in host:
            add(f"{base}/_layouts/15/oaks.journals/downloadpdf.aspx")

        pii_match = re.search(r"/pii/([^/?#]+)", page_url, re.IGNORECASE)
        if pii_match is not None:
            pii = pii_match.group(1)
            add(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true")
            add(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf")

        return unique

    @classmethod
    def _expand_browser_pdf_candidates(
        cls,
        candidate_urls: list[str],
        page_url: str,
        article: ArticleReference,
    ) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()

        def add(url: str | None) -> None:
            if not url:
                return
            absolute = urljoin(page_url, url)
            if absolute in seen:
                return
            seen.add(absolute)
            unique.append(absolute)

        for candidate in candidate_urls:
            add(candidate)

        parsed = urlparse(page_url)
        base = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else page_url
        host = parsed.netloc.lower()
        doi = article.doi or ""

        for candidate in list(unique):
            lower = candidate.lower()
            if "/doi/epdf/" in lower:
                add(re.sub(r"/doi/epdf/", "/doi/pdfdirect/", candidate, flags=re.IGNORECASE))
                add(re.sub(r"/doi/epdf/", "/doi/pdf/", candidate, flags=re.IGNORECASE))
            if "/doi/pdfdirect/" in lower:
                add(re.sub(r"/doi/pdfdirect/", "/doi/pdf/", candidate, flags=re.IGNORECASE))

        if doi:
            if "wiley.com" in host:
                add(f"{base}/doi/pdfdirect/{doi}")
                add(f"{base}/doi/pdf/{doi}")
                add(f"{base}/doi/epdf/{doi}")
            if "pubs.acs.org" in host:
                add(f"{base}/doi/pdf/{doi}")
                add(f"{base}/doi/pdfplus/{doi}")
            if "academic.oup.com" in host:
                add(f"{base}/journals/downloadpdf/{doi}")
            if "journals.lww.com" in host:
                add(f"{base}/_layouts/15/oaks.journals/downloadpdf.aspx")

        pii_match = re.search(r"/pii/([^/?#]+)", page_url, re.IGNORECASE)
        if pii_match is not None:
            pii = pii_match.group(1)
            add(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true")
            add(f"https://www.sciencedirect.com/science/article/pii/{pii}/pdf")

        return unique

    @staticmethod
    def _diagnostic_reason(attempts: list[PDFTestAttempt]) -> str:
        if not attempts:
            return "no_candidates"

        status_codes = [attempt.status_code for attempt in attempts if attempt.status_code is not None]
        if any(code == 403 for code in status_codes):
            return "blocked_403"
        if any(code == 429 for code in status_codes):
            return "rate_limited_429"
        if any((attempt.content_type or "").startswith("text/html") for attempt in attempts):
            return "html_not_pdf"
        return "no_valid_pdf_payload"

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
    def _download_concurrency(mode: str) -> int:
        return 20 if mode == "fast" else 16

    @classmethod
    def _download_concurrency_for_articles(cls, mode: str, articles: list[ArticleReference]) -> int:
        batch_size = max(1, len(articles))
        base = min(cls._download_concurrency(mode), batch_size)
        if mode != "fast":
            return base
        nature_count = sum(
            1
            for article in articles
            if (article.doi or "").lower().startswith("10.1038/")
        )
        if nature_count >= max(2, math.ceil(batch_size * 0.6)):
            return min(2, batch_size)
        return base

    @staticmethod
    def _candidate_concurrency(mode: str) -> int:
        return 6 if mode == "fast" else 6

    @staticmethod
    def _is_fast_confidence_source(source: str) -> bool:
        return (
            source in {
                "article_oa_pdf",
                "article_landing",
                "pmc_oa_pdf",
                "pmc_oa_tgz",
                "europe_pmc_repo_pdf",
                "europe_pmc_repo_xml",
                "crossref",
                "crossref_elsevier_xml",
                "openalex",
                "openalex_landing",
                "openalex_pmc_direct",
                "openalex_pmc_article",
                "openalex_europe_pmc_pdf",
                "citation_pdf_url",
                "doaj_pdf",
                "europe_pmc",
                "europepmc",
                "ncbi_linkout",
            }
            or source.endswith("_citation_pdf_url")
            or source.endswith("_page_pdf")
            or source.endswith("_html_fulltext")
        )

    @classmethod
    def _rank_fast_candidates(cls, candidates: list[PDFCandidate]) -> list[PDFCandidate]:
        priority = {
            "article_oa_pdf": 8,
            "article_landing": 17,
            "pmc_oa_pdf": 0,
            "pmc_oa_tgz": 1,
            "europe_pmc_repo_pdf": 2,
            "europe_pmc_repo_xml": 3,
            "crossref": 10,
            "crossref_elsevier_xml": 12,
            "ncbi_linkout": 13,
            "citation_pdf_url": 14,
            "doaj_pdf": 16,
            "openalex_landing": 17,
            "openalex": 20,
            "europe_pmc": 30,
            "europepmc": 30,
            "openalex_europe_pmc_pdf": 30,
            "openalex_pmc_direct": 5,
            "openalex_pmc_article": 18,
            "pmc_direct": 90,
        }
        preferred = [
            candidate for candidate in candidates
            if cls._is_fast_confidence_source(candidate.source)
        ]
        def sort_key(candidate: PDFCandidate) -> tuple[int, str]:
            source = candidate.source
            base_priority = priority.get(source, 99)
            if source.endswith("_citation_pdf_url"):
                base_priority = min(base_priority, 14)
            elif source.endswith("_page_pdf"):
                base_priority = min(base_priority, 15)
            elif source.endswith("_html_fulltext"):
                base_priority = min(base_priority, 18)
            return base_priority, candidate.url

        preferred.sort(key=sort_key)
        return preferred

    @classmethod
    def _download_probe_candidates(
        cls,
        article: ArticleReference,
        candidates: list[PDFCandidate],
        *,
        mode: str,
    ) -> list[PDFCandidate]:
        if mode != "fast":
            return candidates

        preferred = cls._rank_fast_candidates(candidates)
        if preferred:
            return preferred

        if article.pmc_id:
            pmc_candidates = [
                candidate
                for candidate in candidates
                if candidate.source in {"pmc_oa_pdf", "pmc_oa_tgz", "europe_pmc_repo_pdf", "europe_pmc_repo_xml", "pmc_direct"}
            ]
            if pmc_candidates:
                return pmc_candidates

        return candidates


    @staticmethod
    def _download_timeout_seconds(mode: str, source: str) -> float:
        if source == "europe_pmc_repo_pdf":
            return 60.0 if mode == "fast" else 75.0
        if source == "pmc_oa_tgz":
            return 25.0 if mode == "fast" else 35.0
        if source in {"crossref_elsevier_xml", "europe_pmc_repo_xml"} or source.endswith("_html_fulltext"):
            return 25.0 if mode == "fast" else 35.0
        if source.startswith("pmc_oa"):
            return 15.0 if mode == "fast" else 25.0
        return 20.0 if mode == "fast" else 30.0

    @staticmethod
    def _probe_timeout_seconds(mode: str, source: str) -> float:
        if source == "europe_pmc_repo_pdf":
            return 45.0 if mode == "fast" else 50.0
        if source in {"crossref_elsevier_xml", "europe_pmc_repo_xml"} or source.endswith("_html_fulltext"):
            return 20.0 if mode == "fast" else 30.0
        if source.startswith("pmc_oa"):
            return 3.0 if mode == "fast" else 8.0
        if source in {
            "article_oa_pdf",
            "article_landing",
            "crossref",
            "openalex",
            "openalex_landing",
            "openalex_pmc_direct",
            "openalex_pmc_article",
            "openalex_europe_pmc_pdf",
            "unpaywall",
            "europe_pmc",
            "europepmc",
            "pmc_direct",
            "citation_pdf_url",
            "doi_page",
            "doi_landing",
        }:
            if mode == "fast" and source in {"openalex", "openalex_landing", "citation_pdf_url"}:
                return 2.2
            return 2.0 if mode == "fast" else 5.0
        return 1.5 if mode == "fast" else 4.0

    @staticmethod
    def _quick_probe_range_header(source: str) -> str:
        if source == "pmc_oa_tgz":
            return f"bytes=0-{PDFService._quick_tgz_probe_max_bytes() - 1}"
        return "bytes=0-65535"

    @staticmethod
    def _quick_probe_read_limit(source: str, content_type: str) -> int:
        if "html" in content_type or "xml" in content_type or "text/plain" in content_type:
            return 65536
        if source in {
            "article_oa_pdf",
            "openalex",
            "openalex_pmc_direct",
            "openalex_europe_pmc_pdf",
            "citation_pdf_url",
            "crossref",
            "pmc_direct",
            "pmc_oa_pdf",
        }:
            return 16384
        return 8192

    @staticmethod
    def _quick_tgz_probe_max_bytes() -> int:
        return 524288

    @staticmethod
    def _availability_cache_key(article: ArticleReference, downloader_mode: str) -> str:
        return "|".join(
            [
                downloader_mode,
                article.pmid or "",
                article.doi or "",
                article.pmc_id or "",
                article.title or "",
                article.year or "",
            ]
        )
