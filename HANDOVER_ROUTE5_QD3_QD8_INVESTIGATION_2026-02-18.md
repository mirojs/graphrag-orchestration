# Route 5 Benchmark Investigation — Handover Document
**Date:** 2026-02-18  
**Context:** Route 4 benchmark questions (19 Q-D/Q-N) × 3 repeats on Route 5 (unified_search)

---

## Benchmark Results Summary

| Metric | Value |
|--------|-------|
| **LLM Eval Score** | 54/57 (94.7%) |
| **Questions Passing** | 18/19 |
| **Only Failure** | Q-D8 (1/3 runs passed) |
| **Close Call** | Q-D3 (2/3 runs passed, but missing timeframes in all) |

---

## Q-D8: Invoice Count Inconsistency

### Question
> "How many invoices has each company issued?"

### Ground Truth
> Fabrikam Construction Inc.: 4 invoices; Contoso Lifts LLC: 4 invoices (total 8)

### What Happens
- **Retrieval is 100% deterministic** — all 3 runs have identical NER entities, seed counts, evidence_path (Jaccard similarity = 1.0), and 24 text_chunks_used.
- **LLM synthesis is non-deterministic** — the LLM gives 3 different answers:
  - Run 1: Fabrikam=5, Contoso=4 ❌ (double-counts Fabrikam)
  - Run 2: Tied at 4 each ✅
  - Run 3: Fabrikam>3, Contoso=3 ❌ (miscounts both)

### Root Cause
**Entity disambiguation in the synthesis prompt.** The corpus contains "Fabrikam Construction" and "Fabrikam Inc." — the LLM inconsistently merges/splits these entities when counting invoices. This is NOT a retrieval problem; the correct chunks are always present.

### Fix Options (Not Yet Implemented)
1. **Prompt-level fix:** Add explicit entity disambiguation instructions to the synthesis prompt (e.g., "treat Fabrikam Construction and Fabrikam Inc. as the same entity")
2. **Metadata enrichment:** Include document→entity relationship mapping in the synthesis context so the LLM can see which invoices belong to which entity
3. **Pre-synthesis entity resolution:** Run entity co-reference resolution on retrieved chunks before synthesis

### Priority
Medium — this is a synthesis-layer issue, not architectural. The retrieval pipeline works correctly.

---

## Q-D3: Missing Purchase Contract Timeframes

### Question
> "Compare time windows, notification periods, and deadlines across all five documents."

### Ground Truth (6 required timeframes)
1. 10-year Builders Limited Warranty (1-year structural warranty within)
2. 90-day labor warranty (Purchase Contract)
3. 3 business day cancellation window (Purchase Contract)
4. 12-month Property Management Agreement term
5. 180-day notice to vacate (PM Agreement)
6. Holding Tank servicing schedule/deadlines

### What Happens
Even in "passing" runs, only 4-5 of 6 timeframes are found. **The 90-day labor warranty and 3-day cancellation window from the Purchase Contract are NEVER retrieved in ANY of the 3 runs.**

### Root Cause: Cascading Retrieval Failure

This is a **retrieval failure**, not a synthesis failure. The failure chain:

#### 1. NER Returns Empty
The abstract query "Compare time windows, notification periods, and deadlines" has no named entities → tier1=0 seeds. All weight redistributes to tier2.

#### 2. Over-Broad Section Matching (`resolve_section_entities`)
```sql
WHERE s.title = path
   OR path CONTAINS s.title    ← PROBLEMATIC
   OR s.title CONTAINS path
```
For `path = "PURCHASE CONTRACT"`, clause 2 matches ANY section whose title is a substring — e.g., a section titled just "CONTRACT" from Builders Limited Warranty. This pulls BLW entities into the pool under the Purchase Contract's name.

#### 3. Flat Weight Dilution
With 41 structural seeds, each gets `1.0 / 41 ≈ 0.024`. If Purchase Contract resolves only 3-5 entities but BLW resolves 25+, Purchase Contract gets ~12% teleportation mass vs ~73% for BLW.

#### 4. Community Penalty (synthesis.py)
Top-3 PPR entities (all BLW cluster) define the "target community." Purchase Contract entities in a different Louvain community get **0.3× penalty**.

#### 5. Score-Gap Pruning (synthesis.py)
Finds the largest relative score drop and prunes everything below it. After community penalty, Purchase Contract entities sit below the gap → **pruned entirely**.

