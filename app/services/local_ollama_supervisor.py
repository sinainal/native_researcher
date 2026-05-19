"""Local Ollama readiness checks for selected-model execution."""

from __future__ import annotations

from typing import Any

import httpx


def normalize_ollama_base_url(value: str | None, default: str = "http://localhost:11434") -> str:
    normalized = str(value or "").strip() or default
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


async def ollama_installed_models(
    base_url: str,
    *,
    request_user_agent: str,
    timeout_seconds: float = 4.0,
) -> list[str]:
    headers = {"User-Agent": request_user_agent}
    async with httpx.AsyncClient(
        base_url=normalize_ollama_base_url(base_url),
        timeout=httpx.Timeout(timeout_seconds),
        headers=headers,
        follow_redirects=True,
    ) as client:
        response = await client.get("/api/tags")
        response.raise_for_status()
        payload = response.json() or {}
    names: list[str] = []
    for item in payload.get("models") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                names.append(name)
    return names


async def ensure_ollama_model_available(
    *,
    base_url: str,
    model: str,
    request_user_agent: str,
) -> None:
    normalized_model = str(model or "").strip()
    if not normalized_model:
        raise RuntimeError("Ollama model is not configured.")
    models = await ollama_installed_models(base_url, request_user_agent=request_user_agent)
    if normalized_model not in set(models):
        available = ", ".join(models[:8]) or "none"
        raise RuntimeError(f"Ollama model '{normalized_model}' is not installed. Available models: {available}.")


def is_ollama_model_not_found_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "ollama model" in text and ("not available" in text or "not installed" in text or "not found" in text)

