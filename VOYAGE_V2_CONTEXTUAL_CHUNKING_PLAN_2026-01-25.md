# V2 Contextual Chunking with Voyage-Context-3

**Date:** January 25, 2026  
**Status:** Approved for Implementation  
**Related:** `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` Section 6.5

---

## Executive Summary

Migrate from OpenAI `text-embedding-3-large` (3072 dim) to Voyage AI `voyage-context-3` (2048 dim) with LlamaIndex, enabling section-aware contextual embeddings that simplify the retrieval architecture. V2 will be developed in parallel with V1 (which remains in production) and validated independently before cut-over.

### Key Benefits

| Metric | V1 (Current) | V2 (Voyage) | Improvement |
|--------|--------------|-------------|-------------|
| **Embedding Dimensions** | 3072 | 2048 | 33% smaller |
| **Storage (1M vectors)** | ~11.4 GB | ~7.6 GB | 33% reduction |
| **Cost per 1M tokens** | $0.13 (OpenAI) | $0.06 (Voyage) | 54% cheaper |
| **Embedding Coherence** | Mixed topics per chunk | One topic per chunk | Semantic alignment |
| **Coverage Retrieval** | ~60% (arbitrary first chunks) | ~95% (Purpose sections) | +35% accuracy |

---

## Problem Statement

### Current V1 Issues

1. **Semantic Misalignment:** Fixed-size chunking (512 tokens + 64 overlap) creates chunks that span multiple unrelated sections
2. **Q-D8 Document Counting:** Exhibits/sections treated as separate documents because `doc_title` includes section headers
3. **Complex Retrieval Pipeline:** Requires "Section Diversification" and "Hub Entity Extraction" to compensate for context loss
4. **High Storage Cost:** 3072-dim embeddings consume significant Neo4j memory

### Root Cause

```
┌─────────────────────────────────────────────────────────────────┐
│ PROBLEM: Fixed-Size Chunks Don't Respect Semantic Boundaries   │
└─────────────────────────────────────────────────────────────────┘

Document Structure (what Azure DI sees):
├── Section: "Purpose" (200 words)
├── Section: "Payment Terms" (100 words)
├── Section: "Termination Clause" (150 words)
└── Section: "Signatures" (50 words)

Fixed Chunking (what embeddings see):
├── Chunk 0: [Purpose...] + [start of Payment Terms...]  ← MIXED!
├── Chunk 1: [...Payment Terms] + [Termination...]       ← MIXED!
└── Chunk 2: [...Termination] + [Signatures]             ← MIXED!
```

---

## Solution: Section-Aware Contextual Embeddings

### V2 Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ SOLUTION: Section Boundaries = Chunk Boundaries                 │
└─────────────────────────────────────────────────────────────────┘

Document Structure:
├── Section: "Purpose" (200 words)
│       ↓
│   Chunk 0: [Complete Purpose section]      ← COHERENT!
│
├── Section: "Payment Terms" (100 words)
│       ↓
│   Chunk 1: [Complete Payment section]      ← COHERENT!
│
├── Section: "Terms and Conditions" (2000 words)  ← TOO LARGE
│       ↓
│   Chunk 2: [Terms... paragraph break]      ← Split at paragraph
│   Chunk 3: [...continued Terms]            ← With overlap
│
└── Section: "Signatures" (50 words)         ← TOO SMALL
        ↓
    Merged with Chunk 3                      ← Merge with sibling
```

### Voyage-Context-3 Integration

- **Model:** `voyage-context-3` (2048 dimensions)
- **LlamaIndex Integration:** `VoyageEmbedding(model_name="voyage-context-3")`
- **Contextual Embedding:** Voyage automatically uses document context during embedding
- **API:** Compatible with LlamaIndex's `embed_documents()` for batch efficiency

---

## Parallel Development Strategy

### Key Principle: Copy V1 First, Then Modify

**⚠️ CRITICAL:** V2 development starts by copying all V1 code to the V2 directory. Do NOT create new files from scratch. This ensures:
1. V2 starts from a known-working state
2. All existing functionality is preserved
3. Modifications are incremental and testable
4. Easy to diff V1 vs V2 to see exactly what changed

### Directory Structure

```
app/
├── hybrid/                    # V1 (UNCHANGED - remains in production)
│   ├── routes/
│   ├── pipeline/
│   └── indexing/
│
├── hybrid_v2/                 # V2 (COPY of V1, then modify incrementally)
│   ├── routes/                # Copied from V1, then update for Voyage
│   ├── pipeline/              # Copied from V1, then simplify
│   ├── indexing/              # Copied from V1, then update
│   └── embeddings/            # NEW directory for Voyage service
│       └── voyage_embed.py    # Voyage integration (new file)
│
└── services/
    ├── cu_standard_ingestion_service.py      # V1 (unchanged)
    └── cu_standard_ingestion_service_v2.py   # V2 (copy of V1, then modify)
```

### Neo4j Index Isolation

| Version | Index Name | Dimensions | Group ID Pattern |
|---------|------------|------------|------------------|
| V1 | `chunk_embeddings` | 3072 | `test-5pdfs-*` |
| V2 | `chunk_embeddings_v2` | 2048 | `test-5pdfs-v2-*` |

---

## Configuration

### Environment Variables

| Variable | V1 | V2 | Notes |
|----------|----|----|-------|
| `VOYAGE_V2_ENABLED` | N/A | `"1"` | Master toggle for V2 |
| `VOYAGE_API_KEY` | N/A | Required | Voyage AI API key |
| `USE_SECTION_CHUNKING` | `"1"` | Deprecated | Replaced by V2 |
| `SECTION_GRAPH_ENABLED` | `"1"` | Deprecated | Replaced by V2 |

### Chunking Configuration (V2)

```python
# app/hybrid_v2/indexing/section_chunking.py

