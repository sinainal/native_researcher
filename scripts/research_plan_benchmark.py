#!/usr/bin/env python3
"""Run modular research-plan benchmarks without opening the browser."""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.research_plan_benchmark import (
    BenchmarkConfig,
    DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT,
    close_clients,
    create_default_benchmark_runner,
    parse_llamacpp_engine_metrics,
    parse_model_specs,
)
from app.core.config import get_settings
from app.llm.llamacpp_profiles import LLAMACPP_SERVER_PROFILES, build_llamacpp_server_args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark research planner models with real article pulls.")
    parser.add_argument("--prompt", default="", help="Inline benchmark prompt.")
    parser.add_argument("--prompt-file", default="", help="Path to a prompt text file.")
    parser.add_argument(
        "--models",
        action="append",
        required=True,
        help=(
            "Comma-separated model specs. Format: model|think=off|label=name. "
            "Example: llamacpp:gemma-4|think=off|label=gemma_off"
        ),
    )
    parser.add_argument("--max-articles", type=int, default=5, help="Global unique article cap per model.")
    parser.add_argument("--per-query-limit", type=int, default=5, help="Max articles pulled per generated query.")
    parser.add_argument("--max-queries", type=int, default=8, help="Max generated queries executed per model.")
    parser.add_argument("--databases", default="PubMed,PMC,Europe PMC", help="Comma-separated database allow-list.")
    parser.add_argument("--out", default="", help="Output directory.")
    parser.add_argument("--api-key", default="", help="API key for non-local models.")
    parser.add_argument("--planner-mode", default="staged", choices=["staged", "legacy"])
    parser.add_argument("--criteria-disabled", action="store_true", help="Disable criteria planning stage.")
    parser.add_argument("--tps-probe-tokens", type=int, default=220, help="Requested completion tokens for the TPS probe.")
    parser.add_argument("--stall-threshold", type=float, default=15.0, help="Seconds between stream events counted as a stall gap.")
    parser.add_argument("--no-preflight", action="store_true", help="Run even if the model connectivity preflight fails.")
    parser.add_argument("--start-llamacpp", action="store_true", help="Start a local llama-server for this benchmark run.")
    parser.add_argument("--llamacpp-base-url", default="http://127.0.0.1:8098", help="llama.cpp base URL used by --start-llamacpp and the benchmark.")
    parser.add_argument("--llamacpp-executable", default="", help="Path to llama-server.")
    parser.add_argument("--llamacpp-model-path", default="", help="Path to a GGUF file or Ollama blob.")
    parser.add_argument("--llamacpp-library-path", default="", help="LD_LIBRARY_PATH prefix for llama-server.")
    parser.add_argument("--llamacpp-profile", default="", choices=[""] + sorted(LLAMACPP_SERVER_PROFILES), help="Known llama.cpp server profile.")
    parser.add_argument("--llamacpp-alias", default="", help="Alias exposed by llama-server; defaults to the first llamacpp model spec.")
    parser.add_argument("--llamacpp-extra-args", default="", help="Extra llama-server args appended after the selected profile.")
    parser.add_argument("--llamacpp-log", default="", help="Path for llama-server stdout/stderr capture.")
    return parser.parse_args()


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return args.prompt.strip()
    return DEFAULT_NANOPLASTIC_DOPAMINE_PROMPT


def _first_llamacpp_model(specs) -> str:
    for spec in specs:
        if spec.model.startswith("llamacpp:"):
            return spec.model.split(":", 1)[1].strip() or "local"
    return "local"


def _llamacpp_host_port(base_url: str) -> tuple[str, str]:
    from urllib.parse import urlparse

    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    return parsed.hostname or "127.0.0.1", str(parsed.port or 8098)


