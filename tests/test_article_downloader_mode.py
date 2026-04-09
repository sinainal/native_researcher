from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.schemas.article import ArticleReference
from app.schemas.pdf import PDFDownloadRequest
from app.services.pdf_service import PDFService
from app.services.downloader.article_downloader_bridge import ArticleDownloaderBridge
from app.services.downloader.hybrid_bridge import HybridDownloaderBridge
from app.utils.cache import TTLCache


def test_article_downloader_bridge_uses_real_tool_modes_in_order(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    async def runner() -> None:
        doi = "10.1038/s41598-026-45504-2"
        calls: list[tuple[str, str, str]] = []

        class FakeDownloader:
            def get_pdf_from_doi(self, given_doi: str, writefile, mode: str) -> bool:
                calls.append((given_doi, mode, Path(writefile.name).name))
                if mode == "springer":
                    writefile.write(b"%PDF-1.7 article downloader")
                    return True
                return False

        bridge = ArticleDownloaderBridge()
        monkeypatch.setattr(bridge, "_make_downloader", lambda: FakeDownloader())
        result = await bridge.run(
            ArticleReference(title="Nature article", year="2026", doi=doi),
            output_dir=tmp_path,
            mode="fast",
        )

        assert result["success"] is True
        assert result["source"] == "article_downloader_springer"
        assert len(calls) == 1
        assert calls[0][0] == doi
        assert calls[0][1] == "springer"

    asyncio.run(runner())


def test_article_downloader_bridge_resolves_dynamic_modes() -> None:
    assert ArticleDownloaderBridge._modes_for(
        ArticleReference(
            title="Sepsis study",
            year="2026",
            journal="Scientific reports",
            doi="10.1038/s41598-026-45504-2",
        )
    ) == ["springer", "nature", "crossref"]
    assert ArticleDownloaderBridge._modes_for(
        ArticleReference(
            title="Elsevier paper",
            year="2026",
            journal="Heliyon",
            doi="10.1016/j.heliyon.2026.00001",
        )
    ) == ["elsevier", "crossref"]
    assert ArticleDownloaderBridge._modes_for(
        ArticleReference(
            title="ACS paper",
            year="2026",
            journal="ACS Omega",
            doi="10.1021/acsomega.6c00001",
        )
    ) == ["acs", "crossref"]


def test_pdf_service_article_downloader_mode_runs_single_runner(tmp_path) -> None:
    async def runner() -> None:
        settings = Settings(download_root=tmp_path, pdf_downloader_mode="article_downloader")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            active = 0
            max_active = 0

            class SequentialBridge:
                async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                    _ = article, mode
                    return []

                async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                    nonlocal active, max_active
                    _ = output_dir, mode, budget_seconds
                    active += 1
                    max_active = max(max_active, active)
                    await asyncio.sleep(0.01)
                    active -= 1
                    return {
                        "article": article.model_dump(),
                        "mode": "fast",
                        "success": False,
                        "source": None,
                        "url": None,
                        "file_path": None,
                        "total_ms": 10,
                        "attempts": [],
                        "candidate_count": 0,
                        "note": "no_successful_candidate",
                    }

            service.article_downloader_bridge = SequentialBridge()  # type: ignore[assignment]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(title="A", year="2026", doi="10.1038/a"),
                        ArticleReference(title="B", year="2026", doi="10.1038/b"),
                        ArticleReference(title="C", year="2026", doi="10.1038/c"),
                    ],
                    downloader_mode="article_downloader",
                )
            )

        assert response.total == 3
        assert max_active == 1

    asyncio.run(runner())


def test_hybrid_bridge_uses_legacy_success_without_tool(tmp_path) -> None:
    async def runner() -> None:
        class FakeLegacy:
            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "legacy", "url": "https://example.org/legacy.pdf"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                _ = output_dir, mode, budget_seconds
                return {
                    "article": article.model_dump(),
                    "mode": "fast",
                    "success": True,
                    "source": "pmc_oa_tgz",
                    "url": "https://example.org/legacy.pdf",
                    "file_path": str(tmp_path / "legacy.pdf"),
                    "total_ms": 12,
                    "attempts": [{"source": "pmc_oa_tgz", "status": "ok"}],
                    "candidate_count": 4,
                    "note": None,
                }

        class FakeTool:
            calls = 0

            @staticmethod
            def _modes_for(article: ArticleReference) -> list[str]:
                _ = article
                return ["elsevier", "crossref"]

            @staticmethod
            def _normalize_text(value: str | None) -> str:
                return (value or "").lower()

            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "article_downloader_springer", "url": "https://doi.org/x"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                _ = article, output_dir, mode, budget_seconds
                self.calls += 1
                return {"success": False, "attempts": [], "candidate_count": 0, "note": "should_not_run"}

        tool = FakeTool()
        bridge = HybridDownloaderBridge(legacy_bridge=FakeLegacy(), article_downloader_bridge=tool)  # type: ignore[arg-type]
        result = await bridge.run(
            ArticleReference(title="Fast legacy hit", year="2026", doi="10.1016/j.heliyon.2026.00001", journal="Heliyon"),
            output_dir=tmp_path,
        )

        assert result["success"] is True
        assert result["source"] == "pmc_oa_tgz"
        assert tool.calls == 0

    asyncio.run(runner())


