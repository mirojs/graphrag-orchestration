# Architecture Design Review: Route 3 Updates Needed

**Date:** 2026-02-08  
**Reviewed file:** `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` (last updated February 6, 2026)  
**Based on:** Context quality analysis and 5-model synthesis comparison (Feb 8, 2026)

---

## Summary

The architecture design document needs updates in **6 areas** to reflect findings from the February 8 context quality analysis and synthesis model comparison. The document currently:
- Claims "100% theme coverage" for Route 3 (Jan 25 entry) — this is only true for the default model and doesn't account for context quality issues
- Has no mention of the chunk duplication problem (56.5% of chunks are exact duplicates)
- Is missing the proposed Context Distillation stage (between retrieval and synthesis)
- Has stale Q-G6 EXPECTED_TERMS (missing "pumper")
- Lacks the 5-model synthesis comparison results

---

## Update 1: "Last Updated" Date and Recent Updates Header

**Location:** Lines 1-4 (header)

**Current:**
```markdown
**Last Updated:** February 6, 2026
```

**Change to:**
```markdown
**Last Updated:** February 8, 2026
```

**Add new "Recent Updates" block** before the February 6 block:

```markdown
**Recent Updates (February 8, 2026):**
- 🔍 **Context Quality Analysis: 56.5% Duplicate Chunks in Route 3 Synthesis** — 5-model synthesis comparison revealed that over half of all chunks sent to the synthesis LLM are exact duplicates. Key findings:
  - **3,875 total chunks** across 10 questions, **2,191 exact duplicates** (56.5%)
  - `Date:` appears as a standalone chunk up to **12 times** per query context
  - `pumper` appears **26 times** in Q-G6 context but ALL occurrences are form labels (`Pumper's Name:`, `Pumper's Signature`) — missed by **all 5 models**
  - `default` appears **once** as a bare heading (`4. Customer Default`) with no body text — missed by **all 5 models**
  - Root cause: `_build_cited_context()` passes raw chunks to LLM with no dedup, filtering, or consolidation
  - **Proposed: Context Distillation step** between retrieval and synthesis (new Stage 3.5.1). See Section 23.
  - Analysis document: `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md`
  - Benchmark data: `benchmarks/synthesis_model_comparison_20260208T160737Z.json` (5-model comparison)
- 🔍 **5-Model Synthesis Comparison Complete:** Tested gpt-5.1, gpt-4.1, gpt-4o-mini, gpt-4.1-mini, gpt-5-mini on identical captured contexts:
  - **gpt-4.1-mini** recommended: 95.1% theme coverage, 0.75 containment, 6.6s avg, 10/10 reliability
  - **gpt-5-mini** close second: 94.5% theme coverage, highest accuracy, but no temperature control
  - **gpt-4o-mini** weakest: 42.1% theme coverage, caused majority of misses
  - Script: `scripts/benchmark_synthesis_model_comparison.py` (2-phase: capture context via API, replay through AOAI directly)
```

---

## Update 2: Route 3 Pipeline — New Stage 3.5.1 (Context Distillation)

**Location:** After "Stage 3.5: Raw Text Chunk Fetching" (~line 741), before "Stage 3.5: Synthesis with Citations" (~line 743)

**Current "Stage 3.5: Synthesis" should be renumbered to 3.5.2.**

**Insert new stage:**

```markdown
#### Stage 3.5.1: Context Distillation (PLANNED — February 8, 2026)
*   **Engine:** Python post-processing (no ML/LLM required)
*   **What:** Clean, deduplicate, and filter retrieved chunks before synthesis
*   **Why:** Benchmark analysis revealed **56.5% of chunks are exact duplicates** and many unique chunks are low-content noise (form labels, bare headings, signature blocks). This wastes ~110K tokens per query and causes LLMs to miss key themes even when terms appear 26+ times in context. See Section 23.
*   **Process:**
    1. **Exact dedup** (P0): Hash-based removal of identical chunks after normalizing citation markers
    2. **Low-content filter** (P1): Remove chunks that are solely form labels (`<20 chars ending with :`), standalone dates, or signature blocks
    3. **Near-dedup** (P2): Merge chunks sharing >90% content (keep longest variant)
    4. **Heading consolidation** (P2): If a heading-only chunk exists, attempt to merge with adjacent body chunk
*   **Expected Impact:** ~50-60% context size reduction, improved theme coverage on Q-G5/Q-G6
*   **Status:** Planned. Analysis document: `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md`
*   **Output:** Deduplicated, filtered chunk list ready for synthesis
```

---

## Update 3: January 25 "100% Theme Coverage" Claim Needs Caveat

**Location:** Recent Updates (January 25, 2026) block, ~line 401

**Current:**
```markdown
  - **Results:** All Route 3 questions now achieve 100% theme coverage (Q-G1 through Q-G10)
```

**Change to:**
```markdown
  - **Results:** All Route 3 questions now achieve 100% theme coverage (Q-G1 through Q-G10) *(Note: 100% claim was with default synthesis model. February 8 multi-model analysis revealed context quality limitations — see Section 23. Q-G5 averages 63% and Q-G6 averages 63% when raw chunk noise is factored in.)*
```

