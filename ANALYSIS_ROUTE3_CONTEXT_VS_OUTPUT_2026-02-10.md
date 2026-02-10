# Route 3 Context vs. Output Analysis — February 10, 2026

## Objective

Compare the context fed into the synthesis LLM with its output to identify
improvement opportunities.  Four representative questions were sent to the
deployed API (`force_route=global_search`, `include_context=true`) and the
full `llm_context` + response were captured.

**Test group:** `test-5pdfs-v2-fix2`  
**Deployed commit:** `8c024300` (D1-D4 denoising defaults ON)  
**Model:** GPT-4o via Azure OpenAI  

---

## Questions Tested

| QID | Query | Ctx chars | Ans chars | Chunks (after dedup) |
|-----|-------|-----------|-----------|---------------------|
| Q-G1 | Termination/cancellation rules | 20,482 | 10,226 | 11 (from 18) |
| Q-G3 | "Who pays what" — fees/charges/taxes | 23,929 | 12,395 | 11 (from 19) |
| Q-G6 | Named parties/organizations per document | 15,207 | 10,452 | 10 (from 18) |
| Q-G10 | Each document's main purpose in one sentence | 16,316 | 7,216 | 12 (from 21) |

---

## Finding 1: Retrieval Gaps — Key Facts Never Reach the LLM

The most impactful issue: certain ground-truth facts are **absent from the
retrieved context entirely**, so the LLM has no chance of including them.

### Q-G1 — Warranty transferability missing

| Expected Fact | In Context? | In Answer? |
|---------------|:-----------:|:----------:|
| PMA 60 days written notice | ✅ | ✅ |
| Purchase cancel within 3 business days | ✅ | ✅ |
| Purchase deposit forfeited after window | ✅ | ✅ |
| Holding tank terminates by either party | ✅ | ✅ |
| **Warranty not transferable / terminates on sale** | **❌** | ❌ |

The warranty transferability clause was not retrieved.  This is a retrieval-
layer gap — the chunk containing this clause either wasn't linked to the seed
entities or was dropped by dedup/budget.

### Q-G3 — PMA fee table truncated (worst gap)

| Expected Fact | In Context? | In Answer? |
|---------------|:-----------:|:----------:|
| Invoice $29,900 | ✅ | ✅ |
| Purchase 3 installments ($20k / $7k / $2.9k) | ✅ | ✅ |
| PMA 25% commission | ✅ | ✅ |
| **PMA 10% repair fee** | **❌** | ❌ |
| **PMA $75/mo advertising** | **❌** | ❌ |
| PMA $50/mo admin | ✅ | ✅ |
| **PMA $35/hr scheduling** | **❌** | ❌ |
| Hawaii excise tax 4.712% | ✅ | ✅ |
| Holding tank — owner pays pumper | ✅ | ✅ |

**3 of 7 PMA fee line items are missing from context.**  The AGENT'S FEES
chunk is cut mid-text — it includes the 25% commission and $50/mo admin
but truncates before the 10% repair, $75/mo advertising, and $35/hr
scheduling items.

**Root cause:** Chunk boundary or section splitting cuts the AGENT'S FEES
section before all fee items are captured.  This is the highest-impact
retrieval problem identified.

### Q-G6 — "Contoso Lifts LLC" entity absent

| Expected Party | In Context? | In Answer? |
|----------------|:-----------:|:----------:|
| Fabrikam Inc. | ✅ | ✅ |
| Contoso Ltd. | ✅ | ✅ |
| **Contoso Lifts LLC** | **❌** | ❌ |
| Walt Flood Realty | ✅ | ✅ |

The Purchase Contract contractor ("Contoso Lifts LLC") is not in the
retrieved chunks.  The purchase contract chunks that ARE retrieved mention
product specs and delivery terms but not the contractor's full legal name.

### Q-G10 — Full coverage ✅

All 5 documents' purposes are represented in context and answer.  This is the
cleanest result.

---

## Finding 2: Preamble Overhead — Redundant Entity/Relationship Section

Every query's context begins with a structured preamble:

```
## Entity Descriptions:
- **Builder's Limited Warranty**: Warranty coverage for ...
- **Fabrikam Inc.**: Builder providing ...
...

## Entity Relationships:
- Fabrikam Inc. → Contoso Ltd.: Co-occur in 10 chunk(s)
- Fabrikam Inc. → AAA: Co-occur in 5 chunk(s)
... (20 relationships per query)
```

### Measurements

