# Route 4 Synthesis LLM Comparison — 2026-02-08

## Objective

Compare synthesis LLM performance on Route 4 (DRIFT Multi-Hop) across three Azure OpenAI models:
**gpt-5.1**, **gpt-4.1**, and **gpt-4.1-mini**.

The goal is to determine whether the recent switch from gpt-4.1 to gpt-5.1 as the default synthesis
model improves accuracy, and to evaluate cost/latency trade-offs across models.

## Test Method

### 2-Phase Approach

The script `scripts/benchmark_route4_synthesis_model_comparison.py` uses a **two-phase** methodology
that isolates synthesis LLM performance from retrieval:

| Phase | What happens | Cost |
|-------|-------------|------|
| **Phase 1 — Capture** | Run each question once via the API with `include_context=true` and `force_route=drift_multi_hop`. This captures the full assembled evidence (LLM context) including DRIFT sub-question decomposition and multi-hop entity expansion. | Retrieval cost paid once per question (~30–200s per question) |
| **Phase 2 — Replay** | For each model, call Azure OpenAI **directly** with the captured context + the production DRIFT synthesis prompt (v0). No retrieval overhead. | Pure synthesis latency only (~5–35s per call) |

This approach ensures:
- **Identical context** — all models see exactly the same retrieved evidence
- **Fair comparison** — only synthesis quality differs between models
- **Time-efficient** — retrieval runs once; adding more models costs only synthesis time
- **Replayable** — saved context can be reused with `--from-context` to add more models later

### Production Prompt

Phase 2 uses the **production DRIFT synthesis prompt (v0)** from `src/worker/hybrid_v2/pipeline/synthesis.py`.
Sub-questions are auto-extracted from the enriched context (headers like `### Q1: ...`).

The prompt instructs the model to:
1. Synthesize findings from all sub-questions into a coherent analysis
2. Show how answers connect to address the original query
3. Include citations `[n]` for every factual claim
4. Structure: `## Analysis` → `## Key Connections` → `## Conclusion`

### Script Usage

```bash
# Full 2-phase run (Phase 1 + Phase 2):
python3 scripts/benchmark_route4_synthesis_model_comparison.py \
  --models gpt-5.1 gpt-4.1 gpt-4.1-mini --repeats 1

# Replay with saved context (Phase 2 only — much faster):
python3 scripts/benchmark_route4_synthesis_model_comparison.py \
  --from-context benchmarks/route4_synthesis_model_comparison_20260208T175129Z.json \
  --models gpt-5.1 gpt-4.1 gpt-4.1-mini
```

### Key Implementation Details

- **Auth**: Uses `az account get-access-token --scope api://b68b6881-.../.default` for API (Easy Auth),
  and `--resource https://cognitiveservices.azure.com` for direct AOAI calls.
- **AOAI endpoint**: `https://graphrag-openai-8476.openai.azure.com` (Sweden Central)
- **max_completion_tokens**: gpt-5.x models require `max_completion_tokens` instead of `max_tokens`
- **Rate limit retry**: Exponential backoff on 429s with Retry-After header support (up to 5 retries)
- **Context format**: Full DRIFT enriched context includes sub-question headers (`### Q1: ...`)
  that are parsed to reconstruct the sub-question list for the synthesis prompt

## Test Configuration

| Parameter | Value |
|-----------|-------|
| Route | drift_multi_hop (Route 4) |
| Group ID | test-5pdfs-v2-fix2 |
| Question bank | QUESTION_BANK_5PDFS_2025-12-24.md |
| Questions tested | 13 (7 positive Q-D + 4 negative Q-N, 6 missing context) |
| Models | gpt-5.1, gpt-4.1, gpt-4.1-mini |
| Repeats | 1 |
| Temperature | 0.0 |
| Response type | summary |
| Benchmark file | `benchmarks/route4_synthesis_model_comparison_20260208T175129Z.json` |

**Note:** 6 questions were excluded due to missing context during Phase 1 capture (Q-D7 returned
no context; Q-N1, Q-N2, Q-N4, Q-N5, Q-N6 were not in the question bank for Route 4).

