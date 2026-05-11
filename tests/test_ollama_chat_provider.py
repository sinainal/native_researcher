"""Ollama chat provider integration tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.schemas.article import Article
from app.llm.ollama import (
    OLLAMA_DEFAULT_NUM_CTX,
    OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS,
    _OllamaStreamParser,
    _normalize_ollama_message,
    _ollama_runtime_options,
    _ollama_thinking_budget,
)
from app.schemas.helper import HelperArticle, HelperChatRequest
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.services.agent.helper_ai_service import HelperAIService, HelperThreadState
from app.services.agent.native_researcher_service import NativeResearcherService
from app.utils.cache import TTLCache


class FakePubMedService:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            ai_primary_search_resource="pubmed",
            ollama_base_url="http://localhost:11434",
            ollama_model="gemma4:e2b",
            request_user_agent="NativeResearcherTests/1.0",
        )

    async def search(self, request) -> PubMedSearchResponse:
        _ = request
        return PubMedSearchResponse(
            meta=PubMedSearchMeta(
                full_query="ndm inhibitor",
                total_results_found=1,
                fetched_results=1,
                batch_size_used=1,
                request_count=1,
                elapsed_ms=15,
                cache_hit=False,
                oa_only=False,
                primary_source="pubmed",
                sources_used=["pubmed"],
                fallback_used=False,
            ),
            articles=[
                Article(
                    id=101,
                    pmid="123456",
                    title="NDM inhibitor review",
                    abstract="A concise review.",
                    year="2024",
                    article_type="Review",
                    article_types=["Review"],
                    mesh_terms=["Metallo-beta-Lactamases"],
                )
            ],
        )


def test_normalize_ollama_message_strips_gemma_tool_artifacts() -> None:
    message = {
        "role": "assistant",
        "content": "<|tool_response><tool_call|><|tool_response>\nThe temperature in Paris is 15°C.",
        "tool_calls": [
            {
                "function": {
                    "id": "call_1",
                    "name": "get_temperature",
                    "arguments": {"city": "Paris"},
                }
            }
        ],
    }

    normalized = _normalize_ollama_message(message)

    assert normalized["content"] == "The temperature in Paris is 15°C."
    assert normalized["tool_calls"] == message["tool_calls"]


def test_ollama_stream_parser_splits_think_and_preserves_spacing() -> None:
    parser = _OllamaStreamParser()

    parts = []
    for text in ("<thi", "nk> Merhaba", " dünya", "</thi", "nk> Sonuç"):
        parts.extend(parser.feed(text))
    parts.extend(parser.flush())

    assert [(part.kind, part.text) for part in parts] == [
        ("thinking", " Merhaba"),
        ("thinking", " dünya"),
        ("content", " Sonuç"),
    ]


def test_ollama_runtime_defaults_set_context_and_thinking_budget() -> None:
    assert _ollama_runtime_options()["num_ctx"] == OLLAMA_DEFAULT_NUM_CTX == 16_384
    assert _ollama_thinking_budget("off") is None
    assert _ollama_thinking_budget("on") == {
        "budget_tokens": OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS,
    }
    assert OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS == 8_192


def test_research_plan_tool_normalizes_defaults() -> None:
    async def runner() -> None:
        service = HelperAIService(thread_cache=TTLCache(ttl_seconds=60, max_entries=4))
        result, action = await service._execute_research_tool_call(
            "create_research_plan",
            {
                "topic": "dopamine D1-D5 docking papers with interaction maps",
                "objective": "Find docking papers with receptor interaction evidence.",
                "target_count": 20,
                "screening_criteria": [
                    {
                        "label": "Docking performed",
                        "description": "The paper explicitly reports molecular docking.",
                        "required": True,
                    }
                ],
            },
        )

        plan = result["plan"]
        assert action.name == "create_research_plan"
        assert action.details["execution_state"] == "planned"
        assert plan["target_count"] == 20
        assert plan["candidate_budget"]["per_database"] == 40
        assert plan["databases"] == ["PubMed", "Europe PMC", "OpenAlex", "CORE", "arXiv"]
        assert plan["screening_criteria"][0]["id"] == "docking_performed"
        assert "sum(score_i ** 2" in plan["scoring_rule"]

    asyncio.run(runner())


def test_research_agent_ollama_stream_creates_plan(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            assert kwargs["tools"][0]["function"]["name"] == "create_research_plan"
            assert "Researcher Agent" in kwargs["messages"][0]["content"]
            yield {"message": {"thinking": "Building a research plan. "}}
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "plan_call",
                                "name": "create_research_plan",
                                "arguments": {
                                    "topic": "dopamine D1-D5 docking papers",
                                    "objective": "Find docking papers that identify strong interaction regions.",
                                    "target_count": 20,
                                    "databases": ["PubMed", "OpenAlex"],
                                    "screening_criteria": [
                                        {
                                            "id": "docking_performed",
                                            "label": "Docking performed",
                                            "description": "The article explicitly reports molecular docking.",
                                            "required": True,
                                        },
                                        {
                                            "id": "interaction_region",
                                            "label": "Interaction region evidence",
                                            "description": "The article identifies receptor-ligand interaction regions.",
                                            "required": True,
                                        },
                                    ],
                                    "database_queries": [
                                        {
                                            "database": "PubMed",
                                            "query": "(dopamine receptor) AND molecular docking",
                                            "candidate_limit": 40,
                                        }
                                    ],
                                },
                            }
                        }
                    ]
                }
            }
            return
        yield {"message": {"content": "Researcher plan preview is ready. Ask for edits or execute later."}}

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = HelperAIService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="Find dopamine D1-D5 docking papers with strongest interaction regions",
            model="ollama:gemma4:e2b",
            mode="research_agent",
        )
        events = [event async for event in service.chat_stream(payload)]
        assert any(
            event["type"] == "thinking_delta" and "Building a research plan" in str(event.get("text") or "")
            for event in events
        )
        tool_result = next(event for event in events if event["type"] == "tool_result")
        plan = tool_result["action"]["details"]["plan"]
        assert plan["topic"] == "dopamine D1-D5 docking papers"
        assert plan["candidate_budget"]["per_database"] == 40
        assert [item["id"] for item in plan["screening_criteria"]] == [
            "docking_performed",
            "interaction_region",
        ]
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["mode"] == "research_agent"
        assert final_event["response"]["executed_actions"][0]["name"] == "create_research_plan"
        assert "Building a research plan" in final_event["response"]["thinking"]
        assert "Researcher plan preview is ready" in final_event["response"]["answer"]

    asyncio.run(runner())


def test_research_agent_ollama_followup_answers_from_existing_plan(monkeypatch) -> None:
    seen_messages: list[list[dict[str, object]]] = []

    async def fake_ollama_chat_stream(**kwargs):
        seen_messages.append(list(kwargs.get("messages") or []))
        prompt = str((kwargs.get("messages") or [])[-1].get("content") or "")
        assert "Current structured plan JSON" in prompt
        assert "dopamine receptor docking" in prompt
        yield {
            "message": {
                "content": (
                    "Use the PubMed query `(dopamine receptor) AND molecular docking` first, "
                    "then verify exact papers through DOI, PMID, or publisher landing pages."
                )
            }
        }

    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        cache = TTLCache(ttl_seconds=60, max_entries=4)
        cache.set(
            "thread_followup",
            HelperThreadState(
                research_plan={
                    "topic": "dopamine receptor docking",
                    "objective": "Find exact docking papers and interaction regions.",
                    "target_count": 20,
                    "databases": ["PubMed"],
                    "candidate_budget": {"target_count": 20, "per_database": 40, "rule": "Fetch 40."},
                    "database_queries": [
                        {
                            "database": "PubMed",
                            "query": "(dopamine receptor) AND molecular docking",
                            "candidate_limit": 40,
                        }
                    ],
                    "screening_criteria": [],
                },
            ),
        )
        service = HelperAIService(thread_cache=cache, pubmed_service=FakePubMedService())
        payload = HelperChatRequest(
            api_key="",
            thread_id="thread_followup",
            message="How do I access the exact papers for this plan?",
            model="ollama:gemma4:e2b",
            mode="research_agent",
        )
        events = [event async for event in service.chat_stream(payload)]
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["executed_actions"] == []
        assert "PubMed query" in final_event["response"]["answer"]
        assert cache.get("thread_followup").research_plan["topic"] == "dopamine receptor docking"

    asyncio.run(runner())


def test_research_agent_ollama_followup_revises_existing_plan(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            prompt = str((kwargs.get("messages") or [])[-1].get("content") or "")
            assert "Current structured plan JSON" in prompt
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "revise_plan",
                                "name": "create_research_plan",
                                "arguments": {
                                    "topic": "dopamine receptor docking",
                                    "objective": "Find docking papers with interaction maps.",
                                    "target_count": 10,
                                    "databases": ["PubMed"],
                                    "revision_summary": "Reduced target count to 10.",
                                },
                            }
                        }
                    ]
                }
            }
            return
        yield {"message": {"content": "The plan is revised to target 10 final papers."}}

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        cache = TTLCache(ttl_seconds=60, max_entries=4)
        cache.set(
            "thread_edit",
            HelperThreadState(
                research_plan={
                    "topic": "dopamine receptor docking",
                    "objective": "Find docking papers.",
                    "target_count": 20,
                    "databases": ["PubMed"],
                },
            ),
        )
        service = HelperAIService(thread_cache=cache, pubmed_service=FakePubMedService())
        payload = HelperChatRequest(
            api_key="",
            thread_id="thread_edit",
            message="Make the plan target 10 final papers.",
            model="ollama:gemma4:e2b",
            mode="research_agent",
        )
        events = [event async for event in service.chat_stream(payload)]
        tool_result = next(event for event in events if event["type"] == "tool_result")
        plan = tool_result["action"]["details"]["plan"]
        assert tool_result["action"]["details"]["revision_state"] == "updated"
        assert plan["target_count"] == 10
        assert plan["candidate_budget"]["per_database"] == 20
        assert cache.get("thread_edit").research_plan["target_count"] == 10

    asyncio.run(runner())


def test_helper_service_ollama_chat_stream_executes_tool_calls(monkeypatch) -> None:
    seen_messages: list[list[dict[str, object]]] = []

    async def fake_ollama_chat_stream(**kwargs):
        seen_messages.append(list(kwargs.get("messages") or []))
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            yield {"message": {"thinking": "Query planning. "}}
            yield {
                "message": {
                    "content": " Araçları kontrol ediyorum.",
                    "tool_calls": [
                        {
                            "function": {
                                "id": "call_1",
                                "name": "search_pubmed",
                                "arguments": {"query": "ndm inhibitor", "max_results": 1},
                            }
                        }
                    ],
                }
            }
            return
        yield {"message": {"content": "Bir ilgili derleme buldum."}}

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = HelperAIService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="NDM inhibitor review ara",
            model="ollama:gemma4:e2b",
            mode="fast",
            articles=[HelperArticle(id=1, title="Seed article", mesh_terms=["NDM"])],
        )
        events = [event async for event in service.chat_stream(payload)]
        assert any(event["type"] == "tool_call" for event in events)
        assert any(event["type"] == "status" and str(event.get("text") or "").startswith("Araç çalıştırılıyor") for event in events)
        assert any(event["type"] == "tool_result" for event in events)
        assert any(event["type"] == "answer_delta" and str(event.get("text") or "") == "Bir ilgili derleme buldum." for event in events)
        second_turn_messages = seen_messages[1]
        assistant_message = next(item for item in second_turn_messages if item.get("role") == "assistant")
        assert assistant_message["thinking"] == "Query planning."
        assert assistant_message["content"] == "Araçları kontrol ediyorum."
        assert assistant_message["tool_calls"]
        tool_message = next(item for item in second_turn_messages if item.get("role") == "tool")
        tool_content = json.loads(str(tool_message.get("content") or ""))
        assert "result" not in tool_content
        assert tool_content["query"] == "ndm inhibitor"
        assert tool_content["count"] == 1
        assert tool_content["articles"][0]["id"] == 101
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["model"] == "gemma4:e2b"
        assert final_event["response"]["answer"] == "Bir ilgili derleme buldum."
        assert final_event["response"]["used_article_ids"] == [101]
        assert final_event["response"]["executed_actions"][0]["name"] == "search_pubmed"

    asyncio.run(runner())


def test_native_service_ollama_chat_stream_executes_tool_calls(monkeypatch) -> None:
    seen_messages: list[list[dict[str, object]]] = []

    async def fake_ollama_chat_stream(**kwargs):
        seen_messages.append(list(kwargs.get("messages") or []))
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            yield {"message": {"thinking": "Search planning. "}}
            yield {
                "message": {
                    "content": " İlk sonucu alıyorum.",
                    "tool_calls": [
                        {
                            "function": {
                                "id": "call_native",
                                "name": "search_pubmed",
                                "arguments": {"query": "ndm inhibitor", "max_results": 1},
                            }
                        }
                    ],
                }
            }
            return
        yield {"message": {"content": "Arama tamamlandi."}}

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.native_researcher_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = NativeResearcherService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="NDM inhibitor review ara",
            model="ollama:gemma4:e2b",
            mode="search",
        )
        events = [event async for event in service.chat_stream(payload)]
        assert any(event["type"] == "tool_call" for event in events)
        assert any(event["type"] == "status" and str(event.get("text") or "").startswith("Araç çalıştırılıyor") for event in events)
        assert any(event["type"] == "tool_result" for event in events)
        assert any(event["type"] == "answer_delta" and str(event.get("text") or "") == "Arama tamamlandi." for event in events)
        second_turn_messages = seen_messages[1]
        assistant_message = next(item for item in second_turn_messages if item.get("role") == "assistant")
        assert assistant_message["thinking"] == "Search planning."
        assert assistant_message["content"] == "İlk sonucu alıyorum."
        assert assistant_message["tool_calls"]
        tool_message = next(item for item in second_turn_messages if item.get("role") == "tool")
        tool_content = json.loads(str(tool_message.get("content") or ""))
        assert "result" not in tool_content
        assert tool_content["count"] == 1
        assert tool_content["articles"][0]["id"] == 101
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["model"] == "gemma4:e2b"
        assert final_event["response"]["answer"] == "Arama tamamlandi."
        assert final_event["response"]["used_article_ids"] == [101]
        assert final_event["response"]["executed_actions"][0]["name"] == "search_pubmed"

    asyncio.run(runner())
