"""API tests."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.schemas.article import Article, ArticleReference
from app.schemas.helper import HelperChatResponse
from app.schemas.pdf import PDFCandidate, PDFDownloadResponse, PDFDownloadResult, PDFResolveResponse
from app.schemas.pdf import PDFTestResult
from app.schemas.llm import LLMBatchReport, LLMProcessResponse
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse


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
    async def resolve(self, article, *, mode="balanced"):  # noqa: ANN001
        return PDFResolveResponse(
            article=article,
            candidates=[PDFCandidate(source="crossref", url="https://example.org/test.pdf")],
            cache_hit=False,
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
        mode="balanced",
        use_browser_fallback=False,
    ):
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
                assert "Choose a project workspace" in root.text
                assert "Create project" in root.text
                assert "Legacy console" in root.text

                landing = await client.get("/landing")
                assert landing.status_code == 200
                assert "Workspace launcher" in landing.text

                native = await client.get("/native_researcher")
                assert native.status_code == 200
                assert "Native Researcher" in native.text
                assert "Searcher AI" in native.text
                assert "Article Results" in native.text

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

                projects = await client.get("/app/projects")
                assert projects.status_code == 200
                assert len(projects.json()["projects"]) == 1
                assert projects.json()["projects"][0]["name"] == "Neuro Evidence Map"

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

    asyncio.run(runner())
