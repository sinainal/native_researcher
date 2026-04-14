"""Unified downloader tests."""

from __future__ import annotations

import asyncio
import io
import tarfile

import httpx

from app.core.config import Settings
from app.schemas.article import ArticleReference
from app.schemas.pdf import PDFDownloadRequest
from app.services.pdf_service import PDFService
from app.utils.cache import TTLCache


def test_best_mode_prefers_xml_when_xml_is_available(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/idconv" in url:
                return httpx.Response(200, json={"records": [{"pmcid": "PMC12345"}]})
            if "efetch.fcgi?db=pmc&id=12345" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/xml"},
                    content=b"<?xml version='1.0'?><article><body><sec>text</sec></body></article>",
                )
            if "api.crossref.org/works/" in url:
                return httpx.Response(
                    200,
                    json={"message": {"link": [{"URL": "https://files.example.org/paper.pdf", "content-type": "application/pdf"}]}},
                )
            if url == "https://files.example.org/paper.pdf":
                return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 test")
            if "europepmc.org" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="best"), TTLCache(60, 16))
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="XML first", year="2025", doi="10.1000/xml-first")],
                    downloader_mode="best",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "crossref_pdf"
        assert result.file_path and result.file_path.endswith(".pdf")

    asyncio.run(runner())


def test_xml_mode_returns_xml_only(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/idconv" in url:
                return httpx.Response(200, json={"records": [{"pmcid": "PMC12345"}]})
            if "efetch.fcgi?db=pmc&id=12345" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/xml"},
                    content=b"<?xml version='1.0'?><article><body><sec>text</sec></body></article>",
                )
            if "api.crossref.org/works/" in url:
                return httpx.Response(
                    200,
                    json={"message": {"link": [{"URL": "https://files.example.org/paper.pdf", "content-type": "application/pdf"}]}},
                )
            if url == "https://files.example.org/paper.pdf":
                return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 test")
            if "europepmc.org" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="pdf_xml"), TTLCache(60, 16))
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="XML only", year="2025", doi="10.1000/xml-only")],
                    downloader_mode="xml",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "pmc_efetch_xml"
        assert result.file_path and result.file_path.endswith(".xml")

    asyncio.run(runner())


def test_best_mode_falls_back_to_pdf(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/idconv" in url:
                return httpx.Response(200, json={"records": []})
            if "europepmc.org" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(
                    200,
                    json={"message": {"link": [{"URL": "https://files.example.org/fallback.pdf", "content-type": "application/pdf"}]}},
                )
            if url == "https://files.example.org/fallback.pdf":
                return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7 fallback")
            if "doi.org/" in url:
                return httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="best"), TTLCache(60, 16))
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="PDF fallback", year="2025", doi="10.1000/pdf-fallback")],
                    downloader_mode="best",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.source == "crossref_pdf"
        assert result.file_path and result.file_path.endswith(".pdf")

    asyncio.run(runner())


def test_pdf_mode_extracts_pdf_from_pmc_package(tmp_path) -> None:
    async def runner() -> None:
        buffer = io.BytesIO()
        pdf_bytes = b"%PDF-1.7 package document"
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            info = tarfile.TarInfo(name="PMC123/paper.pdf")
            info.size = len(pdf_bytes)
            archive.addfile(info, io.BytesIO(pdf_bytes))

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml"},
                    text=(
                        "<OA><records><record>"
                        "<link format='tgz' href='ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC123.tar.gz'/>"
                        "</record></records></OA>"
                    ),
                )
            if url == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC123.tar.gz":
                return httpx.Response(200, headers={"content-type": "application/x-gzip"}, content=buffer.getvalue())
            if "europepmc.org/api/fulltextRepo" in url:
                return httpx.Response(200, json={"version": 1, "files": []})
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="pdf"), TTLCache(60, 16))
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="PMC package", year="2025", pmc_id="PMC123")],
                    downloader_mode="pdf",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.source == "pmc_oa_package"
        assert result.file_path and result.file_path.endswith(".pdf")

    asyncio.run(runner())


def test_resolve_best_candidates_combines_xml_and_pdf_sources(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/idconv" in url:
                return httpx.Response(200, json={"records": [{"pmcid": "PMC7003109"}]})
            if "api/fulltextRepo" in url and "type=METADATA" in url:
                return httpx.Response(
                    200,
                    json={
                        "version": 1,
                        "files": [
                            {"filename": "paper.xml", "mimeType": "application/xml", "type": "xml"},
                            {"filename": "paper.pdf", "mimeType": "application/pdf", "type": "pdf"},
                        ],
                    },
                )
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(200, headers={"content-type": "text/xml"}, text="<OA></OA>")
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="best"), TTLCache(60, 16))
            response = await service.resolve(
                ArticleReference(title="Combined", year="2025", doi="10.1000/combined"),
                downloader_mode="best",
            )

        sources = {candidate.source for candidate in response.candidates}
        assert "pmc_efetch_xml" in sources
        assert "europe_pmc_repo_xml" in sources
        assert "pmc_direct_pdf" in sources
        assert "europe_pmc_repo_pdf" in sources

    asyncio.run(runner())


def test_quick_availability_reports_failure_reason(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/idconv" in url:
                return httpx.Response(200, json={"records": []})
            if "europepmc.org" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "doi.org/" in url:
                return httpx.Response(403, headers={"content-type": "text/html"}, text="<html>blocked</html>")
            raise AssertionError(f"Unexpected URL: {url}")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            service = PDFService(client, Settings(download_root=tmp_path, pdf_downloader_mode="best"), TTLCache(60, 16))
            response = await service.quick_availability(
                [ArticleReference(title="Blocked", year="2025", doi="10.1000/blocked", landing_page_url="https://doi.org/10.1000/blocked")]
            )

        item = response.items[0]
        assert item.ready is False
        assert item.detail == "blocked_403"

    asyncio.run(runner())
