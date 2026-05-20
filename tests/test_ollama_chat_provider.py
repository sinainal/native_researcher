"""Ollama chat provider integration tests."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.schemas.article import Article
from app.llm.ollama import (
    OLLAMA_DEFAULT_NUM_CTX,
    OLLAMA_DEFAULT_NUM_PREDICT,
    OLLAMA_DEFAULT_REPEAT_LAST_N,
    OLLAMA_DEFAULT_REPEAT_PENALTY,
    OLLAMA_DEFAULT_TEMPERATURE,
    OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS,
    OLLAMA_DEFAULT_TOP_P,
    _OllamaStreamParser,
    _normalize_ollama_message,
    _ollama_runtime_options,
    _ollama_thinking_budget,
    extract_ollama_tool_calls,
)
from app.llm.llamacpp import (
    LLAMACPP_DEFAULT_REASONING_BUDGET_TOKENS,
    LLAMACPP_LOW_REASONING_BUDGET_TOKENS,
    _chat_payload,
    _normalize_openai_message,
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
            skip_local_model_validation=True,
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


def test_extract_tool_calls_from_gemma4_text_tool_block() -> None:
    message = {
        "role": "assistant",
        "content": '<tool_call>{"name":"search_articles","arguments":{"query":"dopamine D1 receptor","max_results":4}}</tool_call>',
    }

    calls = extract_ollama_tool_calls(message)

    assert len(calls) == 1
    assert calls[0].name == "search_articles"
    assert calls[0].args == {"query": "dopamine D1 receptor", "max_results": 4}


def test_extract_tool_calls_wraps_list_arguments_as_items() -> None:
    message = {
        "role": "assistant",
        "tool_calls": [
            {
                "function": {
                    "id": "call_1",
                    "name": "screen_research_candidates",
                    "arguments": '[{"id":"cand_1","s":{"criterion":1},"x":0}]',
                }
            }
        ],
    }

    calls = extract_ollama_tool_calls(message)

    assert len(calls) == 1
    assert calls[0].args == {"items": [{"id": "cand_1", "s": {"criterion": 1}, "x": 0}]}


def test_llamacpp_normalizes_gemma4_text_tool_block_to_openai_tool_calls() -> None:
    normalized = _normalize_openai_message(
        {
            "role": "assistant",
            "content": '<|tool_call|>{"name":"create_search_plan","arguments":{"topic":"dopamine residues"}}</tool_call>',
        }
    )

    assert normalized["content"] == ""
    assert normalized["tool_calls"][0]["function"]["name"] == "create_search_plan"
    assert json.loads(normalized["tool_calls"][0]["function"]["arguments"]) == {"topic": "dopamine residues"}


def test_llamacpp_payload_uses_auto_for_forced_tool_choice_object() -> None:
    payload = _chat_payload(
        model="gemma",
        messages=[{"role": "user", "content": "plan"}],
        tools=[{"type": "function", "function": {"name": "create_search_plan", "parameters": {"type": "object"}}}],
        stream=True,
        tool_choice={"type": "function", "function": {"name": "create_search_plan"}},
    )

    assert payload["tool_choice"] == "auto"


def test_llamacpp_payload_caps_reasoning_budget_for_thinking_modes() -> None:
    on_payload = _chat_payload(
        model="qwen",
        messages=[{"role": "user", "content": "plan"}],
        tools=None,
        stream=False,
        thinking_level="on",
    )
    low_payload = _chat_payload(
        model="qwen",
        messages=[{"role": "user", "content": "plan"}],
        tools=None,
        stream=False,
        thinking_level="low",
    )
    max_payload = _chat_payload(
        model="qwen",
        messages=[{"role": "user", "content": "plan"}],
        tools=None,
        stream=False,
        thinking_level="max",
    )

    assert on_payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert on_payload["thinking_budget_tokens"] == LLAMACPP_DEFAULT_REASONING_BUDGET_TOKENS
    assert low_payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert low_payload["thinking_budget_tokens"] == LLAMACPP_LOW_REASONING_BUDGET_TOKENS
    assert max_payload["chat_template_kwargs"] == {"enable_thinking": True}
    assert "thinking_budget_tokens" not in max_payload


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
    options = _ollama_runtime_options()
    assert options["num_ctx"] == OLLAMA_DEFAULT_NUM_CTX == 16_384
    assert options["num_predict"] == OLLAMA_DEFAULT_NUM_PREDICT == 4_096
    assert options["temperature"] == OLLAMA_DEFAULT_TEMPERATURE == 0.7
    assert options["top_p"] == OLLAMA_DEFAULT_TOP_P == 0.9
    assert options["repeat_last_n"] == OLLAMA_DEFAULT_REPEAT_LAST_N == 256
    assert options["repeat_penalty"] == OLLAMA_DEFAULT_REPEAT_PENALTY == 1.12
    assert _ollama_thinking_budget("off") is None
    assert _ollama_thinking_budget("on") == {
        "budget_tokens": OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS,
    }
    assert OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS == 4_096


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
        assert plan["target_count_per_branch"] == 20
        assert plan["candidate_budget"]["per_database"] == 40
        assert plan["databases"] == ["PubMed", "Europe PMC", "OpenAlex", "CORE", "arXiv"]
        assert plan["active_databases"] == plan["databases"]
        assert plan["search_branches"][0]["label"] == "dopamine D1-D5 docking papers with interaction maps"
        assert "database_queries" not in plan
        assert len(plan["raw_search_queries"]) == 5
        assert plan["raw_search_queries"][0]["branch_label"] == "dopamine D1-D5 docking papers with interaction maps"
        assert plan["total_queries"] == 5
        assert plan["estimated_candidates"] == 200
        assert plan["estimated_time_seconds"] == 100
        assert plan["screening_criteria"][0]["id"] == "docking_performed"
        assert "sum(score_i ** 2" in plan["scoring_rule"]
        assert plan["search_strategy"]["active_databases"] == plan["active_databases"]
        assert plan["criteria_strategy"]["screening_criteria"][0]["id"] == "docking_performed"
        assert plan["extraction_strategy"]["extraction_questions"]
        assert "evidence_requirements" in plan["extraction_strategy"]
        assert [stage["agent"] for stage in plan["planner_stages"]] == [
            "SearchPlannerAgent",
            "CriteriaPlannerAgent",
            "ExtractionPlannerAgent",
        ]
        assert plan["planner_stages"][1]["context"]["search_branches"] == plan["search_branches"]

    asyncio.run(runner())


def test_research_plan_tool_normalizes_search_branches_and_active_databases() -> None:
    async def runner() -> None:
        service = HelperAIService(thread_cache=TTLCache(ttl_seconds=60, max_entries=4))
        result, _action = await service._execute_research_tool_call(
            "create_research_plan",
            {
                "topic": "multi-target residue mapping",
                "objective": "Find residue-level evidence across multiple targets.",
                "target_count_per_branch": 10,
                "active_databases": ["PubMed", "OpenAlex"],
                "search_branches": [
                    {
                        "label": "Target A",
                        "query": '"Target A" OR "Alias A"',
                        "aliases": ["Alias A"],
                    },
                    {
                        "label": "Target B",
                        "query": '"Target B" OR "Alias B"',
                        "aliases": ["Alias B"],
                    },
                ],
                "shared_query_concepts": [
                    {
                        "label": "Residue evidence",
                        "query": '"binding site" OR mutagenesis OR structure',
                        "terms": ["binding site", "mutagenesis", "structure"],
                    },
                    {
                        "label": "Computational evidence",
                        "query": '"molecular dynamics" OR docking OR simulation',
                    },
                ],
            },
        )

        plan = result["plan"]
        assert plan["databases"] == ["PubMed", "OpenAlex"]
        assert plan["active_databases"] == ["PubMed", "OpenAlex"]
        assert [item["id"] for item in plan["search_branches"]] == ["target_a", "target_b"]
        assert plan["search_branches"][0]["query"] == '"Target A" OR "Alias A"'
        assert "aliases" not in plan["search_branches"][0]
        assert plan["shared_query_concepts"][0]["query"] == '"binding site" OR mutagenesis OR structure'
        assert "terms" not in plan["shared_query_concepts"][0]
        assert plan["candidate_budget"]["per_database"] == 20
        assert len(plan["raw_search_queries"]) == 4
        assert plan["raw_search_queries"][0]["category_label"] == "Combined categories"
        assert plan["raw_search_queries"][0]["category_labels"] == ["Residue evidence", "Computational evidence"]
        assert plan["raw_search_queries"][0]["query"] == (
            '("Target A" OR "Alias A") AND (("binding site" OR mutagenesis OR structure) '
            'OR ("molecular dynamics" OR docking OR simulation))'
        )
        assert plan["total_queries"] == 4
        assert plan["estimated_candidates"] == 80
        assert plan["estimated_time_seconds"] == 40

    asyncio.run(runner())


def test_research_agent_ollama_stream_creates_plan(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            assert kwargs["tools"][0]["function"]["name"] == "create_search_plan"
            assert "SearchPlannerAgent" in kwargs["messages"][0]["content"]
            yield {"message": {"thinking": "Building a research plan. "}}
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "search_plan_call",
                                "name": "create_search_plan",
                                "arguments": {
                                    "topic": "dopamine D1-D5 docking papers",
                                    "objective": "Find docking papers that identify strong interaction regions.",
                                    "target_count": 20,
                                    "databases": ["PubMed", "OpenAlex"],
                                    "search_branches": [
                                        {
                                            "label": "Dopamine D1-D5 docking",
                                            "query": '"dopamine receptor" OR DRD1 OR DRD2 OR DRD3 OR DRD4 OR DRD5',
                                        }
                                    ],
                                    "shared_query_concepts": [
                                        {
                                            "query": '"molecular docking" OR "interaction map" OR "binding pose"',
                                        }
                                    ],
                                },
                            }
                        }
                    ]
                }
            }
            return
        if fake_ollama_chat_stream.calls == 2:
            assert kwargs["tools"][0]["function"]["name"] == "create_criteria_plan"
            assert "CriteriaPlannerAgent" in kwargs["messages"][0]["content"]
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "criteria_plan_call",
                                "name": "create_criteria_plan",
                                "arguments": {
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
                                },
                            }
                        }
                    ]
                }
            }
            return
        assert fake_ollama_chat_stream.calls == 3
        assert kwargs["tools"][0]["function"]["name"] == "create_extraction_plan"
        assert "ExtractionPlannerAgent" in kwargs["messages"][0]["content"]
        yield {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "id": "extraction_plan_call",
                            "name": "create_extraction_plan",
                            "arguments": {
                                "extraction_questions": [
                                    "Which receptor residues interact with ligands in the full text?"
                                ],
                                "extraction_fields": ["paper_id", "residue", "evidence_quote"],
                                "evidence_requirements": ["Use only downloaded PDF/XML evidence."],
                            },
                        }
                    }
                ]
            }
        }

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
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert [event["action"]["name"] for event in tool_results[:3]] == [
            "create_search_plan",
            "create_criteria_plan",
            "create_extraction_plan",
        ]
        tool_result = tool_results[-1]
        plan = tool_result["action"]["details"]["plan"]
        assert plan["topic"] == "dopamine D1-D5 docking papers"
        assert plan["candidate_budget"]["per_database"] == 40
        assert plan["total_queries"] == 2
        assert len(plan["raw_search_queries"]) == 2
        assert "molecular docking" in plan["raw_search_queries"][0]["query"]
        assert [item["id"] for item in plan["screening_criteria"]] == [
            "docking_performed",
            "interaction_region",
        ]
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["mode"] == "research_agent"
        assert [action["name"] for action in final_event["response"]["executed_actions"]] == [
            "create_search_plan",
            "create_criteria_plan",
            "create_extraction_plan",
            "create_research_plan",
        ]
        assert "Building a research plan" in final_event["response"]["thinking"]
        assert "Researcher plan created" in final_event["response"]["answer"]

    asyncio.run(runner())


def test_research_agent_ollama_retries_when_first_turn_skips_tool(monkeypatch) -> None:
    seen_messages: list[list[dict[str, object]]] = []

    async def fake_ollama_chat_stream(**kwargs):
        seen_messages.append(list(kwargs.get("messages") or []))
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            yield {"message": {"content": "I can help you research dopamine receptors."}}
            return
        if fake_ollama_chat_stream.calls == 2:
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "retry_plan_call",
                                "name": "create_search_plan",
                                "arguments": {
                                    "topic": "dopamine D1-D5 interacting residues",
                                    "objective": "Find residue-level interaction evidence for dopamine D1-D5 receptor types.",
                                    "target_count": 20,
                                    "search_branches": [{"label": "dopamine D1-D5", "query": "dopamine receptor"}],
                                },
                            }
                        }
                    ]
                }
            }
            return
        if fake_ollama_chat_stream.calls == 3:
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "criteria_plan_call",
                                "name": "create_criteria_plan",
                                "arguments": {
                                    "screening_criteria": [
                                        {
                                            "id": "residue_evidence",
                                            "label": "Residue evidence",
                                            "description": "Reports residue-level interaction evidence.",
                                        }
                                    ]
                                },
                            }
                        }
                    ]
                }
            }
            return
        yield {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "id": "extraction_plan_call",
                            "name": "create_extraction_plan",
                            "arguments": {
                                "extraction_questions": ["Which residues are supported by full-text evidence?"]
                            },
                        }
                    }
                ]
            }
        }

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = HelperAIService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="give me researchs for dopamine d1-d5 i want to research the important interacting residues of all these types",
            model="ollama:gemma4:e2b",
            mode="research_agent",
        )
        events = [event async for event in service.chat_stream(payload)]
        leaked_prose = [
            event for event in events
            if event["type"] == "answer_delta" and "I can help you research" in str(event.get("text") or "")
        ]
        assert leaked_prose == []
        assert any(
            event["type"] == "status" and "SearchPlannerAgent" in str(event.get("text") or "")
            for event in events
        )
        assert "did not call `create_search_plan`" in str(seen_messages[1][-1]["content"])
        tool_result = [event for event in events if event["type"] == "tool_result"][-1]
        assert tool_result["action"]["details"]["plan"]["topic"] == "dopamine D1-D5 interacting residues"
        final_event = next(event for event in events if event["type"] == "final")
        assert final_event["response"]["executed_actions"][-1]["name"] == "create_research_plan"

    asyncio.run(runner())


def test_research_agent_ollama_legacy_planner_mode_uses_single_tool(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            assert kwargs["tools"][0]["function"]["name"] == "create_research_plan"
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "legacy_plan_call",
                                "name": "create_research_plan",
                                "arguments": {
                                    "topic": "dopamine receptor docking",
                                    "objective": "Find docking papers.",
                                    "target_count": 5,
                                },
                            }
                        }
                    ]
                }
            }
            return
        yield {"message": {"content": "Legacy plan preview is ready."}}

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = HelperAIService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="Plan dopamine receptor docking papers",
            model="ollama:gemma4:e2b",
            mode="research_agent",
            research_planner_mode="legacy",
        )
        events = [event async for event in service.chat_stream(payload)]
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert [event["action"]["name"] for event in tool_results] == ["create_research_plan"]
        assert fake_ollama_chat_stream.calls == 2

    asyncio.run(runner())


def test_research_agent_ollama_can_disable_criteria_stage(monkeypatch) -> None:
    async def fake_ollama_chat_stream(**kwargs):
        fake_ollama_chat_stream.calls += 1
        if fake_ollama_chat_stream.calls == 1:
            assert kwargs["tools"][0]["function"]["name"] == "create_search_plan"
            yield {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "id": "search_plan_call",
                                "name": "create_search_plan",
                                "arguments": {
                                    "topic": "dopamine receptor residues",
                                    "objective": "Find residue evidence.",
                                    "search_branches": [{"label": "D1", "query": "D1 receptor residue"}],
                                },
                            }
                        }
                    ]
                }
            }
            return
        assert fake_ollama_chat_stream.calls == 2
        assert kwargs["tools"][0]["function"]["name"] == "create_extraction_plan"
        yield {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "id": "extraction_plan_call",
                            "name": "create_extraction_plan",
                            "arguments": {
                                "extraction_questions": ["Return the exact sentence naming dopamine-contact residues."]
                            },
                        }
                    }
                ]
            }
        }

    fake_ollama_chat_stream.calls = 0
    monkeypatch.setattr("app.services.agent.helper_ai_service.ollama_chat_stream", fake_ollama_chat_stream)

    async def runner() -> None:
        service = HelperAIService(
            thread_cache=TTLCache(ttl_seconds=60, max_entries=4),
            pubmed_service=FakePubMedService(),
        )
        payload = HelperChatRequest(
            api_key="",
            message="Plan dopamine residue extraction",
            model="ollama:gemma4:e2b",
            mode="research_agent",
            research_criteria_enabled=False,
        )
        events = [event async for event in service.chat_stream(payload)]
        tool_results = [event for event in events if event["type"] == "tool_result"]
        assert [event["action"]["name"] for event in tool_results] == [
            "create_search_plan",
            "create_extraction_plan",
            "create_research_plan",
        ]
        plan = tool_results[-1]["action"]["details"]["plan"]
        assert plan["criteria_strategy"]["criteria_mode"] == "disabled"
        assert plan["screening_criteria"] == []
        assert plan["exclusion_criteria"] == []

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
                    "raw_search_queries": [
                        {
                            "database": "PubMed",
                            "branch_id": "dopamine_receptor_docking",
                            "branch_label": "dopamine receptor docking",
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
        assert any(event["type"] == "status" and str(event.get("text") or "").startswith("Running tool") for event in events)
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
        assert any(event["type"] == "status" and str(event.get("text") or "").startswith("Running tool") for event in events)
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
