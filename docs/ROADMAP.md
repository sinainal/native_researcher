# Researcher_2 Roadmap

## Current State

- `fast mode` is working end-to-end.
- PubMed search, detail reading, streaming UI, tool trace, and assistant logging are in place.
- `agent mode` is still a placeholder and does not yet run a real multi-step research workflow.

## Long-Term Goal

Build a two-mode research assistant:

- `fast mode`: quick, low-tool-count retrieval and answer generation.
- `agent mode`: deeper multi-step literature research with planning, query refinement, evidence verification, and stronger summarization.

## Planned Work

### 1. Batch Abstract Analyzer

Build the reusable abstract screening and extraction engine that agent mode will depend on.

Core behavior:

- split articles into token-aware chunks, typically around 20-30 articles
- run fast structured LLM analysis on each chunk
- return strict JSON in an agent-provided schema
- merge chunk outputs
- surface the most critical candidate articles for deeper reading

This becomes the core screening engine for agent mode.

### 2. Real Agent Mode

Implement a real agentic workflow on top of the batch analyzer:

- planner
- PubMed query planner
- candidate-query tester
- selector
- verifier

Target behavior:

- generate 2-3 candidate PubMed queries
- test them with small result windows
- choose the best query
- run the batch analyzer on large candidate sets
- read relevant article details
- verify final claims before answering

### 3. Fast Mode Quality Improvements

Improve reliability without making fast mode heavy:

- refine PubMed query prompting further
- improve when `get_article_details` is mandatory
- optionally add lightweight reranking for top results
- keep tool use bounded and fast

### 4. Trace / Debug UX

Improve observability:

- dedicated AI trace panel
- clearer separation between thinking, tool calls, tool results, and final answer
- better log browsing from saved assistant history

### 5. PDF / Full-Text Pipeline

Extend the assistant beyond abstracts:

- PDF-aware evidence extraction
- full-text reading for agent mode
- citeable verification against article text

### 6. Smarter Ranking

Optional later-stage work:

- citation-aware reranking
- recency-aware scoring
- hybrid relevance scoring on top PubMed results

### 7. Parallel Research Flows

Only after agent mode is stable:

- parallel candidate query testing
- parallel chunk analysis
- parallel verifier side passes where useful

## Recommended Priority Order

### Priority 1

Batch abstract analyzer

Reason:

- this is the most valuable reusable research engine from the old system
- real agent mode depends on this screening layer

### Priority 2

Real `agent mode`

Reason:

- this is the largest missing product capability
- it will be much easier to implement cleanly once the analyzer exists

### Priority 3

Fast mode quality improvements

Reason:

- fast mode is already usable
- improvements here are valuable, but not as important as unlocking real agent behavior

### Priority 4

Trace / debug UX

Reason:

- useful for trust and debugging
- already partially solved with logging, so it is not the biggest blocker

### Priority 5

PDF / full-text pipeline

Reason:

- high value, but should come after agent mode orchestration is stable

### Priority 6

Smarter ranking

Reason:

- useful optimization, not core functionality

### Priority 7

Parallel research flows

Reason:

- adds complexity
- should come only after the single-path agent flow is stable

## Suggested Next Execution Order

1. implement the batch abstract analyzer as a standalone service/tool
2. define the real `agent mode` state machine around that analyzer
3. wire the analyzer into agent mode
4. add verifier logic for article-detail re-reading before final answer
5. improve trace UI for agent runs
6. add PDF/full-text support
