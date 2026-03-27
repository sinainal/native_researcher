# PDF Mode Benchmark

Date: 2026-03-27
Generated at: 2026-03-27T11:37:48.589451+00:00

## Scope

- Compare current `fast` and sampled `balanced` PDF retrieval latency.
- Check whether the current UI readiness heuristic (`pmc_id => ready`) matches real downloadability.
- Use a small live PubMed sample only; this is a directional benchmark, not a full crawl.

## Environment Notes

- `UNPAYWALL_EMAIL`: not set
- `NCBI_API_KEY`: set
- Balanced mode therefore does not have Unpaywall enrichment in this run.

## Query Fetch Times

| Query | Fetched | Total Found | Requests | Time |
| --- | ---: | ---: | ---: | ---: |
| serotonin receptor docking | 8 | 653 | 4 | 2438 ms |
| serotonin pathway cancer | 6 | 879 | 4 | 3621 ms |
| alphafold ligand discovery | 6 | 104 | 4 | 1646 ms |

## Fast Mode Summary

- Sample size: 8 articles
- Successes: 3, failures: 5
- Total time: mean 9032.6 ms, median 899.5 ms, range 263..42772 ms
- Candidate build time: mean 650.6 ms, median 651.0 ms
- Probe time: mean 8382 ms, median 250.0 ms
- False positives (`ready` but fast cannot download): 1
- False negatives (`not ready` but fast can download): 0

### Fast Sample

| PMID | Ready | Success | Total | Resolve | Probe | Candidates | Source | Notes |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| 36171289 | yes | yes | 42772 ms | 1178 ms | 41594 ms | 2 | crossref |  |
| 38753765 | yes | no | 1287 ms | 868 ms | 419 ms | 3 | - | false positive |
| 39810414 | no | no | 358 ms | 277 ms | 81 ms | 1 | - |  |
| 29679900 | no | no | 263 ms | 263 ms | 0 ms | 0 | - |  |
| 32079105 | yes | yes | 5420 ms | 927 ms | 4493 ms | 4 | pmc_oa_tgz |  |
| 30814658 | yes | yes | 21385 ms | 994 ms | 20391 ms | 3 | crossref |  |
| 37378639 | no | no | 512 ms | 434 ms | 78 ms | 1 | - |  |
| 39097134 | no | no | 264 ms | 264 ms | 0 ms | 0 | - |  |

## Balanced Sample Summary

- Sample size: 4 articles
- Successes: 1, failures: 3
- Total time: mean 3418 ms, median 2040.0 ms, range 1203..8389 ms
- Browser fallback successes inside sample: 1

### Balanced Sample

| PMID | Ready | Success | Total | Candidates | Source | Reason | Browser |
| --- | --- | --- | ---: | ---: | --- | --- | --- |
| 38753765 | yes | yes | 8389 ms | 6 | browser_pmc | downloadable | yes |
| 39810414 | no | no | 1381 ms | 1 | - | blocked_403 | no |
| 29679900 | no | no | 2699 ms | 2 | - | blocked_403 | no |
| 37378639 | no | no | 1203 ms | 1 | - | blocked_403 | no |

## Interpretation

- Current UI readiness is not accurate enough because it only keys off `pmc_id`.
- Any DOI-only article that fast can retrieve is a false negative for the UI.
- Any PMCID article that fast still cannot retrieve is a false positive for the UI.
- Fast mode looks acceptable only when its full end-to-end time stays near the 1-2 second target; anything above that needs either better candidate ordering or lighter probes.
- Balanced is useful as a rescue path, but it is materially slower and should stay out of the default row-level readiness path.

## Immediate Product Guidance

- Keep `fast` as the default click path.
- Do not present `ready` as a hard truth while it is still PMCID-only.
- Replace the current heuristic with a lightweight verified-fast probe if we want row status to be trustworthy.

## Sample Titles

- `36171289`: Bespoke library docking for 5-HT(2A) receptor agonists with antidepressant activity.
- `38753765`: AlphaFold2 structures guide prospective ligand discovery.
- `39810414`: Long-Term Exposure to Tire-Derived 6-PPD Quinone Causes Neurotoxicity and Neuroinflammation via…
- `29679900`: Structural insights into serotonin receptor ligands polypharmacology.
- `32079105`: Mechanisms of Action of Cassiae Semen for Weight Management: A Computational Molecular Docking…
- `30814658`: Structural insight into the serotonin (5-HT) receptor family by molecular docking, molecular dy…
- `37378639`: Design, Synthesis, Molecular Docking, and Biological Evaluation of Novel Pimavanserin-Based Ana…
- `39097134`: Serotonylation in tumor-associated fibroblasts contributes to the tumor-promoting roles of sero…

