"""Application settings routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request

from app.schemas.settings import AppAPIKeysPayload
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


def _apply_runtime_settings(request: Request, payload: AppAPIKeysPayload) -> None:
    settings = request.app.state.settings
    pubmed_rps = 10.0 if payload.ncbi_api_key.strip() else 3.0
    object.__setattr__(settings, "assistant_api_key", payload.assistant_api_key.strip() or None)
    object.__setattr__(settings, "ncbi_api_key", payload.ncbi_api_key.strip() or None)
    object.__setattr__(settings, "unpaywall_email", payload.unpaywall_email.strip() or None)
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
    )


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
        },
    )
    return next_payload
