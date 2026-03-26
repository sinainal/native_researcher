# Batch Analyzer Report

## What The Batch Analyzer Is

The batch analyzer is not the final answering agent.

It is a reusable screening and extraction engine that sits under `agent mode`.
Its job is to take a large article set, read titles + abstracts in chunks, and return structured JSON that helps the agent decide which papers deserve deeper inspection.

This means the agent does not need to read 200 abstracts one by one.
Instead:

1. the agent defines the research question and desired output format
2. the batch analyzer processes the article pool in chunks
3. the analyzer returns per-article structured results
4. the agent reads those results
5. the agent opens only the most critical abstracts in detail
6. later, the agent can escalate to PDF / full text

## Target Role In The System

The batch analyzer should become the first large-scale evidence triage layer for `agent mode`.

It should support tasks such as:

- relevance screening
- question answering potential screening
- structured extraction from abstracts
- claim / mechanism presence detection
- early evidence ranking before detailed reading

## Core Workflow

Example with `200` articles:

1. agent receives a user question
2. agent collects candidate articles from PubMed or catalog
3. batch analyzer splits the `200` articles into `25`-article chunks
4. each chunk is sent to a fast model with a strict JSON schema
5. each article gets a structured result
6. chunk outputs are merged
7. top candidate papers are selected
8. agent reads the most critical abstracts directly
9. later stage can fetch PDF / full text for final verification

Important point:

The chunk size should be token-aware, not hard-coded forever.
`25` is a good working default, but the planner should still respect token budget.

## Required Input Contract

The agent should provide:

- `question`
- `articles`
- `analysis_mode`
- `output_schema`
- `top_k`
- `token_budget`
- optional task-specific instructions

This is important because the analyzer should not be locked to one task only.
The agent must be able to ask for different JSON outputs depending on the stage.

## Required Output Contract

Each article should return a structured result such as:

- `id`
- `in_scope`
- `relevance_score`
- `confidence`
- `short_reason`
- `evidence_summary`
- `matched_terms`

The exact schema can change by task, but results must always:

- be strict JSON
- preserve article `id`
- avoid hallucinated fields
- be mergeable across batches

## Why This Should Be Built Before Real Agent Mode

Without this layer, agent mode has only two bad options:

- read too many abstracts directly and become slow
- skip reading and make poor relevance decisions

The batch analyzer solves that by creating a cheap first-pass evidence filter.

So the correct build order is:

1. batch analyzer
2. agent mode orchestration
3. PDF / full-text escalation

## Case Study

User question:

`In adults with major depression, does hippocampal neurogenesis appear to recover after SSRI treatment?`

Assume the system has already collected `200` PubMed articles.

### Step 1: Agent Defines The Analyzer Task

The agent asks the batch analyzer for this output schema:

```json
{
  "id": 0,
  "in_scope": true,
  "relevance_score": 0,
  "answers_question": false,
  "population_match": false,
  "intervention_match": false,
  "outcome_match": false,
  "evidence_summary": "",
  "short_reason": ""
}
```

What this means:

- `in_scope`: is the paper actually about the question
- `answers_question`: does the abstract contain evidence useful for answering it
- `population_match`: adult / depression fit
- `intervention_match`: SSRI fit
- `outcome_match`: hippocampal neurogenesis fit

### Step 2: Analyzer Processes In Batches

The `200` papers are split into `8` batches of `25`.

For each batch, the analyzer reads the titles + abstracts and produces JSON for all `25` papers.

### Step 3: Analyzer Merges Results

Assume the merged output says:

- `31` papers are broadly in scope
- `12` papers likely answer the question
- `5` papers have high confidence and strong outcome match

At this point the analyzer has already reduced the search space sharply.

### Step 4: Agent Uses The Output

The agent now does not need to inspect all `200` papers.
It reads the analyzer output first, then opens only the top `5-12` abstracts directly.

The agent can then decide:

- which abstracts are truly critical
- which claims are supported
- which papers need PDF download later

### Why This Matches The Intended Design

This case shows the analyzer is:

- not replacing the agent
- not giving the final answer alone
- acting as the agent's large-scale abstract triage engine

That is the correct mental model.

## Recommended Implementation Shape

Build a dedicated `BatchAnalyzerService` on top of the current `BatchLLMService`.

Reuse from the old system:

- token estimation
- abstract trimming
- dynamic chunking
- ID-based merge

Improve over the old system:

- strict task-specific schemas
- stronger JSON validation
- cleaner retry behavior
- clearer per-batch reports
- analyzer outputs that are directly useful for agent mode

## Immediate Next Step

Implement the first analyzer task:

- `screen_for_question`

This should be the default research screening mode and the first tool used by future `agent mode`.
