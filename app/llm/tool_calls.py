"""Tool-call normalization helpers shared by local chat providers."""

from __future__ import annotations

import json
import re
from typing import Any


TOOL_BLOCK_PATTERN = re.compile(
    r"(?:<\|?tool_call\|?>|<tool_call>)(.*?)(?:<\|?/tool_call\|?>|</tool_call>|<\|tool_response\|>|$)",
    re.IGNORECASE | re.DOTALL,
)


def normalized_tool_calls_from_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    calls = normalize_tool_call_items(message.get("tool_calls") or [])
    if calls:
        return calls
    return tool_calls_from_text(str(message.get("content") or ""))


def normalize_tool_call_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        call = _normalize_tool_call_item(item, index)
        if call is not None:
            normalized.append(call)
    return normalized


def tool_calls_from_text(text: str) -> list[dict[str, Any]]:
    cleaned = _strip_fence(text)
    payloads: list[Any] = []
    for match in TOOL_BLOCK_PATTERN.finditer(cleaned):
        parsed = _parse_json_payload(match.group(1))
        if parsed is not None:
            payloads.append(parsed)
    if not payloads:
        parsed = _parse_json_payload(cleaned)
        if parsed is not None:
            payloads.append(parsed)

    calls: list[dict[str, Any]] = []
    for payload in payloads:
        calls.extend(_tool_calls_from_payload(payload, offset=len(calls)))
    return calls


def _tool_calls_from_payload(payload: Any, *, offset: int) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        calls: list[dict[str, Any]] = []
        for item in payload:
            calls.extend(_tool_calls_from_payload(item, offset=offset + len(calls)))
        return calls
    if not isinstance(payload, dict):
        return []

    if isinstance(payload.get("tool_calls"), list):
        return normalize_tool_call_items(payload.get("tool_calls"))
    if isinstance(payload.get("function"), dict):
        call = _normalize_tool_call_item(payload, offset)
        return [call] if call else []

    name = str(payload.get("name") or payload.get("tool_name") or "").strip()
    arguments = payload.get("arguments")
    if arguments is None:
        arguments = payload.get("parameters")
    if name:
        return [_openai_tool_call(name=name, arguments=arguments, index=offset, call_id=payload.get("id"))]

    if len(payload) == 1:
        only_name, only_args = next(iter(payload.items()))
        if isinstance(only_name, str) and isinstance(only_args, (dict, list, str)):
            return [_openai_tool_call(name=only_name, arguments=only_args, index=offset)]
    return []


def _normalize_tool_call_item(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    function_payload = item.get("function") or {}
    if not isinstance(function_payload, dict):
        return None
    name = str(function_payload.get("name") or item.get("name") or "").strip()
    if not name:
        return None
    arguments = function_payload.get("arguments")
    call_id = item.get("id") or function_payload.get("id")
    return _openai_tool_call(name=name, arguments=arguments, index=index, call_id=call_id)


def _openai_tool_call(*, name: str, arguments: Any, index: int, call_id: Any | None = None) -> dict[str, Any]:
    if isinstance(arguments, str):
        argument_text = arguments
    else:
        argument_text = json.dumps(arguments or {}, ensure_ascii=False)
    return {
        "id": str(call_id or f"call_{index + 1}"),
        "type": "function",
        "function": {
            "name": name,
            "arguments": argument_text,
        },
    }


def _parse_json_payload(raw: str) -> Any | None:
    cleaned = _strip_fence(raw)
    if not cleaned:
        return None
    for candidate in _json_candidates(cleaned):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _json_candidates(text: str) -> list[str]:
    stripped = text.strip()
    candidates = [stripped]
    starts = [index for index in (stripped.find("{"), stripped.find("[")) if index >= 0]
    if starts:
        candidates.append(stripped[min(starts):])
    return candidates


def _strip_fence(text: str) -> str:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned
