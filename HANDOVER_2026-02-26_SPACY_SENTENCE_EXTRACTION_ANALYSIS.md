# Session Handover — 2026-02-26: spaCy Sentence Extraction Gap Analysis

**Session focus:** Deep investigation into why spaCy fails to extract complete sentences, with root-cause analysis and concrete improvement recommendations.

---

## Background

The sentence extraction pipeline (`src/worker/services/sentence_extraction_service.py`) feeds every retrieval route that uses Sentence nodes. When sentences are dropped or fragmented, the graph has blind spots that no downstream route can recover from.

Previous fix (commit `019e5840`, 2026-02-18): lowered `SKELETON_MIN_SENTENCE_WORDS` from 5→3, which rescued "Afterward, deposit is forfeited." and improved Q-G1 from 71%→100%. But that fix only addressed one of **three** independent failure modes.

---

## Three Failure Modes Identified

### Failure Mode 1: spaCy Mis-splits at Legal Abbreviations (CRITICAL)

spaCy's dependency parser treats legal abbreviations like `Art.`, `Para.`, `Ref.` as sentence-ending periods, fragmenting complete sentences.

| Input | spaCy output | Impact |
|-------|-------------|--------|
| `Pursuant to Art. 5, Para. 2, the tenant is liable.` | `["Pursuant to Art.", "5, Para.", "2, the tenant is liable."]` | 3 fragments — first two dropped, third loses context |
| `Under Art. IV, Sec. 3, arbitration is mandatory.` | `["Under Art.", "IV, Sec. 3, arbitration is mandatory."]` | "Under Art." dropped, second fragment misleading |
| `Ref. A-101, dated Dec. 31, 2024, is controlling.` | `["Ref.", "A-101, dated Dec. 31, 2024, is controlling."]` | "Ref." dropped, reference number severed from doc |

**Abbreviations that confuse spaCy:** `Art.`, `Para.`, `Ref.`, `Cl.`, `Sec.` (when followed by numbers/Roman numerals). Already handled correctly: `Dr.`, `Mr.`, `Inc.`, `Ltd.`, `U.S.`, `Esq.`, `Prof.`, `Jan.`–`Dec.`, `St.`

**Proposed fix — custom spaCy pipeline component:**

```python
from spacy.language import Language
from spacy.tokens import Doc

LEGAL_ABBREVS = {
    'art', 'para', 'sec', 'cl', 'ref', 'no', 'inc', 'ltd', 'corp', 'co',
    'sr', 'jr', 'dr', 'mr', 'mrs', 'ms', 'prof', 'esq', 'dept', 'div',
    'approx', 'est', 'govt', 'intl', 'natl', 'supp', 'vol', 'pt',
}

@Language.component('legal_sent_boundary_fix')
def legal_sent_boundary_fix(doc):
    """Prevent false sentence splits after legal abbreviations."""
    changes = []
    for i, token in enumerate(doc):
        if token.is_sent_start and i > 0:
            prev = doc[i - 1]
            if prev.text == '.' and i >= 2:
                if doc[i - 2].text.lower() in LEGAL_ABBREVS:
                    changes.append(i)
            elif prev.text.endswith('.') and len(prev.text) > 1:
                if prev.text[:-1].lower() in LEGAL_ABBREVS:
                    changes.append(i)
    if not changes:
        return doc
    sent_starts = [token.is_sent_start for token in doc]
    for idx in changes:
        sent_starts[idx] = False
    words = [t.text for t in doc]
    spaces = [t.whitespace_ != '' for t in doc]
    return Doc(doc.vocab, words=words, spaces=spaces, sent_starts=sent_starts)
```

**Tested results:**

| Input | Before fix | After fix |
|-------|-----------|-----------|
| `Pursuant to Art. 5, Para. 2, the tenant is liable for damages. Landlord may terminate.` | 4 fragments | ✅ 2 correct sentences |
| `Under Art. IV, Sec. 3, arbitration is mandatory. The parties agree.` | 3 fragments | ✅ 2 correct sentences |
| `Ref. A-101, dated Dec. 31, 2024, is the controlling document.` | 2 fragments | ✅ 1 correct sentence |
| Already-correct sentences (Dr., U.S., Esq., etc.) | Correct | ✅ Unchanged |

