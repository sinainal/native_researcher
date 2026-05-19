"""Safe local llama.cpp server detection and startup."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import signal
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

LOCAL_LLAMA_PORTS = (8098, 8099, 8100)
LLAMACPP_START_TIMEOUT_SECONDS = 120.0

_START_LOCK = asyncio.Lock()
_PROCESSES: dict[str, tuple[subprocess.Popen, Any]] = {}


@dataclass(frozen=True)
class LlamaCppProbeResult:
    base_url: str
    connected: bool
    models: list[str]
    error: str | None = None


class LlamaCppModelMismatchError(RuntimeError):
    pass


def normalize_llamacpp_base_url(value: str | None, default: str = "http://localhost:8098") -> str:
    normalized = str(value or "").strip() or default
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def is_local_llamacpp_url(base_url: str) -> bool:
    parsed = urlparse(normalize_llamacpp_base_url(base_url))
    return (parsed.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}


def _port_from_base_url(base_url: str | None) -> int | None:
    if not base_url:
        return None
    parsed = urlparse(normalize_llamacpp_base_url(base_url))
    return parsed.port or 8098


def llama_model_matches(requested_model: str, served_models: list[str]) -> bool:
    requested = str(requested_model or "").strip()
    if not requested or requested == "local" or not served_models:
        return True
    return requested in {str(model or "").strip() for model in served_models}


def llamacpp_log_tail(log_path: str | Path | None, *, lines: int = 20) -> str:
    if not log_path:
        return ""
    path = Path(log_path)
    if not path.exists():
        return ""
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


async def probe_llamacpp_server(
    base_url: str,
    *,
    request_user_agent: str,
    timeout_seconds: float = 4.0,
) -> LlamaCppProbeResult:
    normalized_base_url = normalize_llamacpp_base_url(base_url)
    headers = {"User-Agent": request_user_agent}
    try:
        async with httpx.AsyncClient(
            base_url=normalized_base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers=headers,
            follow_redirects=True,
        ) as client:
            health_response = await client.get("/health")
            if health_response.status_code >= 500:
                health_response.raise_for_status()
            models: list[str] = []
            try:
                models_response = await client.get("/v1/models")
                models_response.raise_for_status()
                models_payload = models_response.json() or {}
                for item in models_payload.get("data") or []:
                    if isinstance(item, dict) and str(item.get("id") or "").strip():
                        models.append(str(item.get("id")).strip())
            except Exception:
                models = []
            return LlamaCppProbeResult(base_url=normalized_base_url, connected=True, models=models)
    except Exception as exc:
        return LlamaCppProbeResult(
            base_url=normalized_base_url,
            connected=False,
            models=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def _candidate_base_urls(configured_base_url: str) -> list[str]:
    configured = normalize_llamacpp_base_url(configured_base_url)
    parsed = urlparse(configured)
    host = parsed.hostname or "127.0.0.1"
    candidates = [configured]
    if host in {"localhost", "127.0.0.1", "::1"}:
        for port in LOCAL_LLAMA_PORTS:
            candidate = f"{parsed.scheme or 'http'}://{host}:{port}"
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _emit(status_callback: Callable[[dict[str, Any]], None] | None, text: str, **extra: Any) -> None:
    if status_callback is None:
        return
    event = {"type": "status", "text": text}
    event.update(extra)
    status_callback(event)


def _skip_server_arg(tokens: list[str], index: int) -> int:
    token = tokens[index]
    options_with_value = {
        "-m",
        "--model",
        "--model-url",
        "--host",
        "--port",
        "--alias",
        "--api-key",
    }
    if token in options_with_value:
        return index + 2
    if token.startswith("--host=") or token.startswith("--port=") or token.startswith("--alias="):
        return index + 1
    if token.startswith("-m="):
        return index + 1
    return index


def sanitized_llamacpp_server_args(server_args: str) -> list[str]:
    tokens = shlex.split(str(server_args or ""))
    sanitized: list[str] = []
    index = 0
    while index < len(tokens):
        next_index = _skip_server_arg(tokens, index)
        if next_index != index:
            index = next_index
            continue
        sanitized.append(tokens[index])
        index += 1
    return sanitized


def _default_log_path(base_url: str) -> Path:
    parsed = urlparse(normalize_llamacpp_base_url(base_url))
    port = parsed.port or 8098
    return Path("logs") / f"llamacpp_server_{port}.log"


def _build_start_command(settings: Any, *, base_url: str, model: str) -> tuple[list[str], dict[str, str], Path]:
    executable = str(getattr(settings, "llamacpp_executable", "") or "").strip()
    model_path = str(getattr(settings, "llamacpp_model_path", "") or "").strip()
    if not executable:
        raise RuntimeError("llama.cpp executable path is not configured.")
    if not model_path:
        raise RuntimeError("llama.cpp model path is not configured.")
    if not Path(executable).is_file():
        raise RuntimeError(f"llama.cpp executable was not found: {executable}")
    if not Path(model_path).is_file():
        raise RuntimeError(f"llama.cpp model file was not found: {model_path}")

    parsed = urlparse(normalize_llamacpp_base_url(base_url))
    host = parsed.hostname or "127.0.0.1"
    if host == "localhost":
        host = "127.0.0.1"
    if host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("llama.cpp auto-start is only supported for local hosts.")
    port = str(parsed.port or 8098)
    command = [
        executable,
        "-m",
        model_path,
        "--host",
        host,
        "--port",
        port,
        *sanitized_llamacpp_server_args(str(getattr(settings, "llamacpp_server_args", "") or "")),
        "--alias",
        model or "local",
    ]
    env = os.environ.copy()
    library_path = str(getattr(settings, "llamacpp_library_path", "") or "").strip()
    if library_path:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = library_path + ((f":{existing}") if existing else "")
    log_path = Path(str(getattr(settings, "llamacpp_log_path", "") or "").strip() or _default_log_path(base_url))
    return command, env, log_path


async def _find_running_server(
    settings: Any,
    *,
    model: str,
    request_user_agent: str,
    status_callback: Callable[[dict[str, Any]], None] | None,
) -> str | None:
    configured = normalize_llamacpp_base_url(str(getattr(settings, "llamacpp_base_url", "") or "http://localhost:8098"))
    for index, candidate in enumerate(_candidate_base_urls(configured)):
        _emit(status_callback, f"Checking llama.cpp server at {candidate}.")
        probe = await probe_llamacpp_server(candidate, request_user_agent=request_user_agent)
        if not probe.connected:
            continue
        if llama_model_matches(model, probe.models):
            if candidate != configured:
                object.__setattr__(settings, "llamacpp_base_url", candidate)
            _emit(status_callback, f"llama.cpp is ready at {candidate}.")
            return candidate
        if index == 0:
            served = ", ".join(probe.models) or "unknown model"
            raise LlamaCppModelMismatchError(
                f"llama.cpp is running at {candidate}, but it is serving {served} instead of {model or 'local'}."
            )
    return None


async def ensure_llamacpp_ready(
    settings: Any,
    *,
    model: str,
    request_user_agent: str,
    status_callback: Callable[[dict[str, Any]], None] | None = None,
    timeout_seconds: float = LLAMACPP_START_TIMEOUT_SECONDS,
) -> str:
    try:
        running = await _find_running_server(
            settings,
            model=model,
            request_user_agent=request_user_agent,
            status_callback=status_callback,
        )
    except LlamaCppModelMismatchError:
        configured = normalize_llamacpp_base_url(str(getattr(settings, "llamacpp_base_url", "") or "http://localhost:8098"))
        if not stop_local_llamacpp_servers(configured)[0]:
            raise
        running = None
    if running:
        return running

    auto_start = bool(getattr(settings, "llamacpp_auto_start", True))
    configured = normalize_llamacpp_base_url(str(getattr(settings, "llamacpp_base_url", "") or "http://localhost:8098"))
    if not auto_start:
        raise RuntimeError(f"llama.cpp is not reachable at {configured}, and auto-start is disabled.")
    if not is_local_llamacpp_url(configured):
        raise RuntimeError("llama.cpp auto-start is only supported for local hosts.")

    async with _START_LOCK:
        running = await _find_running_server(
            settings,
            model=model,
            request_user_agent=request_user_agent,
            status_callback=status_callback,
        )
        if running:
            return running

        command, env, log_path = _build_start_command(settings, base_url=configured, model=model)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_handle = log_path.open("w", encoding="utf-8", buffering=1)
        log_handle.write("# llama-server command\n")
        log_handle.write(shlex.join(command) + "\n\n")
        log_handle.flush()
        _emit(status_callback, "Starting llama.cpp server.", log_path=str(log_path))
        try:
            process = subprocess.Popen(  # noqa: S603
                command,
                stdout=log_handle,
                stderr=log_handle,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except Exception:
            log_handle.close()
            raise
        _PROCESSES[configured] = (process, log_handle)
        object.__setattr__(settings, "llamacpp_log_path", str(log_path))

        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
        last_error = ""
        while asyncio.get_running_loop().time() < deadline:
            if process.poll() is not None:
                log_handle.flush()
                tail = llamacpp_log_tail(log_path)
                raise RuntimeError(
                    f"llama.cpp exited early with code {process.returncode}. "
                    f"Log: {log_path}\n{tail}"
                )
            probe = await probe_llamacpp_server(configured, request_user_agent=request_user_agent)
            if probe.connected:
                if not llama_model_matches(model, probe.models):
                    served = ", ".join(probe.models) or "unknown model"
                    raise LlamaCppModelMismatchError(
                        f"llama.cpp started at {configured}, but it is serving {served} instead of {model or 'local'}."
                    )
                _emit(status_callback, "llama.cpp model is ready.", log_path=str(log_path))
                return configured
            last_error = probe.error or ""
            _emit(status_callback, "Waiting for llama.cpp /health.", log_path=str(log_path))
            await asyncio.sleep(1.0)

        tail = llamacpp_log_tail(log_path)
        raise RuntimeError(
            f"llama.cpp did not become ready within {timeout_seconds:.0f}s. "
            f"Last error: {last_error}. Log: {log_path}\n{tail}"
        )


def is_llamacpp_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return True
    text = str(exc).lower()
    return "all connection attempts failed" in text or "connection refused" in text or "could not connect" in text


def is_supervised_llamacpp_running(base_url: str | None = None) -> bool:
    keys = [normalize_llamacpp_base_url(base_url)] if base_url else list(_PROCESSES)
    running = False
    for key in keys:
        item = _PROCESSES.get(key)
        if item is None:
            continue
        process, log_handle = item
        if process.poll() is None:
            running = True
            continue
        with contextlib.suppress(Exception):
            log_handle.close()
        _PROCESSES.pop(key, None)
    return running


def stop_supervised_llamacpp(base_url: str | None = None) -> tuple[bool, str | None]:
    keys = [normalize_llamacpp_base_url(base_url)] if base_url else list(_PROCESSES)
    errors: list[str] = []
    stopped = False
    for key in keys:
        item = _PROCESSES.pop(key, None)
        if item is None:
            continue
        process, log_handle = item
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                stopped = True
        except Exception as exc:
            errors.append(f"{key}: {type(exc).__name__}: {exc}")
        finally:
            with contextlib.suppress(Exception):
                log_handle.close()
    return stopped, "; ".join(errors) if errors else None


def _llamacpp_pids_for_ports(ports: set[int]) -> set[int]:
    pids: set[int] = set()
    try:
        completed = subprocess.run(
            ["ss", "-ltnp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        completed = None
    if completed and completed.stdout:
        for line in completed.stdout.splitlines():
            if "llama-server" not in line:
                continue
            if not any(f":{port}" in line for port in ports):
                continue
            for match in re.finditer(r"pid=(\d+)", line):
                pids.add(int(match.group(1)))

    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,cmd="],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        completed = None
    if completed and completed.stdout:
        for line in completed.stdout.splitlines():
            if "llama-server" not in line:
                continue
            parts = line.strip().split(maxsplit=1)
            if len(parts) != 2 or not parts[0].isdigit():
                continue
            cmd = parts[1]
            tokens = shlex.split(cmd)
            for index, token in enumerate(tokens):
                port_value = ""
                if token == "--port" and index + 1 < len(tokens):
                    port_value = tokens[index + 1]
                elif token.startswith("--port="):
                    port_value = token.split("=", 1)[1]
                if port_value.isdigit() and int(port_value) in ports:
                    pids.add(int(parts[0]))
                    break
    return pids


def stop_local_llamacpp_servers(base_url: str | None = None) -> tuple[bool, str | None]:
    port = _port_from_base_url(base_url)
    ports = {port} if port else set(LOCAL_LLAMA_PORTS)
    stopped, supervised_error = stop_supervised_llamacpp(base_url)
    errors: list[str] = [supervised_error] if supervised_error else []
    pids = _llamacpp_pids_for_ports(ports)
    for pid in sorted(pids):
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except ProcessLookupError:
            continue
        except Exception as exc:
            errors.append(f"pid {pid}: {type(exc).__name__}: {exc}")
    for _ in range(40):
        remaining = {pid for pid in pids if _pid_alive(pid)}
        if not remaining:
            break
        import time

        time.sleep(0.25)
    for pid in sorted(pids):
        if not _pid_alive(pid):
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            stopped = True
        except ProcessLookupError:
            continue
        except Exception as exc:
            errors.append(f"pid {pid} kill: {type(exc).__name__}: {exc}")
    return stopped, "; ".join(error for error in errors if error) if errors else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True
