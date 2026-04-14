"""Bridge for the real `articledownloader` package."""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from app.schemas.article import ArticleReference


class ArticleDownloaderBridge:
    """Thin wrapper around the upstream `articledownloader` DOI API."""

    def __init__(self, *, timeout_sec: int = 20) -> None:
        self.timeout_sec = timeout_sec

    @staticmethod
    def _safe_stem(article: ArticleReference) -> str:
        raw = article.doi or article.pmid or article.pmc_id or article.title or "article"
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
        return stem or "article"

    @staticmethod
    def _valid_pdf(path: Path) -> bool:
        return path.exists() and path.stat().st_size > 0 and path.read_bytes()[:16].startswith(b"%PDF")

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()

    @classmethod
    def _modes_for(cls, article: ArticleReference) -> list[str]:
        doi = (article.doi or "").strip()
        if not doi:
            return []
        lowered = doi.lower()
        prefix = lowered.split("/", 1)[0]
        journal = cls._normalize_text(article.journal)
        title = cls._normalize_text(article.title)
        modes: list[str] = []

        def add(*items: str) -> None:
            for item in items:
                if item not in modes:
                    modes.append(item)

        if prefix == "10.1016":
            add("elsevier", "crossref")
        if prefix == "10.1021":
            add("acs", "crossref")
        if prefix == "10.1039":
            add("rsc", "crossref")
        if prefix == "10.1149":
            add("ecs", "crossref")
        if prefix in {"10.1038", "10.1007", "10.1186"}:
            add("springer", "nature", "crossref")

        springer_markers = (
            "scientific reports",
            "scientific data",
            "nature communications",
            "communications biology",
            "communications medicine",
            "communications chemistry",
            "experimental molecular medicine",
            "experimental & molecular medicine",
            "bmc ",
            "springer",
            "springeropen",
        )
        if any(marker in journal for marker in springer_markers):
            add("springer", "nature", "crossref")

        if "journal of the electrochemical society" in journal or "ecs journal" in journal:
            add("ecs", "crossref")
        if journal.startswith("acs ") or "american chemical society" in journal:
            add("acs", "crossref")
        if any(marker in journal for marker in ("rsc advances", "chemical communications", "green chemistry", "chemical science", "faraday discussions")):
            add("rsc", "crossref")
        if any(marker in journal for marker in ("cell", "thelancet", "the lancet", "heliyon", "eclinicalmedicine", "materials today")):
            add("elsevier", "crossref")

        if "nature" in journal and "springer" not in modes:
            add("nature", "crossref")

        if "author correction" in title and "springer" not in modes and prefix == "10.1038":
            add("springer", "nature", "crossref")

        add("crossref")
        return modes[:3]

    @staticmethod
    def _source_for_mode(mode: str) -> str:
        return f"article_downloader_{mode}"

    def _make_downloader(self):
        from articledownloader.articledownloader import ArticleDownloader

        return ArticleDownloader(timeout_sec=self.timeout_sec)

    def _run_sync(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str,
        budget_seconds: float,
    ) -> dict[str, Any]:
        _ = mode, budget_seconds
        started = time.perf_counter()
        doi = (article.doi or "").strip()
        output_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[dict[str, Any]] = []
        if not doi:
            return {
                "article": article.model_dump(),
                "mode": mode,
                "success": False,
                "source": None,
                "url": None,
                "file_path": None,
                "total_ms": int((time.perf_counter() - started) * 1000),
                "attempts": attempts,
                "candidate_count": 0,
                "note": "missing_doi",
            }

        modes = self._modes_for(article)
        downloader = self._make_downloader()
        target = output_dir / f"{self._safe_stem(article)}.pdf"
        for candidate_mode in modes:
            target.unlink(missing_ok=True)
            attempt_started = time.perf_counter()
            error: str | None = None
            ok = False
            try:
                with target.open("wb") as writefile:
                    ok = bool(downloader.get_pdf_from_doi(doi, writefile, candidate_mode))
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
            pdf_ok = self._valid_pdf(target)
            attempts.append(
                {
                    "step": "download",
                    "source": self._source_for_mode(candidate_mode),
                    "status": "ok" if pdf_ok else "error" if error else "reject",
                    "elapsed_ms": int((time.perf_counter() - attempt_started) * 1000),
                    "url": f"https://doi.org/{doi}",
                    "detail": None if pdf_ok else error or ("tool_returned_false" if not ok else "non_pdf_response"),
                    "status_code": None,
                    "content_type": "application/pdf" if pdf_ok else None,
                }
            )
            if pdf_ok:
                return {
                    "article": article.model_dump(),
                    "mode": mode,
                    "success": True,
                    "source": self._source_for_mode(candidate_mode),
                    "url": f"https://doi.org/{doi}",
                    "file_path": str(target),
                    "total_ms": int((time.perf_counter() - started) * 1000),
                    "attempts": attempts,
                    "candidate_count": len(modes),
                    "note": None,
                }
            target.unlink(missing_ok=True)
        return {
            "article": article.model_dump(),
            "mode": mode,
            "success": False,
            "source": None,
            "url": None,
            "file_path": None,
            "total_ms": int((time.perf_counter() - started) * 1000),
            "attempts": attempts,
            "candidate_count": len(modes),
            "note": "no_successful_candidate",
        }

    async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast") -> list[dict[str, Any]]:
        _ = mode
        doi = (article.doi or "").strip()
        if not doi:
            return []
        return [
            {
                "source": self._source_for_mode(candidate_mode),
                "url": f"https://doi.org/{doi}",
            }
            for candidate_mode in self._modes_for(article)
        ]

    async def run(
        self,
        article: ArticleReference,
        *,
        output_dir: Path,
        mode: str = "fast",
        budget_seconds: float = 60.0,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._run_sync,
            article,
            output_dir=output_dir,
            mode=mode,
            budget_seconds=budget_seconds,
        )