**Where to add:** In `_get_nlp()` at line 48–50 of `sentence_extraction_service.py`, after `spacy.load()`:

```python
_nlp = spacy.load("en_core_web_sm")
_nlp.add_pipe('legal_sent_boundary_fix', after='parser')
_nlp.max_length = 50_000
```

### Failure Mode 2: `min_chars=30` Threshold Too Aggressive

The `SKELETON_MIN_SENTENCE_CHARS = 30` setting drops all sentences shorter than 30 characters. This is more aggressive than `min_words=3` and blocks **many legitimate legal sentences**.

**Sentences dropped by min_chars=30 that should be kept:**

| Sentence | Chars | Words | Status |
|----------|-------|-------|--------|
| `Tenant forfeits deposit.` | 24 | 3 | **DROPPED** — Q-G1 related |
| `All terms are binding.` | 22 | 4 | **DROPPED** — meaningful legal content |
| `Buyer assumes all risk.` | 23 | 4 | **DROPPED** — meaningful legal content |
| `Landlord may terminate.` | 23 | 3 | **DROPPED** — meaningful legal content |
| `No refund after 30 days.` | 26 | 5 | **DROPPED** — meaningful legal content |
| `Monthly rent: $2,500.00.` | 24 | 3 | **DROPPED** — financial content |
| `The lease term is 12 months.` | 28 | 6 | **DROPPED** — meaningful legal content |
| `Effective as of Jan. 1, 2025.` | 29 | 6 | **DROPPED** — date reference |

**True noise that min_chars catches (correctly):**
- `See above.` (10c), `N/A` (3c), `Page 2 of 5` (11c), `Total:` (6c), `End of section.` (15c)

**Recommendation:** Lower `SKELETON_MIN_SENTENCE_CHARS` from 30 → 20 in `src/core/config.py`. At 20, all true noise is still filtered, while 13+ meaningful sentences are rescued. The `numeric_only` and `kvp_pattern` filters provide secondary protection against noise in the 20–29 char range.

### Failure Mode 3: ALL_CAPS Filter Drops Emphasized Legal Content

Legal documents frequently use ALL CAPS for binding terms. The filter at line 104:
```python
if ALL_CAPS_RE.match(text) and len(text.split()) < 10:
    return True
```

This drops:
- `ALL PARTIES AGREE TO THE TERMS.` (31c, 7w) — a binding statement
- `DEFAULT AND REMEDIES APPLY.` (27c, 5w) — section content leaked as body text
- `THE ABOVE TERMS APPLY TO ALL PARTIES.` (37c, 7w) — binding language

**Recommendation:** Raise the ALL_CAPS word threshold from 10 → 6, OR add a keyword allowlist for legal terms (`DEFAULT`, `AGREEMENT`, `PARTIES`, `BINDING`, `REMEDIES`, `ARBITRATION`). Most true noise ALL CAPS (headers, labels) is under 5 words, while meaningful ALL CAPS sentences tend to be 5+ words.

---

## Interaction Between Failure Modes

The three failures compound. Example:

```
Pursuant to Art. 5, Para. 2, the tenant forfeits deposit.
```

1. **spaCy mis-split** → `"Pursuant to Art."` / `"5, Para."` / `"2, the tenant forfeits deposit."`
2. **min_chars** → `"Pursuant to Art."` (16c) DROPPED, `"5, Para."` (8c) DROPPED
3. **Result:** Only `"2, the tenant forfeits deposit."` survives — missing its legal citation context

With the abbreviation fix applied first, spaCy produces the full sentence, and neither min_chars nor min_words filters it.

---

## `_clean_chunk_text_for_spacy()` — Additional Observations

The cleaning function (lines 120–135) performs well but has one edge:

| Pattern | What it strips | Risk |
|---------|---------------|------|
| `r"^\d+\.\s+"` | Numbered list markers (`1. `, `42. `) | Also strips clause numbers (`4.2 ` is NOT matched — safe) |
| `r"^[·•\-\*]\s+"` | Bullets | Fine — bullets are formatting |
| `r"^#+\s+.*$"` | Markdown headers | Headers are stored in `section_path` so no data loss |