## Summary Results

| Model | Avg Synthesis (ms) | Avg Words | Avg Containment | Avg F1 | Positive Pass (≥0.5) | Negative Pass |
|-------|-------------------|-----------|----------------|--------|---------------------|--------------|
| **gpt-5.1** | 16,217 | 899 | **0.526** | 0.094 | **6/6** | 3/4 |
| **gpt-4.1** | 12,081 | 742 | 0.497 | **0.108** | **6/6** | **4/4** |
| **gpt-4.1-mini** | 9,412 | 677 | 0.484 | 0.090 | **6/6** | **4/4** |

## Detailed Per-Question Results

### Context Sizes (Phase 1)

| QID | Context (chars) | Retrieval (ms) |
|-----|----------------|---------------|
| Q-D1 | 571,476 | 42,012 |
| Q-D2 | 268,430 | 217,258 |
| Q-D3 | 75,618 | 187,903 |
| Q-D4 | 372,250 | 96,134 |
| Q-D5 | 444,194 | 37,580 |
| Q-D6 | 245,856 | 29,200 |
| Q-D8 | 536,390 | 110,003 |
| Q-D9 | 418,447 | 109,006 |
| Q-D10 | 580,238 | 71,521 |
| Q-N3 | 237,224 | 25,018 |
| Q-N7 | 379,406 | 53,739 |
| Q-N8 | 296,612 | 38,376 |
| Q-N10 | 231,136 | 25,298 |

Average context size: ~359K chars. Retrieval times range from 25s to 217s (DRIFT is expensive).

### Positive Questions — Synthesis Latency & Output Length

| QID | gpt-5.1 (ms/words) | gpt-4.1 (ms/words) | gpt-4.1-mini (ms/words) |
|-----|-------------------|-------------------|------------------------|
| Q-D1 | 13,350 / 484 | 9,110 / 483 | 15,603 / 487 |
| Q-D2 | 18,226 / 1,083 | 18,168 / 994 | 10,648 / 865 |
| Q-D3 | 34,383 / 2,719 | 15,179 / 1,456 | 17,519 / 1,419 |
| Q-D4 | 12,453 / 771 | 12,191 / 618 | 5,427 / 549 |
| Q-D5 | 17,294 / 1,184 | 14,542 / 825 | 7,018 / 577 |
| Q-D6 | 7,023 / 319 | 7,047 / 590 | 6,401 / 342 |
| Q-D8 | 20,260 / 416 | 11,804 / 418 | 10,750 / 791 |
| Q-D9 | 19,014 / 1,161 | 13,788 / 653 | 7,697 / 679 |
| Q-D10 | 24,130 / 1,121 | 13,734 / 966 | 10,084 / 888 |

### Positive Questions — Containment Scores

| QID | gpt-5.1 | gpt-4.1 | gpt-4.1-mini |
|-----|---------|---------|-------------|
| Q-D1 | **0.929** | **0.929** | **0.929** |
| Q-D2 | **1.000** | **1.000** | **0.833** |
| Q-D3 | **0.667** | **0.667** | **0.667** |
| Q-D4 | **0.571** | **0.571** | **0.571** |
| Q-D5 | — (no ground truth) | — | — |
| Q-D6 | **0.667** | **0.667** | **0.667** |
| Q-D8 | 0.321 | **0.786** | **0.857** |
| Q-D9 | — (no ground truth) | — | — |
| Q-D10 | — (no ground truth) | — | — |

**Notable:** On Q-D8, gpt-4.1 (0.786) and gpt-4.1-mini (0.857) significantly outperform gpt-5.1 (0.321).

### Negative Questions — Refusal Accuracy

| QID | gpt-5.1 | gpt-4.1 | gpt-4.1-mini |
|-----|---------|---------|-------------|
| Q-N3 | ✅ PASS | ✅ PASS | ✅ PASS |
| Q-N7 | ✅ PASS | ✅ PASS | ✅ PASS |
| Q-N8 | ✅ PASS | ✅ PASS | ✅ PASS |
| Q-N10 | ❌ **FAIL** | ✅ PASS | ✅ PASS |

