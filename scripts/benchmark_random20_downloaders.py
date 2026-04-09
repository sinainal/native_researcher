"""Build a fresh random OA20 dataset and benchmark downloader modes sequentially.

This script intentionally keeps only metadata and result artifacts.
Downloader output files are not retained.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config import get_settings
from app.schemas.article import ArticleReference
from app.services.downloader.service import PDFService
from app.utils.cache import TTLCache

ROOT = Path("/home/sina/Downloads/Researcher")
IMPROVEMENT = ROOT / "improvement project"


def _normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if "doi.org/" in cleaned:
        cleaned = cleaned.split("doi.org/", 1)[1]
    return cleaned or None


def _extract_id(value: str | None, marker: str) -> str | None:
    if not value:
        return None
    parsed = value.strip()
    if marker in parsed:
        parsed = parsed.split(marker, 1)[1]
    parsed = parsed.strip("/ ")
    return parsed or None


def _article_from_openalex(item: dict[str, Any]) -> dict[str, Any] | None:
    doi = _normalize_doi(item.get("doi"))
    if not doi:
        return None
    location = item.get("best_oa_location") or item.get("primary_location") or {}
    source = location.get("source") or {}
    if source.get("type") != "journal":
        return None
    title = (item.get("title") or "").strip()
    journal = (source.get("display_name") or "").strip()
    if not title or not journal:
        return None
    ids = item.get("ids") or {}
    return {
        "openalex_id": _extract_id(item.get("id"), "openalex.org/"),
        "doi": doi,
        "title": title,
        "year": str(item.get("publication_year") or "") or None,
        "journal": journal,
        "pmid": _extract_id(ids.get("pmid"), "pubmed.ncbi.nlm.nih.gov/"),
        "pmc_id": _extract_id(ids.get("pmcid"), "PMC"),
        "issn_l": source.get("issn_l"),
        "source_type": source.get("type"),
        "oa_pdf_url": location.get("pdf_url"),
        "landing_page_url": location.get("landing_page_url"),
    }


async def build_random_oa20_dataset(*, seed: int, sample_size: int, pool_size: int) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    seen_dois: set[str] = set()
    query_urls: list[str] = []
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        for offset in range(6):
            current_seed = seed + offset
            params = {
                "filter": "is_oa:true,type:article,has_doi:true",
                "sample": str(pool_size),
                "seed": str(current_seed),
                "select": ",".join(
                    [
                        "id",
                        "doi",
                        "title",
                        "publication_year",
                        "ids",
                        "primary_location",
                        "best_oa_location",
                        "open_access",
                    ]
                ),
            }
            url = f"https://api.openalex.org/works?{urlencode(params)}"
            query_urls.append(url)
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("results") or []:
                normalized = _article_from_openalex(item)
                if not normalized:
                    continue
                if normalized["doi"] in seen_dois:
                    continue
                seen_dois.add(normalized["doi"])
                candidates.append(normalized)
                if len(candidates) >= sample_size:
                    break
            if len(candidates) >= sample_size:
                break

    if len(candidates) < sample_size:
        raise RuntimeError(f"Only {len(candidates)} usable OA journal articles were sampled across multiple OpenAlex seeds; needed {sample_size}.")

    selected = candidates[:sample_size]
    return {
        "name": "random_oa20_openalex_sample",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": seed,
        "sample_size": sample_size,
        "pool_size": pool_size,
        "source": "openalex_sample",
        "query_urls": query_urls,
        "items": selected,
    }


def _article_reference(item: dict[str, Any]) -> ArticleReference:
    return ArticleReference(
        title=item.get("title"),
        year=item.get("year"),
        journal=item.get("journal"),
        doi=item.get("doi"),
        pmc_id=item.get("pmc_id"),
        pmid=item.get("pmid"),
        oa_pdf_url=item.get("oa_pdf_url"),
        landing_page_url=item.get("landing_page_url"),
    )


async def benchmark_mode(dataset: dict[str, Any], *, downloader_mode: str, exact_mode: str) -> dict[str, Any]:
    settings = get_settings()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
        headers={"User-Agent": settings.request_user_agent},
        follow_redirects=True,
    ) as client:
        service = PDFService(
            http_client=client,
            settings=settings,
            candidate_cache=TTLCache(ttl_seconds=60, max_entries=256),
        )
        started = time.perf_counter()
        item_results: list[dict[str, Any]] = []
        for item in dataset["items"]:
            article = _article_reference(item)
            article_started = time.perf_counter()
            results = await service.diagnose_articles(
                [article],
                save_files=False,
                mode=exact_mode,
                downloader_mode=downloader_mode,
                use_browser_fallback=False,
            )
            result = results[0]
            item_results.append(
                {
                    "article": item,
                    "success": result.success,
                    "reason": result.reason,
                    "source": result.source,
                    "url": result.url,
                    "content_kind": result.content_kind,
                    "content_type": result.content_type,
                    "candidate_count": result.candidate_count,
                    "elapsed_ms": int((time.perf_counter() - article_started) * 1000),
                    "attempts": [
                        {
                            "source": attempt.source,
                            "url": attempt.url,
                            "status_code": attempt.status_code,
                            "content_type": attempt.content_type,
                            "success": attempt.success,
                            "error": attempt.error,
                        }
                        for attempt in result.attempts
                    ],
                }
            )
        elapsed_ms = int((time.perf_counter() - started) * 1000)

    success_count = sum(1 for item in item_results if item["success"])
    pdf_count = sum(1 for item in item_results if item["content_kind"] == "pdf")
    xml_count = sum(1 for item in item_results if item["content_kind"] == "xml_fulltext")
    html_count = sum(1 for item in item_results if item["content_kind"] == "html_fulltext")
    elapsed_values = [item["elapsed_ms"] for item in item_results]
    return {
        "downloader_mode": downloader_mode,
        "mode": exact_mode,
        "sequential": True,
        "elapsed_ms": elapsed_ms,
        "success_count": success_count,
        "failed_count": len(item_results) - success_count,
        "strict_pdf_count": pdf_count,
        "xml_count": xml_count,
        "html_count": html_count,
        "success_rate": round(success_count / len(item_results), 4),
        "strict_pdf_rate": round(pdf_count / len(item_results), 4),
        "avg_article_ms": round(statistics.mean(elapsed_values), 1) if elapsed_values else 0.0,
        "median_article_ms": round(statistics.median(elapsed_values), 1) if elapsed_values else 0.0,
        "reason_counts": dict(sorted(Counter(item["reason"] for item in item_results).items())),
        "source_counts": dict(sorted(Counter(item["source"] or "-" for item in item_results).items())),
        "items": item_results,
    }


def write_report(outdir: Path, *, dataset: dict[str, Any], results: dict[str, Any]) -> None:
    summary = results["summary"]
    lines = [
        "# Random OA20 Downloader Benchmark",
        "",
        f"- Downloader mode: `{summary['downloader_mode']}`",
        f"- Exact mode: `{summary['mode']}`",
        f"- Sequential single-runner: `{summary['sequential']}`",
        f"- Seed: `{dataset['seed']}`",
        f"- Sample size: `{dataset['sample_size']}`",
        f"- Pool size: `{dataset['pool_size']}`",
        f"- Source: `{dataset['source']}`",
        f"- Elapsed: `{summary['elapsed_ms']} ms`",
        f"- Success: `{summary['success_count']}/{dataset['sample_size']}`",
        f"- Strict PDF: `{summary['strict_pdf_count']}/{dataset['sample_size']}`",
        f"- XML: `{summary['xml_count']}`",
        f"- HTML: `{summary['html_count']}`",
        f"- Avg/article: `{summary['avg_article_ms']} ms`",
        f"- Median/article: `{summary['median_article_ms']} ms`",
        "- Files: no downloader artifacts kept; only dataset and result metadata were stored.",
        "",
        "## Reason Counts",
    ]
    for key, value in summary["reason_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Source Counts"])
    for key, value in summary["source_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    (outdir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="hybrid", choices=["legacy", "article_downloader", "hybrid"])
    parser.add_argument("--exact-mode", default="fast", choices=["fast", "balanced"])
    parser.add_argument("--sample-size", type=int, default=20)
    parser.add_argument("--pool-size", type=int, default=120)
    parser.add_argument("--seed", type=int, default=random.randint(1, 999_999))
    parser.add_argument("--dataset", type=str, default="")
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    outdir = IMPROVEMENT / f"random20_{args.mode}_{stamp}"
    outdir.mkdir(parents=True, exist_ok=True)

    if args.dataset:
        dataset = json.loads(Path(args.dataset).read_text())
    else:
        dataset = await build_random_oa20_dataset(
            seed=args.seed,
            sample_size=args.sample_size,
            pool_size=max(args.pool_size, args.sample_size * 2),
        )

    results = await benchmark_mode(dataset, downloader_mode=args.mode, exact_mode=args.exact_mode)
    payload = {
        "dataset": dataset,
        "summary": {k: v for k, v in results.items() if k != "items"},
        "items": results["items"],
    }

    (outdir / "dataset.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(outdir, dataset=dataset, results=payload)
    print(outdir)


if __name__ == "__main__":
    asyncio.run(main())
