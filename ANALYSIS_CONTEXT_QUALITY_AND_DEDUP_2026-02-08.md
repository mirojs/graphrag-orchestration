# Context Quality Analysis: Duplicate Chunks and Structured-Data Noise

**Date:** 2026-02-08  
**Scope:** Route 3 (Global Search) synthesis pipeline — `test-5pdfs-v2-fix2` group  
**Data source:** `benchmarks/synthesis_model_comparison_20260208T153555Z.json` (captured LLM contexts for 10 questions)  
**Benchmark results:** `benchmarks/synthesis_model_comparison_20260208T160737Z.json` (5-model synthesis comparison)

---

## 1. Executive Summary

During the Route 3 synthesis model comparison, we discovered that **56.5% of all chunks** sent to the synthesis LLM are **exact duplicates**. Additionally, many "unique" chunks consist of form labels, bare headings, or structural fragments rather than narrative content. These issues cause all five tested LLMs to miss key themes even when the relevant terms appear dozens of times in the input context.

**Key numbers:**
- 3,875 total chunks across 10 questions
- 2,191 exact duplicates (56.5%)
- "Date:" appears as a standalone chunk up to **12 times** in a single query context
- The word "pumper" appears **26 times** in Q-G6's context but is missed by **all 5 models**
- The word "default" appears only **1 time** as a bare heading in Q-G5 — missed by all 5 models

---

## 2. Duplicate Chunk Statistics

### 2.1 Per-Question Breakdown

| Question | Total Chunks | Unique | Duplicates | Dupe % | Context Size |
|----------|-------------|--------|------------|--------|-------------|
| Q-G1     | 436         | 187    | 249        | 57.1%  | 83,570 chars |
| Q-G2     | 457         | 177    | 280        | 61.3%  | 92,918 chars |
| Q-G3     | 387         | 151    | 236        | 61.0%  | 82,836 chars |
| Q-G4     | 320         | 145    | 175        | 54.7%  | 57,613 chars |
| Q-G5     | 332         | 185    | 147        | 44.3%  | 69,271 chars |
| Q-G6     | 417         | 186    | 231        | 55.4%  | 80,623 chars |
| Q-G7     | 329         | 149    | 180        | 54.7%  | 71,521 chars |
| Q-G8     | 386         | 148    | 238        | 61.7%  | 70,598 chars |
| Q-G9     | 409         | 183    | 226        | 55.3%  | 87,216 chars |
| Q-G10    | 402         | 173    | 229        | 57.0%  | 82,027 chars |
| **TOTAL**| **3,875**   | **1,684** | **2,191** | **56.5%** | **778,193 chars** |

### 2.2 Most Duplicated Content

The worst offenders across all questions:

| Chunk Content | Max Repeats | Affected Questions |
|---------------|------------|-------------------|
| `Date:` (standalone) | 12× | Q-G2, Q-G3, Q-G8, Q-G9 |
| `Township` (standalone) | 4× | Q-G1, Q-G4 |
| `Hillview` (standalone) | 3× | Q-G1, Q-G4 |
| `1. Scope of Work` (heading only) | 3× | Q-G7, Q-G10 |
| `· $7,000.00 upon delivery` (bullet fragment) | 3× | Q-G7, Q-G10 |
| `made no guarantees (written or verbal) of occupancy…` | 5–6× | Q-G2, Q-G3, Q-G8, Q-G9 |
| `(c) A fee/commission of ten percent (10%)…` | 5–6× | Q-G2, Q-G3, Q-G8, Q-G9 |

### 2.3 Impact on Token Budget

Assuming ~4 chars per token, the total context across 10 questions is ~194K tokens. With 56.5% duplicates:
- **~110K tokens are wasted on duplicate content** per benchmark run
- Deduplication would reduce context to ~84K tokens (43.5% of current)
- This frees token budget for more diverse, relevant chunks

---

## 3. Structured-Data Noise (Form Labels, Bare Headings)

### 3.1 The "Pumper" Problem: Q-G6

**Question:** *"What are the key parties involved in the five contracts?"*  
**Expected theme term:** `pumper`  
**Result:** Missed by **all 5 models** (gpt-5.1, gpt-4.1, gpt-4o-mini, gpt-4.1-mini, gpt-5-mini)

The word "pumper" appears **26 times** in the LLM context. Every single occurrence is a **form label or structural fragment**, not a narrative sentence:

```
[3b]  Pumper's Name:
[3g]  Pumper's Signature
[3h]  This contract is made between the Holding Tank Owner and the Pumper.
[3j]  pumper to have access and to enter upon the property for the purpose of servicing…
[3k]  holding tank(s) with the pumping equipment. The owner further agrees to pay the pumper for a…
[3u]  Pumper's Name (Print)
[3v]  Pumper's Registration Number
[333] The owner agrees to have the holding tank(s) serviced by the pumper and guarantees to permit t…
```

