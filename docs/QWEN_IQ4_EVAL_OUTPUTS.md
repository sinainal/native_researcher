# Qwen IQ4_NL Eval Outputs

This file exposes the important local eval outputs that live under ignored `output/` paths.

## Raw Local Files

These files are local artifacts and are not committed because `output/` is gitignored:

- `output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded/summary.md`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded/e2e_results.json`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded/screening_batches.csv`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded/Qwen3.6-35B-A3B-UD-IQ4_NL/result.json`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded/Qwen3.6-35B-A3B-UD-IQ4_NL/llamacpp_server.log`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_prompt2_planner/summary.md`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_prompt2_planner/e2e_results.json`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_prompt2_planner/Qwen3.6-35B-A3B-UD-IQ4_NL/result.json`
- `output/evals/research_agent_e2e/qwen_iq4nl_compact_prompt2_planner/Qwen3.6-35B-A3B-UD-IQ4_NL/llamacpp_server.log`

## Bounded Thinking E2E Run

Command:

```bash
.venv/bin/python scripts/research_agent_e2e_eval.py \
  --models Qwen3.6-35B-A3B-UD-IQ4_NL \
  --thinking-level on \
  --planner-prompts qwen_compact_dopamine_series \
  --batch-sizes 3,5 \
  --skip-residue-screening \
  --out output/evals/research_agent_e2e/qwen_iq4nl_compact_think_on_cpumoe_bounded
```

Summary:

| Metric | Result |
| --- | --- |
| Model | `Qwen3.6-35B-A3B-UD-IQ4_NL` |
| Profile | `qwen36-iq4nl-safe` |
| llama.cpp args | `-c 16384 -b 512 -ub 128 -ngl all --flash-attn on --n-cpu-moe 8 -ctk q4_0 -ctv q4_0` |
| Thinking | `on`, capped with `thinking_budget_tokens=768` |
| Total eval elapsed | `236.088s` |
| Planner | ok, `71.861s`, score `0.55` |
| D1-D5 series coverage | `1.0` |
| D1-D5 batch 3 | ok, score `0.922`, `59.069s` |
| D1-D5 batch 5 | ok, score `0.875`, `41.691s` |
| PDF extraction | ok, `63.466s`, selected `cand_1`, found `Alpha123` |
| Engine eval TPS | about `59-61 tok/s` |

Screening batch details:

```text
batch 3:
  selected: series_1, series_2, series_3, series_4, series_5
  rejected distractors: series_6 review, series_7 DAT transporter, series_8 serotonin receptor
  scores: series_1=1.0, series_2=1.0, series_3=1.0, series_4=1.0, series_5=1.0, series_6=0.4722, series_7=0.0, series_8=0.0
  evidence_coverage=1.0, rationale_coverage=0.375

batch 5:
  selected: series_1, series_2, series_3, series_4, series_5
  rejected distractors: series_6 review, series_7 DAT transporter, series_8 serotonin receptor
  scores: series_1=1.0, series_2=1.0, series_3=1.0, series_4=1.0, series_5=1.0, series_6=0.1389, series_7=0.0, series_8=0.0
  evidence_coverage=1.0, rationale_coverage=0.0
```

## Prompt V2 Planner-Only Run

Command:

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

Summary:

| Metric | Result |
| --- | --- |
| Planner | ok, `178.533s`, score `0.65` |
| Query specificity | `0.733` |
| Branch count | `5` |
| Criteria count | `3` |
| Extraction question count | `7` |
| D1-D5 series coverage | `1.0` |
| Extraction field coverage | `1.0` |
| Engine eval TPS | about `60 tok/s` |

Planner branch output:

```json
[
  {"id": "d1_drd1", "label": "D1/DRD1", "query": "dopamine D1 receptor OR DRD1 OR D1R"},
  {"id": "d2_drd2", "label": "D2/DRD2", "query": "dopamine D2 receptor OR DRD2 OR D2R"},
  {"id": "d3_drd3", "label": "D3/DRD3", "query": "dopamine D3 receptor OR DRD3 OR D3R"},
  {"id": "d4_drd4", "label": "D4/DRD4", "query": "dopamine D4 receptor OR DRD4 OR D4R"},
  {"id": "d5_drd5", "label": "D5/DRD5", "query": "dopamine D5 receptor OR DRD5 OR D5R"}
]
```

Manual read:

- The first compact prompt fixed Qwen's branch collapse, but produced overly broad queries like `D1 OR DRD1`.
- Prompt v2 fixed the query shape by requiring receptor-context aliases.
- Qwen IQ4_NL is now fast enough again with the CPU-MoE profile, but its screening rationale output is still weaker than Gemma's.