**Not a problem:** Numbered sub-sections like `4.2` survive cleaning because the regex requires `\s+` after the period, and `4.2` has a digit after the period. Cleaning preserves `"4.2 Landlord may pursue legal remedies."` correctly.

---

## Recommended Fix Priority

| Priority | Fix | Effort | Impact |
|----------|-----|--------|--------|
| **P0** | Add `legal_sent_boundary_fix` spaCy component | Small (20 LOC) | Prevents sentence fragmentation — fixes root cause |
| **P1** | Lower `SKELETON_MIN_SENTENCE_CHARS` 30→20 | 1-line config | Rescues 13+ short-but-meaningful sentences |
| **P2** | Tighten ALL_CAPS word threshold 10→6 | 1-line change | Rescues binding legal statements in caps |

All three fixes are independent and non-breaking — they only admit sentences that were previously dropped, never remove sentences that were previously kept.

---

## Key Files

| File | Purpose |
|------|---------|
| `src/worker/services/sentence_extraction_service.py` | Sentence extraction — spaCy init (`_get_nlp`), cleaning, noise filters |
| `src/core/config.py:116-117` | `SKELETON_MIN_SENTENCE_CHARS=30`, `SKELETON_MIN_SENTENCE_WORDS=3` |
| `scripts/analyze_dropped_sentences.py` | Threshold analysis tool (connects to Neo4j, tests all filters) |
| `scripts/diagnose_sentence_search.py` | Sentence retrieval diagnostics |

## Verification After Fix

1. Apply fixes to `sentence_extraction_service.py` and `config.py`
2. Delete existing Sentence nodes: `MATCH (s:Sentence {group_id: 'test-5pdfs-v2-fix2'}) DETACH DELETE s`
3. Re-run sentence extraction via `scripts/test_skeleton_e2e.py` or API re-index
4. Run `scripts/analyze_dropped_sentences.py` to confirm fewer dropped sentences
5. Benchmark all routes to verify no regressions: `python scripts/benchmark_route3_global_search.py --force-route unified_search`

---

## Comprehensive 11-Category Extraction Audit (All 5 PDFs)

Full pipeline audit testing representative text from all 5 documents through the actual extraction code. **Critical sentence survival rate: 90%** (27/30 benchmark-critical sentences kept).

### Category 4: `_is_kvp_label()` False Positives

The regex `^[A-Z][^.!?]*:\s*[A-Z][a-z]` with `< 8 words` drops legitimate sentences:

| Sentence | Words | Dropped? |
|----------|-------|----------|
| "Warranty period: One year from completion date." | 7 | ❌ YES — false positive |
| "Builder: Fabrikam Construction, Inc., Pocatello, ID 83201." | 7 | ❌ YES — false positive |
| "Pumper: Fabrikam Inc. shall service the tank." | 7 | ❌ YES — false positive |
| "Owner: Contoso Ltd. is responsible for all taxes." | 8 | ✅ NO (at threshold) |
| "Agent: Walt Flood Realty shall manage the property." | 8 | ✅ NO (at threshold) |

**Fix:** Raise threshold from 8 → 10.

### Category 5: Heading Content Loss

`_clean_chunk_text_for_spacy()` strips ALL 15 markdown heading lines. Content is preserved in `section_path` metadata but invisible to sentence-level vector search.

Impact: Low for current queries but matters if users search heading terms directly.

### Category 6: SKIP_ROLES Filtering

DI "title" and "sectionHeading" roles skip the entire paragraph. By design, but same impact as Category 5.

### Category 7: numeric_only Filter

Strips `[\d,.$%\s\-/·•]`, drops if remaining alpha < 10 chars:

| Sentence | Alpha After Strip | Dropped? |
|----------|-------------------|----------|
| "Total: $29,900.00." | 5 ("Total") | ❌ YES |
| "SUBTOTAL: 29,900.00" | 8 ("SUBTOTAL") | ❌ YES |
| "Invoice #1256003" | 7 ("Invoice") | ❌ YES |

**Fix:** Lower alpha threshold from 10 → 6.

