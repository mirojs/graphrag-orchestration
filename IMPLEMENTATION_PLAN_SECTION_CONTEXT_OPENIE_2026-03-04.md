# Implementation Plan: Section-Context OpenIE & Deterministic Extraction Experiments

**Date**: 2026-03-04  
**Status**: Plan ready, awaiting implementation  
**Baseline**: Route 7 = 55/57 (benchmark `route7_hipporag2_r4questions_20260302T100905Z.json`)

---

## Goal

Improve OpenIE triple extraction quality through two changes:
1. **Section-level context prefix** + **paragraph-grouped batching** for LLM OpenIE calls
2. **Deterministic extraction for structured elements** (signature blocks, letterhead) vs. LLM extraction

Each change will be validated via A/B experiment on the standard 5-PDF benchmark before merging.

---

## Experiment Design

### Experiment Matrix

| Exp | Label | OpenIE Batching | Signature/Letterhead | Notes |
|-----|-------|----------------|---------------------|-------|
| **E0** | baseline | Sequential 5-sentence | LLM (current) | Already have: 55/57 |
| **E1** | section-context | Section-grouped + title prefix | LLM (current) | Tests improvement #2 alone |
| **E2** | section-context + deterministic-sig | Section-grouped + title prefix | Deterministic rules | Tests both improvements |
| **E3** | deterministic-sig-only | Sequential 5-sentence (current) | Deterministic rules | Isolates deterministic effect |

### Success Criteria

- **Primary**: Route 7 benchmark score ≥ 55/57 (no regression)
- **Secondary**: Triple quality improvement (measured via LLM-as-Judge eval script)
- **Tertiary**: LLM call count reduction (logged during indexing)

### How Each Experiment Runs

1. Make code changes (or set env vars)
2. Re-index the 5-PDF test set: `GROUP_ID=test-5pdfs-v2-fix2 PYTHONPATH=. python3 scripts/index_5pdfs_v2_local.py`
3. Deploy to cloud: `./deploy-graphrag.sh` (resets PPR cache)
4. Run benchmark: `python3 scripts/benchmark_route7_hipporag2.py --repeats 3`
5. Run LLM eval: `python3 scripts/evaluate_route4_reasoning.py <output.json>`
6. Record scores

---

## Step-by-Step Implementation

### Phase 1: Extend Neo4j Query (Enabler)

**File**: `src/worker/hybrid_v2/services/neo4j_store.py`  
**Function**: `get_sentences_by_group()` (line 1075)

**Change**: Add `index_in_section`, `total_in_section`, `page` to the RETURN clause and the result dict.

```python
# Current (line 1082-1088):
query = """
MATCH (s:Sentence {group_id: $group_id})
RETURN s.id AS id, s.text AS text, s.chunk_id AS chunk_id,
       s.document_id AS document_id, s.source AS source,
       s.section_path AS section_path
ORDER BY s.document_id, s.chunk_id, s.index_in_chunk
"""

# New:
query = """
MATCH (s:Sentence {group_id: $group_id})
RETURN s.id AS id, s.text AS text, s.chunk_id AS chunk_id,
       s.document_id AS document_id, s.source AS source,
       s.section_path AS section_path,
       s.index_in_section AS index_in_section,
       s.total_in_section AS total_in_section,
       s.page AS page
ORDER BY s.document_id, s.section_path, s.index_in_section
"""
```

Also update the dict comprehension (line 1091-1101) to include the new fields.

**Risk**: Zero — additive change, existing consumers ignore extra fields.

---

### Phase 2: Section-Context Batching for OpenIE (E1)

**File**: `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`  
**Function**: `_extract_openie_triples()` (line 1415)

#### Step 2a: Add section title helper

Add near line 1398 (before the function):

```python
@staticmethod
def _leaf_section_title(section_path: str) -> str:
    """Extract the leaf section title from a ' > ' delimited path."""
    if not section_path:
        return ""
    return section_path.split(" > ")[-1].strip()
```

#### Step 2b: Replace sequential batching with section-grouped batching

Replace the batching block (lines 1445-1451):

```python
# CURRENT:
BATCH_SIZE = 5
batches: List[List[Dict[str, Any]]] = []
for i in range(0, len(content_sentences), BATCH_SIZE):
    batches.append(content_sentences[i : i + BATCH_SIZE])
```

With section-aware batching:

