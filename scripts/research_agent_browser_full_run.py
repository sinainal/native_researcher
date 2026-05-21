#!/usr/bin/env python3
"""Run repeatable full Research Agent flows through the real browser UI."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / ".playwright" / "research-agent-full"
PROFILE_DIR = STATE_DIR / "profile"
PID_FILE = STATE_DIR / "browser.pid"

DEFAULT_MODEL = "llamacpp:Qwen3.6-35B-A3B-UD-IQ4_NL"
DEFAULT_BASE_URL = "http://127.0.0.1:8024"
DEFAULT_CDP_URL = "http://127.0.0.1:9224"
DEFAULT_LLAMACPP_EXECUTABLE_CANDIDATES = [
    "/home/sina/Downloads/LLMs/LLm test/llama.cpp-latest/build-cuda130/bin/llama-server",
    "/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin/llama-server",
]
DEFAULT_LLAMACPP_LIBRARY_PATH = (
    "/home/sina/Downloads/LLMs/LLm test/llama.cpp-latest/build-cuda130/bin:"
    "/home/sina/Downloads/LLMs/cuda130/lib:"
    "/usr/local/lib/ollama/cuda_v13:"
    "/usr/local/lib/ollama"
)

RUNS = {
    "criteria_on_autoprocess_full": {
        "label": "Browser E2E Qwen IQ4 criteria ON autoprocess FULL",
        "criteria_enabled": True,
        "prompt": (
            "Create a very small executable research plan for primary papers about dopamine D1 and dopamine D5 "
            "receptor subtype evidence. Use PubMed only. Make exactly two branches, D1/DRD1 and D5/DRD5. "
            "Target 1 paper per branch and keep candidate budget tiny. Include short screening criteria and "
            "PDF extraction questions for subtype, ligand or perturbation, assay, endpoint, effect, exact quote, "
            "and uncertainty. After the plan is visible I will execute it."
        ),
    },
    "criteria_off_autoprocess_full": {
        "label": "Browser E2E Qwen IQ4 criteria OFF autoprocess FULL",
        "criteria_enabled": False,
        "prompt": (
            "Create a very small executable research plan for primary papers about dopamine D1 and dopamine D5 "
            "receptor subtype evidence. Use PubMed only. Make exactly two branches, D1/DRD1 and D5/DRD5. "
            "Target 1 paper per branch and keep candidate budget tiny. Criteria are disabled for this run, so "
            "do not rely on abstract screening; provide PDF extraction questions for subtype, ligand or perturbation, "
            "assay, endpoint, effect, exact quote, and uncertainty. After the plan is visible I will execute it."
        ),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full Research Agent browser E2E tests and keep pages open.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--thinking-level", default="on", choices=["off", "on", "low", "max"])
    parser.add_argument("--runs", default=",".join(RUNS), help=f"Comma-separated run ids: {', '.join(RUNS)}")
    parser.add_argument("--out", default="output/browser_e2e/research_agent_full")
    parser.add_argument("--timeout-s", type=int, default=900)
    parser.add_argument("--slowmo-ms", type=int, default=0)
    parser.add_argument("--keep-open", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--no-execute", action="store_true", help="Stop after the plan card appears.")
    parser.add_argument("--configure-llamacpp", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--select-model-via-ui", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--llamacpp-executable", default="")
    parser.add_argument("--llamacpp-library-path", default=DEFAULT_LLAMACPP_LIBRARY_PATH)
    return parser.parse_args()


def port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def cdp_ready(cdp_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def wait_for_cdp(cdp_url: str, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cdp_ready(cdp_url):
            return
        time.sleep(0.2)
    raise RuntimeError(f"Browser did not expose CDP at {cdp_url}")


def ensure_browser(playwright: Any, cdp_url: str) -> subprocess.Popen[bytes] | None:
    if cdp_ready(cdp_url):
        return None
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    host, port_text = cdp_url.removeprefix("http://").split(":", 1)
    port = int(port_text.split("/", 1)[0])
    if port_open(host, port):
        raise RuntimeError(f"Port {port} is open but CDP is not ready.")
    process = subprocess.Popen(  # noqa: S603
        [
            playwright.chromium.executable_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            "about:blank",
        ],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    wait_for_cdp(cdp_url)
    return process


def ensure_server(base_url: str, timeout_s: float = 2.0) -> None:
    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        try:
            response = httpx.get(f"{base_url.rstrip('/')}/health", timeout=1.0)
            if response.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Native Researcher is not reachable at {base_url}. Start the app first.")


def create_project(base_url: str, name: str) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url.rstrip()}/app/projects",
        json={"name": name, "description": "Automated full browser E2E Research Agent run."},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def model_name(model: str) -> str:
    return model.split(":", 1)[1].strip() if model.startswith("llamacpp:") else model.strip()


def default_llamacpp_executable() -> str:
    for item in DEFAULT_LLAMACPP_EXECUTABLE_CANDIDATES:
        if Path(item).is_file():
            return item
    return ""


def configure_llamacpp_runtime(args: argparse.Namespace) -> dict[str, Any] | None:
    if not args.configure_llamacpp or not args.model.startswith("llamacpp:"):
        return None
    name = model_name(args.model)
    status = httpx.get(f"{args.base_url.rstrip()}/app/llamacpp", timeout=20).json()
    model_item = next((item for item in status.get("models", []) if item.get("id") == name), None)
    if not model_item:
        available = ", ".join(item.get("id", "") for item in status.get("models", []))
        raise RuntimeError(f"llama.cpp model '{name}' is not discovered. Available: {available}")
    executable = args.llamacpp_executable.strip() or status.get("llamacpp_executable") or default_llamacpp_executable()
    if not executable:
        raise RuntimeError("llama.cpp executable path is not configured and no default executable was found.")
    payload = {
        "llamacpp_base_url": status.get("llamacpp_base_url") or "http://127.0.0.1:8098",
        "llamacpp_model": name,
        "llamacpp_executable": executable,
        "llamacpp_model_path": model_item.get("path") or status.get("llamacpp_model_path") or "",
        "llamacpp_library_path": args.llamacpp_library_path.strip() or status.get("llamacpp_library_path") or "",
        "llamacpp_server_args": status.get("llamacpp_server_args") or "",
        "llamacpp_profile": model_item.get("profile") or status.get("llamacpp_profile") or "custom",
        "llamacpp_auto_start": True,
        "start": False,
        "restart": False,
        "warmup": False,
    }
    response = httpx.put(f"{args.base_url.rstrip()}/app/llamacpp", json=payload, timeout=30)
    response.raise_for_status()
    configured = response.json()
    if configured.get("llamacpp_model") != name:
        raise RuntimeError(f"Failed to configure llama.cpp model '{name}'. Response: {configured}")
    return configured


def init_storage_script(model: str, thinking_level: str, criteria_enabled: bool) -> str:
    visibility = {model: True}
    return f"""
        localStorage.setItem("native_researcher_assistant_mode", "research_agent");
        localStorage.setItem("native_researcher_model", {json.dumps(model)});
        localStorage.setItem("native_researcher_model_visibility", {json.dumps(json.dumps(visibility))});
        localStorage.setItem("native_researcher_research_planner_mode", "staged");
        localStorage.setItem("native_researcher_agent_criteria_enabled", {json.dumps("true" if criteria_enabled else "false")});
        localStorage.setItem("native_researcher_agent_pdf_extractor_enabled", "true");
        localStorage.setItem("native_researcher_agent_autoprocess_enabled", "true");
        localStorage.setItem("native_researcher_agent_pdf_scope", "selected_backup");
        localStorage.setItem("native_researcher_thinking_level", {json.dumps(thinking_level)});
        localStorage.setItem("native_researcher_sidebar_open", "true");
    """


def configure_page(
    page: Any,
    project_id: str,
    model: str,
    thinking_level: str,
    criteria_enabled: bool,
    timeout_ms: int,
    *,
    select_model_via_ui: bool,
) -> None:
    page.wait_for_selector("#assistantInput", timeout=timeout_ms)
    page.wait_for_function(
        "projectId => localStorage.getItem('native_researcher_active_project') === projectId && document.title.includes('Native Researcher')",
        arg=project_id,
        timeout=timeout_ms,
    )
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass
    page.evaluate(
        """async ({model, thinkingLevel, criteriaEnabled, selectModelViaUi}) => {
          localStorage.setItem("native_researcher_assistant_mode", "research_agent");
          localStorage.setItem("native_researcher_model", model);
          localStorage.setItem("native_researcher_agent_criteria_enabled", criteriaEnabled ? "true" : "false");
          localStorage.setItem("native_researcher_agent_pdf_extractor_enabled", "true");
          localStorage.setItem("native_researcher_agent_autoprocess_enabled", "true");
          localStorage.setItem("native_researcher_agent_pdf_scope", "selected_backup");
          localStorage.setItem("native_researcher_thinking_level", thinkingLevel);
          if (typeof state !== "undefined") {
            state.assistantMode = "research_agent";
            state.thinkingLevel = thinkingLevel;
          }
          if (typeof runtime !== "undefined") {
            runtime.assistantModel = model;
            runtime.agentCriteriaEnabled = criteriaEnabled;
            runtime.agentPdfExtractorEnabled = true;
            runtime.agentAutoprocessEnabled = true;
            runtime.agentPdfScope = "selected_backup";
            runtime.agentScreeningModel = model;
            runtime.agentFullTextModel = model;
            runtime.ollamaThinkingLevel = thinkingLevel;
          }
          if (selectModelViaUi && typeof selectAssistantModel === "function") {
            await selectAssistantModel(model);
          }
          if (typeof updateAgentSettingsUI === "function") updateAgentSettingsUI();
          if (typeof updateAssistantModelUI === "function") updateAssistantModelUI();
        }""",
        {
            "model": model,
            "thinkingLevel": thinking_level,
            "criteriaEnabled": criteria_enabled,
            "selectModelViaUi": select_model_via_ui,
        },
    )
    page.wait_for_function(
        "() => document.querySelector('#assistantModelLoadingPopup')?.hidden !== false",
        timeout=timeout_ms,
    )
    page.wait_for_function(
        "model => localStorage.getItem('native_researcher_assistant_mode') === 'research_agent' && localStorage.getItem('native_researcher_model') === model",
        arg=model,
        timeout=timeout_ms,
    )


def send_prompt_and_wait_for_plan(page: Any, prompt: str, timeout_ms: int) -> None:
    page.fill("#assistantInput", prompt)
    page.click("#assistantSendBtn")
    page.wait_for_function(
        """() => document.querySelector('.research-plan-preview:not(.research-report-preview)')
          || (document.querySelector('#assistantMessages')?.innerText || '').includes('Assistant error:')""",
        timeout=timeout_ms,
    )
    page.wait_for_function(
        "() => !document.querySelector('#assistantSendBtn.is-stop') && !document.querySelector('.assistant-message.pending')",
        timeout=timeout_ms,
    )


def project_run_completed(base_url: str, project_id: str) -> bool:
    try:
        state = httpx.get(f"{base_url.rstrip()}/app/projects/{project_id}/state", timeout=10).json()
    except Exception:
        return False
    runs = state.get("research_runs") or []
    if not runs:
        return False
    run = runs[-1]
    meta = run.get("meta") or {}
    stage_statuses = meta.get("stage_statuses") or {}
    run_status = meta.get("run_status") or run.get("status")
    pdf_status = stage_statuses.get("pdf_screening")
    return run_status == "completed" and (not pdf_status or pdf_status == "completed")


def wait_for_project_run_completion(base_url: str, project_id: str, timeout_ms: int) -> bool:
    deadline = time.perf_counter() + (timeout_ms / 1000)
    while time.perf_counter() < deadline:
        if project_run_completed(base_url, project_id):
            return True
        time.sleep(2)
    return False


def execute_plan_and_wait(page: Any, base_url: str, project_id: str, timeout_ms: int) -> None:
    page.locator(".research-plan-execute-btn").last.click(timeout=30_000)
    page.wait_for_function(
        """() => document.querySelector('.research-report-preview')
          || (document.querySelector('#assistantMessages')?.innerText || '').includes('Research plan execution failed:')""",
        timeout=timeout_ms,
    )
    if not page.locator(".research-report-preview").count():
        wait_for_project_run_completion(base_url, project_id, timeout_ms)
        page.reload(wait_until="domcontentloaded", timeout=45_000)
        try:
            page.wait_for_function(
                """() => document.querySelector('.research-report-preview')
                  || !document.querySelector('.assistant-message.pending')""",
                timeout=30_000,
            )
        except PlaywrightTimeoutError:
            pass
    page.wait_for_function(
        "() => !document.querySelector('.assistant-message.pending')",
        timeout=timeout_ms,
    )


def snapshot_payload(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const allText = document.querySelector('#assistantMessages')?.innerText || '';
          const failureMatch =
            allText.match(/Research plan execution failed:[^\\n]*/)
            || allText.match(/Assistant error:[^\\n]*/);
          const reportCards = document.querySelectorAll('.research-report-preview').length;
          const planCards = document.querySelectorAll('.research-plan-preview:not(.research-report-preview)').length;
          return {
            url: location.href,
            title: document.title,
            projectId: localStorage.getItem('native_researcher_active_project') || '',
            assistantMode: localStorage.getItem('native_researcher_assistant_mode') || '',
            model: localStorage.getItem('native_researcher_model') || '',
            criteriaEnabled: localStorage.getItem('native_researcher_agent_criteria_enabled') !== 'false',
            autoprocessEnabled: localStorage.getItem('native_researcher_agent_autoprocess_enabled') !== 'false',
            status: reportCards > 0 ? 'report_ready' : failureMatch ? 'execution_failed' : planCards > 0 ? 'plan_ready' : 'unknown',
            failureText: failureMatch ? failureMatch[0] : '',
            planCards,
            reportCards,
            tableRows: document.querySelectorAll('tr.article-row').length,
            messages: [...document.querySelectorAll('.assistant-message')].map((node) => ({
              role: node.classList.contains('user') ? 'user' : 'assistant',
              text: (node.innerText || '').trim().slice(0, 1200),
            })),
          };
        }"""
    )


