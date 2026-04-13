"""PDF service tests."""

from __future__ import annotations

import asyncio
import io
import tarfile

import httpx

from app.core.config import Settings
from app.schemas.article import ArticleReference
from app.schemas.pdf import PDFCandidate, PDFDownloadRequest, PDFDownloadResult, PDFResolveResponse
from app.services.new_method_exact_bridge import ExactNewMethodBridge
from app.services.pdf_service import PDFService
from app.utils.cache import TTLCache


def test_pdf_service_downloads_from_crossref_first(tmp_path) -> None:
    async def runner() -> None:
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            if "europepmc/webservices/rest/search" in str(request.url):
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "message": {
                            "link": [
                                {
                                    "URL": "https://files.example.org/paper.pdf",
                                    "content-type": "application/pdf",
                                }
                            ]
                        }
                    },
                )
            if "api.openalex.org/works" in str(request.url):
                return httpx.Response(200, json={"results": []})
            if str(request.url) == "https://files.example.org/paper.pdf":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 test document",
                )
            if str(request.url) == "https://doi.org/10.1000%2Ftest":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><a href='https://files.example.org/paper.pdf'>PDF</a></body></html>",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="Crossref Article",
                            year="2024",
                            doi="10.1000/test",
                        )
                    ]
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "crossref"
        assert result.file_path is not None
        assert any("paper.pdf" in call for call in calls)

    asyncio.run(runner())


def test_pdf_service_uses_openalex_pmc_location_without_article_pmcid(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "best_oa_location": None,
                                "primary_location": None,
                                "locations": [
                                    {
                                        "landing_page_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/7003109",
                                        "pdf_url": None,
                                    }
                                ],
                            }
                        ]
                    },
                )
            if "oa.fcgi" in url and "PMC7003109" in url:
                return httpx.Response(404)
            if "europepmc.org/api/fulltextRepo" in url and "type=METADATA" in url:
                return httpx.Response(
                    200,
                    json={
                        "version": 1,
                        "files": [
                            {
                                "filename": "7003109.xml",
                                "mimeType": "application/xml",
                                "type": "xml",
                            }
                        ],
                    },
                )
            if "europepmc.org/api/fulltextRepo" in url and "type=FILE" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/xml;charset=utf-8"},
                    content=b"<full-text-retrieval-response>" + (b"x" * 800) + b"</full-text-retrieval-response>",
                )
            if "ncbi.nlm.nih.gov/pmc/articles/7003109" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><div>PMC landing</div></body></html>",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.resolve(
                ArticleReference(
                    title="PMC from OpenAlex location",
                    year="2019",
                    journal="The Canadian Journal of Psychiatry",
                    doi="10.1177/0706743719877031",
                ),
                downloader_mode="native",
            )

        sources = {candidate.source for candidate in response.candidates}
        assert "openalex_landing" in sources
        assert "openalex_pmc_direct" in sources
        assert "europe_pmc_repo_xml" in sources

    asyncio.run(runner())


def test_exact_bridge_uses_nature_direct_pdf_fast_path(tmp_path) -> None:
    async def runner() -> None:
        calls: list[tuple[str, str | None]] = []
        pdf_bytes = b"%PDF-1.7 nature direct pdf"

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((str(request.url), request.headers.get("range")))
            if str(request.url) == "https://www.nature.com/articles/s41598-026-45504-2.pdf":
                if request.headers.get("range"):
                    return httpx.Response(
                        206,
                        headers={
                            "content-type": "application/pdf",
                            "content-range": f"bytes 0-{len(pdf_bytes) - 1}/{len(pdf_bytes)}",
                        },
                        content=pdf_bytes,
                    )
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=pdf_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        bridge = ExactNewMethodBridge(transport=httpx.MockTransport(handler))
        result = await bridge.run(
            ArticleReference(title="Nature OA", year="2026", doi="10.1038/s41598-026-45504-2"),
            output_dir=tmp_path,
            mode="fast",
            budget_seconds=20.0,
        )

        assert result["success"] is True
        assert result["source"] == "nature_direct_pdf"
        assert result["file_path"] is not None
        assert calls == [
            ("https://www.nature.com/articles/s41598-026-45504-2.pdf", "bytes=0-16383"),
            ("https://www.nature.com/articles/s41598-026-45504-2.pdf", None),
        ]

    asyncio.run(runner())