**Why the LLM misses it:** When a model encounters `Pumper's Name:` or `Pumper's Signature`, it reads these as empty form fields — metadata about a document template, not evidence of a contractual party. The LLM has no way to distinguish "Pumper" as a key party role vs. just a field label on a form.

### 3.2 The "Default" Problem: Q-G5

**Question:** *"What dispute resolution and legal terms are specified in any of the contracts?"*  
**Expected theme term:** `default`  
**Result:** Missed by **all 5 models**

The word "default" appears **exactly once** in 69,271 characters of context:

```
[230] 4. Customer Default
```

This is a **bare section heading** with no body text. The chunk contains a numbered heading and nothing else. Without the clause content beneath it, no LLM can determine what "Customer Default" entails or that it's a legal term worth mentioning.

### 3.3 The "Contractor" Paradox: Q-G5

**Expected theme term:** `contractor`  
**Occurrences in context:** 29  
**Result:** Missed by 3/5 models (gpt-4.1, gpt-4o-mini, gpt-4.1-mini)

Despite 29 occurrences, 3 models miss it. The term appears overwhelmingly in signature blocks and headers (`Contractor's Signature:`, `Independent Contractor Agreement`, `Contractor Name:`) rather than in narrative clauses about dispute resolution. The models focus on the substantive question about legal terms and overlook the repeated form labels.

---

## 4. Theme Coverage vs. Duplicate Rate Correlation

| Question | Dupe % | Avg Theme Coverage | Models < 100% |
|----------|--------|-------------------|---------------|
| Q-G2     | 61.3%  | 100.0%            | 0/5           |
| Q-G3     | 61.0%  | 97.5%             | 1/5           |
| Q-G8     | 61.7%  | 90.0%             | 1/5           |
| Q-G10    | 57.0%  | 90.0%             | 2/5           |
| Q-G7     | 54.7%  | 80.0%             | 3/5           |
| Q-G4     | 54.7%  | 76.7%             | 3/5           |
| Q-G1     | 57.1%  | 68.6%             | 2/5           |
| Q-G5     | 44.3%  | 63.3%             | 5/5           |
| Q-G6     | 55.4%  | 62.5%             | 5/5           |
| Q-G9     | 55.3%  | 60.0%             | 2/5           |

**Observation:** The duplicate rate alone does not predict theme coverage. Q-G2 has 61.3% duplicates but achieves 100% coverage, while Q-G5 has 44.3% duplicates but only 63.3% coverage. The critical factor is **chunk content quality** — whether the theme-relevant information exists in the context as narrative text or merely as form labels/headings.

The worst-performing questions (Q-G5, Q-G6, Q-G9) share a common pattern: their missed themes are present only as **structural metadata** (form labels, bare headings, signature blocks) rather than as substantive clauses the LLM can reason about.

---

## 5. Model-by-Question Theme Coverage Matrix

| Model | Q-G1 | Q-G2 | Q-G3 | Q-G4 | Q-G5 | Q-G6 | Q-G7 | Q-G8 | Q-G9 | Q-G10 |
|-------|------|------|------|------|------|------|------|------|------|-------|
| gpt-5.1     |  0%¹ | 100% | 100% |  50% |  67% |  75% | 100% | 100% |   0%¹ | 100% |
| gpt-4.1     | 100% | 100% | 100% |  50% |  67% |  88% |  80% | 100% | 100%  | 100% |
| gpt-4o-mini |  43% | 100% |  88% |  83% |  50% |   0% |  40% |  50% |   0%  |  67% |
| gpt-4.1-mini| 100% | 100% | 100% | 100% |  50% |  88% |  80% | 100% | 100%  |  83% |
| gpt-5-mini  | 100% | 100% | 100% | 100% |  83% |  62% | 100% | 100% | 100%  | 100% |

¹ gpt-5.1 returned empty responses on Q-G1 and Q-G9 — confirmed as a transient API issue (retest produced normal results).

**Findings:**
- **gpt-4o-mini** is the weakest model: responsible for the majority of 1/5 misses and scores 0% on Q-G6 and Q-G9
- **gpt-5-mini** and **gpt-4.1-mini** are the most reliable, with gpt-5-mini achieving 100% on 8/10 questions
- **No model** achieves 100% on Q-G5 or Q-G6 — these are context quality problems, not model capability problems

---

## 6. Complete Catalogue of All Theme Misses

