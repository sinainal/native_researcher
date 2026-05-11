"""Application settings routes."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

from app.schemas.settings import (
    AppAPIKeysPayload,
    OllamaModelInfo,
    OllamaSettingsPayload,
    OllamaStatusResponse,
)
from app.utils.rate_limit import AsyncRateLimiter
from app.llm.ollama import ollama_warmup

router = APIRouter(prefix="/app", tags=["app-settings"])


def _read_value(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_value(path: Path, value: str) -> None:
    cleaned = value.strip()
    if not cleaned:
        try:
            path.unlink()
        except OSError:
            return
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned + "\n", encoding="utf-8")


def _write_bool_value(path: Path, value: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("true" if value else "false") + "\n", encoding="utf-8")


def _read_bool_value(path: Path, default: bool) -> bool:
    raw = _read_value(path).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


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
    if payload.warmup and connected and next_payload.ollama_model:
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