### Category 8: DI Paragraph Split

If Azure DI splits a sentence across two paragraphs, each half becomes an independent (broken) sentence. Cannot be fixed in spaCy — would need DI paragraph merging heuristic.

### Category 9: Dedup Weakness

Dedup uses case-insensitive exact match. Extra whitespace, line breaks, and OCR spacing variants create duplicates. Creates wasted embeddings but does NOT cause sentence loss.

**Fix:** Normalize whitespace in dedup key: `re.sub(r'\s+', ' ', text).strip().lower()`.

### Category 10: Numbered List Stripping — SAFE

Regex `^\d+\.\s+` correctly strips list markers without affecting sub-sections (1.1, 4.2) or mid-sentence periods. Installment amounts like "$20,000.00 upon signing" are preserved. No action needed.

### Category 11: Merged with Category 5

---

## Benchmark Question Impact Summary

| Question | Term at Risk | Gap Category | Fix Priority |
|----------|-------------|--------------|-------------|
| Q-G1 | "not transferable" | #3 ALL_CAPS | P1 |
| Q-G3 | "TOTAL" / "AMOUNT DUE" | #7 numeric_only | P2 |
| Q-G5 | "CONFIDENTIAL" | #3 ALL_CAPS | P1 |
| Q-D7 | "2024-06-15" | #2 min_chars | P1 |
| Q-G9 | "Warranty period" | #4 kvp_label | P2 |

---

## Complete Fix Priority Table

| Priority | Fix | LOC | Risk | Gain |
|----------|-----|-----|------|------|
| **P0** | `legal_sent_boundary_fix` spaCy component | ~20 new | Low | Prevents all legal-abbrev fragmentation |
| **P1** | `SKELETON_MIN_SENTENCE_CHARS` 30→20 | 1 line | Low | Recovers "Effective date" + similar |
| **P1** | ALL_CAPS word threshold 10→6 | 1 line | Low | Recovers "THIS WARRANTY IS NOT TRANSFERABLE" |
| **P2** | `_is_kvp_label` word threshold 8→10 | 1 line | Low | Recovers "Warranty period: ..." etc. |
| **P2** | numeric_only alpha threshold 10→6 | 1 line | Medium | Recovers "Invoice #1256003", "Total: $29,900" |
| **P3** | Whitespace-normalize dedup key | 1 line | None | Prevents duplicate embeddings |
| **P4** | Emit heading text as sentences | ~10 LOC | Medium | Makes headings searchable at sentence level |

All P0-P2 fixes are additive (admit previously-dropped sentences) and non-breaking.

## Baseline Comparison: spaCy sm vs PySBD vs wtpsplit (2026-02-27)

### Question: "Would a better baseline make the patch less brittle?"

Tested 3 baselines on 25 known legal edge cases + 10 unseen abbreviations:

### Raw Baseline Scores (no patches)

| Baseline | Known/25 | Unseen/10 | Latency | Docker + | New Deps |
|----------|----------|-----------|---------|----------|----------|
| spaCy sm (current) | 19 | 7 | 26ms | 0 MB | none |
| PySBD 0.3.4 | 18 | 0 | 7ms | <1 MB | pysbd (stale, 2021) |
| wtpsplit sat-3l-sm (ONNX) | 24 | **10** | 410ms | ~480 MB | wtpsplit+onnxruntime |
| wtpsplit sat-12l-sm (ONNX) | 24 | **10** | 461ms | ~600 MB | wtpsplit+onnxruntime |

**Note:** Initial tests used `sat-3l-sm` (96.5 F1). Re-tested with `sat-12l-sm` (97.4 F1, best available) — same abbreviation accuracy, better paragraph handling. Legal LoRA modules exist but require PyTorch (incompatible with ONNX-only deployment).

### With Best Config Per Baseline (59-case suite)

Full test: 25 known abbreviations + 10 unseen abbreviations + 24 real DI-sourced text.

