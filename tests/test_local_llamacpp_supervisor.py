from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import local_llamacpp_supervisor as supervisor
from app.services.local_llamacpp_supervisor import (
    LlamaCppModelMismatchError,
    LlamaCppProbeResult,
    ensure_llamacpp_ready,
    sanitized_llamacpp_server_args,
)


def test_sanitized_llamacpp_server_args_removes_unsafe_launch_fields() -> None:
    args = sanitized_llamacpp_server_args(
        "-c 32768 --host 0.0.0.0 --port 9999 --alias wrong -b 512 -m other.gguf --cache-ram 0"
    )

    assert "--host" not in args
    assert "--port" not in args
    assert "--alias" not in args
    assert "-m" not in args
    assert "-c" in args
    assert "32768" in args
    assert "--cache-ram" in args


def test_ensure_llamacpp_ready_rejects_wrong_running_model(monkeypatch) -> None:
    async def fake_probe(base_url: str, *, request_user_agent: str, timeout_seconds: float = 4.0):
        _ = request_user_agent, timeout_seconds
        return LlamaCppProbeResult(base_url=base_url, connected=True, models=["other-model"])

    async def runner() -> None:
        monkeypatch.setattr(supervisor, "probe_llamacpp_server", fake_probe)
        settings = SimpleNamespace(
            llamacpp_base_url="http://localhost:8098",
            llamacpp_auto_start=True,
        )
        with pytest.raises(LlamaCppModelMismatchError):
            await ensure_llamacpp_ready(settings, model="target-model", request_user_agent="test")

    asyncio.run(runner())


def test_ensure_llamacpp_ready_starts_configured_local_server(monkeypatch, tmp_path: Path) -> None:
    executable = tmp_path / "llama-server"
    model = tmp_path / "model.gguf"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    model.write_text("gguf", encoding="utf-8")
    started = {"value": False}
    commands: list[list[str]] = []

    async def fake_probe(base_url: str, *, request_user_agent: str, timeout_seconds: float = 4.0):
        _ = request_user_agent, timeout_seconds
        if started["value"]:
            return LlamaCppProbeResult(base_url=base_url, connected=True, models=["target-model"])
        return LlamaCppProbeResult(base_url=base_url, connected=False, models=[], error="ConnectError")

    class FakeProcess:
        returncode = None

        def __init__(self, command, **kwargs):
            commands.append(list(command))
            started["value"] = True
            self.kwargs = kwargs

        def poll(self):
            return None

    async def runner() -> None:
        monkeypatch.setattr(supervisor, "probe_llamacpp_server", fake_probe)
        monkeypatch.setattr(supervisor.subprocess, "Popen", FakeProcess)
        settings = SimpleNamespace(
            llamacpp_base_url="http://localhost:8098",
            llamacpp_model="target-model",
            llamacpp_executable=str(executable),
            llamacpp_model_path=str(model),
            llamacpp_library_path="",
            llamacpp_server_args="--host 0.0.0.0 --port 9999 --alias wrong -c 32768",
            llamacpp_auto_start=True,
            llamacpp_log_path=str(tmp_path / "llama.log"),
        )
        events: list[dict] = []

        base_url = await ensure_llamacpp_ready(
            settings,
            model="target-model",
            request_user_agent="test",
            status_callback=events.append,
            timeout_seconds=2,
        )

        assert base_url == "http://localhost:8098"
        assert commands
        command = commands[0]
        assert command[:5] == [str(executable), "-m", str(model), "--host", "127.0.0.1"]
        assert "--port" in command
        assert "8098" in command
        assert "--alias" in command
        assert command[-2:] == ["--alias", "target-model"]
        assert "0.0.0.0" not in command
        assert "wrong" not in command
        assert any("Starting llama.cpp" in event["text"] for event in events)

    asyncio.run(runner())

