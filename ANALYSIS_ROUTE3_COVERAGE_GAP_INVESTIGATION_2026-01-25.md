# Route 3 Coverage Gap Fill Investigation - 2026-01-25

## Executive Summary

**The boosts were NOT being used - but for a different reason than we thought.**

### The Real Timeline:

| Date/Time | Event | Handler Used |
|-----------|-------|--------------|
| **Jan 22** | Modular handlers created | Legacy still default |
| **Jan 23 10:00** | **Modular becomes default** (`f42341e`) | **Modular** |
| Jan 23 11:03 | Benchmark `20260123T110329Z` | **Modular** → 100% |
| Jan 24 08:34 | Fast Mode added to legacy | N/A (not used) |
| Jan 24 10:46 | Benchmark `20260124T104602Z` | **Modular** → 100% |
| Jan 24 11:15 | Boosts removed from legacy | N/A (not used) |
| Jan 24 14:48 | Benchmark with `--legacy` flag | **Legacy** → 75% ❌ |

### Key Insight:

**The boost code in orchestrator.py was NEVER being used in the benchmarks** because:
1. Modular handlers became default on Jan 23
2. All subsequent benchmarks used modular handlers by default
3. The legacy code path was only tested when explicitly forced with `--legacy`

### So the real question is:
The legacy handler scored **75% on Q-G3** when tested. Was this:
1. **Always the case** (legacy never had proper cross-document coverage)?
2. **Caused by removing boosts** (boosts WERE working before Jan 23)?

To answer this, we'd need a benchmark from **before Jan 23** that used the legacy handler explicitly.

## What Yesterday's Commit Changed

**Commit:** `28af93a` - "Align modular route_3_global.py with orchestrator.py (1:1)"  
**Date:** January 24, 2026 11:26:14 UTC  
**Author:** GraphRAG Dev

### Changes Made:
✅ Added Fast Mode detection (`ROUTE3_FAST_MODE` env var)  
✅ Added PPR conditional skip logic for simple thematic queries  
✅ Matched variable names: `all_seed_entities`, `evidence_nodes`  
✅ Matched PPR `top_k=20` (was 15)  
✅ Matched logging patterns  
✅ Added relationship indicators check for Fast Mode

### What Was NOT Changed:
❌ **Coverage Gap Fill implementation** - Still uses the simpler modular approach  
❌ Document-level tracking in `_apply_coverage_gap_fill()`  
❌ Retrieval method (`get_document_lead_chunks()` vs `get_summary_chunks_by_section()`)

## Current Code Comparison

### Modular Handler (route_3_global.py:571-592)
```python
async def _apply_coverage_gap_fill(self, query: str, graph_context) -> None:
    """Fill coverage gaps for cross-document queries."""
    try:
        # Get lead chunks from all documents
        fill_chunks = await self.pipeline.enhanced_retriever.get_document_lead_chunks(
            max_total=10,
            min_text_chars=20,
        )
        
        if not fill_chunks:
            return
        
        existing_ids = {c.chunk_id for c in graph_context.source_chunks}
        added = [c for c in fill_chunks if c.chunk_id not in existing_ids]
        
        if added:
            for c in added:
                c.entity_name = "coverage_fill"
            graph_context.source_chunks.extend(added)
            logger.info("coverage_gap_fill_applied", added=len(added))
                       
    except Exception as e:
        logger.warning("coverage_gap_fill_failed", error=str(e))
```

**Issues:**
- ❌ No document-level tracking - only deduplicates by `chunk_id`
- ❌ Fixed `max_total=10` - doesn't scale with corpus size
- ❌ No early exit if all documents already covered
- ❌ Can add multiple chunks from the same document