---

## Update 4: Q-G6 EXPECTED_TERMS Missing "pumper"

**Location:** Section 3.7, Evaluation Strategy A code block (~line 1395)

**Current:**
```python
    "Q-G6": ["fabrikam", "contoso", "walt flood", "contoso lifts", "builder", "owner", "agent"],
```

**Should match the actual benchmark script** (`scripts/benchmark_route3_global_search.py` line 67):
```python
    "Q-G6": ["fabrikam", "contoso", "walt flood", "contoso lifts", "builder", "owner", "agent", "pumper"],
```

---

## Update 5: Section 3.6 Benchmark Results — Add 5-Model Comparison

**Location:** Section 3.6 "Benchmark Results (Route 3 Thematic)" (~line 1351)

**Append after the existing "Sample Scores" block:**

```markdown
**Updated: 5-Model Synthesis Comparison (February 8, 2026)**

Using captured LLM contexts from Route 3 API calls, replayed synthesis through 5 Azure OpenAI models:

| Model | Avg Theme Coverage | Containment | Avg Latency | Reliability |
|-------|-------------------|-------------|-------------|-------------|
| gpt-5-mini | 94.5% | 0.79 | 7.7s | 10/10 |
| gpt-4.1-mini | 90.1% | 0.75 | 6.6s | 10/10 |
| gpt-4.1 | 88.5% | 0.78 | 15.0s | 10/10 |
| gpt-5.1 | 69.2% | 0.79 | 20.3s | 8/10* |
| gpt-4o-mini | 42.1% | 0.52 | 5.9s | 10/10 |

\* gpt-5.1 returned empty responses on Q-G1/Q-G9 (transient API issue, confirmed working on retest).

**Context Quality Caveat:** Theme coverage is capped by raw chunk quality. Q-G5 (`default`: bare heading, 1 occurrence) and Q-G6 (`pumper`: 26 form-label occurrences) are missed by ALL models regardless of capability. See Section 23 for proposed context distillation fix.
```

---

## Update 6: New Section 23 — Context Distillation Architecture

**Location:** After Section 22 (end of file, before the final `---`)

**Add full new section** covering:

- **23.1 Problem Statement:** Current pipeline passes raw chunks directly to LLM with no intermediate processing
- **23.2 Measured Impact:** Per-question duplicate statistics table (3,875 total, 2,191 dupes = 56.5%)
- **23.3 Concrete Examples:** "Pumper" (26 form labels, missed by 5/5 models) and "Default" (1 bare heading, missed by 5/5)
- **23.4 Theme Coverage Correlation:** Table showing dupe rate vs avg theme coverage — key insight: dupe rate doesn't predict coverage; chunk content quality does
- **23.5 Proposed Architecture:** Diagram of P0 → P1 → P2 distillation pipeline
- **23.6 Implementation Details:** Code for `_dedup_chunks_exact()`, `_filter_low_content()`, and prompt entity-scan instruction
- **23.7 Priority Table:** P0 (exact dedup, ~30 lines) through P3 (form-label entity extraction, ~100 lines)
- **23.8 Expected Outcome:** -50-60% context size, -55% token cost, +10-22pp theme coverage on Q-G5/Q-G6
- **23.9 Relationship to Existing Enhancements:** How this complements §22 (sentence citations), §12 (audit extraction), Fast Mode
- **23.10 Data Sources:** File references for benchmarks, analysis doc, scripts

The full proposed text for Section 23 is available in `ANALYSIS_CONTEXT_QUALITY_AND_DEDUP_2026-02-08.md` (Sections 7-9 map to Section 23 content).

---

## Cross-Reference: Model × Question Theme Coverage

For reference, the complete model-by-question matrix:

| Model | Q-G1 | Q-G2 | Q-G3 | Q-G4 | Q-G5 | Q-G6 | Q-G7 | Q-G8 | Q-G9 | Q-G10 |
|-------|------|------|------|------|------|------|------|------|------|-------|
| gpt-5.1      |  0%¹ | 100% | 100% |  50% |  67% |  75% | 100% | 100% |   0%¹ | 100% |
| gpt-4.1      | 100% | 100% | 100% |  50% |  67% |  88% |  80% | 100% | 100%  | 100% |
| gpt-4o-mini  |  43% | 100% |  88% |  83% |  50% |   0% |  40% |  50% |   0%  |  67% |
| gpt-4.1-mini | 100% | 100% | 100% | 100% |  50% |  88% |  80% | 100% | 100%  |  83% |
| gpt-5-mini   | 100% | 100% | 100% | 100% |  83% |  62% | 100% | 100% | 100%  | 100% |

¹ gpt-5.1 returned empty responses (transient API issue).

**Themes missed by ALL 5 models (context quality, not model capability):**
- Q-G5 `default`: 1 bare heading in 69K chars
- Q-G6 `pumper`: 26 form-label occurrences in 80K chars
