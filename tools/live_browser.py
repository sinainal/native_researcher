#!/usr/bin/env python3
"""Small live-browser control CLI for Native Researcher.

This is intentionally domain-level: commands say "send-agent" or "snapshot",
while Playwright stays hidden behind the CLI.
"""

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
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".playwright" / "live-browser"
PROFILE_DIR = STATE_DIR / "profile"
PID_FILE = STATE_DIR / "browser.pid"
SNAPSHOT_FILE = STATE_DIR / "snapshot.json"
DEFAULT_URL = "http://127.0.0.1:8002/native_researcher"
DEFAULT_CDP = "http://127.0.0.1:9223"
DEFAULT_MODEL = "llamacpp:qwen3.6-35b-a3b-q4_K_M"


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def _cdp_ready(cdp_url: str = DEFAULT_CDP) -> bool:
    try:
        with urllib.request.urlopen(f"{cdp_url}/json/version", timeout=0.8) as response:
            return response.status == 200
    except Exception:
        return False


def _wait_for_cdp(cdp_url: str, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cdp_ready(cdp_url):
            return True
        time.sleep(0.2)
    return False


def _read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _chromium_executable() -> str:
    with sync_playwright() as pw:
        return pw.chromium.executable_path


def open_browser(args: argparse.Namespace) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    cdp_url = args.cdp_url
    host, port_text = cdp_url.removeprefix("http://").split(":", 1)
    port = int(port_text.split("/", 1)[0])
    if _port_open(host, port) and _cdp_ready(cdp_url):
        navigate(args.url, cdp_url=cdp_url, model=args.model)
        _print_json({"ok": True, "status": "already_open", "cdp_url": cdp_url, "url": args.url})
        return

    executable = _chromium_executable()
    command = [
        executable,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        args.url,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    if not _wait_for_cdp(cdp_url, timeout=args.timeout):
        raise SystemExit(f"Browser did not expose CDP at {cdp_url}")
    navigate(args.url, cdp_url=cdp_url, model=args.model)
    _print_json({"ok": True, "status": "opened", "pid": process.pid, "cdp_url": cdp_url, "url": args.url})


def close_browser(args: argparse.Namespace) -> None:
    pid = _read_pid()
    if pid and _pid_alive(pid):
        os.killpg(pid, signal.SIGTERM)
        time.sleep(0.4)
        if _pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
    if PID_FILE.exists():
        PID_FILE.unlink()
    _print_json({"ok": True, "status": "closed", "pid": pid})


def status(args: argparse.Namespace) -> None:
    pid = _read_pid()
    _print_json(
        {
            "ok": True,
            "pid": pid,
            "pid_alive": _pid_alive(pid),
            "cdp_ready": _cdp_ready(args.cdp_url),
            "cdp_url": args.cdp_url,
        }
    )


def _with_page(cdp_url: str, url: str | None = None, model: str | None = None):
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    if model:
        page.goto(url or DEFAULT_URL, wait_until="domcontentloaded")
        page.evaluate(
            """model => {
              localStorage.setItem('native_researcher_model', model);
              const raw = localStorage.getItem('native_researcher_model_visibility') || '{}';
              let visibility = {};
              try { visibility = JSON.parse(raw) || {}; } catch (_) { visibility = {}; }
              visibility[model] = true;
              localStorage.setItem('native_researcher_model_visibility', JSON.stringify(visibility));
            }""",
            model,
        )
        page.reload(wait_until="domcontentloaded")
    elif url:
        page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("#assistantInput", timeout=15000)
    return pw, browser, page


def _wait_app_ready(page, *, wait_model: bool = False, timeout: float = 20.0) -> None:
    page.wait_for_selector("#assistantInput", timeout=int(timeout * 1000))
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_function(
        "() => Boolean(document.querySelector('#assistantInput')) && !document.querySelector('#assistantInput').disabled",
        timeout=int(timeout * 1000),
    )
    if wait_model:
        page.wait_for_function(
            "() => document.querySelector('#assistantModelLoadingPopup')?.hidden !== false",
            timeout=int(timeout * 1000),
        )


def navigate(url: str, *, cdp_url: str = DEFAULT_CDP, model: str | None = None) -> None:
    pw, browser, page = _with_page(cdp_url, url=url, model=model)
    try:
        page.bring_to_front()
        _wait_app_ready(page, wait_model=False)
    except PlaywrightTimeoutError:
        pass
    finally:
        browser.close()
        pw.stop()


def _set_research_agent_mode(page) -> None:
    _wait_app_ready(page, wait_model=True)
    page.click("#assistantDraftBtn")
    page.click("#assistantResearchModeBtn")
    page.wait_for_function(
        "() => localStorage.getItem('native_researcher_assistant_mode') === 'research_agent'",
        timeout=10000,
    )
    page.wait_for_function(
        "() => document.querySelector('#assistantMessages')?.innerText.includes('Research Agent Mode')",
        timeout=10000,
    )


def send_agent(args: argparse.Namespace) -> None:
    if not _cdp_ready(args.cdp_url):
        open_args = argparse.Namespace(url=args.url, cdp_url=args.cdp_url, model=args.model, timeout=args.timeout)
        open_browser(open_args)
    pw, browser, page = _with_page(args.cdp_url, url=args.url, model=args.model)
    try:
        page.bring_to_front()
        _wait_app_ready(page, wait_model=True, timeout=args.timeout)
        _set_research_agent_mode(page)
        _wait_app_ready(page, wait_model=True, timeout=args.timeout)
        page.fill("#assistantInput", args.message)
        page.press("#assistantInput", "Enter")
        page.wait_for_function(
            """message => [...document.querySelectorAll('.assistant-message.user')]
              .some((node) => (node.innerText || '').includes(message))""",
            arg=args.message,
            timeout=int(args.timeout * 1000),
        )
        stopped = False
        if args.stop_after_user:
            time.sleep(args.stop_delay)
            try:
                page.click("#assistantSendBtn", timeout=1500)
                stopped = True
            except PlaywrightTimeoutError:
                stopped = False
        payload = _snapshot_payload(page)
        payload.update({"ok": True, "sent": True, "stopped": stopped, "message": args.message})
        SNAPSHOT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_json(payload)
    finally:
        browser.close()
        pw.stop()


def _snapshot_payload(page) -> dict[str, Any]:
    return page.evaluate(
        """() => ({
          url: location.href,
          title: document.title,
          assistantMode: localStorage.getItem('native_researcher_assistant_mode') || '',
          model: localStorage.getItem('native_researcher_model') || '',
          messages: [...document.querySelectorAll('.assistant-message')].map((node) => ({
            role: node.classList.contains('user') ? 'user' : 'assistant',
            text: (node.innerText || '').trim().slice(0, 500),
          })),
          planCards: document.querySelectorAll('.research-plan-preview').length,
          queryHistoryItems: [...document.querySelectorAll('#workspaceQueryList .native-workspace-library-item, #workspaceQueryList [data-query-id]')].length,
          tableRows: document.querySelectorAll('tr.article-row').length,
          modelLoadingHidden: document.querySelector('#assistantModelLoadingPopup')?.hidden ?? true,
        })"""
    )


def snapshot(args: argparse.Namespace) -> None:
    if not _cdp_ready(args.cdp_url):
        raise SystemExit(f"No live browser at {args.cdp_url}. Run `open` first.")
    pw, browser, page = _with_page(args.cdp_url)
    try:
        payload = _snapshot_payload(page)
        SNAPSHOT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_json({"ok": True, **payload, "snapshot_file": str(SNAPSHOT_FILE)})
    finally:
        browser.close()
        pw.stop()


def run_basic_agent_test(args: argparse.Namespace) -> None:
    open_browser(argparse.Namespace(url=args.url, cdp_url=args.cdp_url, model=args.model, timeout=args.timeout))
    send_agent(
        argparse.Namespace(
            url=args.url,
            cdp_url=args.cdp_url,
            model=args.model,
            message=args.message,
            timeout=args.timeout,
            stop_after_user=True,
            stop_delay=args.stop_delay,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control the live Native Researcher browser.")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--cdp-url", default=DEFAULT_CDP)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=20.0)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("open", help="Open or reuse the headed live browser.")
    sub.add_parser("close", help="Close the managed live browser.")
    sub.add_parser("status", help="Report managed browser status.")
    sub.add_parser("snapshot", help="Print a compact DOM snapshot.")

    send = sub.add_parser("send-agent", help="Switch to Research Agent mode and send a message.")
    send.add_argument("message")
    send.add_argument("--stop-after-user", action="store_true", help="Abort the stream after the user bubble appears.")
    send.add_argument("--stop-delay", type=float, default=1.5)

    smoke = sub.add_parser("run-basic-agent-test", help="Open the browser and verify a Research Agent message can be sent.")
    smoke.add_argument(
        "--message",
        default="Create a tiny research plan for dopamine D1 and D5. Target 2 papers per branch.",
    )
    smoke.add_argument("--stop-delay", type=float, default=1.5)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "open":
        open_browser(args)
    elif args.command == "close":
        close_browser(args)
    elif args.command == "status":
        status(args)
    elif args.command == "snapshot":
        snapshot(args)
    elif args.command == "send-agent":
        send_agent(args)
    elif args.command == "run-basic-agent-test":
        run_basic_agent_test(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
