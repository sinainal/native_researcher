"""Ollama chat provider integration tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.schemas.article import Article
from app.llm.ollama import _OllamaStreamParser, _normalize_ollama_message
from app.schemas.helper import HelperArticle, HelperChatRequest
from app.schemas.pubmed import PubMedSearchMeta, PubMedSearchResponse
from app.services.agent.helper_ai_service import HelperAIService
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


def test_helper_service_ollama_chat_stream_executes_tool_calls(monkeypatch) -> None:
    seen_messages: list[list[dict[str, object]]] = []

    async def fake_ollama_chat_stream(**kwargs):
        seen_messages.append(list(kwargs.get("messages") or []))
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
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
        assert any(event["type"] == "answer_delta" and str(event.get("text") or "").startswith(" ") for event in events)
        second_turn_messages = seen_messages[1]
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
        assert any(event["type"] == "answer_delta" and str(event.get("text") or "").startswith(" ") for event in events)
        second_turn_messages = seen_messages[1]
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
