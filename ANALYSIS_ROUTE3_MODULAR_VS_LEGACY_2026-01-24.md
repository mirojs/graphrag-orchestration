# Route 3 Modular vs Legacy Analysis - 2026-01-24

## Summary

Benchmark testing revealed that the **modular GlobalSearchHandler** and the **legacy `_execute_route_3_global_search()`** produce different results despite being intended as identical implementations. The modular handler performs better on cross-document queries.

## Benchmark Results

### Test Configuration
- **Repeats:** 3
- **Questions:** 19 (10 positive Q-G, 9 negative Q-N)
- **Group:** `test-5pdfs-1769071711867955961`
- **Corpus:** 5 documents (Purchase Contract, Invoice, Exhibit A, Holding Tank Contract, Builder's Warranty)

### Comparison Table

| Question | Modular Theme | Legacy Theme | Modular Contain | Legacy Contain |
|----------|---------------|--------------|-----------------|----------------|
| Q-G1 | 100% (7/7) | 100% (7/7) | 0.83 | 0.79 |
| Q-G2 | 100% (6/6) | 100% (6/6) | 0.95 | 0.86 |
| **Q-G3** | **100% (8/8)** | **75% (6/8)** | - | - |
| Q-G4 | 100% (6/6) | 100% (6/6) | 0.84 | 0.76 |
| Q-G5 | 100% (6/6) | 100% (6/6) | 0.90 | 0.75 |
| Q-G6 | 100% (8/8) | 100% (8/8) | 0.82 | 0.82 |
| Q-G7 | 100% (5/5) | 100% (5/5) | 0.79 | 0.82 |
| Q-G8 | 100% (6/6) | 100% (6/6) | 0.74 | 0.68 |
| Q-G9 | 100% (6/6) | 100% (6/6) | 0.87 | 0.73 |
| Q-G10 | 100% (6/6) | 100% (6/6) | - | - |
| Q-N1-N10 | All PASS | All PASS | - | - |

### Q-G3 Deep Dive

**Question:** "Summarize 'who pays what' across the set (fees/charges/taxes)"

**Expected terms:** `29900`, `25%`, `10%`, `installment`, `commission`, `$75`, `$50`, `tax`

#### Legacy Result (75% - Missing 2 terms)
- **Matched:** 25%, 10%, commission, $75, $50, tax
- **Missing:** `29900`, `installment`
- **Citations:** 3 chunks from **1 document** (Property Management Agreement only)
  - `doc_853e4ab63ca94ea492804fe91688f9ce_chunk_0`
  - `doc_853e4ab63ca94ea492804fe91688f9ce_chunk_1`
  - `doc_853e4ab63ca94ea492804fe91688f9ce_chunk_2`

#### Modular Result (100% - All terms matched)
- **Matched:** All 8 terms
- **Citations:** 7 chunks from **4 documents**
  - Property Management Agreement (chunks 0, 1, 2)
  - Purchase Contract (chunks 0, 2)
  - Invoice (chunk 0)
  - Another document (chunk 0)

The legacy response focused only on Hawaii taxes and agent fees, missing the $29,900 purchase price and installment payment terms from the Purchase Contract/Invoice.

---

## Root Cause Analysis

### Code Location Difference

The discrepancy is in the **Coverage Gap Fill** implementation:

| File | Method |
|------|--------|
| `app/hybrid/routes/route_3_global.py` | `_apply_coverage_gap_fill()` (modular) |
| `app/hybrid/orchestrator.py` | Stage 3.4.1 coverage logic (legacy) |

### Implementation Comparison

#### Modular Handler (route_3_global.py:571-592)
```python
async def _apply_coverage_gap_fill(self, query: str, graph_context) -> None:
    # Get lead chunks from all documents
    fill_chunks = await self.pipeline.enhanced_retriever.get_document_lead_chunks(
        max_total=10,
        min_text_chars=20,
    )
    
    existing_ids = {c.chunk_id for c in graph_context.source_chunks}
    added = [c for c in fill_chunks if c.chunk_id not in existing_ids]
    
    if added:
        for c in added:
            c.entity_name = "coverage_fill"
        graph_context.source_chunks.extend(added)
```

#### Legacy Handler (orchestrator.py:3200-3290)
```python
# Uses section-aware retrieval with document-level tracking
coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(
    max_per_document=1,
    max_total=coverage_max_total,  # = min(total_docs, 200)
)
if not coverage_chunks:
    coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(...)

# Only adds chunks for documents we're MISSING
existing_docs = set()
for chunk in graph_context.source_chunks:
    doc_key = (chunk.document_id or ...).strip().lower()
    if doc_key:
        existing_docs.add(doc_key)

for chunk in coverage_chunks:
    doc_key = (chunk.document_id or ...).strip().lower()
    if doc_key and doc_key not in existing_docs and chunk.chunk_id not in existing_ids:
        graph_context.source_chunks.append(chunk)
```

### Key Differences

| Aspect | Modular | Legacy |
|--------|---------|--------|
| **Retrieval Method** | `get_document_lead_chunks()` | `get_summary_chunks_by_section()` → `get_coverage_chunks()` |
| **Max Total Chunks** | Fixed `10` | Dynamic: `min(total_docs, 200)` |
| **Document Tracking** | ❌ None - dedupes by chunk_id only | ✅ Tracks `existing_docs` by document_id |
| **Per-Document Cap** | ❌ No cap | `max_per_document=1` |
| **Skips If Full** | ❌ No | ✅ Skips if all docs already covered |

---

## Why Modular Performs Better

1. **`get_document_lead_chunks()`** appears to be more reliable at returning representative chunks from all documents than `get_summary_chunks_by_section()`.

2. The legacy's document-tracking logic is more **principled** (only add truly missing docs), but if the upstream retrieval method doesn't return the right chunks, the tracking doesn't help.

3. The modular handler's simpler approach (get lead chunks, dedupe by chunk_id) accidentally achieves better coverage because the retrieval method itself returns more diverse results.

---

## Recommendation

**Hybrid Approach:** The modular handler should adopt the legacy's document-tracking logic while keeping its better retrieval method:

```python
async def _apply_coverage_gap_fill(self, query: str, graph_context) -> None:
    """Fill coverage gaps for cross-document queries."""
    try:
        # Track which documents we already have
        existing_docs = set()
        existing_ids = set()
        for chunk in graph_context.source_chunks:
            doc_key = (chunk.document_id or chunk.document_source or chunk.document_title or "").strip().lower()
            if doc_key:
                existing_docs.add(doc_key)
            if chunk.chunk_id:
                existing_ids.add(chunk.chunk_id)
        
        # Get total document count
        all_documents = await self.pipeline.enhanced_retriever.get_all_documents()
        total_docs = len(all_documents)
        
        # Skip if already full coverage
        if total_docs > 0 and len(existing_docs) >= total_docs:
            logger.info("coverage_gap_fill_skipped", reason="already_full_coverage")
            return
        
        # Get lead chunks - dynamic sizing
        max_total = min(max(total_docs, 10), 200)
        fill_chunks = await self.pipeline.enhanced_retriever.get_document_lead_chunks(
            max_total=max_total,
            min_text_chars=20,
        )
        
        if not fill_chunks:
            return
        
        # Only add chunks for MISSING documents
        added_count = 0
        new_docs = set()
        
        for c in fill_chunks:
            doc_key = (c.document_id or c.document_source or c.document_title or "").strip().lower()
            if doc_key and doc_key not in existing_docs and c.chunk_id not in existing_ids:
                c.entity_name = "coverage_fill"
                graph_context.source_chunks.append(c)
                existing_ids.add(c.chunk_id)
                existing_docs.add(doc_key)
                new_docs.add(doc_key)
                added_count += 1
        
        if added_count > 0:
            logger.info("coverage_gap_fill_applied", 
                       added=added_count, 
                       new_docs=len(new_docs),
                       total_docs=total_docs)
                       
    except Exception as e:
        logger.warning("coverage_gap_fill_failed", error=str(e))
```

This combines:
- ✅ Better retrieval method (`get_document_lead_chunks`)
- ✅ Smarter gap detection (document-level tracking)
- ✅ Dynamic sizing based on corpus
- ✅ Early exit if already full coverage

---

## Output Files

- **Modular benchmark:** `benchmarks/route3_global_search_20260124T141453Z.json`
- **Legacy benchmark:** `benchmarks/route3_global_search_legacy_20260124T144840Z.json`

---

## Next Steps

1. [ ] Discuss whether to implement the hybrid approach
2. [ ] Investigate why `get_summary_chunks_by_section()` doesn't return Purchase Contract/Invoice chunks
3. [ ] Consider whether the legacy's stricter document-tracking is beneficial for larger corpora (noise reduction)
4. [ ] Run benchmarks on a larger corpus to validate at scale

---

## Code Cleanup Note

The `--legacy` flag support was added temporarily to the benchmark script and API for this analysis, then reverted. If needed for future A/B testing, those changes can be re-applied:
- `HybridQueryRequest.use_modular_handlers` field
- `--legacy` CLI argument in benchmark script
- Passing `use_modular_handlers` to `pipeline.force_route()` and `pipeline.query()`
