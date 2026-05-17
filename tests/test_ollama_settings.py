"""Ollama settings API tests."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx

from app.core.config import Settings
from app.main import create_app
from app.schemas.settings import LlamaCppModelInfo, OllamaModelInfo


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


def _set_warmup_state(request, *, pending: bool, model: str, error: str | None = None) -> None:
    request.app.state.ollama_warmup_pending = pending
    request.app.state.ollama_warmup_model = model
    request.app.state.ollama_warmup_error = error
    request.app.state.ollama_warmup_token = getattr(request.app.state, "ollama_warmup_token", 0)
    request.app.state.ollama_warmup_task = None


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
        ollama_thinking_level_path=temp_root / "ollama_thinking_level",
        llamacpp_base_url_path=temp_root / "llamacpp_base_url",
        llamacpp_model_name_path=temp_root / "llamacpp_model",
        llamacpp_executable_path=temp_root / "llamacpp_executable",
        llamacpp_model_path_path=temp_root / "llamacpp_model_path",
        llamacpp_library_path_path=temp_root / "llamacpp_library_path",
        llamacpp_server_args_path=temp_root / "llamacpp_server_args",
        pdf_unpaywall_fallback_enabled_path=temp_root / "pdf_unpaywall_fallback_enabled",
        pdf_core_fallback_enabled_path=temp_root / "pdf_core_fallback_enabled",
        pdf_arxiv_fallback_enabled_path=temp_root / "pdf_arxiv_fallback_enabled",
    )


async def _fake_llamacpp_probe_success(base_url: str, *, request_user_agent: str):
    _ = base_url, request_user_agent
    return True, [LlamaCppModelInfo(id="qwen3.6-q4km")], None


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
                        "ollama_thinking_level": "on",
                    },
                )
                assert saved.status_code == 200
                saved_payload = saved.json()
                assert saved_payload["ollama_base_url"] == "http://localhost:11434"
                assert saved_payload["ollama_model"] == "llama3.1:8b"
                assert saved_payload["ollama_thinking_level"] == "on"
                assert saved_payload["connected"] is True
                assert (settings.ollama_base_url_path.read_text(encoding="utf-8")).strip() == "http://localhost:11434"
                assert (settings.ollama_model_path.read_text(encoding="utf-8")).strip() == "llama3.1:8b"
                assert (settings.ollama_thinking_level_path.read_text(encoding="utf-8")).strip() == "on"

    import asyncio

    asyncio.run(runner())


def test_llamacpp_settings_accepts_named_qwen_profile(monkeypatch) -> None:
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
            monkeypatch.setattr("app.api.routes.app_settings._probe_llamacpp", _fake_llamacpp_probe_success)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.put(
                    "/app/llamacpp",
                    json={
                        "llamacpp_base_url": "127.0.0.1:8098",
                        "llamacpp_model": "qwen3.6-q4km",
                        "llamacpp_profile": "qwen36-q4km-safe",
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["llamacpp_profile"] == "qwen36-q4km-safe"
                assert "--n-cpu-moe 15" in payload["llamacpp_server_args"]
                assert "-ctk turbo4" in payload["llamacpp_server_args"]
                assert "-ctv turbo3" in payload["llamacpp_server_args"]
                assert "--direct-io" in payload["llamacpp_server_args"]
                assert "--alias qwen3.6-q4km" in payload["llamacpp_server_args"]
                assert payload["profiles"]

    import asyncio

    asyncio.run(runner())


def test_ollama_settings_warms_selected_model(monkeypatch) -> None:
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
            warmup_calls: list[tuple[str, str, str]] = []

            def _fake_schedule(request, *, base_url: str, model: str, request_user_agent: str):
                warmup_calls.append((base_url, model, request_user_agent))
                _set_warmup_state(request, pending=True, model=model, error=None)

            monkeypatch.setattr("app.api.routes.app_settings._probe_ollama", _fake_probe_success)
            monkeypatch.setattr("app.api.routes.app_settings._schedule_ollama_warmup", _fake_schedule)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.put(
                    "/app/ollama",
                    json={
                        "ollama_base_url": "localhost:11434",
                        "ollama_model": "gemma4:e2b",
                        "warmup": True,
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["connected"] is True
                assert payload["warmup_error"] is None
                assert payload["warming_up"] is True
                assert warmup_calls == [
                    ("http://localhost:11434", "gemma4:e2b", settings.request_user_agent),
                ]

    import asyncio

    asyncio.run(runner())


def test_ollama_settings_starts_local_service_before_warmup(monkeypatch) -> None:
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
            probe_results = [
                (False, None, [], "ConnectError: Connection refused"),
                (False, None, [], "ConnectError: Connection refused"),
                (
                    True,
                    "0.5.7",
                    [OllamaModelInfo(name="gemma4:e2b", size=4_900_000_000)],
                    None,
                ),
            ]
            warmup_calls: list[tuple[str, str, str]] = []
            spawn_calls: list[str] = []

            async def _fake_probe(*args, **kwargs):
                _ = args, kwargs
                if probe_results:
                    return probe_results.pop(0)
                return (
                    True,
                    "0.5.7",
                    [OllamaModelInfo(name="gemma4:e2b", size=4_900_000_000)],
                    None,
                )

            def _fake_spawn(request, base_url):
                _ = request
                spawn_calls.append(base_url)
                return True, None

            def _fake_schedule(request, *, base_url: str, model: str, request_user_agent: str):
                warmup_calls.append((base_url, model, request_user_agent))
                _set_warmup_state(request, pending=True, model=model, error=None)

            monkeypatch.setattr("app.api.routes.app_settings._probe_ollama", _fake_probe)
            monkeypatch.setattr("app.api.routes.app_settings._spawn_ollama_process", _fake_spawn)
            monkeypatch.setattr("app.api.routes.app_settings._schedule_ollama_warmup", _fake_schedule)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.put(
                    "/app/ollama",
                    json={
                        "ollama_base_url": "localhost:11434",
                        "ollama_model": "gemma4:e2b",
                        "warmup": True,
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["connected"] is True
                assert payload["warmup_error"] is None
                assert payload["warming_up"] is True
                assert spawn_calls == ["http://localhost:11434"]
                assert warmup_calls == [
                    ("http://localhost:11434", "gemma4:e2b", settings.request_user_agent),
                ]

    import asyncio

    asyncio.run(runner())


def test_ollama_settings_reports_warmup_error(monkeypatch) -> None:
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

            def _fake_schedule(request, *, base_url: str, model: str, request_user_agent: str):
                _ = base_url, request_user_agent
                _set_warmup_state(request, pending=False, model=model, error="RuntimeError: model is still loading")

            monkeypatch.setattr("app.api.routes.app_settings._schedule_ollama_warmup", _fake_schedule)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.put(
                    "/app/ollama",
                    json={
                        "ollama_base_url": "localhost:11434",
                        "ollama_model": "gemma4:e2b",
                        "warmup": True,
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["connected"] is True
                assert payload["warmup_error"] == "RuntimeError: model is still loading"
                assert payload["warming_up"] is False
                assert payload["error"] is None

    import asyncio

    asyncio.run(runner())


def test_ollama_settings_stops_previous_model_before_switch(monkeypatch) -> None:
    async def runner() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            settings = _build_settings(temp_root)
            settings.ollama_model_path.parent.mkdir(parents=True, exist_ok=True)
            settings.ollama_model_path.write_text("llama3.1:8b\n", encoding="utf-8")
            app = create_app(
                settings=settings,
                pubmed_service=FakePubMedService(),
                pdf_service=FakePDFService(),
                helper_service=FakeHelperService(),
                batch_llm_service=FakeBatchLLMService(),
            )
            stop_calls: list[tuple[str, str]] = []

            def _fake_stop(base_url: str, model: str):
                stop_calls.append((base_url, model))
                return True, None

            def _fake_schedule(request, *, base_url: str, model: str, request_user_agent: str):
                _ = base_url, request_user_agent
                _set_warmup_state(request, pending=True, model=model, error=None)

            monkeypatch.setattr("app.api.routes.app_settings._probe_ollama", _fake_probe_success)
            monkeypatch.setattr("app.api.routes.app_settings._stop_ollama_model", _fake_stop)
            monkeypatch.setattr("app.api.routes.app_settings._schedule_ollama_warmup", _fake_schedule)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                response = await client.put(
                    "/app/ollama",
                    json={
                        "ollama_base_url": "localhost:11434",
                        "ollama_model": "gemma4:e2b",
                        "warmup": True,
                    },
                )
                assert response.status_code == 200
                payload = response.json()
                assert payload["ollama_model"] == "gemma4:e2b"
                assert payload["warming_up"] is True
                assert stop_calls == [("http://localhost:11434", "llama3.1:8b")]

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