| QID | Preamble chars | % of total context | Entities in preamble also in chunks |
|-----|---------------|-------------------|-------------------------------------|
| Q-G1 | 2,104 | 10% | 6/7 (86%) |
| Q-G3 | 2,268 | 9% | 7/8 (88%) |
| Q-G6 | 2,607 | 17% | 7/7 (100%) |
| Q-G10 | 2,619 | 16% | 9/9 (100%) |

### Problems

1. **Relationship lines are information-free.** "Fabrikam Inc. → AAA:
   Co-occur in 5 chunk(s)" tells the LLM nothing actionable.  It doesn't
   explain *what* the relationship is — just co-occurrence counts.

2. **Entity descriptions duplicate chunk content.** 86-100% of entities
   described in the preamble also appear in the chunk text with more detail.

3. **Token waste.** 2,100–2,600 chars (~500–650 tokens) per query that could
   hold additional document content — potentially enough to include the
   missing PMA fee items from Finding 1.

### Recommendation

- **Remove** the "Entity Relationships" section entirely (co-occurrence
  counts provide no synthesis value).
- **Keep** entity descriptions only if they add information not in chunks
  (consider conditional inclusion).
- **Net savings:** ~1,500–2,000 chars per query (~400–500 tokens freed).

---

## Finding 3: Answer Verbosity — LLM Over-Explains Absence

### Output / Input ratio

| QID | Context | Answer | Ratio |
|-----|---------|--------|-------|
| Q-G1 | 20,482 | 10,226 | 0.50x |
| Q-G3 | 23,929 | 12,395 | 0.52x |
| Q-G6 | 15,207 | 10,452 | 0.69x |
| Q-G10 | 16,316 | 7,216 | 0.44x |

The ratios are reasonable (0.44–0.69x), but qualitative review shows padding:

### Specific verbosity issues

1. **Explaining what documents DON'T say.**  In Q-G1 the warranty section
   spends ~6 lines explaining the *absence* of termination clauses, then
   ~4 more lines in Cross-References restating the same absence.  The user
   asked for rules that *exist*, not for exhaustive coverage of what's
   missing.

2. **Answer / Supporting Details / Cross-References repeat each other.**
   The three-section output format (`## Answer`, `## Supporting Details`,
   `## Cross-References`) causes the LLM to re-state the same facts in
   progressively more detail, inflating output by ~30-40%.

3. **Boilerplate hedging.** Phrases like "in the provided text",
   "in the available portion of this agreement", "does not itself create a
   right or procedure" add length without information.

### Recommendation

- Add prompt guidance: *"Focus on facts that ARE stated. Mention absence
  only briefly (one line per document). Do not repeat the same fact across
  Answer and Supporting Details."*
- Consider making the Cross-References section optional / conditional on
  whether genuine cross-document connections exist.

---

## Finding 4: Context Structure Observations

### What's working well

- **Document grouping** (`=== DOCUMENT: ... ===`) is clean and helps the LLM
  organize answers by source document.
- **Chunk citation markers** (`[1]`, `[2]`, etc.) are correctly used by the
  LLM — every claim has citations.
- **Section metadata** (`[Section: PURCHASE CONTRACT > ...]`) gives the LLM
  provenance for each chunk.
- **Dedup is effective** — 7-9 chunks removed per query (38-43% reduction)
  with no loss of unique content.

### Entity descriptions — mixed value

The hub entity descriptions at the top serve as a "map" for the LLM:
```
- **AGENT'S FEES**: Section describing agent's fees and commissions
- **Hawaii Gross Excise tax**: Currently at 4.712% on fees/commissions
```
These are sometimes the ONLY place a fact appears (e.g., the 4.712% tax rate
in the entity description for Q-G3).  So entity descriptions can't be fully
removed without checking whether they carry unique information.

---

## Summary: Ranked Improvement Opportunities

| Priority | Issue | Category | Expected Impact |
|----------|-------|----------|----------------|
| **1** | PMA AGENT'S FEES chunk truncated — 3 fee items lost | Retrieval/chunking | High: fixes Q-G3's 3 missing facts |
| **2** | Strip "Entity Relationships" preamble (co-occurrence counts) | Prompt/context | Medium: frees ~500 tokens per query |
| **3** | Tighten system prompt to reduce verbosity and repetition | Prompt engineering | Medium: shorter, more focused answers |
| **4** | Warranty transferability clause not retrieved (Q-G1) | Retrieval | Low-medium: fixes 1 fact |
| **5** | "Contoso Lifts LLC" entity not in retrieved chunks (Q-G6) | Retrieval/entity extraction | Low: fixes 1 fact |

---

## Raw Data

Captured responses saved to `/tmp/ctx_review/all_results.json` (local only,
not committed — contains full `llm_context` and `response` for all 4 questions).