### Missed by ALL 5 models (context quality issues):
| Question | Theme | Occurrences | Nature of Occurrences |
|----------|-------|------------|----------------------|
| Q-G5 | `default` | 1 | Bare heading: `4. Customer Default` — no body text |
| Q-G6 | `pumper` | 26 | All form labels: `Pumper's Name:`, `Pumper's Signature`, etc. |

### Missed by 3/5 models (borderline context quality):
| Question | Theme | Occurrences | Missed By |
|----------|-------|------------|-----------|
| Q-G5 | `contractor` | 29 | gpt-4.1, gpt-4o-mini, gpt-4.1-mini |
| Q-G5 | `legal fees` | 1 | gpt-5.1, gpt-4o-mini, gpt-4.1-mini |
| Q-G6 | `owner` | 173 | gpt-5.1, gpt-4o-mini, gpt-5-mini |
| Q-G7 | `60 days` | 3 | gpt-4.1, gpt-4o-mini, gpt-4.1-mini |

### Missed by 2/5 models:
| Question | Theme | Occurrences | Missed By |
|----------|-------|------------|-----------|
| Q-G1 | `3 business days` | 1 | gpt-5.1¹, gpt-4o-mini |
| Q-G1 | `deposit` | 3 | gpt-5.1¹, gpt-4o-mini |
| Q-G1 | `forfeited` | 1 | gpt-5.1¹, gpt-4o-mini |
| Q-G1 | `full refund` | 1 | gpt-5.1¹, gpt-4o-mini |
| Q-G4 | `expenses` | 9 | gpt-5.1, gpt-4.1 |
| Q-G4 | `income` | 4 | gpt-5.1, gpt-4.1 |
| Q-G4 | `monthly statement` | 2 | gpt-5.1, gpt-4.1 |
| Q-G6 | `agent` | 64 | gpt-4o-mini, gpt-5-mini |
| Q-G9 | `$250` | 5 | gpt-5.1¹, gpt-4o-mini |
| Q-G9 | `3 business days` | 3 | gpt-5.1¹, gpt-4o-mini |
| Q-G9 | `deposit` | 6 | gpt-5.1¹, gpt-4o-mini |
| Q-G9 | `forfeited` | 3 | gpt-5.1¹, gpt-4o-mini |
| Q-G9 | `non-refundable` | 6 | gpt-5.1¹, gpt-4o-mini |
| Q-G9 | `start-up fee` | 19 | gpt-5.1¹, gpt-4o-mini |
| Q-G10 | `scope of work` | 7 | gpt-4o-mini, gpt-4.1-mini |

¹ gpt-5.1 Q-G1/Q-G9 misses are due to transient empty API responses, not model capability.

---

## 7. Root Cause Analysis

The current synthesis pipeline in `src/worker/hybrid_v2/pipeline/synthesis.py` passes retrieved chunks **directly** to the LLM with no intermediate processing:

```
Retrieval → _build_cited_context() → Prompt template → LLM call
```

The `_build_cited_context()` function (line 802+) performs only:
1. Groups chunks by source document
2. Adds `=== DOCUMENT: ... ===` headers
3. Inserts citation markers `[N]`
4. Applies sentence segmentation

It does **not**:
- Deduplicate identical or near-identical chunks
- Filter out low-content chunks (form labels, bare headings, standalone metadata)
- Consolidate structured data (e.g., form fields) into entity descriptions
- Distinguish narrative content from structural/template fragments

### Why this matters for LLMs:

1. **Signal dilution:** 56.5% duplicate content means the LLM's attention is competing across redundant passages. Key information that appears once (like a "Customer Default" section) gets drowned out by 12 copies of `Date:`.

2. **Form-label blindness:** LLMs are trained on predominantly narrative text. When they encounter `Pumper's Name:` they interpret it as an empty form field — metadata about document structure, not evidence that "Pumper" is a contractual party. Even 26 repetitions of this pattern don't overcome the learned heuristic.

3. **Token waste:** ~110K tokens per benchmark run are consumed by duplicates. These tokens could instead hold additional unique evidence or be saved to reduce cost and latency.

4. **Bare heading problem:** A section heading without its body text is semantically unresolvable. `4. Customer Default` could mean almost anything — the LLM correctly refuses to speculate when it has no clause text to ground a claim.

---

## 8. Proposed Solution: Context Distillation Step

### 8.1 Why We Need It

The current pipeline assumes retrieved chunks are clean, unique, and narrative. This assumption fails for OCR-extracted documents containing:
- Repeated form templates (same form fields across pages)
- Section headings without body text (OCR chunking splits heading from content)
- Signature blocks and metadata fields

Adding a **context distillation step** between retrieval and synthesis would address all three problems.

### 8.2 Option A: Post-Retrieval Processing (Recommended)

