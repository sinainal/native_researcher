"""MCP server for controlling Native Researcher through safe research tools."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.native_mcp_client import NativeResearcherClient

SERVER_INFO = {"name": "native-researcher", "version": "0.1.0"}
DEFAULT_BASE_URL = "http://127.0.0.1:8002"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = os.getenv("NATIVE_RESEARCHER_MCP_TRACE", "").strip()
SEARCH_SOURCES = ["openalex", "pubmed", "europe_pmc", "pmc", "core", "arxiv"]


def _trace(event: str, payload: Any) -> None:
    if not TRACE_PATH:
        return
    try:
        with open(TRACE_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": round(time.time(), 3), "event": event, "payload": payload}, ensure_ascii=False) + "\n")
    except Exception:
        return


TOOLS: list[dict[str, Any]] = [
    {
        "name": "native_backend",
        "description": "Inspect or start the local Native Researcher backend. Does not run research by itself.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status", "start"]},
                "wait_seconds": {"type": "number", "minimum": 0},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "native_sources",
        "description": "List configured literature databases and key availability for live research.",
        "inputSchema": {
            "type": "object",
            "properties": {"response": {"type": "string", "enum": ["summary", "full"]}},
            "additionalProperties": False,
        },
    },
    {
        "name": "native_questions",
        "description": "Generate concise research clarification questions, screening criteria, and full-text extraction questions from a topic.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "objective": {"type": "string"},
                "domain": {"type": "string"},
                "target_count": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
    },
    {
        "name": "native_plan",
        "description": "Ask Native Researcher's Research Agent to create an executable research plan. This plans and asks questions; it does not execute searches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "topic": {"type": "string"},
                "objective": {"type": "string"},
                "target_count": {"type": "integer", "minimum": 1, "maximum": 200},
                "databases": {"type": "array", "items": {"type": "string"}},
                "model": {"type": "string"},
                "api_key": {"type": "string"},
                "thread_id": {"type": "string"},
                "thinking_level": {"type": "string"},
                "research_criteria_enabled": {"type": "boolean"},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "native_search",
        "description": "Run a direct live search against one database: PubMed, PMC, Europe PMC, OpenAlex, CORE, or arXiv.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "source": {"type": "string", "enum": SEARCH_SOURCES},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000},
                "year_start": {"type": "integer", "minimum": 1000, "maximum": 9999},
                "year_end": {"type": "integer", "minimum": 1000, "maximum": 9999},
                "min_cite": {"type": "integer", "minimum": 0},
                "article_type": {"type": "string"},
                "use_cache": {"type": "boolean"},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "native_project",
        "description": "List, create, read, or inspect Native Researcher projects used for persisted research runs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "create", "get", "state"]},
                "project_id": {"type": "string"},
                "name": {"type": "string"},
                "description": {"type": "string"},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "native_research",
        "description": "Execute, inspect, and summarize full Native Researcher workflows including multi-database search, screening, selection, and optional PDF/full-text processing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["execute_plan", "plan_and_execute", "list", "detail", "latest"]},
                "project_id": {"type": "string"},
                "project_name": {"type": "string"},
                "plan": {"type": "object", "additionalProperties": True},
                "topic": {"type": "string"},
                "objective": {"type": "string"},
                "target_count": {"type": "integer", "minimum": 1, "maximum": 200},
                "databases": {"type": "array", "items": {"type": "string"}},
                "screening_model": {"type": "string"},
                "screening_batch_size": {"type": "integer", "minimum": 1, "maximum": 20},
                "criteria_enabled": {"type": "boolean"},
                "pdf_extractor_enabled": {"type": "boolean"},
                "autoprocess": {"type": "boolean"},
                "pdf_scope": {"type": "string", "enum": ["selected", "selected_backup", "all"]},
                "full_text_model": {"type": "string"},
                "api_key": {"type": "string"},
                "thinking_level": {"type": "string"},
                "run_id": {"type": "string"},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "native_pdf",
        "description": "Resolve, download, or extract answers from PDFs/full text for article references.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["resolve", "download", "extract"]},
                "article": {"type": "object", "additionalProperties": True},
                "articles": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "questions": {"type": "array", "items": {"type": "string"}},
                "extraction_fields": {"type": "array", "items": {"type": "string"}},
                "model": {"type": "string"},
                "api_key": {"type": "string"},
                "thinking_level": {"type": "string"},
                "download_dir": {"type": "string"},
                "downloader_mode": {"type": "string"},
                "max_articles": {"type": "integer", "minimum": 1, "maximum": 50},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "native_browser",
        "description": "Open and control the visible local Native Researcher browser via the repo live-browser helper.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["open", "status", "snapshot", "send_agent", "close"]},
                "url": {"type": "string"},
                "message": {"type": "string"},
                "model": {"type": "string"},
                "cdp_url": {"type": "string"},
                "timeout": {"type": "number", "minimum": 1, "maximum": 600},
                "stop_after_user": {"type": "boolean"},
                "stop_delay": {"type": "number", "minimum": 0, "maximum": 30},
                "response": {"type": "string", "enum": ["summary", "full"]},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
]

GUIDE_URI = "native-researcher://guide/mcp"
GUIDE_TEXT = """# Native Researcher MCP

