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
    assistant_api_key: str | None = None
    assistant_api_key_path: Path = APP_ROOT / "api_key.txt"
    ncbi_api_key_path: Path = APP_ROOT / "ncbi_api"
    unpaywall_email_path: Path = APP_ROOT / "unpaywall_email"
    pubmed_oa_only_path: Path = APP_ROOT / "pubmed_oa_only"
    unpaywall_email: str | None = None
    ncbi_api_key: str | None = None
    pubmed_oa_only: bool = True
    request_user_agent: str = "NativeResearcher/0.1 (FastAPI Searcher AI Service)"
    pubmed_default_batch_size: int = 250
    pubmed_max_batch_size: int = 250
    pubmed_requests_per_second: float = 3.0
    search_cache_ttl_seconds: int = 900
    search_cache_max_entries: int = 128
    helper_cache_ttl_seconds: int = 7200
    helper_cache_max_entries: int = 64
    helper_log_path: Path = Path("logs/helper_ai_history.jsonl")
    app_event_log_path: Path = Path("logs/app_events.jsonl")
    pdf_cache_ttl_seconds: int = 1800
    pdf_cache_max_entries: int = 256
    pdf_download_concurrency: int = 16
    pdf_candidate_download_concurrency: int = 5
    pdf_browser_fallback_concurrency: int = 6
    pdf_resolve_requests_per_second: float = 20.0
    download_root: Path = Path("downloads")
    workspace_root: Path = Path("workspace")

    @classmethod
    def from_env(cls) -> "Settings":
        assistant_api_key_path = Path(os.getenv("ASSISTANT_API_KEY_FILE", str(APP_ROOT / "api_key.txt")))
        ncbi_api_key_path = Path(os.getenv("NCBI_API_KEY_FILE", str(APP_ROOT / "ncbi_api")))
        unpaywall_email_path = Path(os.getenv("UNPAYWALL_EMAIL_FILE", str(APP_ROOT / "unpaywall_email")))
        pubmed_oa_only_path = Path(os.getenv("PUBMED_OA_ONLY_FILE", str(APP_ROOT / "pubmed_oa_only")))
        assistant_api_key = os.getenv("ASSISTANT_API_KEY") or _read_secret_file(assistant_api_key_path)
        api_key = os.getenv("NCBI_API_KEY") or _read_secret_file(ncbi_api_key_path)
        unpaywall_email = os.getenv("UNPAYWALL_EMAIL") or _read_secret_file(unpaywall_email_path)
        pubmed_oa_only = _parse_bool(
            os.getenv("PUBMED_OA_ONLY") or _read_secret_file(pubmed_oa_only_path),
            True,
        )
        default_rps = 10.0 if api_key else 3.0
        download_root = Path(os.getenv("DOWNLOAD_ROOT", "downloads"))
        workspace_root = Path(os.getenv("WORKSPACE_ROOT", "workspace"))
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
            assistant_api_key=assistant_api_key,
            assistant_api_key_path=assistant_api_key_path,
            ncbi_api_key_path=ncbi_api_key_path,
            unpaywall_email_path=unpaywall_email_path,
            pubmed_oa_only_path=pubmed_oa_only_path,
            unpaywall_email=unpaywall_email,
            ncbi_api_key=api_key,
            pubmed_oa_only=pubmed_oa_only,
            request_user_agent=os.getenv(
                "REQUEST_USER_AGENT",
                "NativeResearcher/0.1 (FastAPI Searcher AI Service)",
            ),
            pubmed_default_batch_size=int(os.getenv("PUBMED_DEFAULT_BATCH_SIZE", "250")),
            pubmed_max_batch_size=int(os.getenv("PUBMED_MAX_BATCH_SIZE", "250")),
            pubmed_requests_per_second=float(
                os.getenv("PUBMED_REQUESTS_PER_SECOND", str(default_rps))
            ),
            search_cache_ttl_seconds=int(os.getenv("SEARCH_CACHE_TTL_SECONDS", "900")),
            search_cache_max_entries=int(os.getenv("SEARCH_CACHE_MAX_ENTRIES", "128")),
            helper_cache_ttl_seconds=int(os.getenv("HELPER_CACHE_TTL_SECONDS", "7200")),
            helper_cache_max_entries=int(os.getenv("HELPER_CACHE_MAX_ENTRIES", "64")),
            helper_log_path=Path(os.getenv("HELPER_LOG_PATH", "logs/helper_ai_history.jsonl")),
            app_event_log_path=Path(os.getenv("APP_EVENT_LOG_PATH", "logs/app_events.jsonl")),
            pdf_cache_ttl_seconds=int(os.getenv("PDF_CACHE_TTL_SECONDS", "1800")),
            pdf_cache_max_entries=int(os.getenv("PDF_CACHE_MAX_ENTRIES", "256")),
            pdf_download_concurrency=int(os.getenv("PDF_DOWNLOAD_CONCURRENCY", "16")),
            pdf_candidate_download_concurrency=int(
                os.getenv("PDF_CANDIDATE_DOWNLOAD_CONCURRENCY", "5")
            ),
            pdf_browser_fallback_concurrency=int(
                os.getenv("PDF_BROWSER_FALLBACK_CONCURRENCY", "6")
            ),
            pdf_resolve_requests_per_second=float(
                os.getenv("PDF_RESOLVE_REQUESTS_PER_SECOND", "20")
            ),
            download_root=download_root,
            workspace_root=workspace_root,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
