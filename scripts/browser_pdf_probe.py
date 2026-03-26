"""Probe failed PDF candidates with a real browser context."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "output" / "pdf_diagnostics" / "live_test_response.json"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "output" / "test_pdf_browser"
DEFAULT_REPORT = REPO_ROOT / "output" / "pdf_diagnostics" / "browser_probe_report.json"


def sanitize_filename(value: str | None) -> str:
    text = value or "article"
    text = re.sub(r"[^\w.\- ]+", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "_", text).strip("._")[:140] or "article"


def is_pdf_body(content_type: str, body: bytes) -> bool:
    if len(body) < 4:
        return False
    starts_with_pdf = body[:4] == b"%PDF"
    if "pdf" in content_type or "octet-stream" in content_type:
        return starts_with_pdf
    return starts_with_pdf


def build_file_path(article: dict[str, str | None], source_url: str, output_dir: Path) -> Path:
    year = article.get("year") or "unknown_year"
    stem = sanitize_filename(
        article.get("title")
        or article.get("pmid")
        or article.get("doi")
        or article.get("pmc_id")
        or "article"
    )
    host = "browser"
    try:
        host = re.sub(r"^www\.", "", __import__("urllib.parse").parse.urlparse(source_url).hostname or "browser")
    except Exception:
        host = "browser"
    return output_dir / f"year_{year}" / f"{stem}_{host}.pdf"


def normalize_url(candidate: str | None, base_url: str) -> str | None:
    if not candidate:
        return None
    try:
        return urljoin(base_url, candidate)
    except Exception:
        return None


def extract_candidates(page) -> list[str]:  # noqa: ANN001
    return page.evaluate(
        """
        () => {
          const raw = new Set();
          const add = (value) => {
            if (!value || typeof value !== "string") return;
            raw.add(value.trim());
          };

          document.querySelectorAll("meta").forEach((meta) => {
            const name = (meta.getAttribute("name") || meta.getAttribute("property") || "").toLowerCase();
            const content = meta.getAttribute("content") || "";
            if (name.includes("citation_pdf_url") || content.includes("type=printable")) {
              add(content);
            }
          });

          document.querySelectorAll("a[href], area[href], iframe[src], embed[src], link[href]").forEach((node) => {
            add(node.getAttribute("href") || node.getAttribute("src"));
          });

          document.querySelectorAll("object[data]").forEach((node) => add(node.getAttribute("data")));

          document.querySelectorAll("[data-pdf-url], [data-download-url], [data-url]").forEach((node) => {
            add(node.getAttribute("data-pdf-url"));
            add(node.getAttribute("data-download-url"));
            add(node.getAttribute("data-url"));
          });

          document.querySelectorAll("a, button").forEach((node) => {
            const text = (node.textContent || "").toLowerCase();
            if (text.includes("pdf") || text.includes("download")) {
              add(node.getAttribute("href"));
              add(node.getAttribute("data-url"));
            }
          });

          return [...raw];
        }
        """
    )


def rank_candidate(url: str) -> int:
    lower = url.lower()
    score = 0
    if "type=printable" in lower:
        score += 6
    if lower.endswith(".pdf"):
        score += 6
    if "/pdf" in lower:
        score += 5
    if "download" in lower:
        score += 4
    if "article/file" in lower:
        score += 4
    if "viewer" in lower:
        score -= 2
    return score


def try_url(page, context, url: str, article: dict[str, str | None], output_dir: Path, attempt_log: list[dict]) -> dict | None:  # noqa: ANN001
    network_hits: list[dict] = []
    downloads = []

    def on_response(response) -> None:  # noqa: ANN001
        try:
            content_type = (response.headers.get("content-type") or "").lower()
            url_lower = response.url.lower()
            if "pdf" not in content_type and ".pdf" not in url_lower and "type=printable" not in url_lower:
                return
            body = response.body()
            if not is_pdf_body(content_type, body):
                return
            network_hits.append(
                {
                    "url": response.url,
                    "status": response.status,
                    "content_type": content_type,
                    "body": body,
                }
            )
        except Exception:
            return

    def on_download(download) -> None:  # noqa: ANN001
        downloads.append(download)

    page.on("response", on_response)
    page.on("download", on_download)
    try:
        response = None
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception as exc:
            if not downloads:
                raise exc
        page.wait_for_timeout(1800)

        if downloads:
            download = downloads[0]
            file_path = build_file_path(article, url, output_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            download.save_as(str(file_path))
            body = file_path.read_bytes()
            if is_pdf_body("application/pdf", body):
                attempt_log.append(
                    {
                        "url": url,
                        "final_url": download.url,
                        "status": None,
                        "content_type": "application/pdf",
                        "success": True,
                        "mode": "playwright_download",
                    }
                )
                return {"file_path": str(file_path), "url": download.url or url, "mode": "playwright_download"}
            file_path.unlink(missing_ok=True)
            attempt_log.append(
                {
                    "url": url,
                    "final_url": download.url,
                    "status": None,
                    "content_type": "application/pdf",
                    "success": False,
                    "mode": "playwright_download_non_pdf",
                }
            )

        if network_hits:
            hit = network_hits[0]
            file_path = build_file_path(article, hit["url"], output_dir)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(hit["body"])
            attempt_log.append(
                {
                    "url": url,
                    "final_url": hit["url"],
                    "status": hit["status"],
                    "content_type": hit["content_type"],
                    "success": True,
                    "mode": "network_pdf",
                }
            )
            return {"file_path": str(file_path), "url": hit["url"], "mode": "network_pdf"}

        content_type = (response.headers.get("content-type") or "").lower() if response else ""
        status = response.status if response else None
        current_url = page.url

        if (
            response
            and status == 200
            and ("pdf" in content_type or ".pdf" in current_url.lower() or "type=printable" in current_url.lower())
        ):
            body = response.body()
            if is_pdf_body(content_type, body):
                file_path = build_file_path(article, current_url, output_dir)
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_bytes(body)
                attempt_log.append(
                    {
                        "url": url,
                        "final_url": current_url,
                        "status": status,
                        "content_type": content_type,
                        "success": True,
                        "mode": "document_pdf",
                    }
                )
                return {"file_path": str(file_path), "url": current_url, "mode": "document_pdf"}

        extracted = extract_candidates(page)
        normalized = sorted(
            filter(None, (normalize_url(candidate, current_url) for candidate in extracted)),
            key=rank_candidate,
            reverse=True,
        )

        attempt_log.append(
            {
                "url": url,
                "final_url": current_url,
                "status": status,
                "content_type": content_type or None,
                "success": False,
                "mode": "html_scan",
                "extracted_candidates": normalized[:12],
            }
        )

        for candidate_url in normalized[:8]:
            try:
                api_response = context.request.get(
                    candidate_url,
                    headers={"Referer": current_url, "Accept": "application/pdf,*/*"},
                    timeout=15000,
                )
                candidate_type = (api_response.headers.get("content-type") or "").lower()
                candidate_status = api_response.status
                body = api_response.body()
                if candidate_status == 200 and is_pdf_body(candidate_type, body):
                    file_path = build_file_path(article, candidate_url, output_dir)
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                    file_path.write_bytes(body)
                    attempt_log.append(
                        {
                            "url": candidate_url,
                            "final_url": candidate_url,
                            "status": candidate_status,
                            "content_type": candidate_type,
                            "success": True,
                            "mode": "context_request_pdf",
                        }
                    )
                    return {"file_path": str(file_path), "url": candidate_url, "mode": "context_request_pdf"}

                attempt_log.append(
                    {
                        "url": candidate_url,
                        "final_url": candidate_url,
                        "status": candidate_status,
                        "content_type": candidate_type or None,
                        "success": False,
                        "mode": "context_request_non_pdf",
                    }
                )
            except Exception as exc:
                attempt_log.append(
                    {
                        "url": candidate_url,
                        "success": False,
                        "mode": "context_request_error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        return None
    except PlaywrightTimeoutError as exc:
        attempt_log.append({"url": url, "success": False, "mode": "goto_timeout", "error": str(exc)})
        return None
    except Exception as exc:
        attempt_log.append({"url": url, "success": False, "mode": "goto_error", "error": f"{type(exc).__name__}: {exc}"})
        return None
    finally:
        page.remove_listener("response", on_response)
        page.remove_listener("download", on_download)


def probe_article(browser, item: dict, output_dir: Path) -> dict:
    article = item["article"]
    context = browser.new_context(
        accept_downloads=True,
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        viewport={"width": 1440, "height": 1024},
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    page.set_default_navigation_timeout(15000)

    attempt_log: list[dict] = []
    queue: list[str] = []
    seen: set[str] = set()

    def push(url: str | None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        queue.append(url)

    for attempt in item.get("attempts", []):
        push(attempt.get("url"))

    if article.get("doi"):
        push(f"https://doi.org/{article['doi']}")
    if article.get("pmc_id"):
        push(f"https://pmc.ncbi.nlm.nih.gov/articles/{article['pmc_id']}/")
        push(f"https://europepmc.org/articles/{article['pmc_id']}")

    recovered = None
    while queue and len(attempt_log) < 24 and recovered is None:
        url = queue.pop(0)
        recovered = try_url(page, context, url, article, output_dir, attempt_log)

    context.close()
    return {
        "article": article,
        "recovered": recovered is not None,
        "file_path": recovered["file_path"] if recovered else None,
        "recovered_url": recovered["url"] if recovered else None,
        "recovered_mode": recovered["mode"] if recovered else None,
        "attempts": attempt_log,
    }


def main() -> None:
    input_path = DEFAULT_INPUT
    output_dir = DEFAULT_OUTPUT_DIR
    report_path = DEFAULT_REPORT

    payload = json.loads(input_path.read_text())
    failed_items = [item for item in payload["results"] if not item["success"]]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        probe_results = []
        for item in failed_items:
            article = item["article"]
            print(f"Probing browser fallback: PMID={article.get('pmid') or '-'} DOI={article.get('doi') or '-'}")
            probe_results.append(probe_article(browser, item, output_dir))
        browser.close()

    recovered_count = sum(1 for item in probe_results if item["recovered"])
    combined_success = payload["success_count"] + recovered_count
    report = {
        "source_file": str(input_path),
        "baseline_success_count": payload["success_count"],
        "baseline_total": payload["total"],
        "browser_recovered_count": recovered_count,
        "combined_success_count": combined_success,
        "combined_success_rate": round((combined_success / payload["total"]) * 100, 2),
        "results": probe_results,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