```python
from itertools import groupby as _groupby

MAX_SECTION_BATCH = 15  # Safety cap for very large sections

def _section_key(s: Dict[str, Any]) -> Tuple[str, str]:
    return (s.get("document_id", ""), s.get("section_path", ""))

batches_with_context: List[Tuple[List[Dict[str, Any]], str]] = []
for (_doc_id, _sec_path), grp in _groupby(content_sentences, key=_section_key):
    section_sents = list(grp)
    title = self._leaf_section_title(_sec_path)
    # Context prefix: section title (or document title fallback)
    if title and title not in ("[Signature Block]", "[Page Footer]", "[Page Header]", "[Letterhead]"):
        context = f"Section: {title}\n\n"
    elif _sec_path in ("[Signature Block]",):
        context = "Signature Block:\n\n"
    elif _sec_path in ("[Letterhead]",):
        context = "Letterhead:\n\n"
    else:
        context = ""

    if len(section_sents) <= MAX_SECTION_BATCH:
        batches_with_context.append((section_sents, context))
    else:
        # Split large sections at chunk_id boundaries
        for _, chunk_grp in _groupby(section_sents, key=lambda s: s.get("chunk_id", "")):
            batches_with_context.append((list(chunk_grp), context))
```

#### Step 2c: Update `_extract_batch` to use context prefix

```python
async def _extract_batch(batch: List[Dict[str, Any]], context: str) -> List[Dict[str, str]]:
    sentence_block = context + "\n".join(
        f"[{s['id']}]: {s['text']}" for s in batch
    )
    prompt = self._OPENIE_PROMPT.format(sentences=sentence_block)
    # ... rest unchanged
```

Update the `asyncio.gather` call:
```python
results = await asyncio.gather(*[
    _extract_batch(b, ctx) for b, ctx in batches_with_context
])
```

#### Step 2d: Verify — Run E1

1. Re-index: `GROUP_ID=test-5pdfs-v2-fix2 PYTHONPATH=. python3 scripts/index_5pdfs_v2_local.py`
2. Deploy: `./deploy-graphrag.sh`
3. Benchmark: `python3 scripts/benchmark_route7_hipporag2.py --repeats 3`
4. Eval: `python3 scripts/evaluate_route4_reasoning.py benchmarks/<output>.json`
5. Save as `benchmarks/route7_hipporag2_r4questions_<timestamp>_E1_section_context.json`

**Expected**: Score ≥ 55/57, likely same or +1. Main value is qualitative triple improvement.

---

### Phase 3: Deterministic Signature & Letterhead Extraction (E2/E3)

**File**: `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py`

#### Step 3a: Add deterministic extraction functions

Add a new method to `LazyGraphRAGIndexingPipeline`:

```python
def _extract_deterministic_triples(
    self,
    sentences: List[Dict[str, Any]],
    group_id: str,
) -> Tuple[List[Entity], List[Relationship]]:
    """Extract triples from structured elements (signature, letterhead) using rules.
    
    These elements have explicit structure that doesn't need LLM interpretation:
    - Signature: "John Smith. CEO. December 15, 2025"
      → ("john smith", "signed_as", "ceo"), ("john smith", "signed_on", "december 15 2025")
    - Letterhead: "SolarTech Inc. 123 Main Street. San Francisco CA"
      → ("solartech inc", "located_at", "123 main street san francisco ca")
    """
    # Implementation TBD based on experiment results
```

#### Step 3b: Signature block deterministic rules

Parse the joined signature sentence using patterns:
- Split on `. ` to get parts
- First part = person name (if title-cased or known name pattern)
- Second part = role/title (if matches known role patterns: CEO, Director, etc.)
- Date part = if matches date regex
- Emit triples: `(name, "signed_as", role)`, `(name, "signed_on", date)`

#### Step 3c: Letterhead deterministic rules

Parse the joined letterhead sentence:
- First part = company name (title-cased, possibly "Inc.", "LLC", etc.)
- Remaining parts = address, phone, email (recognizable via regex)
- Emit triples: `(company, "located_at", address)`, `(company, "has_phone", phone)`

#### Step 3d: Route structured sentences to deterministic path

In `_extract_openie_triples()`, split content_sentences before batching:

```python
# Separate structured vs. content sentences
structured_sentences = [s for s in content_sentences 
                        if s.get("source") in ("signature_party", "letterhead")]
paragraph_sentences = [s for s in content_sentences 
                       if s.get("source") not in ("signature_party", "letterhead")]

# Deterministic extraction for structured elements
det_entities, det_rels = self._extract_deterministic_triples(structured_sentences, group_id)

# LLM extraction for paragraph content (section-grouped)
llm_entities, llm_rels = ... # existing logic on paragraph_sentences only

# Merge
entities = det_entities + llm_entities
relationships = det_rels + llm_rels
```

#### Step 3e: Verify — Run E3 (deterministic-only, no section context)