def test_exact_bridge_uses_nature_html_fast_fallback(tmp_path) -> None:
    async def runner() -> None:
        calls: list[tuple[str, str | None]] = []
        article_url = "https://www.nature.com/articles/s41467-026-71180-x"
        pdf_url = f"{article_url}.pdf"
        html_body = (
            "<html><head>"
            "<meta name='citation_title' content='Nature communications article' />"
            f"<meta name='citation_pdf_url' content='{pdf_url}' />"
            "</head><body>"
            + ("full text content " * 1200)
            + "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((str(request.url), request.headers.get("range")))
            if str(request.url) == pdf_url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html_body,
                )
            if str(request.url) == article_url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html_body,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        bridge = ExactNewMethodBridge(transport=httpx.MockTransport(handler))
        result = await bridge.run(
            ArticleReference(title="Nature communications OA", year="2026", doi="10.1038/s41467-026-71180-x"),
            output_dir=tmp_path,
            mode="fast",
            budget_seconds=20.0,
        )

        assert result["success"] is True
        assert result["source"] == "nature_html_fulltext"
        assert result["file_path"] is not None
        assert result["file_path"].endswith(".html")
        assert calls == [
            (pdf_url, "bytes=0-16383"),
            (article_url, None),
        ]

    asyncio.run(runner())


def test_pdf_service_download_concurrency_throttles_nature_dominant_fast_batches() -> None:
    articles = [
        ArticleReference(doi="10.1038/s41598-026-45504-2"),
        ArticleReference(doi="10.1038/s42003-026-09928-w"),
        ArticleReference(doi="10.1038/s41467-026-71180-x"),
        ArticleReference(doi="10.1038/s41598-026-44174-4"),
        ArticleReference(doi="10.1007/s44445-026-00156-w"),
    ]

    assert PDFService._download_concurrency_for_articles("fast", articles) == 2


def test_pdf_service_download_concurrency_keeps_default_for_mixed_fast_batches() -> None:
    articles = [
        ArticleReference(doi="10.1000/a"),
        ArticleReference(doi="10.1001/b"),
        ArticleReference(doi="10.1002/c"),
        ArticleReference(doi="10.1038/s41598-026-45504-2"),
        ArticleReference(doi="10.1007/s44445-026-00156-w"),
    ]

    assert PDFService._download_concurrency_for_articles("fast", articles) == 5


def test_pdf_service_downloads_from_pmc_oa_package(tmp_path) -> None:
    async def runner() -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            pdf_bytes = b"%PDF-1.7 package document"
            info = tarfile.TarInfo(name="PMC123/paper.pdf")
            info.size = len(pdf_bytes)
            archive.addfile(info, io.BytesIO(pdf_bytes))
        archive_bytes = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text=(
                        "<OA><records><record>"
                        "<link format='tgz' href='ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC123.tar.gz' />"
                        "</record></records></OA>"
                    ),
                )
            if url == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/ab/cd/PMC123.tar.gz":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/x-gzip"},
                    content=archive_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="PMC OA Article",
                            year="2024",
                            pmc_id="PMC123",
                        )
                    ]
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "pmc_oa_tgz"
        assert result.file_path is not None

    asyncio.run(runner())


