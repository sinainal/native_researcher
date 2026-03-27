#!/usr/bin/env python3
"""Quick local benchmark for fast vs balanced PDF retrieval behavior."""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

SCRAPE_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRAPE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.clients.ncbi import NcbiClient
from app.core.config import get_settings
from app.schemas.article import Article, ArticleReference
from app.schemas.pubmed import PubMedSearchRequest
from app.services.pdf_service import PDFService
from app.services.pubmed_service import PubMedService
from app.utils.cache import TTLCache

DATE_STAMP = "2026-03-27"
JSON_PATH = SCRAPE_DIR / f"pdf_mode_benchmark_{DATE_STAMP}.json"
REPORT_PATH = SCRAPE_DIR / f"pdf_mode_benchmark_{DATE_STAMP}.md"
QUERY_SPECS: list[tuple[str, int]] = [
    ("serotonin receptor docking", 8),
    ("serotonin pathway cancer", 6),
    ("alphafold ligand discovery", 6),
]
FAST_SAMPLE_LIMITS = {"pmc": 4, "doi_only": 4, "neither": 1}
BALANCED_MAX_ARTICLES = 4
BALANCED_CASE_TIMEOUT_SECONDS = 15


@dataclass
class SearchSummary:
    query: str
    fetched: int
    total_found: int
    elapsed_ms: int
    request_count: int


@dataclass
class FastResult:
    pmid: str | None
    title: str
    year: str | None
    doi: str | None
    pmc_id: str | None
    ui_ready: bool
    resolve_ms: int
    probe_ms: int
    total_ms: int
    success: bool
    source: str | None
    candidate_count: int
    attempt_count: int
    attempt_sources: list[str]
    failure_errors: list[str]


@dataclass
class BalancedResult:
    pmid: str | None
    title: str
    ui_ready: bool
    total_ms: int
    success: bool
    source: str | None
    reason: str
    candidate_count: int
    attempt_count: int
    browser_used: bool
    attempt_sources: list[str]


def _article_ref(article: Article) -> ArticleReference:
    return ArticleReference(
        pmid=article.pmid,
        doi=article.doi,
        pmc_id=article.pmc_id,
        title=article.title,
        year=article.year,
    )


def _article_category(article: Article) -> str:
    if article.pmc_id:
        return "pmc"
    if article.doi:
        return "doi_only"
    return "neither"


def _truncate(text: str, limit: int = 96) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _safe_mean(values: list[int]) -> float | None:
    if not values:
        return None
    return round(statistics.mean(values), 1)


def _safe_median(values: list[int]) -> float | None:
    if not values:
        return None
    return round(statistics.median(values), 1)


async def _fetch_article_pool(pubmed_service: PubMedService) -> tuple[list[Article], list[SearchSummary]]:
    articles_by_pmid: dict[str, Article] = {}
    search_summaries: list[SearchSummary] = []
    for query, max_results in QUERY_SPECS:
        response = await pubmed_service.search(
            PubMedSearchRequest(
                query=query,
                max_results=max_results,
                batch_size=max_results,
                use_cache=False,
            )
        )
        search_summaries.append(
            SearchSummary(
                query=query,
                fetched=len(response.articles),
                total_found=response.meta.total_results_found,
                elapsed_ms=response.meta.elapsed_ms,
                request_count=response.meta.request_count,
            )
        )
        for article in response.articles:
            articles_by_pmid.setdefault(article.pmid, article)
    return list(articles_by_pmid.values()), search_summaries


def _select_fast_sample(pool: list[Article]) -> list[Article]:
    selected: list[Article] = []
    counts = Counter()
    for article in pool:
        category = _article_category(article)
        if counts[category] >= FAST_SAMPLE_LIMITS.get(category, 0):
            continue
        selected.append(article)
        counts[category] += 1
    return selected