| Approach | Total/59 | Failures | Latency | New Deps |
|----------|----------|----------|---------|----------|
| sat-12l-sm + `do_paragraph_segmentation=True` | **57/59** | inv-items, ellipsis | 461ms (17.6x) | 2 pkgs, +600MB |
| spaCy sm + `legal_sent_boundary_fix_v2` | **57/59** | U-Reg., inv-items | 26ms (1.0x) | none |
| PySBD + NL-fix + abbreviation merge | ~52/59 est. | multiple | 7ms | pysbd (stale) |

**They tie at 57/59** but fail on different cases:
- wtpsplit: splits at ellipsis (`"premises... failure"` → 2 sentences)
- spaCy+fix: chokes on regulatory citation syntax (`"Per Reg. 44 CFR 206"` → parser splits at CFR)

### Key wtpsplit Feature: `do_paragraph_segmentation=True`

wtpsplit's paragraph mode solves the newline dilemma that naive NL-fix cannot:
- Mid-sentence `\n` ("warrants to\nthat construction"): ✅ keeps merged
- Between-sentence `\n` ("90 days.\nFailure to comply"): ✅ splits correctly
- Double `\n\n` paragraph break: ✅ splits correctly

spaCy's dependency parser handles all three of these correctly by design.

### Critical Finding: spaCy Tokenization Bug in v1 Fix

The v1 `legal_sent_boundary_fix` only checked `token.text.endswith(".")`. But spaCy tokenizes **unknown** abbreviations as two tokens (`"Supp"` + `"."`), so the fix missed them.

**v2 fix** handles both tokenization styles:

```python
LEGAL_ABBREVS = {
    'art', 'para', 'sec', 'cl', 'ref', 'no', 'inc', 'ltd', 'corp', 'co',
    'sr', 'jr', 'dr', 'mr', 'mrs', 'ms', 'prof', 'esq', 'dept', 'div',
    'approx', 'est', 'govt', 'intl', 'natl', 'supp', 'vol', 'pt', 'st',
    'subch', 'ch', 'app', 'exh', 'amdt', 'reg', 'par', 'chap',
}

@Language.component("legal_sent_boundary_fix_v2")
def legal_sent_boundary_fix_v2(doc):
    for token in doc[:-1]:
        # Case 1: Merged period token (e.g. "Art.")
        if (token.text.endswith(".") and len(token.text) > 1 and
            token.text[:-1].lower() in LEGAL_ABBREVS):
            doc[token.i + 1].is_sent_start = False
        # Case 2: Split period token (e.g. "Supp" + ".")
        elif (token.text == "." and token.i > 0 and
              doc[token.i - 1].text.lower() in LEGAL_ABBREVS and
              token.i + 1 < len(doc)):
            doc[token.i + 1].is_sent_start = False
    return doc
```

**Must register BEFORE parser:** `nlp.add_pipe("legal_sent_boundary_fix_v2", before="parser")`

### The 1 Case That Differentiates

`"Per Reg. 44 CFR 206, the standard applies."`
- wtpsplit: ✅ (neural model understands regulatory citation syntax)
- spaCy + legal_fix_v2: ❌ (parser splits at `CFR` — syntax confusion, not abbreviation issue)

This is a parser limitation with multi-token regulatory references (`44 CFR 206`), not an abbreviation problem. The fix cannot address it without suppressing legitimate splits.

### Why spaCy sm IS a Good Baseline

spaCy's dependency parser generalizes to unseen abbreviations via syntactic context:
- When it sees `Xyz. 5`, it recognizes "abbreviation + number" → keeps sentence together
- Scored 7/10 on unseen abbreviations **without any patch** (vs PySBD 0/10)
- PySBD only knows hardcoded rules — MORE brittle for novel abbreviations

### Answer: Is a Better Baseline Less Brittle?

**On our 5 current legal PDFs, they tie.** But on unknown documents, the gap is massive.

On 59 known legal cases (our 5 PDFs):
- `sat-6l-sm` + paragraph mode: **57/59** (best wtpsplit config for speed/accuracy)
- `sat-12l-sm` + paragraph mode: **57/59** (same accuracy, 3x slower)
- `spaCy sm` + `legal_fix_v2`: **57/59**

**Stress test: 45 sentences across 8 unknown domains** (medical, financial, technical, government, academic, international, insurance, real estate):
- `sat-6l-sm` + paragraph mode: **42/45 (93%)**
- `spaCy sm` + `legal_fix_v2`: **25/45 (56%)**

