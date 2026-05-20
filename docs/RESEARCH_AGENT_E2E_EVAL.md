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

## 2026-05-20 Thinking Mode And D1-D5 Series Eval

Prompt improvements added after the first eval:

- Complete receptor/protein/gene series requests should become explicit per-member branches.
- Branch queries should focus on target aliases, while shared method/evidence terms belong in `shared_query_concepts`.
- Planner should avoid disease-model or organism expansions unless the user asks for them.
- Criteria should remain short and auditable: target match, primary study type, intervention/exposure match, and requested evidence type.
- Extraction questions should capture subtype, ligand or perturbation, assay/model, endpoint, direction of effect, evidence quote, and uncertainty.

Thinking-mode command:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models gemma-4-26B-A4B-it-UD-IQ4_NL,Qwen3.6-35B-A3B-IQ3_S-merged \
  --batch-sizes 1,2,3,5 \
  --thinking-level on \
  --out output/evals/research_agent_e2e/thinking_dopamine_series
```

Strict D1-D5 screening rerun, with rationale/evidence coverage included in score:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models gemma-4-26B-A4B-it-UD-IQ4_NL,Qwen3.6-35B-A3B-IQ3_S-merged \
  --batch-sizes 3,5 \
  --thinking-level on \
  --skip-planner \
  --skip-pdf-model \
  --out output/evals/research_agent_e2e/thinking_dopamine_series_strict
```

Planner quality highlights:

| Model | Prompt | Time | Branches | D1-D5 coverage | Extraction field coverage | Manual read |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Gemma IQ4_NL | nanoplastic/dopamine | 89.306s | 6 | 1.0 | 0.714 | Over-split into D1-D5 plus a general dopaminergic branch even though the prompt was nanoplastic-focused. |
| Gemma IQ4_NL | D1-D5 series | 68.870s | 5 | 1.0 | 0.857 | Best plan shape: one clean branch per receptor, target-only queries, useful extraction questions. |
| Qwen IQ3_S | nanoplastic/dopamine | 158.215s | 1 | 0.0 | 0.857 | Bad plan shape: collapsed to a single placeholder-like branch, despite reasonable extraction questions. |
| Qwen IQ3_S | D1-D5 series | 165.897s | 5 | 1.0 | 0.714 | Clean D1-D5 branch coverage, but slower than Gemma. |

Strict D1-D5 screening highlights:

| Model | Batch | Score | Time | Selected D1-D5 | Rejected negatives | Evidence coverage | Rationale coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Gemma IQ4_NL | 3 | 1.0 | 49.261s | 1.0 | 1.0 | 1.0 | 1.0 |
| Gemma IQ4_NL | 5 | 1.0 | 44.978s | 1.0 | 1.0 | 1.0 | 1.0 |
| Qwen IQ3_S | 3 | 0.875 | 98.962s | 1.0 | 1.0 | 1.0 | 0.0 |
| Qwen IQ3_S | 5 | 0.875 | 55.181s | 1.0 | 1.0 | 1.0 | 0.0 |

Interpretation:

- Thinking mode is much slower than no-thinking mode for both models.
- Gemma IQ4_NL is currently the stronger thinking-mode planner and produces auditable screening rationales.
- Qwen IQ3_S still selects and rejects the correct candidates, but in D1-D5 screening it omits rationale text, so it is less useful for explainable/inspectable screening.
- Batch 5 remains promising for compact screening, but Qwen had unstable tool-call behavior in one thinking-mode batch-2 residue run and one batch-1 D1-D5 run.
- Browser-driven UI execution is intentionally not part of this eval yet. It should be added as a later Playwright smoke test for autoprocess on/off and criteria on/off paths.

## 2026-05-21 Qwen IQ4_NL Limited Eval

Qwen IQ4_NL did not fit with the full-GPU profile on the 16 GB card. The first attempts failed at model load because the model requested about 16.3-16.7 GiB of CUDA buffer. The limited eval therefore used `-ngl 32`, leaving part of the model on CPU:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models Qwen3.6-35B-A3B-UD-IQ4_NL \
  --batch-sizes 3,5 \
  --thinking-level off \
  --n-gpu-layers 32 \
  --out output/evals/research_agent_e2e/qwen_iq4nl_limited_off_ngl32
