# Native vs Legacy Fast50 Benchmark

- Date: 2026-03-29
- Query: `"ethylene"[Title/Abstract] AND ("docking"[Title/Abstract] OR "molecular docking"[Title/Abstract] OR "in silico"[Title/Abstract])`
- Max results: `50`
- PDF diagnostics used `save_files=false`, so no benchmark files were kept on disk.

## Search

- Native search: `2158.7 ms` | backend `2145 ms`
- Legacy search: `4091.4 ms` | backend `4085 ms`
- PMID overlap in top 50: `50/50`

## Citations

- Native citations: `5153.4 ms` | non-null `50/50`
- Legacy citations: `17107.2 ms` | non-null `50/50`

## Native Preview

- Availability wall time: `34643.4 ms`
- Ready count: `17`
- Preview false negatives vs native fast diagnose: `8`
- Preview false positives vs native fast diagnose: `3`

## Fast Diagnose

- Native fast diagnose: `267722.6 ms` | success `22/50`
- Legacy fast diagnose: `29924.7 ms` | success `18/50`

## Legacy Heuristic

- Legacy PMCID-ready heuristic count: `30`
- Legacy heuristic false negatives vs legacy fast diagnose: `2`
- Legacy heuristic false positives vs legacy fast diagnose: `14`

## Native Ready Sources

- `crossref`: `5`
- `openalex`: `5`
- `pmc_oa_pdf`: `2`
- `pmc_oa_tgz`: `5`

## Diagnose Reasons

- Native: `{"blocked_403": 14, "downloadable": 22, "no_candidates": 11, "no_valid_pdf_payload": 2, "html_not_pdf": 1}`
- Legacy: `{"blocked_403": 20, "downloadable": 18, "no_candidates": 10, "no_valid_pdf_payload": 2}`
