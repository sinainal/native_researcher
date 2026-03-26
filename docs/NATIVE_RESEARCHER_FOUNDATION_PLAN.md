# Native Researcher Foundation Plan

## Objective

Build the product in the correct order:

1. strengthen the application shell and workspace model
2. add in-app PDF storage, parsing, and viewing
3. add deterministic PDF search and section extraction
4. move to agentic evidence workflows only after the document layer is reliable

## Execution Order

### Phase 1. Workspace Foundation

- add a landing page and launcher
- introduce `workspace -> project` structure
- persist project metadata under a dedicated workspace root
- route the app through project selection instead of dropping directly into a single workspace
- prepare filesystem layout for:
  - `pdfs`
  - `derived`
  - `indexes`
  - `exports`
  - `notes`

### Phase 2. Project Library

- show downloaded PDFs per project
- move PDF downloads into project-scoped folders
- add project library status:
  - queued
  - downloaded
  - parsed
  - failed

### Phase 3. PDF Parsing Core

- extract page, block, line, span, and bounding-box data from PDFs
- normalize text for deterministic matching
- split documents into canonical sections where possible:
  - abstract
  - introduction
  - methods
  - results
  - discussion
  - conclusion
  - references

### Phase 4. In-App PDF Viewer

- render PDFs inside the app
- support page navigation
- support evidence highlights from deterministic matches
- support side evidence list and section jumping

### Phase 5. Deterministic Evidence Engine

- exact text search
- normalized search
- dehyphenated search
- fragment search
- nearest-passage fallback
- verification states:
  - exact
  - normalized_exact
  - fragment_recovered
  - closest_match
  - unverified
  - rejected

### Phase 6. Metadata Enrichment

- add ISSN-aware journal metadata
- add journal quartile enrichment
- expose quartile in the results table
- use quartile as a ranking priority, not a hard gate

### Phase 7. Agentic Layer

- add lightweight planner/executor tools on top of the deterministic evidence engine
- use Flash Lite in intermediate search/verification steps
- keep final synthesis constrained to verified evidence spans only

## Current Deliverable

This change starts `Phase 1`:

- saved the product plan to docs
- added a dedicated launcher page
- introduced project creation and listing
- created project-scoped filesystem directories for future PDF and evidence work
