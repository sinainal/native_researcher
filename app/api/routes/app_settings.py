"""Application settings routes."""

from __future__ import annotations

from pathlib import Path

import httpx
from fastapi import APIRouter, Request

from app.schemas.settings import (
    AppAPIKeysPayload,
    OllamaModelInfo,
    OllamaSettingsPayload,
    OllamaStatusResponse,
)
from app.utils.rate_limit import AsyncRateLimiter

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
        assistant_api_key=_read_value(settings.assistant_api_key_path),
        ncbi_api_key=_read_value(settings.ncbi_api_key_path),
        unpaywall_email=_read_value(settings.unpaywall_email_path),
        openalex_api_key=_read_value(settings.openalex_api_key_path),
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
    return OllamaStatusResponse(
        ollama_base_url=payload.ollama_base_url,
        connected=connected,
        version=version,
        ollama_model=payload.ollama_model,
        models=models,
        error=error,
    )


@router.put("/ollama", response_model=OllamaStatusResponse)
async def update_ollama_settings(payload: OllamaSettingsPayload, request: Request) -> OllamaStatusResponse:
    settings = request.app.state.settings
    normalized_base_url = _normalize_ollama_base_url(
        payload.ollama_base_url,
        str(getattr(settings, "ollama_base_url", "http://localhost:11434")),
    )
    _write_value(settings.ollama_base_url_path, normalized_base_url)
    _write_value(settings.ollama_model_path, payload.ollama_model)
    next_payload = _current_ollama_payload(request)
    connected, version, models, error = await _probe_ollama(
        next_payload.ollama_base_url,
        request_user_agent=settings.request_user_agent,
    )
    request.app.state.app_event_log_service.log(
        "info",
        "ollama_settings_updated",
        "Ollama connection settings were updated.",
        context={
            "ollama_base_url": next_payload.ollama_base_url,
            "ollama_model": next_payload.ollama_model,
            "connected": connected,
            "model_count": len(models),
        },
    )
    return OllamaStatusResponse(
        ollama_base_url=next_payload.ollama_base_url,
        connected=connected,
        version=version,
        ollama_model=next_payload.ollama_model,
        models=models,
        error=error,
    )