async def _run_fast_probe(pdf_service: PDFService, article: Article) -> FastResult:
    pdf_service.candidate_cache._store.clear()
    ref = _article_ref(article)

    started = time.perf_counter()
    candidates = await pdf_service._build_candidates(ref, mode="fast")
    resolve_ms = int((time.perf_counter() - started) * 1000)

    probe_started = time.perf_counter()
    success_probe, attempts = await pdf_service._probe_candidates(
        candidates,
        mode="fast",
        stop_on_first_success=True,
    )
    probe_ms = int((time.perf_counter() - probe_started) * 1000)

    success = success_probe is not None and success_probe.payload_bytes is not None
    result = FastResult(
        pmid=article.pmid,
        title=article.title,
        year=article.year,
        doi=article.doi,
        pmc_id=article.pmc_id,
        ui_ready=bool(article.pmc_id),
        resolve_ms=resolve_ms,
        probe_ms=probe_ms,
        total_ms=resolve_ms + probe_ms,
        success=success,
        source=success_probe.candidate.source if success_probe is not None else None,
        candidate_count=len(candidates),
        attempt_count=len(attempts),
        attempt_sources=[attempt.candidate.source for attempt in attempts],
        failure_errors=[attempt.error for attempt in attempts if attempt.error],
    )
    print(
        f"[fast] PMID {article.pmid} ready={result.ui_ready} success={result.success} total={result.total_ms}ms"
    )
    return result


def _choose_balanced_articles(pool: list[Article], fast_results: list[FastResult]) -> list[Article]:
    by_pmid = {article.pmid: article for article in pool}
    chosen: list[Article] = []
    seen: set[str] = set()

    def add(pmid: str | None) -> None:
        if not pmid or pmid in seen or pmid not in by_pmid:
            return
        chosen.append(by_pmid[pmid])
        seen.add(pmid)

    false_positives = [item for item in fast_results if item.ui_ready and not item.success]
    false_negatives = [item for item in fast_results if (not item.ui_ready) and item.success]
    ready_successes = [item for item in fast_results if item.ui_ready and item.success]
    doi_failures = [item for item in fast_results if (not item.ui_ready) and (not item.success)]

    for group in (false_positives, false_negatives, doi_failures, ready_successes):
        for item in group:
            add(item.pmid)
            if len(chosen) >= BALANCED_MAX_ARTICLES:
                return chosen
    return chosen


async def _run_balanced_case(pdf_service: PDFService, article: Article) -> BalancedResult:
    pdf_service.candidate_cache._store.clear()
    ref = _article_ref(article)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            pdf_service.diagnose_articles(
                [ref],
                save_files=False,
                mode="balanced",
                use_browser_fallback=False,
            ),
            timeout=BALANCED_CASE_TIMEOUT_SECONDS,
        )
        result = result[0]
    except TimeoutError:
        total_ms = int((time.perf_counter() - started) * 1000)
        timed_out = BalancedResult(
            pmid=article.pmid,
            title=article.title,
            ui_ready=bool(article.pmc_id),
            total_ms=total_ms,
            success=False,
            source=None,
            reason="benchmark_timeout",
            candidate_count=0,
            attempt_count=0,
            browser_used=False,
            attempt_sources=[],
        )
        print(f"[balanced] PMID {article.pmid} timeout after {timed_out.total_ms}ms")
        return timed_out
    total_ms = int((time.perf_counter() - started) * 1000)
    browser_used = any((attempt.mode or "") == "browser_download" for attempt in result.attempts)
    balanced = BalancedResult(
        pmid=article.pmid,
        title=article.title,
        ui_ready=bool(article.pmc_id),
        total_ms=total_ms,
        success=result.success,
        source=result.source,
        reason=result.reason,
        candidate_count=result.candidate_count,
        attempt_count=len(result.attempts),
        browser_used=browser_used,
        attempt_sources=[attempt.source for attempt in result.attempts],
    )
    print(
        f"[balanced] PMID {article.pmid} ready={balanced.ui_ready} success={balanced.success} total={balanced.total_ms}ms"
    )
    return balanced


def _stats_block(items: list[int]) -> dict[str, float | int | None]:
    if not items:
        return {"count": 0, "mean_ms": None, "median_ms": None, "min_ms": None, "max_ms": None}
    return {
        "count": len(items),
        "mean_ms": _safe_mean(items),
        "median_ms": _safe_median(items),
        "min_ms": min(items),
        "max_ms": max(items),
    }


def _summarize_fast(fast_results: list[FastResult]) -> dict[str, object]:
    total_ms = [item.total_ms for item in fast_results]
    resolve_ms = [item.resolve_ms for item in fast_results]
    probe_ms = [item.probe_ms for item in fast_results]
    false_positives = [item for item in fast_results if item.ui_ready and not item.success]
    false_negatives = [item for item in fast_results if (not item.ui_ready) and item.success]
    return {
        "timing": {
            "total": _stats_block(total_ms),
            "resolve": _stats_block(resolve_ms),
            "probe": _stats_block(probe_ms),
        },
        "success_count": sum(1 for item in fast_results if item.success),
        "failure_count": sum(1 for item in fast_results if not item.success),
        "false_positive_count": len(false_positives),
        "false_negative_count": len(false_negatives),
        "false_positive_pmids": [item.pmid for item in false_positives],
        "false_negative_pmids": [item.pmid for item in false_negatives],
    }