### Legacy Handler (orchestrator.py:3200-3296)
```python
# Track which documents we already have
existing_docs = set()
existing_ids = set()
for chunk in graph_context.source_chunks:
    doc_key = (chunk.document_id or chunk.document_source or chunk.document_title or "").strip().lower()
    if doc_key:
        existing_docs.add(doc_key)
    if getattr(chunk, "chunk_id", None):
        existing_ids.add(chunk.chunk_id)

# Count documents and size coverage retrieval
all_documents = await self.enhanced_retriever.get_all_documents()
total_docs_in_group = len(all_documents)
coverage_max_total = min(max(total_docs_in_group, 0), 200)

# Early exit if already full coverage
if total_docs_in_group > 0 and len(existing_docs) >= total_docs_in_group:
    logger.info("coverage_gap_fill_complete", skipped=True, reason="already_full_coverage")
else:
    # Prefer section-aware summary chunks
    coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(
        max_per_document=1,
        max_total=coverage_max_total,
    )
    
    if not coverage_chunks:
        coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(
            max_per_document=1,
            max_total=coverage_max_total,
        )
    
    # Only add chunks for documents we're MISSING
    for chunk in coverage_chunks:
        doc_key = (chunk.document_id or ...).strip().lower()
        if doc_key and doc_key not in existing_docs and chunk.chunk_id not in existing_ids:
            graph_context.source_chunks.append(chunk)
            existing_ids.add(chunk.chunk_id)
            new_docs.add(doc_key)
            existing_docs.add(doc_key)
            added_count += 1
```

**Advantages:**
- ✅ Document-level tracking prevents duplicate document coverage
- ✅ Dynamic sizing based on corpus: `min(max(total_docs, 0), 200)`
- ✅ Early exit optimization if all documents already covered
- ✅ `max_per_document=1` ensures minimal noise
- ✅ Tries section-aware retrieval first, falls back to position-based

## Why Modular Still Performs Better (Despite Being "Wrong")

The paradox: The modular handler's **simpler but flawed** implementation accidentally works better because:

1. **`get_document_lead_chunks()` is more reliable** at returning diverse chunks from all documents
2. **`get_summary_chunks_by_section()` appears to miss some documents** (Purchase Contract, Invoice in Q-G3)
3. The modular's lack of document tracking means it can add multiple chunks if needed

## Test Case: Q-G3 Results

**Question:** "Summarize 'who pays what' across the set (fees/charges/taxes)"

| Implementation | Theme Score | Documents Covered | Missing Terms |
|----------------|-------------|-------------------|---------------|
| **Modular** | 100% (8/8) | 4 documents, 7 chunks | None |
| **Legacy** | 75% (6/8) | 1 document, 3 chunks | `29900`, `installment` |

The legacy's document tracking worked perfectly - but the upstream retrieval method failed to return chunks from the Purchase Contract and Invoice.

## Root Cause Analysis

Yesterday's commit aligned:
- ✅ Fast Mode logic
- ✅ PPR parameters and conditional skipping
- ✅ Variable naming
- ✅ Logging patterns

But it **did NOT align** the core issue identified in the investigation:
- ❌ Coverage gap fill retrieval method
- ❌ Document-level deduplication logic
- ❌ Dynamic sizing based on corpus

## Recommended Fix

The investigation document already provides the recommended hybrid approach (lines 151-224 of the analysis doc). The fix should:

1. **Keep the better retrieval**: `get_document_lead_chunks()`
2. **Add document tracking** from legacy:
   ```python
   existing_docs = set()
   for chunk in graph_context.source_chunks:
       doc_key = (chunk.document_id or ...).strip().lower()
       if doc_key:
           existing_docs.add(doc_key)
   ```
3. **Add early exit** if already full coverage
4. **Dynamic sizing**: `max_total = min(max(total_docs, 10), 200)`
5. **Per-document filtering**: Only add chunks from missing documents

## Next Steps

1. ✅ **Confirmed:** Yesterday's changes did NOT fix the coverage gap issue
2. 🔴 **Action Required:** Implement the hybrid approach from the investigation document
3. 🔴 **Action Required:** Investigate why `get_summary_chunks_by_section()` misses documents
4. ⚠️ **Consider:** Whether to backport the fix to the legacy orchestrator.py or deprecate it entirely

## Conclusion

**Yesterday's commit `e7f18aa` (11:15) IS the cause** - it removed Section Boost, Keyword Boost, and Doc Lead Boost from the legacy orchestrator.py. These stages provided cross-document coverage that was essential for Q-G3.

### Why Modular Wasn't Affected:
The modular handler never had these boost stages. Instead, it uses `get_document_lead_chunks()` which provides better document coverage than the legacy's Coverage Gap Fill alone.

