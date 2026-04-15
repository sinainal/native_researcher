"""API tests."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.schemas.article import Article, ArticleReference
from app.schemas.helper import HelperChatResponse
from app.schemas.pdf import (
    PDFAvailabilityResponse,
    PDFCandidate,
    PDFDownloadResponse,
    PDFDownloadResult,
    PDFResolveResponse,
)
from app.schemas.pdf import PDFTestResult
from app.schemas.llm import LLMBatchReport, LLMProcessResponse
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.utils.pubmed_xml import parse_pubmed_fetch_xml


class FakePubMedService:
    async def search(self, request):  # noqa: ANN001
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=request.query,
                total_results_found=1,
                fetched_results=1,
                batch_size_used=50,
                request_count=3,
                elapsed_ms=15,
                cache_hit=False,
            ),
            articles=[
                Article(
                    id=1,
                    pmid="123",
                    title="Test article",
                    abstract="A short abstract.",
                    year="2024",
                    journal="Test Journal",
                    publication_date="2024 Jan",
                    article_type="Review",
                    article_types=["Review", "Journal Article"],
                    citation_count=42,
                    authors=["Jane Doe", "John Roe"],
                    keywords=["ndm", "inhibitor"],
                    mesh_terms=["beta-Lactamases", "Drug Inhibitors"],
                    related_articles=["456", "789"],
                    reference_count=12,
                    doi="10.1000/test",
                    pmc_id="PMC123",
                )
            ],
        )


class FakePDFService:
    async def resolve(self, article, *, downloader_mode=None):  # noqa: ANN001
        _ = downloader_mode
        return PDFResolveResponse(
            article=article,
            candidates=[PDFCandidate(source="crossref", url="https://example.org/test.pdf")],
            cache_hit=False,
        )

    async def quick_availability(self, articles):  # noqa: ANN001
        return PDFAvailabilityResponse(
            items=[
                {
                    "article": article,
                    "ready": True,
                    "source": "crossref",
                    "candidate_count": 1,
                    "detail": "verified",
                }
                for article in articles
            ]
        )

    async def download_articles(self, payload):  # noqa: ANN001
        article = payload.articles[0]
        return PDFDownloadResponse(
            total=1,
            success_count=1,
            failed_count=0,
            results=[
                PDFDownloadResult(
                    article=article,
                    success=True,
                    source="crossref",
                    url="https://example.org/test.pdf",
                    file_path="/tmp/test.pdf",
                    candidate_count=1,
                )
            ],
        )

    async def diagnose_articles(  # noqa: ANN001
        self,
        articles,
        *,
        download_dir=None,
        save_files=True,
        downloader_mode=None,
    ):
        _ = download_dir, downloader_mode
        article = articles[0]
        return [
            PDFTestResult(
                article=article,
                success=True,
                reason="downloadable",
                source="crossref",
                url="https://example.org/test.pdf",
                file_path="/tmp/test.pdf" if save_files else None,
                candidate_count=1,
                attempts=[],
            )
        ]


class FakeHelperService:
    async def chat(self, payload):  # noqa: ANN001
        return HelperChatResponse(
            thread_id=payload.thread_id or "thread_test",
            answer="Makale 1 review tipindedir.",
            model="gemini-2.5-flash-lite",
            used_article_ids=[1],
            history_size=2,
        )

    def reset(self, thread_id):  # noqa: ANN001
        return None


class FakeBatchLLMService:
    async def process(self, payload):  # noqa: ANN001
        return LLMProcessResponse(
            model="gemini-3.1-flash-lite-preview",
            analysis_mode=payload.analysis_mode,
            article_scope="selected" if payload.selected_ids else "all",
            article_count=len(payload.articles),
            batch_count=1,
            processed_count=len(payload.articles),
            merged_count=len(payload.articles),
            top_article_ids=[item.id for item in payload.articles[:5]],
            aggregate_summary={"top_candidates_count": min(5, len(payload.articles))},
            logs=["Batch 1 tamamlandi."],
            errors=[],
            batches=[
                LLMBatchReport(
                    batch_number=1,
                    article_ids=[item.id for item in payload.articles],
                    article_count=len(payload.articles),
                    estimated_input_tokens=120,
                    attempts=1,
                    output_count=len(payload.articles),
                )
            ],
            processed_articles=[
                {
                    **item.model_dump(),
                    "summary": "Kisa ozet",
                }
                for item in payload.articles
            ],
        )


def test_api_endpoints() -> None:
    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = Settings(
                download_root=temp_root / "downloads",
                workspace_root=temp_root / "workspace",
                helper_log_path=temp_root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=temp_root / "logs" / "app_events.jsonl",
                assistant_api_key_path=temp_root / "assistant_api_key.txt",
                ncbi_api_key_path=temp_root / "ncbi_api",
                unpaywall_email_path=temp_root / "unpaywall_email",
                openalex_api_key_path=temp_root / "openalex_api_key",
                pubmed_oa_only_path=temp_root / "pubmed_oa_only",
                ai_primary_search_resource_path=temp_root / "ai_primary_search_resource",
                pdf_downloader_mode_path=temp_root / "pdf_downloader_mode",
            )
            app = create_app(
                settings=settings,
                pubmed_service=FakePubMedService(),
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                root = await client.get("/")
                assert root.status_code == 200
                assert "Recent projects" in root.text
                assert 'id="projectList"' in root.text

                landing = await client.get("/landing")
                assert landing.status_code == 200
                assert "Recent projects" in landing.text

                native = await client.get("/native_researcher")
                assert native.status_code == 200
                assert "Native Researcher" in native.text
                assert "Searcher AI" in native.text
                assert "Article Results" in native.text
                assert "Always OA Search" in native.text

                legacy = await client.get("/researcher_2")
                assert legacy.status_code == 200
                assert "Researcher_2" in legacy.text
                assert "Researcher AI" in legacy.text

                styles_path = Path(__file__).resolve().parents[1] / "app" / "web" / "styles.css"
                styles_text = styles_path.read_text(encoding="utf-8")
                assert "landing-body" in styles_text
                assert "flex: 1 1 auto;" in styles_text
                assert "overflow: auto;" in styles_text

                favicon = await client.get("/favicon.ico")
                assert favicon.status_code == 204

                health = await client.get("/health")
                assert health.status_code == 200
                assert health.json() == {"status": "ok"}

                bootstrap = await client.get("/app/bootstrap")
                assert bootstrap.status_code == 200
                assert bootstrap.json() == {
                    "api_key": "",
                    "ncbi_api_key": "",
                    "unpaywall_email": "",
                    "openalex_api_key": "",
                    "pubmed_oa_only": True,
                    "pdf_downloader_mode": "pdf_xml",
                }

                api_keys = await client.get("/app/api-keys")
                assert api_keys.status_code == 200
                assert api_keys.json() == {
                    "assistant_api_key": "",
                    "ncbi_api_key": "",
                    "unpaywall_email": "",
                    "openalex_api_key": "",
                    "pubmed_oa_only": True,
                    "ai_primary_search_resource": "pubmed",
                    "pdf_downloader_mode": "pdf_xml",
                }

                update_api_keys = await client.put(
                    "/app/api-keys",
                    json={
                        "assistant_api_key": "assistant-secret",
                        "ncbi_api_key": "ncbi-secret",
                        "unpaywall_email": "me@example.com",
                        "openalex_api_key": "openalex-secret",
                        "pubmed_oa_only": False,
                        "ai_primary_search_resource": "pubmed",
                        "pdf_downloader_mode": "article_downloader",
                    },
                )
                assert update_api_keys.status_code == 200
                assert update_api_keys.json() == {
                    "assistant_api_key": "assistant-secret",
                    "ncbi_api_key": "ncbi-secret",
                    "unpaywall_email": "me@example.com",
                    "openalex_api_key": "openalex-secret",
                    "pubmed_oa_only": False,
                    "ai_primary_search_resource": "pubmed",
                    "pdf_downloader_mode": "pdf_xml",
                }

                update_hybrid_mode = await client.put(
                    "/app/api-keys",
                    json={
                        "assistant_api_key": "assistant-secret",
                        "ncbi_api_key": "ncbi-secret",
                        "unpaywall_email": "me@example.com",
                        "openalex_api_key": "openalex-secret",
                        "pubmed_oa_only": False,
                        "ai_primary_search_resource": "pubmed",
                        "pdf_downloader_mode": "hybrid",
                    },
                )
                assert update_hybrid_mode.status_code == 200
                assert update_hybrid_mode.json()["pdf_downloader_mode"] == "pdf_xml"

                projects = await client.get("/app/projects")
                assert projects.status_code == 200
                assert projects.json() == {"projects": []}

                create_project = await client.post(
                    "/app/projects",
                    json={"name": "Neuro Evidence Map", "description": "Phase 1 workspace"},
                )
                assert create_project.status_code == 200
                assert create_project.json()["id"] == "neuro-evidence-map"
                assert create_project.json()["pdf_count"] == 0

                create_default_project = await client.post("/app/projects", json={})
                assert create_default_project.status_code == 200
                assert create_default_project.json()["id"] == "project-1"
                assert create_default_project.json()["name"] == "Project 1"

                create_second_default_project = await client.post("/app/projects", json={})
                assert create_second_default_project.status_code == 200
                assert create_second_default_project.json()["id"] == "project-2"
                assert create_second_default_project.json()["name"] == "Project 2"

                workspace_db = settings.workspace_root / ".native_researcher.db"
                assert workspace_db.exists()

                legacy_dir = settings.workspace_root / "projects" / "legacy-review"
                legacy_dir.mkdir(parents=True, exist_ok=True)
                for relative in ("pdfs", "derived", "indexes", "exports", "notes"):
                    (legacy_dir / relative).mkdir(parents=True, exist_ok=True)
                (legacy_dir / "project.json").write_text(
                    json.dumps(
                        {
                            "id": "legacy-review",
                            "name": "Legacy Review",
                            "description": "Imported from disk",
                            "created_at": "2026-03-20T10:00:00+00:00",
                            "updated_at": "2026-03-20T10:00:00+00:00",
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                (legacy_dir / "state.json").write_text(
                    json.dumps(
                        {
                            "active_query_id": "legacy_q",
                            "selected_ids": [],
                            "detail_article_id": None,
                            "sidebar_panel": "queries",
                            "query_detail_id": "legacy_q",
                            "query_history": [
                                {
                                    "id": "legacy_q",
                                    "title": "legacy serotonin",
                                    "created_at": "2026-03-20T10:00:00+00:00",
                                    "updated_at": "2026-03-20T10:00:00+00:00",
                                    "search_payload": {
                                        "query": "legacy serotonin",
                                        "year_start": None,
                                        "year_end": None,
                                        "max_results": 5,
                                        "batch_size": None,
                                        "min_cite": None,
                                        "article_type": None,
                                        "use_cache": True,
                                    },
                                    "meta": None,
                                    "articles": [],
                                }
                            ],
                        },
                        ensure_ascii=True,
                        indent=2,
                    ),
                    encoding="utf-8",
                )

                project_pdf_dir = settings.workspace_root / "projects" / "project-1" / "pdfs" / "year_2025"
                project_pdf_dir.mkdir(parents=True, exist_ok=True)
                sample_pdf = project_pdf_dir / "sample-paper.pdf"
                sample_pdf.write_bytes(b"%PDF-1.4\n%test\n")
                sample_xml = project_pdf_dir / "sample-paper.xml"
                sample_xml.write_text("<article><body>xml</body></article>", encoding="utf-8")
                xml_only = project_pdf_dir / "xml-only-study.xml"
                xml_only.write_text("<article><body>xml</body></article>", encoding="utf-8")

                projects = await client.get("/app/projects")
                assert projects.status_code == 200
                assert len(projects.json()["projects"]) == 4
                assert {item["name"] for item in projects.json()["projects"]} == {
                    "Neuro Evidence Map",
                    "Project 1",
                    "Project 2",
                    "Legacy Review",
                }

                legacy_state = await client.get("/app/projects/legacy-review/state")
                assert legacy_state.status_code == 200
                assert legacy_state.json()["active_query_id"] == "legacy_q"
                assert legacy_state.json()["query_history"][0]["title"] == "legacy serotonin"

                project = await client.get("/app/projects/project-1")
                assert project.status_code == 200
                assert project.json()["name"] == "Project 1"

                project_downloads = await client.get("/app/projects/project-1/downloads")
                assert project_downloads.status_code == 200
                download_items = project_downloads.json()["items"]
                assert len(download_items) == 2
                combined_item = next(item for item in download_items if item["path"].endswith("sample-paper.pdf"))
                assert "sample" in combined_item["name"]
                assert combined_item["path"].endswith("sample-paper.pdf")
                assert combined_item["artifact_types"] == ["pdf", "xml"]
                xml_item = next(item for item in download_items if item["path"].endswith("xml-only-study.xml"))
                assert "xml" in xml_item["name"]
                assert xml_item["path"].endswith("xml-only-study.xml")
                assert xml_item["artifact_types"] == ["xml"]
                assert project.json()["pdf_count"] == 1

                project_state = await client.get("/app/projects/project-1/state")
                assert project_state.status_code == 200
                assert project_state.json()["query_history"] == []

                saved_state = await client.put(
                    "/app/projects/project-1/state",
                    json={
                        "active_query_id": "qry_1",
                        "selected_ids": [1],
                        "detail_article_id": 1,
                        "sidebar_panel": "queries",
                        "query_detail_id": "qry_1",
                        "downloadability_cache": {
                            "123": {
                                "status": "high",
                                "label": "Ready",
                                "detail": "Fast verification confirmed a downloadable PDF.",
                                "openUrl": None,
                            }
                        },
                        "current_session_id": "chat_1",
                        "assistant_sessions": [
                            {
                                "id": "chat_1",
                                "threadId": "thread_123",
                                "title": "NDM summary",
                                "preview": "Summarise NDM inhibitor evidence",
                                "updatedAt": "2026-03-27T12:00:00+00:00",
                                "messages": [
                                    {
                                        "id": "msg_1",
                                        "role": "user",
                                        "text": "Summarise NDM inhibitor evidence",
                                        "pending": False,
                                        "thinking": "",
                                        "thinkingEnabled": False,
                                        "meta": "",
                                        "actions": [],
                                    }
                                ],
                            }
                        ],
                        "query_history": [
                            {
                                "id": "qry_1",
                                "title": "ndm inhibitor",
                                "created_at": "2026-03-27T12:00:00+00:00",
                                "updated_at": "2026-03-27T12:00:00+00:00",
                                "search_payload": {
                                    "query": "ndm inhibitor",
                                    "year_start": None,
                                    "year_end": None,
                                    "max_results": 1,
                                    "batch_size": None,
                                    "min_cite": None,
                                    "article_type": None,
                                    "use_cache": True,
                                },
                                "meta": {
                                    "full_query": "ndm inhibitor",
                                    "total_results_found": 1,
                                    "fetched_results": 1,
                                    "batch_size_used": 50,
                                    "request_count": 3,
                                    "elapsed_ms": 15,
                                    "cache_hit": False,
                                },
                                "articles": [
                                    {
                                        "id": 1,
                                        "pmid": "123",
                                        "title": "Test article",
                                        "abstract": "A short abstract.",
                                        "year": "2024",
                                        "journal": "Test Journal",
                                        "publication_date": "2024 Jan",
                                        "article_type": "Review",
                                        "article_types": ["Review", "Journal Article"],
                                        "citation_count": 42,
                                        "authors": ["Jane Doe", "John Roe"],
                                        "keywords": ["ndm", "inhibitor"],
                                        "mesh_terms": ["beta-Lactamases", "Drug Inhibitors"],
                                        "related_articles": ["456", "789"],
                                        "reference_count": 12,
                                        "doi": "10.1000/test",
                                        "pmc_id": "PMC123",
                                    }
                                ],
                            }
                        ],
                    },
                )
                assert saved_state.status_code == 200
                assert saved_state.json()["active_query_id"] == "qry_1"
                assert saved_state.json()["query_history"][0]["title"] == "ndm inhibitor"
                assert saved_state.json()["current_session_id"] == "chat_1"
                assert saved_state.json()["assistant_sessions"][0]["threadId"] == "thread_123"
                assert saved_state.json()["downloadability_cache"]["123"]["status"] == "high"

                with sqlite3.connect(workspace_db) as conn:
                    assert conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 4
                    assert conn.execute(
                        "SELECT COUNT(*) FROM project_queries WHERE project_id = ?",
                        ("project-1",),
                    ).fetchone()[0] == 1
                    assert conn.execute(
                        "SELECT COUNT(*) FROM project_documents WHERE project_id = ?",
                        ("project-1",),
                    ).fetchone()[0] == 3

                touched_project = await client.post("/app/projects/project-1/touch")
                assert touched_project.status_code == 200
                assert touched_project.json()["id"] == "project-1"

                renamed_project = await client.patch(
                    "/app/projects/project-1",
                    json={"name": "Docking Review"},
                )
                assert renamed_project.status_code == 200
                assert renamed_project.json()["name"] == "Docking Review"

                project_list_after_rename = await client.get("/app/projects")
                assert project_list_after_rename.status_code == 200
                assert any(
                    item["name"] == "Docking Review"
                    for item in project_list_after_rename.json()["projects"]
                )

                deleted_project = await client.delete("/app/projects/project-2")
                assert deleted_project.status_code == 200
                assert deleted_project.json()["id"] == "project-2"
                assert not (settings.workspace_root / "projects" / "project-2").exists()

                projects_after_delete = await client.get("/app/projects")
                assert projects_after_delete.status_code == 200
                assert all(
                    item["id"] != "project-2"
                    for item in projects_after_delete.json()["projects"]
                )

                with sqlite3.connect(workspace_db) as conn:
                    assert conn.execute(
                        "SELECT COUNT(*) FROM projects WHERE id = ?",
                        ("project-2",),
                    ).fetchone()[0] == 0

                app_event = await client.post(
                    "/app/events",
                    json={"level": "error", "event": "ui_error", "message": "Test event"},
                )
                assert app_event.status_code == 200
                assert app_event.json() == {"ok": True}
                assert settings.app_event_log_path.exists()
                assert "ui_error" in settings.app_event_log_path.read_text(encoding="utf-8")

                search = await client.post("/pubmed/search", json={"query": "ndm inhibitor", "max_results": 1})
                assert search.status_code == 200
                assert search.json()["articles"][0]["pmid"] == "123"

                helper = await client.post(
                    "/assistant/chat",
                    json={
                        "api_key": "test_api_key_1234567890",
                        "message": "Bu makale nedir?",
                        "articles": [{"id": 1, "title": "Test article", "mesh_terms": ["beta-Lactamases"]}],
                    },
                )
                assert helper.status_code == 200
                assert helper.json()["used_article_ids"] == [1]

                llm = await client.post(
                    "/llm/process",
                    json={
                        "api_key": "test_api_key_1234567890",
                        "prompt": "Ozetle",
                        "articles": [{"id": 1, "title": "Test article", "abstract": "A short abstract."}],
                    },
                )
                assert llm.status_code == 200
                assert llm.json()["processed_count"] == 1

                resolve = await client.post(
                    "/pdf/resolve",
                    json={"title": "Test article", "doi": "10.1000/test"},
                )
                assert resolve.status_code == 200
                assert resolve.json()["candidates"][0]["source"] == "crossref"

                availability = await client.post(
                    "/pdf/availability/fast",
                    json={"articles": [{"title": "Test article", "doi": "10.1000/test"}]},
                )
                assert availability.status_code == 200
                assert availability.json()["items"][0]["ready"] is True

                download = await client.post(
                    "/pdf/download",
                    json={"articles": [{"title": "Test article", "doi": "10.1000/test"}]},
                )
                assert download.status_code == 200
                assert download.json()["success_count"] == 1

                pdf_test = await client.post(
                    "/pdf/test",
                    json={"query": "ndm inhibitor", "max_results": 1, "save_files": False},
                )
                assert pdf_test.status_code == 200
                assert pdf_test.json()["success_count"] == 1

                grouped_project = await client.post(
                    "/app/projects",
                    json={"name": "Grouped Downloads"},
                )
                assert grouped_project.status_code == 200
                grouped_project_payload = grouped_project.json()
                grouped_project_id = grouped_project_payload["id"]
                grouped_project_dir = Path(grouped_project_payload["project_path"])
                grouped_pdf_dir = grouped_project_dir / "pdfs" / "year_2024"
                grouped_pdf_dir.mkdir(parents=True, exist_ok=True)

                article_one_pdf = grouped_pdf_dir / "Docking_Study_article_oa_pdf.pdf"
                article_two_pdf = grouped_pdf_dir / "Shared_Therapy_article_oa_pdf.pdf"
                article_two_xml = grouped_pdf_dir / "Shared_Therapy_pmc_efetch_xml.xml"
                article_three_xml = grouped_pdf_dir / "OpenAlex_Results_europe_pmc_repo_xml.xml"
                article_one_pdf.write_bytes(b"%PDF-1.4\n% article one")
                article_two_pdf.write_bytes(b"%PDF-1.4\n% article two pdf")
                article_two_xml.write_text("<article><body><p>Article two xml</p></body></article>", encoding="utf-8")
                article_three_xml.write_text("<article><body><p>Article three xml</p></body></article>", encoding="utf-8")

                grouped_state = await client.put(
                    f"/app/projects/{grouped_project_id}/state",
                    json={
                        "active_query_id": "query_docking",
                        "selected_ids": [],
                        "detail_article_id": None,
                        "sidebar_panel": "downloads",
                        "query_detail_id": None,
                        "downloadability_cache": {
                            "1001": {
                                "status": "downloaded",
                                "label": "Downloaded",
                                "detail": "Ready to open.",
                                "openUrl": f"/pdf/file?path={article_one_pdf}",
                            },
                            "1002": {
                                "status": "downloaded",
                                "label": "Downloaded",
                                "detail": "Ready to open.",
                                "openUrl": f"/pdf/file?path={article_two_pdf}",
                            },
                            "1003": {
                                "status": "downloaded",
                                "label": "Downloaded",
                                "detail": "Ready to open.",
                                "openUrl": f"/pdf/file?path={article_three_xml}",
                            },
                        },
                        "query_history": [
                            {
                                "id": "query_docking",
                                "title": "Docking query",
                                "created_at": "2026-04-15T10:00:00+03:00",
                                "updated_at": "2026-04-15T10:01:00+03:00",
                                "search_payload": {
                                    "query": "docking inhibitors",
                                    "year_start": 2020,
                                    "year_end": 2026,
                                    "max_results": 10,
                                    "batch_size": 10,
                                    "min_cite": None,
                                    "article_type": None,
                                    "use_cache": True,
                                },
                                "meta": None,
                                "articles": [
                                    {
                                        "id": 1001,
                                        "pmid": "1001",
                                        "title": "Docking study alpha",
                                        "abstract": "",
                                        "year": "2024",
                                        "journal": "Test Journal",
                                        "publication_date": "2024 Jan",
                                        "article_type": "article",
                                        "article_types": [],
                                        "citation_count": 0,
                                        "authors": [],
                                        "keywords": [],
                                        "mesh_terms": [],
                                        "related_articles": [],
                                        "reference_count": 0,
                                        "doi": "10.1000/alpha",
                                        "pmc_id": "PMC1001",
                                    },
                                    {
                                        "id": 1002,
                                        "pmid": "1002",
                                        "title": "Shared therapy beta",
                                        "abstract": "",
                                        "year": "2024",
                                        "journal": "Test Journal",
                                        "publication_date": "2024 Feb",
                                        "article_type": "article",
                                        "article_types": [],
                                        "citation_count": 0,
                                        "authors": [],
                                        "keywords": [],
                                        "mesh_terms": [],
                                        "related_articles": [],
                                        "reference_count": 0,
                                        "doi": "10.1000/beta",
                                        "pmc_id": "PMC1002",
                                    },
                                ],
                            },
                            {
                                "id": "query_openalex",
                                "title": "OpenAlex query",
                                "created_at": "2026-04-15T10:02:00+03:00",
                                "updated_at": "2026-04-15T10:03:00+03:00",
                                "search_payload": {
                                    "query": "openalex xml extraction",
                                    "year_start": 2020,
                                    "year_end": 2026,
                                    "max_results": 10,
                                    "batch_size": 10,
                                    "min_cite": None,
                                    "article_type": None,
                                    "use_cache": True,
                                },
                                "meta": None,
                                "articles": [
                                    {
                                        "id": 1002,
                                        "pmid": "1002",
                                        "title": "Shared therapy beta",
                                        "abstract": "",
                                        "year": "2024",
                                        "journal": "Test Journal",
                                        "publication_date": "2024 Feb",
                                        "article_type": "article",
                                        "article_types": [],
                                        "citation_count": 0,
                                        "authors": [],
                                        "keywords": [],
                                        "mesh_terms": [],
                                        "related_articles": [],
                                        "reference_count": 0,
                                        "doi": "10.1000/beta",
                                        "pmc_id": "PMC1002",
                                    },
                                    {
                                        "id": 1003,
                                        "pmid": "1003",
                                        "title": "OpenAlex result gamma",
                                        "abstract": "",
                                        "year": "2024",
                                        "journal": "Test Journal",
                                        "publication_date": "2024 Mar",
                                        "article_type": "article",
                                        "article_types": [],
                                        "citation_count": 0,
                                        "authors": [],
                                        "keywords": [],
                                        "mesh_terms": [],
                                        "related_articles": [],
                                        "reference_count": 0,
                                        "doi": "10.1000/gamma",
                                        "pmc_id": "PMC1003",
                                    },
                                ],
                            },
                        ],
                    },
                )
                assert grouped_state.status_code == 200

                grouped_downloads = await client.get(f"/app/projects/{grouped_project_id}/downloads")
                assert grouped_downloads.status_code == 200
                grouped_payload = grouped_downloads.json()
                assert {group["title"] for group in grouped_payload["groups"]} == {"Docking query", "OpenAlex query"}
                docking_group = next(group for group in grouped_payload["groups"] if group["title"] == "Docking query")
                openalex_group = next(group for group in grouped_payload["groups"] if group["title"] == "OpenAlex query")
                assert docking_group["item_count"] == 2
                assert openalex_group["item_count"] == 2
                assert len(grouped_payload["items"]) == 3
                shared_item = next(item for item in grouped_payload["items"] if item["name"] == "Shared therapy beta")
                assert shared_item["path"].endswith("Shared_Therapy_article_oa_pdf.pdf")
                assert shared_item["artifact_types"] == ["pdf", "xml"]
                assert sorted(shared_item["query_titles"]) == ["Docking query", "OpenAlex query"]

    asyncio.run(runner())


def test_pubmed_parser_uses_primary_article_ids() -> None:
    xml_text = """
    <PubmedArticleSet>
      <PubmedArticle>
        <MedlineCitation>
          <PMID>12345</PMID>
          <Article>
            <Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue><Title>Test</Title></Journal>
            <ArticleTitle>Parser check</ArticleTitle>
          </Article>
        </MedlineCitation>
        <PubmedData>
          <ArticleIdList>
            <ArticleId IdType="pubmed">12345</ArticleId>
            <ArticleId IdType="pmc">PMC999</ArticleId>
            <ArticleId IdType="doi">10.1000/right</ArticleId>
          </ArticleIdList>
          <ReferenceList>
            <Reference>
              <ArticleIdList>
                <ArticleId IdType="pmc">PMCWRONG</ArticleId>
                <ArticleId IdType="doi">10.1000/wrong</ArticleId>
              </ArticleIdList>
            </Reference>
          </ReferenceList>
        </PubmedData>
      </PubmedArticle>
    </PubmedArticleSet>
    """
    parsed = parse_pubmed_fetch_xml(xml_text)
    assert parsed["12345"]["doi"] == "10.1000/right"
    assert parsed["12345"]["pmc_id"] == "PMC999"
