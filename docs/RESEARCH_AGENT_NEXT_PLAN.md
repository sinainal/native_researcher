# Research Agent Next Plan

## Current Fixes In This Pass

- Persisted the current pre-change baseline to `feature/research-plan-execution-v1`.
- Added plan-level `year_start` and `year_end` support to Research Agent plans and manual plan editing.
- Enforced required screening criteria during final selection. A candidate that misses a required criterion is treated as excluded for that branch.
- Made execution fail loudly when every normalized query errors before candidate normalization.
- Added a chat-visible Search Report card after research plan execution.
- Expanded the Search Report popup with candidate status, scores, criteria, exclusion visibility, filters, and a "save checked as query" flow.

## Remaining Known Issues

- Research Agent structured plans still live primarily in assistant thread cache and frontend session state. A backend restart or cache expiry can break plan-followup continuity.
- Execution intentionally rebuilds normalized database queries from branch and shared concept plan fields. This is safer than trusting LLM raw queries, but database-specific syntax adaptation is still shallow.
- Query failure handling is stricter only when all queries fail. Partial source failures are still allowed and should be surfaced more strongly in the report.
- Screening is abstract/title-level only. Full-text/PDF evidence extraction is not yet part of this execution path.
- The Screening Agent currently scores one candidate per model call. This is reliable but slow for large runs.
- Candidate pre-screening still limits the number of candidates sent to the LLM by recency per branch, which can miss older seminal papers.

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
- keep fallback deterministic scoring for missing/invalid model outputs

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
2. Split the existing `create_research_plan` tool into deterministic backend plan schema plus separate Search Strategy and Screening Criteria tool outputs.
3. Add database-specific query normalization in backend adapters.
4. Add partial-failure warnings and retry/broaden controls in the Search Report.
5. Add a user approval step before PDF downloads.
6. Build Full-Text Extraction Agent around downloaded PDF text and page-aware citations.