Insert a processing step between `_build_cited_context()` and the LLM call:

```python
def _distill_context(chunks: list[dict]) -> list[dict]:
    """
    Clean and deduplicate retrieved chunks before synthesis.
    
    Steps:
    1. Exact dedup: Remove chunks with identical normalized text
    2. Near dedup: Merge chunks sharing >90% content (keep longest)
    3. Low-content filter: Remove chunks that are:
       - Only form labels (< 20 chars, ending with ':')
       - Only headings (< 40 chars, no sentences)
       - Only metadata (dates, signatures, page numbers)
    4. Entity extraction: From form-label chunks, extract entity-role 
       pairs (e.g., "Pumper's Name:" → entity: Pumper, role: party)
       and inject as a structured entity summary chunk
    5. Heading consolidation: If a heading chunk exists without body,
       look for adjacent chunks that may contain the body content
    """
```

**Benefits:**
- Reduces context size by ~50%, cutting cost and latency
- Surfaces entities buried in form labels as explicit structured data
- Preserves citation traceability (keep original chunk IDs, mark as consolidated)
- No change to the retrieval or indexing pipeline

**Estimated implementation:** Modify `synthesis.py`, add ~150-200 lines in `_build_cited_context()` or as a new `_distill_chunks()` function called before it.

### 8.3 Option B: Prompt Engineering (Quick Win)

Add an instruction to the synthesis prompt:

```
Before answering, scan all evidence chunks and identify:
1. All named parties, roles, and entities — including those appearing 
   only in form labels, signature blocks, or headers
2. Any section headings that indicate relevant topics, even if 
   the section body is not provided

Then incorporate these findings in your answer.
```

**Benefits:**
- Zero code change to the pipeline
- Quick to test and iterate

**Drawbacks:**
- Burns additional output tokens on entity scanning
- Relies on the LLM overcoming its form-label blindness (not guaranteed)
- Doesn't reduce the duplicate chunk problem

### 8.4 Option C: Combined Approach

Implement Option A for deduplication and low-content filtering (handles the 56.5% duplicate waste and bare heading problem), and add Option B's prompt instruction for form-label entity extraction (handles the "pumper" pattern without needing NLP in Python). This gives the best of both worlds.

---

## 9. Implementation Priority

| Priority | Change | Impact | Effort |
|----------|--------|--------|--------|
| **P0** | Exact chunk deduplication | Eliminates 56.5% waste, ~50% cost reduction | Small (hash-based, ~30 lines) |
| **P1** | Low-content chunk filtering | Removes `Date:`, signature blocks, form metadata | Medium (~50 lines + tuning) |
| **P1** | Prompt entity-scan instruction | Addresses form-label blindness for named parties | Small (prompt text change) |
| **P2** | Near-duplicate merging | Handles chunks with minor OCR variations | Medium (~50 lines) |
| **P2** | Heading-body consolidation | Fixes bare heading problem (e.g., "Customer Default") | Medium (requires chunk adjacency logic) |
| **P3** | Form-label entity extraction | Converts `Pumper's Name:` → structured entity list | Large (~100 lines + testing) |

---

## 10. Expected Outcome

After implementing P0 + P1 changes:

- **Context size:** Reduced ~50-60% (from ~80K chars to ~35-40K chars per question)
- **Token cost:** Proportional reduction in input tokens → lower API cost
- **Latency:** Shorter context → faster synthesis (especially for slower models)
- **Theme coverage:** Expected improvement on Q-G5 (`default` — if heading consolidation is included) and marginal improvement on Q-G6 (`pumper` — if prompt instruction is added)
- **No LLM change needed:** The pipeline improvement works regardless of which synthesis model is used

---

## Appendix A: Methodology

- All data from **5-model synthesis comparison** run on 2026-02-08
- Models tested: gpt-5.1, gpt-4.1, gpt-4o-mini, gpt-4.1-mini, gpt-5-mini
- Context captured from live API with `include_context=true`, then replayed through each model via direct Azure OpenAI calls
- Duplicate detection: exact match after stripping citation sub-markers (`[Na]`, `[Nb]`)
- Theme coverage: keyword matching against per-question expected term lists from `benchmark_route3_global_search.py`

## Appendix B: Files Referenced

- Context data: `benchmarks/synthesis_model_comparison_20260208T153555Z.json`
- Benchmark results: `benchmarks/synthesis_model_comparison_20260208T160737Z.json`
- Synthesis pipeline: `src/worker/hybrid_v2/pipeline/synthesis.py` (lines 802-1000: `_build_cited_context()`)
- Benchmark script: `scripts/benchmark_synthesis_model_comparison.py`
- Route 3 benchmark: `scripts/benchmark_route3_global_search.py`
