"""Smoke test helper coverage."""

from __future__ import annotations

import argparse
import asyncio

from scripts.download_smoke import build_parser, run_smoke


def test_smoke_parser_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["--query", "docking"])
    assert args.query == "docking"
    assert args.source == "pubmed"
    assert args.mode == "pdf_xml"
    assert args.max_results == 1


def test_smoke_runner_uses_injected_services(monkeypatch) -> None:
    class FakeSettings:
        http_timeout_seconds = 1.0
        request_user_agent = "test-agent"
        ncbi_base_url = "https://ncbi.example"
        search_cache_ttl_seconds = 60
        search_cache_max_entries = 8
        pdf_cache_ttl_seconds = 60
        pdf_cache_max_entries = 8

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeMeta:
        def model_dump(self) -> dict[str, object]:
            return {"primary_source": "pmc", "fetched_results": 1}

    class FakeArticle:
        title = "Test"
        year = "2025"
        journal = None
        doi = "10.1000/test"
        pmc_id = "PMC1"
        pmid = "1"
        oa_pdf_url = None
        landing_page_url = None

    class FakeSearchResponse:
        meta = FakeMeta()
        articles = [FakeArticle()]

    class FakePubMedService:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            pass

        async def search(self, request):  # noqa: ANN001
            assert request.query == "docking"
            assert request.preferred_source == "pmc"
            return FakeSearchResponse()

    class FakeResult:
        success = True

        def model_dump(self) -> dict[str, object]:
            return {"success": True, "source": "pmc_efetch_xml"}

    class FakePDFService:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            pass

        async def diagnose_articles(self, articles, **kwargs):  # noqa: ANN001
            assert len(articles) == 1
            assert kwargs["downloader_mode"] == "pdf_xml"
            return [FakeResult()]

    class FakeNcbiClient:
        def __init__(self, client, settings) -> None:  # noqa: ANN001
            self.client = client
            self.settings = settings

    class FakeCache:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN001
            pass

    monkeypatch.setattr("scripts.download_smoke.get_settings", lambda: FakeSettings())
    monkeypatch.setattr("scripts.download_smoke.httpx.AsyncClient", FakeAsyncClient)
    monkeypatch.setattr("scripts.download_smoke.NcbiClient", FakeNcbiClient)
    monkeypatch.setattr("scripts.download_smoke.PubMedService", FakePubMedService)
    monkeypatch.setattr("scripts.download_smoke.PDFService", FakePDFService)
    monkeypatch.setattr("scripts.download_smoke.TTLCache", FakeCache)

    parser = build_parser()
    args = parser.parse_args(["--query", "docking", "--source", "pmc", "--mode", "pdf_xml"])
    payload = asyncio.run(run_smoke(args))
    assert payload["success_rate"] == 100.0
    assert payload["search_meta"]["primary_source"] == "pmc"