def _start_llamacpp(args: argparse.Namespace, *, alias: str, log_path: Path) -> tuple[subprocess.Popen, Any] | None:
    if not args.start_llamacpp:
        return None
    if not args.llamacpp_executable or not args.llamacpp_model_path:
        raise SystemExit("--start-llamacpp requires --llamacpp-executable and --llamacpp-model-path.")
    executable = Path(args.llamacpp_executable)
    model_path = Path(args.llamacpp_model_path)
    if not executable.is_file():
        raise SystemExit(f"llama-server executable was not found: {executable}")
    if not model_path.is_file():
        raise SystemExit(f"GGUF/model file was not found: {model_path}")
    host, port = _llamacpp_host_port(args.llamacpp_base_url)
    cmd = [str(executable), "-m", str(model_path), "--host", host, "--port", port]
    if args.llamacpp_profile:
        cmd.extend(shlex.split(build_llamacpp_server_args(args.llamacpp_profile, alias=alias)))
    if args.llamacpp_extra_args.strip():
        cmd.extend(shlex.split(args.llamacpp_extra_args))
    env = os.environ.copy()
    if args.llamacpp_library_path.strip():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = args.llamacpp_library_path.strip() + ((f":{existing}") if existing else "")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8", buffering=1)
    log_handle.write("# llama-server command\n")
    log_handle.write(shlex.join(cmd) + "\n\n")
    log_handle.flush()
    process = subprocess.Popen(  # noqa: S603
        cmd,
        stdout=log_handle,
        stderr=log_handle,
        stdin=subprocess.DEVNULL,
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 90
    import httpx

    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_handle.close()
            raise SystemExit(f"llama-server exited early with code {process.returncode}.")
        try:
            with httpx.Client(base_url=args.llamacpp_base_url.rstrip("/"), timeout=2.0, follow_redirects=True) as client:
                response = client.get("/health")
                if response.status_code < 500:
                    return process, log_handle
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    process.terminate()
    log_handle.close()
    raise SystemExit(f"llama-server did not become ready in 90s. Last error: {last_error}")


async def main() -> None:
    args = parse_args()
    model_specs = parse_model_specs(args.models)
    llama_alias = args.llamacpp_alias.strip() or _first_llamacpp_model(model_specs)
    out_dir = Path(args.out) if args.out else Path("output/benchmarks") / "nanoplastic_dopamine_plan"
    llama_log_path = Path(args.llamacpp_log) if args.llamacpp_log else out_dir / "llamacpp_server.log"
    llama_started = _start_llamacpp(args, alias=llama_alias, log_path=llama_log_path)
    llama_process = llama_started[0] if llama_started else None
    llama_log_handle = llama_started[1] if llama_started else None
    config = BenchmarkConfig(
        prompt=load_prompt(args),
        models=model_specs,
        max_articles=max(1, args.max_articles),
        per_query_limit=max(1, args.per_query_limit),
        max_queries=max(1, args.max_queries),
        databases=[item.strip() for item in args.databases.split(",") if item.strip()],
        criteria_enabled=not args.criteria_disabled,
        planner_mode=args.planner_mode,
        out_dir=out_dir,
        api_key=args.api_key,
        tps_probe_tokens=max(1, args.tps_probe_tokens),
        stall_gap_threshold_s=max(1.0, args.stall_threshold),
        require_preflight=not args.no_preflight,
        llamacpp_log_path=llama_log_path if args.start_llamacpp or args.llamacpp_log else None,
    )
    settings = get_settings()
    if args.start_llamacpp or args.llamacpp_base_url:
        object.__setattr__(settings, "llamacpp_base_url", args.llamacpp_base_url.rstrip("/"))
        object.__setattr__(settings, "llamacpp_model", llama_alias)
    runner, clients = await create_default_benchmark_runner(settings=settings)
    payload: dict[str, Any] | None = None
    try:
        payload = await runner.run(config)
    finally:
        await close_clients(clients)
        if llama_log_handle is not None:
            llama_log_handle.flush()
        if llama_process is not None and llama_process.poll() is None:
            llama_process.terminate()
            try:
                llama_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                llama_process.kill()
        if llama_log_handle is not None:
            llama_log_handle.close()
    if payload is None:
        raise SystemExit(1)
    if config.llamacpp_log_path:
        payload["engine_metrics"] = parse_llamacpp_engine_metrics(config.llamacpp_log_path)
        runner.write_outputs(config.out_dir, payload)
    print(f"Wrote benchmark outputs to {config.out_dir}")
    for row in payload["comparison"]["ranking"]:
        print(
            f"{row['run_id']}: status={row.get('status')} relevant={row['relevant_hits']} "
            f"partial={row['partial_hits']} planning={row['planning_elapsed_s']}s "
            f"score={row.get('overall_score')} api_tps={row.get('api_tps')} "
            f"estimated_tps={row['tps']} max_gap={row.get('max_event_gap_s')}"
        )
    engine = payload.get("engine_metrics") or {}
    if engine:
        eval_metrics = engine.get("eval") or {}
        prompt_metrics = engine.get("prompt_eval") or {}
        print(
            "engine: "
            f"eval_tps last/avg/max={eval_metrics.get('last_tps')}/{eval_metrics.get('average_tps')}/{eval_metrics.get('max_tps')} "
            f"prompt_tps last/avg/max={prompt_metrics.get('last_tps')}/{prompt_metrics.get('average_tps')}/{prompt_metrics.get('max_tps')} "
            f"log={engine.get('log_path')}"
        )


if __name__ == "__main__":
    asyncio.run(main())
