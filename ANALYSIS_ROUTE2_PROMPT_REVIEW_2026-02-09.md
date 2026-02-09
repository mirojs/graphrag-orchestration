# Route 2 Prompt Review — 2026-02-09

## Context

After de-noising (Steps 4–12), Route 2 now sends **~10 focused chunks** to the LLM (down from ~38).
This review evaluates whether the current synthesis prompt is appropriate for the reduced context,
and whether a cheaper/smaller model could replace gpt-5.1.

## Current Prompt

Located in `src/worker/hybrid_v2/pipeline/synthesis.py` → `_get_summary_prompt()` (line 1410).

```
You are an expert analyst generating a concise summary.

Question: {query}

Evidence Context:
{context}

Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence:
    - Question asks for "bank routing number" but evidence only has payment portal URL → Output: "The requested information was not found in the available documents."
    - Question asks for "SWIFT code" but evidence has no SWIFT/IBAN → Output: "The requested information was not found in the available documents."
    - Question asks for "California law" but evidence shows Texas law → Output: "The requested information was not found in the available documents."
   - Do NOT say "The invoice does not provide X, but here is Y" — Just refuse entirely.
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs).
3. **RESPECT ALL QUALIFIERS** in the question. If the question asks for a specific type, category, or unit:
   - Include ONLY items matching that qualifier
   - EXCLUDE items that don't match, even if they seem related
4. Include citations [N] for factual claims (aim for every sentence that states a fact).
5. If the evidence contains explicit numeric values (e.g., dollar amounts, time periods/deadlines, percentages, counts), include them verbatim.
6. Prefer concrete obligations/thresholds over general paraphrases.
7. If the question is asking for obligations, reporting/record-keeping, remedies, default/breach, or dispute-resolution: enumerate each distinct obligation/mechanism that is explicitly present in the Evidence Context; do not omit items just because another item is more prominent.

Respond using this format:

## Summary
[Summary with citations [N] for every factual claim. Include explicit numeric values verbatim. Cover provisions from ALL source documents, not just the most prominent one.]

## Key Points
- [Distinct item/obligation 1 with citation [N]]
- [Distinct item/obligation 2 with citation [N]]
- [Additional items from each source document as needed]
```

Additionally, a conditional **document guidance** block is appended for per-document queries
(e.g. "what does each document say about...") instructing the model to consolidate sections/exhibits
into parent documents and avoid double-counting.

### Prompt Characteristics