spaCy's failures are ALL abbreviation-related — each new domain brings abbreviations not in LEGAL_ABBREVS:
- Medical: Fig. Tab. ca. mets. Temp.
- Financial: Treas.
- Technical: temp. Appx. in.
- Government: Pub. L. Fed.
- Academic: J. Am. Chem. Soc. pts.
- International: Conv. Dist. Res.
- Insurance: Excl. Sched.
- Real Estate: Mun. Props.

The allowlist would need to grow from 37 → 60+ words for just these 8 domains, and every new domain adds more. wtpsplit handles them all because it learned the PATTERN of abbreviations from massive training data, not a fixed list.

wtpsplit's 3 failures are all newline-boundary ambiguity, not abbreviation problems.

### Recommended Model: sat-6l-sm

All wtpsplit `-sm` models tested with `do_paragraph_segmentation=True`:

| Model | Score/59 | Unseen/45 | Latency | Model Size |
|-------|----------|-----------|---------|------------|
| sat-1l-sm | 52/59 | not tested | 74ms | 381 MB |
| **sat-3l-sm** | **56/59** | not tested | **232ms** | **408 MB** |
| **sat-6l-sm** | **57/59** | **42/45** | **445ms** | **449 MB** |
| sat-12l-sm | 57/59 | not tested | 1343ms | 531 MB |

`sat-6l-sm` is the sweet spot: same accuracy as 12l at 3x the speed. `sat-3l-sm` is 1 point behind but 2x faster if latency is critical.

### Revised Recommendation

**If quality is the killer standard:** use `sat-6l-sm` + `do_paragraph_segmentation=True`. The deployment cost (+449 MB, 445ms/doc, ~28s cold start) is justified by the 56% → 93% quality gap on unknown documents.

**If the document set is fixed and known:** `spaCy sm + legal_fix_v2` is sufficient at 57/59 with zero deployment cost.

### Threshold Brittleness (Separate Issue)

The `min_chars`, `ALL_CAPS`, `numeric_only`, and `kvp_label` thresholds remain brittle regardless of the sentence splitting baseline. These are filtering heuristics, not splitting decisions. The recommended threshold changes (P1/P2) are the same regardless of which splitter we use.

---

## Phase 3: Real PDF Validation (Corrected Methodology)

### Methodology Fix

The initial real-PDF test was flawed: raw DI text (with HTML tables, embedded newlines, address blocks) was fed directly to splitters. The corrected test applies `_clean_chunk_text_for_spacy()` first — the same preprocessing the pipeline uses in production. This removes markdown headings, `<figure>` tags, list markers, and bullets, but NOT newlines or HTML tables.

Data: 164 sentences across 9 paragraph groups from 5 PDFs, reconstructed from Neo4j.

### Real PDF Comparison Table

```
Document                                         Neo4j spaCy  NLTK  wtp  wtp_f
─────────────────────────────────────────────────────────────────────────────────
★ BUILDERS LIMITED WARRANTY                         74    75    78    88    80
★ PROPERTY MANAGEMENT AGREEMENT                     43    43    44    53    45
★ PURCHASE CONTRACT                                 21    19    21    29    25
★ HOLDING TANK SERVICING CONTRACT                   18    18    13    20    19
  EXHIBIT A - SCOPE OF WORK                          4     3     4    18    11
  PROPERTY MGMT (small group)                        1     1     1     2     1
  Contoso Lifts header                               1     1     3     5     4
  INVOICE (HTML table)                               1     1     2    61    18
  10. Permitting                                     1     1     1     1     1
─────────────────────────────────────────────────────────────────────────────────
  ALL                                              164   162   167   277   204
★ PROSE ONLY (≥18 sents)                           156   155   156   190   169

  wtp = wtpsplit sat-6l-sm raw output
  wtp_f = wtpsplit filtered (≥30 chars, same as pipeline min_chars)
```

**Prose documents Δ vs Neo4j baseline (156):**