def test_hybrid_bridge_prefers_tool_first_for_nature_family(tmp_path) -> None:
    async def runner() -> None:
        class FakeLegacy:
            calls = 0

            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "openalex", "url": "https://example.org/legacy"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                self.calls += 1
                _ = output_dir, mode, budget_seconds
                return {
                    "article": article.model_dump(),
                    "mode": "fast",
                    "success": False,
                    "source": None,
                    "url": None,
                    "file_path": None,
                    "total_ms": 50,
                    "attempts": [{"source": "openalex", "status": "error", "detail": "budget_exhausted"}],
                    "candidate_count": 5,
                    "note": "budget_exhausted",
                }

        class FakeTool:
            calls = 0

            @staticmethod
            def _modes_for(article: ArticleReference) -> list[str]:
                _ = article
                return ["springer", "nature", "crossref"]

            @staticmethod
            def _normalize_text(value: str | None) -> str:
                return (value or "").lower()

            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "article_downloader_springer", "url": "https://doi.org/x"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                _ = article, output_dir, mode, budget_seconds
                self.calls += 1
                return {
                    "article": article.model_dump(),
                    "mode": "fast",
                    "success": True,
                    "source": "article_downloader_springer",
                    "url": "https://doi.org/x",
                    "file_path": str(tmp_path / "tool.pdf"),
                    "total_ms": 20,
                    "attempts": [{"source": "article_downloader_springer", "status": "ok"}],
                    "candidate_count": 3,
                    "note": None,
                }

        legacy = FakeLegacy()
        tool = FakeTool()
        bridge = HybridDownloaderBridge(legacy_bridge=legacy, article_downloader_bridge=tool)  # type: ignore[arg-type]
        result = await bridge.run(
            ArticleReference(title="Nature family", year="2026", doi="10.1038/s41598-026-45504-2", journal="Scientific reports"),
            output_dir=tmp_path,
        )

        assert result["success"] is True
        assert result["source"] == "article_downloader_springer"
        assert result["candidate_count"] == 3
        assert len(result["attempts"]) == 1
        assert tool.calls == 1
        assert legacy.calls == 0

    asyncio.run(runner())


def test_hybrid_bridge_uses_article_downloader_as_bounded_fallback(tmp_path) -> None:
    async def runner() -> None:
        class FakeLegacy:
            calls = 0

            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "crossref", "url": "https://example.org/legacy"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                self.calls += 1
                _ = output_dir, mode, budget_seconds
                return {
                    "article": article.model_dump(),
                    "mode": "fast",
                    "success": False,
                    "source": None,
                    "url": None,
                    "file_path": None,
                    "total_ms": 50,
                    "attempts": [{"source": "crossref", "status": "error", "detail": "no_successful_candidate"}],
                    "candidate_count": 2,
                    "note": "no_successful_candidate",
                }

        class FakeTool:
            calls = 0

            @staticmethod
            def _modes_for(article: ArticleReference) -> list[str]:
                _ = article
                return ["elsevier", "crossref"]

            @staticmethod
            def _normalize_text(value: str | None) -> str:
                return (value or "").lower()

            async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                _ = article, mode
                return [{"source": "article_downloader_elsevier", "url": "https://doi.org/x"}]

            async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                _ = article, output_dir, mode, budget_seconds
                self.calls += 1
                return {
                    "article": article.model_dump(),
                    "mode": "fast",
                    "success": True,
                    "source": "article_downloader_elsevier",
                    "url": "https://doi.org/x",
                    "file_path": str(tmp_path / "tool.pdf"),
                    "total_ms": 20,
                    "attempts": [{"source": "article_downloader_elsevier", "status": "ok"}],
                    "candidate_count": 2,
                    "note": None,
                }

        legacy = FakeLegacy()
        tool = FakeTool()
        bridge = HybridDownloaderBridge(legacy_bridge=legacy, article_downloader_bridge=tool)  # type: ignore[arg-type]
        result = await bridge.run(
            ArticleReference(title="Elsevier family", year="2026", doi="10.1016/j.heliyon.2026.00001", journal="Heliyon"),
            output_dir=tmp_path,
        )

        assert result["success"] is True
        assert result["source"] == "article_downloader_elsevier"
        assert result["candidate_count"] == 4
        assert len(result["attempts"]) == 2
        assert tool.calls == 1
        assert legacy.calls == 1

    asyncio.run(runner())


