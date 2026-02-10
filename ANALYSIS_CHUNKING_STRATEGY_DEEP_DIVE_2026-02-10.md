# Chunking & Embedding Strategy Deep Dive

**Date:** 2026-02-10  
**Status:** Analysis complete — ready for Phase 0 experiment  
**Author:** Co-pilot session with system architect  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current Architecture](#2-current-architecture)
3. [Problems Identified](#3-problems-identified)
4. [Option 1: Improve Existing Section-Based Chunking](#4-option-1-improve-existing-section-based-chunking)
5. [Option 2: Sentence-Level Chunking](#5-option-2-sentence-level-chunking)
6. [Mature Industry Strategies (References)](#6-mature-industry-strategies-references)
7. [Experiment Design — Phase 0](#7-experiment-design--phase-0)
8. [Production Scale Considerations](#8-production-scale-considerations)
9. [Decision Framework](#9-decision-framework)

---

## 1. Executive Summary

Our retrieval pipeline embeds all content types identically — prose paragraphs, linearized tables, headers, and mixed sections all receive the same voyage-context-3 treatment. For precision-critical domains (medical, legal, insurance, finance, research), this "one-size-fits-all" approach causes **three measurable problems**:

1. **Table data is invisible to retrieval** — table rows are linearized as `"HEADER: value | HEADER: value"` in chunk metadata but are **never embedded separately**. They are buried inside large (avg 641 token) section chunks.
2. **Chunks are too coarse** — at 100–1500 tokens, a single chunk may blend 3 unrelated topics. Retrieval returns the whole chunk when only 1–2 sentences are relevant → context pollution.
3. **DI sentence boundaries are noisy** — `language_spans` include table cells, form labels, and headers alongside real sentences, making raw sentence-level retrieval unreliable without filtering.

This document evaluates two improvement paths and defines a Phase 0 experiment to test both.

---

## 2. Current Architecture

### 2.1 Pipeline Flow

```
Azure DI (prebuilt-layout)
    ↓
document_intelligence_service.py
    • Strip pageHeader / pageFooter / pageNumber paragraphs
    • title → # H1, sectionHeading → ## H2
    • Tables → markdown pipes  (linearized into chunk text)
    • Table rows → "HEADER: value | …" sentences  (stored in metadata ONLY)
    • language_spans → sentence polygons  (stored in metadata ONLY)
    ↓
SectionAwareChunker (chunker.py)
    • Walk DI section tree
    • Merge tiny sections (< 100 tokens) with parent/sibling
    • Split large sections (> 1500 tokens) at paragraph boundaries
    • Overlap: 50 tokens between splits
    • Fallback: 512-token fixed chunking when no sections
    ↓
voyage-context-3  contextualized_embed()
    • All chunks embedded identically
    • Bin-packed into 30K-token context windows
    • 2048-dim vectors stored as embedding_v2
    ↓
Neo4j TextChunk nodes
    • 18 chunks (avg 641 tokens) across 5 test docs
    • Vector index: chunk_embeddings_v2 (cosine, 2048-dim)
```

### 2.2 Code Locations

| Component | File | Key Method |
|---|---|---|
| DI Processing | `src/worker/services/document_intelligence_service.py` | `_build_markdown_from_paragraphs_and_tables()` |
| Table Row Linearization | same | `_extract_table_row_sentences()` |
| Section Chunking | `src/worker/hybrid_v2/indexing/section_chunking/chunker.py` | `SectionAwareChunker.chunk_document()` |
| Embedding | `src/worker/hybrid_v2/embeddings/voyage_embed.py` | `embed_documents_contextualized()` |
| Noise Filters | `src/worker/hybrid_v2/pipeline/chunk_filters.py` | `apply_noise_filters()` |
| Pipeline Entry | `src/worker/hybrid_v2/indexing/lazygraphrag_pipeline.py` | `_chunk_di_units_section_aware()` |

### 2.3 Test Corpus: `test-5pdfs-v2-fix2`

| Metric | Value |
|---|---|
| Documents | 5 |
| TextChunks | 18 |
| Avg tokens/chunk | 641 |
| V2 max tokens | 1500 |
| Sentences (language_spans) | 347 |
| Sentence embeddings | **0 (none exist)** |
| Table row sentences in metadata | present but never embedded |
| Vector index | `chunk_embeddings_v2` (Voyage 2048-dim) |

### 2.4 What `contextualized_embed()` Already Gives Us

Voyage's `contextualized_embed()` API accepts `inputs = [[chunk1, chunk2, …]]` — all chunks from the same document in one call. Internally it:

- Reads the *surrounding chunks* as context for each chunk's embedding
- Produces embeddings that are aware of the document's broader meaning
- Uses a 32K-token context window (bin-packed for large docs)

This **partially** implements Anthropic's "contextual retrieval" and Jina's "late chunking" strategies. However, it only works at the **chunk level** — it cannot improve granularity *within* a chunk.

---

## 3. Problems Identified

### 3.1 Table Data Invisible to Retrieval

**Evidence:** `_extract_table_row_sentences()` in `document_intelligence_service.py` already linearizes each table row as:

```
"Invoice Number: INV-2024-001 | Date: 2024-03-15 | Amount: $12,450.00 | Status: Paid"
```

These are stored in `chunk.metadata.sentences` (source=`"table"`) but are **never embedded** separately. They are only searchable when they happen to appear in the parent chunk's markdown-pipe linearization — which is diluted by surrounding prose.

**Impact:** Queries like "What's the total amount for invoice INV-2024-001?" must match the entire section chunk instead of the specific table row. This is a **precision killer** for invoice/insurance/finance use cases.

### 3.2 Chunks Too Coarse for Precision Domains

**Evidence:** Average chunk size is 641 tokens. A medical report chunk might contain:

```
[Patient demographics] + [Diagnosis paragraph] + [Treatment plan] + [Medication list]
```

A query about ONE medication retrieves the entire chunk. The synthesis LLM must sift through 600+ tokens when only 50 are relevant.

**Impact:**
- Context window pollution (irrelevant material competes with relevant)
- Higher cost (tokens passed to synthesis LLM unnecessarily)
- Lower precision scores (F1 currently 0.479–0.521)

### 3.3 DI `language_spans` Are Noisy

**Evidence:** The 347 sentences extracted from `language_spans` across 5 test docs include:

| Category | Example | % of spans | Problem |
|---|---|---|---|
| Real sentences | "The patient was diagnosed with Type 2 diabetes." | ~60% | Good |
| Table cells | "12,450.00" | ~15% | Not a sentence |
| Form labels | "Name: ____" | ~10% | Not searchable content |
| Headers/footers | "Page 3 of 12" | ~5% | Should be stripped |
| Captions/notes | "See Appendix A" | ~5% | Marginal value |
| Mixed fragments | "Total" | ~5% | Too short to embed |

**Impact:** If we naively embed all `language_spans` as sentences, ~40% are noise that degrades retrieval quality. Any sentence-level strategy must include filtering.

### 3.4 No Content-Type Routing in Embedding

All chunk types — pure prose, tables-as-markdown, form fields, headers — are embedded identically by `embed_documents_contextualized()`. There is no:

- Separate embedding strategy for tabular data
- Boosting for structured/numeric content
- Differentiation between prose and list content

---

## 4. Option 1: Improve Existing Section-Based Chunking

### 4.1 What To Change

**A. Embed table row linearizations separately**

The infrastructure already exists. `_extract_table_row_sentences()` produces clean `"HEADER: value"` structures. We need to:

1. Promote table row sentences from metadata → standalone `TextChunk` nodes
2. Embed them with voyage-context-3 using the parent chunk/section as context
3. Store as separate nodes in Neo4j with `chunk_type = "table_row"`
4. Link them to parent chunk via `PART_OF` relationship

**B. Reduce max chunk size**

Current: `max_tokens = 1500`. This was designed for GraphRAG community summaries.  
Proposed: `max_tokens = 800` (halves average chunk size from 641 → ~350 tokens).  
This gives finer granularity without full sentence-level decomposition.

**C. Add content-type-aware embedding prefixes**

For table-row chunks: prepend `"Table row: "` before embedding.  
For KVP chunks: prepend `"Key-value: "` before embedding.  
For prose: no prefix (default behavior).

This helps the embedding model distinguish structured from unstructured content.

**D. Enhance noise filters**

Current filters (`chunk_filters.py`) apply post-retrieval soft penalties:
- form_label: 0.05× (nearly eliminate)
- bare_heading: 0.10× 
- min_content < 50 tokens: 0.20×

Add new filters:
- **table-only chunk**: if chunk is 100% table markdown AND table rows are embedded separately → 0.15× penalty (avoid double-counting)
- **numeric-only**: if chunk is >80% numbers/dates → flag for structured queries only

### 4.2 Pros

- ✅ Minimal code change (table row promotion is ~50 lines)
- ✅ Uses existing infrastructure (`_extract_table_row_sentences()` already works)
- ✅ Backward compatible (existing chunks remain; table rows are additive)
- ✅ Modest scale increase (~2× chunks, not 100×)
- ✅ No new dependencies
- ✅ `contextualized_embed()` already handles document context for free

### 4.3 Cons

- ❌ Doesn't solve intra-chunk precision for prose (still 350+ tokens per chunk)
- ❌ Table-row linearizations may lose relational context (row-to-row relationships)
- ❌ Doesn't leverage sentence-level geometry for pixel-accurate highlighting

### 4.4 Estimated Impact

| Metric | Current | Projected |
|---|---|---|
| TextChunks | 18 | ~36 (18 section + 18 table-row) |
| Avg tokens/chunk | 641 | ~350 (with max_tokens=800) |
| Table-specific F1 | low | significantly improved |
| Embedding cost | 1× | ~1.5× |
| Re-index required | yes | yes |

---

## 5. Option 2: Sentence-Level Chunking

### 5.1 Architecture Overview

```
Azure DI (prebuilt-layout)
    ↓
Sentence Extraction (NEW)
    • Filter DI language_spans to remove noise
    • Add table-row linearizations as synthetic sentences
    • Optionally: spaCy/LLM segmentation for clean boundaries
    ↓
Sentence embedding with voyage-context-3
    • contextualized_embed() with all sentences from same doc as context
    • 2048-dim vectors
    ↓
Neo4j Sentence nodes (NEW)
    • Separate from TextChunk nodes
    • PART_OF → TextChunk (parent) relationship
    • HAS_SENTENCE → Document relationship
    • Own vector index: sentence_embeddings_v2
    ↓
Retrieval: Top-k sentences → expand to parent chunks for synthesis context
```

### 5.2 Sentence Extraction Strategy

**Critical question: How to get clean sentences?**

| Strategy | Quality | Latency | Cost | Notes |
|---|---|---|---|---|
| **A. Filter DI `language_spans`** | Medium | 0ms | Free | Heuristic removal of table cells, headers, short fragments |
| **B. spaCy `en_core_web_sm`** | Good | ~1s/doc | Free | Handles abbreviations, decimal points; misses tables |
| **C. LLM segmentation** | Excellent | ~5s/doc | ~$0.02/doc | GPT-5-nano or mini to segment; expensive at scale |
| **D. DI paragraphs as sentences** | Good | 0ms | Free | Already available; coarser than true sentences but cleaner than language_spans |
| **E. Hybrid: DI paragraphs + filtered language_spans + table rows** | Best | ~1s/doc | Free | Recommended starting point |

**Recommended: Option E (Hybrid)**

1. Use DI paragraphs as base "sentence" units for prose sections
2. Add table-row linearizations from `_extract_table_row_sentences()`
3. Filter `language_spans` to EXCLUDE entries where:
   - `len(text) < 20 chars` (headers, labels, fragments)
   - `source == "table"` (already covered by table-row linearizations)
   - `confidence < 0.5` (low-quality OCR)
   - `text` matches `_FORM_LABEL_RE` from `chunk_filters.py`
4. Use filtered `language_spans` only when they provide sub-paragraph granularity not available from DI paragraphs

### 5.3 Pros

- ✅ Maximum retrieval precision (sentence-level granularity)
- ✅ Pixel-accurate citation highlighting (sentence polygons preserved)
- ✅ Clean separation of content types (prose vs table vs KVP)
- ✅ voyage-context-3 `contextualized_embed()` is designed for this — sentences with document context
- ✅ Parent-chunk expansion gives synthesis LLM necessary surrounding context

### 5.4 Cons

- ❌ **Scale**: 347 → ~3.5M sentences at production scale (10K docs). Embedding cost ~$175–350 for initial index
- ❌ **Complexity**: New `Sentence` node type, new vector index, new retrieval path
- ❌ **Parent expansion logic**: Must implement sentence → parent chunk → context window assembly
- ❌ **DI noise**: Requires robust filtering pipeline (not trivial)
- ❌ **Re-index required**: Full reprocessing of all documents
- ❌ **Benchmark may not show improvement**: If sentence boundaries are bad, precision could decrease

### 5.5 Production Scale Estimates

| Parameter | 5 docs (test) | 100 docs | 10K docs |
|---|---|---|---|
| Sentences | 347 | ~7K | ~700K |
| DI paragraphs | ~90 | ~1.8K | ~180K |
| Table rows | ~50 | ~1K | ~100K |
| Voyage API calls | 1 | ~20 | ~2K |
| Embedding cost | ~$0.01 | ~$1.75 | ~$175 |
| Neo4j nodes added | 347 | ~7K | ~700K |
| Vector index size | trivial | ~28MB | ~2.8GB |

---

## 6. Mature Industry Strategies (References)

### 6.1 Element-Type Routing (Unstructured.io)

**Source:** Unstructured.io partition + chunking pipeline

**Approach:** Classify each DI element (paragraph, table, header, list, image) → route to type-specific chunker → embed with type-aware strategy.

**Key insight:** Tables should NEVER be chunked the same way as prose. Linearize rows, embed separately, link to table context.

**Relevance to us:** We already have element classification from DI. We just don't USE it during embedding. Implementing this would mean routing table rows to a separate embedding path — exactly what Option 1.A proposes.

### 6.2 Contextual Header Stacking (Anthropic)

**Source:** Anthropic "Contextual Retrieval" blog post (2024)

**Approach:** Prepend document-level context (title, section headers, summary) to each chunk before embedding. This gives the embedding model awareness of where the chunk sits in the document.

**Key insight:** A chunk that says "The dosage is 500mg daily" means nothing without context: which drug? which patient? Prepending "Document: Treatment Protocol for Metformin | Section: Dosage Guidelines" makes the embedding dramatically more specific.

**Relevance to us:** `contextualized_embed()` does this automatically at the API level. However, we could ALSO prepend section_path as explicit text for additional signal. Belt and suspenders.

### 6.3 Late Chunking (Jina AI)

**Source:** Jina AI "Late Chunking" paper (2024)

**Approach:** Embed the entire document through a long-context model, then split the embedding sequence into chunk-aligned segments AFTER the attention mechanism has seen the full document.

**Key insight:** Traditional chunking → embedding loses cross-chunk context. Late chunking preserves it because attention operates on the full document.

**Relevance to us:** `contextualized_embed()` is Voyage's implementation of a similar idea. Instead of late-splitting embeddings, they provide document context alongside each chunk during embedding. We're already using this. The question is whether our CHUNKS are the right granularity to maximize its benefit.

### 6.4 Parent-Child Chunking (Microsoft GraphRAG / LlamaIndex)

**Source:** Microsoft GraphRAG documentation, LlamaIndex HierarchicalNodeParser

**Approach:** Create two levels of chunks: small "leaf" chunks for precision retrieval, large "parent" chunks for synthesis context. Retrieve at leaf level, expand to parent for LLM.

**Key insight:** Small chunks give precision; large chunks give context. You need both.

**Relevance to us:** This is exactly what sentence-level retrieval with parent-chunk expansion would give us. Our existing `TextChunk` nodes become parents; `Sentence` nodes become leaves. The graph already has the infrastructure for `PART_OF` relationships.

---

## 7. Experiment Design — Phase 0

### 7.1 Goal

Measure whether finer-grained retrieval units improve precision/recall/F1 on our existing benchmark queries, **without re-indexing**.

### 7.2 Approach: Script-Only Experiment

```
Phase 0 Experiment (script only — no production changes)

Step 1: Extract candidate retrieval units from existing data
    a) DI paragraphs (already in chunk metadata)
    b) Table-row linearizations (already in chunk metadata)
    c) Filtered language_span sentences (existing, need filtering)

Step 2: Embed each unit with voyage-context-3
    - Use contextualized_embed() with all units from same doc
    - Store embeddings in memory (no Neo4j write)

Step 3: Run benchmark queries
    - Cosine similarity top-k retrieval
    - Compare against current chunk-level retrieval

Step 4: Measure
    - Precision@k, Recall@k, F1@k for k = 3, 5, 10
    - Context size (avg tokens returned)
    - Per-query analysis: which queries improved, which degraded
```

### 7.3 Experiment Variants

| Variant | Retrieval Unit | Expected Behavior |
|---|---|---|
| **Baseline** | Current TextChunks (18, avg 641 tok) | Current production behavior |
| **V1: Paragraphs + table rows** | DI paragraphs + table row linearizations | Finer than chunks, no language_span noise |
| **V2: Filtered sentences** | language_spans filtered (≥20 chars, no tables, no form labels) | Finest granularity, highest noise risk |
| **V3: Hybrid** | V1 + V2 combined, deduplicated | Maximum coverage, needs dedup |
| **V4: Smaller chunks** | TextChunks with max_tokens=800 | Lowest-risk improvement |

### 7.4 Key Metrics to Watch

- **Table queries** (e.g., "What is the invoice total?"): V1 should dramatically outperform Baseline
- **Specific-fact queries** (e.g., "When was the policy effective?"): V2 should improve precision
- **Multi-hop queries** (e.g., "Compare coverage across all policies"): Baseline may win (needs broad context)
- **Context efficiency**: tokens returned per correct answer

### 7.5 Script Skeleton

```python
# scripts/experiment_chunking_strategy.py

"""
Phase 0: Chunking Strategy Experiment
Compares retrieval precision across different granularity levels.
No production changes — read-only experiment.
"""

import asyncio
import json
import numpy as np
from neo4j import AsyncGraphDatabase

# 1. Connect to Neo4j, pull existing chunks + metadata
# 2. Extract: paragraphs, table_rows, filtered_sentences from metadata
# 3. Embed all variants with voyage-context-3 contextualized_embed()
# 4. For each benchmark query:
#    a. Embed query with voyage-context-3 (query mode)
#    b. Cosine similarity against each variant's embeddings
#    c. Top-k retrieval
#    d. Score against ground truth
# 5. Report comparison table

BENCHMARK_QUERIES = [
    # Format: (query, expected_doc_ids, expected_content_keywords)
    ...  # Load from existing benchmark
]
```

---

## 8. Production Scale Considerations

### 8.1 Embedding Cost Projections

| Approach | Chunks/Sentences per Doc | 10K Docs Total | Voyage Cost (@ $0.05/M tokens) |
|---|---|---|---|
| Current (section chunks) | ~4 | ~40K | ~$35 |
| Option 1 (+ table rows) | ~8 | ~80K | ~$55 |
| Option 2 (sentences) | ~70 | ~700K | ~$175 |
| Option 2 (sentences + parents) | ~74 | ~740K | ~$180 |

### 8.2 Neo4j Index Impact

| Approach | Nodes Added | Memory for HNSW Index | Query Latency Impact |
|---|---|---|---|
| Current | 0 | 0 | baseline |
| Option 1 | ~40K | ~160MB | negligible |
| Option 2 | ~700K | ~2.8GB | <5ms per query added |

### 8.3 Retrieval Latency

Sentence-level retrieval adds ONE extra step: expand sentences → parent chunks. This is a simple Cypher traversal:

```cypher
MATCH (s:Sentence)-[:PART_OF]->(c:TextChunk)
WHERE s.id IN $sentence_ids
RETURN DISTINCT c
```

Expected impact: <5ms added to retrieval.

---

## 9. Decision Framework

### When to choose Option 1 (Improve Section Chunks)

- ✅ Table-heavy corpus (invoices, insurance forms, financial reports)
- ✅ Need quick win without major architecture change
- ✅ Budget-sensitive (minimal embedding cost increase)
- ✅ Existing chunk boundaries are semantically reasonable

### When to choose Option 2 (Sentence-Level)

- ✅ Prose-heavy corpus (medical reports, legal documents, research papers)
- ✅ Pixel-accurate citation highlighting is a hard requirement
- ✅ F1 improvement of 5%+ would be commercially significant
- ✅ Willing to invest in re-indexing and new retrieval path

### Recommended Path

**Start with Phase 0 experiment** (tomorrow morning). If V1 (paragraphs + table rows) shows ≥3% F1 improvement on table-heavy queries, implement Option 1 first (2-3 days of work). If V2 (sentences) shows ≥5% F1 improvement on prose queries, plan Option 2 as a follow-on sprint (1–2 weeks).

Both options are **additive** — Option 1 can be implemented first, and Option 2 can be layered on top later. They are not mutually exclusive.

---

## Appendix A: Relevant Config Parameters

```python
# Section chunking (chunker.py)
SectionChunkConfig(
    min_tokens=100,       # Merge threshold
    max_tokens=1500,      # Split threshold (consider reducing to 800)
    overlap_tokens=50,    # Split overlap
    fallback_chunk_size=512,  # When no DI sections
    fallback_overlap=64,
)

# Noise filters (chunk_filters.py)
FORM_LABEL_PENALTY = 0.05     # Nearly eliminate
BARE_HEADING_PENALTY = 0.10   # Nearly eliminate
LOW_CONTENT_PENALTY = 0.20    # Strong but not fatal
MIN_CONTENT_TOKENS = 50       # Token floor

# Embedding (voyage_embed.py)
VOYAGE_EMBEDDING_DIM = 2048
VOYAGE_MODEL = "voyage-context-3"
BIN_PACK_MAX_TOKENS = 30000   # 32K context - 2K headroom
```

## Appendix B: Customer Domain Sensitivity Matrix

| Domain | Table Data | Prose Precision | Citation Accuracy | Recommended Option |
|---|---|---|---|---|
| Medical | Medium | Critical | High | Option 2 |
| Legal | Low | Critical | Critical | Option 2 |
| Insurance | High | Medium | High | Option 1 first |
| Finance | High | Medium | Medium | Option 1 first |
| Research | Low | High | Medium | Option 2 |

---

*End of analysis. Phase 0 experiment script to be built tomorrow morning.*
