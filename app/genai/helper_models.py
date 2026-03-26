"""Helper model selection."""

from __future__ import annotations


DEFAULT_HELPER_MODEL = "gemini-3.1-flash-lite-preview"

MODEL_NAME_MAP = {
    "gemini 3.1 pro": "gemini-3.1-pro-preview",
    "gemini 3 flash": "gemini-3-flash-preview",
    "gemini 3.1 flash lite": "gemini-3.1-flash-lite-preview",
    "gemini 2.5 pro": "gemini-2.5-pro",
    "gemini 2.5 flash": "gemini-2.5-flash",
    "gemini 2.5 flash lite": "gemini-2.5-flash-lite",
}


def resolve_helper_model_name(requested_model: str | None) -> str:
    normalized = (requested_model or "").strip().lower()
    if not normalized:
        return DEFAULT_HELPER_MODEL
    if normalized in MODEL_NAME_MAP:
        return MODEL_NAME_MAP[normalized]
    if normalized.startswith("gemini-"):
        return requested_model.strip()
    if "2.5" in normalized and "flash lite" in normalized:
        return "gemini-2.5-flash-lite"
    if "2.5" in normalized and "flash" in normalized:
        return "gemini-2.5-flash"
    if "2.5" in normalized and "pro" in normalized:
        return "gemini-2.5-pro"
    if "3.1" in normalized and "flash lite" in normalized:
        return "gemini-3.1-flash-lite-preview"
    if "3" in normalized and "flash" in normalized:
        return "gemini-3-flash-preview"
    return DEFAULT_HELPER_MODEL
