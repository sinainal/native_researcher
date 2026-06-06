# Native Researcher MCP

Native Researcher now has a local MCP server for research-safe control from
Codex, VS Code, or any stdio MCP client.

The MCP exposes high-level research actions only:

- `native_backend`: check or start the local FastAPI backend
- `native_sources`: inspect configured literature sources
- `native_questions`: generate clarification questions, screening criteria, and full-text questions
- `native_plan`: ask the Research Agent to create an executable plan
- `native_search`: run direct live database searches
- `native_project`: list, create, read, or inspect projects
- `native_research`: execute plans, plan-and-execute, and inspect run traces
- `native_pdf`: resolve, download, or extract answers from PDFs/full text
- `native_browser`: open, inspect, snapshot, or send a Research Agent message in a visible local browser

It does not expose shell, git, arbitrary filesystem, or source-code tools.

## Agent-side setup

Codex can connect with this config:

```toml
[mcp_servers.native-researcher]
command = "bash"
args = ["-lc", 'cd "/home/sina/Downloads/autoresearcher/native_researcher" && exec .venv/bin/python -m app.mcp_server --base-url http://127.0.0.1:8002 --auto-start']
```

The `--auto-start` flag starts the Native Researcher backend through `start.sh`
when the MCP sees that `127.0.0.1:8002` is down. Port `8002` is used to avoid
colliding with DockUP or other local tools that often occupy `8000`.

## VS Code setup

This repository includes `.vscode/mcp.json`:

```json
{
  "servers": {
    "native-researcher": {
      "type": "stdio",
      "command": "bash",
      "args": [
        "-lc",
        "cd \"/home/sina/Downloads/autoresearcher/native_researcher\" && exec .venv/bin/python -m app.mcp_server --base-url http://127.0.0.1:8002 --auto-start"
      ]
    }
  }
}
```

Open the repository folder in VS Code and enable the `native-researcher` MCP
server from the MCP panel.

## Suggested workflow

1. `native_backend {"action":"status"}`.
2. `native_backend {"action":"start"}` if the backend is not running.
3. `native_sources {}` to confirm database availability.
4. `native_questions {"topic":"..."}` to form criteria and extraction questions.
5. `native_plan {"topic":"...","target_count":20}` for a model-generated executable plan.
6. `native_research {"action":"execute_plan","plan":{...}}`.
7. `native_research {"action":"latest","response":"full"}` for run details.
8. `native_pdf {"action":"extract","articles":[...],"questions":[...]}` for full-text evidence.

## Visible browser

Use `native_browser` when the user should see Native Researcher operating on
the local desktop:

```json
{"action":"open"}
```

The tool delegates to `tools/live_browser.py`, opens a headed Chromium window,
and reuses Chrome DevTools Protocol at `http://127.0.0.1:9223`. It can also run:

- `{"action":"status"}`
- `{"action":"snapshot"}`
- `{"action":"send_agent","message":"Create a research plan for ..."}`
- `{"action":"close"}`
