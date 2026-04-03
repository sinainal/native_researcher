"""Native Researcher search-only assistant service."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from app.genai import create_genai_client, load_genai_sdk, resolve_helper_model_name
from app.schemas.helper import (
    HelperChatRequest,
    HelperChatResponse,
    HelperExecutedAction,
)
from app.schemas.pubmed import PubMedSearchRequest
from app.services.agent.search_policy import AGENT_SEARCH_MAX_RESULTS
from app.services.agent.source_prompts import (
    source_label,
    source_query_guidance,
)
from app.services.agent.system_prompts import (
    NATIVE_FINALIZER_PROMPT,
    build_native_prompt,
    build_native_system_instruction,
)
from app.services.helper_log_service import HelperLogService
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache

MAX_NATIVE_TOOL_CALLS = 2


@dataclass
class NativeThreadState:
    history: list[dict[str, str]] = field(default_factory=list)


class NativeResearcherService:
    def __init__(
        self,
        *,
        thread_cache: TTLCache[str, NativeThreadState],
        pubmed_service: PubMedService,
        log_service: HelperLogService | None = None,
    ) -> None:
        self.thread_cache = thread_cache
        self.pubmed_service = pubmed_service
        self.log_service = log_service

    def log_event(self, event: str, **payload: Any) -> None:
        if self.log_service is None:
            return
        self.log_service.log(event, **payload)

    def _preferred_search_source(self) -> str:
        return getattr(self.pubmed_service.settings, "ai_primary_search_resource", "openalex")

    @staticmethod
    def _source_label(source: str) -> str:
        return source_label(source)

    def _source_query_guidance(self, source: str) -> str:
        return source_query_guidance(source)

    def _system_instruction(self) -> str:
        return build_native_system_instruction(self._preferred_search_source())

    def reset(self, thread_id: str) -> None:
        self.thread_cache.delete(thread_id)

    async def chat_stream(self, payload: HelperChatRequest) -> AsyncIterator[dict[str, Any]]:
        model_name = resolve_helper_model_name(payload.model)
        thread_id = payload.thread_id or f"native_{uuid4().hex[:16]}"
        thread_state = self.thread_cache.get(thread_id) or NativeThreadState()
        self.log_event(
            "native_stream_start",
            thread_id=thread_id,
            model=model_name,
            message=payload.message,
            thinking_level=payload.thinking_level,
        )

        client = create_genai_client(payload.api_key)
        _genai, types = load_genai_sdk()
        last_search_ids: list[int] = []
        executed_actions: list[HelperExecutedAction] = []
        streamed_thoughts: list[str] = []

        contents: list[Any] = [
            types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
            for item in thread_state.history
        ]
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=self._build_prompt(payload.message, date.today().isoformat()))],
            )
        )

        yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": "search"}
        yield {"type": "status", "text": "İstek analiz ediliyor."}

        remaining_tool_calls = MAX_NATIVE_TOOL_CALLS
        answer = "Yanit uretilemedi."
        finalizer_needed = False

        while True:
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=contents,
                config=self._build_generate_config(
                    types,
                    allow_tools=remaining_tool_calls > 0,
                    thinking_level=payload.thinking_level,
                    include_thoughts=payload.thinking_level != "off",
                ),
            )
            collected_parts: list[Any] = []
            function_calls: list[Any] = []
            seen_function_calls: set[str] = set()
            answer_chunks: list[str] = []

            async for chunk in stream:
                for candidate in getattr(chunk, "candidates", []) or []:
                    content = getattr(candidate, "content", None)
                    if content is None:
                        continue
                    for part in getattr(content, "parts", None) or []:
                        if self._should_store_stream_part(part):
                            collected_parts.append(part)

                        function_call = getattr(part, "function_call", None)
                        if function_call is not None:
                            call_key = self._function_call_key(function_call)
                            if call_key not in seen_function_calls:
                                seen_function_calls.add(call_key)
                                function_calls.append(function_call)
                            continue

                        if getattr(part, "thought", None):
                            thought_text = (getattr(part, "text", None) or "").strip()
                            if thought_text:
                                streamed_thoughts.append(thought_text)
                                yield {"type": "thinking_delta", "text": thought_text}
                            continue

                        text_value = getattr(part, "text", None) or ""
                        if text_value:
                            answer_chunks.append(text_value)
                            yield {"type": "answer_delta", "text": text_value}

            model_content = types.Content(role="model", parts=collected_parts)
            if function_calls and remaining_tool_calls > 0:
                contents.append(model_content)
                response_parts: list[Any] = []
                for function_call in function_calls:
                    if remaining_tool_calls <= 0:
                        break

                    call_id = getattr(function_call, "id", None) or f"call_{uuid4().hex[:8]}"
                    args = dict(function_call.args or {})
                    self.log_event(
                        "native_tool_call",
                        thread_id=thread_id,
                        model=model_name,
                        call_id=call_id,
                        name=function_call.name,
                        args=args,
                    )
                    yield {
                        "type": "tool_call",
                        "call_id": call_id,
                        "action": {
                            "type": "tool_call",
                            "name": function_call.name,
                            "title": "Searching Literature",
                            "status": "running",
                            "details": args,
                        },
                    }
                    result, action, last_search_ids = await self._execute_tool_call(
                        function_call.name,
                        args,
                    )
                    executed_actions.append(action)
                    self.log_event(
                        "native_tool_result",
                        thread_id=thread_id,
                        model=model_name,
                        call_id=call_id,
                        action=action.model_dump(),
                    )
                    yield {"type": "tool_result", "call_id": call_id, "action": action.model_dump()}
                    response_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=getattr(function_call, "id", None),
                                name=function_call.name,
                                response={"result": result},
                            )
                        )
                    )
                    remaining_tool_calls -= 1
                if response_parts:
                    contents.append(types.Content(role="user", parts=response_parts))
                    continue

            answer = "".join(answer_chunks).strip()
            if not answer and executed_actions:
                finalizer_needed = True
            answer = answer or "Yanit uretilemedi."
            break

        if finalizer_needed:
            yield {"type": "status", "text": "Son yanıt hazırlanıyor."}
            final_contents = [
                *contents,
                types.Content(role="user", parts=[types.Part(text=NATIVE_FINALIZER_PROMPT)]),
            ]
            stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=final_contents,
                config=self._build_generate_config(
                    types,
                    allow_tools=False,
                    thinking_level=payload.thinking_level,
                    include_thoughts=payload.thinking_level != "off",
                ),
            )
            answer_chunks: list[str] = []
            async for chunk in stream:
                for candidate in getattr(chunk, "candidates", []) or []:
                    content = getattr(candidate, "content", None)
                    if content is None:
                        continue
                    for part in getattr(content, "parts", None) or []:
                        if getattr(part, "thought", None):
                            thought_text = (getattr(part, "text", None) or "").strip()
                            if thought_text:
                                streamed_thoughts.append(thought_text)
                                yield {"type": "thinking_delta", "text": thought_text}
                            continue
                        text_value = getattr(part, "text", None) or ""
                        if text_value:
                            answer_chunks.append(text_value)
                            yield {"type": "answer_delta", "text": text_value}
            answer = "".join(answer_chunks).strip() or answer

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode="search",
            used_article_ids=last_search_ids,
            history_size=len(thread_state.history),
            thinking="\n\n".join(streamed_thoughts).strip() or None,
            executed_actions=executed_actions,
        )
        self.log_event(
            "native_stream_final",
            thread_id=thread_id,
            model=model_name,
            answer=answer,
            used_article_ids=last_search_ids,
            executed_actions=[item.model_dump() for item in executed_actions],
        )
        yield {"type": "final", "response": response.model_dump()}

    @staticmethod
    def _append_history(thread_state: NativeThreadState, user_message: str, answer: str) -> None:
        thread_state.history.extend(
            [
                {"role": "user", "text": user_message},
                {"role": "model", "text": answer},
            ]
        )
        thread_state.history = thread_state.history[-10:]

    def _build_prompt(self, message: str, today_stamp: str) -> str:
        return build_native_prompt(
            message,
            today_stamp=today_stamp,
            source=self._preferred_search_source(),
        )

    def _build_generate_config(
        self,
        types: Any,
        *,
        allow_tools: bool,
        thinking_level: str = "off",
        include_thoughts: bool = False,
    ):
        config_kwargs: dict[str, Any] = {
            "system_instruction": self._system_instruction(),
            "thinking_config": NativeResearcherService._build_thinking_config(
                types,
                thinking_level=thinking_level,
                include_thoughts=include_thoughts,
            ),
        }
        if allow_tools:
            config_kwargs["tools"] = [self._build_toolset(types)]
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO
                )
            )
        return types.GenerateContentConfig(**config_kwargs)

    @staticmethod
    def _build_thinking_config(types: Any, *, thinking_level: str, include_thoughts: bool):
        if not include_thoughts:
            return None
        level = (thinking_level or "off").strip().lower()
        level_map = {
            "low": types.ThinkingLevel.LOW,
            "max": types.ThinkingLevel.HIGH,
        }
        config_kwargs: dict[str, Any] = {"include_thoughts": True}
        if level in level_map:
            config_kwargs["thinking_level"] = level_map[level]
        return types.ThinkingConfig(**config_kwargs)

    @staticmethod
    def _should_store_stream_part(part: Any) -> bool:
        if getattr(part, "function_call", None) is not None:
            return True
        if getattr(part, "thought_signature", None) is not None:
            return True
        return bool(getattr(part, "text", None))

    @staticmethod
    def _function_call_key(function_call: Any) -> str:
        call_id = getattr(function_call, "id", None)
        if call_id:
            return str(call_id)
        return f"{getattr(function_call, 'name', '-')}-{json.dumps(dict(getattr(function_call, 'args', None) or {}), sort_keys=True)}"

    def _build_toolset(self, types: Any):
        source = self._preferred_search_source()
        label = self._source_label(source)
        return types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="search_pubmed",
                    description=(
                        "Run a literature search. "
                        f"This tool searches only the active source: {label}. "
                        f"{self._source_query_guidance(source)}"
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Concise literature search query string.",
                            },
                            "year_start": {
                                "type": "integer",
                                "description": "Optional start year.",
                            },
                            "year_end": {
                                "type": "integer",
                                "description": "Optional end year.",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Maximum number of articles to fetch, between 1 and 100.",
                            },
                            "article_type": {
                                "type": "string",
                                "description": "Optional article type filter.",
                            },
                            "min_cite": {
                                "type": "integer",
                                "description": "Optional minimum citation-count threshold.",
                            },
                        },
                        "required": ["query"],
                    },
                )
            ]
        )

    async def _execute_tool_call(
        self,
        name: str,
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], HelperExecutedAction, list[int]]:
        if name != "search_pubmed":
            raise ValueError(f"Bilinmeyen tool cagrisi: {name}")
        return await self._tool_search_pubmed(args)

    async def _tool_search_pubmed(
        self,
        args: dict[str, Any],
    ) -> tuple[dict[str, Any], HelperExecutedAction, list[int]]:
        query = str(args.get("query") or "").strip()
        year_start = parse_bounded_int(args.get("year_start"), default=None, minimum=1000, maximum=9999)
        year_end = parse_bounded_int(args.get("year_end"), default=None, minimum=1000, maximum=9999)
        max_results = parse_bounded_int(
            args.get("max_results"),
            default=AGENT_SEARCH_MAX_RESULTS,
            minimum=1,
            maximum=AGENT_SEARCH_MAX_RESULTS,
        )
        article_type = str(args.get("article_type") or "").strip() or None
        min_cite = parse_bounded_int(args.get("min_cite"), default=None, minimum=0, maximum=1_000_000)

        search = await self.pubmed_service.search(
            PubMedSearchRequest(
                query=query,
                year_start=year_start,
                year_end=year_end,
                max_results=max_results,
                min_cite=min_cite,
                article_type=article_type,
                use_cache=True,
                preferred_source=getattr(
                    self.pubmed_service.settings,
                    "ai_primary_search_resource",
                    "openalex",
                ),
            )
        )
        articles = [article.model_dump() for article in search.articles]
        article_ids = [int(article["id"]) for article in articles]
        result = {
            "count": len(articles),
            "articles": articles,
            "meta": search.meta.model_dump(),
        }
        action = HelperExecutedAction(
            type="tool_call",
            name="search_pubmed",
            title=f"Searched {self._source_label(search.meta.primary_source or self._preferred_search_source())}",
            status="success",
            details={
                "query": query,
                "year_start": year_start,
                "year_end": year_end,
                "max_results": max_results,
                "article_type": article_type,
                "min_cite": min_cite,
                "articles": articles,
                "meta": search.meta.model_dump(),
            },
        )
        return result, action, article_ids


def parse_bounded_int(
    value: Any,
    *,
    default: int | None,
    minimum: int,
    maximum: int,
) -> int | None:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))
