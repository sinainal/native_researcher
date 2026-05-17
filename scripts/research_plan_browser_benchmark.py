#!/usr/bin/env python3
"""Drive the real Native Researcher UI for research-plan benchmark smoke tests."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPT = (
    "Create the best research plan to find real papers about nanoplastics or microplastics "
    "and dopamine D-series receptors/signaling. We want papers that can later answer: in "
    "nanoplastic-related studies, what dopamine D receptor or dopaminergic interactions, "
    "binding/signaling effects, cellular effects, oxidative stress, neurotoxicity, or pathway "
    "changes were observed? Prefer queries likely to retrieve primary studies and mechanistic "
    "evidence. Do not execute screening or PDF analysis in planning."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a browser-driven Research Agent planning smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8024", help="Native Researcher app URL.")
    parser.add_argument("--app-path", default="/static/native_researcher.html", help="Path opened in the browser.")
    parser.add_argument("--model", required=True, help="Assistant model, e.g. llamacpp:Qwen3.6-35B-A3B-UD-IQ4_NL.")
    parser.add_argument("--prompt", default="", help="Inline prompt.")
    parser.add_argument("--prompt-file", default="", help="Prompt file.")
    parser.add_argument("--out", default="", help="Output directory.")
    parser.add_argument("--headed", action="store_true", help="Open a visible browser window.")
    parser.add_argument("--slowmo-ms", type=int, default=0, help="Playwright slow motion in milliseconds.")
    parser.add_argument("--timeout-s", type=int, default=360, help="End-to-end timeout.")
    parser.add_argument("--planner-mode", default="staged", choices=["staged", "legacy"])
    parser.add_argument("--criteria-disabled", action="store_true")
    parser.add_argument("--no-start-server", action="store_true", help="Require an already-running app server.")
    parser.add_argument("--server-port", type=int, default=8024, help="Port for auto-started uvicorn.")
    return parser.parse_args()


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    return args.prompt.strip() or DEFAULT_PROMPT


def wait_for_server(base_url: str, timeout_s: float) -> bool:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=2.0)
            if response.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def ensure_server(args: argparse.Namespace) -> subprocess.Popen[bytes] | None:
    if wait_for_server(args.base_url, 1.5):
        return None
    if args.no_start_server:
        raise RuntimeError(f"App server is not reachable at {args.base_url}.")
    process = subprocess.Popen(  # noqa: S603,S607
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(args.server_port),
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not wait_for_server(args.base_url, 45.0):
        process.terminate()
        raise RuntimeError(f"Started uvicorn but {args.base_url} did not become reachable.")
    return process


def local_storage_script(*, model: str, planner_mode: str, criteria_enabled: bool) -> str:
    visibility = {model: True}
    return f"""
        localStorage.setItem("native_researcher_assistant_mode", "research_agent");
        localStorage.setItem("native_researcher_model", {json.dumps(model)});
        localStorage.setItem("native_researcher_model_visibility", {json.dumps(json.dumps(visibility))});
        localStorage.setItem("native_researcher_research_planner_mode", {json.dumps(planner_mode)});
        localStorage.setItem("native_researcher_agent_criteria_enabled", {json.dumps("true" if criteria_enabled else "false")});
        localStorage.setItem("native_researcher_sidebar_open", "true");
    """


def fetch_project_state(base_url: str, project_id: str) -> dict[str, Any] | None:
    if not project_id:
        return None
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/app/projects/{project_id}/state", timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def run_browser(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = Path(args.out) if args.out else PROJECT_ROOT / "output" / "benchmarks" / "browser_research_plan"
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = load_prompt(args)
    started = time.perf_counter()
    console_messages: list[str] = []
    page_errors: list[str] = []
    app_url = f"{args.base_url.rstrip('/')}{args.app_path}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=not args.headed, slow_mo=max(0, args.slowmo_ms))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script(
            local_storage_script(
                model=args.model,
                planner_mode=args.planner_mode,
                criteria_enabled=not args.criteria_disabled,
            )
        )
        page = context.new_page()
        page.on("console", lambda message: console_messages.append(f"{message.type}: {message.text}"))
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(app_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector("#assistantInput", timeout=45_000)
        page.fill("#assistantInput", prompt)
        page.click("#assistantSendBtn")
        try:
            page.wait_for_selector(".research-plan-preview", timeout=args.timeout_s * 1000)
            page.wait_for_function(
                "() => !document.querySelector('#assistantSendBtn.is-stop')",
                timeout=args.timeout_s * 1000,
            )
        except PlaywrightTimeoutError:
            page.screenshot(path=str(out_dir / "timeout.png"), full_page=True)
            raise
        elapsed_s = round(time.perf_counter() - started, 3)
        screenshot_path = out_dir / "final.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        text_path = out_dir / "assistant_messages.txt"
        assistant_text = page.locator("#assistantMessages").inner_text(timeout=10_000)
        text_path.write_text(assistant_text, encoding="utf-8")
        project_id = str(page.evaluate("localStorage.getItem('native_researcher_active_project') || ''") or "")
        browser.close()

    project_state = fetch_project_state(args.base_url, project_id)
    state_path = None
    if project_state is not None:
        state_path = out_dir / "project_state.json"
        state_path.write_text(json.dumps(project_state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "base_url": args.base_url,
        "app_url": app_url,
        "model": args.model,
        "planner_mode": args.planner_mode,
        "criteria_enabled": not args.criteria_disabled,
        "elapsed_s": elapsed_s,
        "project_id": project_id,
        "artifacts": {
            "screenshot": str(screenshot_path),
            "assistant_messages": str(text_path),
            "project_state": str(state_path) if state_path else "",
        },
        "console_tail": console_messages[-80:],
        "page_errors": page_errors,
    }
    (out_dir / "browser_benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    args = parse_args()
    process = ensure_server(args)
    try:
        report = run_browser(args)
    finally:
        if process is not None:
            process.terminate()
    print(f"Wrote browser benchmark artifacts to {Path(report['artifacts']['screenshot']).parent}")
    print(f"{report['model']}: elapsed={report['elapsed_s']}s project={report['project_id'] or '-'}")


if __name__ == "__main__":
    main()
