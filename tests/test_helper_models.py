"""Helper model mapping tests."""

from __future__ import annotations

from app.genai.helper_models import resolve_helper_model_name


def test_resolve_helper_model_name_supports_gemini_25_family() -> None:
    assert resolve_helper_model_name("Gemini 2.5 Pro") == "gemini-2.5-pro"
    assert resolve_helper_model_name("Gemini 2.5 Flash") == "gemini-2.5-flash"
    assert resolve_helper_model_name("Gemini 2.5 Flash Lite") == "gemini-2.5-flash-lite"


def test_resolve_helper_model_name_keeps_existing_models() -> None:
    assert resolve_helper_model_name("Gemini 3.1 Pro") == "gemini-3.1-pro-preview"
    assert resolve_helper_model_name("Gemini 3 Flash") == "gemini-3-flash-preview"
    assert resolve_helper_model_name("Gemini 3.1 Flash Lite") == "gemini-3.1-flash-lite-preview"