def test_pdf_service_hybrid_mode_uses_native_download_rescue(tmp_path) -> None:
    async def runner() -> None:
        settings = Settings(download_root=tmp_path, pdf_downloader_mode="hybrid")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            class FailingHybridBridge:
                async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                    _ = article, mode
                    return [{"source": "article_downloader_crossref", "url": "https://doi.org/x"}]

                async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                    _ = output_dir, mode, budget_seconds
                    return {
                        "article": article.model_dump(),
                        "mode": "fast",
                        "success": False,
                        "source": None,
                        "url": None,
                        "file_path": None,
                        "total_ms": 10,
                        "attempts": [{"source": "article_downloader_crossref", "status": "error", "detail": "tool_returned_false"}],
                        "candidate_count": 1,
                        "note": "no_successful_candidate",
                    }

            async def fake_native_download(article: ArticleReference, target_dir: Path, **kwargs):
                _ = kwargs
                output = target_dir / "native.pdf"
                output.write_bytes(b"%PDF-1.7 hybrid native rescue")
                return service._to_pdf_download_result(
                    article,
                    {
                        "article": article.model_dump(),
                        "mode": "fast",
                        "success": True,
                        "source": "crossref",
                        "url": "https://example.org/native.pdf",
                        "file_path": str(output),
                        "total_ms": 20,
                        "attempts": [],
                        "candidate_count": 2,
                        "note": None,
                    },
                )

            service.hybrid_bridge = FailingHybridBridge()  # type: ignore[assignment]
            service._download_single_article = fake_native_download  # type: ignore[method-assign]

            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="Rescue me", year="2026", doi="10.1000/test")],
                    downloader_mode="hybrid",
                )
            )

        assert response.success_count == 1
        assert response.results[0].source == "crossref"

    asyncio.run(runner())


def test_pdf_service_hybrid_mode_uses_native_diagnose_rescue(tmp_path) -> None:
    async def runner() -> None:
        settings = Settings(download_root=tmp_path, pdf_downloader_mode="hybrid")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: httpx.Response(500))) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            class FailingHybridBridge:
                async def resolve_candidates(self, article: ArticleReference, *, mode: str = "fast"):
                    _ = article, mode
                    return [{"source": "article_downloader_crossref", "url": "https://doi.org/x"}]

                async def run(self, article: ArticleReference, *, output_dir, mode: str = "fast", budget_seconds: float = 60.0):
                    _ = output_dir, mode, budget_seconds
                    return {
                        "article": article.model_dump(),
                        "mode": "fast",
                        "success": False,
                        "source": None,
                        "url": None,
                        "file_path": None,
                        "total_ms": 10,
                        "attempts": [{"source": "article_downloader_crossref", "status": "error", "detail": "tool_returned_false"}],
                        "candidate_count": 1,
                        "note": "no_successful_candidate",
                    }

            async def fake_native_diagnose(article: ArticleReference, target_dir: Path, **kwargs):
                _ = target_dir, kwargs
                return service._to_pdf_test_result(
                    article,
                    {
                        "article": article.model_dump(),
                        "mode": "fast",
                        "success": True,
                        "source": "article_oa_pdf",
                        "url": "https://example.org/native.pdf",
                        "file_path": str(tmp_path / "native.pdf"),
                        "total_ms": 18,
                        "attempts": [{"source": "article_oa_pdf", "status": "ok", "url": "https://example.org/native.pdf"}],
                        "candidate_count": 2,
                        "note": None,
                    },
                    expose_file_path=False,
                )

            service.hybrid_bridge = FailingHybridBridge()  # type: ignore[assignment]
            service._diagnose_single_article = fake_native_diagnose  # type: ignore[method-assign]

            results = await service.diagnose_articles(
                [ArticleReference(title="Rescue me", year="2026", doi="10.1000/test")],
                save_files=False,
                mode="fast",
                downloader_mode="hybrid",
            )

        assert results[0].success is True
        assert results[0].source == "article_oa_pdf"
        assert len(results[0].attempts) == 2

    asyncio.run(runner())