1. Revert section-context changes (or use a feature flag env var)
2. Keep only the deterministic extraction routing
3. Re-index + deploy + benchmark
4. Save as `benchmarks/..._E3_deterministic_sig_only.json`

#### Step 3f: Verify — Run E2 (both changes together)

1. Re-apply section-context batching
2. Keep deterministic extraction routing
3. Re-index + deploy + benchmark
4. Save as `benchmarks/..._E2_section_context_deterministic_sig.json`

---

### Phase 4: Compare Results & Decide

#### Step 4a: Build comparison table

| Experiment | Score (/57) | LLM Calls | Triple Count | Entity Count | Notes |
|------------|-------------|-----------|-------------|-------------|-------|
| E0 (baseline) | 55 | N | — | — | Already measured |
| E1 (section-context) | ? | ~same | — | — | |
| E2 (section + deterministic) | ? | fewer | — | — | |
| E3 (deterministic only) | ? | fewer | — | — | |

#### Step 4b: Run LLM-as-Judge on all 4 results

```bash
for f in benchmarks/route7_*_E{0,1,2,3}_*.json; do
    python3 scripts/evaluate_route4_reasoning.py "$f"
done
```

Compare scores across experiments. The LLM-as-Judge gives a 0-3 score per question (max 57).

#### Step 4c: Decision matrix

| Outcome | Action |
|---------|--------|
| E1 ≥ E0 | Merge section-context batching |
| E2 ≥ E1 | Also merge deterministic extraction |
| E3 < E0 | Deterministic alone hurts — investigate which structured element regressed |
| E1 = E0 AND E2 = E0 | Still merge — no regression, but graph quality improves (check triple count/quality manually) |

---

### Phase 5: Merge & Deploy

#### Step 5a: Commit the winning combination

```bash
git add src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py \
        src/worker/hybrid_v2/services/neo4j_store.py
git commit -m "feat: section-context OpenIE batching + deterministic structured extraction

- Group OpenIE batches by (document_id, section_path) instead of sequential 5
- Prefix each batch with section title for LLM disambiguation
- Extract triples deterministically for signature blocks and letterhead
- Port section-aware batching pattern from native extractor path

Benchmark: E<N> = XX/57 (baseline E0 = 55/57)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

#### Step 5b: Deploy to production

```bash
./deploy-graphrag.sh
```

#### Step 5c: Production re-index

Re-index with the winning code on the production group ID.

---

## Feature Flag (Optional but Recommended)

To make experiments easier without code reverts, add an env var:

```python
# In __init__ of LazyGraphRAGIndexingPipeline:
self._openie_batching = os.getenv("OPENIE_BATCHING", "section")  # "sequential" | "section"
self._structured_extraction = os.getenv("STRUCTURED_EXTRACTION", "llm")  # "llm" | "deterministic"
```

This allows running any experiment combination by just changing env vars before re-indexing:

| Experiment | OPENIE_BATCHING | STRUCTURED_EXTRACTION |
|------------|----------------|----------------------|
| E0 | sequential | llm |
| E1 | section | llm |
| E2 | section | deterministic |
| E3 | sequential | deterministic |

---

## Key Files to Modify

| File | Changes |
|------|---------|
| `src/worker/hybrid_v2/services/neo4j_store.py` | Extend `get_sentences_by_group()` RETURN clause + dict |
| `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | Section-grouped batching, context prefix, deterministic extraction, feature flags |

## Key Files to Run

| Script | Purpose |
|--------|---------|
| `scripts/index_5pdfs_v2_local.py` | Re-index test corpus |
| `deploy-graphrag.sh` | Deploy to Azure |
| `scripts/benchmark_route7_hipporag2.py` | Run Route 7 benchmark (score /57) |
| `scripts/evaluate_route4_reasoning.py` | LLM-as-Judge quality eval |

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|-----------|-----------|
| Section grouping produces larger batches → JSON parse failures | LOW | MAX_SECTION_BATCH=15 safety cap |
| Deterministic sig extraction misses nuances LLM catches | MEDIUM | A/B experiment E2 vs E1 proves it |
| ORDER BY change in Cypher breaks existing consumers | LOW | Only `_extract_openie_triples` consumes this, and it doesn't depend on order |
| Score regression on E1/E2 | LOW | Full experiment matrix covers this; revert is trivial |

---

## Timeline Estimate

- Phase 1 (Neo4j query): Trivial
- Phase 2 (Section-context + E1): Core implementation + re-index + benchmark
- Phase 3 (Deterministic + E2/E3): Implementation + 2 re-index/benchmark cycles
- Phase 4 (Compare): Analysis
- Phase 5 (Merge): Commit + deploy
