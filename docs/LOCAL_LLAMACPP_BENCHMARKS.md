# Local llama.cpp Research Planner Benchmarks

This note records the local profiles tested for the research-plan benchmark. It is intentionally limited to planner/search quality and local model runtime. It does not change or exercise the native download pipeline.

## Test Setup

- Date: 2026-05-17
- GPU: NVIDIA RTX 5060 Ti, 16 GB VRAM
- Benchmark script: `scripts/research_plan_benchmark.py`
- Benchmark prompt: default nanoplastic/dopamine planner prompt in `app/services/research_plan_benchmark.py`
- Stages exercised: plan generation and real article pulls only
- Thinking: off for all measured runs

The benchmark records two TPS views:

- `api_tps`: provider-reported completion tokens divided by elapsed wall time.
- `estimated_total_tps`: visible text plus measured thinking-token estimate divided by elapsed wall time. This is useful when a provider streams thinking separately, but it can overestimate no-thinking llama.cpp runs because it estimates tokens from characters.
- `engine eval TPS`: parsed from llama-server `eval time` log lines when the benchmark starts llama.cpp or receives `--llamacpp-log`. This is the closest value to the older raw llama.cpp TPS tests.

The benchmark also records quality signals:

- `plan_quality_score`: branch count, extraction question count, criteria count, query specificity, and nanoplastic/dopamine coverage.
- `query_validity_score`: empty/overlong/broken Boolean query checks and execution errors.
- `article_relevance_score`: simple relevance heuristic over pulled article titles/abstracts for nanoplastic, dopamine/Parkinson, and interaction/effect signals.
- `overall_score`: weighted summary of plan, query, and article relevance scores.

## Models and Binaries

### Qwen 3.6 35B IQ4_NL

Model:

```bash
/home/sina/Downloads/LLMs/LLm test/models/qwen36-unsloth/Qwen3.6-35B-A3B-UD-IQ4_NL.gguf
```

Compatible binary:

```bash
/home/sina/Downloads/LLMs/LLm test/llama.cpp-latest/build-cuda130/bin/llama-server
```

Notes:

- `llama.cpp-turbo3-cuda` is not compatible with this IQ4_NL file on this machine. It fails at load time with `qwen35moe.rope.dimension_sections has wrong array length; expected 3, got 4`.
- The latest CUDA build does not support `turbo3` KV cache types. It accepts standard cache types such as `f16`, `q8_0`, `q4_0`, and `iq4_nl`.
- The safest measured profile remains 64k context, flash attention on, direct I/O on, `-b 512`, `-ub 128`.

Recommended command:

```bash
env LD_LIBRARY_PATH="/home/sina/Downloads/LLMs/LLm test/llama.cpp-latest/build-cuda130/bin:/home/sina/Downloads/LLMs/cuda130/lib:/usr/local/lib/ollama/cuda_v13:/usr/local/lib/ollama:${LD_LIBRARY_PATH:-}" \
  "/home/sina/Downloads/LLMs/LLm test/llama.cpp-latest/build-cuda130/bin/llama-server" \
  -m "/home/sina/Downloads/LLMs/LLm test/models/qwen36-unsloth/Qwen3.6-35B-A3B-UD-IQ4_NL.gguf" \
  --host 127.0.0.1 --port 8100 \
  -c 65536 -fa on -b 512 -ub 128 \
  --threads 10 --threads-batch 16 \
  --parallel 1 -np 1 --no-cont-batching --no-warmup \
  --reasoning off --direct-io --cache-ram 0 \
  --alias qwen3.6-iq4nl-latest-b512
```

### Qwen 3.6 35B Q4_K_M

Model:

```bash
/usr/share/ollama/.ollama/models/blobs/sha256-f5ee307a2982106a6eb82b62b2c00b575c9072145a759ae4660378acda8dcf2d
```

Compatible binary:

```bash
/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin/llama-server
```

Notes:

- The newer `llama.cpp-latest` and `atomic-llama-cpp-turboquant` builds reject this Q4_K_M blob with the opposite `rope.dimension_sections` shape error.
- Do not use `--direct-io` for this large Q4_K_M blob unless there is a specific reason. Keeping mmap enabled avoids pulling the full 23 GB file into resident RAM.
- `--fit on` is needed to keep the profile inside 16 GB VRAM.
- `--cache-type-k turbo3 --cache-type-v turbo3` reduces KV memory substantially, but it did not materially improve planner wall time in the measured plan-agent workload.

Recommended command:

```bash
env LD_LIBRARY_PATH="/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin:/home/sina/Downloads/LLMs/cuda130/lib:/usr/local/lib/ollama/cuda_v13:/usr/local/lib/ollama:${LD_LIBRARY_PATH:-}" \
  "/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin/llama-server" \
  -m /usr/share/ollama/.ollama/models/blobs/sha256-f5ee307a2982106a6eb82b62b2c00b575c9072145a759ae4660378acda8dcf2d \
  --host 127.0.0.1 --port 8099 \
  -c 32768 -fa on -b 256 -ub 96 \
  --threads 10 --threads-batch 16 \
  --parallel 1 -np 1 --no-cont-batching --no-warmup \
  --reasoning off --cache-ram 0 \
  --fit on --fit-target 1600 --fit-ctx 16384 \
  --cache-type-k turbo3 --cache-type-v turbo3 \
  --alias qwen3.6-q4km-turbo3kv-fit
```

