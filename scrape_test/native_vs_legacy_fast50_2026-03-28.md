# Native vs Legacy Fast50 Benchmark

- Date: 2026-03-28
- Query: `"ethylene"[Title/Abstract] AND ("docking"[Title/Abstract] OR "molecular docking"[Title/Abstract] OR "in silico"[Title/Abstract])`
- Max results: `50`
- PDF diagnostics used `save_files=false`, so no benchmark files were kept on disk.

## Search

- Native search: `2333.8 ms` | backend `2323 ms`
- Legacy search: `3212.5 ms` | backend `3204 ms`
- PMID overlap in top 50: `50/50`

## Citations

- Native citations: `5204.1 ms` | non-null `50/50`
- Legacy citations: `5318.3 ms` | non-null `50/50`

## Native Preview

- Availability wall time: `1770.0 ms`
- Ready count: `13`
- Preview false negatives vs native fast diagnose: `5`
- Preview false positives vs native fast diagnose: `1`

## Fast Diagnose

- Native fast diagnose: `124575.6 ms` | success `17/50`
- Legacy fast diagnose: `23070.9 ms` | success `16/50`

## Legacy Heuristic

- Legacy PMCID-ready heuristic count: `30`
- Legacy heuristic false negatives vs legacy fast diagnose: `2`
- Legacy heuristic false positives vs legacy fast diagnose: `16`

## Native Ready Sources

- `crossref`: `6`
- `openalex`: `4`
- `pmc_oa_pdf`: `3`

## Diagnose Reasons

- Native: `{"blocked_403": 20, "downloadable": 17, "no_candidates": 10, "no_valid_pdf_payload": 2, "html_not_pdf": 1}`
- Legacy: `{"blocked_403": 23, "downloadable": 16, "no_candidates": 9, "no_valid_pdf_payload": 2}`
