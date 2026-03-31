#!/usr/bin/env python3
"""Benchmark native vs legacy fast search/download behavior on a 50-result query."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

QUERY = '"ethylene"[Title/Abstract] AND ("docking"[Title/Abstract] OR "molecular docking"[Title/Abstract] OR "in silico"[Title/Abstract])'
NATIVE_BASE = "http://127.0.0.1:8002"
LEGACY_BASE = "http://127.0.0.1:8003"
MAX_RESULTS = 50

SCRAPE_DIR = Path(__file__).resolve().parent
DATE_STAMP = date.today().isoformat()
JSON_PATH = SCRAPE_DIR / f"native_vs_legacy_fast50_{DATE_STAMP}.json"
REPORT_PATH = SCRAPE_DIR / f"native_vs_legacy_fast50_{DATE_STAMP}.md"


def article_ref(article: dict) -> dict[str, str | None]:
    return {
        "pmid": article.get("pmid"),
        "doi": article.get("doi"),
        "pmc_id": article.get("pmc_id"),
        "title": article.get("title"),
        "year": article.get("year"),
    }


def article_key(article: dict) -> str:
    return article.get("pmid") or article.get("doi") or article.get("pmc_id") or article.get("title") or ""


async def run_search_and_citations(client: httpx.AsyncClient, base_url: str) -> dict:
    started = time.perf_counter()
    search_response = await client.post(
        f"{base_url}/pubmed/search",
        json={
            "query": QUERY,
            "max_results": MAX_RESULTS,
            "batch_size": MAX_RESULTS,
            "use_cache": False,
        },
    )
    search_response.raise_for_status()
    search_wall_ms = round((time.perf_counter() - started) * 1000, 1)
    search_payload = search_response.json()

    started = time.perf_counter()
    citation_response = await client.post(
        f"{base_url}/pubmed/citations",
        json={"articles": [article_ref(article) for article in search_payload["articles"]]},
    )
    citation_response.raise_for_status()
    citations_wall_ms = round((time.perf_counter() - started) * 1000, 1)
    citation_payload = citation_response.json()

    return {
        "search_wall_ms": search_wall_ms,
        "search_meta": search_payload["meta"],
        "articles": search_payload["articles"],
        "citations_wall_ms": citations_wall_ms,
        "citation_non_null": sum(1 for item in citation_payload["items"] if item.get("citation_count") is not None),
        "pmcid_count": sum(1 for article in search_payload["articles"] if article.get("pmc_id")),
    }


async def run_native_availability(client: httpx.AsyncClient, articles: list[dict]) -> dict:
    started = time.perf_counter()
    response = await client.post(
        f"{NATIVE_BASE}/pdf/availability/fast",
        json={"articles": [article_ref(article) for article in articles]},
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "items": payload["items"],
        "ready_count": sum(1 for item in payload["items"] if item.get("ready")),
        "source_counts": dict(Counter(item.get("source") or "none" for item in payload["items"] if item.get("ready"))),
    }


async def run_fast_diagnose(client: httpx.AsyncClient, base_url: str) -> dict:
    started = time.perf_counter()
    response = await client.post(
        f"{base_url}/pdf/test",
        json={
            "query": QUERY,
            "max_results": MAX_RESULTS,
            "batch_size": MAX_RESULTS,
            "use_cache": False,
            "mode": "fast",
            "save_files": False,
        },
        timeout=600.0,
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "success_count": payload["success_count"],
        "failed_count": payload["failed_count"],
        "success_rate": payload["success_rate"],
        "reason_counts": payload["reason_counts"],
        "results": payload["results"],
    }


def compare_preview_to_diagnose(preview_keys: set[str], diagnose_results: list[dict]) -> dict:
    success_keys = {article_key(item["article"]) for item in diagnose_results if item.get("success")}
    return {
        "preview_ready_count": len(preview_keys),
        "diagnose_success_count": len(success_keys),
        "false_negative_count": len(success_keys - preview_keys),
        "false_positive_count": len(preview_keys - success_keys),
    }


def write_report(report: dict) -> None:
    native = report["native"]
    legacy = report["legacy"]
    lines = [
        "# Native vs Legacy Fast50 Benchmark",
        "",
        f"- Date: {report['date']}",
        f"- Query: `{QUERY}`",
        f"- Max results: `{MAX_RESULTS}`",
        "- PDF diagnostics used `save_files=false`, so no benchmark files were kept on disk.",
        "",
        "## Search",
        "",
        f"- Native search: `{native['search']['search_wall_ms']} ms` | backend `{native['search']['search_meta']['elapsed_ms']} ms`",
        f"- Legacy search: `{legacy['search']['search_wall_ms']} ms` | backend `{legacy['search']['search_meta']['elapsed_ms']} ms`",
        f"- PMID overlap in top 50: `{report['pmid_overlap']}/{MAX_RESULTS}`",
        "",
        "## Citations",
        "",
        f"- Native citations: `{native['search']['citations_wall_ms']} ms` | non-null `{native['search']['citation_non_null']}/{MAX_RESULTS}`",
        f"- Legacy citations: `{legacy['search']['citations_wall_ms']} ms` | non-null `{legacy['search']['citation_non_null']}/{MAX_RESULTS}`",
        "",
        "## Native Preview",
        "",
        f"- Availability wall time: `{native['availability']['wall_ms']} ms`",
        f"- Ready count: `{native['availability']['ready_count']}`",
        f"- Preview false negatives vs native fast diagnose: `{native['preview_vs_diag']['false_negative_count']}`",
        f"- Preview false positives vs native fast diagnose: `{native['preview_vs_diag']['false_positive_count']}`",
        "",
        "## Fast Diagnose",
        "",
        f"- Native fast diagnose: `{native['diagnose']['wall_ms']} ms` | success `{native['diagnose']['success_count']}/{MAX_RESULTS}`",
        f"- Legacy fast diagnose: `{legacy['diagnose']['wall_ms']} ms` | success `{legacy['diagnose']['success_count']}/{MAX_RESULTS}`",
        "",
        "## Legacy Heuristic",
        "",
        f"- Legacy PMCID-ready heuristic count: `{legacy['heuristic_ready_count']}`",
        f"- Legacy heuristic false negatives vs legacy fast diagnose: `{legacy['heuristic_vs_diag']['false_negative_count']}`",
        f"- Legacy heuristic false positives vs legacy fast diagnose: `{legacy['heuristic_vs_diag']['false_positive_count']}`",
        "",
        "## Native Ready Sources",
        "",
    ]
    for source, count in sorted(native["availability"]["source_counts"].items()):
        lines.append(f"- `{source}`: `{count}`")
    lines.extend(
        [
            "",
            "## Diagnose Reasons",
            "",
            f"- Native: `{json.dumps(native['diagnose']['reason_counts'], ensure_ascii=True)}`",
            f"- Legacy: `{json.dumps(legacy['diagnose']['reason_counts'], ensure_ascii=True)}`",
            "",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


async def main() -> None:
    async with httpx.AsyncClient(timeout=120.0) as client:
        native_search = await run_search_and_citations(client, NATIVE_BASE)
        legacy_search = await run_search_and_citations(client, LEGACY_BASE)
        native_availability = await run_native_availability(client, native_search["articles"])
        native_diag = await run_fast_diagnose(client, NATIVE_BASE)
        legacy_diag = await run_fast_diagnose(client, LEGACY_BASE)

    native_preview_keys = {article_key(item["article"]) for item in native_availability["items"] if item.get("ready")}
    legacy_heuristic_keys = {
        article_key(article)
        for article in legacy_search["articles"]
        if article.get("pmc_id")
    }
    native_diag_compare = compare_preview_to_diagnose(native_preview_keys, native_diag["results"])
    legacy_diag_compare = compare_preview_to_diagnose(legacy_heuristic_keys, legacy_diag["results"])

    report = {
        "date": DATE_STAMP,
        "query": QUERY,
        "max_results": MAX_RESULTS,
        "pmid_overlap": sum(
            1
            for left, right in zip(native_search["articles"], legacy_search["articles"], strict=False)
            if left.get("pmid") == right.get("pmid")
        ),
        "native": {
            "search": native_search,
            "availability": native_availability,
            "diagnose": native_diag,
            "preview_vs_diag": native_diag_compare,
        },
        "legacy": {
            "search": legacy_search,
            "diagnose": legacy_diag,
            "heuristic_ready_count": len(legacy_heuristic_keys),
            "heuristic_vs_diag": legacy_diag_compare,
        },
    }
    JSON_PATH.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    write_report(report)
    print(json.dumps({
        "json": str(JSON_PATH),
        "report": str(REPORT_PATH),
        "native_search_ms": native_search["search_wall_ms"],
        "legacy_search_ms": legacy_search["search_wall_ms"],
        "native_availability_ready": native_availability["ready_count"],
        "native_diag_success": native_diag["success_count"],
        "legacy_diag_success": legacy_diag["success_count"],
    }, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
