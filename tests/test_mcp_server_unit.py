from __future__ import annotations

import json
import subprocess
from io import BytesIO

from app import mcp_server


class FakeNativeClient:
    def __init__(self) -> None:
        self.last_search_payload = None
        self.last_execution_payload = None

    def health(self):
        return {"status": "ok"}

    def bootstrap(self):
        return {
            "core_api_key": "",
            "pubmed_oa_only": True,
            "pdf_unpaywall_fallback_enabled": True,
            "pdf_core_fallback_enabled": False,
            "pdf_arxiv_fallback_enabled": True,
        }

    def list_projects(self):
        return {"projects": [{"id": "proj_1", "name": "MCP Research", "updated_at": "now", "pdf_count": 0, "note_count": 0}]}

    def create_project(self, *, name: str, description: str = ""):
        return {"id": "proj_new", "name": name, "description": description}

    def get_project(self, project_id: str):
        return {"id": project_id, "name": "MCP Research"}

    def get_project_state(self, project_id: str):
        return {
            "id": project_id,
            "name": "MCP Research",
            "research_runs": [
                {
                    "id": "research_run_abc",
                    "status": "completed",
                    "created_at": "2026-06-06T00:00:00+00:00",
                    "topic": "dopamine receptor docking",
                    "objective": "find docking papers",
                    "executed_queries": [{"source": "pubmed"}, {"source": "pmc"}],
                    "meta": {
                        "candidate_count": 10,
                        "selected_count": 3,
                        "screening_status": "completed",
                        "run_status": "completed",
                    },
                }
            ],
        }

    def search(self, payload):
        self.last_search_payload = payload
        return {
            "meta": {"fetched_results": 1, "primary_source": payload["preferred_source"]},
            "articles": [
                {
                    "id": 1,
                    "source_name": payload["preferred_source"],
                    "title": "A useful paper",
                    "abstract": "Long abstract",
                    "year": "2024",
                    "doi": "10.1/example",
                    "pmid": "123",
                }
            ],
        }

    def assistant_chat(self, payload):
        return {
            "thread_id": "thread_1",
            "answer": "Plan ready",
            "model": payload.get("model") or "test-model",
            "executed_actions": [
                {
                    "name": "create_research_plan",
                    "details": {
                        "plan": {
                            "topic": "dopamine receptor docking",
                            "objective": "find docking papers",
                            "active_databases": ["pubmed"],
                            "search_queries": [{"database": "pubmed", "query": "dopamine receptor docking"}],
                            "screening_criteria": [{"id": "docking"}],
                            "target_count": 2,
                        }
                    },
                }
            ],
        }

    def execute_research_plan(self, project_id: str, payload):
        self.last_execution_payload = payload
        return {
            "meta": {"fetched_results": 1},
            "run_trace": {
                "id": "research_run_new",
                "status": "completed",
                "topic": payload["plan"]["topic"],
                "meta": {"candidate_count": 1, "selected_count": 1},
            },
            "articles": [{"id": 1, "title": "Selected", "pmid": "123", "abstract": ""}],
            "candidate_articles": [{"id": 1, "title": "Selected", "pmid": "123", "abstract": ""}],
        }

    def resolve_pdf(self, article):
        return {"article": article, "candidates": [{"source": "oa", "url": "https://example.org/a.pdf"}], "cache_hit": False}

    def download_pdfs(self, payload):
        return {"total": 1, "success_count": 1, "failed_count": 0, "results": [{"success": True}]}

    def extract_pdf_answers(self, payload):
        return {"total": 1, "success_count": 1, "failed_count": 0, "questions": payload["questions"], "results": []}


def make_server() -> mcp_server.NativeResearcherMCPServer:
    server = mcp_server.NativeResearcherMCPServer(base_url="http://native.local", client=FakeNativeClient())
    return server


def tool_payload(response):
    assert response is not None
    assert response["result"]["isError"] is False
    return json.loads(response["result"]["content"][0]["text"])


def call_tool(server, name, arguments=None):
    return server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )


def test_mcp_lists_research_tools() -> None:
    server = make_server()
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert response is not None
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == [
        "native_backend",
        "native_sources",
        "native_questions",
        "native_plan",
        "native_search",
        "native_project",
        "native_research",
        "native_pdf",
        "native_browser",
    ]


def test_initialize_includes_cross_tool_instructions() -> None:
    response = make_server().handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert response is not None
    instructions = response["result"]["instructions"]
    assert "native_sources" in instructions
    assert "unscreened" in instructions


def test_trace_recursively_redacts_secrets(tmp_path, monkeypatch) -> None:
    trace_path = tmp_path / "mcp.jsonl"
    monkeypatch.setattr(mcp_server, "TRACE_PATH", str(trace_path))

    mcp_server._trace(
        "request",
        {
            "params": {
                "arguments": {
                    "api_key": "top-secret",
                    "nested": {"access_token": "also-secret"},
                    "topic": "dopamine adsorption",
                }
            }
        },
    )

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    arguments = payload["payload"]["params"]["arguments"]
    assert arguments["api_key"] == "***"
    assert arguments["nested"]["access_token"] == "***"
    assert arguments["topic"] == "dopamine adsorption"


