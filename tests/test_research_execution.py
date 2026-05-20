"""Research plan execution tests."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.schemas.article import Article
from app.schemas.helper import HelperChatResponse
from app.schemas.llm import LLMProcessResponse
from app.schemas.pdf import PDFAvailabilityResponse, PDFResolveResponse
from app.schemas.pdf import PDFDownloadResponse, PDFDownloadResult
from app.schemas.pdf_extraction import PDFExtractionRequest
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.schemas.research_execution import ResearchPlanExecuteRequest, ResearchScreeningTrace
from app.services.pdf_extraction_service import PDFExtractionService
from app.services.research_pdf_pipeline_service import research_plan_questions
from app.services.research_execution_service import ResearchExecutionService
from app.services.research_plan_payload_service import build_execution_plan
from app.services.research_screening_service import ResearchScreeningService


class FakePubMedService:
    def __init__(self) -> None:
        self.calls = []

    async def search(self, request):  # noqa: ANN001
        self.calls.append(request)
        source = request.preferred_source
        if source == "pubmed":
            articles = [
                Article(
                    id=1,
                    source_name=source,
                    source_record_id="pubmed-1",
                    pmid="111",
                    title="Binding pocket residues in receptor alpha",
                    abstract="Mutagenesis identifies binding pocket residues and ligand interaction sites.",
                    year="2021",
                    doi="10.1000/shared",
                )
            ]
        elif source == "openalex":
            articles = [
                Article(
                    id=1,
                    source_name=source,
                    source_record_id="openalex-1",
                    pmid="",
                    title="Binding pocket residues in receptor alpha",
                    abstract="Mutagenesis identifies binding pocket residues and ligand interaction sites.",
                    year="2021",
                    doi="10.1000/shared",
                ),
                Article(
                    id=2,
                    source_name=source,
                    source_record_id="openalex-2",
                    pmid="",
                    title="Review without residue data",
                    abstract="This review does not report direct experimental residue evidence.",
                    year="2020",
                    doi="10.1000/review",
                    article_type="Review",
                ),
            ]
        else:
            articles = []
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query=request.query,
                total_results_found=len(articles),
                fetched_results=len(articles),
                batch_size_used=request.max_results,
                request_count=1,
                elapsed_ms=5,
                cache_hit=False,
                primary_source=source,
                sources_used=[source],
            ),
            articles=articles,
            )


def _sse_events(text: str) -> list[dict]:
    events = []
    for block in text.split("\n\n"):
        lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if lines:
            import json

            events.append(json.loads("\n".join(lines)))
    return events


def test_research_execution_plan_payload_disables_criteria_without_mutating_source() -> None:
    original_plan = {
        "topic": "criteria off",
        "screening_criteria": [{"id": "topic_match"}],
        "exclusion_criteria": ["review"],
    }
    request = ResearchPlanExecuteRequest(
        plan=original_plan,
        criteria_enabled=False,
        screening_model="ollama:screen",
        pdf_extractor_enabled=True,
        pdf_scope="selected_backup",
        full_text_model=None,
    )

    plan = build_execution_plan(request)

    assert plan["criteria_mode"] == "disabled"
    assert plan["screening_criteria"] == []
    assert plan["exclusion_criteria"] == []
    assert plan["full_text_settings"]["full_text_model"] == "ollama:screen"
    assert original_plan["screening_criteria"] == [{"id": "topic_match"}]


def test_research_pdf_pipeline_prefers_structured_question_specs() -> None:
    plan = {
        "extraction_questions": ["fallback question"],
        "extraction_question_specs": [
            {"id": "q1", "question": "Which residue is reported?", "answer_format": "exact_text"}
        ],
    }

    assert research_plan_questions(plan) == ["Which residue is reported?"]


class FakePDFService:
    async def resolve(self, article, *, downloader_mode=None):  # noqa: ANN001
        _ = article, downloader_mode
        return PDFResolveResponse(article=article, candidates=[], cache_hit=False)

    async def quick_availability(self, articles):  # noqa: ANN001
        return PDFAvailabilityResponse(items=[])

    async def download_articles(self, payload):  # noqa: ANN001
        return PDFDownloadResponse(total=0, success_count=0, failed_count=0, results=[])


class FakeHelperService:
    async def chat(self, payload):  # noqa: ANN001
        return HelperChatResponse(
            thread_id=payload.thread_id or "thread",
            answer="ok",
            model="test",
            used_article_ids=[],
            history_size=0,
        )

    def reset(self, thread_id):  # noqa: ANN001
        _ = thread_id


class FakeBatchLLMService:
    async def process(self, payload):  # noqa: ANN001
        return LLMProcessResponse(
            model="test",
            analysis_mode=payload.analysis_mode,
            article_scope="all",
            article_count=0,
            batch_count=0,
            processed_count=0,
            merged_count=0,
            top_article_ids=[],
            aggregate_summary={},
            logs=[],
            errors=[],
            batches=[],
            processed_articles=[],
        )


class FakeScreeningService:
    async def screen_candidates(self, candidates, plan, **kwargs):  # noqa: ANN001
        _ = plan, kwargs
        traces = []
        for candidate in candidates:
            score = 1.0 if candidate.article.doi == "10.1000/shared" else 0.0
            traces.append(
                ResearchScreeningTrace(
                    candidate_id=candidate.candidate_id,
                    criterion_scores={"must_have": score, "nice_to_have": 1.0},
                    exclusion_scores={},
                    final_score=score,
                    excluded=False,
                    matched_branch_ids=[match.branch_id for match in candidate.matches if match.branch_id],
                    evidence=["fake screening"],
                    rationale="fake",
                )
            )
        return traces


def test_research_execution_enforces_required_screening_criteria() -> None:
    async def runner() -> None:
        service = ResearchExecutionService(
            pubmed_service=FakePubMedService(),
            screening_service=FakeScreeningService(),
        )
        response = await service.execute_plan_with_screening(
            {
                "topic": "required criteria",
                "target_count_per_branch": 2,
                "active_databases": ["PubMed", "OpenAlex"],
                "candidate_budget": {"per_database": 2},
                "search_branches": [{"id": "alpha", "label": "Alpha", "query": "alpha"}],
                "screening_criteria": [
                    {"id": "must_have", "label": "Must have", "required": True},
                    {"id": "nice_to_have", "label": "Nice to have", "required": False},
                ],
                "exclusion_criteria": [],
            }
        )
        selected_ids = response.run_trace.selected_candidate_ids
        excluded_ids = response.run_trace.excluded_candidate_ids
        assert selected_ids == ["cand_1"]
        assert "cand_2" in excluded_ids

    asyncio.run(runner())


def test_screening_agent_maps_label_scores_to_criterion_ids() -> None:
    async def runner() -> None:
        service = ResearchScreeningService()
        candidates = []
        article = Article(id=1, pmid="", title="Alpha residue interaction", abstract="Residue interaction evidence.")
        from app.services.research_candidate_normalizer import NormalizedResearchCandidate

        candidates.append(NormalizedResearchCandidate(candidate_id="cand_1", article=article))
        traces = service._normalize_agent_items(
            candidates,
            {
                "screening_criteria": [
                    {"id": "residue_evidence", "label": "Residue Evidence", "description": "Residue evidence"}
                ],
                "exclusion_criteria": [],
            },
            [{"candidate_id": "cand_1", "criterion_scores": {"Residue Evidence": 1.0}, "exclusion_scores": {}}],
        )
        assert traces[0].criterion_scores["residue_evidence"] == 1.0
        assert traces[0].final_score == 1.0

    asyncio.run(runner())


def test_pdf_extraction_reads_downloaded_xml_and_answers_questions(tmp_path) -> None:
    xml_path = tmp_path / "paper.xml"
    xml_path.write_text(
        "<article><body><sec><title>Results</title><p>Docking identified residue Alpha123 as a key interaction site.</p></sec></body></article>",
        encoding="utf-8",
    )

    class XMLPDFService:
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
                        file_path=str(xml_path),
                        content_kind="xml_fulltext",
                    )
                ],
            )

    async def runner() -> None:
        service = PDFExtractionService(pdf_service=XMLPDFService())
        response = await service.extract(
            PDFExtractionRequest(
                articles=[
                    {
                        "title": "Docking paper",
                        "year": "2024",
                        "doi": "10.1/test",
                    }
                ],
                questions=["Which residue is the key interaction site?"],
            )
        )
        assert response.success_count == 1
        assert "Alpha123" in response.results[0].answers[0].answer

    asyncio.run(runner())


def test_research_execution_fails_when_all_queries_error() -> None:
    class FailingPubMedService:
        async def search(self, request):  # noqa: ANN001
            _ = request
            raise RuntimeError("source down")

    async def runner() -> None:
        service = ResearchExecutionService(
            pubmed_service=FailingPubMedService(),
            screening_service=FakeScreeningService(),
        )
        try:
            await service.execute_plan_with_screening(
                {
                    "topic": "all fail",
                    "active_databases": ["PubMed"],
                    "search_branches": [{"id": "alpha", "label": "Alpha", "query": "alpha"}],
                    "screening_criteria": [{"id": "must_have", "label": "Must have", "required": True}],
                }
            )
        except RuntimeError as exc:
            assert "All research plan queries failed" in str(exc)
            return
        raise AssertionError("Expected all-query failure to raise.")

    asyncio.run(runner())


def test_research_plan_execute_endpoint_dedupes_screens_and_persists_trace(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        assert kwargs["model"] == "test-screen-model"
        assert "screening subagent" in kwargs["messages"][0]["content"]
        assert kwargs["tools"][0]["function"]["name"] == "screen_research_candidates"
        candidates = json.loads(kwargs["messages"][1]["content"])["candidates"]
        assert len(candidates) == 1
        candidate_id = candidates[0]["candidate_id"]
        payloads = {
            "cand_1": {
                "candidate_id": "cand_1",
                "criterion_scores": {"residue_evidence": 1.0},
                "exclusion_scores": {"exclusion_1": 0.0},
                "confidence": 0.9,
                "evidence": ["The abstract reports binding pocket residues."],
                "rationale": "Direct residue evidence is present.",
            },
            "cand_2": {
                "candidate_id": "cand_2",
                "criterion_scores": {"residue_evidence": 0.5},
                "exclusion_scores": {"exclusion_1": 1.0},
                "confidence": 0.8,
                "evidence": ["The article is a review."],
                "rationale": "Excluded as review material.",
            },
        }
        yield {"message": {"thinking": "screening started"}}
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items": [
            payloads[candidate_id],
        ]}}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
            )
            fake_pubmed = FakePubMedService()
            app = create_app(
                settings=settings,
                pubmed_service=fake_pubmed,
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                project = await client.post("/app/projects", json={"name": "Research Plan Test", "description": ""})
                assert project.status_code == 200
                project_id = project.json()["id"]

                plan = {
                    "topic": "Receptor binding residues",
                    "objective": "Find papers with specific interacting residues.",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed", "OpenAlex"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [
                        {"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}
                    ],
                    "screening_criteria": [
                        {
                            "id": "residue_evidence",
                            "label": "Residue evidence",
                            "description": "Specific binding pocket residues and ligand interaction evidence.",
                            "weight": 1,
                        }
                    ],
                    "exclusion_criteria": ["review"],
                    "raw_search_queries": [
                        {
                            "database": "PubMed",
                            "branch_id": "alpha",
                            "branch_label": "Receptor alpha",
                            "query": "receptor alpha",
                            "candidate_limit": 2,
                        },
                        {
                            "database": "OpenAlex",
                            "branch_id": "alpha",
                            "branch_label": "Receptor alpha",
                            "query": "receptor alpha",
                            "candidate_limit": 2,
                        },
                    ],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={
                        "plan": plan,
                        "screening_model": "ollama:test-screen-model",
                        "thinking_level": "off",
                        "pdf_extractor_enabled": True,
                        "pdf_scope": "selected_backup",
                        "full_text_model": "llamacpp:qwen3.6-35b-a3b-q4_K_M",
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["meta"]["primary_source"] == "research_plan"
                assert payload["articles"][0]["doi"] == "10.1000/shared"
                assert len(payload["run_trace"]["candidates"]) == 2
                assert payload["run_trace"]["selected_candidate_ids"] == ["cand_1"]
                assert payload["run_trace"]["excluded_candidate_ids"] == ["cand_2"]
                assert payload["run_trace"]["meta"]["full_text_settings"] == {
                    "pdf_extractor_enabled": True,
                    "pdf_scope": "selected_backup",
                    "full_text_model": "llamacpp:qwen3.6-35b-a3b-q4_K_M",
                }

                state = await client.get(f"/app/projects/{project_id}/state")
                assert state.status_code == 200
                assert state.json()["research_runs"][0]["id"] == payload["run_trace"]["id"]

    asyncio.run(runner())


def test_research_plan_execute_runs_pdf_screening_through_existing_download_service(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        candidates = json.loads(kwargs["messages"][1]["content"])["candidates"]
        candidate_id = candidates[0]["candidate_id"]
        excluded = candidate_id != "cand_1"
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items": [
            {
                "candidate_id": candidate_id,
                "criterion_scores": {"residue_evidence": 1.0 if not excluded else 0.1},
                "exclusion_scores": {"exclusion_1": 1.0 if excluded else 0.0},
                "confidence": 0.9,
                "evidence": ["screened"],
                "rationale": "screened",
            }
        ]}}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
            )

            class XMLDownloadPDFService(FakePDFService):
                async def download_articles(self, payload):  # noqa: ANN001
                    assert payload.downloader_mode == "pdf_xml"
                    assert len(payload.articles) == 1
                    xml_path = root / "paper.xml"
                    xml_path.write_text(
                        "<article><body><p>Residue Alpha123 contacts dopamine in the D1 receptor.</p></body></article>",
                        encoding="utf-8",
                    )
                    return PDFDownloadResponse(
                        total=1,
                        success_count=1,
                        failed_count=0,
                        results=[
                            PDFDownloadResult(
                                article=payload.articles[0],
                                success=True,
                                file_path=str(xml_path),
                                content_kind="xml_fulltext",
                            )
                        ],
                    )

            app = create_app(
                settings=settings,
                pubmed_service=FakePubMedService(),
                pdf_service=XMLDownloadPDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                project = await client.post("/app/projects", json={"name": "PDF Screen Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "objective": "Find papers with specific interacting residues.",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "screening_criteria": [{"id": "residue_evidence", "label": "Residue evidence", "weight": 1}],
                    "exclusion_criteria": ["review"],
                    "extraction_questions": ["Which residue contacts dopamine?"],
                    "extraction_fields": ["residue", "evidence_quote"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={
                        "plan": plan,
                        "screening_model": "ollama:test-screen-model",
                        "pdf_extractor_enabled": True,
                        "pdf_scope": "selected",
                        "full_text_model": "",
                        "thinking_level": "off",
                    },
                )
                assert response.status_code == 200
                pdf_screening = response.json()["run_trace"]["meta"]["pdf_screening"]
                assert pdf_screening["success_count"] == 1
                assert "Alpha123" in pdf_screening["results"][0]["answers"][0]["answer"]

    asyncio.run(runner())


def test_research_plan_stream_executes_two_branches_two_categories_with_small_limits(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        body = kwargs["messages"][1]["content"]

        candidates = json.loads(body)["candidates"]
        assert len(candidates) == 1
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items":
            [
                {
                    "candidate_id": item["candidate_id"],
                    "criterion_scores": {"topic_match": 1.0},
                    "exclusion_scores": {},
                    "confidence": 0.8,
                    "evidence": ["title/abstract matched"],
                    "rationale": "Relevant candidate.",
                }
                for item in candidates
            ]
        }}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
            )
            fake_pubmed = FakePubMedService()
            app = create_app(
                settings=settings,
                pubmed_service=fake_pubmed,
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                project = await client.post("/app/projects", json={"name": "Small Execute Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "small backend test",
                    "target_count_per_branch": 2,
                    "active_databases": ["PubMed", "OpenAlex"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [
                        {"id": "branch_a", "label": "Branch A", "query": "branch a"},
                        {"id": "branch_b", "label": "Branch B", "query": "branch b"},
                    ],
                    "shared_query_concepts": [
                        {"id": "cat_1", "label": "Category 1", "query": "category one"},
                        {"id": "cat_2", "label": "Category 2", "query": "category two"},
                    ],
                    "screening_criteria": [
                        {"id": "topic_match", "label": "Topic match", "description": "Matches the requested topic."}
                    ],
                    "exclusion_criteria": [],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute/stream",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                events = _sse_events(response.text)
                assert [event["type"] for event in events if event["type"] == "final"]
                final = next(event for event in events if event["type"] == "final")["response"]
                assert len(fake_pubmed.calls) == 4
                assert {call.max_results for call in fake_pubmed.calls} == {2}
                assert final["run_trace"]["meta"]["raw_query_count"] == 4
                assert final["run_trace"]["meta"]["candidate_article_count"] == len(final["candidate_articles"])
                assert all("category one" in call.query and "category two" in call.query for call in fake_pubmed.calls)
                assert any(event.get("stage") == "query_start" for event in events)
                query_complete_index = next(index for index, event in enumerate(events) if event.get("stage") == "queries_complete")
                screening_start_index = next(index for index, event in enumerate(events) if event.get("stage") == "screening_start")
                assert query_complete_index < screening_start_index
                assert events[query_complete_index]["articles"]
                assert events[query_complete_index]["meta"]["primary_source"] == "research_plan_candidates"
                assert any(event.get("stage") == "screening_batch" for event in events)
                assert any(event.get("stage") == "screening_agent_first_token" for event in events)
                state = await client.get(f"/app/projects/{project_id}/state")
                assert state.status_code == 200
                saved_queries = state.json()["query_history"]
                assert saved_queries[0]["id"] == f"research_{final['run_trace']['id']}"
                assert saved_queries[0]["title"] == "small backend test · Agent Query"
                assert saved_queries[0]["meta"]["primary_source"] == "research_plan_candidates"
                assert len(saved_queries[0]["articles"]) == len(final["candidate_articles"])

    asyncio.run(runner())


def test_research_plan_stream_uses_combined_shared_query_not_agent_split_queries(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        candidates = json.loads(kwargs["messages"][1]["content"])["candidates"]
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items":
            [
                {
                    "candidate_id": item["candidate_id"],
                    "criterion_scores": {"topic_match": 1.0},
                    "exclusion_scores": {},
                    "confidence": 0.9,
                    "evidence": ["matched"],
                    "rationale": "Relevant.",
                }
                for item in candidates
            ]
        }}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
            )
            fake_pubmed = FakePubMedService()
            app = create_app(
                settings=settings,
                pubmed_service=fake_pubmed,
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                project = await client.post("/app/projects", json={"name": "Combined Query Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "combined query test",
                    "target_count_per_branch": 2,
                    "active_databases": ["PubMed", "OpenAlex"],
                    "candidate_budget": {},
                    "search_branches": [{"id": "d1", "label": "D1", "query": "D1"}],
                    "shared_query_concepts": [
                        {"id": "binding", "label": "Binding residues", "query": "binding pocket residues"},
                        {"id": "structure", "label": "Structure", "query": "crystal structure OR cryo-EM"},
                    ],
                    "raw_search_queries": [
                        {
                            "database": "PubMed",
                            "branch_id": "d1",
                            "branch_label": "D1",
                            "category_id": "binding",
                            "category_label": "Binding residues",
                            "query": "(DRD1) AND (binding pocket residues)",
                            "candidate_limit": 3,
                        },
                        {
                            "database": "OpenAlex",
                            "branch_id": "d1",
                            "branch_label": "D1",
                            "category_id": "structure",
                            "category_label": "Structure",
                            "query": "(DRD1) AND (crystal structure OR cryo-EM)",
                            "candidate_limit": 3,
                        },
                    ],
                    "screening_criteria": [{"id": "topic_match", "label": "Topic match"}],
                    "exclusion_criteria": [],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute/stream",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                final = next(event for event in _sse_events(response.text) if event["type"] == "final")["response"]
                assert [call.query for call in fake_pubmed.calls] == [
                    "(D1) AND ((binding pocket residues) OR (crystal structure OR cryo-EM))",
                    "(D1) AND ((binding pocket residues) OR (crystal structure OR cryo-EM))",
                ]
                assert {call.max_results for call in fake_pubmed.calls} == {4}
                assert final["run_trace"]["meta"]["normalized_queries"][0]["category_id"] == ""
                assert final["run_trace"]["meta"]["normalized_queries"][0]["category_ids"] == ["binding", "structure"]
                assert final["run_trace"]["meta"]["normalized_queries"][0]["query"] == "(D1) AND ((binding pocket residues) OR (crystal structure OR cryo-EM))"

    asyncio.run(runner())


def test_screening_agent_errors_when_first_token_does_not_arrive(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        _ = kwargs
        await asyncio.sleep(0.05)
        yield {"message": {"content": "[]"}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)
    monkeypatch.setattr("app.services.research_screening_service.OLLAMA_FIRST_TOKEN_SECONDS", 0.01)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "First Token Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "first token test",
                    "target_count_per_branch": 1,
                    "active_databases": ["OpenAlex"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Alpha", "query": "alpha"}],
                    "screening_criteria": [{"id": "topic_match", "label": "Topic match"}],
                    "exclusion_criteria": [],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute/stream",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                events = _sse_events(response.text)
                error = next(event for event in events if event["type"] == "error")
                assert "did not emit" in error["message"]

    asyncio.run(runner())


def test_screening_agent_missing_candidate_does_not_fail_execution(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        candidates = json.loads(kwargs["messages"][1]["content"])["candidates"]
        assert len(candidates) == 1
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items":
            [
              {
                "candidate_id": "cand_1",
                "criterion_scores": {"residue_evidence": 1.0},
                "exclusion_scores": {"exclusion_1": 0.0},
                "evidence": ["first candidate scored"],
                "rationale": "ok"
              }
            ]
        }}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "Missing Candidate Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "target_count_per_branch": 2,
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "active_databases": ["OpenAlex"],
                    "screening_criteria": [
                        {"id": "residue_evidence", "label": "Residue evidence", "description": "binding pocket residues"}
                    ],
                    "exclusion_criteria": ["review"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                payload = response.json()
                assert len(payload["run_trace"]["screening"]) == 2
                omitted = payload["run_trace"]["screening"][1]
                assert omitted["candidate_id"] == "cand_2"
                assert "omitted" in omitted["evidence"][0]

    asyncio.run(runner())


def test_screening_agent_accepts_common_tool_result_alias(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        _ = kwargs
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"screening_results": [
            {
                "candidate_id": "cand_1",
                "criterion_scores": {"residue_evidence": 1.0},
                "exclusion_scores": {"exclusion_1": 0.0},
                "evidence": ["alias accepted"],
                "rationale": "ok",
            }
        ]}}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "Alias Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "screening_criteria": [{"id": "residue_evidence", "label": "Residue evidence"}],
                    "exclusion_criteria": ["review"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                assert response.json()["run_trace"]["screening"][0]["evidence"] == ["alias accepted"]

    asyncio.run(runner())


def test_screening_agent_retries_bad_tool_argument_shape(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            yield {"message": {"tool_calls": [{"function": {"id": "bad_call", "name": "screen_research_candidates", "arguments": {"note": "wrong shape"}}}]}}
            return
        assert "previous `screen_research_candidates` function call had invalid arguments" in kwargs["messages"][-1]["content"]
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items": [
            {
                "candidate_id": "cand_1",
                "criterion_scores": {"residue_evidence": 1.0},
                "exclusion_scores": {"exclusion_1": 0.0},
                "evidence": ["retry fixed"],
                "rationale": "ok",
            }
        ]}}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "Retry Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "screening_criteria": [{"id": "residue_evidence", "label": "Residue evidence"}],
                    "exclusion_criteria": ["review"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                assert calls["count"] == 2
                assert response.json()["run_trace"]["screening"][0]["evidence"] == ["retry fixed"]

    asyncio.run(runner())


def test_screening_agent_retries_when_model_returns_text_instead_of_tool(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] == 1:
            yield {"message": {"content": '[{"candidate_id":"cand_1","criterion_scores":{"residue_evidence":1.0},"exclusion_scores":{"exclusion_1":0.0}}]'}}
            return
            assert "returned text/JSON instead of calling the required function" in kwargs["messages"][-1]["content"]
        yield {"message": {"tool_calls": [{"function": {"id": "screen_call", "name": "screen_research_candidates", "arguments": {"items": [
            {
                "candidate_id": "cand_1",
                "criterion_scores": {"residue_evidence": 1.0},
                "exclusion_scores": {"exclusion_1": 0.0},
                "evidence": ["text retry fixed"],
                "rationale": "ok",
            }
        ]}}}]}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "Text Retry Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "screening_criteria": [{"id": "residue_evidence", "label": "Residue evidence"}],
                    "exclusion_criteria": ["review"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 200
                assert calls["count"] == 1
                assert response.json()["run_trace"]["screening"][0]["criterion_scores"]["residue_evidence"] == 1.0

    asyncio.run(runner())


def test_screening_agent_retries_then_fails_when_model_never_calls_tool(monkeypatch) -> None:
    calls = {"count": 0}

    async def fake_ollama_chat_stream(**kwargs):  # noqa: ANN001
        calls["count"] += 1
        if calls["count"] > 1:
            assert "Error:" in kwargs["messages"][-1]["content"] or "returned text/JSON" in kwargs["messages"][-1]["content"]
        yield {"message": {"content": "I cannot use the function right now."}}

    monkeypatch.setattr("app.services.research_screening_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = Settings(
                download_root=root / "downloads",
                workspace_root=root / "workspace",
                helper_log_path=root / "logs" / "helper_ai_history.jsonl",
                app_event_log_path=root / "logs" / "app_events.jsonl",
                assistant_api_key_path=root / "assistant_api_key.txt",
                ncbi_api_key_path=root / "ncbi_api",
                unpaywall_email_path=root / "unpaywall_email",
                openalex_api_key_path=root / "openalex_api_key",
                core_api_key_path=root / "core_api_key",
                pubmed_oa_only_path=root / "pubmed_oa_only",
                ai_primary_search_resource_path=root / "ai_primary_search_resource",
                pdf_downloader_mode_path=root / "pdf_downloader_mode",
                pdf_unpaywall_fallback_enabled_path=root / "pdf_unpaywall_fallback_enabled",
                pdf_core_fallback_enabled_path=root / "pdf_core_fallback_enabled",
                pdf_arxiv_fallback_enabled_path=root / "pdf_arxiv_fallback_enabled",
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
                project = await client.post("/app/projects", json={"name": "Fallback Test", "description": ""})
                project_id = project.json()["id"]
                plan = {
                    "topic": "Receptor binding residues",
                    "target_count_per_branch": 1,
                    "active_databases": ["PubMed"],
                    "candidate_budget": {"per_database": 2},
                    "search_branches": [{"id": "alpha", "label": "Receptor alpha", "query": "receptor alpha"}],
                    "screening_criteria": [{"id": "residue_evidence", "label": "Residue evidence"}],
                    "exclusion_criteria": ["review"],
                }
                response = await client.post(
                    f"/app/projects/{project_id}/research-plan/execute",
                    json={"plan": plan, "screening_model": "ollama:test-screen-model"},
                )
                assert response.status_code == 502
                assert calls["count"] == 3
                assert "screen_research_candidates" in response.json()["detail"]

    asyncio.run(runner())
