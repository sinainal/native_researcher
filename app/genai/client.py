"""Google GenAI client loading helpers."""

from __future__ import annotations


def load_genai_sdk():
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError(
            "Helper AI icin `google-genai` paketi gerekli. `pip install -r requirements.txt` calistir."
        ) from exc
    return genai, types


def create_genai_client(api_key: str):
    genai, _types = load_genai_sdk()
    return genai.Client(api_key=api_key)