def test_pdf_service_fast_mode_short_circuits_with_pmc_preflight(tmp_path) -> None:
    async def runner() -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            pdf_bytes = b"%PDF-1.7 pmc preflight document"
            info = tarfile.TarInfo(name="PMC999/article.pdf")
            info.size = len(pdf_bytes)
            archive.addfile(info, io.BytesIO(pdf_bytes))
        archive_bytes = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text=(
                        "<OA><records><record>"
                        "<link format='tgz' href='ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC999.tar.gz' />"
                        "</record></records></OA>"
                    ),
                )
            if url == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC999.tar.gz":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/x-gzip"},
                    content=archive_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="PMC Preflight Article",
                            year="2024",
                            pmc_id="PMC999",
                            doi="10.1000/preflight",
                        )
                    ],
                    mode="fast",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "pmc_oa_tgz"

    asyncio.run(runner())


def test_pdf_service_fast_mode_uses_europe_pmc_repo_for_pmc_doi_article(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text="<OA><records><record id='PMC4242'></record></records></OA>",
                )
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if "doaj.org/api/search/articles" in url:
                return httpx.Response(200, json={"results": []})
            if "europepmc.org/api/fulltextRepo" in url and "type=METADATA" in url:
                return httpx.Response(
                    200,
                    json={
                        "version": 1,
                        "files": [
                            {
                                "filename": "article.pdf",
                                "mimeType": "application/pdf",
                                "type": "pdf",
                            }
                        ],
                    },
                )
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "europepmc.org/api/fulltextRepo" in url and "type=FILE" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 europe pmc repo document",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="Europe PMC Repo Article",
                            year="2024",
                            pmc_id="PMC4242",
                            doi="10.1000/europepmc",
                        )
                    ],
                    mode="fast",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "europe_pmc_repo_pdf"

    asyncio.run(runner())


def test_pdf_service_fast_mode_skips_doi_landing_page(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://doi.org/10.2000%2Fplos":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=(
                        "<html><head>"
                        "<meta name='citation_pdf_url' content='https://journals.example.org/article/file?id=10.2000/plos&type=printable'>"
                        "</head><body></body></html>"
                    ),
                )
            if url == "https://journals.example.org/article/file?id=10.2000/plos&type=printable":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 printable document",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="Citation PDF URL Article",
                            year="2024",
                            doi="10.2000/plos",
                        )
                    ],
                    mode="fast",
                )
            )

        assert response.success_count == 0
        result = response.results[0]
        assert result.success is False

    asyncio.run(runner())


def test_pdf_service_balanced_mode_uses_citation_pdf_url(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://doi.org/10.2000%2Fplos":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=(
                        "<html><head>"
                        "<meta name='citation_pdf_url' content='https://journals.example.org/article/file?id=10.2000/plos&type=printable'>"
                        "</head><body></body></html>"
                    ),
                )
            if url == "https://journals.example.org/article/file?id=10.2000/plos&type=printable":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 printable document",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._prepare_browser_runtime = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="Citation PDF URL Article",
                            year="2024",
                            doi="10.2000/plos",
                        )
                    ],
                    mode="balanced",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "citation_pdf_url"

    asyncio.run(runner())


def test_pdf_service_uses_unpaywall_before_crossref(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "api.unpaywall.org/v2/" in url:
                return httpx.Response(
                    200,
                    json={
                        "best_oa_location": {
                            "url_for_pdf": "https://repo.example.org/paper.pdf",
                        },
                        "oa_locations": [
                            {"url_for_pdf": "https://repo.example.org/paper.pdf"},
                            {"url_for_pdf": "https://repo.example.org/alt.pdf"},
                        ],
                    },
                )
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if url == "https://doi.org/10.4000%2Funpaywall":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body>No direct pdf here.</body></html>",
                )
            if url == "https://repo.example.org/paper.pdf":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 unpaywall",
                )
            if url == "https://repo.example.org/alt.pdf":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 alt",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(
            download_root=tmp_path,
            unpaywall_email="tester@example.com",
            pdf_downloader_mode="legacy"
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._prepare_browser_runtime = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="Unpaywall Article", year="2024", doi="10.4000/unpaywall")],
                    mode="balanced",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "unpaywall"

    asyncio.run(runner())