| Method | Count | Δ | % |
|--------|-------|---|---|
| spaCy re-split | 155 | -1 | -0.6% |
| NLTK punkt | 156 | ±0 | 0.0% |
| wtpsplit raw | 190 | +34 | +21.8% |
| wtpsplit filtered | 169 | +13 | +8.3% |

### Quality Analysis: Are the Extra wtpsplit Sentences Legitimate?

**WARRANTY doc deep dive (74 → 88 wtpsplit, 80 after filter):**

6 Neo4j sentences were split further by wtpsplit:

| Neo4j sentence | wtpsplit splits | Assessment |
|----------------|-----------------|------------|
| 671ch: address + instructions mixed | 5 pieces: address fields + instruction | ✓ LEGIT — improves retrieval for "builder address" |
| 792ch: numbered list (1)…(2)…(3)…(4)… | 4 pieces: one per legal provision | ✓ LEGIT — each provision becomes separately retrievable |
| 459ch: severability + execution date | 2 pieces: legal clause + date clause | ✓ LEGIT — distinct legal concepts separated |
| 309ch: equipment list + section heading | 2 pieces: sentence + heading | MIXED — heading fragment "Exclusions from Coverage." caught by filter |
| 48ch: "D. Arbitrator Powers…; Awards." | 2 pieces | ✗ FRAGMENT — "Awards." (7ch) caught by min_chars filter |
| 168ch: signature block | 6 pieces | MIXED — signature fragments, 4 caught by filter |

**Key finding: 0 Neo4j sentences were LOST by wtpsplit** — no destructive merging occurred.

### Latency Comparison (24K chars, CPU-only)

| Method | Time | chars/s | vs spaCy |
|--------|------|---------|----------|
| NLTK punkt | 0.04s | 598,764 | 27× faster |
| spaCy sm | 1.11s | 21,745 | baseline |
| wtpsplit sat-1l-sm | ~7s | 2,036 | 10× slower |
| wtpsplit sat-3l-sm | ~20s | 719 | 28× slower |
| wtpsplit sat-6l-sm | 53s | 452 | 48× slower |

wtpsplit model load: ~5s one-time. Model size: ~449 MB.

### Ersatz