```

Results:

| Model | Mode | GPU layers | Nanoplastic planner | D1-D5 planner | Residue batch 5 | D1-D5 batch 3 | D1-D5 batch 5 | PDF extraction |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Qwen IQ4_NL | thinking off | 32 | 0.3 / 226.362s | 0.75 / 86.356s | 1.0 / 7.422s | 0.922 / 38.580s | failed / 20.016s | pass / 23.578s |

Manual read:

- The D1-D5 plan had the right five-branch shape and usable extraction questions.
- The nanoplastic/dopamine plan collapsed to a single placeholder-like branch, similar to Qwen IQ3_S thinking-mode behavior.
- Residue screening was clean and fast once the model was loaded.
- D1-D5 batch 3 selected all five receptor papers and rejected the review, DAT transporter paper, and serotonin paper.
- D1-D5 batch 3 still had incomplete rationales, with rationale coverage `0.375`.
- D1-D5 batch 5 failed to emit output within the screening timeout.
- PDF/XML extraction answered the `Alpha123` evidence question correctly.

Conclusion:

- IQ4_NL was not better than IQ3_S in this local setup because it does not fit comfortably in VRAM and needs CPU offload.
- Quality was mixed: good D1-D5 branch coverage and good selected/rejected decisions at batch 3, but weak rationale completeness and batch-5 instability.
- For this hardware, IQ3_S remains more practical for Qwen-family local screening unless the IQ4_NL runtime profile is improved.

## 2026-05-21 Qwen IQ4_NL CPU-MoE Retest

The local `LLMs` benchmark logs showed the faster Qwen 3.6 runs were not the previous `-ngl 32` CPU-offload path. They used full layer offload with partial CPU-MoE and q4 KV cache. The built-in `qwen36-iq4nl-safe` profile now uses that path by default:

```text
-c 16384 -b 512 -ub 128 -ngl all --flash-attn on --n-cpu-moe 8 -ctk q4_0 -ctv q4_0 --direct-io
```

The llama.cpp provider also caps normal `thinking_level=on` reasoning to 768 tokens per request. `thinking_level=max` is still available for intentionally unbounded runs.

Limited retest command:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models Qwen3.6-35B-A3B-UD-IQ4_NL \
  --thinking-level on \
  --planner-prompts qwen_compact_dopamine_series \
  --batch-sizes 3,5 \
  --skip-residue-screening \
  --out output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded
```

Prompt-only retest after tightening branch-query wording:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models Qwen3.6-35B-A3B-UD-IQ4_NL \
  --thinking-level on \
  --planner-prompts qwen_compact_dopamine_series \
  --skip-series-screening \
  --skip-residue-screening \
  --skip-full-execution \
  --out output/evals/research_agent_e2e/qwen_iq4nl_compact_prompt2_planner
```

Results:

| Run | Planner | D1-D5 batch 3 | D1-D5 batch 5 | PDF extraction | Engine eval TPS |
| --- | ---: | ---: | ---: | ---: | ---: |
| Compact prompt, bounded thinking | 0.55 / 71.861s | 0.922 / 59.069s | 0.875 / 41.691s | pass / 63.466s | ~59-61 |
| Prompt v2 planner-only | 0.65 / 178.533s | n/a | n/a | n/a | ~60 |

Manual read:

- The compact prompt fixed the earlier Qwen collapse: it produced five D1-D5 branches, four criteria, and seven extraction questions.
- The first compact version made branch queries too broad (`D1 OR DRD1`). Prompt v2 fixed this to receptor-context queries such as `dopamine D1 receptor OR DRD1 OR D1R`.
- Screening decisions were good: both batch sizes selected all five receptor papers and rejected the review/transporter/serotonin distractors.
- Rationale coverage remains weaker than Gemma (`0.375` at batch 3 and `0.0` at batch 5), so Qwen still needs output-format work for auditability.
- PDF/XML extraction succeeded and found the `Alpha123` evidence.

Conclusion:

- The poor Qwen IQ4_NL result was partly runtime/profile related and partly prompt related. The CPU-MoE profile restores the expected ~60 tok/s generation band, while the compact prompt restores the D1-D5 branch shape.
- Qwen is still more verbose in thinking mode than Gemma. Bounded reasoning is necessary for agent flows; use `max` only for targeted experiments.

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
