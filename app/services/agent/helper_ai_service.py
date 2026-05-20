"""Gemini-backed helper chat service."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from app.genai import create_genai_client, load_genai_sdk
from app.llm import (
    extract_ollama_tool_calls,
    llamacpp_chat,
    llamacpp_chat_stream,
    ollama_chat,
    ollama_chat_stream,
    resolve_chat_model_target,
)
from app.schemas.article import Article
from app.schemas.helper import (
    HelperArticle,
    HelperChatRequest,
    HelperChatResponse,
    HelperExecutedAction,
)
from app.schemas.pubmed import PubMedSearchRequest, PubMedSearchResponse
from app.services.agent.search_policy import AGENT_SEARCH_MAX_RESULTS
from app.services.agent.source_prompts import (
    source_label,
    source_query_guidance,
    source_tool_description,
)
from app.services.agent.system_prompts import (
    HELPER_FINALIZER_PROMPT,
    RESEARCH_PLAN_FINALIZER_PROMPT,
    build_helper_fast_mode_system_instruction,
    build_helper_fast_prompt,
    build_research_agent_prompt,
    build_research_agent_system_instruction,
)
from app.services.helper_log_service import HelperLogService
from app.services.local_llamacpp_supervisor import ensure_llamacpp_ready, is_llamacpp_connection_error
from app.services.local_llamacpp_supervisor import stop_local_llamacpp_servers
from app.services.local_ollama_supervisor import ensure_ollama_model_available
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache
MAX_FAST_TOOL_CALLS = 3
MAX_DETAIL_TOOL_TOKENS = 50_000
RESEARCH_AGENT_MODE = "research_agent"


@dataclass
class HelperThreadState:
    history: list[dict[str, str]] = field(default_factory=list)
    research_plan: dict[str, Any] | None = None


class HelperAIService:
    def __init__(
        self,
        *,
        thread_cache: TTLCache[str, HelperThreadState],
        pubmed_service: PubMedService | None = None,
        log_service: HelperLogService | None = None,
    ) -> None:
        self.thread_cache = thread_cache
        self.pubmed_service = pubmed_service
        self.log_service = log_service

    def recent_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.log_service is None:
            return []
        return self.log_service.tail(limit=limit)

    def log_event(self, event: str, **payload: Any) -> None:
        self._log(event, **payload)

    def _log(self, event: str, **payload: Any) -> None:
        if self.log_service is None:
            return
        self.log_service.log(event, **payload)

    def _preferred_search_source(self) -> str:
        if self.pubmed_service is None:
            return "pubmed"
        return getattr(self.pubmed_service.settings, "ai_primary_search_resource", "pubmed")

    @staticmethod
    def _source_label(source: str) -> str:
        return source_label(source)

    def _source_query_guidance(self, source: str) -> str:
        return source_query_guidance(source)

    def _fast_mode_system_instruction(self) -> str:
        return build_helper_fast_mode_system_instruction(self._preferred_search_source())

    def _runtime_settings(self) -> Any | None:
        return getattr(self.pubmed_service, "settings", None)

    def _resolve_model_target(self, requested_model: str | None):
        return resolve_chat_model_target(requested_model, settings=self._runtime_settings())

    def _require_gemini_api_key(self, api_key: str) -> None:
        if len((api_key or "").strip()) >= 10:
            return
        raise RuntimeError("Gemini modeli icin API key gerekli.")

    def _ollama_base_url(self) -> str:
        settings = self._runtime_settings()
        return str(getattr(settings, "ollama_base_url", "http://localhost:11434") or "http://localhost:11434")

    def _ollama_request_user_agent(self) -> str:
        settings = self._runtime_settings()
        return str(getattr(settings, "request_user_agent", "NativeResearcher/0.1") or "NativeResearcher/0.1")

    def _local_llm_base_url(self, provider: str) -> str:
        settings = self._runtime_settings()
        if provider == "llamacpp":
            return str(getattr(settings, "llamacpp_base_url", "http://localhost:8098") or "http://localhost:8098")
        return self._ollama_base_url()

    async def _ensure_ollama_ready_for_model(self, model: str) -> None:
        settings = self._runtime_settings()
        if bool(getattr(settings, "skip_local_model_validation", False)):
            return
        stop_local_llamacpp_servers()
        await ensure_ollama_model_available(
            base_url=self._ollama_base_url(),
            model=model,
            request_user_agent=str(getattr(settings, "request_user_agent", "NativeResearcher/0.1") or "NativeResearcher/0.1"),
        )

    async def _local_llm_chat(self, *, provider: str, **kwargs: Any) -> dict[str, Any]:
        kwargs["base_url"] = self._local_llm_base_url(provider)
        if provider == "llamacpp":
            settings = self._runtime_settings()
            if settings is not None:
                kwargs["base_url"] = await ensure_llamacpp_ready(
                    settings,
                    model=str(kwargs.get("model") or "local"),
                    request_user_agent=str(kwargs.get("request_user_agent") or self._ollama_request_user_agent()),
                )
            try:
                return await llamacpp_chat(**kwargs)
            except Exception as exc:
                if settings is None or not is_llamacpp_connection_error(exc):
                    raise
                kwargs["base_url"] = await ensure_llamacpp_ready(
                    settings,
                    model=str(kwargs.get("model") or "local"),
                    request_user_agent=str(kwargs.get("request_user_agent") or self._ollama_request_user_agent()),
                )
                return await llamacpp_chat(**kwargs)
        await self._ensure_ollama_ready_for_model(str(kwargs.get("model") or ""))
        return await ollama_chat(**kwargs)

    async def _local_llm_chat_stream(self, *, provider: str, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        kwargs["base_url"] = self._local_llm_base_url(provider)
        if provider == "llamacpp":
            settings = self._runtime_settings()
            if settings is not None:
                status_events: list[dict[str, Any]] = []
                ensure_task = asyncio.create_task(
                    ensure_llamacpp_ready(
                        settings,
                        model=str(kwargs.get("model") or "local"),
                        request_user_agent=str(kwargs.get("request_user_agent") or self._ollama_request_user_agent()),
                        status_callback=status_events.append,
                    )
                )
                while True:
                    try:
                        kwargs["base_url"] = await asyncio.wait_for(asyncio.shield(ensure_task), timeout=0.25)
                        break
                    except asyncio.TimeoutError:
                        while status_events:
                            yield status_events.pop(0)
                while status_events:
                    yield status_events.pop(0)
            try:
                async for chunk in llamacpp_chat_stream(**kwargs):
                    yield chunk
                return
            except Exception as exc:
                if settings is None or not is_llamacpp_connection_error(exc):
                    raise
                retry_events: list[dict[str, Any]] = [{"type": "status", "text": "Recovering llama.cpp connection."}]
                ensure_task = asyncio.create_task(
                    ensure_llamacpp_ready(
                        settings,
                        model=str(kwargs.get("model") or "local"),
                        request_user_agent=str(kwargs.get("request_user_agent") or self._ollama_request_user_agent()),
                        status_callback=retry_events.append,
                    )
                )
                while True:
                    try:
                        kwargs["base_url"] = await asyncio.wait_for(asyncio.shield(ensure_task), timeout=0.25)
                        break
                    except asyncio.TimeoutError:
                        while retry_events:
                            yield retry_events.pop(0)
                retry_events.append({"type": "status", "text": "Retrying llama.cpp request after reconnect."})
                for event in retry_events:
                    yield event
                async for chunk in llamacpp_chat_stream(**kwargs):
                    yield chunk
                return
        await self._ensure_ollama_ready_for_model(str(kwargs.get("model") or ""))
        stream = ollama_chat_stream(**kwargs)
        async for chunk in stream:
            yield chunk

    @staticmethod
    def _history_to_ollama_messages(history: list[dict[str, str]]) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        for item in history:
            role = "assistant" if item.get("role") == "model" else "user"
            text = str(item.get("text") or "")
            if not text:
                continue
            messages.append({"role": role, "content": text})
        return messages

    @staticmethod
    def _ollama_assistant_message(
        *,
        content: str,
        thinking: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant"}
        if thinking:
            message["thinking"] = thinking
        if content:
            message["content"] = content
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    @staticmethod
    def _ollama_tool_message_content(result: Any) -> str:
        if isinstance(result, str):
            return result
        try:
            return json.dumps(result, ensure_ascii=False)
        except TypeError:
            return str(result)

    @staticmethod
    def _apply_criteria_enabled(args: dict[str, Any], enabled: bool) -> dict[str, Any]:
        next_args = dict(args)
        if not enabled:
            next_args["criteria_mode"] = "disabled"
            next_args["screening_criteria"] = []
            next_args["exclusion_criteria"] = []
        return next_args

    async def _ollama_chat_with_heartbeat(
        self,
        *,
        status_text: str,
        heartbeat_text: str,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        task = asyncio.create_task(ollama_chat(**kwargs))
        try:
            yield {"type": "status", "text": status_text}
            while True:
                try:
                    response = await asyncio.wait_for(asyncio.shield(task), timeout=8.0)
                    yield {"type": "response", "payload": response}
                    return
                except asyncio.TimeoutError:
                    yield {"type": "status", "text": heartbeat_text}
        finally:
            if not task.done():
                task.cancel()

    async def chat(self, payload: HelperChatRequest) -> HelperChatResponse:
        model_target = self._resolve_model_target(payload.model)
        model_name = model_target.model_name
        thread_id = payload.thread_id or f"thread_{uuid4().hex[:16]}"
        thread_state = self.thread_cache.get(thread_id) or HelperThreadState()
        self._log(
            "assistant_chat_start",
            thread_id=thread_id,
            mode=payload.mode,
            model=model_name,
            message=payload.message,
            selected_ids=payload.selected_ids,
            article_count=len(payload.articles),
            thinking_level=payload.thinking_level,
        )
        if model_target.provider in {"ollama", "llamacpp"}:
            return await self._chat_with_ollama(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
                provider=model_target.provider,
            )

        if payload.mode == RESEARCH_AGENT_MODE:
            return await self._chat_research_agent(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
            )

        if payload.mode != "fast":
            answer = "This assistant mode is not available yet. Use Normal Mode or Research Agent Mode."
            self._append_history(thread_state, payload.message, answer)
            self.thread_cache.set(thread_id, thread_state)
            self._log(
                "assistant_chat_final",
                thread_id=thread_id,
                mode=payload.mode,
                model=model_name,
                answer=answer,
                used_article_ids=[],
                executed_actions=[],
            )
            return HelperChatResponse(
                thread_id=thread_id,
                answer=answer,
                model=model_name,
                mode=payload.mode,
                history_size=len(thread_state.history),
            )

        self._require_gemini_api_key(payload.api_key)
        _genai, types = load_genai_sdk()
        article_index = {article.id: article for article in payload.articles}
        last_search_index: dict[int, HelperArticle] = {}
        selected_set = set(payload.selected_ids)
        used_article_ids: set[int] = set()
        executed_actions: list[HelperExecutedAction] = []
        step_notes: list[str] = []

        contents: list[Any] = [
            types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
            for item in thread_state.history
        ]
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=self._build_fast_prompt(payload, today_stamp=date.today().isoformat()))],
            )
        )

        remaining_tool_calls = MAX_FAST_TOOL_CALLS
        answer = "No answer could be generated."
        finalizer_needed = False
        terminal_answer: str | None = None
        while True:
            response = await asyncio.to_thread(
                self._generate_model_response,
                payload.api_key,
                model_name,
                contents,
                remaining_tool_calls > 0,
            )
            model_content = response.candidates[0].content
            function_calls = [
                part.function_call for part in model_content.parts if getattr(part, "function_call", None)
            ]
            if function_calls and remaining_tool_calls > 0:
                contents.append(model_content)
                response_parts: list[Any] = []
                for function_call in function_calls:
                    if remaining_tool_calls <= 0:
                        break
                    result, action = await self._execute_tool_call(
                        function_call.name,
                        dict(function_call.args or {}),
                        api_key=payload.api_key,
                        model_name=model_name,
                        article_index=article_index,
                        last_search_index=last_search_index,
                        selected_set=selected_set,
                        used_article_ids=used_article_ids,
                    )
                    executed_actions.append(action)
                    step_notes.append(self._step_note_from_action(action))
                    self._log(
                        "assistant_tool_result",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        action=action.model_dump(),
                    )
                    if self._is_terminal_empty_search_action(action):
                        terminal_answer = self._build_no_results_answer(action)
                        break
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
                if terminal_answer is not None:
                    answer = terminal_answer
                    break
                if response_parts:
                    contents.append(types.Content(role="user", parts=response_parts))
                    continue

            answer = self._extract_text_response(response).strip()
            if not answer and executed_actions:
                finalizer_needed = True
            answer = answer or "No answer could be generated."
            break

        if finalizer_needed:
            answer = await self._run_finalizer(
                api_key=payload.api_key,
                model_name=model_name,
                contents=contents,
                fallback_answer=answer,
            )

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_chat_final",
            thread_id=thread_id,
            mode="fast",
            model=model_name,
            answer=answer,
            used_article_ids=sorted(used_article_ids),
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )

        return HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode="fast",
            used_article_ids=sorted(used_article_ids),
            history_size=len(thread_state.history),
            thinking=self._build_thinking_summary(
                payload.thinking_level,
                total_articles=len(payload.articles),
                selected_count=len(selected_set),
                steps=step_notes,
                used_article_ids=sorted(used_article_ids),
            ),
            executed_actions=executed_actions,
        )

    async def chat_stream(self, payload: HelperChatRequest) -> AsyncIterator[dict[str, Any]]:
        model_target = self._resolve_model_target(payload.model)
        model_name = model_target.model_name
        thread_id = payload.thread_id or f"thread_{uuid4().hex[:16]}"
        thread_state = self.thread_cache.get(thread_id) or HelperThreadState()
        self._log(
            "assistant_stream_start",
            thread_id=thread_id,
            mode=payload.mode,
            model=model_name,
            message=payload.message,
            selected_ids=payload.selected_ids,
            article_count=len(payload.articles),
            thinking_level=payload.thinking_level,
        )
        if model_target.provider in {"ollama", "llamacpp"}:
            async for event in self._chat_stream_with_ollama(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
                provider=model_target.provider,
            ):
                yield event
            return

        if payload.mode == RESEARCH_AGENT_MODE:
            async for event in self._chat_stream_research_agent(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
            ):
                yield event
            return

        if payload.mode != "fast":
            answer = "This assistant mode is not available yet. Use Normal Mode or Research Agent Mode."
            self._append_history(thread_state, payload.message, answer)
            self.thread_cache.set(thread_id, thread_state)
            self._log(
                "assistant_stream_final",
                thread_id=thread_id,
                mode=payload.mode,
                model=model_name,
                answer=answer,
                used_article_ids=[],
                executed_actions=[],
            )
            response = HelperChatResponse(
                thread_id=thread_id,
                answer=answer,
                model=model_name,
                mode=payload.mode,
                history_size=len(thread_state.history),
            )
            yield {
                "type": "start",
                "thread_id": thread_id,
                "model": model_name,
                "mode": payload.mode,
            }
            yield {"type": "final", "response": response.model_dump()}
            return

        self._require_gemini_api_key(payload.api_key)
        client = create_genai_client(payload.api_key)
        _genai, types = load_genai_sdk()
        article_index = {article.id: article for article in payload.articles}
        last_search_index: dict[int, HelperArticle] = {}
        selected_set = set(payload.selected_ids)
        used_article_ids: set[int] = set()
        executed_actions: list[HelperExecutedAction] = []
        step_notes: list[str] = []
        streamed_thoughts: list[str] = []

        contents: list[Any] = [
            types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
            for item in thread_state.history
        ]
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(text=self._build_fast_prompt(payload, today_stamp=date.today().isoformat()))],
            )
        )

        yield {
            "type": "start",
            "thread_id": thread_id,
            "model": model_name,
            "mode": "fast",
        }
        yield {"type": "status", "text": "Analyzing the request."}

        remaining_tool_calls = MAX_FAST_TOOL_CALLS
        answer = "No answer could be generated."
        finalizer_needed = False
        terminal_answer: str | None = None

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
                    self._log(
                        "assistant_tool_call",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        call_id=call_id,
                        name=function_call.name,
                        args=dict(function_call.args or {}),
                    )
                    yield {
                        "type": "tool_call",
                        "call_id": call_id,
                        "action": {
                            "type": "tool_call",
                            "name": function_call.name,
                            "title": self._tool_pending_title(function_call.name),
                            "status": "running",
                            "details": dict(function_call.args or {}),
                        },
                    }
                    result, action = await self._execute_tool_call(
                        function_call.name,
                        dict(function_call.args or {}),
                        api_key=payload.api_key,
                        model_name=model_name,
                        article_index=article_index,
                        last_search_index=last_search_index,
                        selected_set=selected_set,
                        used_article_ids=used_article_ids,
                    )
                    executed_actions.append(action)
                    step_notes.append(self._step_note_from_action(action))
                    self._log(
                        "assistant_tool_result",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        call_id=call_id,
                        action=action.model_dump(),
                    )
                    yield {
                        "type": "tool_result",
                        "call_id": call_id,
                        "action": action.model_dump(),
                    }
                    if self._is_terminal_empty_search_action(action):
                        terminal_answer = self._build_no_results_answer(action)
                        yield {"type": "answer_delta", "text": terminal_answer}
                        break
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
                if terminal_answer is not None:
                    answer = terminal_answer
                    break
                if response_parts:
                    contents.append(types.Content(role="user", parts=response_parts))
                    continue

            answer = "".join(answer_chunks).strip()
            if not answer and executed_actions:
                finalizer_needed = True
            answer = answer or "No answer could be generated."
            break

        if finalizer_needed:
            yield {"type": "status", "text": "Combining tool results."}
            final_contents = [
                *contents,
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=HELPER_FINALIZER_PROMPT
                        )
                    ],
                ),
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
            answer_chunks = []
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
        self._log(
            "assistant_stream_final",
            thread_id=thread_id,
            mode="fast",
            model=model_name,
            answer=answer,
            used_article_ids=sorted(used_article_ids),
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )

        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode="fast",
            used_article_ids=sorted(used_article_ids),
            history_size=len(thread_state.history),
            thinking=(
                "\n\n".join(streamed_thoughts).strip()
                if streamed_thoughts
                else self._build_thinking_summary(
                    payload.thinking_level,
                    total_articles=len(payload.articles),
                    selected_count=len(selected_set),
                    steps=step_notes,
                    used_article_ids=sorted(used_article_ids),
                )
            ),
            executed_actions=executed_actions,
        )
        yield {"type": "final", "response": response.model_dump()}

    async def _chat_with_ollama(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
        provider: str = "ollama",
    ) -> HelperChatResponse:
        if payload.mode == RESEARCH_AGENT_MODE:
            return await self._chat_research_agent_ollama(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
                provider=provider,
            )

        if payload.mode != "fast":
            answer = "This assistant mode is not available yet. Use Normal Mode or Research Agent Mode."
            self._append_history(thread_state, payload.message, answer)
            self.thread_cache.set(thread_id, thread_state)
            self._log(
                "assistant_chat_final",
                thread_id=thread_id,
                mode=payload.mode,
                model=model_name,
                answer=answer,
                used_article_ids=[],
                executed_actions=[],
            )
            return HelperChatResponse(
                thread_id=thread_id,
                answer=answer,
                model=model_name,
                mode=payload.mode,
                history_size=len(thread_state.history),
            )

        article_index = {article.id: article for article in payload.articles}
        last_search_index: dict[int, HelperArticle] = {}
        selected_set = set(payload.selected_ids)
        used_article_ids: set[int] = set()
        executed_actions: list[HelperExecutedAction] = []
        step_notes: list[str] = []
        thinking_notes: list[str] = []
        messages = [
            {"role": "system", "content": self._fast_mode_system_instruction()},
            *self._history_to_ollama_messages(thread_state.history),
            {"role": "user", "content": self._build_fast_prompt(payload, today_stamp=date.today().isoformat())},
        ]
        remaining_tool_calls = MAX_FAST_TOOL_CALLS
        answer = "No answer could be generated."
        finalizer_needed = False

        while True:
            response = await self._local_llm_chat(
                provider=provider,
                model=model_name,
                messages=messages,
                tools=self._build_ollama_fast_toolset() if remaining_tool_calls > 0 else None,
                thinking_level=payload.thinking_level,
                request_user_agent=self._ollama_request_user_agent(),
            )
            message = response.get("message") or {}
            answer_text = str(message.get("content") or "").strip()
            thinking_text = str(message.get("thinking") or "").strip()
            if thinking_text:
                thinking_notes.append(thinking_text)
            tool_calls = extract_ollama_tool_calls(message)
            if tool_calls and remaining_tool_calls > 0:
                messages.append(
                    self._ollama_assistant_message(
                        content=answer_text,
                        thinking=thinking_text,
                        tool_calls=[call.raw for call in tool_calls],
                    )
                )
                for call in tool_calls:
                    if remaining_tool_calls <= 0:
                        break
                    result, action = await self._execute_tool_call(
                        call.name,
                        call.args,
                        api_key=payload.api_key,
                        model_name=model_name,
                        article_index=article_index,
                        last_search_index=last_search_index,
                        selected_set=selected_set,
                        used_article_ids=used_article_ids,
                    )
                    executed_actions.append(action)
                    step_notes.append(self._step_note_from_action(action))
                    self._log(
                        "assistant_tool_result",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        call_id=call.call_id,
                        action=action.model_dump(),
                    )
                    if self._is_terminal_empty_search_action(action):
                        answer = self._build_no_results_answer(action)
                        self._append_history(thread_state, payload.message, answer)
                        self.thread_cache.set(thread_id, thread_state)
                        return HelperChatResponse(
                            thread_id=thread_id,
                            answer=answer,
                            model=model_name,
                            mode="fast",
                            used_article_ids=sorted(used_article_ids),
                            history_size=len(thread_state.history),
                            thinking="\n\n".join(thinking_notes).strip()
                            or self._build_thinking_summary(
                                payload.thinking_level,
                                total_articles=len(payload.articles),
                                selected_count=len(selected_set),
                                steps=step_notes,
                                used_article_ids=sorted(used_article_ids),
                            ),
                            executed_actions=executed_actions,
                        )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": call.name,
                            "content": self._ollama_tool_message_content(result),
                        }
                    )
                    remaining_tool_calls -= 1
                continue

            if answer_text:
                messages.append(self._ollama_assistant_message(content=answer_text))
            answer = answer_text or "No answer could be generated."
            if not answer_text and executed_actions:
                finalizer_needed = True
            break

        if finalizer_needed:
            final_response = await self._local_llm_chat(
                provider=provider,
                model=model_name,
                messages=[*messages, {"role": "user", "content": HELPER_FINALIZER_PROMPT}],
                tools=None,
                thinking_level=payload.thinking_level,
                request_user_agent=self._ollama_request_user_agent(),
            )
            final_message = final_response.get("message") or {}
            final_answer = str(final_message.get("content") or "").strip()
            final_thinking = str(final_message.get("thinking") or "").strip()
            if final_thinking:
                thinking_notes.append(final_thinking)
            answer = final_answer or answer

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_chat_final",
            thread_id=thread_id,
            mode="fast",
            model=model_name,
            answer=answer,
            used_article_ids=sorted(used_article_ids),
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        return HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode="fast",
            used_article_ids=sorted(used_article_ids),
            history_size=len(thread_state.history),
            thinking="\n\n".join(thinking_notes).strip()
            or self._build_thinking_summary(
                payload.thinking_level,
                total_articles=len(payload.articles),
                selected_count=len(selected_set),
                steps=step_notes,
                used_article_ids=sorted(used_article_ids),
            ),
            executed_actions=executed_actions,
        )

    async def _chat_stream_with_ollama(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
        provider: str = "ollama",
    ) -> AsyncIterator[dict[str, Any]]:
        if payload.mode == RESEARCH_AGENT_MODE:
            async for event in self._chat_stream_research_agent_ollama(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
                provider=provider,
            ):
                yield event
            return

        if payload.mode != "fast":
            answer = "This assistant mode is not available yet. Use Normal Mode or Research Agent Mode."
            self._append_history(thread_state, payload.message, answer)
            self.thread_cache.set(thread_id, thread_state)
            response = HelperChatResponse(
                thread_id=thread_id,
                answer=answer,
                model=model_name,
                mode=payload.mode,
                history_size=len(thread_state.history),
            )
            yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": payload.mode}
            yield {"type": "final", "response": response.model_dump()}
            return

        article_index = {article.id: article for article in payload.articles}
        last_search_index: dict[int, HelperArticle] = {}
        selected_set = set(payload.selected_ids)
        used_article_ids: set[int] = set()
        executed_actions: list[HelperExecutedAction] = []
        step_notes: list[str] = []
        streamed_thoughts: list[str] = []
        messages = [
            {"role": "system", "content": self._fast_mode_system_instruction()},
            *self._history_to_ollama_messages(thread_state.history),
            {"role": "user", "content": self._build_fast_prompt(payload, today_stamp=date.today().isoformat())},
        ]

        yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": "fast"}

        remaining_tool_calls = MAX_FAST_TOOL_CALLS
        answer = "No answer could be generated."
        finalizer_needed = False

        while True:
            answer_chunks: list[str] = []
            thinking_chunks: list[str] = []
            tool_calls: list[Any] = []
            seen_tool_call_keys: set[tuple[str, str]] = set()
            tool_turn_active = False
            async for chunk in self._local_llm_chat_stream(
                provider=provider,
                model=model_name,
                messages=messages,
                tools=self._build_ollama_fast_toolset() if remaining_tool_calls > 0 else None,
                thinking_level=payload.thinking_level,
                keep_alive="10m",
                timeout_seconds=900.0,
                request_user_agent=self._ollama_request_user_agent(),
            ):
                if chunk.get("type") == "status":
                    yield chunk
                    continue
                message = chunk.get("message") or {}
                thinking_text = str(message.get("thinking") or "")
                if thinking_text:
                    thinking_chunks.append(thinking_text)
                    streamed_thoughts.append(thinking_text)
                    yield {"type": "thinking_delta", "text": thinking_text}
                chunk_tool_calls = extract_ollama_tool_calls(message)
                if chunk_tool_calls:
                    tool_turn_active = True
                for call in chunk_tool_calls:
                    call_key = (call.name, json.dumps(call.args, sort_keys=True))
                    if call_key in seen_tool_call_keys:
                        continue
                    seen_tool_call_keys.add(call_key)
                    tool_calls.append(call)
                answer_text = str(message.get("content") or "")
                if answer_text:
                    answer_chunks.append(answer_text)
                if answer_text and not tool_turn_active:
                    yield {"type": "answer_delta", "text": answer_text}
            answer_text = "".join(answer_chunks).strip()
            if tool_calls and remaining_tool_calls > 0:
                messages.append(
                    self._ollama_assistant_message(
                        content=answer_text.strip(),
                        thinking="".join(thinking_chunks).strip(),
                        tool_calls=[call.raw for call in tool_calls],
                    )
                )
                for call in tool_calls:
                    if remaining_tool_calls <= 0:
                        break
                    self._log(
                        "assistant_tool_call",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        call_id=call.call_id,
                        name=call.name,
                        args=call.args,
                    )
                    yield {
                        "type": "tool_call",
                        "call_id": call.call_id,
                        "action": {
                            "type": "tool_call",
                            "name": call.name,
                            "title": self._tool_pending_title(call.name),
                            "status": "running",
                            "details": call.args,
                        },
                    }
                    yield {"type": "status", "text": f"Running tool: {call.name}"}
                    result, action = await self._execute_tool_call(
                        call.name,
                        call.args,
                        api_key=payload.api_key,
                        model_name=model_name,
                        article_index=article_index,
                        last_search_index=last_search_index,
                        selected_set=selected_set,
                        used_article_ids=used_article_ids,
                    )
                    executed_actions.append(action)
                    step_notes.append(self._step_note_from_action(action))
                    self._log(
                        "assistant_tool_result",
                        thread_id=thread_id,
                        mode="fast",
                        model=model_name,
                        call_id=call.call_id,
                        action=action.model_dump(),
                    )
                    yield {"type": "tool_result", "call_id": call.call_id, "action": action.model_dump()}
                    if self._is_terminal_empty_search_action(action):
                        answer = self._build_no_results_answer(action)
                        yield {"type": "answer_delta", "text": answer}
                        self._append_history(thread_state, payload.message, answer)
                        self.thread_cache.set(thread_id, thread_state)
                        response_payload = HelperChatResponse(
                            thread_id=thread_id,
                            answer=answer,
                            model=model_name,
                            mode="fast",
                            used_article_ids=sorted(used_article_ids),
                            history_size=len(thread_state.history),
                            thinking="\n\n".join(streamed_thoughts).strip()
                            or self._build_thinking_summary(
                                payload.thinking_level,
                                total_articles=len(payload.articles),
                                selected_count=len(selected_set),
                                steps=step_notes,
                                used_article_ids=sorted(used_article_ids),
                            ),
                            executed_actions=executed_actions,
                        )
                        yield {"type": "final", "response": response_payload.model_dump()}
                        return
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": call.name,
                            "content": self._ollama_tool_message_content(result),
                        }
                    )
                    remaining_tool_calls -= 1
                continue

            answer = answer_text or "No answer could be generated."
            if answer_text:
                messages.append(self._ollama_assistant_message(content=answer_text))
            if not answer_text and executed_actions:
                finalizer_needed = True
            break

        if finalizer_needed:
            yield {"type": "status", "text": "Combining tool results."}
            answer_chunks: list[str] = []
            async for chunk in self._local_llm_chat_stream(
                provider=provider,
                model=model_name,
                messages=[*messages, {"role": "user", "content": HELPER_FINALIZER_PROMPT}],
                tools=None,
                thinking_level=payload.thinking_level,
                keep_alive="10m",
                timeout_seconds=900.0,
                request_user_agent=self._ollama_request_user_agent(),
            ):
                if chunk.get("type") == "status":
                    yield chunk
                    continue
                final_message = chunk.get("message") or {}
                final_thinking = str(final_message.get("thinking") or "")
                if final_thinking:
                    streamed_thoughts.append(final_thinking)
                    yield {"type": "thinking_delta", "text": final_thinking}
                final_text = str(final_message.get("content") or "")
                if final_text:
                    answer_chunks.append(final_text)
                    yield {"type": "answer_delta", "text": final_text}
            final_answer = "".join(answer_chunks).strip()
            if final_answer:
                answer = final_answer

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_stream_final",
            thread_id=thread_id,
            mode="fast",
            model=model_name,
            answer=answer,
            used_article_ids=sorted(used_article_ids),
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode="fast",
            used_article_ids=sorted(used_article_ids),
            history_size=len(thread_state.history),
            thinking="\n\n".join(streamed_thoughts).strip()
            or self._build_thinking_summary(
                payload.thinking_level,
                total_articles=len(payload.articles),
                selected_count=len(selected_set),
                steps=step_notes,
                used_article_ids=sorted(used_article_ids),
            ),
            executed_actions=executed_actions,
        )
        yield {"type": "final", "response": response.model_dump()}

    async def _chat_research_agent(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
    ) -> HelperChatResponse:
        self._require_gemini_api_key(payload.api_key)
        _genai, types = load_genai_sdk()
        has_existing_plan = bool(thread_state.research_plan)
        contents = self._research_agent_contents(types, thread_state, payload)
        response = await asyncio.to_thread(
            self._generate_research_response,
            payload.api_key,
            model_name,
            contents,
            True,
            not has_existing_plan,
        )
        model_content = response.candidates[0].content
        function_calls = [
            part.function_call for part in model_content.parts if getattr(part, "function_call", None)
        ]
        executed_actions: list[HelperExecutedAction] = []
        if function_calls:
            contents.append(model_content)
            response_parts: list[Any] = []
            for function_call in function_calls[:1]:
                result, action = await self._execute_research_tool_call(
                    function_call.name,
                    dict(function_call.args or {}),
                    previous_plan=thread_state.research_plan,
                )
                executed_actions.append(action)
                thread_state.research_plan = action.details["plan"]
                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            id=getattr(function_call, "id", None),
                            name=function_call.name,
                            response={"result": result},
                        )
                    )
                )
            if response_parts:
                contents.append(types.Content(role="user", parts=response_parts))
                answer = await self._run_research_finalizer(
                    api_key=payload.api_key,
                    model_name=model_name,
                    contents=contents,
                    fallback_answer=self._research_plan_preview_text(executed_actions[0].details["plan"]),
                )
            else:
                answer = self._extract_text_response(response).strip() or "Research plan could not be created."
        elif has_existing_plan:
            answer = self._extract_text_response(response).strip() or "I can revise the plan or help you access papers from it."
        else:
            answer = self._extract_text_response(response).strip() or "Research plan could not be created."

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_chat_final",
            thread_id=thread_id,
            mode=RESEARCH_AGENT_MODE,
            model=model_name,
            answer=answer,
            used_article_ids=[],
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        return HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode=RESEARCH_AGENT_MODE,
            history_size=len(thread_state.history),
            executed_actions=executed_actions,
        )

    async def _chat_stream_research_agent(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
    ) -> AsyncIterator[dict[str, Any]]:
        self._require_gemini_api_key(payload.api_key)
        client = create_genai_client(payload.api_key)
        _genai, types = load_genai_sdk()
        has_existing_plan = bool(thread_state.research_plan)
        contents = self._research_agent_contents(types, thread_state, payload)
        executed_actions: list[HelperExecutedAction] = []
        streamed_thoughts: list[str] = []

        yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": RESEARCH_AGENT_MODE}
        yield {"type": "status", "text": "Creating the Researcher Agent plan."}

        stream = await client.aio.models.generate_content_stream(
            model=model_name,
            contents=contents,
            config=self._build_research_generate_config(
                types,
                allow_tools=True,
                thinking_level=payload.thinking_level,
                include_thoughts=payload.thinking_level != "off",
                force_tool=not has_existing_plan,
            ),
        )
        collected_parts: list[Any] = []
        function_calls: list[Any] = []
        seen_function_calls: set[str] = set()
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

        if function_calls:
            contents.append(types.Content(role="model", parts=collected_parts))
            response_parts: list[Any] = []
            for function_call in function_calls[:1]:
                call_id = getattr(function_call, "id", None) or f"call_{uuid4().hex[:8]}"
                args = self._apply_criteria_enabled(
                    dict(function_call.args or {}),
                    bool(getattr(payload, "research_criteria_enabled", True)),
                )
                self._log(
                    "assistant_tool_call",
                    thread_id=thread_id,
                    mode=RESEARCH_AGENT_MODE,
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
                        "title": self._tool_pending_title(function_call.name),
                        "status": "running",
                        "details": args,
                    },
                }
                result, action = await self._execute_research_tool_call(
                    function_call.name,
                    args,
                    previous_plan=thread_state.research_plan,
                )
                executed_actions.append(action)
                thread_state.research_plan = action.details["plan"]
                self._log(
                    "assistant_tool_result",
                    thread_id=thread_id,
                    mode=RESEARCH_AGENT_MODE,
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
            contents.append(types.Content(role="user", parts=response_parts))
            yield {"type": "status", "text": "Preparing the plan preview."}
            answer_chunks: list[str] = []
            final_stream = await client.aio.models.generate_content_stream(
                model=model_name,
                contents=[
                    *contents,
                    types.Content(role="user", parts=[types.Part(text=RESEARCH_PLAN_FINALIZER_PROMPT)]),
                ],
                config=self._build_research_generate_config(
                    types,
                    allow_tools=False,
                    thinking_level=payload.thinking_level,
                    include_thoughts=payload.thinking_level != "off",
                    force_tool=False,
                ),
            )
            async for chunk in final_stream:
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
            answer = "".join(answer_chunks).strip()
            if not answer and executed_actions:
                answer = self._research_plan_preview_text(executed_actions[0].details["plan"])
        elif has_existing_plan:
            answer = "".join(
                getattr(part, "text", None) or ""
                for part in collected_parts
                if not getattr(part, "thought", None) and getattr(part, "text", None)
            ).strip()
            if not answer:
                answer = "I can revise the current plan or help you access exact papers with database-specific queries."
            if answer:
                yield {"type": "answer_delta", "text": answer}
        else:
            answer = "Research plan could not be created because the model did not call the planning tool."
            yield {"type": "answer_delta", "text": answer}

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_stream_final",
            thread_id=thread_id,
            mode=RESEARCH_AGENT_MODE,
            model=model_name,
            answer=answer,
            used_article_ids=[],
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode=RESEARCH_AGENT_MODE,
            history_size=len(thread_state.history),
            thinking="\n\n".join(streamed_thoughts).strip() or None,
            executed_actions=executed_actions,
        )
        yield {"type": "final", "response": response.model_dump()}

    async def _chat_research_agent_ollama(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
        provider: str = "ollama",
    ) -> HelperChatResponse:
        messages = [
            {"role": "system", "content": build_research_agent_system_instruction()},
            *self._history_to_ollama_messages(thread_state.history),
            {
                "role": "user",
                "content": build_research_agent_prompt(
                    payload,
                    today_stamp=date.today().isoformat(),
                    current_plan=thread_state.research_plan,
                ),
            },
        ]
        response = await self._local_llm_chat(
            provider=provider,
            model=model_name,
            messages=messages,
            tools=self._build_ollama_research_toolset(),
            thinking_level=payload.thinking_level,
            request_user_agent=self._ollama_request_user_agent(),
        )
        message = response.get("message") or {}
        tool_calls = extract_ollama_tool_calls(message)
        executed_actions: list[HelperExecutedAction] = []
        thinking_text = str(message.get("thinking") or "").strip()
        if tool_calls:
            for call in tool_calls[:1]:
                args = self._apply_criteria_enabled(
                    call.args,
                    bool(getattr(payload, "research_criteria_enabled", True)),
                )
                result, action = await self._execute_research_tool_call(
                    call.name,
                    args,
                    previous_plan=thread_state.research_plan,
                )
                executed_actions.append(action)
                thread_state.research_plan = action.details["plan"]
                messages.append(
                    self._ollama_assistant_message(
                        content=str(message.get("content") or "").strip(),
                        thinking=thinking_text,
                        tool_calls=[call.raw],
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "content": self._ollama_tool_message_content(result),
                    }
                )
            final_response = await self._local_llm_chat(
                provider=provider,
                model=model_name,
                messages=[*messages, {"role": "user", "content": RESEARCH_PLAN_FINALIZER_PROMPT}],
                tools=None,
                thinking_level=payload.thinking_level,
                request_user_agent=self._ollama_request_user_agent(),
            )
            final_message = final_response.get("message") or {}
            answer = str(final_message.get("content") or "").strip()
            final_thinking = str(final_message.get("thinking") or "").strip()
            thinking = "\n\n".join(item for item in [thinking_text, final_thinking] if item).strip() or None
        elif thread_state.research_plan:
            answer = str(message.get("content") or "").strip() or "I can revise the current plan or help you access exact papers with database-specific queries."
            thinking = thinking_text or None
        else:
            answer = "Research plan could not be created because the model did not call the planning tool."
            thinking = thinking_text or None
        if not answer and executed_actions:
            answer = self._research_plan_preview_text(executed_actions[0].details["plan"])
        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        return HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode=RESEARCH_AGENT_MODE,
            history_size=len(thread_state.history),
            thinking=thinking,
            executed_actions=executed_actions,
        )

    async def _chat_stream_research_agent_ollama_three_stage(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
        provider: str = "ollama",
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": RESEARCH_AGENT_MODE}
        yield {"type": "status", "text": "SearchPlannerAgent is creating sources, branches, and filters."}

        executed_actions: list[HelperExecutedAction] = []
        streamed_thoughts: list[str] = []
        stage_outputs: dict[str, dict[str, Any]] = {}

        stages = [
            {
                "stage": "search",
                "agent": "SearchPlannerAgent",
                "tool_name": "create_search_plan",
                "title": "Search plan created",
                "status": "SearchPlannerAgent is creating sources, branches, and filters.",
                "schema": self._research_search_plan_parameters_schema(),
                "tools": self._build_ollama_research_stage_toolset(
                    name="create_search_plan",
                    description="Create only the search planning stage: topic, objective, sources, year filters, branches, and query concepts.",
                    parameters=self._research_search_plan_parameters_schema(),
                ),
            },
            {
                "stage": "criteria",
                "agent": "CriteriaPlannerAgent",
                "tool_name": "create_criteria_plan",
                "title": "Criteria plan created",
                "status": "CriteriaPlannerAgent is creating screening and exclusion criteria.",
                "schema": self._research_criteria_plan_parameters_schema(),
                "tools": self._build_ollama_research_stage_toolset(
                    name="create_criteria_plan",
                    description="Create only the criteria planning stage from the validated search plan context.",
                    parameters=self._research_criteria_plan_parameters_schema(),
                ),
            },
            {
                "stage": "extraction",
                "agent": "ExtractionPlannerAgent",
                "tool_name": "create_extraction_plan",
                "title": "Extraction plan created",
                "status": "ExtractionPlannerAgent is creating PDF/full-text questions and evidence rules.",
                "schema": self._research_extraction_plan_parameters_schema(),
                "tools": self._build_ollama_research_stage_toolset(
                    name="create_extraction_plan",
                    description="Create only the PDF/full-text extraction stage from search and criteria context.",
                    parameters=self._research_extraction_plan_parameters_schema(),
                ),
            },
        ]
        if not bool(getattr(payload, "research_criteria_enabled", True)):
            stages = [stage for stage in stages if stage["stage"] != "criteria"]

        for stage in stages:
            yield {"type": "status", "text": stage["status"]}
            stage_call_id = f"{stage['stage']}_plan"
            yield {
                "type": "tool_call",
                "call_id": stage_call_id,
                "action": {
                    "type": "tool_call",
                    "name": stage["tool_name"],
                    "title": self._tool_pending_title(stage["tool_name"]),
                    "status": "running",
                    "details": {
                        "agent": stage["agent"],
                        "stage": stage["stage"],
                    },
                },
            }
            context = {
                "today": date.today().isoformat(),
                "user_request": payload.message.strip(),
                "loaded_article_count": len(payload.articles),
                "selected_article_ids": payload.selected_ids,
                "criteria_enabled": bool(getattr(payload, "research_criteria_enabled", True)),
                "search_plan": stage_outputs.get("search"),
                "criteria_plan": stage_outputs.get("criteria"),
            }
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"You are {stage['agent']} inside Native Researcher. "
                        f"Call `{stage['tool_name']}` exactly once. Do not answer in prose. "
                        "Planning does not execute database searches, screening, downloads, or PDF scans. "
                        "Keep the plan compact and executable. "
                        "If the request names a complete series such as D1-D5, make one branch per member and keep each branch query focused on target aliases only. "
                        "Put shared method/evidence concepts in shared_query_concepts instead of repeating them in every branch. "
                        "Do not add disease-model terms, organisms, or mechanisms that the user did not request. "
                        "For CriteriaPlannerAgent, produce a small auditable rubric with required target match, primary study type, intervention/exposure match, and requested evidence type. "
                        "For ExtractionPlannerAgent, write data-oriented questions that can be answered from full text. "
                        "Extraction questions should capture target subtype, intervention or ligand, assay/model, measured endpoint, effect direction, evidence quote, and uncertainty when relevant. "
                        "Use only two answer formats: exact_text for direct quoted phrases/sentences, or factual_answer for a concise extracted fact."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "stage": stage["stage"],
                            "context": context,
                            "required_tool": stage["tool_name"],
                            "required_schema": stage["schema"],
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
            call_args: dict[str, Any] | None = None
            raw_answer = ""
            raw_thinking = ""
            for attempt in range(2):
                if attempt:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                f"You did not call `{stage['tool_name']}`. "
                                f"Call `{stage['tool_name']}` now with valid arguments only. No prose."
                            ),
                        }
                    )
                async for chunk in self._local_llm_chat_stream(
                    provider=provider,
                    model=model_name,
                    messages=messages,
                    tools=stage["tools"],
                    thinking_level=payload.thinking_level,
                    **(
                        {
                            "tool_choice": {
                                "type": "function",
                                "function": {"name": stage["tool_name"]},
                            }
                        }
                        if provider == "llamacpp"
                        else {}
                    ),
                    keep_alive="10m",
                    timeout_seconds=900.0,
                    request_user_agent=self._ollama_request_user_agent(),
                ):
                    if chunk.get("type") == "status":
                        yield chunk
                        continue
                    message = chunk.get("message") or {}
                    thinking = str(message.get("thinking") or "")
                    if thinking:
                        raw_thinking += thinking
                        streamed_thoughts.append(thinking)
                        yield {"type": "thinking_delta", "text": thinking}
                    content = str(message.get("content") or "")
                    if content:
                        raw_answer += content
                    for call in extract_ollama_tool_calls(message):
                        if call.name != stage["tool_name"]:
                            continue
                        call_args = call.args
                        break
                    if call_args is not None:
                        break
                if call_args is not None:
                    break
            if call_args is None:
                raise RuntimeError(f"{stage['agent']} did not call `{stage['tool_name']}`.")
            stage_outputs[stage["stage"]] = dict(call_args)
            action = HelperExecutedAction(
                type="tool_call",
                name=str(stage["tool_name"]),
                title=str(stage["title"]),
                status="success",
                details={
                    "agent": stage["agent"],
                    "stage": stage["stage"],
                    "output": dict(call_args),
                },
            )
            executed_actions.append(action)
            yield {
                "type": "tool_result",
                "call_id": stage_call_id,
                "action": action.model_dump(),
            }

        merged_args: dict[str, Any] = {}
        for stage_name in ("search", "criteria", "extraction"):
            merged_args.update(stage_outputs.get(stage_name) or {})
        if not bool(getattr(payload, "research_criteria_enabled", True)):
            merged_args["criteria_mode"] = "disabled"
            merged_args["screening_criteria"] = []
            merged_args["exclusion_criteria"] = []
        plan = self._normalize_research_plan(merged_args)
        thread_state.research_plan = plan
        plan_action = HelperExecutedAction(
            type="tool_call",
            name="create_research_plan",
            title="Research plan merged",
            status="success",
            details={
                "plan": plan,
                "execution_state": "planned",
                "revision_state": "created",
            },
        )
        executed_actions.append(plan_action)
        yield {
            "type": "tool_result",
            "call_id": "research_plan_merged",
            "action": plan_action.model_dump(),
        }
        answer = self._research_plan_preview_text(plan)
        yield {"type": "answer_delta", "text": answer}
        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_stream_final",
            thread_id=thread_id,
            mode=RESEARCH_AGENT_MODE,
            model=model_name,
            answer=answer,
            used_article_ids=[],
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode=RESEARCH_AGENT_MODE,
            history_size=len(thread_state.history),
            thinking="\n\n".join(streamed_thoughts).strip() or None,
            executed_actions=executed_actions,
        )
        yield {"type": "final", "response": response.model_dump()}

    async def _chat_stream_research_agent_ollama(
        self,
        payload: HelperChatRequest,
        *,
        thread_id: str,
        thread_state: HelperThreadState,
        model_name: str,
        provider: str = "ollama",
    ) -> AsyncIterator[dict[str, Any]]:
        planner_mode = str(getattr(payload, "research_planner_mode", "staged") or "staged").strip().lower()
        if not thread_state.research_plan and planner_mode != "legacy":
            async for event in self._chat_stream_research_agent_ollama_three_stage(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
                provider=provider,
            ):
                yield event
            return

        yield {"type": "start", "thread_id": thread_id, "model": model_name, "mode": RESEARCH_AGENT_MODE}
        yield {"type": "status", "text": "Research Agent is building the first planning tool call."}

        async def stream_ollama_with_heartbeat(
            *,
            heartbeat_text: str,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]] | None,
            force_tool_name: str | None = None,
        ) -> AsyncIterator[dict[str, Any]]:
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

            async def produce_chunks() -> None:
                try:
                    async for chunk in self._local_llm_chat_stream(
                        provider=provider,
                        model=model_name,
                        messages=messages,
                        tools=tools,
                        thinking_level=payload.thinking_level,
                        **(
                            {
                                "tool_choice": {
                                    "type": "function",
                                    "function": {"name": force_tool_name},
                                }
                            }
                            if provider == "llamacpp" and force_tool_name
                            else {}
                        ),
                        keep_alive="10m",
                        timeout_seconds=900.0,
                        request_user_agent=self._ollama_request_user_agent(),
                    ):
                        if chunk.get("type") == "status":
                            queue.put_nowait(chunk)
                            continue
                        queue.put_nowait({"type": "chunk", "chunk": chunk})
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    queue.put_nowait({"type": "error", "error": error})
                finally:
                    queue.put_nowait({"type": "done"})

            producer_task = asyncio.create_task(produce_chunks())
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=8.0)
                    except asyncio.TimeoutError:
                        yield {"type": "status", "text": heartbeat_text}
                        continue
                    if event["type"] == "done":
                        break
                    if event["type"] == "error":
                        raise event["error"]
                    yield event
            finally:
                if not producer_task.done():
                    producer_task.cancel()
                with contextlib.suppress(BaseException):
                    await producer_task

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_research_agent_system_instruction()},
            *(
                self._history_to_ollama_messages(thread_state.history)
                if thread_state.research_plan
                else []
            ),
            {
                "role": "user",
                "content": build_research_agent_prompt(
                    payload,
                    today_stamp=date.today().isoformat(),
                    current_plan=thread_state.research_plan,
                ),
            },
        ]
        executed_actions: list[HelperExecutedAction] = []
        streamed_thoughts: list[str] = []
        answer = "Research plan could not be created because the model did not call the planning tool."
        answer_chunks: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls: list[Any] = []
        seen_tool_call_keys: set[tuple[str, str]] = set()
        tool_turn_active = False

        async for stream_event in stream_ollama_with_heartbeat(
            heartbeat_text="Research Agent is still waiting for the local model to emit the planning call.",
            messages=messages,
            tools=self._build_ollama_research_toolset(),
            force_tool_name="create_research_plan" if provider == "llamacpp" and not thread_state.research_plan else None,
        ):
            if stream_event["type"] == "status":
                yield stream_event
                continue
            message = (stream_event["chunk"].get("message") or {})
            thinking_text = str(message.get("thinking") or "")
            if thinking_text:
                thinking_chunks.append(thinking_text)
                streamed_thoughts.append(thinking_text)
                yield {"type": "thinking_delta", "text": thinking_text}
            chunk_tool_calls = extract_ollama_tool_calls(message)
            if chunk_tool_calls:
                tool_turn_active = True
            for call in chunk_tool_calls:
                call_key = (call.name, json.dumps(call.args, sort_keys=True))
                if call_key in seen_tool_call_keys:
                    continue
                seen_tool_call_keys.add(call_key)
                tool_calls.append(call)
            answer_text = str(message.get("content") or "")
            if answer_text:
                answer_chunks.append(answer_text)
            if answer_text and not tool_turn_active and thread_state.research_plan:
                yield {"type": "answer_delta", "text": answer_text}

        raw_answer = "".join(answer_chunks).strip()
        raw_thinking = "".join(thinking_chunks).strip()
        if not tool_calls and not thread_state.research_plan:
            if raw_answer:
                messages.append(self._ollama_assistant_message(content=raw_answer, thinking=raw_thinking))
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You returned ordinary text instead of the required function call. "
                        "For this first Research Agent turn, call `create_research_plan` now. "
                        "Do not answer in prose before the tool call."
                    ),
                }
            )
            yield {"type": "status", "text": "Research Agent is requesting the required planning tool call again."}
            answer_chunks = []
            thinking_chunks = []
            raw_answer = ""
            raw_thinking = ""
            async for stream_event in stream_ollama_with_heartbeat(
                heartbeat_text="Research Agent is still waiting for the required planning call.",
                messages=messages,
                tools=self._build_ollama_research_toolset(),
                force_tool_name="create_research_plan" if provider == "llamacpp" else None,
            ):
                if stream_event["type"] == "status":
                    yield stream_event
                    continue
                message = stream_event["chunk"].get("message") or {}
                thinking_text = str(message.get("thinking") or "")
                if thinking_text:
                    thinking_chunks.append(thinking_text)
                    streamed_thoughts.append(thinking_text)
                    yield {"type": "thinking_delta", "text": thinking_text}
                for call in extract_ollama_tool_calls(message):
                    call_key = (call.name, json.dumps(call.args, sort_keys=True))
                    if call_key in seen_tool_call_keys:
                        continue
                    seen_tool_call_keys.add(call_key)
                    tool_calls.append(call)
                answer_text = str(message.get("content") or "")
                if answer_text:
                    answer_chunks.append(answer_text)
            raw_answer = "".join(answer_chunks).strip()
            raw_thinking = "".join(thinking_chunks).strip()

        if tool_calls:
            call = tool_calls[0]
            self._log(
                "assistant_tool_call",
                thread_id=thread_id,
                mode=RESEARCH_AGENT_MODE,
                model=model_name,
                call_id=call.call_id,
                name=call.name,
                args=call.args,
            )
            yield {
                "type": "tool_call",
                "call_id": call.call_id,
                "action": {
                    "type": "tool_call",
                    "name": call.name,
                    "title": self._tool_pending_title(call.name),
                    "status": "running",
                    "details": call.args,
                },
            }
            yield {"type": "status", "text": "Research Agent is normalizing the plan."}
            result, action = await self._execute_research_tool_call(
                call.name,
                self._apply_criteria_enabled(
                    call.args,
                    bool(getattr(payload, "research_criteria_enabled", True)),
                ),
                previous_plan=thread_state.research_plan,
            )
            executed_actions.append(action)
            thread_state.research_plan = action.details["plan"]
            self._log(
                "assistant_tool_result",
                thread_id=thread_id,
                mode=RESEARCH_AGENT_MODE,
                model=model_name,
                call_id=call.call_id,
                action=action.model_dump(),
            )
            yield {"type": "tool_result", "call_id": call.call_id, "action": action.model_dump()}
            messages.append(
                self._ollama_assistant_message(
                    content=raw_answer,
                    thinking=raw_thinking,
                    tool_calls=[call.raw],
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_name": call.name,
                    "content": self._ollama_tool_message_content(result),
                }
            )
            if provider == "llamacpp":
                answer = self._research_plan_preview_text(executed_actions[0].details["plan"])
                yield {"type": "answer_delta", "text": answer}
            else:
                yield {"type": "status", "text": "Research Agent is writing the plan preview."}
                final_chunks: list[str] = []
                async for stream_event in stream_ollama_with_heartbeat(
                    heartbeat_text="Research Agent is still writing the plan preview.",
                    messages=[*messages, {"role": "user", "content": RESEARCH_PLAN_FINALIZER_PROMPT}],
                    tools=None,
                ):
                    if stream_event["type"] == "status":
                        yield stream_event
                        continue
                    final_message = stream_event["chunk"].get("message") or {}
                    final_thinking = str(final_message.get("thinking") or "")
                    if final_thinking:
                        streamed_thoughts.append(final_thinking)
                        yield {"type": "thinking_delta", "text": final_thinking}
                    final_text = str(final_message.get("content") or "")
                    if final_text:
                        final_chunks.append(final_text)
                        yield {"type": "answer_delta", "text": final_text}
                answer = "".join(final_chunks).strip()
                if not answer and executed_actions:
                    answer = self._research_plan_preview_text(executed_actions[0].details["plan"])
                    yield {"type": "answer_delta", "text": answer}
        else:
            if raw_answer and thread_state.research_plan:
                answer = raw_answer
            elif not thread_state.research_plan:
                yield {"type": "answer_delta", "text": answer}

        self._append_history(thread_state, payload.message, answer)
        self.thread_cache.set(thread_id, thread_state)
        self._log(
            "assistant_stream_final",
            thread_id=thread_id,
            mode=RESEARCH_AGENT_MODE,
            model=model_name,
            answer=answer,
            used_article_ids=[],
            executed_actions=[action.model_dump() for action in executed_actions],
            history_size=len(thread_state.history),
        )
        response = HelperChatResponse(
            thread_id=thread_id,
            answer=answer,
            model=model_name,
            mode=RESEARCH_AGENT_MODE,
            history_size=len(thread_state.history),
            thinking="\n\n".join(streamed_thoughts).strip() or None,
            executed_actions=executed_actions,
        )
        yield {"type": "final", "response": response.model_dump()}

    def reset(self, thread_id: str) -> None:
        self.thread_cache.delete(thread_id)

    @staticmethod
    def _append_history(
        thread_state: HelperThreadState,
        user_message: str,
        answer: str,
    ) -> None:
        thread_state.history.extend(
            [
                {"role": "user", "text": user_message},
                {"role": "model", "text": answer},
            ]
        )
        thread_state.history = thread_state.history[-12:]

    def _generate_model_response(
        self,
        api_key: str,
        model_name: str,
        contents: list[Any],
        allow_tools: bool,
    ):
        client = create_genai_client(api_key)
        _genai, types = load_genai_sdk()
        return client.models.generate_content(
            model=model_name,
            contents=contents,
            config=self._build_generate_config(types, allow_tools=allow_tools),
        )

    def _generate_final_response(
        self,
        api_key: str,
        model_name: str,
        contents: list[Any],
    ):
        client = create_genai_client(api_key)
        _genai, types = load_genai_sdk()
        final_contents = [
            *contents,
            types.Content(
                role="user",
                parts=[
                    types.Part(text=HELPER_FINALIZER_PROMPT)
                ],
            ),
        ]
        return client.models.generate_content(
            model=model_name,
            contents=final_contents,
            config=self._build_generate_config(types, allow_tools=False),
        )

    def _generate_research_response(
        self,
        api_key: str,
        model_name: str,
        contents: list[Any],
        allow_tools: bool,
        force_tool: bool,
    ):
        client = create_genai_client(api_key)
        _genai, types = load_genai_sdk()
        return client.models.generate_content(
            model=model_name,
            contents=contents,
            config=self._build_research_generate_config(
                types,
                allow_tools=allow_tools,
                force_tool=force_tool,
            ),
        )

    def _generate_research_final_response(
        self,
        api_key: str,
        model_name: str,
        contents: list[Any],
    ):
        client = create_genai_client(api_key)
        _genai, types = load_genai_sdk()
        return client.models.generate_content(
            model=model_name,
            contents=[
                *contents,
                types.Content(role="user", parts=[types.Part(text=RESEARCH_PLAN_FINALIZER_PROMPT)]),
            ],
            config=self._build_research_generate_config(types, allow_tools=False),
        )

    async def _run_research_finalizer(
        self,
        *,
        api_key: str,
        model_name: str,
        contents: list[Any],
        fallback_answer: str,
    ) -> str:
        response = await asyncio.to_thread(
            self._generate_research_final_response,
            api_key,
            model_name,
            contents,
        )
        return self._extract_text_response(response).strip() or fallback_answer

    @staticmethod
    def _research_agent_contents(types: Any, thread_state: HelperThreadState, payload: HelperChatRequest) -> list[Any]:
        contents = [
            types.Content(role=item["role"], parts=[types.Part(text=item["text"])])
            for item in thread_state.history
        ]
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        text=build_research_agent_prompt(
                            payload,
                            today_stamp=date.today().isoformat(),
                            current_plan=thread_state.research_plan,
                        )
                    )
                ],
            )
        )
        return contents

    def _build_research_generate_config(
        self,
        types: Any,
        *,
        allow_tools: bool,
        thinking_level: str = "off",
        include_thoughts: bool = False,
        force_tool: bool = False,
    ):
        config_kwargs: dict[str, Any] = {
            "system_instruction": build_research_agent_system_instruction(),
        }
        thinking_config = HelperAIService._build_thinking_config(
            types,
            thinking_level=thinking_level,
            include_thoughts=include_thoughts,
        )
        if thinking_config is not None:
            config_kwargs["thinking_config"] = thinking_config
        if allow_tools:
            config_kwargs["tools"] = [self._build_research_toolset(types)]
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY if force_tool else types.FunctionCallingConfigMode.AUTO,
                    allowed_function_names=["create_research_plan"],
                )
            )
        return types.GenerateContentConfig(**config_kwargs)

    @staticmethod
    def _build_research_toolset(types: Any):
        return types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="create_research_plan",
                    description=(
                        "Create or revise a structured Deep Research plan. "
                        "This only plans the research workflow; it does not execute searches or screening."
                    ),
                    parameters_json_schema=HelperAIService._research_plan_parameters_schema(),
                )
            ]
        )

    @staticmethod
    def _build_ollama_research_toolset() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_research_plan",
                    "description": (
                        "Create or revise a structured Deep Research plan. "
                        "This only plans the research workflow; it does not execute searches or screening."
                    ),
                    "parameters": HelperAIService._research_plan_parameters_schema(),
                },
            }
        ]

    @staticmethod
    def _build_ollama_research_stage_toolset(
        *,
        name: str,
        description: str,
        parameters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        ]

    @staticmethod
    def _research_search_plan_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "objective": {"type": "string"},
                "target_count": {"type": "integer"},
                "target_count_per_branch": {"type": "integer"},
                "year_start": {"type": "integer"},
                "year_end": {"type": "integer"},
                "databases": {"type": "array", "items": {"type": "string"}},
                "active_databases": {"type": "array", "items": {"type": "string"}},
                "search_branches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["label", "query"],
                    },
                },
                "shared_query_concepts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                },
                "candidate_budget": {
                    "type": "object",
                    "properties": {
                        "target_count": {"type": "integer"},
                        "per_database": {"type": "integer"},
                        "rule": {"type": "string"},
                    },
                },
                "query_expansion_policy": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic", "objective", "search_branches"],
        }

    @staticmethod
    def _research_criteria_plan_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "criteria_mode": {"type": "string"},
                "screening_criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "required": {"type": "boolean"},
                            "weight": {"type": "number"},
                            "scoring_guidance": {"type": "string"},
                        },
                        "required": ["id", "label", "description"],
                    },
                },
                "exclusion_criteria": {"type": "array", "items": {"type": "string"}},
                "screening_json_schema": {"type": "object"},
                "scoring_rule": {"type": "string"},
            },
            "required": ["screening_criteria"],
        }

    @staticmethod
    def _research_extraction_plan_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "extraction_questions": {"type": "array", "items": {"type": "string"}},
                "extraction_question_specs": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "answer_format": {
                                "type": "string",
                                "enum": ["exact_text", "factual_answer"],
                            },
                        },
                        "required": ["question", "answer_format"],
                    },
                    "description": "Precise full-text questions. exact_text requires a direct quote; factual_answer requires a concise fact from the paper.",
                },
                "extraction_fields": {"type": "array", "items": {"type": "string"}},
                "evidence_requirements": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string"},
            },
            "required": ["extraction_questions"],
        }

    @staticmethod
    def _research_plan_parameters_schema() -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "The user's research topic."},
                "objective": {"type": "string", "description": "Concrete research objective."},
                "target_count": {
                    "type": "integer",
                    "description": "Legacy alias for target_count_per_branch.",
                },
                "target_count_per_branch": {
                    "type": "integer",
                    "description": "Desired number of final selected papers per search branch. Defaults to 20.",
                },
                "year_start": {
                    "type": "integer",
                    "description": "Optional lower publication year bound, for example 2019.",
                },
                "year_end": {
                    "type": "integer",
                    "description": "Optional upper publication year bound, for example 2026.",
                },
                "databases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Legacy alias for active_databases.",
                },
                "active_databases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Databases the backend should search, such as PubMed, Europe PMC, OpenAlex, CORE, arXiv.",
                },
                "search_branches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["label", "query"],
                    },
                    "description": (
                        "Executable main search branches. Split explicit user-named targets, subtypes, "
                        "categories, or comparable branches. Put aliases, synonyms, spelling variants, "
                        "abbreviations, and naming variants directly in the query."
                    ),
                },
                "shared_query_concepts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "query": {"type": "string"},
                        },
                        "required": ["query"],
                    },
                    "description": (
                        "Shared evidence query blocks paired with every search branch. "
                        "During execution these blocks are combined into one OR evidence block. "
                        "Use short residue/binding/method synonyms. Prefer 1-3 compact blocks."
                    ),
                },
                "exclusion_criteria": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Criteria that should remove papers.",
                },
                "screening_criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "required": {"type": "boolean"},
                            "weight": {"type": "number"},
                            "scoring_guidance": {"type": "string"},
                        },
                        "required": ["id", "label", "description"],
                    },
                    "description": "Criteria for the Screening Agent to score from 0.0 to 1.0.",
                },
                "candidate_budget": {
                    "type": "object",
                    "properties": {
                        "target_count": {"type": "integer"},
                        "per_database": {
                            "type": "integer",
                            "description": (
                                "Optional explicit override. Omit unless the user requests a specific fetch size; "
                                "the backend default is target_count_per_branch * 2."
                            ),
                        },
                        "rule": {"type": "string"},
                    },
                },
                "screening_json_schema": {
                    "type": "object",
                    "description": "Strict JSON shape expected from the later Screening Agent.",
                },
                "scoring_rule": {"type": "string"},
                "query_expansion_policy": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "open_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "revision_summary": {
                    "type": "string",
                    "description": "Short summary of what changed when revising an existing plan.",
                },
                "notes": {"type": "string"},
                "extraction_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Questions the later PDF extraction agent should answer from full text.",
                },
                "extraction_fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Structured fields to extract from PDF/full text evidence.",
                },
                "evidence_requirements": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Page, section, quote, figure, table, and uncertainty requirements for full-text evidence.",
                },
            },
            "required": ["topic", "objective"],
        }

    def _build_generate_config(
        self,
        types: Any,
        *,
        allow_tools: bool,
        thinking_level: str = "off",
        include_thoughts: bool = False,
    ):
        config_kwargs: dict[str, Any] = {
            "system_instruction": self._fast_mode_system_instruction(),
        }
        thinking_config = HelperAIService._build_thinking_config(
            types,
            thinking_level=thinking_level,
            include_thoughts=include_thoughts,
        )
        if thinking_config is not None:
            config_kwargs["thinking_config"] = thinking_config
        if allow_tools:
            config_kwargs["tools"] = [self._build_fast_toolset(types)]
            config_kwargs["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO
                )
            )
        return types.GenerateContentConfig(**config_kwargs)

    @staticmethod
    def _build_thinking_config(
        types: Any,
        *,
        thinking_level: str,
        include_thoughts: bool,
    ):
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

    @staticmethod
    def _tool_pending_title(name: str) -> str:
        titles = {
            "list_catalog_articles": "Scanning article catalog",
            "search_pubmed": "Searching literature",
            "get_article_details": "Reading article details",
            "create_research_plan": "Creating research plan",
            "create_search_plan": "SearchPlannerAgent planning",
            "create_criteria_plan": "CriteriaPlannerAgent planning",
            "create_extraction_plan": "ExtractionPlannerAgent planning",
        }
        return titles.get(name, name)

    def _build_fast_toolset(self, types: Any):
        source = self._preferred_search_source()
        search_description, query_description = source_tool_description(source)
        return types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="list_catalog_articles",
                    description=(
                        "Quickly scans the loaded catalog using title, article type, and MeSH metadata."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Free-text filter for title and MeSH fields.",
                            },
                            "article_type": {
                                "type": "string",
                                "description": "Optional article type filter.",
                            },
                            "selected_only": {
                                "type": "boolean",
                                "description": "Limit the scan to selected articles only.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum result count, between 1 and 20.",
                            },
                        },
                    },
                ),
                types.FunctionDeclaration(
                    name="search_pubmed",
                    description=search_description,
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": query_description,
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
                                "description": "Maximum number of articles to fetch, between 1 and 100. Defaults to 100 when omitted.",
                            },
                            "article_type": {
                                "type": "string",
                                "description": "Optional article type filter, for example Review, Clinical Trial, or Meta-Analysis.",
                            },
                            "min_cite": {
                                "type": "integer",
                                "description": "Optional minimum citation-count threshold applied after retrieval.",
                            },
                        },
                        "required": ["query"],
                    },
                ),
                types.FunctionDeclaration(
                    name="get_article_details",
                    description=(
                        "Reads abstracts and detailed metadata for specific article IDs. "
                        "You must use this tool before answering abstract-level or detailed article questions. "
                        "Default source is `loaded`; use `last_search` after a new search."
                    ),
                    parameters_json_schema={
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "enum": ["loaded", "last_search"],
                                "description": "Source to read details from.",
                            },
                            "ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of numeric article IDs.",
                            },
                        },
                        "required": ["ids"],
                    },
                ),
            ]
        )

    def _build_ollama_fast_toolset(self) -> list[dict[str, Any]]:
        source = self._preferred_search_source()
        search_description, query_description = source_tool_description(source)
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_catalog_articles",
                    "description": "Quickly scans the loaded catalog using title, article type, and MeSH metadata.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Free-text filter for title and MeSH fields.",
                            },
                            "article_type": {
                                "type": "string",
                                "description": "Optional article type filter.",
                            },
                            "selected_only": {
                                "type": "boolean",
                                "description": "Limit the scan to selected articles only.",
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum result count, between 1 and 20.",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_pubmed",
                    "description": search_description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": query_description,
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
                                "description": "Maximum number of articles to fetch, between 1 and 100. Defaults to 100 when omitted.",
                            },
                            "article_type": {
                                "type": "string",
                                "description": "Optional article type filter, for example Review, Clinical Trial, or Meta-Analysis.",
                            },
                            "min_cite": {
                                "type": "integer",
                                "description": "Optional minimum citation-count threshold applied after retrieval.",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_article_details",
                    "description": (
                        "Reads abstracts and detailed metadata for specific article IDs. "
                        "You must use this tool before answering abstract-level or detailed article questions. "
                        "Default source is `loaded`; use `last_search` after a new search."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "enum": ["loaded", "last_search"],
                                "description": "Source to read details from.",
                            },
                            "ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "List of numeric article IDs.",
                            },
                        },
                        "required": ["ids"],
                    },
                },
            },
        ]

    async def _execute_research_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        previous_plan: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], HelperExecutedAction]:
        if name != "create_research_plan":
            raise ValueError(f"Unknown research tool call: {name}")
        plan = self._normalize_research_plan(args)
        revision_state = "updated" if previous_plan else "created"
        result = {
            "plan": plan,
            "execution_state": "planned",
            "revision_state": revision_state,
            "message": f"Plan {revision_state}. No search, screening, or download has been executed.",
        }
        action = HelperExecutedAction(
            type="tool_call",
            name="create_research_plan",
            title=f"Research plan {revision_state}",
            status="success",
            details={
                "plan": plan,
                "execution_state": "planned",
                "revision_state": revision_state,
            },
        )
        return result, action

    @staticmethod
    def _as_string_list(value: Any, *, fallback: list[str] | None = None) -> list[str]:
        if isinstance(value, list):
            items = [str(item).strip() for item in value if str(item or "").strip()]
            return items or list(fallback or [])
        if isinstance(value, str) and value.strip():
            return [line.strip("-• \t") for line in value.splitlines() if line.strip("-• \t")]
        return list(fallback or [])

    @staticmethod
    def _as_dict_list(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    @staticmethod
    def _slug_id(value: str, fallback: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
        return normalized[:64] or fallback

    def _normalize_search_branches(self, value: Any, *, topic: str) -> list[dict[str, Any]]:
        raw_branches = self._as_dict_list(value)
        search_branches: list[dict[str, Any]] = []
        for index, item in enumerate(raw_branches, start=1):
            label = str(item.get("label") or item.get("name") or f"Branch {index}").strip()
            aliases = self._as_string_list(item.get("aliases") or item.get("synonyms"))
            query = str(item.get("query") or "").strip()
            if not query:
                query_terms = [label, *aliases]
                query = " OR ".join(f'"{term}"' if " " in term else term for term in query_terms if term)
            search_branches.append(
                {
                    "id": self._slug_id(str(item.get("id") or label), f"branch_{index}"),
                    "label": label,
                    "query": query or label,
                }
            )
        if search_branches:
            return search_branches
        return [
            {
                "id": "main_branch",
                "label": topic,
                "query": topic,
            }
        ]

    def _normalize_shared_query_concepts(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            concepts: list[dict[str, Any]] = []
            for index, item in enumerate(value, start=1):
                if isinstance(item, str):
                    query = item.strip()
                    if not query:
                        continue
                    concepts.append(
                        {
                            "id": self._slug_id(query, f"concept_{index}"),
                            "label": f"Shared query {index}",
                            "query": query,
                        }
                    )
                    continue
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("name") or f"Shared query {index}").strip()
                query = str(item.get("query") or "").strip()
                if not query:
                    terms = self._as_string_list(item.get("terms"), fallback=[label])
                    query = " OR ".join(f'"{term}"' if " " in term else term for term in terms if term) or label
                concepts.append(
                    {
                        "id": self._slug_id(str(item.get("id") or label), f"concept_{index}"),
                        "label": label,
                        "query": query,
                    }
                )
            return concepts
        return []

    @staticmethod
    def _compose_raw_search_queries(
        *,
        databases: list[str],
        search_branches: list[dict[str, Any]],
        shared_query_concepts: list[dict[str, Any]],
        candidate_limit: int,
    ) -> list[dict[str, Any]]:
        shared_queries = [
            {
                "id": str(item.get("id") or "").strip(),
                "label": str(item.get("label") or "").strip(),
                "query": str(item.get("query") or "").strip(),
            }
            for item in shared_query_concepts
            if str(item.get("query") or "").strip()
        ]
        combined_concept_query = " OR ".join(f"({item['query']})" for item in shared_queries)
        raw_queries: list[dict[str, Any]] = []
        for database in databases:
            for branch in search_branches:
                branch_query = str(branch.get("query") or branch.get("label") or "").strip()
                query_parts = [branch_query, combined_concept_query]
                query = " AND ".join(f"({part})" for part in query_parts if part)
                raw_queries.append(
                    {
                        "database": database,
                        "branch_id": branch.get("id") or "",
                        "branch_label": branch.get("label") or "",
                        "category_ids": [item["id"] for item in shared_queries if item["id"]],
                        "category_labels": [item["label"] for item in shared_queries if item["label"]],
                        "category_id": "",
                        "category_label": "Combined categories" if shared_queries else "",
                        "query": query,
                        "candidate_limit": candidate_limit,
                    }
                )
        return raw_queries

    def _normalize_research_plan(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = str(args.get("topic") or "").strip() or "Untitled research topic"
        objective = str(args.get("objective") or "").strip() or f"Find and rank the most relevant papers for: {topic}"
        target_count = parse_bounded_int(
            args.get("target_count_per_branch") or args.get("target_count"),
            default=20,
            minimum=1,
            maximum=100,
        )
        per_database = target_count * 2
        year_start = parse_optional_int(args.get("year_start"))
        year_end = parse_optional_int(args.get("year_end"))
        if year_start is not None:
            year_start = max(1000, min(9999, year_start))
        if year_end is not None:
            year_end = max(1000, min(9999, year_end))
        if year_start is not None and year_end is not None and year_start > year_end:
            year_start, year_end = year_end, year_start
        databases = self._as_string_list(
            args.get("active_databases") or args.get("databases"),
            fallback=["PubMed", "Europe PMC", "OpenAlex", "CORE", "arXiv"],
        )
        search_branches = self._normalize_search_branches(
            args.get("search_branches") or args.get("search_topics"),
            topic=topic,
        )
        shared_query_concepts = self._normalize_shared_query_concepts(args.get("shared_query_concepts"))
        exclusion = self._as_string_list(
            args.get("exclusion_criteria"),
            fallback=[
                "Exclude papers that are unrelated to the target topic.",
                "Exclude papers with no abstract or evidence-bearing metadata during abstract screening.",
            ],
        )
        criteria_disabled = str(args.get("criteria_mode") or "").strip().lower() in {"disabled", "off", "none", "false"}
        if criteria_disabled:
            exclusion = []
        raw_screening = self._as_dict_list(args.get("screening_criteria"))
        screening_criteria: list[dict[str, Any]] = []
        for index, item in enumerate(raw_screening, start=1):
            label = str(item.get("label") or item.get("id") or f"Criterion {index}").strip()
            criterion_id = self._slug_id(str(item.get("id") or label), f"criterion_{index}")
            screening_criteria.append(
                {
                    "id": criterion_id,
                    "label": label,
                    "description": str(item.get("description") or label).strip(),
                    "required": bool(item.get("required", False)),
                    "weight": float(item.get("weight") or 1.0),
                    "scoring_guidance": str(
                        item.get("scoring_guidance")
                        or "Score 1.0 for explicit evidence, 0.5 for partial evidence, and 0.0 when absent."
                    ).strip(),
                }
            )
        if not screening_criteria and not criteria_disabled:
            screening_criteria = [
                {
                    "id": "topic_match",
                    "label": "Topic match",
                    "description": "The paper directly matches the user's research topic.",
                    "required": True,
                    "weight": 1.0,
                    "scoring_guidance": "Score 1.0 for explicit match, 0.5 for partial match, 0.0 for unrelated papers.",
                },
                {
                    "id": "method_match",
                    "label": "Method or evidence match",
                    "description": "The paper contains the method, evidence, or artifact requested by the user.",
                    "required": False,
                    "weight": 1.0,
                    "scoring_guidance": "Score 1.0 for explicit evidence, 0.5 for likely evidence, 0.0 if absent.",
                },
            ]
        candidate_budget = args.get("candidate_budget") if isinstance(args.get("candidate_budget"), dict) else {}
        budget_per_database = candidate_budget.get("per_database") if "per_database" in candidate_budget else per_database
        normalized_budget = {
            "target_count": target_count,
            "per_database": parse_bounded_int(budget_per_database, default=per_database, minimum=1, maximum=500),
            "rule": str(candidate_budget.get("rule") or "Fetch target_count * 2 candidates per enabled database in the first pass.").strip(),
        }
        raw_search_queries = self._compose_raw_search_queries(
            databases=databases,
            search_branches=search_branches,
            shared_query_concepts=shared_query_concepts,
            candidate_limit=normalized_budget["per_database"],
        )
        total_queries = len(raw_search_queries) or (max(1, len(search_branches)) * max(1, len(databases)))
        estimated_candidates = total_queries * normalized_budget["per_database"]
        estimated_time_seconds = max(20, ((estimated_candidates + 39) // 40) * 20)
        screening_json_schema = args.get("screening_json_schema")
        if not isinstance(screening_json_schema, dict):
            screening_json_schema = {
                "candidate_id": "string",
                "criterion_scores": {item["id"]: "number 0.0-1.0" for item in screening_criteria},
                "confidence": "number 0.0-1.0",
                "evidence": ["short evidence strings"],
                "rationale": "short explanation",
            }
        extraction_questions = self._as_string_list(
            args.get("extraction_questions"),
            fallback=[
                f"Return the exact sentence or phrase that directly supports the objective: {objective}",
                "Return the specific named entity, residue, method, assay, figure, table, or numeric value that answers the objective.",
            ],
        )
        raw_question_specs = self._as_dict_list(args.get("extraction_question_specs"))
        extraction_question_specs: list[dict[str, str]] = []
        for index, item in enumerate(raw_question_specs, start=1):
            question = str(item.get("question") or "").strip()
            if not question:
                continue
            answer_format = str(item.get("answer_format") or item.get("format") or "factual_answer").strip()
            if answer_format not in {"exact_text", "factual_answer"}:
                answer_format = "factual_answer"
            extraction_question_specs.append(
                {
                    "id": self._slug_id(str(item.get("id") or question), f"question_{index}"),
                    "question": question,
                    "answer_format": answer_format,
                }
            )
        if not extraction_question_specs:
            extraction_question_specs = [
                {
                    "id": self._slug_id(question, f"question_{index}"),
                    "question": question,
                    "answer_format": "exact_text" if index == 1 else "factual_answer",
                }
                for index, question in enumerate(extraction_questions, start=1)
            ]
        extraction_questions = [item["question"] for item in extraction_question_specs]
        extraction_fields = self._as_string_list(
            args.get("extraction_fields"),
            fallback=[
                "paper_id",
                "question",
                "answer_format",
                "answer",
                "evidence_quote",
                "page_or_section",
                "confidence",
            ],
        )
        evidence_requirements = self._as_string_list(
            args.get("evidence_requirements"),
            fallback=[
                "Use only downloaded PDF or full-text XML content.",
                "Attach page number when available; otherwise attach section/context.",
                "Quote short exact evidence snippets and mark uncertainty explicitly.",
            ],
        )
        search_strategy = {
            "year_start": year_start,
            "year_end": year_end,
            "active_databases": databases,
            "search_branches": search_branches,
            "shared_query_concepts": shared_query_concepts,
            "candidate_budget": normalized_budget,
            "query_expansion_policy": self._as_string_list(
                args.get("query_expansion_policy"),
                fallback=[
                    "If fewer than the target count survive screening, relax phrase strictness.",
                    "Add synonyms, abbreviations, and alternate target names.",
                    "Broaden database-specific syntax while preserving mandatory scientific concepts.",
                ],
            ),
        }
        criteria_strategy = {
            "criteria_mode": "disabled" if criteria_disabled else (str(args.get("criteria_mode") or "llm").strip() or "llm"),
            "screening_criteria": screening_criteria,
            "exclusion_criteria": exclusion,
            "screening_json_schema": screening_json_schema,
            "scoring_rule": str(
                args.get("scoring_rule")
                or "final_relevance = sum(score_i ** 2 for score_i in criterion_scores) / number_of_criteria"
            ).strip(),
        }
        extraction_strategy = {
            "extraction_questions": extraction_questions,
            "extraction_question_specs": extraction_question_specs,
            "extraction_fields": extraction_fields,
            "evidence_requirements": evidence_requirements,
            "output_schema": {
                "paper_id": "string",
                "question": "string",
                "answer": "string",
                "evidence": [
                    {
                        "quote": "short exact quote",
                        "page": "number or null",
                        "section": "string",
                        "confidence": "number 0.0-1.0",
                    }
                ],
            },
        }
        planner_stages = [
            {
                "agent": "SearchPlannerAgent",
                "status": "validated",
                "context": {
                    "topic": topic,
                    "objective": objective,
                    "target_count_per_branch": target_count,
                },
                "output": search_strategy,
            },
            {
                "agent": "CriteriaPlannerAgent",
                "status": "validated",
                "context": {
                    "search_branches": search_branches,
                    "active_databases": databases,
                    "year_start": year_start,
                    "year_end": year_end,
                },
                "output": criteria_strategy,
            },
            {
                "agent": "ExtractionPlannerAgent",
                "status": "validated",
                "context": {
                    "search_branch_count": len(search_branches),
                    "screening_criterion_count": len(screening_criteria),
                    "evidence_requirements": evidence_requirements,
                },
                "output": extraction_strategy,
            },
        ]
        return {
            "topic": topic,
            "objective": objective,
            "target_count": target_count,
            "target_count_per_branch": target_count,
            "year_start": year_start,
            "year_end": year_end,
            "databases": databases,
            "active_databases": databases,
            "search_branches": search_branches,
            "shared_query_concepts": shared_query_concepts,
            "candidate_budget": normalized_budget,
            "search_strategy": search_strategy,
            "total_queries": total_queries,
            "estimated_candidates": estimated_candidates,
            "estimated_time_seconds": estimated_time_seconds,
            "raw_search_queries": raw_search_queries,
            "exclusion_criteria": exclusion,
            "screening_criteria": screening_criteria,
            "criteria_strategy": criteria_strategy,
            "planner_stages": planner_stages,
            "screening_json_schema": screening_json_schema,
            "scoring_rule": str(
                args.get("scoring_rule")
                or "final_relevance = sum(score_i ** 2 for score_i in criterion_scores) / number_of_criteria"
            ).strip(),
            "query_expansion_policy": search_strategy["query_expansion_policy"],
            "extraction_strategy": extraction_strategy,
            "extraction_questions": extraction_questions,
            "extraction_question_specs": extraction_question_specs,
            "extraction_fields": extraction_fields,
            "evidence_requirements": evidence_requirements,
            "open_questions": self._as_string_list(args.get("open_questions")),
            "revision_summary": str(args.get("revision_summary") or "").strip(),
            "notes": str(args.get("notes") or "").strip(),
        }

    @staticmethod
    def _research_plan_preview_text(plan: dict[str, Any]) -> str:
        topic = plan.get("topic") or "Research topic"
        target_count = plan.get("target_count_per_branch") or plan.get("target_count") or 20
        databases = ", ".join(plan.get("databases") or [])
        criteria = plan.get("screening_criteria") or []
        query_count = plan.get("total_queries") or len(plan.get("raw_search_queries") or [])
        branch_count = len(plan.get("search_branches") or [])
        return (
            f"Researcher plan created for **{topic}**.\n\n"
            f"- Target papers per branch: {target_count}\n"
            f"- Databases: {databases or 'not specified'}\n"
            f"- Search branches: {branch_count or 1}\n"
            f"- Screening criteria: {len(criteria)}\n"
            f"- Executable database queries: {query_count}\n\n"
            "Review the plan preview, ask for changes in the chat, or execute it when the screening pipeline is ready."
        )

    async def _execute_tool_call(
        self,
        name: str,
        args: dict[str, Any],
        *,
        api_key: str,
        model_name: str,
        article_index: dict[int, HelperArticle],
        last_search_index: dict[int, HelperArticle],
        selected_set: set[int],
        used_article_ids: set[int],
    ) -> tuple[dict[str, Any], HelperExecutedAction]:
        if name == "list_catalog_articles":
            return self._tool_list_catalog_articles(
                args,
                article_index=article_index,
                selected_set=selected_set,
                used_article_ids=used_article_ids,
            )
        if name == "search_pubmed":
            return await self._tool_search_pubmed(
                args,
                last_search_index=last_search_index,
                used_article_ids=used_article_ids,
            )
        if name == "get_article_details":
            return self._tool_get_article_details(
                args,
                article_index=article_index,
                last_search_index=last_search_index,
                used_article_ids=used_article_ids,
            )
        raise ValueError(f"Unknown tool call: {name}")

    def _tool_list_catalog_articles(
        self,
        args: dict[str, Any],
        *,
        article_index: dict[int, HelperArticle],
        selected_set: set[int],
        used_article_ids: set[int],
    ) -> tuple[dict[str, Any], HelperExecutedAction]:
        query = str(args.get("query") or "").strip().lower()
        article_type = str(args.get("article_type") or "").strip().lower()
        selected_only = bool(args.get("selected_only"))
        limit = parse_bounded_int(args.get("limit"), default=8, minimum=1, maximum=20)

        source = list(article_index.values())
        if selected_only and selected_set:
            source = [article for article in source if article.id in selected_set]

        matches: list[HelperArticle] = []
        for article in source:
            haystacks = [
                article.title,
                article.article_type or "",
                " ".join(article.mesh_terms),
            ]
            matches_query = not query or any(query in value.lower() for value in haystacks)
            matches_type = not article_type or article_type in (article.article_type or "").lower()
            if matches_query and matches_type:
                matches.append(article)

        resolved = matches[:limit]
        used_article_ids.update(article.id for article in resolved)
        result = {
            "count": len(resolved),
            "articles": [
                {
                    "id": article.id,
                    "title": article.title,
                    "year": article.year,
                    "article_type": article.article_type,
                    "citation_count": article.citation_count,
                    "mesh_terms": article.mesh_terms[:8],
                }
                for article in resolved
            ],
        }
        action = HelperExecutedAction(
            type="tool_call",
            name="list_catalog_articles",
            title="Catalog scanned",
            status="success",
            details={
                "query": query or None,
                "article_type": article_type or None,
                "selected_only": selected_only,
                "returned_ids": [article["id"] for article in result["articles"]],
            },
        )
        return result, action

    async def _tool_search_pubmed(
        self,
        args: dict[str, Any],
        *,
        last_search_index: dict[int, HelperArticle],
        used_article_ids: set[int],
    ) -> tuple[dict[str, Any], HelperExecutedAction]:
        raw_query = str(args.get("query") or "").strip()
        if not raw_query:
            raise ValueError("search_pubmed icin query zorunlu.")
        preferred_source = getattr(
            self.pubmed_service.settings,
            "ai_primary_search_resource",
            "pubmed",
        )
        query = self._sanitize_pubmed_query_text(raw_query) or raw_query

        year_start = parse_optional_int(args.get("year_start"))
        year_end = parse_optional_int(args.get("year_end"))
        max_results = parse_bounded_int(
            args.get("max_results"),
            default=AGENT_SEARCH_MAX_RESULTS,
            minimum=1,
            maximum=AGENT_SEARCH_MAX_RESULTS,
        )
        article_type = str(args.get("article_type") or "").strip() or None
        min_cite = parse_optional_int(args.get("min_cite"))
        if min_cite is not None:
            min_cite = max(0, min(min_cite, 1_000_000))

        response = await self._search_pubmed(
            query=query,
            year_start=year_start,
            year_end=year_end,
            max_results=max_results,
            article_type=article_type,
            min_cite=min_cite,
        )
        last_search_index.clear()
        for article in response.articles:
            helper_article = self._helper_article_from_article(article)
            last_search_index[helper_article.id] = helper_article

        used_article_ids.update(last_search_index.keys())
        result = {
            "query": query,
            "input_query": raw_query,
            "meta": response.meta.model_dump(),
            "count": len(response.articles),
            "article_type": article_type,
            "min_cite": min_cite,
            "articles": [
                {
                    "id": article.id,
                    "title": article.title,
                    "year": article.year,
                    "article_type": article.article_type,
                    "citation_count": article.citation_count,
                    "pmid": article.pmid,
                }
                for article in response.articles
            ],
        }
        action = HelperExecutedAction(
            type="tool_call",
            name="search_pubmed",
            title=f"Searched {self._source_label(response.meta.primary_source or preferred_source)}",
            status="success",
            details={
                "query": query,
                "input_query": raw_query,
                "year_start": year_start,
                "year_end": year_end,
                "max_results": max_results,
                "article_type": article_type,
                "min_cite": min_cite,
                "meta": response.meta.model_dump(),
                "articles": [article.model_dump() for article in response.articles],
            },
        )
        return result, action

    @staticmethod
    def _sanitize_pubmed_query_text(text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        if "```" in cleaned:
            cleaned = "\n".join(
                line for line in cleaned.splitlines() if not line.strip().startswith("```")
            ).strip()
        cleaned = re.sub(r"^\s*PubMed\s+query\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip().strip("`").strip()
        if (
            len(cleaned) >= 2
            and cleaned[0] == cleaned[-1]
            and cleaned[0] in {'"', "'"}
        ):
            cleaned = cleaned[1:-1].strip()
        return re.sub(r"\s+", " ", cleaned)

    def _tool_get_article_details(
        self,
        args: dict[str, Any],
        *,
        article_index: dict[int, HelperArticle],
        last_search_index: dict[int, HelperArticle],
        used_article_ids: set[int],
    ) -> tuple[dict[str, Any], HelperExecutedAction]:
        source_name = str(args.get("source") or "loaded").strip().lower()
        source_index = last_search_index if source_name == "last_search" else article_index
        raw_ids = args.get("ids") or []
        resolved_ids: list[int] = []
        for value in raw_ids:
            try:
                article_id = int(value)
            except (TypeError, ValueError):
                continue
            if article_id in source_index and article_id not in resolved_ids:
                resolved_ids.append(article_id)

        details: list[dict[str, Any]] = []
        omitted_ids: list[int] = []
        token_budget = 0
        for article_id in resolved_ids:
            article = source_index[article_id]
            payload = {
                "id": article.id,
                "title": article.title,
                "year": article.year,
                "journal": article.journal,
                "article_type": article.article_type,
                "citation_count": article.citation_count,
                "pmid": article.pmid,
                "doi": article.doi,
                "mesh_terms": article.mesh_terms[:12],
                "abstract": article.abstract,
            }
            article_tokens = estimate_token_count(json.dumps(payload, ensure_ascii=False))
            if details and token_budget + article_tokens > MAX_DETAIL_TOOL_TOKENS:
                omitted_ids.append(article_id)
                continue
            token_budget += article_tokens
            details.append(payload)
            used_article_ids.add(article_id)

        result = {
            "count": len(details),
            "estimated_tokens": token_budget,
            "articles": details,
            "omitted_ids": omitted_ids,
            "source": source_name,
        }
        action = HelperExecutedAction(
            type="tool_call",
            name="get_article_details",
            title="Makale detaylari okundu",
            status="success",
            details={
                "source": source_name,
                "requested_ids": resolved_ids,
                "returned_ids": [article["id"] for article in details],
                "omitted_ids": omitted_ids,
                "estimated_tokens": token_budget,
            },
        )
        return result, action

    async def _search_pubmed(
        self,
        *,
        query: str,
        year_start: int | None,
        year_end: int | None,
        max_results: int,
        article_type: str | None,
        min_cite: int | None,
    ) -> PubMedSearchResponse:
        if self.pubmed_service is None:
            raise RuntimeError("PubMed service bagli degil.")
        request = PubMedSearchRequest(
            query=query,
            year_start=year_start,
            year_end=year_end,
            max_results=max_results,
            article_type=article_type,
            min_cite=min_cite,
            use_cache=True,
            preferred_source=getattr(
                self.pubmed_service.settings,
                "ai_primary_search_resource",
                "pubmed",
            ),
        )
        return await self.pubmed_service.search(request)

    @staticmethod
    def _helper_article_from_article(article: Article) -> HelperArticle:
        article_type = article.article_type or (article.article_types[0] if article.article_types else None)
        return HelperArticle(
            id=article.id,
            title=article.title,
            year=article.year,
            article_type=article_type,
            citation_count=article.citation_count,
            mesh_terms=list(article.mesh_terms or []),
            abstract=article.abstract or "",
            pmid=article.pmid or None,
            doi=article.doi,
            journal=article.journal,
        )

    async def _run_finalizer(
        self,
        *,
        api_key: str,
        model_name: str,
        contents: list[Any],
        fallback_answer: str,
    ) -> str:
        response = await asyncio.to_thread(
            self._generate_final_response,
            api_key,
            model_name,
            contents,
        )
        return self._extract_text_response(response).strip() or fallback_answer

    def _build_fast_prompt(self, payload: HelperChatRequest, today_stamp: str) -> str:
        return build_helper_fast_prompt(
            payload,
            today_stamp=today_stamp,
            source=self._preferred_search_source(),
        )

    @staticmethod
    def _extract_text_response(response: Any) -> str:
        text = (getattr(response, "text", None) or "").strip()
        if text:
            return text
        for candidate in getattr(response, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", None) or []
            lines = [part.text for part in parts if getattr(part, "text", None)]
            if lines:
                return "\n".join(lines).strip()
        return ""

    @staticmethod
    def _step_note_from_action(action: HelperExecutedAction) -> str:
        if action.name == "list_catalog_articles":
            ids = action.details.get("returned_ids") or []
            return f"Catalog scan completed; matching IDs: {', '.join(map(str, ids)) or '-'}."
        if action.name == "search_pubmed":
            source = action.details.get("meta", {}).get("primary_source") or "search"
            source_label = HelperAIService._source_label(source)
            query = action.details.get("query") or "-"
            article_count = len(action.details.get("articles") or [])
            return f"{source_label} search completed for `{query}`; returned article count: {article_count}."
        if action.name == "get_article_details":
            ids = action.details.get("returned_ids") or []
            source = action.details.get("source") or "loaded"
            return (
                f"Makale detaylari okundu ({source}), getirilen ID'ler: "
                f"{', '.join(map(str, ids)) or '-'}."
            )
        return action.title

    @staticmethod
    def _build_thinking_summary(
        thinking_level: str,
        *,
        total_articles: int,
        selected_count: int,
        steps: list[str],
        used_article_ids: list[int],
    ) -> str | None:
        if thinking_level == "off":
            return None
        lines = [
            f"Catalog size: {total_articles}",
            f"Selected article count: {selected_count}",
        ]
        if steps:
            lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
        if thinking_level == "max":
            lines.append(
                "Note: Fast mode ran with at most 3 tool calls and stayed grounded in the current catalog/search results."
            )
        if used_article_ids:
            lines.append(f"Used IDs: {', '.join(map(str, used_article_ids))}")
        return "\n".join(lines)

    @staticmethod
    def _is_terminal_empty_search_action(action: HelperExecutedAction) -> bool:
        if action.name != "search_pubmed":
            return False
        return not (action.details.get("articles") or [])

    @staticmethod
    def _build_no_results_answer(action: HelperExecutedAction) -> str:
        source = action.details.get("meta", {}).get("primary_source") or "search"
        source_label = HelperAIService._source_label(source)
        return f"I could not find relevant articles for this request in {source_label}.\nSource IDs:"


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4 + 1)


def parse_optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(parsed, maximum))