- **7 instruction rules** including refusal logic, qualifier handling, citations, verbatim numbers
- **3 refusal examples** (routing number, SWIFT code, California law)
- **Structured output format** (## Summary + ## Key Points)
- **Domain-specific guidance** (obligations, dispute-resolution enumeration)

## Model Comparison Results (Post De-noising)

**Benchmark:** `benchmarks/route2_synthesis_model_comparison_20260209T164316Z.json`
**Default synthesis model:** `gpt-5.1` (set in `src/core/config.py`)

### Summary Table

| Model | Avg Latency | Avg Words | Avg Chars | Positive Pass | Negative Pass | Avg F1 | Avg Containment |
|-------|------------|-----------|-----------|--------------|--------------|--------|----------------|
| **gpt-5.1** | 5,202ms | 61 | 410 | **10/10** | **9/9** | **0.260** | **1.000** |
| gpt-4.1 | 6,026ms | 103 | 674 | **10/10** | **9/9** | 0.148 | **1.000** |
| gpt-4.1-mini | 6,129ms | 95 | 615 | 9/10 | **9/9** | 0.154 | 0.900 |
| gpt-5-mini | 3,200ms | 26 | 215 | 0/10 | 5/9 | 0.012 | 0.000 |
| gpt-5-nano | 10,447ms | 26 | 215 | 0/10 | 5/9 | 0.012 | 0.000 |

### Key Findings

1. **gpt-5-mini and gpt-5-nano are broken** — they returned HTTP 400 because these models
   don't support custom `temperature` (only default=1). Every response was an error message
   (268 chars). Fix committed: `a4b88946` skips `temperature` for these models. Needs redeploy to test.

2. **gpt-5.1 remains the best** — perfect accuracy (10/10 positive, 9/9 negative), highest F1 (0.260),
   and produces the **most concise answers** (avg 61 words vs gpt-4.1's 103 words).

3. **gpt-4.1 is a viable cheaper alternative** — same accuracy as gpt-5.1 (10/10, 9/9) but
   lower F1 (0.148) due to more verbose responses. Slightly slower.

4. **gpt-4.1-mini dropped a positive test** — 9/10 positive pass (Q-N3 negative test also failed
   in a prior run). Less reliable for edge cases.

### F1 Score Interpretation

F1 is the harmonic mean of precision and recall over token overlap with ground truth.
Route 2 F1 is naturally low because:
- Ground truth answers are terse (e.g. "60 days written notice")
- Model responses include citations, context, and structured formatting
- High recall (containment=1.0) but low precision → low F1

**Containment** (≈ recall) is the primary accuracy metric: "did the answer include the expected information?"

### Per-Question Detail (Positive Tests)

| QID | gpt-5.1 | gpt-4.1 | gpt-4.1-mini |
|-----|---------|---------|-------------|
| Q-L1 | 7,561ms / 85w / 0.28 | 11,703ms / 149w / 0.18 | 7,433ms / 113w / 0.09 |
| Q-L2 | 5,694ms / 105w / 0.07 | 7,455ms / 194w / 0.06 | 8,523ms / 204w / 0.04 |
| Q-L3 | 5,716ms / 44w / 0.42 | 5,504ms / 148w / 0.18 | 6,789ms / 108w / 0.23 |
| Q-L4 | 6,187ms / 124w / 0.10 | 7,653ms / 154w / 0.08 | 5,935ms / 100w / 0.10 |
| Q-L5 | 5,972ms / 66w / 0.22 | 5,454ms / 115w / 0.17 | 7,551ms / 147w / 0.12 |
| Q-L6 | 4,892ms / 79w / 0.33 | 8,382ms / 255w / 0.14 | 10,390ms / 235w / 0.13 |
| Q-L7 | 8,054ms / 142w / 0.29 | 7,064ms / 199w / 0.15 | 10,327ms / 252w / 0.12 |
| Q-L8 | 6,414ms / 60w / 0.26 | 8,515ms / 118w / 0.18 | 8,959ms / 128w / 0.20 |
| Q-L9 | 5,817ms / 46w / 0.43 | 4,845ms / 135w / 0.20 | 5,237ms / 74w / 0.25 |
| Q-L10 | 6,038ms / 43w / 0.29 | 6,182ms / 162w / 0.13 | 7,274ms / 88w / 0.17 |

### Negative Tests

| QID | gpt-5.1 | gpt-4.1 | gpt-4.1-mini |
|-----|---------|---------|-------------|
| Q-N1 | ✅ | ✅ | ✅ |
| Q-N2 | ✅ | ✅ | ✅ |
| Q-N3 | ✅ | ✅ | ❌ |
| Q-N5 | ✅ | ✅ | ✅ |
| Q-N6 | ✅ | ✅ | ✅ |
| Q-N7 | ✅ | ✅ | ✅ |
| Q-N8 | ✅ | ✅ | ✅ |
| Q-N9 | ✅ | ✅ | ✅ |
| Q-N10 | ✅ | ✅ | ✅ |

## Recommendations

1. **Keep gpt-5.1 as default** — best accuracy, most concise, competitive latency.
2. **Redeploy and retest gpt-5-mini/gpt-5-nano** after temperature fix lands.
3. **Consider prompt simplification** — with only ~10 chunks, the 7-rule prompt may be
   over-engineered. A simpler prompt could enable smaller models and faster responses.
4. **gpt-4.1 is a safe fallback** if cost becomes a concern — identical accuracy to gpt-5.1.

## Pending

- [ ] Redeploy temperature fix (`a4b88946`) and retest gpt-5-mini / gpt-5-nano
- [ ] Consider A/B testing a simplified prompt with fewer instruction rules