def run_one(context: Any, args: argparse.Namespace, run_id: str, spec: dict[str, Any], out_root: Path) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_name = f"{spec['label']} {timestamp}"
    project = create_project(args.base_url, project_name)
    out_dir = out_root / f"{timestamp}_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    page = context.new_page()
    page.add_init_script(init_storage_script(args.model, args.thinking_level, bool(spec["criteria_enabled"])))
    page.goto(f"{args.base_url.rstrip()}/native_researcher?project={project['id']}", wait_until="domcontentloaded", timeout=45_000)
    started = time.perf_counter()
    timeout_ms = max(30, args.timeout_s) * 1000
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    configure_page(
        page,
        str(project["id"]),
        args.model,
        args.thinking_level,
        bool(spec["criteria_enabled"]),
        timeout_ms,
        select_model_via_ui=bool(args.select_model_via_ui),
    )
    send_prompt_and_wait_for_plan(page, str(spec["prompt"]), timeout_ms)
    if not args.no_execute:
        execute_plan_and_wait(page, args.base_url, str(project["id"]), timeout_ms)
    elapsed_s = round(time.perf_counter() - started, 3)
    page.bring_to_front()
    screenshot = out_dir / "final.png"
    page.screenshot(path=str(screenshot), full_page=True)
    assistant_text = page.locator("#assistantMessages").inner_text(timeout=10_000)
    (out_dir / "assistant_messages.txt").write_text(assistant_text, encoding="utf-8")
    snapshot = snapshot_payload(page)
    project_state = httpx.get(f"{args.base_url.rstrip()}/app/projects/{project['id']}/state", timeout=20).json()
    (out_dir / "project_state.json").write_text(json.dumps(project_state, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "elapsed_s": elapsed_s,
        "project": project,
        "model": args.model,
        "thinking_level": args.thinking_level,
        "criteria_enabled": bool(spec["criteria_enabled"]),
        "autoprocess_enabled": True,
        "executed": not args.no_execute,
        "snapshot": snapshot,
        "page_errors": errors,
        "artifacts": {
            "screenshot": str(screenshot),
            "assistant_messages": str(out_dir / "assistant_messages.txt"),
            "project_state": str(out_dir / "project_state.json"),
        },
    }
    (out_dir / "browser_full_run.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    args = parse_args()
    ensure_server(args.base_url)
    configured = configure_llamacpp_runtime(args)
    if configured:
        print(
            "Configured llama.cpp:",
            configured.get("llamacpp_model"),
            configured.get("llamacpp_profile"),
            configured.get("llamacpp_executable"),
            flush=True,
        )
    selected_runs = [item.strip() for item in args.runs.split(",") if item.strip()]
    unknown = [item for item in selected_runs if item not in RUNS]
    if unknown:
        raise SystemExit(f"Unknown run id(s): {', '.join(unknown)}")
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        process = ensure_browser(playwright, args.cdp_url)
        browser = playwright.chromium.connect_over_cdp(args.cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context(viewport={"width": 1440, "height": 1000})
        if args.slowmo_ms:
            context.set_default_timeout(args.timeout_s * 1000)
        reports = []
        for run_id in selected_runs:
            print(f"Running browser full E2E: {run_id}", flush=True)
            reports.append(run_one(context, args, run_id, RUNS[run_id], out_root))
        summary_path = out_root / "latest_browser_full_summary.json"
        summary_path.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote browser full summary to {summary_path}")
        for report in reports:
            print(
                f"{report['run_id']}: project={report['project']['id']} elapsed={report['elapsed_s']}s "
                f"url={report['snapshot']['url']} reports={report['snapshot']['reportCards']}"
            )
        if not args.keep_open:
            browser.close()
            if process is not None:
                os.killpg(process.pid, signal.SIGTERM)
        else:
            print(f"Browser left open at {args.cdp_url}")


if __name__ == "__main__":
    main()