def test_pdf_service_collects_europe_pmc_fulltext_urls(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text="<OA><records /></OA>",
                )
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(
                    200,
                    json={
                        "resultList": {
                            "result": [
                                {
                                    "fullTextUrlList": {
                                        "fullTextUrl": [
                                            {
                                                "availability": "Open access",
                                                "documentStyle": "pdf",
                                                "site": "Europe PMC",
                                                "url": "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC123&blobtype=pdf",
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    },
                )
            if url == "https://europepmc.org/articles/PMC123?pdf=render":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 europe pmc render",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            resolved = await service.resolve(
                ArticleReference(title="Europe PMC Article", year="2024", pmc_id="PMC123"),
                mode="balanced",
            )

        urls = [candidate.url for candidate in resolved.candidates if candidate.source == "europe_pmc"]
        assert "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC123&blobtype=pdf" in urls
        assert any(
            candidate.url == "https://europepmc.org/articles/PMC123?pdf=render"
            for candidate in resolved.candidates
        )

    asyncio.run(runner())


def test_pdf_service_accepts_verified_html_fulltext(tmp_path) -> None:
    async def runner() -> None:
        body = " ".join(["Introduction methods results discussion conclusion serotonin receptor signaling"] * 140)
        html = f"<html><body><article><h1>Paper</h1><section>{body}</section></article></body></html>"

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(200, headers={"content-type": "text/xml; charset=utf-8"}, text="<OA><records /></OA>")
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://repo.example.org/fulltext":
                return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=html)
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            async def fake_resolve(_article: ArticleReference, *, mode: str = "balanced") -> PDFResolveResponse:
                return PDFResolveResponse(
                    article=ArticleReference(title="HTML Fulltext", year="2024", doi="10.3000/html"),
                    cache_hit=False,
                    candidates=[PDFCandidate(source="repo_html", url="https://repo.example.org/fulltext")],
                )

            service.resolve = fake_resolve  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(articles=[ArticleReference(title="HTML Fulltext", year="2024", doi="10.3000/html")])
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.content_kind == "html_fulltext"
        assert result.file_path is not None and result.file_path.endswith(".html")

    asyncio.run(runner())


def test_pdf_service_accepts_verified_doi_landing_fulltext(tmp_path) -> None:
    async def runner() -> None:
        long_body = (
            "<html><body><h1>Introduction</h1>"
            + "<p>serotonin " * 600
            + "</p><h2>Methods</h2><p>assay " * 300
            + "</p><h2>Results</h2><p>result " * 300
            + "</p><h2>Discussion</h2><p>discussion " * 300
            + "</p><h2>References</h2><p>ref " * 50
            + "</p></body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://doi.org/10.5555%2Flanding":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=long_body,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._prepare_browser_runtime = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="Landing HTML", year="2024", doi="10.5555/landing")],
                    mode="balanced",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "doi_landing"
        assert result.content_kind == "html_fulltext"

    asyncio.run(runner())


def test_pdf_service_accepts_elsevier_open_archive_html(tmp_path) -> None:
    async def runner() -> None:
        body = " ".join(["Introduction results discussion references serotonin receptor signaling"] * 90)
        html = (
            "<html><head><title>ScienceDirect</title></head><body>"
            "<div>Elsevier ScienceDirect Open Archive Main text View PDF</div>"
            f"<article>{body}</article>"
            "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://doi.org/10.1016%2Fj.example.2024.01.001":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._prepare_browser_runtime = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="Elsevier Landing HTML", year="2024", doi="10.1016/j.example.2024.01.001")],
                    mode="balanced",
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "doi_landing"
        assert result.content_kind == "html_fulltext"

    asyncio.run(runner())


def test_pdf_service_rejects_elsevier_preview_html(tmp_path) -> None:
    async def runner() -> None:
        body = " ".join(["summary abstract snippets serotonin receptor signaling"] * 120)
        html = (
            "<html><head><title>ScienceDirect</title></head><body>"
            "<div>Article preview Access through your organization Purchase PDF</div>"
            f"<article>{body}</article>"
            "</body></html>"
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "api.crossref.org/works/" in url:
                return httpx.Response(200, json={"message": {"link": []}})
            if "api.openalex.org/works" in url:
                return httpx.Response(200, json={"results": []})
            if url == "https://doi.org/10.1016%2Fj.example.2024.01.002":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._prepare_browser_runtime = lambda *_args, **_kwargs: asyncio.sleep(0, result=None)  # type: ignore[method-assign]
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[ArticleReference(title="Elsevier Preview HTML", year="2024", doi="10.1016/j.example.2024.01.002")],
                    mode="balanced",
                )
            )

        assert response.success_count == 0

    asyncio.run(runner())


def test_pdf_service_uses_browser_fallback_when_enabled(tmp_path) -> None:
    async def runner() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "europepmc/webservices/rest/search" in url:
                return httpx.Response(200, json={"resultList": {"result": []}})
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text="<OA><records /></OA>",
                )
            if url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC999/pdf/":
                return httpx.Response(
                    403,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html>blocked</html>",
                )
            if url == "https://europepmc.org/articles/PMC999?pdf=render":
                raise httpx.RemoteProtocolError("Server disconnected")
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            service._browser_fallback_download_sync = lambda article, target_dir, **_: PDFDownloadResult(  # type: ignore[method-assign]
                article=article,
                success=True,
                source="browser_pmc",
                url="https://pmc.ncbi.nlm.nih.gov/articles/PMC999/pdf/test.pdf",
                file_path=str(target_dir / "test.pdf"),
            )
            response = await service.download_articles(
                PDFDownloadRequest(
                    articles=[
                        ArticleReference(
                            title="Browser Fallback Article",
                            year="2024",
                            pmc_id="PMC999",
                        )
                    ],
                    use_browser_fallback=True,
                )
            )

        assert response.success_count == 1
        result = response.results[0]
        assert result.success is True
        assert result.source == "browser_pmc"

    asyncio.run(runner())


