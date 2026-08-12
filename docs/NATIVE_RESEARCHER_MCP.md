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

## OA-first and broad discovery modes

The installation-wide `pubmed_oa_only` setting remains the default. This keeps
ordinary searches focused on records whose full text is more likely to be
downloadable. Do not change that runtime default for a one-off broad search.

Use a per-call override instead:

```json
{
  "query": "dopamine polystyrene adsorption",
  "source": "openalex",
  "oa_only": false
}
```

Omit `oa_only` to preserve the configured default.

## Precision workflow

Database relevance ranking is candidate retrieval, not a final relatedness
decision. For a high-precision search:

1. Retrieve broadly with several short, source-specific query branches.
2. Add `relevance_groups`; aliases within one group are OR alternatives.
3. Set `require_all_relevance_groups=true`.
4. Set `require_relevance_cooccurrence=true` so every concept must occur in the
   same title, sentence, or metadata passage.
5. Add topic-specific `relevance_exclude_terms` such as `polydopamine`,
   `sensor`, or `coating` when those are outside scope.
6. Run `native_research` with an explicit relation-level inclusion question.

Example prefilter:

```json
{
  "query": "dopamine polystyrene adsorption",
  "source": "openalex",
  "oa_only": false,
  "relevance_groups": [
    ["dopamine", "catecholamine"],
    ["polystyrene", "PS"],
    ["adsorption", "binding"]
  ],
  "require_all_relevance_groups": true,
  "require_relevance_cooccurrence": true,
  "relevance_exclude_terms": ["polydopamine", "sensor", "coating"]
}
```

Lexical co-occurrence cannot always distinguish interaction direction. For
example, “dopamine-modified PS adsorbs a dye” contains the same keywords as
“dopamine adsorbs to PS” but represents a different claim. The final screening
criterion must state the exact subject–relation–object claim, material
restrictions, and exclusions.

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
