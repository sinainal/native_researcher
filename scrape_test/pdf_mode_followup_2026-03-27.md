# PDF Mode Follow-up

Date: 2026-03-27

## What changed after the first benchmark

- Fixed a PubMed XML parsing bug that was pulling DOI and PMCID values from reference lists instead of the main article record.
- Added local file loading for `NCBI_API_KEY`, so the current app now reads the key from `ncbi_api`.
- Added a separate `fast availability` verifier for the UI.
  - This path is now used for row readiness.
  - It verifies only quick direct-PDF candidates.
  - It does not download full PDFs or PMC `.tar.gz` bundles during readiness checks.

## Controlled NCBI API key check

Same query, same app, three runs each:

| Mode | Runs (ms) | Mean | Median |
| --- | --- | ---: | ---: |
| No key | 5460, 1627, 3174 | 3420.3 ms | 3174 ms |
| With key | 2915, 1395, 1758 | 2022.7 ms | 1758 ms |

Conclusion:

- The NCBI key clearly helps PubMed fetch speed on this small controlled sample.
- It does not materially improve PDF download success by itself.
- PDF success is driven more by identifier correctness and candidate strategy than by NCBI request rate.

## Full fast download after parser fix

From the live benchmark in [pdf_mode_benchmark_2026-03-27.md](/home/sina/Downloads/Researcher/native_researcher/scrape_test/pdf_mode_benchmark_2026-03-27.md):

- `fast` success count improved from `1/8` to `3/8` after identifiers were corrected.
- The remaining problem is tail latency:
  - some `fast` downloads still took `21s` to `42s`
  - the long tail came from real file transfer, not search metadata

Key finding:

- `fast` should not be used as the UI truth source by downloading whole files.
- readiness verification must stay separate from full download.

## New fast availability verifier

Small live sample:

- Articles checked: `3`
- Total time: `3627 ms`
- Effective rate: about `1.2 s/article`

Results:

- `36171289`: ready via `crossref`
- `38753765`: not ready in fast verifier
- `39810414`: not ready in fast verifier

Operational meaning:

- The UI can now avoid the old false-positive pattern without blocking initial PubMed search.
- Deep/balanced remains the rescue path for items that are not quick-downloadable.

## Practical direction

- Keep PubMed search keyed with `NCBI_API_KEY`.
- Keep UI readiness tied to the new fast verifier, not raw `pmc_id`.
- Keep `Deep` as the path for hard cases such as browser rescue or slower repository/package retrieval.