def _summarize_balanced(balanced_results: list[BalancedResult]) -> dict[str, object]:
    return {
        "timing": _stats_block([item.total_ms for item in balanced_results]),
        "success_count": sum(1 for item in balanced_results if item.success),
        "failure_count": sum(1 for item in balanced_results if not item.success),
        "browser_success_count": sum(1 for item in balanced_results if item.browser_used and item.success),
    }


def _build_report(
    *,
    generated_at: str,
    search_summaries: list[SearchSummary],
    fast_results: list[FastResult],
    balanced_results: list[BalancedResult],
    fast_summary: dict[str, object],
    balanced_summary: dict[str, object],
    settings_info: dict[str, object],
) -> str:
    lines: list[str] = []
    lines.append("# PDF Mode Benchmark")
    lines.append("")
    lines.append(f"Date: {DATE_STAMP}")
    lines.append(f"Generated at: {generated_at}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("- Compare current `fast` and sampled `balanced` PDF retrieval latency.")
    lines.append("- Check whether the current UI readiness heuristic (`pmc_id => ready`) matches real downloadability.")
    lines.append("- Use a small live PubMed sample only; this is a directional benchmark, not a full crawl.")
    lines.append("")
    lines.append("## Environment Notes")
    lines.append("")
    lines.append(f"- `UNPAYWALL_EMAIL`: {'set' if settings_info['unpaywall_email_set'] else 'not set'}")
    lines.append(f"- `NCBI_API_KEY`: {'set' if settings_info['ncbi_api_key_set'] else 'not set'}")
    lines.append("- Balanced mode therefore does not have Unpaywall enrichment in this run.")
    lines.append("")
    lines.append("## Query Fetch Times")
    lines.append("")
    lines.append("| Query | Fetched | Total Found | Requests | Time |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for item in search_summaries:
        lines.append(
            f"| {item.query} | {item.fetched} | {item.total_found} | {item.request_count} | {item.elapsed_ms} ms |"
        )
    lines.append("")
    lines.append("## Fast Mode Summary")
    lines.append("")
    fast_total = fast_summary["timing"]["total"]  # type: ignore[index]
    fast_resolve = fast_summary["timing"]["resolve"]  # type: ignore[index]
    fast_probe = fast_summary["timing"]["probe"]  # type: ignore[index]
    lines.append(
        f"- Sample size: {fast_total['count']} articles"
    )
    lines.append(
        f"- Successes: {fast_summary['success_count']}, failures: {fast_summary['failure_count']}"
    )
    lines.append(
        f"- Total time: mean {fast_total['mean_ms']} ms, median {fast_total['median_ms']} ms, range {fast_total['min_ms']}..{fast_total['max_ms']} ms"
    )
    lines.append(
        f"- Candidate build time: mean {fast_resolve['mean_ms']} ms, median {fast_resolve['median_ms']} ms"
    )
    lines.append(
        f"- Probe time: mean {fast_probe['mean_ms']} ms, median {fast_probe['median_ms']} ms"
    )
    lines.append(
        f"- False positives (`ready` but fast cannot download): {fast_summary['false_positive_count']}"
    )
    lines.append(
        f"- False negatives (`not ready` but fast can download): {fast_summary['false_negative_count']}"
    )
    lines.append("")
    lines.append("### Fast Sample")
    lines.append("")
    lines.append("| PMID | Ready | Success | Total | Resolve | Probe | Candidates | Source | Notes |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
    for item in fast_results:
        notes = "false positive" if item.ui_ready and not item.success else (
            "false negative" if (not item.ui_ready) and item.success else ""
        )
        lines.append(
            f"| {item.pmid or '-'} | {'yes' if item.ui_ready else 'no'} | {'yes' if item.success else 'no'} | "
            f"{item.total_ms} ms | {item.resolve_ms} ms | {item.probe_ms} ms | {item.candidate_count} | "
            f"{item.source or '-'} | {notes} |"
        )
    lines.append("")
    lines.append("## Balanced Sample Summary")
    lines.append("")
    balanced_timing = balanced_summary["timing"]  # type: ignore[index]
    lines.append(f"- Sample size: {balanced_timing['count']} articles")
    lines.append(
        f"- Successes: {balanced_summary['success_count']}, failures: {balanced_summary['failure_count']}"
    )
    lines.append(
        f"- Total time: mean {balanced_timing['mean_ms']} ms, median {balanced_timing['median_ms']} ms, range {balanced_timing['min_ms']}..{balanced_timing['max_ms']} ms"
    )
    lines.append(
        f"- Browser fallback successes inside sample: {balanced_summary['browser_success_count']}"
    )
    lines.append("")
    lines.append("### Balanced Sample")
    lines.append("")
    lines.append("| PMID | Ready | Success | Total | Candidates | Source | Reason | Browser |")
    lines.append("| --- | --- | --- | ---: | ---: | --- | --- | --- |")
    for item in balanced_results:
        lines.append(
            f"| {item.pmid or '-'} | {'yes' if item.ui_ready else 'no'} | {'yes' if item.success else 'no'} | "
            f"{item.total_ms} ms | {item.candidate_count} | {item.source or '-'} | {item.reason} | "
            f"{'yes' if item.browser_used else 'no'} |"
        )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Current UI readiness is not accurate enough because it only keys off `pmc_id`.")
    lines.append("- Any DOI-only article that fast can retrieve is a false negative for the UI.")
    lines.append("- Any PMCID article that fast still cannot retrieve is a false positive for the UI.")
    lines.append("- Fast mode looks acceptable only when its full end-to-end time stays near the 1-2 second target; anything above that needs either better candidate ordering or lighter probes.")
    lines.append("- Balanced is useful as a rescue path, but it is materially slower and should stay out of the default row-level readiness path.")
    lines.append("")
    lines.append("## Immediate Product Guidance")
    lines.append("")
    lines.append("- Keep `fast` as the default click path.")
    lines.append("- Do not present `ready` as a hard truth while it is still PMCID-only.")
    lines.append("- Replace the current heuristic with a lightweight verified-fast probe if we want row status to be trustworthy.")
    lines.append("")
    lines.append("## Sample Titles")
    lines.append("")
    for item in fast_results:
        lines.append(f"- `{item.pmid}`: {_truncate(item.title)}")
    lines.append("")
    return "\n".join(lines)


async def main() -> None:
    settings = get_settings()
    timeout = httpx.Timeout(settings.http_timeout_seconds)
    generated_at = datetime.now(timezone.utc).isoformat()

    ncbi_client = httpx.AsyncClient(
        base_url=settings.ncbi_base_url,
        timeout=timeout,
        headers={"User-Agent": settings.request_user_agent},
    )
    shared_client = httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": settings.request_user_agent},
    )
    pubmed_service = PubMedService(
        client=NcbiClient(ncbi_client, settings),
        cache=TTLCache(ttl_seconds=1, max_entries=1),
    )
    pdf_service = PDFService(
        http_client=shared_client,
        settings=settings,
        candidate_cache=TTLCache(ttl_seconds=1, max_entries=1),
    )

    try:
        pool, search_summaries = await _fetch_article_pool(pubmed_service)
        fast_sample = _select_fast_sample(pool)
        fast_results = [await _run_fast_probe(pdf_service, article) for article in fast_sample]
        balanced_articles = _choose_balanced_articles(pool, fast_results)
        balanced_results = [await _run_balanced_case(pdf_service, article) for article in balanced_articles]
    finally:
        await ncbi_client.aclose()
        await shared_client.aclose()

    fast_summary = _summarize_fast(fast_results)
    balanced_summary = _summarize_balanced(balanced_results)
    payload = {
        "generated_at": generated_at,
        "settings": {
            "unpaywall_email_set": bool(settings.unpaywall_email),
            "ncbi_api_key_set": bool(settings.ncbi_api_key),
        },
        "queries": [asdict(item) for item in search_summaries],
        "fast_sample_pmids": [item.pmid for item in fast_results],
        "balanced_sample_pmids": [item.pmid for item in balanced_results],
        "fast_results": [asdict(item) for item in fast_results],
        "balanced_results": [asdict(item) for item in balanced_results],
        "fast_summary": fast_summary,
        "balanced_summary": balanced_summary,
    }
    JSON_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(
        _build_report(
            generated_at=generated_at,
            search_summaries=search_summaries,
            fast_results=fast_results,
            balanced_results=balanced_results,
            fast_summary=fast_summary,
            balanced_summary=balanced_summary,
            settings_info=payload["settings"],
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {JSON_PATH}")
    print(f"Wrote {REPORT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
