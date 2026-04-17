"""Ollama chat API helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaToolCall:
    call_id: str
    name: str
    args: dict[str, Any]
    raw: dict[str, Any]


def _ollama_think_option(thinking_level: str) -> bool | str:
    level = str(thinking_level or "off").strip().lower()
    if level == "off":
        return False
    if level == "low":
        return "low"
    if level == "max":
        return "high"
    return True


async def ollama_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    thinking_level: str = "off",
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
    headers = {"User-Agent": request_user_agent}
    timeout = httpx.Timeout(120.0, connect=5.0)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        return response.json()


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