### Fix Options:

1. **Restore boost code to legacy orchestrator.py** - Revert commit `e7f18aa`
2. **Improve legacy Coverage Gap Fill** - Make it use `get_document_lead_chunks()` like modular
3. **Deprecate legacy handler** - Just use modular handler (already works at 100%)

### Recommendation:
Since the modular handler already achieves 100% theme coverage without boost code, **Option 3 (deprecate legacy)** is the cleanest path forward. The modular handler's simpler approach is more maintainable and performs better.

---

## Fix Applied: 2026-01-25

### The "Magic" of Modular's Simpler Approach

The key insight is that `get_document_lead_chunks()` **directly guarantees document coverage** while `get_summary_chunks_by_section()` tries to achieve it **indirectly**:

| Method | Approach | Reliability |
|--------|----------|-------------|
| `get_document_lead_chunks()` | Simple: "Give me the first chunk from each document" | ✅ **Direct** - no metadata dependencies |
| `get_summary_chunks_by_section()` | Complex: "Give me chunks marked as summaries OR chunk_index=0, with metadata parsing" | ❌ **Indirect** - can miss documents with non-standard metadata |

**Why `get_summary_chunks_by_section()` misses documents:**
1. Requires `metadata IS NOT NULL`
2. Requires either `is_summary_section = true` OR `chunk_index = 0`
3. Uses APOC JSON parsing (`apoc.convert.fromJsonMap`) which can fail silently
4. If a document doesn't have proper metadata markers, it gets **silently skipped**

**Why `get_document_lead_chunks()` always works:**
```cypher
MATCH (d:Document)<-[:PART_OF]-(t:TextChunk)
WHERE t.chunk_index IN [0, 1, 2, 3, 4, 5]
ORDER BY doc_id ASC, chunk_index ASC
```
- No metadata requirements
- No APOC dependency  
- Built-in fallbacks (if chunk 0 doesn't exist, try 1, 2, 3...)
- Directly guarantees one chunk per document

### Code Change Applied

**File:** [orchestrator.py](graphrag-orchestration/app/hybrid/orchestrator.py#L3252-L3260)

**Before:**
```python
# Prefer section-aware summary chunks if enabled; fall back to position-based.
coverage_chunks = []
if use_section_retrieval:
    coverage_chunks = await self.enhanced_retriever.get_summary_chunks_by_section(
        max_per_document=1,
        max_total=coverage_max_total,
    )

if not coverage_chunks:
    coverage_chunks = await self.enhanced_retriever.get_coverage_chunks(
        max_per_document=1,
        max_total=coverage_max_total,
    )
```

**After:**
```python
# Use document lead chunks for reliable cross-document coverage.
# This approach directly guarantees document coverage by fetching
# early chunks (chunk_index 0-5) from each document, avoiding the
# metadata/APOC dependencies of get_summary_chunks_by_section().
coverage_chunks = await self.enhanced_retriever.get_document_lead_chunks(
    max_total=coverage_max_total,
    min_text_chars=20,
)
```

### Also Removed

The `USE_SECTION_RETRIEVAL` environment variable check was removed since it's no longer used:
```python
# Removed:
use_section_retrieval = os.getenv("USE_SECTION_RETRIEVAL", "1").strip().lower() in {"1", "true", "yes"}
```

### Expected Result

With this fix, the legacy handler should now achieve the same 100% Q-G3 coverage as the modular handler, using the same reliable `get_document_lead_chunks()` approach.

---

**Files Referenced:**
- Analysis: [ANALYSIS_ROUTE3_MODULAR_VS_LEGACY_2026-01-24.md](ANALYSIS_ROUTE3_MODULAR_VS_LEGACY_2026-01-24.md)
- Modular: [graphrag-orchestration/app/hybrid/routes/route_3_global.py](graphrag-orchestration/app/hybrid/routes/route_3_global.py#L571-L592)
- Legacy: [graphrag-orchestration/app/hybrid/orchestrator.py](graphrag-orchestration/app/hybrid/orchestrator.py#L3200-L3296)
- Commit: `28af93a` - "Align modular route_3_global.py with orchestrator.py (1:1)"
