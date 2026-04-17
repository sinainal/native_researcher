"""Model selection helpers for chat providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.genai.helper_models import DEFAULT_HELPER_MODEL, resolve_helper_model_name

OLLAMA_MODEL_PREFIX = "ollama:"


@dataclass(frozen=True)
class LLMTarget:
    provider: Literal["gemini", "ollama"]
    model_name: str
    display_name: str


def format_ollama_model_choice(model_name: str | None) -> str:
    normalized = str(model_name or "").strip()
    if not normalized:
        return ""
    return f"{OLLAMA_MODEL_PREFIX}{normalized}"


def is_ollama_model_choice(model_name: str | None) -> bool:
    normalized = str(model_name or "").strip().lower()
    return normalized.startswith(OLLAMA_MODEL_PREFIX)


def resolve_chat_model_target(requested_model: str | None, *, settings: Any | None = None) -> LLMTarget:
    normalized = str(requested_model or "").strip()
    if is_ollama_model_choice(normalized):
        configured_model = str(getattr(settings, "ollama_model", "") or "").strip()
        selected_model = normalized[len(OLLAMA_MODEL_PREFIX):].strip() or configured_model
        if not selected_model:
            raise RuntimeError("Ollama modeli secili ama ayarlarda model tanimli degil.")
        return LLMTarget(
            provider="ollama",
            model_name=selected_model,
            display_name=format_ollama_model_choice(selected_model),
        )
    resolved = resolve_helper_model_name(normalized or None)
    return LLMTarget(
        provider="gemini",
        model_name=resolved,
        display_name=normalized or DEFAULT_HELPER_MODEL,
    )
