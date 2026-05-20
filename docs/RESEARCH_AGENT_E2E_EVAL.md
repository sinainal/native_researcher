# Research Agent E2E Eval

This document records the local end-to-end evaluation flow for the Research Agent. It is meant to catch control-flow, model-output, screening, and PDF-extraction regressions before changing the agent architecture further.

## Current Eval Flow

Script:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models gemma-4-26B-A4B-it-UD-IQ4_NL,Qwen3.6-35B-A3B-IQ3_S-merged \
  --batch-sizes 1,2,3,5 \
  --out output/evals/research_agent_e2e/latest
```

The script starts each discovered llama.cpp model with its configured profile, then runs three checks:

1. Planner check: staged Research Agent planning on the nanoplastic/dopamine benchmark prompt.
2. Screening check: compact screening output over a controlled 3-candidate fixture, repeated with batch sizes 1, 2, 3, and 5.
3. Full execution check: fake PubMed candidate retrieval, real model screening, XML full-text download fixture, and model-backed PDF extraction.

Artifacts are written under `output/evals/research_agent_e2e/latest/`:

- `summary.md`: short human-readable result summary.
- `screening_batches.csv`: screening score and latency per model and batch size.
- `e2e_results.json`: full structured result payload.
- `<model>/result.json`: per-model raw details.
- `<model>/llamacpp_server.log`: llama.cpp runtime log.

## 2026-05-20 Results

| Model | Profile | Planner | Planner time | Best screening batch | Screening score | Screening time | Full execution | Full time | Selected | PDF extraction |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| `gemma-4-26B-A4B-it-UD-IQ4_NL` | `gemma4-iq4nl-safe` | pass | 18.173s | 5 | 1.0 | 3.730s | pass | 6.274s | `cand_1` | found `Alpha123` |
| `Qwen3.6-35B-A3B-IQ3_S-merged` | `qwen36-iq3s-safe` | pass | 26.057s | 5 | 1.0 | 2.042s | pass | 7.310s | `cand_1` | found `Alpha123` |

Screening by batch size:

| Model | Batch 1 | Batch 2 | Batch 3 | Batch 5 |
| --- | ---: | ---: | ---: | ---: |
| `gemma-4-26B-A4B-it-UD-IQ4_NL` | 1.0 / 4.664s | 1.0 / 4.050s | 1.0 / 3.918s | 1.0 / 3.730s |
| `Qwen3.6-35B-A3B-IQ3_S-merged` | 1.0 / 4.878s | 1.0 / 3.249s | 1.0 / 2.434s | 1.0 / 2.042s |

## Interpretation

- Both target local models can complete the staged Research Agent flow, abstract screening, and full-text extraction fixture.
- Batch size 5 is stable on this small controlled fixture and is faster than single-candidate screening for both models.
- Qwen IQ3_S is the faster screening model in this run, especially at batch size 5.
- Gemma IQ4_NL produced the staged plan faster in this run.
- Both models selected the relevant primary article, rejected the review and unrelated article, downloaded one full-text fixture, and extracted the expected `Alpha123` evidence.

## Bug Found By The Eval

The first Qwen full-execution run exposed a local tool-call parser crash when the model returned tool arguments as a JSON list instead of a JSON object. The parser now wraps list-shaped arguments as:

```json
{"items": [...]}
```

A regression test was added in `tests/test_ollama_chat_provider.py`.

## Limits Of This Eval

- The screening fixture has only three candidates. Passing batch size 5 here does not prove that larger 10, 20, or 50 candidate batches are safe.
- PubMed and PDF download are controlled fixtures. This isolates agent control flow, but it does not measure live search recall or real publisher PDF variability.
- PDF extraction is tested on XML full text with a known evidence phrase. Real PDF chunking, page evidence, OCR, and noisy text still need broader fixtures.
- UI autoprocess/manual approval behavior should still get a browser-level smoke test after the agent workflow changes.

## Next Eval Expansion

1. Add 10, 20, and 50 candidate screening fixtures to find the batch size where each model starts confusing candidate IDs.
2. Add adversarial candidates with similar dopamine wording but missing residue evidence.
3. Add criteria-disabled execution tests that skip screening and go directly to PDF processing.
4. Add real PubMed/PDF smoke runs with a tiny candidate budget for live-source regressions.
5. Add browser tests for autoprocess on/off, criteria on/off, and the PDF approval path.
