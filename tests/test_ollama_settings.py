"""Ollama settings API tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.schemas.settings import OllamaModelInfo


class FakePubMedService:
    pass


class FakePDFService:
    pass


class FakeHelperService:
    pass


class FakeBatchLLMService:
    pass


async def _fake_probe_success(base_url: str, *, request_user_agent: str):
    _ = base_url, request_user_agent
    return (
        True,
        "0.5.7",
        [
            OllamaModelInfo(name="llama3.1:8b", size=4_900_000_000),
            OllamaModelInfo(name="mistral:7b", size=4_100_000_000),
        ],
        None,
    )


async def _fake_probe_down(base_url: str, *, request_user_agent: str):
    _ = base_url, request_user_agent
    return (False, None, [], "ConnectError: Connection refused")


def _build_settings(temp_root: Path) -> Settings:
    return Settings(
        download_root=temp_root / "downloads",
        workspace_root=temp_root / "workspace",
        helper_log_path=temp_root / "logs" / "helper_ai_history.jsonl",
        app_event_log_path=temp_root / "logs" / "app_events.jsonl",
        assistant_api_key_path=temp_root / "assistant_api_key.txt",
        ncbi_api_key_path=temp_root / "ncbi_api",
        unpaywall_email_path=temp_root / "unpaywall_email",
        openalex_api_key_path=temp_root / "openalex_api_key",
        core_api_key_path=temp_root / "core_api_key",
        pubmed_oa_only_path=temp_root / "pubmed_oa_only",
        ai_primary_search_resource_path=temp_root / "ai_primary_search_resource",
        pdf_downloader_mode_path=temp_root / "pdf_downloader_mode",
        ollama_base_url_path=temp_root / "ollama_base_url",
        ollama_model_path=temp_root / "ollama_model",
        pdf_unpaywall_fallback_enabled_path=temp_root / "pdf_unpaywall_fallback_enabled",
        pdf_core_fallback_enabled_path=temp_root / "pdf_core_fallback_enabled",
        pdf_arxiv_fallback_enabled_path=temp_root / "pdf_arxiv_fallback_enabled",
    )


def test_ollama_settings_detects_running_service(monkeypatch) -> None:
    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = _build_settings(temp_root)
            app = create_app(
                settings=settings,
                pubmed_service=FakePubMedService(),
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            monkeypatch.setattr("app.api.routes.app_settings._probe_ollama", _fake_probe_success)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/app/ollama")
                assert response.status_code == 200
                payload = response.json()
                assert payload["connected"] is True
                assert payload["version"] == "0.5.7"
                assert [item["name"] for item in payload["models"]] == ["llama3.1:8b", "mistral:7b"]

                saved = await client.put(
                    "/app/ollama",
                    json={
                        "ollama_base_url": "localhost:11434",
                        "ollama_model": "llama3.1:8b",
                    },
                )
                assert saved.status_code == 200
                saved_payload = saved.json()
                assert saved_payload["ollama_base_url"] == "http://localhost:11434"
                assert saved_payload["ollama_model"] == "llama3.1:8b"
                assert saved_payload["connected"] is True
                assert (settings.ollama_base_url_path.read_text(encoding="utf-8")).strip() == "http://localhost:11434"
                assert (settings.ollama_model_path.read_text(encoding="utf-8")).strip() == "llama3.1:8b"

    import asyncio

    asyncio.run(runner())


def test_ollama_settings_detects_missing_service(monkeypatch) -> None:
    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = _build_settings(temp_root)
            app = create_app(
                settings=settings,
                pubmed_service=FakePubMedService(),
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            monkeypatch.setattr("app.api.routes.app_settings._probe_ollama", _fake_probe_down)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.get("/app/ollama")
                assert response.status_code == 200
                payload = response.json()
                assert payload["connected"] is False
                assert payload["models"] == []
                assert payload["error"]

    import asyncio

    asyncio.run(runner())
