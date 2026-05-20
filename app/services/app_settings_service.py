"""Application-level runtime settings orchestration."""

from __future__ import annotations

from typing import Any

from app.schemas.settings import AppAPIKeysPayload
from app.services.runtime_settings_store import read_bool_value, read_value, write_bool_value, write_value
from app.utils.rate_limit import AsyncRateLimiter


def normalize_search_resource(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"}:
        return normalized
    return default


def normalize_pdf_downloader_mode(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"pdf_xml", "best", "pdf", "xml", "legacy", "article_downloader", "hybrid", "final_method", "perfect"}:
        if normalized in {"best", "legacy", "article_downloader", "hybrid", "final_method", "perfect"}:
            return "pdf_xml"
        return normalized
    return default


def current_app_settings_payload(settings: Any) -> AppAPIKeysPayload:
    return AppAPIKeysPayload(
        assistant_api_key=read_value(settings.assistant_api_key_path)
        or str(getattr(settings, "assistant_api_key", "") or ""),
        ncbi_api_key=read_value(settings.ncbi_api_key_path) or str(getattr(settings, "ncbi_api_key", "") or ""),
        unpaywall_email=read_value(settings.unpaywall_email_path)
        or str(getattr(settings, "unpaywall_email", "") or ""),
        openalex_api_key=read_value(settings.openalex_api_key_path)
        or str(getattr(settings, "openalex_api_key", "") or ""),
        core_api_key=read_value(settings.core_api_key_path) or str(getattr(settings, "core_api_key", "") or ""),
        pubmed_oa_only=read_bool_value(
            settings.pubmed_oa_only_path,
            bool(getattr(settings, "pubmed_oa_only", True)),
        ),
        pdf_unpaywall_fallback_enabled=read_bool_value(
            settings.pdf_unpaywall_fallback_enabled_path,
            bool(getattr(settings, "pdf_unpaywall_fallback_enabled", True)),
        ),
        pdf_core_fallback_enabled=read_bool_value(
            settings.pdf_core_fallback_enabled_path,
            bool(getattr(settings, "pdf_core_fallback_enabled", False)),
        ),
        pdf_arxiv_fallback_enabled=read_bool_value(
            settings.pdf_arxiv_fallback_enabled_path,
            bool(getattr(settings, "pdf_arxiv_fallback_enabled", False)),
        ),
        ai_primary_search_resource=normalize_search_resource(
            read_value(settings.ai_primary_search_resource_path),
            normalize_search_resource(
                getattr(settings, "ai_primary_search_resource", "pubmed"),
                "pubmed",
            ),
        ),
        pdf_downloader_mode=normalize_pdf_downloader_mode(
            read_value(settings.pdf_downloader_mode_path),
            normalize_pdf_downloader_mode(
                getattr(settings, "pdf_downloader_mode", "pdf_xml"),
                "pdf_xml",
            ),
        ),
    )


def write_app_settings_payload(settings: Any, payload: AppAPIKeysPayload) -> None:
    write_value(settings.assistant_api_key_path, payload.assistant_api_key)
    write_value(settings.ncbi_api_key_path, payload.ncbi_api_key)
    write_value(settings.unpaywall_email_path, payload.unpaywall_email)
    write_value(settings.openalex_api_key_path, payload.openalex_api_key)
    write_value(settings.core_api_key_path, payload.core_api_key)
    write_bool_value(settings.pubmed_oa_only_path, payload.pubmed_oa_only)
    write_bool_value(settings.pdf_unpaywall_fallback_enabled_path, payload.pdf_unpaywall_fallback_enabled)
    write_bool_value(settings.pdf_core_fallback_enabled_path, payload.pdf_core_fallback_enabled)
    write_bool_value(settings.pdf_arxiv_fallback_enabled_path, payload.pdf_arxiv_fallback_enabled)
    write_value(
        settings.ai_primary_search_resource_path,
        normalize_search_resource(payload.ai_primary_search_resource, "pubmed"),
    )
    write_value(
        settings.pdf_downloader_mode_path,
        normalize_pdf_downloader_mode(payload.pdf_downloader_mode, "pdf_xml"),
    )


def apply_app_runtime_settings(app_state: Any, payload: AppAPIKeysPayload) -> None:
    settings = app_state.settings
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
        normalize_search_resource(payload.ai_primary_search_resource, "pubmed"),
    )
    object.__setattr__(
        settings,
        "pdf_downloader_mode",
        normalize_pdf_downloader_mode(payload.pdf_downloader_mode, "pdf_xml"),
    )
    object.__setattr__(settings, "pubmed_requests_per_second", pubmed_rps)

    pubmed_service = getattr(app_state, "pubmed_service", None)
    client = getattr(pubmed_service, "client", None)
    if client is not None:
        client.rate_limiter = AsyncRateLimiter(pubmed_rps)


def app_settings_log_context(payload: AppAPIKeysPayload) -> dict[str, object]:
    return {
        "assistant_api_key": bool(payload.assistant_api_key),
        "ncbi_api_key": bool(payload.ncbi_api_key),
        "unpaywall_email": bool(payload.unpaywall_email),
        "openalex_api_key": bool(payload.openalex_api_key),
        "core_api_key": bool(payload.core_api_key),
        "pubmed_oa_only": payload.pubmed_oa_only,
        "ai_primary_search_resource": payload.ai_primary_search_resource,
        "pdf_downloader_mode": payload.pdf_downloader_mode,
        "pdf_unpaywall_fallback_enabled": payload.pdf_unpaywall_fallback_enabled,
        "pdf_core_fallback_enabled": payload.pdf_core_fallback_enabled,
        "pdf_arxiv_fallback_enabled": payload.pdf_arxiv_fallback_enabled,
    }
