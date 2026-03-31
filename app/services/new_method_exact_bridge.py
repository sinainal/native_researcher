"""Exact bridge to the vendored new_method downloader."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx

from app.schemas.article import ArticleReference
from app.services import new_method_exact_core


class ExactNewMethodBridge:
    """Thin adapter over the vendored exact downloader."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _make_downloader(self, *, mode: str, output_dir: Path, budget_seconds: float) -> Any:
        downloader = new_method_exact_core.SingleArticleDownloader(
            mode=mode,
            output_dir=output_dir,
            budget_seconds=budget_seconds,
            user_agent=new_method_exact_core.DEFAULT_USER_AGENT,
        )
        if self._transport is not None:
            original_metadata = downloader._metadata_client
            original_download = downloader._download_client
            downloader._metadata_client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=4.0, read=4.0, write=4.0, pool=2.0),
                headers={"User-Agent": new_method_exact_core.DEFAULT_USER_AGENT},
                follow_redirects=True,
            )
            downloader._download_client = httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(connect=5.0, read=25.0, write=25.0, pool=5.0),
                headers={"User-Agent": new_method_exact_core.DEFAULT_USER_AGENT},
                follow_redirects=True,
            )
            downloader._bridge_original_clients = (original_metadata, original_download)
        return downloader

    async def _close_downloader(self, downloader: Any) -> None:
        originals = getattr(downloader, "_bridge_original_clients", None)
        try:
            await downloader.close()
        finally:
            if originals:
                await originals[0].aclose()
                await originals[1].aclose()

    def article_ref(self, article: ArticleReference) -> Any:
        return new_method_exact_core.ArticleRef(
            pmid=article.pmid,
            doi=article.doi,
            pmc_id=article.pmc_id,
            title=article.title,
            year=article.year,
        )

    async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast") -> list[dict[str, Any]]:
        article_ref = self.article_ref(article)
        with TemporaryDirectory() as temp_dir:
            downloader = self._make_downloader(mode=mode, output_dir=Path(temp_dir), budget_seconds=60.0)
            try:
                all_candidates: list[Any] = []
                if article_ref.pmc_id:
                    pmc_candidates = await downloader._pmc_oa_candidates(article_ref.pmc_id)
                    all_candidates.extend(pmc_candidates)

                if article_ref.doi:
                    if mode == "fast":
                        crossref_candidates, openalex_candidates, doaj_candidates, ncbi_linkout_candidates, europe_candidates = await asyncio.gather(
                            downloader._crossref_candidates(article_ref.doi),
                            downloader._openalex_candidates(article_ref.doi),
                            downloader._doaj_candidates(article_ref.doi),
                            downloader._ncbi_linkout_candidates(article_ref.pmid) if article_ref.pmid else asyncio.sleep(0, result=[]),
                            downloader._europe_pmc_candidates(article_ref) if article_ref.pmc_id else asyncio.sleep(0, result=[]),
                        )
                        all_candidates.extend(crossref_candidates)
                        all_candidates.extend(openalex_candidates)
                        all_candidates.extend(doaj_candidates)
                        all_candidates.extend(ncbi_linkout_candidates)
                        all_candidates.extend(europe_candidates)
                    else:
                        crossref_candidates, openalex_candidates, doaj_candidates, ncbi_linkout_candidates, europe_candidates, landing_candidates = await asyncio.gather(
                            downloader._crossref_candidates(article_ref.doi),
                            downloader._openalex_candidates(article_ref.doi),
                            downloader._doaj_candidates(article_ref.doi),
                            downloader._ncbi_linkout_candidates(article_ref.pmid) if article_ref.pmid else asyncio.sleep(0, result=[]),
                            downloader._europe_pmc_candidates(article_ref),
                            downloader._doi_landing_candidates(article_ref.doi),
                        )
                        all_candidates.extend(crossref_candidates)
                        all_candidates.extend(openalex_candidates)
                        all_candidates.extend(doaj_candidates)
                        all_candidates.extend(ncbi_linkout_candidates)
                        all_candidates.extend(europe_candidates)
                        all_candidates.extend(landing_candidates)
                elif mode == "balanced" and article_ref.pmc_id:
                    all_candidates.extend(await downloader._europe_pmc_candidates(article_ref))

                deduped = downloader._dedupe_candidates(all_candidates)
                return [{"source": item.source, "url": item.url} for item in deduped]
            finally:
                await self._close_downloader(downloader)

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str = "fast",
        budget_seconds: float = 60.0,
    ) -> dict[str, Any]:
        article_ref = self.article_ref(article)
        downloader = self._make_downloader(mode=mode, output_dir=output_dir, budget_seconds=budget_seconds)
        try:
            result = await downloader.run(article_ref)
            return {
                "article": result.article,
                "mode": result.mode,
                "success": result.success,
                "source": result.source,
                "url": result.url,
                "file_path": result.file_path,
                "total_ms": result.total_ms,
                "attempts": result.attempts,
                "candidate_count": result.candidate_count,
                "note": result.note,
            }
        finally:
            await self._close_downloader(downloader)