def test_pdf_service_probes_candidates_in_parallel(tmp_path) -> None:
    async def runner() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://files.example.org/slow-fail.pdf":
                await asyncio.sleep(0.22)
                return httpx.Response(
                    404,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html>missing</html>",
                )
            if url == "https://files.example.org/fast-success.pdf":
                await asyncio.sleep(0.05)
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"%PDF-1.7 fast success",
                )
            if url == "https://files.example.org/medium-fail.pdf":
                await asyncio.sleep(0.14)
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html>not pdf</html>",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        article = ArticleReference(
            title="Parallel Candidate Article",
            year="2025",
            doi="10.3000/parallel",
        )
        settings = Settings(
            download_root=tmp_path,
            pdf_candidate_download_concurrency=3,
            pdf_downloader_mode="legacy"
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            async def fake_resolve(_article: ArticleReference, *, mode: str = "balanced") -> PDFResolveResponse:
                return PDFResolveResponse(
                    article=article,
                    cache_hit=False,
                    candidates=[
                        PDFCandidate(source="slow", url="https://files.example.org/slow-fail.pdf"),
                        PDFCandidate(source="fast", url="https://files.example.org/fast-success.pdf"),
                        PDFCandidate(source="medium", url="https://files.example.org/medium-fail.pdf"),
                    ],
                )

            service.resolve = fake_resolve  # type: ignore[method-assign]

            start = asyncio.get_running_loop().time()
            response = await service.download_articles(PDFDownloadRequest(articles=[article]))
            elapsed = asyncio.get_running_loop().time() - start

        assert response.success_count == 1
        assert response.results[0].source == "fast"
        assert elapsed < 0.16

    asyncio.run(runner())


def test_pdf_service_builds_browser_targets_for_pmc_only_in_balanced_mode(tmp_path) -> None:
    settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    try:
        service = PDFService(
            http_client=mock_client,
            settings=settings,
            candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
        )
        article = ArticleReference(
            title="Browser Targets",
            year="2025",
            doi="10.1000/example",
            pmc_id="PMC123456",
        )
        targets = service._browser_target_pages(article, mode="balanced")
        assert targets == [("browser_pmc", "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/")]
    finally:
        asyncio.run(mock_client.aclose())


def test_pdf_service_expands_browser_candidates_for_publishers(tmp_path) -> None:
    settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    try:
        service = PDFService(
            http_client=mock_client,
            settings=settings,
            candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
        )

        wiley_article = ArticleReference(doi="10.1111/j.1582-4934.2008.00430.x")
        wiley_candidates = service._expand_browser_pdf_candidates(
            ["https://onlinelibrary.wiley.com/doi/epdf/10.1111/j.1582-4934.2008.00430.x"],
            "https://onlinelibrary.wiley.com/doi/10.1111/j.1582-4934.2008.00430.x",
            wiley_article,
        )
        assert "https://onlinelibrary.wiley.com/doi/pdfdirect/10.1111/j.1582-4934.2008.00430.x" in wiley_candidates
        assert "https://onlinelibrary.wiley.com/doi/pdf/10.1111/j.1582-4934.2008.00430.x" in wiley_candidates

        elsevier_article = ArticleReference(doi="10.1016/j.bioorg.2021.105024")
        elsevier_candidates = service._expand_browser_pdf_candidates(
            [],
            "https://www.sciencedirect.com/science/article/pii/S0045206821004016",
            elsevier_article,
        )
        assert (
            "https://www.sciencedirect.com/science/article/pii/S0045206821004016/pdfft?isDTMRedir=true&download=true"
            in elsevier_candidates
        )
    finally:
        asyncio.run(mock_client.aclose())


def test_pdf_service_quick_availability_marks_pmc_direct_pdf_ready(tmp_path) -> None:
    async def runner() -> None:
        requests: list[str] = []
        archive_buffer = io.BytesIO()
        with tarfile.open(fileobj=archive_buffer, mode="w:gz") as archive:
            pdf_payload = b"%PDF-1.7 pmc oa tgz preview"
            info = tarfile.TarInfo(name="article.pdf")
            info.size = len(pdf_payload)
            archive.addfile(info, io.BytesIO(pdf_payload))
        archive_bytes = archive_buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(str(request.url))
            if "pmc/utils/oa/oa.fcgi" in str(request.url):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text=(
                        "<OA><records><record id='PMC555'>"
                        "<link format='tgz' href='ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC555.tar.gz' />"
                        "</record></records></OA>"
                    ),
                )
            if str(request.url) == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC555.tar.gz":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/x-gzip"},
                    content=archive_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.quick_availability(
                [ArticleReference(title="PMC OA Article", year="2024", pmc_id="PMC555")]
            )

        assert response.items[0].ready is True
        assert response.items[0].source == "pmc_oa_tgz"
        assert requests == [
            "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC555",
            "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC555.tar.gz",
        ]

    asyncio.run(runner())


