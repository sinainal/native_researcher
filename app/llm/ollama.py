"""Ollama chat API helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.tool_calls import normalized_tool_calls_from_message

OLLAMA_DEFAULT_NUM_CTX = 16_384
OLLAMA_DEFAULT_NUM_PREDICT = 4_096
OLLAMA_DEFAULT_REPEAT_LAST_N = 256
OLLAMA_DEFAULT_REPEAT_PENALTY = 1.12
OLLAMA_DEFAULT_TEMPERATURE = 0.7
OLLAMA_DEFAULT_TOP_P = 0.9
OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS = 4_096


@dataclass(frozen=True)
class OllamaToolCall:
    call_id: str
    name: str
    args: dict[str, Any]
    raw: dict[str, Any]


_THINK_BLOCK_RE = re.compile(r"<think>\s*(.*?)\s*</think>", re.DOTALL)
_TOOL_ARTIFACT_RE = re.compile(r"<[^>\n]*tool_(?:call|response)[^>\n]*>", re.IGNORECASE)


def _clean_ollama_text(text: str, *, strip: bool = True) -> str:
    cleaned = _TOOL_ARTIFACT_RE.sub("", text)
    cleaned = (
        cleaned.replace("<|endoftext|>", "")
        .replace("<|im_start|>", "")
        .replace("<|im_end|>", "")
    )
    return cleaned.strip() if strip else cleaned


def _normalize_ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message.get("content") or "")
    thinking = str(message.get("thinking") or "").strip()
    if not thinking and "<think>" in content:
        think_parts = [part.strip() for part in _THINK_BLOCK_RE.findall(content) if part.strip()]
        if think_parts:
            thinking = "\n\n".join(think_parts)
            content = _THINK_BLOCK_RE.sub("", content)

    content = _clean_ollama_text(content)

    normalized = dict(message)
    normalized["content"] = content
    if thinking and not str(normalized.get("thinking") or "").strip():
        normalized["thinking"] = thinking
    return normalized


@dataclass(frozen=True)
class _StreamTextPart:
    kind: str
    text: str


class _OllamaStreamParser:
    _OPEN_TAG = "<think>"
    _CLOSE_TAG = "</think>"

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    @staticmethod
    def _trailing_marker_length(text: str, marker: str) -> int:
        limit = min(len(text), len(marker) - 1)
        for size in range(limit, 0, -1):
            if text.endswith(marker[:size]):
                return size
        return 0

    @staticmethod
    def _strip_partial_marker(text: str, marker: str) -> str:
        tail_len = _OllamaStreamParser._trailing_marker_length(text, marker)
        return text[:-tail_len] if tail_len else text

    def feed(self, text: str) -> list[_StreamTextPart]:
        cleaned = _clean_ollama_text(text, strip=False)
        if not cleaned:
            return []
        self._buffer += cleaned
        emitted: list[_StreamTextPart] = []
        while self._buffer:
            if self._in_think:
                close_idx = self._buffer.find(self._CLOSE_TAG)
                if close_idx >= 0:
                    if close_idx > 0:
                        emitted.append(_StreamTextPart("thinking", self._buffer[:close_idx]))
                    self._buffer = self._buffer[close_idx + len(self._CLOSE_TAG):]
                    self._in_think = False
                    continue
                safe_len = len(self._buffer) - self._trailing_marker_length(self._buffer, self._CLOSE_TAG)
                if safe_len > 0:
                    emitted.append(_StreamTextPart("thinking", self._buffer[:safe_len]))
                    self._buffer = self._buffer[safe_len:]
                break

            open_idx = self._buffer.find(self._OPEN_TAG)
            if open_idx >= 0:
                if open_idx > 0:
                    emitted.append(_StreamTextPart("content", self._buffer[:open_idx]))
                self._buffer = self._buffer[open_idx + len(self._OPEN_TAG):]
                self._in_think = True
                continue

            safe_len = len(self._buffer) - self._trailing_marker_length(self._buffer, self._OPEN_TAG)
            if safe_len > 0:
                emitted.append(_StreamTextPart("content", self._buffer[:safe_len]))
                self._buffer = self._buffer[safe_len:]
            break
        return emitted

    def flush(self) -> list[_StreamTextPart]:
        if not self._buffer:
            return []
        pending = self._strip_partial_marker(
            self._buffer,
            self._CLOSE_TAG if self._in_think else self._OPEN_TAG,
        )
        self._buffer = ""
        if not pending:
            return []
        return [_StreamTextPart("thinking" if self._in_think else "content", pending)]


def _ollama_think_option(thinking_level: str) -> bool | str:
    level = str(thinking_level or "off").strip().lower()
    if level == "off":
        return False
    if level == "on":
        return True
    return True


def _ollama_runtime_options(*, num_ctx: int = OLLAMA_DEFAULT_NUM_CTX) -> dict[str, int | float]:
    return {
        "num_ctx": num_ctx,
        "num_predict": OLLAMA_DEFAULT_NUM_PREDICT,
        "temperature": OLLAMA_DEFAULT_TEMPERATURE,
        "top_p": OLLAMA_DEFAULT_TOP_P,
        "repeat_last_n": OLLAMA_DEFAULT_REPEAT_LAST_N,
        "repeat_penalty": OLLAMA_DEFAULT_REPEAT_PENALTY,
    }


def _ollama_thinking_budget(thinking_level: str) -> dict[str, int] | None:
    if str(thinking_level or "off").strip().lower() == "off":
        return None
    return {"budget_tokens": OLLAMA_DEFAULT_THINKING_BUDGET_TOKENS}


def _ollama_error_text(response: httpx.Response, *, model: str) -> str:
    try:
        payload = response.json() or {}
        raw_error = str(payload.get("error") or "").strip()
    except Exception:
        raw_error = response.text.strip()
    if raw_error:
        return f"Ollama model '{model}' failed: {raw_error}"
    return f"Ollama model '{model}' failed with HTTP {response.status_code}."


async def ollama_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    thinking_level: str = "off",
    keep_alive: str | int | float | None = None,
    timeout_seconds: float = 120.0,
    request_user_agent: str = "NativeResearcher/0.1",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": _ollama_think_option(thinking_level),
        "options": _ollama_runtime_options(),
    }
    thinking_budget = _ollama_thinking_budget(thinking_level)
    if thinking_budget is not None:
        payload["thinking"] = thinking_budget
    if tools:
        payload["tools"] = tools
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    headers = {"User-Agent": request_user_agent}
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        response = await client.post("/api/chat", json=payload)
        if response.status_code >= 400:
            raise RuntimeError(_ollama_error_text(response, model=model))
        response.raise_for_status()
        data = response.json()
        message = data.get("message")
        if isinstance(message, dict):
            data["message"] = _normalize_ollama_message(message)
        return data


async def ollama_chat_stream(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    thinking_level: str = "off",
    keep_alive: str | int | float | None = None,
    timeout_seconds: float = 120.0,
    request_user_agent: str = "NativeResearcher/0.1",
) -> AsyncIterator[dict[str, Any]]:
    parser = _OllamaStreamParser()
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": _ollama_think_option(thinking_level),
        "options": _ollama_runtime_options(),
    }
    thinking_budget = _ollama_thinking_budget(thinking_level)
    if thinking_budget is not None:
        payload["thinking"] = thinking_budget
    if tools:
        payload["tools"] = tools
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive
    headers = {"User-Agent": request_user_agent}
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code >= 400:
                body = await response.aread()
                try:
                    error_payload = json.loads(body.decode("utf-8") or "{}")
                    error_text = str(error_payload.get("error") or "").strip()
                except Exception:
                    error_text = body.decode("utf-8", errors="replace").strip()
                if error_text:
                    raise RuntimeError(f"Ollama model '{model}' failed: {error_text}")
                raise RuntimeError(f"Ollama model '{model}' failed with HTTP {response.status_code}.")
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                message = data.get("message")
                if isinstance(message, dict):
                    emitted_parts: list[dict[str, Any]] = []
                    raw_thinking = _clean_ollama_text(str(message.get("thinking") or ""), strip=False)
                    if raw_thinking.strip():
                        thinking_chunk = dict(data)
                        thinking_message = dict(message)
                        thinking_message["thinking"] = raw_thinking
                        thinking_message["content"] = ""
                        thinking_chunk["message"] = thinking_message
                        emitted_parts.append(thinking_chunk)

                    content_text = str(message.get("content") or "")
                    if content_text:
                        for part in parser.feed(content_text):
                            chunk = dict(data)
                            part_message = dict(message)
                            part_message["thinking"] = part.text if part.kind == "thinking" else ""
                            part_message["content"] = part.text if part.kind == "content" else ""
                            chunk["message"] = part_message
                            emitted_parts.append(chunk)

                    if emitted_parts:
                        if message.get("tool_calls"):
                            emitted_parts[-1]["message"]["tool_calls"] = message["tool_calls"]
                        for emitted in emitted_parts:
                            yield emitted
                        continue

                    data["message"] = _normalize_ollama_message(message)
                yield data

            for part in parser.flush():
                yield {
                    "message": {
                        "role": "assistant",
                        "thinking": part.text if part.kind == "thinking" else "",
                        "content": part.text if part.kind == "content" else "",
                    }
                }


async def ollama_warmup(
    *,
    base_url: str,
    model: str,
    keep_alive: str | int | float = "10m",
    timeout_seconds: float = 600.0,
    request_user_agent: str = "NativeResearcher/0.1",
) -> dict[str, Any]:
    return await ollama_chat(
        base_url=base_url,
        model=model,
        messages=[
            {
                "role": "user",
                "content": "Warm up the model and reply with a single word.",
            }
        ],
        keep_alive=keep_alive,
        timeout_seconds=timeout_seconds,
        request_user_agent=request_user_agent,
    )


def extract_ollama_tool_calls(message: dict[str, Any]) -> list[OllamaToolCall]:
    extracted: list[OllamaToolCall] = []
    for index, item in enumerate(normalized_tool_calls_from_message(message)):
        if not isinstance(item, dict):
            continue
        function_payload = item.get("function") or {}
        if not isinstance(function_payload, dict):
            continue
        name = str(function_payload.get("name") or "").strip()
        if not name:
            continue
        args = function_payload.get("arguments") or {}
        if isinstance(args, str):
            try:
                parsed_args = json.loads(args)
            except json.JSONDecodeError:
                parsed_args = {}
        elif isinstance(args, dict):
            parsed_args = args
        elif isinstance(args, list):
            parsed_args = {"items": args}
        else:
            parsed_args = {}
        if isinstance(parsed_args, list):
            parsed_args = {"items": parsed_args}
        if not isinstance(parsed_args, dict):
            parsed_args = {}
        extracted.append(
            OllamaToolCall(
                call_id=str(item.get("id") or function_payload.get("id") or f"call_{index + 1}"),
                name=name,
                args=dict(parsed_args),
                raw=item,
            )
        )
    return extracted
