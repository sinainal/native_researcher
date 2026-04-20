"""Gemini-backed helper chat service."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from app.genai import create_genai_client, load_genai_sdk
from app.llm import extract_ollama_tool_calls, ollama_chat, resolve_chat_model_target
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
    build_helper_fast_mode_system_instruction,
    build_helper_fast_prompt,
)
from app.services.helper_log_service import HelperLogService
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache
MAX_FAST_TOOL_CALLS = 3
MAX_DETAIL_TOOL_TOKENS = 50_000


@dataclass
class HelperThreadState:
    history: list[dict[str, str]] = field(default_factory=list)


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
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant"}
        if content:
            message["content"] = content
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

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
        if model_target.provider == "ollama":
            return await self._chat_with_ollama(payload, thread_id=thread_id, thread_state=thread_state, model_name=model_name)

        if payload.mode != "fast":
            answer = "Agent mode MVP surumunde henuz aktif degil. Fast mode u kullan."
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
        answer = "Yanit uretilemedi."
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
            answer = answer or "Yanit uretilemedi."
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
        if model_target.provider == "ollama":
            async for event in self._chat_stream_with_ollama(
                payload,
                thread_id=thread_id,
                thread_state=thread_state,
                model_name=model_name,
            ):
                yield event
            return

        if payload.mode != "fast":
            answer = "Agent mode MVP surumunde henuz aktif degil. Fast mode u kullan."
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
        yield {"type": "status", "text": "İstek analiz ediliyor."}

        remaining_tool_calls = MAX_FAST_TOOL_CALLS
        answer = "Yanit uretilemedi."
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
            answer = answer or "Yanit uretilemedi."
            break

        if finalizer_needed:
            yield {"type": "status", "text": "Araç çıktıları birleştiriliyor."}
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
    ) -> HelperChatResponse:
        if payload.mode != "fast":
            answer = "Agent mode MVP surumunde henuz aktif degil. Fast mode u kullan."
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
        answer = "Yanit uretilemedi."
        finalizer_needed = False

        while True:
            response = await ollama_chat(
                base_url=self._ollama_base_url(),
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
                            "content": json.dumps({"result": result}, ensure_ascii=False),
                        }
                    )
                    remaining_tool_calls -= 1
                continue

            if answer_text:
                messages.append(self._ollama_assistant_message(content=answer_text))
            answer = answer_text or "Yanit uretilemedi."
            if not answer_text and executed_actions:
                finalizer_needed = True
            break

        if finalizer_needed:
            final_response = await ollama_chat(
                base_url=self._ollama_base_url(),
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
    ) -> AsyncIterator[dict[str, Any]]:
        if payload.mode != "fast":
            answer = "Agent mode MVP surumunde henuz aktif degil. Fast mode u kullan."
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
        answer = "Yanit uretilemedi."
        finalizer_needed = False

        while True:
            response = None
            async for event in self._ollama_chat_with_heartbeat(
                status_text="İstek analiz ediliyor.",
                heartbeat_text=f"{model_name} yanıt hazırlıyor.",
                base_url=self._ollama_base_url(),
                model=model_name,
                messages=messages,
                tools=self._build_ollama_fast_toolset() if remaining_tool_calls > 0 else None,
                thinking_level=payload.thinking_level,
                keep_alive="10m",
                timeout_seconds=900.0,
                request_user_agent=self._ollama_request_user_agent(),
            ):
                if event["type"] == "status":
                    yield event
                    continue
                response = event["payload"]
            if response is None:
                raise RuntimeError("Ollama response was empty.")
            message = response.get("message") or {}
            answer_text = str(message.get("content") or "")
            thinking_text = str(message.get("thinking") or "").strip()
            if thinking_text:
                streamed_thoughts.append(thinking_text)
                yield {"type": "thinking_delta", "text": thinking_text}
            tool_calls = extract_ollama_tool_calls(message)
            if tool_calls and remaining_tool_calls > 0:
                messages.append(
                    self._ollama_assistant_message(
                        content=answer_text.strip(),
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
                            "content": json.dumps({"result": result}, ensure_ascii=False),
                        }
                    )
                    remaining_tool_calls -= 1
                continue

            answer = answer_text.strip()
            if answer:
                messages.append(self._ollama_assistant_message(content=answer))
                yield {"type": "answer_delta", "text": answer}
            if not answer and executed_actions:
                finalizer_needed = True
            answer = answer or "Yanit uretilemedi."
            break

        if finalizer_needed:
            final_response = None
            async for event in self._ollama_chat_with_heartbeat(
                status_text="Araç çıktıları birleştiriliyor.",
                heartbeat_text=f"{model_name} son yanıtı toparlıyor.",
                base_url=self._ollama_base_url(),
                model=model_name,
                messages=[*messages, {"role": "user", "content": HELPER_FINALIZER_PROMPT}],
                tools=None,
                thinking_level=payload.thinking_level,
                keep_alive="10m",
                timeout_seconds=900.0,
                request_user_agent=self._ollama_request_user_agent(),
            ):
                if event["type"] == "status":
                    yield event
                    continue
                final_response = event["payload"]
            if final_response is None:
                raise RuntimeError("Ollama final response was empty.")
            final_message = final_response.get("message") or {}
            final_thinking = str(final_message.get("thinking") or "").strip()
            if final_thinking:
                streamed_thoughts.append(final_thinking)
                yield {"type": "thinking_delta", "text": final_thinking}
            final_answer = str(final_message.get("content") or "").strip()
            if final_answer:
                answer = final_answer
                yield {"type": "answer_delta", "text": final_answer}

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
            "list_catalog_articles": "Katalog taramasi yapiliyor",
            "search_pubmed": "Literatur aramasi yapiliyor",
            "get_article_details": "Makale detaylari okunuyor",
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
        raise ValueError(f"Bilinmeyen tool cagrisi: {name}")

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
            title="Katalog tarandi",
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
            title=f"{self._source_label(response.meta.primary_source or preferred_source)} aramasi yapildi",
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
            return f"Katalog taramasi yapildi, eslesen ID'ler: {', '.join(map(str, ids)) or '-'}."
        if action.name == "search_pubmed":
            source = action.details.get("meta", {}).get("primary_source") or "search"
            source_label = HelperAIService._source_label(source)
            query = action.details.get("query") or "-"
            article_count = len(action.details.get("articles") or [])
            return f"{source_label} aramasi yapildi, sorgu `{query}`, donen makale sayisi: {article_count}."
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
            f"Katalog boyutu: {total_articles}",
            f"Secili makale sayisi: {selected_count}",
        ]
        if steps:
            lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
        if thinking_level == "max":
            lines.append(
                "Not: Fast mode en fazla 3 tool cagrisi ile ve o anki katalog/arama sonucuna dayanarak calisti."
            )
        if used_article_ids:
            lines.append(f"Kullanilan ID'ler: {', '.join(map(str, used_article_ids))}")
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
        return f"Bu istek icin {source_label} kaynaginda ilgili makale bulamadim.\nKaynak ID:"


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