def test_pdf_service_quick_availability_requires_pdf_signature(tmp_path) -> None:
    async def runner() -> None:
        article = ArticleReference(title="Misleading PDF", year="2024", doi="10.1000/fake")

        async def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://files.example.org/not-really.pdf":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/pdf"},
                    content=b"<html>not actually a pdf</html>",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            async def fake_resolve(_article: ArticleReference, *, mode: str = "fast") -> PDFResolveResponse:
                return PDFResolveResponse(
                    article=article,
                    cache_hit=False,
                    candidates=[PDFCandidate(source="crossref", url="https://files.example.org/not-really.pdf")],
                )

            service.resolve = fake_resolve  # type: ignore[method-assign]
            response = await service.quick_availability([article])

        assert response.items[0].ready is False

    asyncio.run(runner())


def test_pdf_service_quick_availability_marks_tgz_with_pdf_ready(tmp_path) -> None:
    async def runner() -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            image_bytes = b"not-a-pdf" * 1024
            image_info = tarfile.TarInfo(name="PMC777/figure1.jpg")
            image_info.size = len(image_bytes)
            archive.addfile(image_info, io.BytesIO(image_bytes))

            pdf_bytes = b"%PDF-1.7 package document"
            pdf_info = tarfile.TarInfo(name="PMC777/article.pdf")
            pdf_info.size = len(pdf_bytes)
            archive.addfile(pdf_info, io.BytesIO(pdf_bytes))
        archive_bytes = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC777/pdf/":
                return httpx.Response(403, headers={"content-type": "text/html"}, text="<html>blocked</html>")
            if url == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC777.tar.gz":
                return httpx.Response(
                    206,
                    headers={"content-type": "application/x-gzip"},
                    content=archive_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            
            async def fake_resolve(_article: ArticleReference, *, mode: str = "fast") -> PDFResolveResponse:
                return PDFResolveResponse(
                    article=ArticleReference(title="PMC Package Article", year="2024", pmc_id="PMC777"),
                    cache_hit=False,
                    candidates=[
                        PDFCandidate(source="pmc_direct", url="https://pmc.ncbi.nlm.nih.gov/articles/PMC777/pdf/"),
                        PDFCandidate(source="pmc_oa_tgz", url="https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC777.tar.gz"),
                        PDFCandidate(source="openalex", url="https://files.example.org/placeholder"),
                    ],
                )

            service.resolve = fake_resolve  # type: ignore[method-assign]
            response = await service.quick_availability(
                [ArticleReference(title="PMC Package Article", year="2024", pmc_id="PMC777")]
            )

        assert response.items[0].ready is True
        assert response.items[0].source == "pmc_oa_tgz"

    asyncio.run(runner())


def test_pdf_service_quick_availability_rejects_tgz_without_pdf(tmp_path) -> None:
    async def runner() -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            image_bytes = b"image-bytes" * 1024
            image_info = tarfile.TarInfo(name="PMC778/figure1.jpg")
            image_info.size = len(image_bytes)
            archive.addfile(image_info, io.BytesIO(image_bytes))
        archive_bytes = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "pmc/utils/oa/oa.fcgi" in url:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/xml; charset=utf-8"},
                    text=(
                        "<OA><records><record id='PMC778'>"
                        "<link format='tgz' href='ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC778.tar.gz' />"
                        "</record></records></OA>"
                    ),
                )
            if url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC778/pdf/":
                return httpx.Response(403, headers={"content-type": "text/html"}, text="<html>blocked</html>")
            if url == "https://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/aa/bb/PMC778.tar.gz":
                return httpx.Response(
                    206,
                    headers={"content-type": "application/x-gzip"},
                    content=archive_bytes,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )
            response = await service.quick_availability(
                [ArticleReference(title="PMC Image Package", year="2024", pmc_id="PMC778")]
            )

        assert response.items[0].ready is False

    asyncio.run(runner())


def test_pdf_service_quick_availability_accepts_html_fulltext(tmp_path) -> None:
    async def runner() -> None:
        article = ArticleReference(title="HTML Fulltext", year="2024", doi="10.1000/html")
        body = " ".join(["Introduction methods results discussion conclusion references serotonin receptor"] * 140)
        html = f"<html><body><article>{body}</article></body></html>"

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://files.example.org/fulltext":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=html,
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        settings = Settings(download_root=tmp_path, pdf_downloader_mode="legacy")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            service = PDFService(
                http_client=client,
                settings=settings,
                candidate_cache=TTLCache(ttl_seconds=60, max_entries=16),
            )

            async def fake_resolve(_article: ArticleReference, *, mode: str = "fast") -> PDFResolveResponse:
                return PDFResolveResponse(
                    article=article,
                    cache_hit=False,
                    candidates=[PDFCandidate(source="openalex", url="https://files.example.org/fulltext")],
                )

            service.resolve = fake_resolve  # type: ignore[method-assign]
            response = await service.quick_availability([article])

        assert response.items[0].ready is True
        assert response.items[0].source == "openalex"

    asyncio.run(runner())
