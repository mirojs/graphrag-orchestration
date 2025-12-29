# End-of-day handoff (2025-12-26)

## TL;DR
- **Root cause (already fixed):** `Community.summary` was being truncated to ~1200 chars at indexing time, which removed “later sections” (jurisdictions, fees, etc.) and broke Global QA.
- **Current state:** community truncation is fixed (summaries now multi‑KB up to the configured cap), and Global QA improved from 4 failures → **2 failures**.
- **Why 2 failures remain:** they’re now **answer-fidelity + evaluation brittleness** issues:
  - One case is “term exists in evidence but model didn’t reproduce it verbatim”.
  - One case is “question bank expects a composite label string (e.g., `TOTAL/AMOUNT DUE 29900.00`) that does not appear verbatim in community reports”.
- **Decision:** product-correct path (quality + reliability):
  1) Make Global answers reliably quote concrete terms verbatim from evidence.
  2) Improve indexing-time community report generation so invoice label lines (including slash-delimited labels) are preserved when they exist in excerpts.
  3) Reindex into a new group after deploying indexing-time changes.

---

## Where we are
### Deployed and validated earlier
- Community truncation fix is deployed and validated by inspecting `Community.summary` lengths in Aura:
  - Summaries are no longer pinned at ~1200 chars.
  - Observed typical sizes: ~2.8k–8k chars (cap).
- Global question bank run on group `qbank-global-1766777718` now shows **2 failures**.

### The two remaining failures (observed symptoms)
- **Q‑G2 (jurisdictions / governing law):** evidence exists in community summaries, but the final global answer did not include the exact required substring the bank expects.
  - Example symptom: answer lists jurisdictions but omits a specific venue/location string verbatim.
- **Q‑G3 (“who pays what”):** answer includes the correct amount but not the composite string required by the bank.
  - Evidence check we ran previously showed:
    - `29,900.00` appears in multiple community summaries.
    - `TOTAL/AMOUNT DUE` and `29900.00` did **not** appear in `Community.summary` for that group.
  - Interpretation: either the invoice label exists in raw chunk text but didn’t make it into community summaries, or it never exists in chunk text in that exact form.

---

## Why we chose the product-correct path
Success criterion is **quality and reliability**, not “passing a brittle substring check by forcing labels”.

We explicitly rejected the doc-specific approach (hardcoding specific example strings in prompts) because:
- It does not generalize.
- It risks producing ungrounded output when the exact string is not present in evidence.

Instead we’re choosing improvements that generalize across document types:
- Stronger evidence-faithful answer generation (verbatim quoting requirement).
- Stronger evidence shaping at indexing time (ensure community reports preserve invoice label lines when present in excerpts).

---

## What changed locally today (not yet deployed)
> These changes are currently in the workspace. They are intended to be generic (not doc-specific).

1) Global answer fidelity (query-time)
- File: `graphrag-orchestration/app/v3/routers/graphrag_v3.py`
- Change: global map/reduce prompts now instruct:
  - when stating any concrete term (amount/date/jurisdiction/venue), include a short **verbatim quote** from the evidence containing that term.
  - keep numeric values exactly as written; optionally include a normalized numeric form only by stripping separators (do not add decimals).

2) Community report preservation for invoice labels (index-time)
- File: `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
- Change: invoice “label + value” extraction expanded to catch slash-delimited label variants like:
  - `TOTAL/AMOUNT DUE 29900.00`
  - `TOTAL / AMOUNT DUE: $29,900.00`
  This improves the odds that community reports will retain the exact label line when it exists in excerpts.

3) QA harness robustness (evaluation-time)
- File: `graphrag-orchestration/test_phase1_5docs.py`
- Change: for composite backticked anchors (label + number), `_term_variants()` now also yields numeric-only variants.
  - Example: `TOTAL/AMOUNT DUE 29900.00` → variants include `29900.00`.
  This reduces false negatives due to formatting/label variation.

---

## What is deployed vs. what is local
- **Deployed:** community truncation fix (the ~1200 char truncation is gone).
- **Local pending deploy:** the 3 changes above (global prompt quoting, invoice label extraction, QA harness variants).

---

## Tomorrow’s continuation (product-correct)
### Step 0 — Confirm whether invoice label exists in raw chunks
Goal: decide whether we must fix indexing-time excerpt/report capture vs. adjust the bank expectation.

Run a term scan on Aura for `TextChunk.text` (same group) for:
- `TOTAL/AMOUNT DUE`, `AMOUNT DUE`, `SUBTOTAL`, `TOTAL`, `29900.00`, `29,900.00`

Note: In the agent environment today, `NEO4J_PASSWORD` was not available, so we could not run the scan from here without you exporting it in the shell.

### Step 1 — Deploy latest code
- Use the canonical deploy script:
  - `./deploy-graphrag.sh`

### Step 2 — Reindex into a NEW group
Because we changed indexing-time report generation, we must reindex to validate the fix.
- Create a new group ID (e.g., `qbank-global-<ts>`), run `/graphrag/v3/index`, and wait for communities.

### Step 3 — Rerun Global question bank on the new group
- Run the global bank with answers/sources printed to validate:
  - Q‑G2: verbatim term appears in answer (via quote requirement)
  - Q‑G3: invoice total evidence appears as a preserved label line **if** it exists in raw chunks.

### Step 4 — Verify in Neo4j
- Confirm that new group’s `Community.summary` contains invoice label lines and key jurisdiction/venue phrases.

---

## Notes / constraints
- Indexing-time changes require a new group reindex.
- Query-time prompt improvements can be A/B tested against the existing group, but the product-correct invoice label preservation requires reindex.
- We intentionally keep Global “report-driven”; we avoid query-time chunk heuristics to maintain reliability and avoid hallucinations.
