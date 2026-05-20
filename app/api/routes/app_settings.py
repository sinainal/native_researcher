"""Application settings routes."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

from app.schemas.settings import (
    AppAPIKeysPayload,
    LlamaCppModelInfo,
    LlamaCppSettingsPayload,
    LlamaCppStatusResponse,
    OllamaModelInfo,
    OllamaSettingsPayload,
    OllamaStatusResponse,
)
from app.utils.rate_limit import AsyncRateLimiter
from app.llm.ollama import ollama_warmup
from app.llm.llamacpp import llamacpp_chat
from app.llm.llamacpp_profiles import (
    LLAMACPP_SERVER_PROFILES,
    build_llamacpp_server_args,
    detect_llamacpp_profile,
    llama_cpp_profile_choices,
)
from app.services.local_llamacpp_supervisor import (
    ensure_llamacpp_ready,
    is_supervised_llamacpp_running,
    probe_llamacpp_server,
    stop_local_llamacpp_servers,
)
from app.services.llamacpp_model_discovery import (
    discover_llamacpp_model_files,
    merge_llamacpp_models,
    resolve_llamacpp_model_path,
)
from app.services.runtime_settings_store import (
    read_bool_value as _read_bool_value,
    read_value as _read_value,
    write_bool_value as _write_bool_value,
    write_value as _write_value,
)

router = APIRouter(prefix="/app", tags=["app-settings"])

def _normalize_search_resource(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"}:
        return normalized
    return default


def _normalize_pdf_downloader_mode(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"pdf_xml", "best", "pdf", "xml", "legacy", "article_downloader", "hybrid", "final_method", "perfect"}:
        if normalized in {"best", "legacy", "article_downloader", "hybrid", "final_method", "perfect"}:
            return "pdf_xml"
        return normalized
    return default


def _normalize_ollama_base_url(value: str | None, default: str) -> str:
    normalized = (value or "").strip() or default.strip()
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def _normalize_llamacpp_base_url(value: str | None, default: str = "http://localhost:8098") -> str:
    normalized = (value or "").strip() or default.strip()
    if "://" not in normalized:
        normalized = f"http://{normalized}"
    return normalized.rstrip("/")


def _normalize_ollama_thinking_level(value: str | None, default: str = "off") -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"off", "on"}:
        return normalized
    if normalized in {"low", "medium", "high", "max", "minimal", "true", "yes", "1"}:
        return "on"
    return default


def _ollama_host_for_env(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.netloc:
        return parsed.netloc
    if parsed.path:
        return parsed.path
    return "localhost:11434"


def _ollama_base_url_is_local(base_url: str) -> bool:
    parsed = urlparse(_normalize_ollama_base_url(base_url, "http://localhost:11434"))
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _llamacpp_base_url_is_local(base_url: str) -> bool:
    parsed = urlparse(_normalize_llamacpp_base_url(base_url))
    host = (parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _ollama_process_is_running(request: Request) -> bool:
    process = getattr(request.app.state, "ollama_process", None)
    if process is None:
        return False
    poll = getattr(process, "poll", None)
    if not callable(poll):
        return False
    return poll() is None


def _ensure_ollama_warmup_state(request: Request) -> None:
    state = request.app.state
    if not hasattr(state, "ollama_warmup_pending"):
        state.ollama_warmup_pending = False
    if not hasattr(state, "ollama_warmup_model"):
        state.ollama_warmup_model = ""
    if not hasattr(state, "ollama_warmup_error"):
        state.ollama_warmup_error = None
    if not hasattr(state, "ollama_warmup_token"):
        state.ollama_warmup_token = 0
    if not hasattr(state, "ollama_warmup_task"):
        state.ollama_warmup_task = None


def _ollama_warmup_snapshot(request: Request) -> tuple[bool, str, str | None]:
    _ensure_ollama_warmup_state(request)
    state = request.app.state
    return (
        bool(getattr(state, "ollama_warmup_pending", False)),
        str(getattr(state, "ollama_warmup_model", "") or ""),
        getattr(state, "ollama_warmup_error", None),
    )


def _spawn_ollama_process(request: Request, base_url: str) -> tuple[bool, str | None]:
    if not _ollama_base_url_is_local(base_url):
        return False, "Ollama auto-start is only supported for local hosts."
    executable = shutil.which("ollama")
    if not executable:
        return False, "Ollama executable was not found on PATH."
    if _ollama_process_is_running(request):
        return True, None
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _ollama_host_for_env(base_url)
    try:
        process = subprocess.Popen(  # noqa: S603,S607
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    request.app.state.ollama_process = process
    return True, None


def _stop_ollama_model(base_url: str, model: str) -> tuple[bool, str | None]:
    normalized_model = str(model or "").strip()
    if not normalized_model:
        return True, None
    if not _ollama_base_url_is_local(base_url):
        return False, "Ollama model stop is only supported for local hosts."
    executable = shutil.which("ollama")
    if not executable:
        return False, "Ollama executable was not found on PATH."
    env = os.environ.copy()
    env["OLLAMA_HOST"] = _ollama_host_for_env(base_url)
    try:
        completed = subprocess.run(  # noqa: S603,S607
            [executable, "stop", normalized_model],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            timeout=30,
            check=False,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if completed.returncode not in {0, 1}:
        return False, f"ollama stop exited with code {completed.returncode}."
    return True, None


def _ollama_model_available(model: str, models: list[OllamaModelInfo]) -> bool:
    normalized = str(model or "").strip()
    if not normalized:
        return True
    names = {str(item.name or "").strip() for item in models}
    return normalized in names


def _ollama_missing_model_error(model: str, models: list[OllamaModelInfo]) -> str:
    names = ", ".join(item.name for item in models[:8]) or "none"
    return f"Ollama model '{model}' is not installed or not loaded in /api/tags. Available models: {names}."


async def _list_ollama_running_models(base_url: str, *, request_user_agent: str) -> list[str]:
    if not _ollama_base_url_is_local(base_url):
        return []
    try:
        async with httpx.AsyncClient(
            base_url=_normalize_ollama_base_url(base_url, "http://localhost:11434"),
            timeout=httpx.Timeout(4.0),
            headers={"User-Agent": request_user_agent},
            follow_redirects=True,
        ) as client:
            response = await client.get("/api/ps")
            response.raise_for_status()
            payload = response.json() or {}
            names = []
            for item in payload.get("models") or []:
                if isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip():
                    names.append(str(item.get("name") or item.get("model")).strip())
            return names
    except Exception:
        return []


async def _stop_ollama_running_models(base_url: str, *, request_user_agent: str, except_model: str = "") -> None:
    running = await _list_ollama_running_models(base_url, request_user_agent=request_user_agent)
    for model in running:
        if except_model and model == except_model:
            continue
        await asyncio.to_thread(_stop_ollama_model, base_url, model)


async def _finalize_ollama_warmup(
    request: Request,
    *,
    token: int,
    base_url: str,
    model: str,
    request_user_agent: str,
) -> None:
    error: str | None = None
    try:
        await ollama_warmup(
            base_url=base_url,
            model=model,
            request_user_agent=request_user_agent,
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    _ensure_ollama_warmup_state(request)
    state = request.app.state
    if getattr(state, "ollama_warmup_token", 0) != token:
        return
    state.ollama_warmup_pending = False
    state.ollama_warmup_model = model
    state.ollama_warmup_error = error


def _schedule_ollama_warmup(
    request: Request,
    *,
    base_url: str,
    model: str,
    request_user_agent: str,
) -> None:
    _ensure_ollama_warmup_state(request)
    state = request.app.state
    state.ollama_warmup_token = int(getattr(state, "ollama_warmup_token", 0) or 0) + 1
    token = state.ollama_warmup_token
    state.ollama_warmup_pending = True
    state.ollama_warmup_model = model
    state.ollama_warmup_error = None

    task = asyncio.create_task(
        _finalize_ollama_warmup(
            request,
            token=token,
            base_url=base_url,
            model=model,
            request_user_agent=request_user_agent,
        )
    )
    state.ollama_warmup_task = task

    def _swallow_task_exception(done_task: asyncio.Task[None]) -> None:
        try:
            done_task.exception()
        except asyncio.CancelledError:
            return
        except Exception:
            return

    task.add_done_callback(_swallow_task_exception)


async def _probe_ollama_with_start(
    request: Request,
    base_url: str,
    *,
    request_user_agent: str,
) -> tuple[bool, str | None, list[OllamaModelInfo], str | None]:
    connected, version, models, error = await _probe_ollama(
        base_url,
        request_user_agent=request_user_agent,
    )
    if connected:
        return connected, version, models, error

    lock = getattr(request.app.state, "ollama_start_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        request.app.state.ollama_start_lock = lock

    async with lock:
        connected, version, models, error = await _probe_ollama(
            base_url,
            request_user_agent=request_user_agent,
        )
        if connected:
            return connected, version, models, error

        started, start_error = _spawn_ollama_process(request, base_url)
        if not started:
            return False, None, [], start_error or error

        deadline = asyncio.get_running_loop().time() + 20.0
        last_error = error or start_error
        while True:
            connected, version, models, error = await _probe_ollama(
                base_url,
                request_user_agent=request_user_agent,
            )
            if connected:
                return connected, version, models, error
            if error:
                last_error = error
            if asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(0.5)
        return False, None, [], last_error or "Ollama could not be started."


def _apply_runtime_settings(request: Request, payload: AppAPIKeysPayload) -> None:
    settings = request.app.state.settings
    pubmed_rps = 10.0 if payload.ncbi_api_key.strip() else 3.0
    object.__setattr__(settings, "assistant_api_key", payload.assistant_api_key.strip() or None)
    object.__setattr__(settings, "ncbi_api_key", payload.ncbi_api_key.strip() or None)
    object.__setattr__(settings, "unpaywall_email", payload.unpaywall_email.strip() or None)
    object.__setattr__(settings, "openalex_api_key", payload.openalex_api_key.strip() or None)
    object.__setattr__(settings, "core_api_key", payload.core_api_key.strip() or None)
    object.__setattr__(settings, "pubmed_oa_only", payload.pubmed_oa_only)
    object.__setattr__(settings, "pdf_unpaywall_fallback_enabled", payload.pdf_unpaywall_fallback_enabled)
    object.__setattr__(settings, "pdf_core_fallback_enabled", payload.pdf_core_fallback_enabled)
    object.__setattr__(settings, "pdf_arxiv_fallback_enabled", payload.pdf_arxiv_fallback_enabled)
    object.__setattr__(
        settings,
        "ai_primary_search_resource",
        _normalize_search_resource(payload.ai_primary_search_resource, "pubmed"),
    )
    object.__setattr__(
        settings,
        "pdf_downloader_mode",
        _normalize_pdf_downloader_mode(payload.pdf_downloader_mode, "pdf_xml"),
    )
    object.__setattr__(settings, "pubmed_requests_per_second", pubmed_rps)

    pubmed_service = getattr(request.app.state, "pubmed_service", None)
    client = getattr(pubmed_service, "client", None)
    if client is not None:
        client.rate_limiter = AsyncRateLimiter(pubmed_rps)


def _current_payload(request: Request) -> AppAPIKeysPayload:
    settings = request.app.state.settings
    return AppAPIKeysPayload(
        assistant_api_key=_read_value(settings.assistant_api_key_path)
        or str(getattr(settings, "assistant_api_key", "") or ""),
        ncbi_api_key=_read_value(settings.ncbi_api_key_path) or str(getattr(settings, "ncbi_api_key", "") or ""),
        unpaywall_email=_read_value(settings.unpaywall_email_path)
        or str(getattr(settings, "unpaywall_email", "") or ""),
        openalex_api_key=_read_value(settings.openalex_api_key_path)
        or str(getattr(settings, "openalex_api_key", "") or ""),
        core_api_key=_read_value(settings.core_api_key_path) or str(getattr(settings, "core_api_key", "") or ""),
        pubmed_oa_only=_read_bool_value(
            settings.pubmed_oa_only_path,
            bool(getattr(settings, "pubmed_oa_only", True)),
        ),
        pdf_unpaywall_fallback_enabled=_read_bool_value(
            settings.pdf_unpaywall_fallback_enabled_path,
            bool(getattr(settings, "pdf_unpaywall_fallback_enabled", True)),
        ),
        pdf_core_fallback_enabled=_read_bool_value(
            settings.pdf_core_fallback_enabled_path,
            bool(getattr(settings, "pdf_core_fallback_enabled", False)),
        ),
        pdf_arxiv_fallback_enabled=_read_bool_value(
            settings.pdf_arxiv_fallback_enabled_path,
            bool(getattr(settings, "pdf_arxiv_fallback_enabled", False)),
        ),
        ai_primary_search_resource=_normalize_search_resource(
            _read_value(settings.ai_primary_search_resource_path),
            _normalize_search_resource(
                getattr(settings, "ai_primary_search_resource", "pubmed"),
                "pubmed",
            ),
        ),
        pdf_downloader_mode=_normalize_pdf_downloader_mode(
            _read_value(settings.pdf_downloader_mode_path),
            _normalize_pdf_downloader_mode(
                getattr(settings, "pdf_downloader_mode", "pdf_xml"),
                "pdf_xml",
            ),
        ),
    )


def _current_ollama_payload(request: Request) -> OllamaSettingsPayload:
    settings = request.app.state.settings
    return OllamaSettingsPayload(
        ollama_base_url=_normalize_ollama_base_url(
            _read_value(settings.ollama_base_url_path),
            str(getattr(settings, "ollama_base_url", "http://localhost:11434")),
        ),
        ollama_model=_read_value(settings.ollama_model_path) or str(getattr(settings, "ollama_model", "") or ""),
        ollama_thinking_level=_normalize_ollama_thinking_level(
            _read_value(settings.ollama_thinking_level_path),
            _normalize_ollama_thinking_level(getattr(settings, "ollama_thinking_level", "off"), "off"),
        ),
    )


def _current_llamacpp_payload(request: Request) -> LlamaCppSettingsPayload:
    settings = request.app.state.settings
    server_args = (
        _read_value(settings.llamacpp_server_args_path)
        or str(getattr(settings, "llamacpp_server_args", "") or "")
    )
    return LlamaCppSettingsPayload(
        llamacpp_base_url=_normalize_llamacpp_base_url(
            _read_value(settings.llamacpp_base_url_path),
            str(getattr(settings, "llamacpp_base_url", "http://localhost:8098")),
        ),
        llamacpp_model=_read_value(settings.llamacpp_model_name_path)
        or str(getattr(settings, "llamacpp_model", "") or "")
        or "local",
        llamacpp_executable=_read_value(settings.llamacpp_executable_path)
        or str(getattr(settings, "llamacpp_executable", "") or ""),
        llamacpp_model_path=_read_value(settings.llamacpp_model_path_path)
        or str(getattr(settings, "llamacpp_model_path", "") or ""),
        llamacpp_library_path=_read_value(settings.llamacpp_library_path_path)
        or str(getattr(settings, "llamacpp_library_path", "") or ""),
        llamacpp_server_args=server_args,
        llamacpp_profile=detect_llamacpp_profile(server_args),
        llamacpp_auto_start=_read_bool_value(
            settings.llamacpp_auto_start_path,
            bool(getattr(settings, "llamacpp_auto_start", True)),
        ),
    )


def _apply_llamacpp_runtime_settings(request: Request, payload: LlamaCppSettingsPayload) -> None:
    settings = request.app.state.settings
    object.__setattr__(settings, "llamacpp_base_url", payload.llamacpp_base_url)
    object.__setattr__(settings, "llamacpp_model", payload.llamacpp_model)
    object.__setattr__(settings, "llamacpp_executable", payload.llamacpp_executable)
    object.__setattr__(settings, "llamacpp_model_path", payload.llamacpp_model_path)
    object.__setattr__(settings, "llamacpp_library_path", payload.llamacpp_library_path)
    object.__setattr__(settings, "llamacpp_server_args", payload.llamacpp_server_args)
    object.__setattr__(settings, "llamacpp_auto_start", payload.llamacpp_auto_start)


def _llamacpp_process_is_running(request: Request) -> bool:
    process = getattr(request.app.state, "llamacpp_process", None)
    poll = getattr(process, "poll", None)
    return bool(process is not None and callable(poll) and poll() is None)


def _stop_llamacpp_process(request: Request) -> None:
    process = getattr(request.app.state, "llamacpp_process", None)
    poll = getattr(process, "poll", None)
    if process is None or not callable(poll) or poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
    except Exception:
        return


def _spawn_llamacpp_process(request: Request, payload: LlamaCppSettingsPayload) -> tuple[bool, str | None]:
    if not _llamacpp_base_url_is_local(payload.llamacpp_base_url):
        return False, "llama.cpp auto-start is only supported for local hosts."
    executable = payload.llamacpp_executable.strip()
    model_path = payload.llamacpp_model_path.strip()
    if not executable:
        return False, "llama.cpp executable path is not configured."
    if not model_path:
        return False, "llama.cpp model path is not configured."
    if not Path(executable).is_file():
        return False, "llama.cpp executable was not found."
    if not Path(model_path).is_file():
        return False, "llama.cpp model file was not found."
    if _llamacpp_process_is_running(request):
        return True, None
    parsed = urlparse(payload.llamacpp_base_url)
    host = parsed.hostname or "127.0.0.1"
    port = str(parsed.port or 8098)
    args = [
        executable,
        "-m",
        model_path,
        "--host",
        host,
        "--port",
        port,
    ]
    if payload.llamacpp_server_args.strip():
        args.extend(shlex.split(payload.llamacpp_server_args))
    env = os.environ.copy()
    if payload.llamacpp_library_path.strip():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = payload.llamacpp_library_path.strip() + ((f":{existing}") if existing else "")
    try:
        process = subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    request.app.state.llamacpp_process = process
    return True, None


async def _probe_llamacpp(
    base_url: str,
    *,
    request_user_agent: str,
) -> tuple[bool, list[LlamaCppModelInfo], str | None]:
    result = await probe_llamacpp_server(base_url, request_user_agent=request_user_agent)
    return (
        result.connected,
        [LlamaCppModelInfo(id=model) for model in result.models],
        result.error,
    )


async def _llamacpp_warmup(
    *,
    base_url: str,
    model: str,
    request_user_agent: str,
) -> str | None:
    try:
        await llamacpp_chat(
            base_url=base_url,
            model=model or "local",
            messages=[{"role": "user", "content": "Warm up the model and reply with a single word."}],
            timeout_seconds=600.0,
            request_user_agent=request_user_agent,
        )
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


async def _probe_ollama(base_url: str, *, request_user_agent: str) -> tuple[bool, str | None, list[OllamaModelInfo], str | None]:
    normalized_base_url = _normalize_ollama_base_url(base_url, "http://localhost:11434")
    timeout = httpx.Timeout(4.0)
    headers = {"User-Agent": request_user_agent}
    try:
        async with httpx.AsyncClient(
            base_url=normalized_base_url,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            version: str | None = None
            try:
                version_response = await client.get("/api/version")
                version_response.raise_for_status()
                version_payload = version_response.json() or {}
                version = str(version_payload.get("version") or version_payload.get("ollama_version") or "").strip() or None
            except Exception as exc:
                return False, None, [], f"{type(exc).__name__}: {exc}"

            models: list[OllamaModelInfo] = []
            running_models: set[str] = set()
            try:
                ps_response = await client.get("/api/ps")
                ps_response.raise_for_status()
                ps_payload = ps_response.json() or {}
                for item in ps_payload.get("models") or []:
                    if isinstance(item, dict):
                        running_name = str(item.get("name") or item.get("model") or "").strip()
                        if running_name:
                            running_models.add(running_name)
            except Exception:
                running_models = set()
            tags_error: str | None = None
            try:
                tags_response = await client.get("/api/tags")
                tags_response.raise_for_status()
                tags_payload = tags_response.json() or {}
                raw_models = tags_payload.get("models") or []
                for item in raw_models:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or item.get("model") or "").strip()
                    if not name:
                        continue
                    size_value = item.get("size")
                    if isinstance(size_value, (int, float)):
                        size = int(size_value)
                    else:
                        size = None
                    models.append(
                        OllamaModelInfo(
                            name=name,
                            size=size,
                            modified_at=str(item.get("modified_at") or item.get("modifiedAt") or "").strip() or None,
                            digest=str(item.get("digest") or "").strip() or None,
                            running=name in running_models,
                        )
                    )
            except Exception as exc:
                tags_error = f"{type(exc).__name__}: {exc}"

            models.sort(key=lambda item: item.name.lower())
            return True, version, models, tags_error
    except Exception as exc:
        return False, None, [], f"{type(exc).__name__}: {exc}"


@router.get("/api-keys", response_model=AppAPIKeysPayload)
async def get_api_keys(request: Request) -> AppAPIKeysPayload:
    payload = _current_payload(request)
    _apply_runtime_settings(request, payload)
    return payload


@router.put("/api-keys", response_model=AppAPIKeysPayload)
async def update_api_keys(payload: AppAPIKeysPayload, request: Request) -> AppAPIKeysPayload:
    settings = request.app.state.settings
    _write_value(settings.assistant_api_key_path, payload.assistant_api_key)
    _write_value(settings.ncbi_api_key_path, payload.ncbi_api_key)
    _write_value(settings.unpaywall_email_path, payload.unpaywall_email)
    _write_value(settings.openalex_api_key_path, payload.openalex_api_key)
    _write_value(settings.core_api_key_path, payload.core_api_key)
    _write_bool_value(settings.pubmed_oa_only_path, payload.pubmed_oa_only)
    _write_bool_value(settings.pdf_unpaywall_fallback_enabled_path, payload.pdf_unpaywall_fallback_enabled)
    _write_bool_value(settings.pdf_core_fallback_enabled_path, payload.pdf_core_fallback_enabled)
    _write_bool_value(settings.pdf_arxiv_fallback_enabled_path, payload.pdf_arxiv_fallback_enabled)
    _write_value(
        settings.ai_primary_search_resource_path,
        _normalize_search_resource(payload.ai_primary_search_resource, "pubmed"),
    )
    _write_value(
        settings.pdf_downloader_mode_path,
        _normalize_pdf_downloader_mode(payload.pdf_downloader_mode, "pdf_xml"),
    )
    next_payload = _current_payload(request)
    _apply_runtime_settings(request, next_payload)
    request.app.state.app_event_log_service.log(
        "info",
        "api_keys_updated",
        "Application API keys were updated.",
        context={
            "assistant_api_key": bool(next_payload.assistant_api_key),
            "ncbi_api_key": bool(next_payload.ncbi_api_key),
            "unpaywall_email": bool(next_payload.unpaywall_email),
            "openalex_api_key": bool(next_payload.openalex_api_key),
            "core_api_key": bool(next_payload.core_api_key),
            "pubmed_oa_only": next_payload.pubmed_oa_only,
            "ai_primary_search_resource": next_payload.ai_primary_search_resource,
            "pdf_downloader_mode": next_payload.pdf_downloader_mode,
            "pdf_unpaywall_fallback_enabled": next_payload.pdf_unpaywall_fallback_enabled,
            "pdf_core_fallback_enabled": next_payload.pdf_core_fallback_enabled,
            "pdf_arxiv_fallback_enabled": next_payload.pdf_arxiv_fallback_enabled,
        },
    )
    return next_payload


@router.get("/ollama", response_model=OllamaStatusResponse)
async def get_ollama_settings(request: Request) -> OllamaStatusResponse:
    settings = request.app.state.settings
    payload = _current_ollama_payload(request)
    connected, version, models, error = await _probe_ollama(
        payload.ollama_base_url,
        request_user_agent=settings.request_user_agent,
    )
    if connected and payload.ollama_model and not _ollama_model_available(payload.ollama_model, models):
        error = _ollama_missing_model_error(payload.ollama_model, models)
    warming_up, warming_model, warmup_error = _ollama_warmup_snapshot(request)
    return OllamaStatusResponse(
        ollama_base_url=payload.ollama_base_url,
        connected=connected,
        version=version,
        ollama_model=payload.ollama_model,
        ollama_thinking_level=payload.ollama_thinking_level,
        models=models,
        error=error,
        warmup_error=warmup_error,
        warming_up=warming_up,
        warming_model=warming_model or None,
    )


@router.put("/ollama", response_model=OllamaStatusResponse)
async def update_ollama_settings(payload: OllamaSettingsPayload, request: Request) -> OllamaStatusResponse:
    settings = request.app.state.settings
    current_payload = _current_ollama_payload(request)
    normalized_base_url = _normalize_ollama_base_url(
        payload.ollama_base_url,
        str(getattr(settings, "ollama_base_url", "http://localhost:11434")),
    )
    _write_value(settings.ollama_base_url_path, normalized_base_url)
    _write_value(settings.ollama_model_path, payload.ollama_model)
    _write_value(
        settings.ollama_thinking_level_path,
        _normalize_ollama_thinking_level(payload.ollama_thinking_level, "off"),
    )
    next_payload = _current_ollama_payload(request)
    stop_error: str | None = None
    if (
        payload.warmup
        and next_payload.ollama_model
        and current_payload.ollama_model
        and current_payload.ollama_model != next_payload.ollama_model
    ):
        _, stop_error = await asyncio.to_thread(
            _stop_ollama_model,
            next_payload.ollama_base_url,
            current_payload.ollama_model,
        )
    if payload.warmup:
        connected, version, models, error = await _probe_ollama_with_start(
            request,
            next_payload.ollama_base_url,
            request_user_agent=settings.request_user_agent,
        )
    else:
        connected, version, models, error = await _probe_ollama(
            next_payload.ollama_base_url,
            request_user_agent=settings.request_user_agent,
        )
    if connected and next_payload.ollama_model and not _ollama_model_available(next_payload.ollama_model, models):
        error = _ollama_missing_model_error(next_payload.ollama_model, models)
        warmup_error = error
        warming_up = False
        warming_model = ""
    else:
        warmup_error = None
        if payload.warmup and connected and next_payload.ollama_model:
            stop_local_llamacpp_servers()
            _stop_llamacpp_process(request)
            await _stop_ollama_running_models(
                next_payload.ollama_base_url,
                request_user_agent=settings.request_user_agent,
                except_model=next_payload.ollama_model,
            )
            _schedule_ollama_warmup(
                request,
                base_url=next_payload.ollama_base_url,
                model=next_payload.ollama_model,
                request_user_agent=settings.request_user_agent,
            )
        warming_up, warming_model, warmup_error = _ollama_warmup_snapshot(request)
    if stop_error and not warmup_error:
        warmup_error = stop_error
    request.app.state.app_event_log_service.log(
        "info",
        "ollama_settings_updated",
        "Ollama connection settings were updated.",
        context={
            "ollama_base_url": next_payload.ollama_base_url,
            "ollama_model": next_payload.ollama_model,
            "connected": connected,
            "model_count": len(models),
            "stopped_previous_model": bool(current_payload.ollama_model and current_payload.ollama_model != next_payload.ollama_model and not stop_error),
        },
    )
    return OllamaStatusResponse(
        ollama_base_url=next_payload.ollama_base_url,
        connected=connected,
        version=version,
        ollama_model=next_payload.ollama_model,
        ollama_thinking_level=next_payload.ollama_thinking_level,
        models=models,
        error=error,
        warmup_error=warmup_error,
        warming_up=warming_up,
        warming_model=warming_model or None,
    )


@router.get("/llamacpp", response_model=LlamaCppStatusResponse)
async def get_llamacpp_settings(request: Request) -> LlamaCppStatusResponse:
    settings = request.app.state.settings
    payload = _current_llamacpp_payload(request)
    _apply_llamacpp_runtime_settings(request, payload)
    connected, models, error = await _probe_llamacpp(
        payload.llamacpp_base_url,
        request_user_agent=settings.request_user_agent,
    )
    models = merge_llamacpp_models(discover_llamacpp_model_files(settings), models, payload)
    return LlamaCppStatusResponse(
        llamacpp_base_url=payload.llamacpp_base_url,
        llamacpp_model=payload.llamacpp_model,
        llamacpp_executable=payload.llamacpp_executable,
        llamacpp_model_path=payload.llamacpp_model_path,
        llamacpp_library_path=payload.llamacpp_library_path,
        llamacpp_server_args=payload.llamacpp_server_args,
        llamacpp_profile=payload.llamacpp_profile,
        llamacpp_auto_start=payload.llamacpp_auto_start,
        llamacpp_log_path=str(getattr(settings, "llamacpp_log_path", "") or ""),
        profiles=llama_cpp_profile_choices(),
        connected=connected,
        models=models,
        error=error,
        started=is_supervised_llamacpp_running(payload.llamacpp_base_url) or _llamacpp_process_is_running(request),
    )


@router.put("/llamacpp", response_model=LlamaCppStatusResponse)
async def update_llamacpp_settings(payload: LlamaCppSettingsPayload, request: Request) -> LlamaCppStatusResponse:
    settings = request.app.state.settings
    requested_profile = payload.llamacpp_profile.strip()
    server_args = payload.llamacpp_server_args.strip()
    if requested_profile and requested_profile != "custom" and requested_profile in LLAMACPP_SERVER_PROFILES:
        server_args = build_llamacpp_server_args(
            requested_profile,
            alias=payload.llamacpp_model.strip() or "local",
        )
    normalized_payload = LlamaCppSettingsPayload(
        llamacpp_base_url=_normalize_llamacpp_base_url(
            payload.llamacpp_base_url,
            str(getattr(settings, "llamacpp_base_url", "http://localhost:8098")),
        ),
        llamacpp_model=payload.llamacpp_model.strip() or "local",
        llamacpp_executable=payload.llamacpp_executable.strip(),
        llamacpp_model_path=payload.llamacpp_model_path.strip()
        or resolve_llamacpp_model_path(payload.llamacpp_model.strip(), settings),
        llamacpp_library_path=payload.llamacpp_library_path.strip(),
        llamacpp_server_args=server_args,
        llamacpp_profile=detect_llamacpp_profile(server_args),
        llamacpp_auto_start=payload.llamacpp_auto_start,
        start=payload.start,
        restart=payload.restart,
        warmup=payload.warmup,
    )
    _write_value(settings.llamacpp_base_url_path, normalized_payload.llamacpp_base_url)
    _write_value(settings.llamacpp_model_name_path, normalized_payload.llamacpp_model)
    _write_value(settings.llamacpp_executable_path, normalized_payload.llamacpp_executable)
    _write_value(settings.llamacpp_model_path_path, normalized_payload.llamacpp_model_path)
    _write_value(settings.llamacpp_library_path_path, normalized_payload.llamacpp_library_path)
    _write_value(settings.llamacpp_server_args_path, normalized_payload.llamacpp_server_args)
    _write_bool_value(settings.llamacpp_auto_start_path, normalized_payload.llamacpp_auto_start)
    _apply_llamacpp_runtime_settings(request, normalized_payload)

    start_error: str | None = None
    started = False
    if normalized_payload.start:
        ollama_model = str(getattr(settings, "ollama_model", "") or _read_value(settings.ollama_model_path)).strip()
        ollama_base_url = str(getattr(settings, "ollama_base_url", "") or _read_value(settings.ollama_base_url_path) or "http://localhost:11434")
        await _stop_ollama_running_models(ollama_base_url, request_user_agent=settings.request_user_agent)
        if ollama_model:
            await asyncio.to_thread(_stop_ollama_model, ollama_base_url, ollama_model)
        if normalized_payload.restart:
            stop_local_llamacpp_servers(normalized_payload.llamacpp_base_url)
        try:
            await ensure_llamacpp_ready(
                settings,
                model=normalized_payload.llamacpp_model,
                request_user_agent=settings.request_user_agent,
                timeout_seconds=120.0,
            )
            started = True
            normalized_payload.llamacpp_base_url = str(getattr(settings, "llamacpp_base_url", normalized_payload.llamacpp_base_url))
            _write_value(settings.llamacpp_base_url_path, normalized_payload.llamacpp_base_url)
            _write_value(settings.llamacpp_log_path_path, str(getattr(settings, "llamacpp_log_path", "") or ""))
        except Exception as exc:
            start_error = f"{type(exc).__name__}: {exc}"

    connected, models, error = await _probe_llamacpp(
        normalized_payload.llamacpp_base_url,
        request_user_agent=settings.request_user_agent,
    )
    models = merge_llamacpp_models(discover_llamacpp_model_files(settings), models, normalized_payload)
    warmup_error = None
    if normalized_payload.warmup and connected:
        warmup_error = await _llamacpp_warmup(
            base_url=normalized_payload.llamacpp_base_url,
            model=normalized_payload.llamacpp_model,
            request_user_agent=settings.request_user_agent,
        )
    if start_error and not error:
        error = start_error
    request.app.state.app_event_log_service.log(
        "info",
        "llamacpp_settings_updated",
        "llama.cpp connection settings were updated.",
        context={
            "llamacpp_base_url": normalized_payload.llamacpp_base_url,
            "llamacpp_model": normalized_payload.llamacpp_model,
            "connected": connected,
            "started": started,
            "model_path_configured": bool(normalized_payload.llamacpp_model_path),
        },
    )
    return LlamaCppStatusResponse(
        llamacpp_base_url=normalized_payload.llamacpp_base_url,
        llamacpp_model=normalized_payload.llamacpp_model,
        llamacpp_executable=normalized_payload.llamacpp_executable,
        llamacpp_model_path=normalized_payload.llamacpp_model_path,
        llamacpp_library_path=normalized_payload.llamacpp_library_path,
        llamacpp_server_args=normalized_payload.llamacpp_server_args,
        llamacpp_profile=normalized_payload.llamacpp_profile,
        llamacpp_auto_start=normalized_payload.llamacpp_auto_start,
        llamacpp_log_path=str(getattr(settings, "llamacpp_log_path", "") or ""),
        profiles=llama_cpp_profile_choices(),
        connected=connected,
        models=models,
        error=error,
        warmup_error=warmup_error,
        started=started or is_supervised_llamacpp_running(normalized_payload.llamacpp_base_url) or _llamacpp_process_is_running(request),
    )