#### 6. Score-Weighted Chunk Budget
Top PPR entity gets 12 chunks; low-score entities get 1. Even if a PC entity survives, it gets minimal chunk budget.

#### 7. Sentence Evidence Ranking
Sentence search hits (if any) get `min_entity_score × 0.5` — ranked below ALL entity-retrieved chunks, likely truncated from context window.

**Result:** ZERO Purchase Contract chunks in final context → LLM cannot answer the 90-day labor warranty or 3-day cancellation window.

### Evidence from Benchmark Data
- `structural_sections` includes "PURCHASE CONTRACT" in ALL 3 runs
- Citations across ALL 3 runs: only Warranty (8-10 chunks), Property Management (2-3 chunks), Holding Tank (1 chunk)
- ZERO purchase_contract chunks in ANY citation
- `evidence_path` contains Exhibit A entities (Savaria V1504 lift specs, "110 VAC 60 Hz" power details) instead of timeframe clauses

---

## Architecture Issues Identified

### Tier 2 Low-Signal Matching
- Section titles are short labels: `"2. Term."`, `"EXHIBIT A"`, `"INVOICE"`, `"PURCHASE CONTRACT"`
- `structural_embedding` was computed from **title + path_key only** — very low semantic signal
- Embedding cosine similarity barely clears 0.25 threshold for relevant sections
- LLM match compensates but introduces non-determinism (Run 2 missed "HOLDING TANK SERVICING CONTRACT")

### Tier 2 Hybrid Mode
- Default mode runs `match_sections_by_embedding` + `match_sections_by_llm` in parallel, unions results
- Embedding match: deterministic but low recall on short titles
- LLM match: better semantic understanding but non-deterministic
- **The Tier 2 mode is NOT the root cause of Q-D3's failure** — even with perfect section selection, the downstream PPR + community penalty + pruning pipeline still eliminates minority-document entities

### Missing Tier Contribution Visibility
- Current metadata reports only `tier1_seed_count`, `tier2_seed_count`, `tier3_seed_count`
- No visibility into which entities came from which tier, effective weights after redistribution, or per-tier contribution to the final PPR teleportation vector
- This makes it hard to diagnose whether the issue is in seed resolution vs PPR vs denoising

---

## Changes Made Today (2026-02-18)

### 1. Section Summary Generation (Ingestion)
**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

New method `_generate_section_summaries()` added as step 4.6.1:
- For each Section node with linked chunks, sends up to 6 chunk excerpts to LLM
- LLM produces 1-2 sentence summary capturing key topics, parties, time periods, obligations
- Stored as `Section.summary` property in Neo4j
- Idempotent — skips sections that already have summaries