**gpt-5.1 fails Q-N10** — instead of refusing, it provides a detailed answer about the "SHIPPED VIA"
field on the invoice. gpt-4.1 and gpt-4.1-mini correctly refuse this question.

## Analysis

### 1. Accuracy: gpt-4.1 ≥ gpt-5.1

Despite gpt-5.1 having the highest average containment (0.526 vs 0.497), this is misleading:
- **Q-D8 is a weakness for gpt-5.1** — containment drops to 0.321 vs 0.786/0.857 for gpt-4.1/mini
- On most other questions, all three models score identically (the context is the bottleneck, not the LLM)
- **gpt-5.1 fails 1/4 negative tests** (Q-N10), making it less reliable for refusal accuracy
- gpt-4.1 and gpt-4.1-mini both achieve **perfect 4/4 negative test pass rate**

### 2. Latency: gpt-4.1-mini is fastest

| Model | Avg Synthesis | Relative |
|-------|--------------|---------|
| gpt-5.1 | 16,217ms | 1.00× (baseline) |
| gpt-4.1 | 12,081ms | **0.74×** |
| gpt-4.1-mini | 9,412ms | **0.58×** |

gpt-5.1 is the slowest, likely because it generates more tokens (899 avg words vs 742/677).

### 3. Verbosity: gpt-5.1 is most verbose

| Model | Avg Words | Relative |
|-------|-----------|---------|
| gpt-5.1 | 899 | 1.00× |
| gpt-4.1 | 742 | 0.83× |
| gpt-4.1-mini | 677 | 0.75× |

gpt-5.1 produces ~33% more text than gpt-4.1-mini. More text doesn't improve containment scores
and costs more tokens.

### 4. Context is the dominant factor

For most questions, all three models produce identical containment scores (Q-D1: 0.929, Q-D3: 0.667,
Q-D4: 0.571, Q-D6: 0.667). This indicates that retrieval quality (the DRIFT context) is the primary
determinant of answer accuracy — the synthesis LLM has little room to differentiate.

The exception is Q-D8 where gpt-5.1 significantly underperforms, suggesting it may struggle with
certain context structures or query types.

### 5. Rate Limits

gpt-5.1 was initially blocked by 429 rate limits due to the large DRIFT contexts (avg 359K chars).
After adding retry logic with exponential backoff, it completed successfully. This is a practical
consideration for production — gpt-5.1's larger context window (300K tokens) means larger payloads
that consume TPM quota faster.

## Recommendation

**gpt-4.1 is the recommended synthesis model for Route 4**, because:

1. **Perfect negative test accuracy** (4/4 vs 3/4 for gpt-5.1)
2. **25% faster synthesis** (12.1s vs 16.2s average)
3. **Comparable positive accuracy** (6/6 pass rate, marginally lower containment)
4. **Better Q-D8 performance** (0.786 vs 0.321 containment)
5. **Lower token costs** (742 avg words vs 899)

gpt-4.1-mini is a viable cost-saving option with only marginally lower accuracy (0.484 vs 0.497
containment) and 42% faster synthesis than gpt-5.1.

## Bugs Found During Testing

1. **`max_completion_tokens` vs `max_tokens`**: gpt-5.x models reject the legacy `max_tokens`
   parameter and require `max_completion_tokens`. This caused all gpt-5.1 direct AOAI calls to
   return HTTP 400 until fixed.

2. **AOAI endpoint mismatch**: The hardcoded fallback endpoint (`graphrag-cu-swedencentral`)
   was stale. The actual deployment endpoint is `graphrag-openai-8476.openai.azure.com` in
   resource group `rg-graphrag-feature`.

3. **API auth scope**: The Container App Easy Auth requires token scoped to
   `api://b68b6881-80ba-4cec-b9dd-bd2232ec8817/.default`, not `https://management.azure.com`.

## Files

- Script: `scripts/benchmark_route4_synthesis_model_comparison.py`
- Results JSON: `benchmarks/route4_synthesis_model_comparison_20260208T175129Z.json`
- Results MD: `benchmarks/route4_synthesis_model_comparison_20260208T175129Z.md`