def test_questions_generate_criteria_and_pdf_questions() -> None:
    payload = tool_payload(call_tool(make_server(), "native_questions", {"topic": "dopamine receptor docking"}))
    assert payload["facts"]["screening_criteria"]
    assert payload["facts"]["extraction_questions"]
    assert "pubmed" in payload["facts"]["recommended_databases"]


def test_sources_report_configured_databases() -> None:
    payload = tool_payload(call_tool(make_server(), "native_sources", {}))
    sources = {item["name"]: item for item in payload["facts"]["sources"]}
    assert sources["pubmed"]["configured"] is True
    assert sources["core"]["configured"] is False
    assert payload["facts"]["pdf_fallbacks"]["arxiv"] is True


def test_search_passes_source_and_compacts_articles() -> None:
    server = make_server()
    payload = tool_payload(
        call_tool(server, "native_search", {"query": "dopamine receptor docking", "source": "pubmed", "max_results": 1})
    )
    assert server.client.last_search_payload["preferred_source"] == "pubmed"
    assert payload["facts"]["articles"][0]["title"] == "A useful paper"


def test_search_passes_broad_discovery_and_relevance_options() -> None:
    server = make_server()
    groups = [["dopamine", "catecholamine"], ["polystyrene"], ["adsorption", "binding"]]
    tool_payload(
        call_tool(
            server,
            "native_search",
            {
                "query": "dopamine polystyrene adsorption",
                "oa_only": False,
                "relevance_groups": groups,
                "require_all_relevance_groups": True,
                "require_relevance_cooccurrence": True,
                "relevance_exclude_terms": ["polydopamine", "sensor"],
            },
        )
    )
    assert server.client.last_search_payload["oa_only"] is False
    assert server.client.last_search_payload["relevance_groups"] == groups
    assert server.client.last_search_payload["require_all_relevance_groups"] is True
    assert server.client.last_search_payload["require_relevance_cooccurrence"] is True
    assert server.client.last_search_payload["relevance_exclude_terms"] == ["polydopamine", "sensor"]


def test_plan_extracts_executable_plan() -> None:
    payload = tool_payload(call_tool(make_server(), "native_plan", {"topic": "dopamine receptor docking"}))
    assert payload["facts"]["has_plan"] is True
    assert payload["facts"]["plan"]["active_databases"] == ["pubmed"]


def test_research_execute_plan_uses_existing_project() -> None:
    server = make_server()
    payload = tool_payload(
        call_tool(
            server,
            "native_research",
            {
                "action": "execute_plan",
                "plan": {"topic": "dopamine receptor docking", "search_queries": []},
                "pdf_extractor_enabled": False,
            },
        )
    )
    assert server.client.last_execution_payload["pdf_extractor_enabled"] is False
    assert payload["facts"]["project_id"] == "proj_1"
    assert payload["facts"]["run"]["id"] == "research_run_new"


def test_research_latest_reads_project_state() -> None:
    payload = tool_payload(call_tool(make_server(), "native_research", {"action": "latest"}))
    assert payload["facts"]["run"]["id"] == "research_run_abc"
    assert payload["facts"]["run"]["sources_used"] == ["pmc", "pubmed"]


def test_pdf_extract_calls_pdf_pipeline() -> None:
    payload = tool_payload(
        call_tool(
            make_server(),
            "native_pdf",
            {
                "action": "extract",
                "article": {"title": "A useful paper", "pmid": "123"},
                "questions": ["Was docking performed?"],
            },
        )
    )
    assert payload["facts"]["success_count"] == 1
    assert payload["facts"]["questions"] == ["Was docking performed?"]


def test_browser_tool_delegates_to_live_browser(monkeypatch) -> None:
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"ok": True, "status": "opened", "cdp_url": "http://127.0.0.1:9223"}),
            stderr="",
        )

    monkeypatch.setattr(mcp_server.subprocess, "run", fake_run)
    payload = tool_payload(call_tool(make_server(), "native_browser", {"action": "open"}))

    assert payload["facts"]["status"] == "opened"
    assert calls[0][-1] == "open"
    assert "tools/live_browser.py" in calls[0][1]


def test_mcp_exposes_setup_guide_resource() -> None:
    server = make_server()
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "resources/list"})
    assert listed is not None
    uri = listed["result"]["resources"][0]["uri"]
    read = server.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/read", "params": {"uri": uri}})
    assert read is not None
    assert ".vscode/mcp.json" in read["result"]["contents"][0]["text"]


def test_stdio_supports_ndjson_framing() -> None:
    request = {"jsonrpc": "2.0", "id": 7, "method": "ping"}

    class Stream:
        def __init__(self, initial: bytes = b"") -> None:
            self.buffer = BytesIO(initial)

    incoming = Stream((json.dumps(request) + "\n").encode("utf-8"))
    parsed = mcp_server._read_message(incoming)
    assert parsed == (request, "ndjson")

    outgoing = Stream()
    mcp_server._write_message(outgoing, {"jsonrpc": "2.0", "id": 7, "result": {}}, framing="ndjson")
    outgoing.buffer.seek(0)
    assert json.loads(outgoing.buffer.readline().decode("utf-8"))["id"] == 7