### 2. Updated Structural Embedding (Ingestion)
**File:** `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

`_embed_section_structural()` now embeds `title + path_key + summary` instead of just `title + path_key`:
- Before: `"PURCHASE CONTRACT"` → low semantic signal
- After: `"PURCHASE CONTRACT — Covers the 3 business day cancellation window, 90-day labor warranty, and contractor obligations per the residential purchase agreement."` → rich semantic signal
- Falls back to title+path_key when no summary exists

### 3. Updated LLM Section Matching (Query Time)
**File:** `src/worker/hybrid_v2/pipeline/seed_resolver.py`

`match_sections_by_llm()` now includes summaries in the LLM prompt:
- Before: `"1. PURCHASE CONTRACT"`
- After: `"1. PURCHASE CONTRACT — Covers the 3 business day cancellation window..."`
- LLM can now make informed section selections based on actual content

### 4. Tier Contribution Metadata (Query Time)
**File:** `src/worker/hybrid_v2/pipeline/seed_resolver.py` + `src/worker/hybrid_v2/routes/route_5_unified.py`

New `tier_contribution` block in metadata:
- Reports per-tier entity IDs, effective weights after redistribution, total weight mass per tier
- Enables diagnosing whether retrieval failures are in seed resolution vs PPR vs denoising

---

## TODO — Remaining Work

### High Priority
- [ ] **Re-index with section summaries:** Run re-indexing on test-5pdfs-v2-fix2 to populate `Section.summary` and regenerate `structural_embedding` with enriched text. This is required before any section-summary-related improvements take effect.
- [ ] **Fix over-broad section matching:** Tighten the `path CONTAINS s.title` clause in `resolve_section_entities()` — require minimum title length (e.g., 4+ chars) or use exact-only matching to prevent generic titles like "CONTRACT" from cross-contaminating seed pools.
- [ ] **Per-section weight allocation:** Change `build_unified_seeds()` to distribute weight equally across *sections* first, then within each section across entities. Currently a section with 25 entities gets 25× the influence of a section with 1 entity.
- [ ] **Community penalty bypass for cross-doc queries:** When `structural_sections` span multiple documents, disable community penalty or run per-document PPR to ensure minority documents aren't systematically eliminated.
- [ ] **Re-run Route 5 benchmark** after re-indexing + fixes to validate improvements on Q-D3.

### Medium Priority
- [ ] **Q-D8 entity disambiguation:** Add synthesis prompt instructions for entity co-reference resolution, or pre-merge entity variants before counting.
- [ ] **Tier 2 mode evaluation:** Compare embedding-only vs LLM-only vs hybrid on full benchmark after section summaries are populated, to determine if LLM mode non-determinism is worth the recall improvement.
- [ ] **Sentence evidence ranking:** Consider giving sentence-search hits higher initial scores (currently capped at `min_entity_score × 0.5`), especially when NER is empty and sentence search is the only content-based signal.

### Low Priority / Investigation
- [ ] **Document scoping filter:** Investigate whether `DOC_SCOPE_ENABLED=1` is filtering out Purchase Contract chunks even when its entities survive PPR. The IDF-weighted entity→document voting may be biased toward BLW when BLW entities dominate.
- [ ] **Adaptive weight profiles:** For cross-document comparison queries (detected by structural_sections spanning 3+ documents), automatically switch to a profile with lower w1 / higher w2 to give structural seeds more influence.
- [ ] **Score-gap pruning threshold:** Evaluate whether `SCORE_GAP_THRESHOLD=0.5` is too aggressive for cross-doc queries where entities from different documents naturally form score gaps.

---

## Session Notes — 2026-02-19: Proposed Improvements to Section-to-Sentence Pipeline

Five ideas raised for discussion. Commentary below in context of the current architecture.

---

### Idea 1: Semantic Search (Bi-encoder) vs Cross-Encoder for Section Summary Matching

**Current state:** `match_sections_by_embedding` encodes the query independently, encodes each section's `title + path_key + summary` independently, and scores by cosine similarity. This is a bi-encoder / dual-encoder approach.

**Cross-encoder alternative:** Encodes (query, section_summary) *jointly* in a single forward pass → one relevance score per pair. Direct interaction between query and document tokens during encoding rather than comparing opaque vectors.

**Why cross-encoder is better here:**
- Abstract queries like "Compare time windows, notification periods, and deadlines" are hard to embed faithfully in isolation. The bi-encoder must produce a single vector that captures all possible content the query might be about, while the cross-encoder can directly ask: "Does this section actually discuss the notification periods and deadlines the query is asking about?"
- Q-D3 is the canonical example: bi-encoder similarity between the abstract query and "PURCHASE CONTRACT — Covers the 3 business day cancellation window..." may still underrank relative to Builders Limited Warranty (which has a longer, richer summary). Cross-encoder would directly assess which sections are *most relevant* to the specific comparison question.
- With ~20–30 sections across 5 docs, the compute cost is negligible — cross-encoder runs N forward passes where N ≈ 25, not tens of thousands.

**Practical options:**
- `cross-encoder/ms-marco-MiniLM-L-6-v2` (open, local, fast, good quality)
- Voyage's re-ranker API if already available in the stack
- Use as a *re-ranker* on top of the existing cosine pre-filter (fast pre-filter → top-10 candidates → cross-encoder re-rank → top-k) for future scalability

**Verdict: Cross-encoder is clearly better for this task.** Replace or augment `match_sections_by_embedding` with a cross-encoder re-ranker. The LLM match (`match_sections_by_llm`) already does something semantically equivalent but is non-deterministic and expensive — a cross-encoder gives the same quality improvement deterministically.

---

### Idea 2: Context (Header + Structural Link + Sentence Index) as Part of the Seed

**Proposal:** When section matching (idea 1) identifies a relevant section, the seed payload should include not just the section's entities, but the context needed to identify *which sentences* are relevant within that section.

**Current state:** Matching a section → resolving all entities linked to that section → flat PPR seeds. No sub-section granularity.

**Richer seed representation:**
```
{
  "section": "PURCHASE CONTRACT",
  "path_key": "purchase_contract",
  "document": "Purchase_Contract.pdf",
  "structural_link": Section node ID,
  "sentence_indices": [3, 7, 12],   ← which sentences matched (from idea 3)
  "match_score": 0.87
}
```

**Why this matters:**
- Currently, a section with 25 entities contributes 25× the teleportation mass of a section with 1 entity (the per-section weight dilution noted in the TODO). Knowing *which* sentences matched lets us seed only the entities linked to *those* sentences, not the whole section.
- The sentence indices carry forward as context for the synthesis step — "We retrieved these sentences because sentences 3, 7, 12 in PURCHASE CONTRACT matched" — enabling more precise chunk window construction.
- We already have `header` (section title) and `structural_link` (Section node). The only missing piece is sentence-level position, which is idea 3.

**Dependency:** Requires idea 3 (sentence index field) to be in place.

---

### Idea 3: Sentence Position Index Within Each Section

**Proposal:** Add a `sentence_index` integer property to each `Sentence` node during ingestion — the 0-based ordinal position within its parent section.

**Current state:** Sentences have `IN_SECTION` → Section, and `NEXT` chaining between sentences. Position can be derived by traversing the `NEXT` chain backwards, but this is slow and not queryable.

**Implementation:** Trivially added during ingestion. The section-sentence assignment loop already iterates sentences in order — just pass the enumerate index.

```python
# lazygraphrag_pipeline.py — during sentence creation
for idx, sentence in enumerate(section_sentences):
    sentence.sentence_index = idx
