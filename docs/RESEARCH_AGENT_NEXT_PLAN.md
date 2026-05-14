# Research Agent Next Plan

## Current Fixes In This Pass

- Persisted the current pre-change baseline to `feature/research-plan-execution-v1`.
- Added plan-level `year_start` and `year_end` support to Research Agent plans and manual plan editing.
- Enforced required screening criteria during final selection. A candidate that misses a required criterion is treated as excluded for that branch.
- Made execution fail loudly when every normalized query errors before candidate normalization.
- Added a chat-visible Search Report card after research plan execution.
- Expanded the Search Report popup with candidate status, scores, criteria, exclusion visibility, filters, and a "save checked as query" flow.
- Fixed score normalization when the Screening Agent returns criterion labels or alternate score keys instead of exact criterion IDs.
- Added report plots for branch coverage and score distribution, and tightened report layout for desktop and mobile popups.
- Added `search_strategy`, `criteria_strategy`, `extraction_strategy`, and ordered `planner_stages` metadata to Research Agent plans.
- Added a `/pdf/extract` endpoint that downloads PDF/XML artifacts, extracts text, and answers extraction questions from the downloaded full text.
- Changed the first local Research Agent planning turn from one planner tool call to three visible stage calls: `create_search_plan`, `create_criteria_plan`, and `create_extraction_plan`, then backend merge into `create_research_plan`.
- Added screening recovery when a local model returns valid JSON text instead of the `screen_research_candidates` tool call. If the model returns neither a valid tool call nor parseable JSON, the backend sends explicit retry feedback; after retries fail, execution stops with an error instead of silently using deterministic scoring.
- Added a Research Planner Flow setting so new local Research Agent plans can use either staged planner agents or the legacy single-block planner.
- Made PDF extraction questions editable in plan details, with explicit `exact_text` and `factual_answer` answer formats.

## Remaining Known Issues

- Research Agent structured plans still live primarily in assistant thread cache and frontend session state. A backend restart or cache expiry can break plan-followup continuity.
- Execution intentionally rebuilds normalized database queries from branch and shared concept plan fields. This is safer than trusting LLM raw queries, but database-specific syntax adaptation is still shallow.
- Query failure handling is stricter only when all queries fail. Partial source failures are still allowed and should be surfaced more strongly in the report.
- Screening execution is still abstract/title-level. Full-text/PDF extraction now exists as a backend endpoint, but is not yet wired into the main research execution UI as an automatic next stage.
- The Screening Agent currently scores one candidate per model call. This is reliable but slow for large runs.
- Candidate pre-screening still limits the number of candidates sent to the LLM by recency per branch, which can miss older seminal papers.
- The three-stage planner split is implemented for the first local Research Agent planning turn. Existing-plan edits still use the legacy single `create_research_plan` path until edit semantics are redesigned. The legacy first-plan path remains available from settings.

## Proposed Three-Agent Architecture

### 1. Search Strategy Agent

Owns scope, sources, year filters, branches, and database-specific query intent.

Outputs:
- topic and objective
- `year_start` / `year_end`
- active databases
- search branches
- shared query concepts
- database-specific query guidance, not final trusted query strings
- expansion policy if first-pass recall is weak

Backend responsibility:
- normalize queries per database
- enforce max query count and candidate budgets
- record query failures and coverage gaps

### 2. Screening Criteria Agent

Owns abstract-level inclusion/exclusion criteria and scoring rubric.

Outputs:
- required criteria
- weighted optional criteria
- exclusion criteria
- score thresholds
- rationale/evidence JSON shape

Backend responsibility:
- enforce required criteria
- compute final score deterministically from returned criterion scores
- stop with a visible error when the screening model cannot produce a valid tool call or parseable JSON after retry

### 3. Full-Text Extraction Agent

Runs only after selected/backup candidate approval and PDF retrieval.

Outputs:
- structured extraction questions
- evidence fields to capture from PDFs
- expected answer/report format
- uncertainty flags

Backend responsibility:
- download/resolve PDFs
- chunk and index full text
- run extraction against exact PDF text only
- attach quote/page evidence
- produce exportable evidence tables

## Suggested Next Implementation Order

1. Persist `research_plan` into project state as a first-class object keyed by run/session.
2. Extend the three-stage planner split to plan edits/revisions once edit semantics are redesigned.
3. Add database-specific query normalization in backend adapters.
4. Add partial-failure warnings and retry/broaden controls in the Search Report.
5. Add a user approval step before PDF downloads.
6. Wire `/pdf/extract` into the research execution flow after selected/backup candidate approval, with page-aware evidence tables in the report.