## Results

| Profile | Status | Planning | Relevant hits | Partial hits | Max stream gap | API TPS | Estimated total TPS | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `qwen_iq4nl_latest_b512_rerun` | success | 69.236s | 3 | 5 | 24.334s | 42.65 | 68.62 | Best practical local profile tested. |
| `qwen_iq4nl_latest_b1024` | success, bad queries | 90.118s | 0 | 0 | 41.679s | 46.93 | 72.95 | Larger batch looked faster on the TPS probe but produced overlong invalid PubMed queries and 414 errors. Not recommended. |
| `qwen_q4km_turbo3kv_fit` | success | 162.192s | 3 | 5 | 62.757s | 35.86 | 58.52 | Quality preserved, but wall time is effectively unchanged from the previous Q4_K_M fit profile. |
| `qwen36_q4km_llamacpp_turbo3_nothink` | success | 163.578s | 2 | 2 | 63.731s | 34.38 | 53.58 | Earlier baseline without turbo3 KV in benchmark output. |
| `qwen_q4km_turbo3kv_cpumoe` | aborted | n/a | n/a | n/a | n/a | n/a | n/a | Full CPU-MoE loaded safely but prompt eval was too slow for planner use. |

## Practical Conclusion

- IQ4_NL is the better planner candidate right now. It is about 2.3x faster than Q4_K_M on the full staged planning benchmark and retrieved comparable or better target papers in the rerun.
- Q4_K_M remains useful when output quality matters more than latency, but turbo3 KV did not deliver meaningful planner speedup. It mainly reduces KV memory.
- Full CPU-MoE is a memory escape hatch, not a planner-speed optimization on this machine.
- Partial CPU-MoE via `--n-cpu-moe` is different from full `--cpu-moe`. The measured fast Q4_K_M profiles use partial CPU-MoE, usually `--n-cpu-moe 15`, not full CPU-MoE.
- The `b1024/ub256` IQ4_NL run should not be adopted. It improved the short TPS probe but made the real planner output worse and slower.

## Built-In Profiles

Native Researcher now exposes the measured llama.cpp profiles through `app/llm/llamacpp_profiles.py`.

- `qwen36-q4km-safe`: `--n-cpu-moe 15`, `-ctk turbo4`, `-ctv turbo3`, 32K context, direct I/O.
- `qwen36-q4km-fast-risky`: `--n-cpu-moe 14`, `-ctk turbo4`, `-ctv turbo3`, 32K context, lower VRAM margin.
- `qwen36-q4km-64k-safe`: safe Q4_K_M settings with 64K context.
- `qwen36-iq4nl-safe`: latest CUDA 13 IQ4_NL settings with 64K context.
- `gemma4-iq4nl-safe`: existing Gemma 4 IQ4_NL full-GPU settings.

The benchmark CLI can now start llama-server with one of these profiles:

```bash
.venv/bin/python scripts/research_plan_benchmark.py \
  --start-llamacpp \
  --llamacpp-base-url http://127.0.0.1:8098 \
  --llamacpp-executable "/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin/llama-server" \
  --llamacpp-model-path /usr/share/ollama/.ollama/models/blobs/sha256-f5ee307a2982106a6eb82b62b2c00b575c9072145a759ae4660378acda8dcf2d \
  --llamacpp-library-path "/home/sina/Downloads/LLMs/LLm test/llama.cpp-turbo3-cuda/build-cuda-local/bin:/home/sina/Downloads/LLMs/cuda130/lib:/usr/local/lib/ollama/cuda_v13:/usr/local/lib/ollama" \
  --llamacpp-profile qwen36-q4km-safe \
  --llamacpp-log output/benchmarks/qwen_q4km_safe/llamacpp_server.log \
  --models "llamacpp:qwen3.6-q4km-safe|think=off|label=qwen_q4km_safe"
```

Outputs are written under `output/benchmarks/<run-name>/`:

- `benchmark.json`: full raw run payload, timing, model usage, thinking-token estimate, engine metrics, and quality metrics.
- `summary.md`: readable comparison report with ranking, engine TPS, quality scores, query issues, and pulled article relevance.
- `articles.csv`: pulled article list with relevance flags and relevance score.

## Artifact Paths

- `output/benchmarks/optimization_qwen_iq4nl_latest_b512_rerun/`
- `output/benchmarks/optimization_qwen_iq4nl_latest_b1024/`
- `output/benchmarks/optimization_qwen_q4km_turbo3kv_fit/`
- `output/benchmarks/nanoplastic_dopamine_plan_qwen_q4km_llamacpp_turbo3/`