```

**Benefits (beyond idea 2):**
1. **Sentence window retrieval:** After matching sentence_index=7, retrieve sentences 5–9 as a coherent context window without relying on `NEXT` traversal.
2. **Diagnostic visibility:** When a section matches but the pipeline fails to retrieve its content, we can report "section matched on sentences [3,7,12]" in metadata, making failures inspectable.
3. **Seed precision:** Seed the entities linked to sentences 3, 7, 12 rather than all ~40+ entities in the section — directly counteracts the weight dilution problem.
4. **Zero downside.** Is a plain integer field added at ingestion time. The reindex is already planned and the corpus is small (185 sentences), so cost is negligible.

**Verdict: Do this at reindex time. Pure upside.**

---

### Idea 4: Keyword Search as an Additional Seed Source

**Proposal:** Add a keyword/BM25 search path (e.g., Lucene full-text via Neo4j's `db.index.fulltext.queryNodes()`) as a complementary tier alongside or adjacent to tier 3 (thematic/sentence search).

**Where it helps vs semantic search:**
- Exact legal terms and numbers not well-captured by embeddings: "90-day", "3 business days", "cancellation window", "attorneys' fees", "180-day notice"
- Queries where NER returns zero seeds (tier 1 = 0, as in Q-D3) — keyword search can provide direct sentence hits without needing any entity resolution
- High-precision fall-through: when semantic scores are all low (abstract query, out-of-vocabulary section titles), keyword match on specific terms can provide reliable grounding

**Q-D3 example:** BM25 on "notification period" or "business day" would immediately surface the two missing Purchase Contract sentences ("90-day labor warranty", "3 business day cancellation") that the entire PPR pipeline failed to reach.

**Risks:**
- Common terms (e.g., "agreement", "contract", "notice") will over-match, producing noisy seeds
- May not add value when the query is purely conceptual with no keyword overlap in the target sentences

**Recommended approach — treat as a lower-weight supplement, not a primary tier:**
- Apply BM25 top-k (e.g., top-5) against `Sentence.text` full-text index
- Use a score threshold to filter obvious noise
- Weight keyword seeds at ~50% of semantic tier seeds (or configurable)
- Report separately in metadata (`keyword_seed_count`) for diagnosability
- Label as "Tier 2.5" (between structural and thematic) since it's also content-based but not entity-graph-rooted

**Verdict: Yes, add it — particularly as a safety net when tier 1 is empty and tier 2 structural seeds are weak.** The Q-D3 failure is exactly the scenario keyword search is built for: an abstract query, zero NER entities, structurally-contaminated seeds leading to total Purchase Contract dropout. Keyword search would have caught it. Quality is lower than cross-encoder semantic on average, but for precise legal terms the recall is higher.

---

### Idea 5: Integration View — How the Four Ideas Work Together

The ideas form a coherent stack rather than independent features:

```
Query
  │
  ├─ [Existing] Tier 1: NER → entity seeds (high quality, sparse)
  │
  ├─ [IMPROVED] Tier 2: Section matching
  │     Cross-encoder(query, section_summary) → top-k sections
  │     → for each matched section: resolve entities from matched sentences only
  │       (requires sentence_index from Idea 3)
  │     → seed payload includes {section, path, sentence_indices} as context (Idea 2)
  │
  ├─ [NEW] Tier 2.5: Keyword / BM25 search (Idea 4)
  │     fulltext(query terms) → top-5 sentence hits
  │     → lower weight, but catches exact-term queries with zero NER + weak structural
  │
  └─ [Existing] Tier 3: Thematic sentence semantic search
        → already captures content-based sentence hits
