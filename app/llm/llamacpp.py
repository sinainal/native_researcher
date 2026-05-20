"""llama.cpp OpenAI-compatible chat helpers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.llm.tool_calls import normalized_tool_calls_from_message, tool_calls_from_text

LLAMACPP_DEFAULT_TEMPERATURE = 0.7
LLAMACPP_DEFAULT_TOP_P = 0.9
LLAMACPP_DEFAULT_MAX_TOKENS = 4096
LLAMACPP_DEFAULT_REASONING_BUDGET_TOKENS = 768
LLAMACPP_LOW_REASONING_BUDGET_TOKENS = 384


def _normalize_openai_message(message: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(message)
    normalized["content"] = str(normalized.get("content") or "")
    parsed_tool_calls = normalized_tool_calls_from_message(normalized)
    if parsed_tool_calls:
        normalized["tool_calls"] = parsed_tool_calls
        if tool_calls_from_text(normalized["content"]):
            normalized["content"] = ""
    reasoning = str(normalized.get("reasoning_content") or "").strip()
    if reasoning and not str(normalized.get("thinking") or "").strip():
        normalized["thinking"] = reasoning
    if "tool_calls" in normalized and normalized["tool_calls"] is None:
        normalized.pop("tool_calls", None)
    return normalized


def _openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        item: dict[str, Any] = {"role": role, "content": str(message.get("content") or "")}
        if role == "tool":
            item["tool_call_id"] = str(message.get("tool_call_id") or message.get("tool_name") or "tool_call")
        if role == "assistant" and message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        converted.append(item)
    return converted


def _openai_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            converted.append(tool)
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
        converted.append({"type": "function", "function": function})
    return converted


def _llamacpp_tool_choice(tool_choice: Any | None) -> Any | None:
    if isinstance(tool_choice, dict):
        return None
    return tool_choice


def _chat_payload(
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    stream: bool,
    tool_choice: Any | None = None,
    thinking_level: str = "off",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model or "local",
        "messages": _openai_messages(messages),
        "stream": stream,
        "temperature": LLAMACPP_DEFAULT_TEMPERATURE,
        "top_p": LLAMACPP_DEFAULT_TOP_P,
        "max_tokens": LLAMACPP_DEFAULT_MAX_TOKENS,
    }
    openai_tools = _openai_tools(tools)
    if openai_tools:
        payload["tools"] = openai_tools
        payload["tool_choice"] = _llamacpp_tool_choice(tool_choice) or "auto"
    level = str(thinking_level or "off").strip().lower()
    if level in {"on", "off"}:
        payload["chat_template_kwargs"] = {"enable_thinking": level == "on"}
        if level == "on":
            payload["thinking_budget_tokens"] = LLAMACPP_DEFAULT_REASONING_BUDGET_TOKENS
    elif level == "low":
        payload["chat_template_kwargs"] = {"enable_thinking": True}
        payload["thinking_budget_tokens"] = LLAMACPP_LOW_REASONING_BUDGET_TOKENS
    elif level == "max":
        payload["chat_template_kwargs"] = {"enable_thinking": True}
    return payload


async def llamacpp_chat(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    thinking_level: str = "off",
    tool_choice: Any | None = None,
    keep_alive: str | int | float | None = None,
    timeout_seconds: float = 120.0,
    request_user_agent: str = "NativeResearcher/0.1",
) -> dict[str, Any]:
    del keep_alive
    headers = {"User-Agent": request_user_agent}
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json=_chat_payload(
                model=model,
                messages=messages,
                tools=tools,
                stream=False,
                tool_choice=tool_choice,
                thinking_level=thinking_level,
            ),
        )
        response.raise_for_status()
        data = response.json()
    choices = data.get("choices") or []
    message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
    return {"model": data.get("model") or model, "message": _normalize_openai_message(message or {})}


def _merge_tool_call_delta(
    tool_calls: dict[int, dict[str, Any]],
    delta_call: dict[str, Any],
    fallback_index: int,
) -> None:
    index = int(delta_call.get("index") if delta_call.get("index") is not None else fallback_index)
    target = tool_calls.setdefault(index, {"id": f"call_{index + 1}", "type": "function", "function": {"name": "", "arguments": ""}})
    if delta_call.get("id"):
        target["id"] = str(delta_call["id"])
    function_delta = delta_call.get("function") or {}
    if isinstance(function_delta, dict):
        function = target.setdefault("function", {})
        if function_delta.get("name"):
            function["name"] = str(function_delta["name"])
        if function_delta.get("arguments") is not None:
            function["arguments"] = str(function.get("arguments") or "") + str(function_delta.get("arguments") or "")


async def llamacpp_chat_stream(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    thinking_level: str = "off",
    tool_choice: Any | None = None,
    keep_alive: str | int | float | None = None,
    timeout_seconds: float = 120.0,
    request_user_agent: str = "NativeResearcher/0.1",
) -> AsyncIterator[dict[str, Any]]:
    del keep_alive
    headers = {"User-Agent": request_user_agent}
    timeout = httpx.Timeout(timeout_seconds, connect=5.0)
    collected_tool_calls: dict[int, dict[str, Any]] = {}
    collected_content: list[str] = []
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=timeout,
        headers=headers,
        follow_redirects=True,
    ) as client:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json=_chat_payload(
                model=model,
                messages=messages,
                tools=tools,
                stream=True,
                tool_choice=tool_choice,
                thinking_level=thinking_level,
            ),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line == "[DONE]":
                    break
                data = json.loads(line)
                choices = data.get("choices") or []
                if not choices or not isinstance(choices[0], dict):
                    continue
                delta = choices[0].get("delta") or {}
                for fallback_index, delta_call in enumerate(delta.get("tool_calls") or []):
                    if isinstance(delta_call, dict):
                        _merge_tool_call_delta(collected_tool_calls, delta_call, fallback_index)
                content = str(delta.get("content") or "")
                reasoning = str(delta.get("reasoning_content") or "")
                if reasoning:
                    yield {"model": data.get("model") or model, "message": {"role": "assistant", "thinking": reasoning, "content": ""}}
                if content:
                    collected_content.append(content)
                    if "<tool_call" in "".join(collected_content).lower():
                        continue
                    yield {"model": data.get("model") or model, "message": {"role": "assistant", "content": content}}
    parsed_content_tool_calls = tool_calls_from_text("".join(collected_content)) if not collected_tool_calls else []
    for index, parsed_call in enumerate(parsed_content_tool_calls):
        collected_tool_calls[index] = parsed_call
    if collected_tool_calls:
        yield {
            "model": model,
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [collected_tool_calls[index] for index in sorted(collected_tool_calls)],
            },
        }