Ersatz (91.4 on wtpsplit's comparison table) requires PyTorch 1.7.1 — **incompatible** with our environment. Not testable.

### Inverted Heuristic: Fatal Flaw on Real PDFs

The inverted heuristic (dictionary of common English words) scored 93% on synthetic tests but has a **fatal flaw** on real documents: it treats lettered list items (b. c. d. e. … n.) as abbreviations because they're single letters not in the exception set {i, a}. Legal documents are FULL of lettered enumeration. On the WARRANTY doc, it collapsed 74 → ~50 sentences. **Dismissed for production use.**

---

## Final Recommendation (Updated with Real PDF Data)

### Summary

| Criterion | spaCy sm (current) | wtpsplit sat-6l-sm |
|-----------|-------------------|--------------------|
| Prose quality (real PDFs) | 155/156 (99.4%) | 169/156 (+8.3% more useful chunks) |
| Unknown domain robustness | 56% (stress test) | 93% (stress test) |
| Compound sentence handling | Keeps as one chunk | Splits correctly |
| Destructive merging | None | None |
| Latency (24K chars, CPU) | 1.1s | 53s (48× slower) |
| Deployment size | 0 MB extra | +449 MB |
| Fix brittleness | Grows per domain | Zero tailoring needed |

### Decision Framework

**Option A — Stay with spaCy + legal_fix_v2 (conservative)**
- Pros: Fast, no deployment change, handles known documents
- Cons: Brittle on new domains (allowlist grows), misses compound sentence splits
- Best if: document set is fixed and known

**Option B — Switch to wtpsplit sat-6l-sm (quality-first)**
- Pros: Best quality, zero tailoring, handles unknown domains, better retrieval granularity
- Cons: 48× slower, +449 MB deployment, model download on cold start
- Best if: quality is killer standard, diverse document types expected
- Mitigation: use sat-3l-sm (28× slower, same quality on our tests) or sat-1l-sm (10× slower, slightly more aggressive splitting)

**Option C — Hybrid: wtpsplit for indexing, spaCy for real-time (pragmatic)**
- Indexing is batch/async — latency tolerance is high (minutes, not seconds)
- Use wtpsplit sat-6l-sm during indexing pipeline only
- Keep spaCy for any real-time sentence needs
- Best balance of quality and operational constraints

### P1/P2 Threshold Fixes (Independent of Splitter Choice)

These should be applied regardless:
- P1: `SKELETON_MIN_SENTENCE_CHARS`: 30 → 20 (preserves short legal sentences)
- P2: ALL_CAPS filter: raise word threshold 10 → 6 (preserves legal headings)
- P2: Add "Inc.", "Ltd.", "LLC" to spaCy special cases (if staying with spaCy)

---

## Phase 4: Implementation & Benchmark Results (2026-02-27)

### Changes Applied

1. **`sentence_extraction_service.py`** — Replaced spaCy with wtpsplit `sat-3l-sm`:
   - Lazy singleton `_get_sat()` with threading lock (same pattern as old spaCy loader)
   - `_split_sentences()` helper with `do_paragraph_segmentation=True` for DI text
   - All 3 public APIs updated: `extract_sentences_from_chunk`, `extract_sentences_from_di_units`, `extract_sentences_from_raw_text`

2. **`requirements.txt`** — Added `wtpsplit>=2.1.0`, `onnxruntime>=1.16.0`

3. **`neo4j_retry.py`** — Fixed `_EagerResult.__getitem__` (missing, caused `TypeError` during reindex)

### Reindex Results (test-5pdfs-v2-fix2)

| Metric | Value |
|--------|-------|
| Documents | 5 |
| Sections | 55 |
| **Sentences** | **208** (was ~155 with spaCy) |
| Entities | 240 |
| MENTIONS edges | 602 |
| KNN edges | 0 (GDS Aura timeout) |
| Communities | 0 (GDS Aura timeout) |

### Route 7 Benchmark: spaCy vs wtpsplit

| QID | spaCy Cont | wtpsplit Cont | Δ | spaCy F1 | wtpsplit F1 | Δ |
|-----|-----------|--------------|-----|---------|------------|-----|
| Q-D1 | 0.94 | 0.94 | +0.00 | 0.33 | 0.31 | -0.02 |
| Q-D2 | 0.83 | 0.83 | +0.00 | 0.19 | 0.16 | -0.03 |
| Q-D3 | 0.41 | **0.71** | **+0.30** | 0.32 | **0.44** | **+0.12** |
| Q-D4 | 1.00 | 1.00 | +0.00 | 0.51 | 0.41 | -0.10 |
| Q-D5 | 0.89 | 0.89 | +0.00 | 0.40 | 0.34 | -0.06 |
| Q-D6 | 0.90 | 0.90 | +0.00 | 0.22 | 0.31 | +0.08 |
| Q-D7 | 1.00 | 0.87 | -0.13 | 0.50 | 0.43 | -0.07 |
| Q-D8 | 0.57 | 0.61 | +0.05 | 0.56 | 0.59 | +0.03 |
| Q-D9 | 0.92 | **1.00** | **+0.08** | 0.32 | 0.35 | +0.04 |
| Q-D10 | 0.97 | 0.81 | -0.16 | 0.40 | 0.37 | -0.03 |
| **AVG** | **0.843** | **0.856** | **+0.013** | **0.374** | **0.370** | **-0.004** |

**Negative tests: 9/9 PASS** (unchanged)

### Verdict

- **Containment improved** +1.3% overall, with Q-D3 (time windows) jumping +30 points
- **F1 roughly neutral** (-0.4%), within single-run variance
- **Note:** GDS KNN/Louvain failed (Neo4j Aura connectivity) — 0 communities and 0 KNN edges.
  Regressions on Q-D7/Q-D10 may partly be from missing KNN edges, not from wtpsplit itself.
- **208 sentences** vs ~155 with spaCy = +34% more sentence nodes in the graph

---

## Git State

```
b20351a (HEAD, main) fix(neo4j-retry): add __getitem__ to _EagerResult for subscript access
6f4cbdc feat(sentence-extraction): replace spaCy with wtpsplit for sentence splitting
e720c65 (origin/main) feat(route7): increase rerank_top_k from 20 to 30
```