```

**Suggested implementation order:**

| Priority | Idea | Rationale |
|----------|------|-----------|
| 1 | **Idea 3** (sentence index) | Trivial, do at reindex, unlocks ideas 2 + precise seeding |
| 2 | **Idea 1** (cross-encoder sections) | High impact on abstract queries, deterministic, replaces LLM match |
| 3 | **Idea 2** (sentence-index-as-seed context) | Depends on 1 + 3; precision improvement for weight dilution |
| 4 | **Idea 4** (keyword search) | Safety net, good ROI for exact-term legal queries |

Note on re-indexing: as planned, the re-index already needs to run to populate `Section.summary` and regenerate embeddings. Sentence index (idea 3) can be added in the same pass at zero marginal cost.

---

### Follow-up Discussion — 2026-02-19

#### (a) Section header vs section summary — why the summary matters for semantic search

The short section title (e.g., `"PURCHASE CONTRACT"`) is where **humans** naturally anchor — it's a meaningful label that a person reading a document would immediately recognise. But cosine similarity on a short title embedding has almost no semantic signal: `"PURCHASE CONTRACT"` is close to any document containing the word "contract", and the embedding has no way to know what content is *inside* the section.

The section summary is specifically designed to fix this for the bi-encoder. Instead of embedding a label, you embed a description of the section's actual content: *"Covers the 3 business day cancellation window, 90-day labor warranty, and contractor obligations."* The query `"Compare time windows, notification periods, and deadlines"` now has overlapping concepts with the summary (`cancellation window` ↔ `time windows`, `90-day` ↔ deadline, etc.) that were completely absent from the title.

**The summary does the heavy lifting for bi-encoder quality.** This is the main contribution of the section summary feature.

#### (b) Does cross-encoder still win when section summaries are available?

The previous analysis of idea 1 assumed the embedding was title-only. With summaries included, the question changes:

**With rich summaries, the bi-encoder gap narrows substantially.** For Q-D3, the bi-encoder similarity between the abstract query and "PURCHASE CONTRACT — *Covers the 3 business day cancellation window...*" should now score meaningfully high, and the fix to section matching may already be sufficient to route Purchase Contract entities into the seed pool.

**Cross-encoder still has an edge but for a different reason.** The remaining advantage of the cross-encoder is *joint reasoning*: it can assess "this query asks for a comparison across ALL five documents — does this section contribute to that?" rather than computing independent vectors. For multi-document comparison queries specifically, this matters. For simpler queries where the query and summary have high lexical overlap, bi-encoder with summaries is likely good enough.

**Practical conclusion:**
- Try bi-encoder + summaries first (already in the plan, zero extra cost)
- If section matching still fails on abstract queries after re-indexing, add cross-encoder as a re-ranker on top
- Cross-encoder is the ceiling, summary-enriched bi-encoder is the cheaper stepping stone; the summary likely captures 80% of the gap

#### (c) Tier Contribution Survey — Are Current Weights Balanced?

From reading `seed_resolver.py`, the current weights and redistribution logic are:

**Default profile (`balanced`): w1=0.5, w2=0.3, w3=0.2**

Other profiles for reference:

| Profile | w1 NER | w2 Structural | w3 Thematic |
|---------|--------|---------------|-------------|
| balanced (default) | 0.5 | 0.3 | 0.2 |
| fact_extraction | 0.6 | 0.3 | 0.1 |
| clause_analysis | 0.3 | 0.5 | 0.2 |
| cross_doc_comparison | 0.2 | 0.3 | 0.5 |
| thematic_survey | 0.1 | 0.2 | 0.7 |

**The real problem is per-seed weight, not tier weight.** The current merging in `build_unified_seeds()` is:

```python
per_seed = tier_weight / len(tier_seeds)   # flat distribution within each tier
```

This means with the balanced profile:
- Tier 1 (5 NER seeds) → each seed gets 0.5/5 = **0.100** weight
- Tier 2 (41 structural seeds, Q-D3 case) → each seed gets 0.3/41 ≈ **0.007** weight
- Tier 3 (say 10 thematic seeds) → each seed gets 0.2/10 = **0.020** weight

A single NER entity gets ~14× more PPR mass than a structural entity. And when NER is empty in Q-D3, the redistribution gives tier2 effective w=0.6/41 ≈ 0.015 per seed — still heavily diluted by the 41-entity pool from over-broad section matching.

**We cannot reliably calibrate the weights — or the keyword search weight — without actual per-tier usage data.** The `tier_contribution` metadata was added specifically to make this visible. The right next step is:

1. Run the benchmark (after re-indexing)
2. Extract `tier_contribution` from each query result in the JSON
3. Look at: effective `weight_mass` per tier, `count` per tier, and overlap
4. For Q-D3 specifically: check if tier2 still has 41 seeds or if the over-broad matching fix reduces it to 3-5 (which would change the per-seed weight from 0.015 to ~0.12 — much healthier)

**Until we have that data, the weights are not well-calibrated for the "zero NER" case.** The `balanced` default is designed for entity-rich queries. For abstract comparison queries, `cross_doc_comparison` (w1=0.2, w2=0.3, w3=0.5) or even a new `abstract_comparison` profile would be more appropriate — but this should be validated against actual tier contribution numbers.

**For keyword search weight calibration:** defer until after the tier contribution survey. A reasonable starting point is to treat keyword seeds as a fraction of tier3 seeds (e.g., add them to tier3 with 50% weight per seed), but empirically check the tier_contribution output to see if they add signal or noise.

---

### Follow-up Discussion (2) — 2026-02-19

#### (b) Is cross-encoder overkill with section summaries in place?

**Likely yes, for this corpus.** Here is the reasoning from what we know about the pipeline:

The LLM section match (`match_sections_by_llm`) already functions as a cross-encoder — and a stronger one: it jointly reasons about the query and all section summaries together, understands multi-document comparison intent, and can weigh relevance holistically. The problem with LLM match was never quality; it was non-determinism and cost. A standard cross-encoder (e.g., ms-marco-MiniLM) would be deterministic and cheaper, but qualitatively it sits *below* the LLM match — it's a step backward on quality, not forward.

With summaries closing the length/signal gap:
- Bi-encoder + summaries should be sufficient for most queries — the semantic overlap between query and summary text is now meaningful
- The LLM match (already present) handles the hard abstract cases and gives cross-encoder-level reasoning; it just needs the summaries to be populated so it also gets richer context per section
- A separate cross-encoder model adds a new dependency for an incremental gain that is likely already covered by the LLM match path

**More importantly: fixing section matching is not sufficient for Q-D3 anyway.** Even if every section is matched perfectly, the failure cascade has 5 more steps — weight dilution from 41 seeds, community penalty, score-gap pruning — all of which need separate fixes. The section matching fix (summaries + tighter `path CONTAINS` clause) is the first link in the chain, but cross-encoder vs bi-encoder is not the bottleneck.

**Revised verdict for idea 1:** With summaries:
- Use bi-encoder + summaries as the primary path (already in plan)
- Keep LLM match in hybrid mode as the quality backstop (already available)
- Do NOT add cross-encoder — it is overkill given the LLM match already exists

#### (c) Are all seed sources computed in parallel? → Yes, confirmed from code

All three tiers are launched as concurrent `asyncio` tasks:

```python
# seed_resolver.py lines 802-808
tier1_task = asyncio.create_task(_resolve_tier1())
tier2_task = asyncio.create_task(_resolve_tier2())
tier3_task = asyncio.create_task(_resolve_tier3())
tier1_ids, (tier2_ids, structural_sections), (tier3_ids, community_data) = (
    await asyncio.gather(tier1_task, tier2_task, tier3_task)
)
```

Within tier 2 (hybrid mode), embedding and LLM are also parallel:
```python
# seed_resolver.py lines 745-758
emb_task = asyncio.create_task(match_sections_by_embedding(...))
llm_task = asyncio.create_task(match_sections_by_llm(...))
emb_sections, llm_sections = await asyncio.gather(emb_task, llm_task)
```

**Implication for keyword search (idea 4):** Adding it as a new tier costs essentially zero additional latency. It would be another `asyncio.create_task` inside the same `asyncio.gather` call, running concurrently with tiers 1–3. This makes idea 4 even lower cost than it may appear — the I/O (Neo4j full-text query) executes during the same wall-clock window as the other three tiers.

---

### Follow-up Discussion (3) — 2026-02-19: LLM Role Clarification

#### What `match_sections_by_llm` actually does (and why it should go away)

`match_sections_by_llm` (`seed_resolver.py:205–296`) is a **query-time** LLM call — not a semantic search step. On every user query, it:

1. Fetches all section titles + summaries from Neo4j
2. Sends them to the LLM: *"Which of these sections are relevant to this query?"*
3. Parses the LLM's comma-separated response
4. Returns matched section titles as tier 2 seeds

This is using the LLM as a live section-relevance classifier on every request. It runs in parallel with `match_sections_by_embedding` in hybrid mode (lines 745–758), and their results are unioned.

**This is the wrong place for the LLM.** With section summaries in place:

- The LLM's value was compensating for the low-signal section titles — it could "read" short titles like "PURCHASE CONTRACT" and infer relevance. Now that summaries carry the content signal, the embedding match can do this directly.
- Query-time LLM adds: non-determinism (Run 2 missed "HOLDING TANK SERVICING CONTRACT" in the benchmark), latency, cost per query.
- The LLM's contribution should be at **ingestion time only**: generate the section summary once, then the embedding match uses it for all subsequent queries.

**Recommendation:** After re-indexing with summaries, run the benchmark in embedding-only mode (`ROUTE5_TIER2_MODE=embedding`) and compare to hybrid. If embedding-only matches or exceeds hybrid quality, deprecate `match_sections_by_llm` from the query path.

#### LLM choice for section summarization (ingestion time)

For ingestion-time summarization, the requirements are:

1. **Low hallucination** — the summary must faithfully reflect the chunk content. No invented facts, no overgeneralization. The prompt sends up to 6 chunk excerpts and asks for 1–2 sentences, so the LLM has a tight grounding window.
2. **Speed** — runs once per section at ingestion time (not per query). With ~25 sections across 5 docs, total cost is 25 LLM calls regardless of model.
3. **Factual extraction, not creative writing** — the task is condensing: "What are the key topics, parties, time periods, and obligations in these chunks?" This is a strengths of smaller, low-temperature models.

**Good candidates:**
- **GPT-4o-mini**: fast, low hallucination for extractive tasks, cheap. Already in the stack if using Azure OpenAI.
- **Claude Haiku / 3.5 Haiku**: fast, faithful to source text, good at extracting structure from legal content. Lower temperature defaults.
- Low temperature setting (0.0–0.2) is critical regardless of model — want extractive, not generative.

**What matters less:**
- Model size / capability ceiling — this is a simple extraction task with source text in context.
- Cost — 25 calls per re-index is negligible regardless of model.

**What matters most:** factual grounding and reproducibility. Use the smallest model that reliably extracts key terms (time periods, parties, obligations) from 6 chunk excerpts without adding information not present in the source.

---

## Key File References

| File | Purpose |
|------|---------|
| `src/worker/hybrid_v2/pipeline/seed_resolver.py` | 3-tier seed resolution (NER, structural, thematic) |
| `src/worker/hybrid_v2/routes/route_5_unified.py` | Route 5 handler — orchestrates full pipeline |
| `src/worker/hybrid_v2/pipeline/synthesis.py` | Chunk retrieval, community penalty, score-gap pruning, synthesis |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Ingestion — section graph, summaries, embeddings |
| `scripts/benchmark_route5_unified_r4_questions.py` | Benchmark runner (Route 4 Qs on Route 5) |
| `scripts/evaluate_route4_reasoning.py` | LLM judge evaluation script |
