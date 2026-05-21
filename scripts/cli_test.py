#!/usr/bin/env python3
"""Small, repeatable CLI smoke tests for Research Agent model flows."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import Settings, get_settings
from app.services.local_llamacpp_supervisor import ensure_llamacpp_ready, stop_local_llamacpp_servers
from scripts.research_agent_e2e_eval import (
    QWEN_COMPACT_DOPAMINE_SERIES_PROMPT,
    ModelTarget,
    configure_settings,
    resolve_targets,
    run_planner_eval,
    safe_name,
)

MODEL_ALIASES = {
    "qwen-iq4nl": "Qwen3.6-35B-A3B-UD-IQ4_NL",
    "qwen-iq3s": "Qwen3.6-35B-A3B-IQ3_S-merged",
    "gemma-iq4nl": "gemma-4-26B-A4B-it-UD-IQ4_NL",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a standard Research Agent smoke test from the terminal. "
            "Models are executed sequentially so VRAM is not shared."
        )
    )
    parser.add_argument(
        "-prompt",
        "--prompt",
        default="",
        help="Research prompt to test. Defaults to the compact dopamine D1-D5 planner prompt.",
    )
    parser.add_argument(
        "--models",
        default="qwen-iq4nl,gemma-iq4nl",
        help=(
            "Comma-separated model aliases or exact model ids. "
            "Known aliases: qwen-iq4nl, qwen-iq3s, gemma-iq4nl."
        ),
    )
    parser.add_argument(
        "--thinking",
        "--thinking-level",
        dest="thinking_level",
        default="on",
        choices=["off", "low", "on", "max"],
        help="Thinking level passed to the Research Agent.",
    )
    parser.add_argument(
        "--out",
        default="output/cli_test/latest",
        help="Output directory for result.json and summary.md.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8098", help="Local llama.cpp base URL.")
    parser.add_argument("--timeout-s", type=int, default=360, help="Planner timeout per model.")
    parser.add_argument(
        "--start-timeout-s",
        type=float,
        default=180.0,
        help="llama.cpp startup timeout per model.",
    )
    parser.add_argument(
        "--n-gpu-layers",
        default="",
        help="Optional override for llama.cpp -ngl. Empty keeps the model profile default.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve models and write the test plan without starting llama.cpp.",
    )
    return parser.parse_args()


def resolve_model_ids(raw: str) -> list[str]:
    ids = []
    for item in str(raw or "").split(","):
        key = item.strip()
        if not key:
            continue
        ids.append(MODEL_ALIASES.get(key, key))
    if not ids:
        raise SystemExit("At least one model must be provided with --models.")
    return ids


def default_prompt() -> str:
    return QWEN_COMPACT_DOPAMINE_SERIES_PROMPT


def write_summary(out_dir: Path, payload: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# CLI Research Agent Smoke Test",
        "",
        f"Created: {payload['created_at']}",
        f"Thinking: `{payload['thinking_level']}`",
        f"Dry run: `{payload['dry_run']}`",
        "",
        "## Models",
        "",
    ]
    for result in payload["results"]:
        planner = result.get("planner") or {}
        metrics = planner.get("dopamine_series_metrics") or {}
        lines.extend(
            [
                f"### {result['model']}",
                "",
                f"- Profile: `{result.get('profile')}`",
                f"- OK: `{planner.get('ok')}`",
                f"- Elapsed: `{planner.get('elapsed_s')}`",
                f"- Plan score: `{planner.get('plan_quality_score')}`",
                f"- Branches: `{planner.get('branch_count')}`",
                f"- Criteria: `{planner.get('criteria_count')}`",
                f"- Questions: `{planner.get('question_count')}`",
                f"- D1-D5 coverage: `{metrics.get('series_coverage')}`",
                f"- Covered receptors: `{', '.join(metrics.get('covered_receptors') or [])}`",
                f"- Error: `{planner.get('error') or ''}`",
                "",
            ]
        )
    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


async def run_one(
    args: argparse.Namespace,
    settings: Settings,
    target: ModelTarget,
    out_dir: Path,
    prompt: str,
) -> dict[str, Any]:
    model_out = out_dir / safe_name(target.id)
    model_out.mkdir(parents=True, exist_ok=True)
    configure_settings(
        settings,
        target,
        model_out,
        args.base_url,
        args.thinking_level,
        args.n_gpu_layers,
    )
    stop_local_llamacpp_servers(args.base_url)
    print(f"[cli-test] Starting {target.id} ({target.profile})", flush=True)
    started = time.perf_counter()
    try:
        await ensure_llamacpp_ready(
            settings,
            model=target.id,
            request_user_agent=settings.request_user_agent,
            timeout_seconds=args.start_timeout_s,
        )
        planner = await run_planner_eval(
            settings,
            target,
            args.timeout_s,
            prompt_name="cli_prompt",
            prompt=prompt,
            thinking_level=args.thinking_level,
        )
        result = {
            "model": target.id,
            "path": target.path,
            "profile": target.profile,
            "elapsed_s": round(time.perf_counter() - started, 3),
            "planner": planner,
        }
        (model_out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            "[cli-test] "
            f"{target.id}: ok={planner.get('ok')} "
            f"elapsed={planner.get('elapsed_s')} "
            f"branches={planner.get('branch_count')}",
            flush=True,
        )
        return result
    finally:
        stop_local_llamacpp_servers(args.base_url)


async def main() -> None:
    args = parse_args()
    settings = get_settings()
    prompt = args.prompt.strip() or default_prompt()
    model_ids = resolve_model_ids(args.models)
    targets = resolve_targets(settings, model_ids)
    out_dir = Path(args.out)
    created_at = datetime.now(UTC).replace(microsecond=0).isoformat()

    if args.dry_run:
        payload = {
            "created_at": created_at,
            "thinking_level": args.thinking_level,
            "dry_run": True,
            "prompt": prompt,
            "results": [
                {
                    "model": target.id,
                    "path": target.path,
                    "profile": target.profile,
                    "planner": {"ok": None, "error": "dry-run"},
                }
                for target in targets
            ],
        }
        write_summary(out_dir, payload)
        print(f"[cli-test] Dry run OK. Models: {', '.join(target.id for target in targets)}", flush=True)
        print(f"[cli-test] Wrote {out_dir / 'summary.md'}", flush=True)
        return

    results = []
    for target in targets:
        results.append(await run_one(args, settings, target, out_dir, prompt))

    payload = {
        "created_at": created_at,
        "thinking_level": args.thinking_level,
        "dry_run": False,
        "prompt": prompt,
        "results": results,
    }
    write_summary(out_dir, payload)
    print(f"[cli-test] Wrote {out_dir / 'summary.md'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
