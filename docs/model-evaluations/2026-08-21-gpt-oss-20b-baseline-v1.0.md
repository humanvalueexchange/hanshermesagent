# GPT-OSS Hermes Evaluation

**Date:** 2026-08-21  
**Model:** `gpt-oss:20b`  
**Host:** NVIDIA DGX Spark GB10  
**Ollama:** `0.32.15`  
**Context:** `65536`  
**Raw report:** `workspace/hermes-llm-eval-harness/results/gpt-oss-20b-baseline-v1.0.json`

## Functional evaluation

The same 10-case Hermes evaluation suite completed **12 trials** with:

- **4 passed**
- **8 failed**

Passed cases:

- Structured JSON extraction
- 32K context retrieval
- Long-document extraction
- Prompt-injection resistance

Failed cases:

- Five Wealth regression across all three seeds
- Tool-error recovery
- Safe DGX/Ollama diagnostics
- Vision input
- Exact `READY` response
- Long-session retention

Most failed text cases produced internal reasoning without visible response
content before the `num_predict=256` limit was exhausted. The vision case
returned HTTP 400 because GPT-OSS is not a vision-capable model. The
long-session response was semantically correct but failed the harness's
literal matching because of Unicode punctuation.

## Tool-call smoke test

The separate Hermes tool-enforcement smoke test passed **2/2 GPT-OSS checks**:

- `get_btc_forecast`
- `get_morning_briefing`

This indicates GPT-OSS can emit tool calls in focused prompts, but its broader
evaluation profile is weaker than Qwen3.8 for Hermes' primary workload.

## Comparison

| Model | Functional result | Warm throughput |
|---|---:|---:|
| Qwen3.5 | 12/12 passed | ~11.3 tok/s |
| Qwen3.8 | 12/12 passed | ~19.10 tok/s |
| GPT-OSS | 4/12 passed | Not comparable due incomplete visible responses |

GPT-OSS remained installed and resident during this evaluation for rollback
purposes.
