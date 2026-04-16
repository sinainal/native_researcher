"""Run a simple end-to-end search + download smoke test from the terminal."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.clients.ncbi import NcbiClient
from app.core.config import get_settings
from app.schemas.article import ArticleReference
from app.schemas.pdf import PDFTestRequest
from app.schemas.pubmed import PubMedSearchRequest
from app.services.pdf_service import PDFService
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a simple search + download smoke test.")
    parser.add_argument("--query", required=True, help="Literature query to search.")
    parser.add_argument("--source", default="pubmed", choices=["pubmed", "openalex", "europe_pmc", "pmc", "core", "arxiv"], help="Primary search source.")
    parser.add_argument("--mode", default="pdf_xml", choices=["pdf_xml", "xml", "pdf"], help="Downloader mode to test.")
    parser.add_argument("--max-results", type=int, default=1, help="Number of search hits to inspect.")
    parser.add_argument("--year-start", type=int, default=None)
    parser.add_argument("--year-end", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--download-dir", default=None, help="Download directory. Defaults to project download root.")
    save_group = parser.add_mutually_exclusive_group()
    save_group.add_argument("--save-files", dest="save_files", action="store_true", help="Persist downloaded files to disk.")
    save_group.add_argument("--no-save-files", dest="save_files", action="store_false", help="Use a temporary directory and discard files.")
    parser.set_defaults(save_files=True)
    return parser


def _article_reference(item: Any) -> ArticleReference:
    return ArticleReference(
        source_name=getattr(item, "source_name", None),
        source_record_id=getattr(item, "source_record_id", None),
        title=getattr(item, "title", None),
        year=getattr(item, "year", None),
        journal=getattr(item, "journal", None),
        doi=getattr(item, "doi", None),
        pmc_id=getattr(item, "pmc_id", None),
        pmid=getattr(item, "pmid", None),
        oa_pdf_url=getattr(item, "oa_pdf_url", None),
        landing_page_url=getattr(item, "landing_page_url", None),
    )


async def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    timeout = httpx.Timeout(settings.http_timeout_seconds)
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": settings.request_user_agent},
        follow_redirects=True,
    ) as shared_client, httpx.AsyncClient(
        base_url=settings.ncbi_base_url,
        timeout=timeout,
        headers={"User-Agent": settings.request_user_agent},
        follow_redirects=True,
    ) as ncbi_http_client:
        ncbi_client = NcbiClient(ncbi_http_client, settings)
        pubmed_service = PubMedService(
            client=ncbi_client,
            cache=TTLCache(ttl_seconds=settings.search_cache_ttl_seconds, max_entries=settings.search_cache_max_entries),
            http_client=shared_client,
            settings=settings,
        )
        pdf_service = PDFService(
            http_client=shared_client,
            settings=settings,
            candidate_cache=TTLCache(ttl_seconds=settings.pdf_cache_ttl_seconds, max_entries=settings.pdf_cache_max_entries),
        )

        search = await pubmed_service.search(
            PubMedSearchRequest(
                query=args.query,
                year_start=args.year_start,
                year_end=args.year_end,
                max_results=args.max_results,
                batch_size=args.batch_size,
                preferred_source=args.source,
                use_cache=False,
            )
        )
        articles = [_article_reference(article) for article in search.articles]
        diagnostics = await pdf_service.diagnose_articles(
            articles,
            download_dir=args.download_dir,
            save_files=args.save_files,
            downloader_mode=args.mode,
        )
        success_count = sum(1 for item in diagnostics if item.success)
        total = len(diagnostics)
        return {
            "query": args.query,
            "source": args.source,
            "mode": args.mode,
            "max_results": args.max_results,
            "search_meta": search.meta.model_dump(),
            "success_count": success_count,
            "failed_count": total - success_count,
            "success_rate": round((success_count / total) * 100, 2) if total else 0.0,
            "results": [item.model_dump() for item in diagnostics],
        }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = asyncio.run(run_smoke(args))
    print(json.dumps(payload, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