This MCP exposes only research-safe actions: planning, clarification questions,
database search, research execution, project inspection, and PDF/full-text
processing. It does not expose shell, git, arbitrary filesystem, or source-code
tools.

## Recommended workflow

1. `native_backend` with `status`, then `start` if needed.
2. `native_sources` to check enabled databases and missing keys.
3. `native_questions` to turn a topic into criteria and extraction questions.
4. `native_plan` to ask the Research Agent for an executable plan.
5. `native_research` with `execute_plan` or `plan_and_execute`.
6. `native_research` with `latest` or `detail` to inspect run traces.
7. `native_pdf` with `extract` for selected articles when full-text evidence is needed.
8. `native_browser` with `open` if the user should see the local UI while the agent works.

## VS Code manual setup

Create `.vscode/mcp.json` in this repository:

```json
{
  "servers": {
    "native-researcher": {
      "type": "stdio",
      "command": "bash",
      "args": [
        "-lc",
        "cd \\"/home/sina/Downloads/autoresearcher/native_researcher\\" && exec .venv/bin/python -m app.mcp_server --base-url http://127.0.0.1:8002 --auto-start"
      ]
    }
  }
}
```

For Codex CLI, add the equivalent TOML entry under `[mcp_servers.native-researcher]`.
"""


class NativeResearcherMCPServer:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        auto_start: bool = False,
        client: NativeResearcherClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.auto_start = auto_start
        self.backend_process: subprocess.Popen[Any] | None = None
        if self.auto_start and self._is_local_base_url():
            self._ensure_backend(wait_seconds=10.0)
        self.client = client or NativeResearcherClient(base_url=self.base_url, timeout=timeout)

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = str(request.get("method") or "")
        request_id = request.get("id")
        try:
            if method == "initialize":
                return self._result(
                    request_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}, "resources": {}},
                        "serverInfo": SERVER_INFO,
                    },
                )
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": TOOLS})
            if method == "tools/call":
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                return self._result(request_id, self._call_tool(str(params.get("name") or ""), params.get("arguments") or {}))
            if method == "resources/list":
                return self._result(
                    request_id,
                    {
                        "resources": [
                            {
                                "uri": GUIDE_URI,
                                "name": "Native Researcher MCP guide",
                                "description": "Workflow and setup guide for the Native Researcher MCP server.",
                                "mimeType": "text/markdown",
                            }
                        ]
                    },
                )
            if method == "resources/read":
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                if str(params.get("uri") or "") != GUIDE_URI:
                    return self._error(request_id, -32602, f"Unknown resource: {params.get('uri')}")
                return self._result(request_id, {"contents": [{"uri": GUIDE_URI, "mimeType": "text/markdown", "text": GUIDE_TEXT}]})
            return self._error(request_id, -32601, f"Unsupported MCP method: {method}")
        except Exception as exc:
            return self._error(request_id, -32000, f"{type(exc).__name__}: {exc}")

    def _call_tool(self, name: str, arguments: Any) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        if name == "native_backend":
            payload = self._backend(args)
        elif name == "native_sources":
            payload = self._sources(args)
        elif name == "native_questions":
            payload = self._questions(args)
        elif name == "native_plan":
            payload = self._plan(args)
        elif name == "native_search":
            payload = self._search(args)
        elif name == "native_project":
            payload = self._project(args)
        elif name == "native_research":
            payload = self._research(args)
        elif name == "native_pdf":
            payload = self._pdf(args)
        elif name == "native_browser":
            payload = self._browser(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return {
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}],
            "isError": not bool(payload.get("ok", False)),
        }

    def _backend(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "status")
        wait_seconds = float(args.get("wait_seconds") or 10.0)
        if action == "start":
            started = self._ensure_backend(wait_seconds=wait_seconds)
        else:
            started = False
        running = self._backend_running()
        facts = {
            "running": running,
            "started": started,
            "base_url": self.base_url,
            "local": self._is_local_base_url(),
        }
        if running:
            try:
                facts["health"] = self.client.health()
            except Exception as exc:
                facts["health_error"] = str(exc)
        return {"ok": running, "action": f"backend.{action}", "facts": facts}

    def _sources(self, args: dict[str, Any]) -> dict[str, Any]:
        response = str(args.get("response") or "summary")
        bootstrap: dict[str, Any] = {}
        try:
            bootstrap = self.client.bootstrap()
        except Exception as exc:
            return {"ok": False, "action": "sources", "error": str(exc), "facts": {"sources": SEARCH_SOURCES}}
        sources = []
        for source in SEARCH_SOURCES:
            needs_key = source == "core"
            configured = bool(bootstrap.get("core_api_key")) if source == "core" else True
            sources.append({"name": source, "configured": configured, "requires_api_key": needs_key})
        facts: dict[str, Any] = {
            "sources": sources,
            "oa_only": bool(bootstrap.get("pubmed_oa_only")),
            "pdf_fallbacks": {
                "unpaywall": bool(bootstrap.get("pdf_unpaywall_fallback_enabled")),
                "core": bool(bootstrap.get("pdf_core_fallback_enabled")),
                "arxiv": bool(bootstrap.get("pdf_arxiv_fallback_enabled")),
            },
        }
        if response == "full":
            facts["bootstrap"] = _redact_secrets(bootstrap)
        return {"ok": True, "action": "sources", "facts": facts}

    def _questions(self, args: dict[str, Any]) -> dict[str, Any]:
        topic = _required_str(args, "topic")
        objective = str(args.get("objective") or "").strip()
        target_count = _bounded_int(args.get("target_count"), default=20, minimum=1, maximum=200)
        criteria = [
            {"id": "topic_match", "question": f"Does the paper directly address {topic}?", "required": True},
            {"id": "method_match", "question": "Does the method or evidence type match the requested study design?", "required": True},
            {"id": "usable_evidence", "question": "Does the abstract or full text contain extractable evidence for the objective?", "required": True},
            {"id": "recency_or_context", "question": "Is the paper recent enough or foundational enough to keep?", "required": False},
        ]
        clarification_questions = [
            "Which databases should be active for this run?",
            "What counts as a must-include criterion versus a nice-to-have signal?",
            "Should review papers, preprints, or non-open-access records be included?",
        ]
        extraction_questions = [
            f"What exact evidence supports the main claim about {topic}?",
            "Which methods, datasets, targets, ligands, receptors, or assays were used?",
            "Are there figures, tables, interaction maps, or supplementary files that answer the objective?",
            "What limitations or uncertainty should be preserved in the final synthesis?",
        ]
        facts = {
            "topic": topic,
            "objective": objective or f"Find and rank the most relevant papers about {topic}.",
            "target_count": target_count,
            "clarification_questions": clarification_questions,
            "screening_criteria": criteria,
            "extraction_questions": extraction_questions,
            "recommended_databases": ["pubmed", "pmc", "europe_pmc", "openalex", "core", "arxiv"],
        }
        return {"ok": True, "action": "questions", "facts": facts}

    def _plan(self, args: dict[str, Any]) -> dict[str, Any]:
        response = str(args.get("response") or "summary")
        message = _plan_message(args)
        payload = {
            "message": message,
            "mode": "research_agent",
            "research_planner_mode": "staged",
            "research_criteria_enabled": bool(args.get("research_criteria_enabled", True)),
            "thinking_level": str(args.get("thinking_level") or "off"),
        }
        for optional in ("model", "api_key", "thread_id"):
            if args.get(optional):
                payload[optional] = args[optional]
        result = self.client.assistant_chat(payload)
        plan = _extract_plan(result)
        facts: dict[str, Any] = {
            "thread_id": result.get("thread_id"),
            "model": result.get("model"),
            "answer": result.get("answer", ""),
            "has_plan": bool(plan),
            "plan_summary": _plan_summary(plan) if plan else {},
        }
        if plan:
            facts["plan"] = plan
        if response == "full":
            facts["raw"] = result
        return {"ok": True, "action": "plan", "facts": facts}

    def _search(self, args: dict[str, Any]) -> dict[str, Any]:
        response = str(args.get("response") or "summary")
        payload = {
            "query": _required_str(args, "query"),
            "preferred_source": str(args.get("source") or "openalex"),
            "max_results": _bounded_int(args.get("max_results"), default=20, minimum=1, maximum=5000),
            "use_cache": bool(args.get("use_cache", True)),
        }
        for optional in ("year_start", "year_end", "min_cite", "article_type"):
            if args.get(optional) is not None:
                payload[optional] = args[optional]
        result = self.client.search(payload)
        articles = result.get("articles") if isinstance(result.get("articles"), list) else []
        facts = {
            "meta": result.get("meta", {}),
            "articles": _compact_articles(articles, full=response == "full"),
        }
        return {"ok": True, "action": "search", "facts": facts}

    def _project(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "list")
        response = str(args.get("response") or "summary")
        if action == "list":
            result = self.client.list_projects()
            projects = result.get("projects") if isinstance(result.get("projects"), list) else []
            facts = {"projects": projects if response == "full" else _compact_projects(projects)}
        elif action == "create":
            facts = self.client.create_project(
                name=str(args.get("name") or "MCP Research"),
                description=str(args.get("description") or "Created by Native Researcher MCP."),
            )
        elif action == "get":
            facts = self.client.get_project(_required_str(args, "project_id"))
        elif action == "state":
            facts = self.client.get_project_state(_required_str(args, "project_id"))
            if response != "full":
                facts = _compact_project_state(facts)
        else:
            raise ValueError(f"Unknown project action: {action}")
        return {"ok": True, "action": f"project.{action}", "facts": facts}

    def _research(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "latest")
        response = str(args.get("response") or "summary")
        if action in {"list", "latest", "detail"}:
            project_id = self._ensure_project_id(args)
            state = self.client.get_project_state(project_id)
            runs = state.get("research_runs") if isinstance(state.get("research_runs"), list) else []
            if action == "list":
                facts = {"project_id": project_id, "runs": _compact_runs(runs)}
            elif action == "latest":
                facts = {"project_id": project_id, "run": _compact_run(runs[0] if runs else {}, full=response == "full")}
            else:
                run_id = _required_str(args, "run_id")
                run = next((item for item in runs if str(item.get("id") or "") == run_id), {})
                facts = {"project_id": project_id, "run": _compact_run(run, full=response == "full")}
            return {"ok": True, "action": f"research.{action}", "facts": facts}

        project_id = self._ensure_project_id(args)
        plan = args.get("plan") if isinstance(args.get("plan"), dict) else None
        planner_result: dict[str, Any] | None = None
        if action == "plan_and_execute":
            planner_result = self._plan({**args, "response": "full"})
            plan = ((planner_result.get("facts") or {}).get("plan") if isinstance(planner_result.get("facts"), dict) else None)
            if not isinstance(plan, dict):
                plan = _basic_plan_from_args(args)
        elif action == "execute_plan":
            if plan is None:
                plan = _basic_plan_from_args(args)
        else:
            raise ValueError(f"Unknown research action: {action}")

        payload = {
            "plan": plan,
            "screening_model": args.get("screening_model") or None,
            "screening_batch_size": args.get("screening_batch_size") or None,
            "criteria_enabled": bool(args.get("criteria_enabled", True)),
            "pdf_extractor_enabled": bool(args.get("pdf_extractor_enabled", True)),
            "autoprocess": bool(args.get("autoprocess", True)),
            "pdf_scope": str(args.get("pdf_scope") or "selected_backup"),
            "full_text_model": args.get("full_text_model") or None,
            "api_key": str(args.get("api_key") or ""),
            "thinking_level": str(args.get("thinking_level") or "off"),
        }
        result = self.client.execute_research_plan(project_id, payload)
        facts: dict[str, Any] = _compact_research_response(result, full=response == "full")
        facts["project_id"] = project_id
        if planner_result and response == "full":
            facts["planner_result"] = planner_result
        return {"ok": True, "action": f"research.{action}", "facts": facts}

    def _pdf(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "")
        response = str(args.get("response") or "summary")
        if action == "resolve":
            article = args.get("article") if isinstance(args.get("article"), dict) else None
            if article is None:
                articles = args.get("articles") if isinstance(args.get("articles"), list) else []
                article = articles[0] if articles and isinstance(articles[0], dict) else None
            if article is None:
                raise ValueError("native_pdf resolve requires article or articles[0].")
            result = self.client.resolve_pdf(article)
        elif action == "download":
            result = self.client.download_pdfs(
                {
                    "articles": _articles_arg(args),
                    "download_dir": args.get("download_dir") or None,
                    "max_articles": args.get("max_articles") or None,
                    "downloader_mode": args.get("downloader_mode") or None,
                }
            )
        elif action == "extract":
            result = self.client.extract_pdf_answers(
                {
                    "articles": _articles_arg(args),
                    "questions": args.get("questions") or [],
                    "extraction_fields": args.get("extraction_fields") or [],
                    "model": args.get("model") or None,
                    "api_key": str(args.get("api_key") or ""),
                    "thinking_level": str(args.get("thinking_level") or "off"),
                    "max_articles": args.get("max_articles") or None,
                    "download_dir": args.get("download_dir") or None,
                    "downloader_mode": args.get("downloader_mode") or None,
                }
            )
        else:
            raise ValueError(f"Unknown pdf action: {action}")
        facts = result if response == "full" else _compact_pdf_result(action, result)
        return {"ok": True, "action": f"pdf.{action}", "facts": facts}

    def _browser(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args.get("action") or "status")
        response = str(args.get("response") or "summary")
        script = PROJECT_ROOT / "tools" / "live_browser.py"
        if not script.exists():
            raise RuntimeError(f"Live browser helper not found: {script}")
        command = [sys.executable, str(script)]
        if args.get("url"):
            command.extend(["--url", str(args["url"])])
        else:
            command.extend(["--url", f"{self.base_url}/native_researcher"])
        if args.get("cdp_url"):
            command.extend(["--cdp-url", str(args["cdp_url"])])
        if args.get("model"):
            command.extend(["--model", str(args["model"])])
        if args.get("timeout"):
            command.extend(["--timeout", str(float(args["timeout"]))])
        if action == "send_agent":
            command.append("send-agent")
            command.append(_required_str(args, "message"))
            if bool(args.get("stop_after_user", False)):
                command.append("--stop-after-user")
            if args.get("stop_delay") is not None:
                command.extend(["--stop-delay", str(float(args["stop_delay"]))])
        else:
            command.append(action.replace("_", "-"))
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=float(args.get("timeout") or 60.0) + 15.0,
            check=False,
        )
        if completed.returncode != 0:
            return {
                "ok": False,
                "action": f"browser.{action}",
                "error": (completed.stderr or completed.stdout or "").strip()[:2000],
                "facts": {"returncode": completed.returncode},
            }
        payload = _loads_json_or_text(completed.stdout)
        facts = payload if response == "full" or not isinstance(payload, dict) else _compact_browser_payload(payload)
        return {"ok": True, "action": f"browser.{action}", "facts": facts}

    def _ensure_project_id(self, args: dict[str, Any]) -> str:
        if args.get("project_id"):
            return str(args["project_id"])
        projects_payload = self.client.list_projects()
        projects = projects_payload.get("projects") if isinstance(projects_payload.get("projects"), list) else []
        if projects:
            return str(projects[0].get("id") or "")
        created = self.client.create_project(
            name=str(args.get("project_name") or "MCP Research"),
            description="Created automatically by Native Researcher MCP.",
        )
        return str(created.get("id") or "")

    def _is_local_base_url(self) -> bool:
        parsed = urlparse(self.base_url)
        return parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _backend_running(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/app/bootstrap", timeout=1.5, follow_redirects=True)
            return response.status_code == 200 and isinstance(response.json(), dict)
        except Exception:
            return False

    def _ensure_backend(self, *, wait_seconds: float) -> bool:
        if self._backend_running():
            return False
        if not self._is_local_base_url():
            raise RuntimeError("Refusing to start a non-local Native Researcher backend.")
        parsed = urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        port = str(parsed.port or 8000)
        env = os.environ.copy()
        env["HOST"] = host
        env["PORT"] = port
        log_path = PROJECT_ROOT / "logs" / "native_researcher_mcp_backend.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "ab") as log_fh:
            self.backend_process = subprocess.Popen(
                ["bash", "start.sh"],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if self._backend_running():
                return True
            time.sleep(0.25)
        return self._backend_running()

    @staticmethod
    def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _required_str(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _plan_message(args: dict[str, Any]) -> str:
    if args.get("message"):
        return str(args["message"])
    topic = str(args.get("topic") or "").strip()
    objective = str(args.get("objective") or "").strip()
    target_count = _bounded_int(args.get("target_count"), default=20, minimum=1, maximum=200)
    databases = [str(item) for item in args.get("databases") or SEARCH_SOURCES]
    if not topic and not objective:
        raise ValueError("native_plan requires message, topic, or objective.")
    return (
        "Create an executable Native Researcher plan. "
        f"Topic: {topic or objective}. "
        f"Objective: {objective or 'Find, screen, and rank the most relevant literature.'} "
        f"Target papers per branch: {target_count}. "
        f"Active databases: {', '.join(databases)}. "
        "Return comprehensive database-specific queries, screening criteria, exclusions, and PDF/full-text extraction questions."
    )


def _extract_plan(result: dict[str, Any]) -> dict[str, Any] | None:
    actions = result.get("executed_actions") if isinstance(result.get("executed_actions"), list) else []
    for action in actions:
        if not isinstance(action, dict):
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        plan = details.get("plan")
        if isinstance(plan, dict):
            return plan
    return None


def _basic_plan_from_args(args: dict[str, Any]) -> dict[str, Any]:
    topic = str(args.get("topic") or args.get("objective") or "Untitled research topic").strip()
    objective = str(args.get("objective") or f"Find and rank relevant papers about {topic}.").strip()
    target_count = _bounded_int(args.get("target_count"), default=20, minimum=1, maximum=200)
    databases = [str(item) for item in args.get("databases") or ["pubmed", "pmc", "europe_pmc", "openalex"]]
    query = topic if topic else objective
    return {
        "topic": topic,
        "objective": objective,
        "target_count": target_count,
        "target_count_per_branch": target_count,
        "databases": databases,
        "active_databases": databases,
        "search_branches": [{"id": "main", "label": topic[:80] or "Main topic", "query": query, "target_count": target_count}],
        "search_queries": [
            {"database": database, "source": database, "branch_id": "main", "branch_label": topic[:80] or "Main topic", "query": query, "candidate_limit": target_count * 2}
            for database in databases
        ],
        "screening_criteria": [
            {"id": "topic_match", "label": "Topic match", "description": f"Directly addresses {topic}.", "required": True, "weight": 1.0},
            {"id": "usable_evidence", "label": "Usable evidence", "description": "Contains extractable evidence for the research objective.", "required": True, "weight": 1.0},
        ],
        "exclusion_criteria": [],
        "candidate_budget": {"per_database": target_count * 2, "rule": "Fetch twice the target count per database."},
    }


def _plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    queries = plan.get("search_queries") if isinstance(plan.get("search_queries"), list) else []
    criteria = plan.get("screening_criteria") if isinstance(plan.get("screening_criteria"), list) else []
    return {
        "topic": plan.get("topic") or "",
        "objective": plan.get("objective") or "",
        "databases": plan.get("active_databases") or plan.get("databases") or [],
        "query_count": len(queries),
        "criteria_count": len(criteria),
        "target_count": plan.get("target_count") or plan.get("target_count_per_branch"),
    }


def _compact_articles(articles: list[Any], *, full: bool = False) -> list[dict[str, Any]]:
    if full:
        return [item for item in articles if isinstance(item, dict)]
    compact = []
    for item in articles[:50]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "id": item.get("id"),
                "source": item.get("source_name"),
                "title": item.get("title"),
                "year": item.get("year"),
                "journal": item.get("journal"),
                "doi": item.get("doi"),
                "pmid": item.get("pmid"),
                "pmc_id": item.get("pmc_id"),
                "source_record_id": item.get("source_record_id"),
                "score": (item.get("research_meta") or {}).get("score") if isinstance(item.get("research_meta"), dict) else None,
                "abstract_snippet": str(item.get("abstract") or "")[:500],
                "oa_pdf_url": item.get("oa_pdf_url"),
                "landing_page_url": item.get("landing_page_url"),
            }
        )
    return compact


def _compact_projects(projects: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "updated_at": item.get("updated_at"),
            "pdf_count": item.get("pdf_count"),
            "note_count": item.get("note_count"),
        }
        for item in projects
        if isinstance(item, dict)
    ]


def _compact_project_state(state: dict[str, Any]) -> dict[str, Any]:
    runs = state.get("research_runs") if isinstance(state.get("research_runs"), list) else []
    return {
        "id": state.get("id"),
        "name": state.get("name"),
        "research_run_count": len(runs),
        "latest_run": _compact_run(runs[0] if runs else {}),
    }


def _compact_runs(runs: list[Any]) -> list[dict[str, Any]]:
    return [_compact_run(run) for run in runs[:20] if isinstance(run, dict)]


def _compact_run(run: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    if full:
        return run
    meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
    return {
        "id": run.get("id"),
        "status": run.get("status"),
        "created_at": run.get("created_at"),
        "topic": run.get("topic"),
        "objective": run.get("objective"),
        "candidate_count": meta.get("candidate_count"),
        "selected_count": meta.get("selected_count"),
        "screening_status": meta.get("screening_status"),
        "run_status": meta.get("run_status"),
        "sources_used": sorted({item.get("source") for item in run.get("executed_queries", []) if isinstance(item, dict) and item.get("source")}),
    }


def _compact_research_response(result: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    if full:
        return result
    return {
        "meta": result.get("meta", {}),
        "run": _compact_run(result.get("run_trace") if isinstance(result.get("run_trace"), dict) else {}),
        "articles": _compact_articles(result.get("articles") if isinstance(result.get("articles"), list) else []),
        "candidate_count": len(result.get("candidate_articles") if isinstance(result.get("candidate_articles"), list) else []),
    }


def _articles_arg(args: dict[str, Any]) -> list[dict[str, Any]]:
    articles = args.get("articles") if isinstance(args.get("articles"), list) else []
    if articles:
        return [item for item in articles if isinstance(item, dict)]
    article = args.get("article") if isinstance(args.get("article"), dict) else None
    if article:
        return [article]
    raise ValueError("native_pdf requires article or articles.")


def _compact_pdf_result(action: str, result: dict[str, Any]) -> dict[str, Any]:
    if action == "resolve":
        return {
            "candidate_count": len(result.get("candidates") if isinstance(result.get("candidates"), list) else []),
            "candidates": result.get("candidates", [])[:10],
            "cache_hit": result.get("cache_hit"),
        }
    if action == "download":
        return {
            "total": result.get("total"),
            "success_count": result.get("success_count"),
            "failed_count": result.get("failed_count"),
            "results": result.get("results", [])[:20],
        }
    return {
        "total": result.get("total"),
        "success_count": result.get("success_count"),
        "failed_count": result.get("failed_count"),
        "questions": result.get("questions", []),
        "results": result.get("results", [])[:10],
        "meta": result.get("meta", {}),
    }


def _loads_json_or_text(text: str) -> dict[str, Any] | str:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        payload = json.loads(stripped)
        return payload if isinstance(payload, dict) else {"value": payload}
    except json.JSONDecodeError:
        return stripped


def _compact_browser_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compact = {
        "ok": payload.get("ok"),
        "status": payload.get("status"),
        "pid": payload.get("pid"),
        "pid_alive": payload.get("pid_alive"),
        "cdp_ready": payload.get("cdp_ready"),
        "cdp_url": payload.get("cdp_url"),
        "url": payload.get("url"),
        "title": payload.get("title"),
        "assistantMode": payload.get("assistantMode"),
        "model": payload.get("model"),
        "planCards": payload.get("planCards"),
        "queryHistoryItems": payload.get("queryHistoryItems"),
        "tableRows": payload.get("tableRows"),
        "snapshot_file": payload.get("snapshot_file"),
    }
    messages = payload.get("messages") if isinstance(payload.get("messages"), list) else []
    if messages:
        compact["messages"] = messages[-5:]
    return {key: value for key, value in compact.items() if value is not None}


def _redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    for key in list(redacted):
        if "key" in key.lower() or "token" in key.lower():
            redacted[key] = "***" if redacted[key] else ""
    return redacted


def _read_message(stream: Any) -> tuple[dict[str, Any], str] | None:
    first = stream.buffer.readline()
    if not first:
        return None
    if first.startswith(b"Content-Length:"):
        length = int(first.decode("ascii").split(":", 1)[1].strip())
        while True:
            line = stream.buffer.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        body = stream.buffer.read(length)
        return json.loads(body.decode("utf-8")), "lsp"
    return json.loads(first.decode("utf-8")), "ndjson"


def _write_message(stream: Any, message: dict[str, Any], *, framing: str) -> None:
    raw = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if framing == "lsp":
        stream.buffer.write(f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii") + raw)
    else:
        stream.buffer.write(raw + b"\n")
    stream.buffer.flush()


def serve(server: NativeResearcherMCPServer) -> None:
    framing = "ndjson"
    while True:
        parsed = _read_message(sys.stdin)
        if parsed is None:
            break
        request, framing = parsed
        _trace("request", request)
        response = server.handle(request)
        if response is None:
            continue
        _trace("response", response)
        _write_message(sys.stdout, response, framing=framing)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Native Researcher MCP server")
    parser.add_argument("--base-url", default=os.getenv("NATIVE_RESEARCHER_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("NATIVE_RESEARCHER_MCP_TIMEOUT", "120")))
    parser.add_argument("--auto-start", action="store_true", default=os.getenv("NATIVE_RESEARCHER_MCP_AUTO_START", "") == "1")
    args = parser.parse_args(argv)
    server = NativeResearcherMCPServer(base_url=args.base_url, timeout=args.timeout, auto_start=args.auto_start)
    serve(server)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
