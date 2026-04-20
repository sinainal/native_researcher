"""Ollama chat API helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaToolCall:
    call_id: str
    name: str
    args: dict[str, Any]
    raw: dict[str, Any]


_THINK_BLOCK_RE = re.compile(r"<think>\s*(.*?)\s*</think>", re.DOTALL)
_TOOL_ARTIFACT_RE = re.compile(r"<[^>\n]*tool_(?:call|response)[^>\n]*>", re.IGNORECASE)


def _normalize_ollama_message(message: dict[str, Any]) -> dict[str, Any]:
    content = str(message.get("content") or "")
    thinking = str(message.get("thinking") or "").strip()
    if not thinking and "<think>" in content:
        think_parts = [part.strip() for part in _THINK_BLOCK_RE.findall(content) if part.strip()]
        if think_parts:
            thinking = "\n\n".join(think_parts)
            content = _THINK_BLOCK_RE.sub("", content)

    content = _TOOL_ARTIFACT_RE.sub("", content)
    content = (
        content.replace("<|endoftext|>", "")
        .replace("<|im_start|>", "")
        .replace("<|im_end|>", "")
        .strip()
    )

    normalized = dict(message)
    normalized["content"] = content
    if thinking and not str(normalized.get("thinking") or "").strip():
        normalized["thinking"] = thinking
    return normalized


def _ollama_think_option(thinking_level: str) -> bool | str:
    level = str(thinking_level or "off").strip().lower()
    if level == "off":
        return False
    if level == "on":
        return True
    return True


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
    }
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
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": _ollama_think_option(thinking_level),
    }
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
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                message = data.get("message")
                if isinstance(message, dict):
                    data["message"] = _normalize_ollama_message(message)
                yield data


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
    for index, item in enumerate(message.get("tool_calls") or []):
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
        else:
            parsed_args = {}
        extracted.append(
            OllamaToolCall(
                call_id=str(function_payload.get("id") or f"call_{index + 1}"),
                name=name,
                args=dict(parsed_args),
                raw=item,
            )
        )
    return extracted
