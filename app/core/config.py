"""Application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]


def _read_secret_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _default_journal_metrics_url() -> str:
    return "https://zenodo.org/api/records/15206056/files/Scimago%20Journal%20Rank%202023.xlsx/content"


def _normalize_search_resource(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"}:
        return normalized
    return default


def _normalize_pdf_downloader_mode(value: str | None, default: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"pdf_xml", "best", "pdf", "xml", "legacy", "article_downloader", "hybrid", "native", "final_method", "perfect"}:
        if normalized in {"best", "legacy", "article_downloader", "hybrid", "native", "final_method", "perfect"}:
            return "pdf_xml"
        return normalized
    return default


def _normalize_ollama_thinking_level(value: str | None, default: str = "off") -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"off", "on"}:
        return normalized
    if normalized in {"low", "medium", "high", "max", "minimal", "true", "yes", "1"}:
        return "on"
    return default


@dataclass(frozen=True)
class Settings:
    app_name: str = "Native Researcher"
    version: str = "0.1.0"
    debug: bool = False
    http_timeout_seconds: float = 30.0
    ncbi_base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    pmc_oa_base_url: str = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"
    europe_pmc_base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    crossref_base_url: str = "https://api.crossref.org"
    doi_resolver_base_url: str = "https://doi.org"
    openalex_base_url: str = "https://api.openalex.org"
    unpaywall_base_url: str = "https://api.unpaywall.org/v2"
    core_base_url: str = "https://api.core.ac.uk/v3"
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    assistant_api_key: str | None = None
    assistant_api_key_path: Path = APP_ROOT / "api_key.txt"
    ncbi_api_key_path: Path = APP_ROOT / "ncbi_api"
    unpaywall_email_path: Path = APP_ROOT / "unpaywall_email"
    openalex_api_key_path: Path = APP_ROOT / "openalex_api_key"
    core_api_key_path: Path = APP_ROOT / "core_api_key"
    pubmed_oa_only_path: Path = APP_ROOT / "pubmed_oa_only"
    ai_primary_search_resource_path: Path = APP_ROOT / "ai_primary_search_resource"
    pdf_downloader_mode_path: Path = APP_ROOT / "pdf_downloader_mode"
    ollama_base_url_path: Path = APP_ROOT / "ollama_base_url"
    ollama_model_path: Path = APP_ROOT / "ollama_model"
    ollama_thinking_level_path: Path = APP_ROOT / "ollama_thinking_level"
    pdf_unpaywall_fallback_enabled_path: Path = APP_ROOT / "pdf_unpaywall_fallback_enabled"
    pdf_core_fallback_enabled_path: Path = APP_ROOT / "pdf_core_fallback_enabled"
    pdf_arxiv_fallback_enabled_path: Path = APP_ROOT / "pdf_arxiv_fallback_enabled"
    unpaywall_email: str | None = None
    ncbi_api_key: str | None = None
    openalex_api_key: str | None = None
    core_api_key: str | None = None
    pubmed_oa_only: bool = True
    ai_primary_search_resource: str = "pubmed"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    ollama_thinking_level: str = "off"
    request_user_agent: str = "NativeResearcher/0.1 (FastAPI Searcher AI Service)"
    pubmed_default_batch_size: int = 250
    pubmed_max_batch_size: int = 250
    pubmed_requests_per_second: float = 2.5
    openalex_requests_per_second: float = 4.5
    europe_pmc_requests_per_second: float = 3.5
    core_requests_per_second: float = 1.5
    arxiv_requests_per_second: float = 2.0
    search_cache_ttl_seconds: int = 900
    search_cache_max_entries: int = 128
    helper_cache_ttl_seconds: int = 7200
    helper_cache_max_entries: int = 64
    helper_log_path: Path = Path("logs/helper_ai_history.jsonl")
    app_event_log_path: Path = Path("logs/app_events.jsonl")
    pdf_cache_ttl_seconds: int = 1800
    pdf_cache_max_entries: int = 256
    pdf_resolve_requests_per_second: float = 20.0
    pdf_downloader_mode: str = "pdf_xml"
    pdf_unpaywall_fallback_enabled: bool = True
    pdf_core_fallback_enabled: bool = False
    pdf_arxiv_fallback_enabled: bool = False
    journal_metrics_enabled: bool = True
    journal_metrics_bootstrap_url: str = _default_journal_metrics_url()
    journal_metrics_source_name: str = "scimago_sjr_2023_zenodo"
    download_root: Path = Path("downloads")
    workspace_root: Path = Path("workspace")

    @classmethod
    def from_env(cls) -> "Settings":
        assistant_api_key_path = Path(os.getenv("ASSISTANT_API_KEY_FILE", str(APP_ROOT / "api_key.txt")))
        ncbi_api_key_path = Path(os.getenv("NCBI_API_KEY_FILE", str(APP_ROOT / "ncbi_api")))
        unpaywall_email_path = Path(os.getenv("UNPAYWALL_EMAIL_FILE", str(APP_ROOT / "unpaywall_email")))
        openalex_api_key_path = Path(os.getenv("OPENALEX_API_KEY_FILE", str(APP_ROOT / "openalex_api_key")))
        core_api_key_path = Path(os.getenv("CORE_API_KEY_FILE", str(APP_ROOT / "core_api_key")))
        pubmed_oa_only_path = Path(os.getenv("PUBMED_OA_ONLY_FILE", str(APP_ROOT / "pubmed_oa_only")))
        ai_primary_search_resource_path = Path(
            os.getenv("AI_PRIMARY_SEARCH_RESOURCE_FILE", str(APP_ROOT / "ai_primary_search_resource"))
        )
        pdf_downloader_mode_path = Path(
            os.getenv("PDF_DOWNLOADER_MODE_FILE", str(APP_ROOT / "pdf_downloader_mode"))
        )
        ollama_base_url_path = Path(os.getenv("OLLAMA_BASE_URL_FILE", str(APP_ROOT / "ollama_base_url")))
        ollama_model_path = Path(os.getenv("OLLAMA_MODEL_FILE", str(APP_ROOT / "ollama_model")))
        ollama_thinking_level_path = Path(os.getenv("OLLAMA_THINKING_LEVEL_FILE", str(APP_ROOT / "ollama_thinking_level")))
        pdf_unpaywall_fallback_enabled_path = Path(
            os.getenv("PDF_UNPAYWALL_FALLBACK_ENABLED_FILE", str(APP_ROOT / "pdf_unpaywall_fallback_enabled"))
        )
        pdf_core_fallback_enabled_path = Path(
            os.getenv("PDF_CORE_FALLBACK_ENABLED_FILE", str(APP_ROOT / "pdf_core_fallback_enabled"))
        )
        pdf_arxiv_fallback_enabled_path = Path(
            os.getenv("PDF_ARXIV_FALLBACK_ENABLED_FILE", str(APP_ROOT / "pdf_arxiv_fallback_enabled"))
        )
        assistant_api_key = os.getenv("ASSISTANT_API_KEY") or _read_secret_file(assistant_api_key_path)
        api_key = os.getenv("NCBI_API_KEY") or _read_secret_file(ncbi_api_key_path)
        unpaywall_email = os.getenv("UNPAYWALL_EMAIL") or _read_secret_file(unpaywall_email_path)
        openalex_api_key = os.getenv("OPENALEX_API_KEY") or _read_secret_file(openalex_api_key_path)
        core_api_key = (
            os.getenv("CORE_API_KEY")
            or _read_secret_file(core_api_key_path)
            or _read_secret_file(APP_ROOT.parent / "core_api_key")
        )
        pubmed_oa_only = _parse_bool(
            os.getenv("PUBMED_OA_ONLY") or _read_secret_file(pubmed_oa_only_path),
            True,
        )
        ai_primary_search_resource = _normalize_search_resource(
            os.getenv("AI_PRIMARY_SEARCH_RESOURCE") or _read_secret_file(ai_primary_search_resource_path),
            "pubmed",
        )
        pdf_downloader_mode = _normalize_pdf_downloader_mode(
            os.getenv("PDF_DOWNLOADER_MODE") or _read_secret_file(pdf_downloader_mode_path),
            "pdf_xml",
        )
        ollama_base_url = (os.getenv("OLLAMA_BASE_URL") or _read_secret_file(ollama_base_url_path) or "http://localhost:11434").strip()
        if ollama_base_url and "://" not in ollama_base_url:
            ollama_base_url = f"http://{ollama_base_url}"
        ollama_model = os.getenv("OLLAMA_MODEL") or _read_secret_file(ollama_model_path) or ""
        ollama_thinking_level = _normalize_ollama_thinking_level(
            os.getenv("OLLAMA_THINKING_LEVEL") or _read_secret_file(ollama_thinking_level_path),
            "off",
        )
        pdf_unpaywall_fallback_enabled = _parse_bool(
            os.getenv("PDF_UNPAYWALL_FALLBACK_ENABLED") or _read_secret_file(pdf_unpaywall_fallback_enabled_path),
            True,
        )
        pdf_core_fallback_enabled = _parse_bool(
            os.getenv("PDF_CORE_FALLBACK_ENABLED") or _read_secret_file(pdf_core_fallback_enabled_path),
            False,
        )
        pdf_arxiv_fallback_enabled = _parse_bool(
            os.getenv("PDF_ARXIV_FALLBACK_ENABLED") or _read_secret_file(pdf_arxiv_fallback_enabled_path),
            False,
        )
        default_rps = 10.0 if api_key else 2.5
        download_root = Path(os.getenv("DOWNLOAD_ROOT", "downloads"))
        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "workspace"))
        journal_metrics_enabled = _parse_bool(os.getenv("JOURNAL_METRICS_ENABLED"), True)
        return cls(
            debug=os.getenv("DEBUG", "false").lower() == "true",
            http_timeout_seconds=float(os.getenv("HTTP_TIMEOUT_SECONDS", "30")),
            europe_pmc_base_url=os.getenv(
                "EUROPE_PMC_BASE_URL",
                "https://www.ebi.ac.uk/europepmc/webservices/rest",
            ),
            unpaywall_base_url=os.getenv(
                "UNPAYWALL_BASE_URL",
                "https://api.unpaywall.org/v2",
            ),
            core_base_url=os.getenv("CORE_BASE_URL", "https://api.core.ac.uk/v3"),
            arxiv_base_url=os.getenv("ARXIV_BASE_URL", "https://export.arxiv.org/api/query"),
            assistant_api_key=assistant_api_key,
            assistant_api_key_path=assistant_api_key_path,
            ncbi_api_key_path=ncbi_api_key_path,
            unpaywall_email_path=unpaywall_email_path,
            openalex_api_key_path=openalex_api_key_path,
            core_api_key_path=core_api_key_path,
            pubmed_oa_only_path=pubmed_oa_only_path,
            ai_primary_search_resource_path=ai_primary_search_resource_path,
            pdf_downloader_mode_path=pdf_downloader_mode_path,
            ollama_base_url_path=ollama_base_url_path,
            ollama_model_path=ollama_model_path,
            ollama_thinking_level_path=ollama_thinking_level_path,
            pdf_unpaywall_fallback_enabled_path=pdf_unpaywall_fallback_enabled_path,
            pdf_core_fallback_enabled_path=pdf_core_fallback_enabled_path,
            pdf_arxiv_fallback_enabled_path=pdf_arxiv_fallback_enabled_path,
            unpaywall_email=unpaywall_email,
            ncbi_api_key=api_key,
            openalex_api_key=openalex_api_key,
            core_api_key=core_api_key,
            pubmed_oa_only=pubmed_oa_only,
            ai_primary_search_resource=ai_primary_search_resource,
            ollama_base_url=ollama_base_url.rstrip("/"),
            ollama_model=ollama_model.strip(),
            ollama_thinking_level=ollama_thinking_level,
            request_user_agent=os.getenv(
                "REQUEST_USER_AGENT",
                "NativeResearcher/0.1 (FastAPI Searcher AI Service)",
            ),
            pubmed_default_batch_size=int(os.getenv("PUBMED_DEFAULT_BATCH_SIZE", "250")),
            pubmed_max_batch_size=int(os.getenv("PUBMED_MAX_BATCH_SIZE", "250")),
            pubmed_requests_per_second=float(os.getenv("PUBMED_REQUESTS_PER_SECOND", str(default_rps))),
            openalex_requests_per_second=float(os.getenv("OPENALEX_REQUESTS_PER_SECOND", "4.5")),
            europe_pmc_requests_per_second=float(os.getenv("EUROPE_PMC_REQUESTS_PER_SECOND", "3.5")),
            core_requests_per_second=float(os.getenv("CORE_REQUESTS_PER_SECOND", "1.5")),
            arxiv_requests_per_second=float(os.getenv("ARXIV_REQUESTS_PER_SECOND", "2.0")),
            search_cache_ttl_seconds=int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "900")),
            search_cache_max_entries=int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "128")),
            helper_cache_ttl_seconds=int(os.getenv("HELPER_CACHE_TTL_SECONDS", "7200")),
            helper_cache_max_entries=int(os.getenv("HELPER_CACHE_MAX_ENTRIES", "64")),
            helper_log_path=Path(os.getenv("HELPER_LOG_PATH", "logs/helper_ai_history.jsonl")),
            app_event_log_path=Path(os.getenv("APP_EVENT_LOG_PATH", "logs/app_events.jsonl")),
            pdf_cache_ttl_seconds=int(os.getenv("PDF_CACHE_TTL_SECONDS", "1800")),
            pdf_cache_max_entries=int(os.getenv("PDF_CACHE_MAX_ENTRIES", "256")),
            pdf_resolve_requests_per_second=float(
                os.getenv("PDF_RESOLVE_REQUESTS_PER_SECOND", "20")
            ),
            pdf_downloader_mode=pdf_downloader_mode,
            pdf_unpaywall_fallback_enabled=pdf_unpaywall_fallback_enabled,
            pdf_core_fallback_enabled=pdf_core_fallback_enabled,
            pdf_arxiv_fallback_enabled=pdf_arxiv_fallback_enabled,
            journal_metrics_enabled=journal_metrics_enabled,
            journal_metrics_bootstrap_url=os.getenv(
                "JOURNAL_METRICS_BOOTSTRAP_URL",
                _default_journal_metrics_url(),
            ),
            journal_metrics_source_name=os.getenv(
                "JOURNAL_METRICS_SOURCE_NAME",
                "scimago_sjr_2023_zenodo",
            ),
            download_root=download_root,
            workspace_root=workspace_root,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