class SectionChunkConfigV2:
    min_tokens: int = 100           # Merge sections below this
    max_tokens: int = 1500          # Split sections above this
    overlap_tokens: int = 50        # Overlap between split chunks
    merge_tiny_sections: bool = True
    preserve_hierarchy: bool = True
    prefer_paragraph_splits: bool = True
```

### Chunk Metadata Schema (V2)

```python
{
    "id": "doc_001_chunk_3",
    "text": "The purpose of this Agreement is to...",
    "tokens": 245,
    "section_id": "sec_a1b2c3d4e5f6",
    "section_title": "Purpose and Scope",
    "section_level": 1,
    "section_path": ["Purpose and Scope"],
    "parent_doc_title": "Purchase Contract",       # NEW: Base document only
    "section_chunk_index": 0,
    "section_chunk_total": 1,
    "is_summary_section": true,
    "is_section_start": true
}
```

---

## Fallback Policy

| Condition | Behavior | Log Level |
|-----------|----------|-----------|
| Azure DI returns valid sections | Use section-aware chunking | INFO |
| Azure DI returns 0 sections | Fall back to fixed 512-token chunking | WARNING |
| Azure DI returns malformed sections | Skip malformed, chunk remaining | WARNING |
| Azure DI API failure | **Fail ingestion** (do NOT silently fall back) | ERROR |

---

## Pipeline Simplification (V2)

### Stages Removed

| Stage | V1 | V2 | Reason |
|-------|----|----|--------|
| Section Diversification | Required | **Removed** | Chunks *are* sections |
| Hub Entity Extraction | Required | **Removed** | Contextual embeddings capture doc context |

### Route 2 Upgrade

**Note:** Route 1 (Vector RAG) was already removed on January 24, 2026. V2 upgrades Route 2 (Local Search) with:
- Voyage embeddings (2048 dim) instead of OpenAI (3072 dim)
- Section-aware chunks for better semantic coherence
- Existing BM25+Vector hybrid approach retained

### Expected Latency Improvement

| Route | V1 | V2 (Expected) | Improvement |
|-------|----|----|-------------|
| Local Search | 2-4s | 1-2s | 50% faster |
| Global Search | 20-30s | 8-16s | 40-50% faster |
| DRIFT | 15-25s | 10-18s | 30% faster |

---

## Validation Plan

### Phase 1: V2 Indexing
1. Re-index `test-5pdfs` corpus with V2 pipeline
2. Verify chunk count (~17 vs V1's ~74)
3. Verify `section_title`, `parent_doc_title` metadata populated

### Phase 2: V2 Retrieval
1. Run Q-D/Q-N benchmark on V2
2. Target: 100% (57/57)
3. Specifically validate Q-D8 ("Exhibit A" counted as part of "Purchase Contract")

### Phase 3: Comparison
1. Compare V1 vs V2 accuracy
2. Compare V1 vs V2 latency
3. Compare V1 vs V2 storage cost

### Phase 4: Cut-Over
1. Enable V2 via feature flag (`VOYAGE_V2_ENABLED=1`)
2. 2-week soak period with monitoring
3. Deprecate V1 after successful soak

---

## Files to Create/Modify

### New Files (V2)
- `app/hybrid_v2/` - Copy from `app/hybrid/`
- `app/hybrid_v2/embeddings/voyage_embed.py` - Voyage integration
- `app/services/cu_standard_ingestion_service_v2.py` - Section-aware ingestion

### Modified Files
- `requirements.txt` - Add `voyageai`
- `app/core/config.py` - Add `VOYAGE_API_KEY`, `VOYAGE_V2_ENABLED`
- `.env` - Add Voyage credentials

### Unchanged (V1)
- `app/hybrid/` - All V1 code remains untouched

---

## Success Criteria

| Metric | Target |
|--------|--------|
| Q-D/Q-N Benchmark | 100% (57/57) |
| Q-D8 Document Counting | Correct (Fabrikam: 4, Contoso: 3) |
| Latency (Global Search) | < 16s p50 |
| Storage Reduction | ≥ 30% |
| V1 Stability | Zero regressions during V2 development |

---

## Timeline

| Week | Milestone |
|------|-----------|
| Week 1 | Create V2 directory, add Voyage dependency, implement `voyage_embed.py` |
| Week 2 | Implement section-aware chunking, create V2 Neo4j index |
| Week 3 | Simplify retrieval pipeline, run benchmarks |
| Week 4 | Comparison testing, documentation, feature flag setup |
| Week 5-6 | Production soak, V1 deprecation |

---

## References

- [ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md](ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md) Section 6.5
- [SECTION_CHUNKING_VERIFICATION.md](SECTION_CHUNKING_VERIFICATION.md)
- [Voyage AI Documentation](https://docs.voyageai.com/)
- [LlamaIndex VoyageEmbedding](https://docs.llamaindex.ai/en/stable/examples/embeddings/voyage/)
