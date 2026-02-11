# Architecture: Deterministic Skeleton + Sparse k-NN Hybrid

**Date:** 2026-02-11  
**Updated:** 2026-02-11 (content taxonomy, DI/CU architecture, spaCy sentence detection, cross-chunk dedup)  
**Status:** Phase 0 experiment ready  
**Origin:** New inspiration — validated against existing codebase + research conversation  
**Experiment script:** `scripts/experiment_hybrid_skeleton.py`

---

## Content Taxonomy: What Gets Embedded vs. Metadata

Informed by Azure DI output analysis on real data (5 PDFs, 18 chunks, 708 raw DI sentences).

### Architecture: DI Primary + CU Supplement

```
PDF
 ├── DI (primary) ──→ OCR, tables, KVPs, sections, word geometry, barcodes
 │                     ↓
 │                   chunk text → spaCy → full SentenceNodes
 │
 └── CU (supplement, Phase 2) ──→ ONLY for figure descriptions + equation LaTeX
                                    ↓
                                  SentenceNodes (source="figure_description" / "equation")
```

DI stays as the backbone (~95% of the work). CU is called **only** for documents that
contain figures or complex equations — features DI doesn't offer.

### Embed as SentenceNodes (searchable via Voyage)

| Content Type | Source | source tag | Notes |
|---|---|---|---|
| **Body text** | DI chunk text → spaCy split | `"paragraph"` | spaCy handles abbreviations (P.O., Inc., Ltd.) — DI regex mis-splits at abbreviation periods |
| **Table rows** | DI table extraction → linearize | `"table_row"` | `"Header: val \| Header: val"` format. Answers structured queries directly |
| **Figure captions** | DI figure extraction | `"figure_caption"` | Caption text from detected figures |
| **Figure descriptions** | CU `enableFigureDescription` (Phase 2) | `"figure_description"` | Natural language summary of visual content. Mermaid/Chart.js for diagrams |
| **Equations (display)** | CU LaTeX or pix2tex fallback (Phase 2) | `"equation"` | Context sentence + LaTeX merged. Equations ARE the answer, not metadata |

### Store as Metadata Only (not embedded)

| Content Type | Why Not Embed | How Used |
|---|---|---|
| **KVPs** (key-value pairs) | Already in body text — embedding doubles count | Exact-match lookup (Route 4 style) |
| **Titles / Section headings** | Labels, not sentences — no semantic content alone | `section_path` metadata on child sentences |
| **Page headers / footers** | Repeated boilerplate, zero retrieval value | Dropped by DI paragraph role filter |
| **Barcodes / QR codes** | Identifiers, not semantic content | Structured metadata for exact filter |
| **Selection marks** (checkboxes) | Boolean flags, not searchable | Metadata on parent paragraph |

### Why spaCy Replaces DI Regex for Sentence Detection

DI's `_extract_sentences_with_geometry()` uses naive regex `(?<=[.!?])\s+` which mis-splits:
- `"Contoso Ltd. is at P.O. Box 123, FL."` → 4 fragments  
- spaCy keeps it as 1 sentence

Measured on real data: DI produced 453 noise-filtered "sentences" (25/chunk avg). After
spaCy + merge + cross-chunk dedup: ~120-150 sentences (7-8/chunk avg). 72% reduction.

---

## Core Insight

This hybrid approach is **not just the right answer — it's the natural evolution of what the codebase already partially implements**. Here's the mapping:

| Hybrid Concept | Already Exists | What's Missing |
|---|---|---|
| **Section hierarchy** | `:Section` nodes, `SUBSECTION_OF`, `HAS_SECTION`, `IN_SECTION` | Nothing — fully implemented |
| **Sentence extraction** | `SentenceGeometry` dataclass, DI sentence polygons in chunk metadata | `:Sentence` nodes in Neo4j. DI regex replaced by spaCy for accuracy |
| **Table row sentences** | `_extract_table_row_sentences()` produces clean linearizations; tables in chunk metadata | Not embedded or stored as separate nodes |
| **Paragraph grouping** | DI paragraphs available in pipeline | No `:Paragraph` intermediate node type |
| **Semantic embedding** | `voyage-context-3` with `contextualized_embed()`, 2048-dim vectors | Only at chunk level, not sentence level |
| **Sparse semantic linking** | `SEMANTICALLY_SIMILAR` edges between Sections (threshold 0.43), GDS KNN infrastructure | Not at sentence level, threshold too low for sparsity |
| **Context expansion** | `MENTIONS` → `TextChunk` → `IN_SECTION` traversal in Route 3 PPR | No sentence → parent expansion path |
| **Re-ranking** | LLM synthesis with doc-scope filtering, noise penalties | No dedicated cross-encoder re-rank stage (may not need one at sentence level) |

**Bottom line:** ~70% of the infrastructure exists. The missing 30% is the sentence/paragraph node layer and sentence-level vector index.

---

## The Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 3: SEMANTIC                         │
│  Sparse RELATED_TO edges (similarity > 0.90)                │
│  Cross-chunk, cross-document hidden connections              │
│  k=1-2 per sentence only                                     │
│  ♦ This is the ONLY layer that uses algorithms (k-NN)        │
├─────────────────────────────────────────────────────────────┤
│                    LAYER 2: EMBEDDING                        │
│  Sentence embeddings: voyage-context-3 (2048-dim)           │
│  Vector index: sentence_embeddings_v2                        │
│  Contextualized with document-level context                  │
├─────────────────────────────────────────────────────────────┤
│                    LAYER 1: SKELETON (Deterministic)         │
│  Document → Section → Paragraph → Sentence                  │
│  Edges: NEXT, PART_OF (parsed from document, no algorithms)  │
│  Clean, sparse, structurally faithful                        │
│  ♦ 100% of these edges come from DI document parsing          │
└─────────────────────────────────────────────────────────────┘
```

## Mapping to Existing Graph Schema

### Current Schema (already in Neo4j)

```
(:Document)-[:HAS_SECTION]->(:Section)
(:Section)-[:SUBSECTION_OF]->(:Section)
(:TextChunk)-[:IN_SECTION]->(:Section)
(:TextChunk)-[:IN_DOCUMENT]->(:Document)
(:Entity)-[:MENTIONS]->(:TextChunk)
(:Section)-[:SEMANTICALLY_SIMILAR]->(:Section)  ← already sparse semantic linking!
```

### Extended Schema (what to add)

```
# Deterministic hierarchy (parsed from document structure, no algorithms):
(:Sentence)-[:PART_OF]->(:Paragraph)          ← sentence belongs to paragraph
(:Paragraph)-[:PART_OF]->(:Section)            ← paragraph belongs to section
(:Sentence)-[:NEXT]->(:Sentence)               ← reading order within chunk

# Implementation-level containment (bridges to existing TextChunk layer):
(:Sentence)-[:PART_OF]->(:TextChunk)           ← sentence belongs to chunk
(:Paragraph)-[:PART_OF]->(:TextChunk)          ← paragraph belongs to chunk

# Semantic layer (probabilistic, k-NN with strict threshold):
(:Sentence)-[:RELATED_TO]->(:Sentence)         ← sparse semantic links (>0.90)
```

The complete deterministic chain is:
```
SENTENCE ─PART_OF→ PARAGRAPH ─PART_OF→ SECTION ─PART_OF→ DOCUMENT
SENTENCE ─NEXT→ SENTENCE (reading order)
```

This hierarchy is **entirely parsed from document structure** — no algorithms
guess these relationships. DI tells us which sentences form a paragraph,
which paragraphs sit in a section, and which sections belong to a document.
The skeleton simply stores what the parser already knows.

### What Does NOT Change

- Entity graph (`:Entity`, `MENTIONS`, `RELATED_TO` between entities)
- Community structure (`:Community`, `BELONGS_TO`)
- Section hierarchy (`:Section`, `SUBSECTION_OF`)
- Existing TextChunk embeddings (kept for backward compat)
- All 4 retrieval routes (this adds a new sub-route, doesn't replace)

---

## How the Three-Stage Retrieval Integrates

### Current Route 1 (Vector RAG)
```
Query → embed → cosine similarity on TextChunk.embedding_v2 → top-k chunks → synthesis
```

### Proposed Route 1-S (Sentence-Level Hybrid)
```
Stage 1: Semantic Anchor
  Query → embed → cosine similarity on Sentence.embedding_v2 → top-5 sentences

Stage 2: Context Expansion (Graph Traversal)
  For each anchor sentence:
    ─ PART_OF → TextChunk (get parent chunk for full context)
    ─ NEXT/PREV × 2 → neighboring sentences (sliding window)
    ─ RELATED_TO → semantically linked sentences in other chunks
    ─ PART_OF target chunk → IN_SECTION → Section (get section context)

Stage 3: Re-ranking
  Deduplicate expanded chunks → score by anchor density → LLM synthesis
```

### Cypher for Stage 2 (production implementation)

```cypher
// Given anchor sentence IDs from vector search
MATCH (s:Sentence)-[:PART_OF]->(c:TextChunk)-[:IN_DOCUMENT]->(d:Document)
WHERE s.id IN $anchor_ids

// Get parent chunks
WITH s, c, d

// Expand via NEXT/PREV (window of 2)
OPTIONAL MATCH (s)-[:NEXT*1..2]->(next:Sentence)
OPTIONAL MATCH (prev:Sentence)-[:NEXT*1..2]->(s)

// Expand via RELATED_TO (sparse semantic links)
OPTIONAL MATCH (s)-[:RELATED_TO]->(related:Sentence)-[:PART_OF]->(rc:TextChunk)

// Collect
WITH COLLECT(DISTINCT c) + COLLECT(DISTINCT rc) AS all_chunks,
     COLLECT(DISTINCT s) + COLLECT(DISTINCT next) + COLLECT(DISTINCT prev) + COLLECT(DISTINCT related) AS all_sentences
UNWIND all_chunks AS chunk
MATCH (chunk)-[:IN_DOCUMENT]->(doc:Document)
OPTIONAL MATCH (chunk)-[:IN_SECTION]->(sec:Section)
RETURN DISTINCT chunk, doc, sec
```

---

## Why This Approach Is Right for This System

### 1. Sparsity Is Already the Design Philosophy

The existing codebase already prioritizes sparsity:
- `_build_section_similarity_edges()` uses a threshold (0.43) and `max_edges_per_section=5`
- GDS KNN has configurable `knn_top_k` (currently disabled when set to 0)
- Denoising passes (doc-scope, community filter, score gap, semantic dedup) all reduce noise

The hybrid approach takes this further by applying the same principle at sentence level with a **much higher threshold** (0.90 vs 0.43). This is correct because:
- Sentences are more numerous than sections (~350 vs ~15)
- Low thresholds at sentence level would create explosive edge counts
- High thresholds ensure only truly important cross-references survive

### 2. Contextual Embedding Already Works at Document Level

`voyage-context-3`'s `contextualized_embed()` is designed to embed smaller units with awareness of the larger document. Currently it only operates on chunks (avg 641 tokens). Applied to sentences (~20-50 tokens each), it will produce **dramatically more specific embeddings** because:
- Each sentence embedding captures its meaning in context
- The same sentence in different documents gets different embeddings
- This is exactly the "parent-child" pattern from LlamaIndex/Microsoft GraphRAG

### 3. The Graph Already Supports Multi-Hop Discovery

Route 3 (HippoRAG PPR) already does multi-hop graph traversal from entities to chunks to sections. Adding sentence nodes creates a **finer-grained traversal mesh**:
- Current: `Entity → MENTIONS → TextChunk → IN_SECTION → Section`
- Enhanced: `Entity → MENTIONS → TextChunk → has Sentence → RELATED_TO → Sentence → PART_OF → another TextChunk`

This enables discovery of semantically related content that shares no entities.

### 4. The DI Sentence Infrastructure Is Ready

`_extract_sentences_with_geometry()` already produces clean sentence data with:
- Text, offset, length, page, confidence
- Multi-polygon geometry for pixel-accurate highlighting
- Table row linearizations via `_extract_table_row_sentences()`

The only missing piece is storing these as Neo4j nodes instead of chunk metadata.

---

## Test Plan (Phase 0 → Production)

### Phase 0: In-Memory Experiment (TODAY)

Script: `scripts/experiment_hybrid_skeleton.py`

- Pull chunks + metadata from Neo4j
- Build skeleton in memory (Python dicts, not Neo4j writes)
- Embed sentences with Voyage
- Run sparse k-NN with threshold sweep (0.80, 0.85, 0.90, 0.92, 0.95)
- Compare vs baseline chunk retrieval on keyword-hit metric
- **Expected output:** Which threshold + granularity level gives best results

```bash
# Basic run
python scripts/experiment_hybrid_skeleton.py --group-id test-5pdfs-v2-fix2

# Threshold sweep
python scripts/experiment_hybrid_skeleton.py --sweep-thresholds

# Custom config
python scripts/experiment_hybrid_skeleton.py \
  --similarity-threshold 0.85 \
  --max-related 2 \
  --top-k 5 \
  --expand-window 2
```

### Phase 1: Sentence Nodes in Neo4j (1-2 days)

If Phase 0 shows improvement:
- Add `:Sentence` node type to `initialize_schema()` in `neo4j_store.py`
- Create `sentence_embeddings_v2` vector index (cosine, 2048-dim)
- Extend `_build_section_graph()` to also create Sentence nodes
- Add NEXT edges between sequential sentences
- Add PART_OF edges to parent TextChunk
- Backfill for existing indexed corpora

### Phase 2: Sparse Semantic Links (1 day)

- Extend `_build_section_similarity_edges()` pattern to sentence level
- Use threshold 0.90 (or whatever Phase 0 determines)
- Max k=2 per sentence, cross-chunk only
- Edge type: `RELATED_TO` with `{source: "knn_sentence", similarity: 0.93}`

### Phase 3: Three-Stage Retrieval (2-3 days)

- Add `search_sentences_v2()` to `neo4j_store.py` (vector search on Sentence nodes)
- Implement sentence → chunk expansion in `enhanced_graph_retriever.py`
- Add as Route 1-S (sentence-level vector RAG) in the router
- Full benchmark against existing 4 routes

### Phase 4: Production (1 week)

- Full re-index with sentence extraction
- Update synthesis to use sentence-level citations
- A/B test against current production
- Monitor precision/recall/F1 on live traffic

---

## Design Consideration 1: Unified Node Metadata

**Principle:** Voyage semantic search and graph structural search must operate on the **same** sentence node. No dual-node, no separate index.

### Why Unified?

If we stored sentence embeddings in a separate vector index and sentence structure in the graph, every retrieval would require a join — matching Voyage results (by text/ID) to graph nodes (by relationship). This creates:
- Alignment bugs (what if a sentence exists in one store but not the other?)
- Latency from cross-store joins
- Impedance mismatch between "top-k by cosine" and "2-hop by structure"

Instead, each `:Sentence` node carries **both**:
- `embedding_v2`: 2048-dim Voyage vector (for Neo4j vector index search)
- Structural metadata: `prev_sentence_id`, `next_sentence_id`, `parent_paragraph_id`, `parent_paragraph_text`

This means after Voyage finds the top-k sentences, we already have the structural metadata on the same node — zero additional hops for context assembly.

### Metadata Fields

| Field | Type | Purpose |
|---|---|---|
| `id` | string | Unique sentence identifier |
| `text` | string | Sentence text |
| `embedding_v2` | float[2048] | Voyage-context-3 embedding |
| `source` | string | `"language_span"`, `"table_row"`, `"extracted"` |
| `page` | int | Page number in source document |
| `confidence` | float | Extraction confidence (0-1) |
| `char_offset` | int | Character offset in parent chunk |
| `char_length` | int | Character length |
| `polygons` | json | Pixel-accurate geometry for highlighting |
| `parent_paragraph_id` | string | Links to parent paragraph (metadata, not edge) |
| `parent_paragraph_text` | string | Full parent paragraph text (denormalized) |
| `prev_sentence_id` | string | Previous sentence in reading order |
| `next_sentence_id` | string | Next sentence in reading order |

### Why Denormalize `parent_paragraph_text`?

Storing the full paragraph text on each sentence node seems wasteful (duplication), but it enables the **"sentence search, paragraph display"** pattern with zero graph hops:

1. Voyage finds top-5 sentences by cosine similarity
2. For each sentence, read `parent_paragraph_text` directly from the node
3. Return paragraph-level context to LLM without any MATCH/TRAVERSE

The storage cost is negligible (~2-5KB per sentence × 350 sentences = ~1MB for test corpus).

---

## Design Consideration 2: Context Window Strategy ("Sentence Search, Paragraph Display")

**Principle:** Embed at sentence granularity for precision. Display at paragraph granularity for coherence.

### The Problem with Chunk-Level Retrieval

Current Route 1 retrieves 641-token chunks. For specific-fact queries ("What was the invoice total?"), most of those 641 tokens are irrelevant padding — the answer is one sentence. This wastes the LLM's context window and dilutes attention.

### The Problem with Sentence-Level Display

Pure sentence retrieval (returning only the matched sentence) strips away context. The LLM sees "The total was $5,432" but not "This invoice covers services rendered in Q3 2025 for the East Region office." Without surrounding context, the LLM may hallucinate or hedge.

### The Solution: Sentence Search, Paragraph Display

```
Query: "What was the invoice total for Q3?"

Step 1 (Sentence Search):
  Voyage finds: "The total was $5,432.00" (similarity: 0.94)

Step 2 (Paragraph Display — metadata-driven):
  Read parent_paragraph_text from the same node:
  "This invoice covers services rendered in Q3 2025 for the
   East Region office. The total was $5,432.00, due within
   30 days of receipt."

Step 3 (Wider Window — graph-driven):
  If needed, follow prev_sentence_id/next_sentence_id to get
  sentences from adjacent paragraphs for additional context.
```

### Three-Priority Context Assembly

The `stage2_context_expansion()` function implements this as three priorities:

1. **Priority 1 (Zero-hop, metadata):** Read `parent_paragraph_text`, `prev_sentence_id`, `next_sentence_id` directly from the anchor sentence node. Cost: 0 graph hops.

2. **Priority 2 (1-hop, graph traversal):** Follow NEXT/PREV edges ×2 to get a wider sentence window. Useful when the paragraph boundary doesn't contain enough context. Cost: 1 hop.

3. **Priority 3 (Cross-chunk, semantic):** Follow RELATED_TO edges to find semantically related sentences in other chunks. This is where the sparse k-NN links add value — discovering connections that pure proximity can't find. Cost: 1 hop.

### Why Voyage-context-3 Makes This Work

Voyage's `contextualized_embed()` API takes both the sentence AND its document context as input. This means:
- Each sentence embedding already encodes "where this sentence lives in the document"
- No need for explicit `[SENTENCE_START]`/`[SENTENCE_END]` markers
- The model implicitly understands sentence boundaries within paragraphs
- Two identical sentences in different documents get different embeddings

This is a critical architectural advantage: the embedding model handles the context-awareness, so we don't need to engineer it at the graph level.

---

## Design Consideration 3: Edge Strategy (Deterministic vs. Probabilistic)

**Principle:** Deterministic edges and probabilistic edges serve fundamentally different purposes and must NEVER be conflated.

### Two Types of Edges

| Property | Deterministic Edges | Probabilistic Edges |
|---|---|---|
| **Types** | NEXT, PREV, PART_OF | RELATED_TO |
| **Source** | Document structure parsing | k-NN on sentence embeddings |
| **Guarantees** | 100% correct, complete, ordered | Approximate, threshold-dependent |
| **Cardinality** | Exactly 1 NEXT, 1 PREV per sentence (within chunk) | 0-2 RELATED_TO per sentence |
| **Purpose** | Reading order, containment, hierarchy | Cross-chunk semantic discovery |
| **When created** | At indexing time, from DI output | After embedding, as a separate pass |

### Why This Distinction Matters

If we let k-NN generate NEXT/PREV edges (i.e., the "nearest" sentence must be the next one), we'd get:
- False reading orders (similar sentences from different documents linked as sequential)
- Broken paragraph boundaries (sentences jump between paragraphs by similarity)
- Unreliable context windows (following "NEXT" might land you in a different document)

Conversely, if we tried to generate RELATED_TO edges from document structure, we'd get:
- Only within-document links (no cross-document discovery)
- Proximity bias (sentence n is always "related to" sentence n±1)
- No novel connections

**Rule:** Deterministic edges come from document parsing. Probabilistic edges come from embedding space. No exceptions.

### Edge Budget Analysis

To maintain O(n) sparsity (where n = sentence count):

```
Deterministic edges:
  NEXT:    n-1 per document (linear in sentence count)
  PREV:    n-1 per document (linear)
  PART_OF: n per document (each sentence → 1 chunk)
  Total:   ~3n

Probabilistic edges:
  RELATED_TO: max k=2 per sentence, cross-chunk only
  Worst case: 2n
  Typical:    0.5n-1n (many sentences won't find partners above 0.90)

Total edge budget: ~4n-5n = O(n) ✓
```

For the test corpus (347 sentences): ~1,400-1,700 edges total, which is extremely manageable.

**Budget invariant:** `semantic_edges ≤ 2 × sentence_count`. If this invariant is violated, the threshold is too low.

### Threshold Selection

Why 0.90 as the minimum threshold for RELATED_TO?

- At **chunk level** (641 tokens), the existing threshold is 0.43 — this is correct because chunks are large, diverse units where even moderate similarity is meaningful
- At **sentence level** (~20-50 tokens), sentences are specific and focused; a 0.43 threshold would create massive noise (nearly every sentence about "invoices" would link to every other)
- At **0.90+**, only genuinely paraphrased or closely related sentences link — typically cross-document references to the same fact, or alternative phrasings of the same finding
- The Phase 0 experiment sweeps [0.80, 0.85, 0.90, 0.92, 0.95] to find the empirical sweet spot

---

## Design Consideration 4: Hallucination Controls in Re-Ranking

**Principle:** The most dangerous hallucinations happen not in embedding or retrieval, but in the final LLM re-ranking and synthesis step, where the model may extrapolate beyond what the retrieved context supports.

### Where Hallucinations Originate

```
Stage 1 (Anchor Selection):     Low risk — cosine similarity is deterministic
Stage 2 (Context Expansion):    Low risk — graph traversal follows real edges
Stage 3 (Re-ranking):           MEDIUM risk — LLM scores relevance (may hallucinate relevance)
Stage 4 (Synthesis/Answer):     HIGH risk — LLM generates text from context (may extrapolate)
```

### Five Anti-Hallucination Strategies

#### 1. Confidence Gating (Pre-filter)

Before re-ranking, discard sentences with extraction confidence below threshold (0.5). These are often:
- OCR artifacts from scanned documents
- Partial sentences from table cell extraction
- Form labels that DI misidentified as content

```python
# In stage3_rerank_and_select():
confident_sentences = [s for s in context_sentences
                       if s.get("confidence", 1.0) >= CONFIDENCE_FLOOR]
```

#### 2. Structural Coherence Scoring

Boost chunks where anchor sentences cluster together (same paragraph or consecutive). Penalize isolated anchors — if a single sentence from a 50-sentence chunk matches but nothing around it does, it's likely a false positive.

```
Same paragraph, multiple anchors:  +1.5 bonus
Single isolated anchor:            no bonus
```

#### 3. Pointwise Relevance: Do We Even Need a Reranker?

**At sentence level, probably not (Phase 0-2).** Here's why:

The bi-encoder weakness (coarse matching) is most severe with large chunks (641 tokens). A chunk about "insurance policies" scores high for "What's the policy number?" even if the number is in a different chunk. At sentence level (~20-50 tokens), this problem mostly disappears — embeddings are specific enough that top-k is already precise.

Phase 0-2: Keyword overlap density + structural coherence scoring (no external API).

Phase 3+: Add `voyage-rerank-2.5` cross-encoder **only if benchmarks show** the right sentences exist in top-20 but not in top-5 (ranking error, not retrieval error). Cross-encoders see query and passage simultaneously (word-level interaction), so they can catch subtle relevance differences that bi-encoders miss.

**Important cost model:** A reranker is a **per-query cost**, not a one-time indexing cost. Every user query sends N×(query, passage) pairs to the API. At ~$0.05/1000 pairs and 20 candidates per query, that's ~$0.001/query — cheap but recurring.

#### 4. Grounding Constraint

Every sentence in the final context must be traceable to a specific source document, page, and extraction method. The re-ranker checks:
- Does the sentence have a valid `doc_id`?
- Is the `source` type known (language_span, table_row, extracted)?
- If mixing multiple source types, apply a penalty (mixed-source contexts are harder for the LLM to reason about coherently)

#### 5. Structural Pruning Before LLM

Before sending context to the synthesis LLM, prune structurally:
- Remove duplicate sentences (exact match)
- Remove sentences that are substrings of other sentences in the context
- Limit context to N sentences per source document (prevents single-document domination)
- Order by document reading order, not similarity score (maintains coherence)

### Re-Ranking Strategy: When (and Whether) to Add a Cross-Encoder

LLM reranking (GPT-4/Claude as a relevance judge) is **not recommended** for production RAG: non-deterministic, position-biased, 50-500× more expensive, and can hallucinate relevance.

But the real question is: **do we need ANY external reranker at sentence level?**

| Scenario | Reranker needed? | Why |
|---|---|---|
| Chunk-level retrieval (641 tokens) | Yes, strongly | Chunks are topically broad; cosine similarity is coarse |
| Sentence-level retrieval (20-50 tokens) | Maybe not | Embeddings are precise; top-k is often correct |
| After graph expansion | Depends on expansion quality | If NEXT/PREV adds noise, reranker filters it |

**Recommended phased approach:**

```
Phase 0-2 (NOW):
  Stage 1: Voyage embedding → vector search → top-k sentence anchors
  Stage 2: Graph expansion (NEXT/PREV/RELATED_TO) → context sentences
  Stage 3: Heuristic scoring (confidence + structural coherence + keywords)
  Stage 4: LLM synthesis (ANSWER ONLY, not ranking)

Phase 3+ (IF benchmarks show ranking errors):
  Stage 3 becomes: voyage-rerank-2.5 cross-encoder scoring
  Adds: ~$0.001/query, 10-50ms latency
  Note: per-query cost (recurring), NOT one-time indexing cost
```

The decision point: after Phase 2 benchmarks, check whether the right sentences appear in top-20 but not in top-5. If yes → add reranker. If no (right sentences not in top-20 at all) → fix embeddings/indexing, not ranking.

If a reranker IS needed, use a **dedicated cross-encoder** (not LLM):
- **`voyage-rerank-2.5`** (already in our Voyage vendor stack)
- Cohere Rerank v3.5
- Jina Reranker v2
- BGE Reranker (open source option)

Cross-encoders process (query, passage) jointly — they see word-level interactions that bi-encoders lose when compressing text to a single vector. They're deterministic, calibrated, and cannot hallucinate relevance (no generation step).

---

## Industry Leader Strategies (Validated)

The hybrid skeleton approach aligns with several published strategies from industry leaders:

### 1. Anthropic: Contextual Retrieval (2024)

Anthropic's approach prepends document-level context to each chunk before embedding, improving retrieval by 49%. Our approach takes this further:
- We use `voyage-context-3`'s native `contextualized_embed()` instead of manual prepending
- We apply it at sentence level instead of chunk level
- The "unified node" pattern means context is carried as metadata, not as text prefix

### 2. LlamaIndex/Microsoft GraphRAG: Parent-Child Pattern

LlamaIndex's `SentenceWindowNodeParser` and Microsoft GraphRAG both implement the "small-to-big" pattern: embed smaller units, retrieve larger parent units. Our approach:
- Embeds sentences (small), returns paragraphs (big) — same pattern
- Adds the graph structure layer that neither LlamaIndex nor vanilla GraphRAG has
- Uses NEXT/PREV/PART_OF edges for structural navigation that pure vector search can't provide

### 3. Jina AI: Late Chunking

Jina's late chunking passes the full document through the model before chunking, preserving cross-sentence dependencies in embeddings. Voyage-context-3 achieves a similar effect:
- `contextualized_embed()` takes both the sentence AND its document context
- The embedding already encodes inter-sentence dependencies
- No need for post-hoc late-chunking pass

### 4. HippoRAG: Personalized PageRank on Knowledge Graphs

Already implemented in Route 3 of this system. The hybrid skeleton approach complements it:
- PPR operates on entity → chunk → section level (coarse)
- Sentence-level retrieval operates on sentence → paragraph level (fine)
- Together: coarse-grained discovery (PPR) + fine-grained precision (sentence search)

### 5. ColBERT/ColPali: Multi-Vector Retrieval

While we don't use ColBERT directly, the insight is the same: representing documents as **sets of vectors** (one per token/sentence) instead of one vector per chunk. Our approach:
- One vector per sentence (not per token — more practical at scale)
- Graph structure provides the "interaction" that ColBERT does via late interaction
- More interpretable: we can explain why a sentence was retrieved (edge path)

---

## Risk Analysis

| Risk | Mitigation |
|---|---|
| Sentence extraction noise (40% from DI) | Filtering pipeline: min chars, min words, form label regex, confidence threshold |
| Graph explosion (350 sentences × k=2 = 700 new edges) | High threshold (0.90), cross-chunk only, max k=2 |
| Embedding cost increase (~10× more units) | Acceptable: ~$0.10 for test corpus, ~$175 at 10K docs |
| Retrieval latency increase | Minimal: sentence vector search + 1 hop traversal = <10ms added |
| Backward compatibility | Additive only — existing TextChunk retrieval unchanged |

---

## Decision Points After Phase 0

| If Phase 0 Shows... | Then... |
|---|---|
| ≥5% keyword improvement on table queries | Implement Phase 1-2 (sentence nodes + sparse links) |
| ≥3% improvement on specific-fact queries | Implement Phase 3 (three-stage retrieval) |
| No improvement or degradation | Analyze per-query — may indicate sentence extraction quality issue, not architecture issue |
| RELATED_TO edges = 0 at 0.90 threshold | Lower threshold in 0.05 increments; 0.85 is acceptable minimum |
| Multi-hop queries degrade | Keep chunk-level retrieval for broad queries, sentence-level for precision queries |

---

## Relation to Yesterday's Chunking Strategy Analysis

Yesterday's analysis (`ANALYSIS_CHUNKING_STRATEGY_DEEP_DIVE_2026-02-10.md`) proposed two options:

- **Option 1:** Improve section-based chunking (table row promotion, smaller max_tokens)
- **Option 2:** Sentence-level chunking (new Sentence node type)

The hybrid skeleton approach is **a mature synthesis of both options plus the graph structure layer**:

| Feature | Option 1 | Option 2 | Hybrid Skeleton |
|---|---|---|---|
| Table row embedding | ✅ | ✅ | ✅ |
| Sentence nodes | ❌ | ✅ | ✅ |
| NEXT/PREV edges | ❌ | ❌ | ✅ |
| Paragraph grouping | ❌ | ❌ | ✅ |
| Sparse semantic links | ❌ | ❌ | ✅ |
| Three-stage retrieval | ❌ | partial | ✅ |
| Parent-chunk expansion | ❌ | ✅ | ✅ |

The hybrid approach subsumes both options and adds the graph structure that makes the system self-reinforcing — the more documents indexed, the more cross-references discovered, the better the retrieval becomes.

---

## Known Issues & Future Improvements

### Context Metadata Leakage (Priority: Medium)

**Problem:** When using smaller synthesis models (e.g. `gpt-4.1-mini`), retrieval metadata tags embedded in the context window can leak into the LLM response. Example observed in Q-L6:

```
Agent fee/commission for short-term rentals: 15% of Gross Revenue [paragraph, sim=0.751, doc=...]
```

The `[paragraph, sim=X.XXX, doc=...]` tags are internal retrieval annotations that should never appear in user-facing output.

**Root Cause:** Context assembled in Route 2 includes similarity scores and source metadata inline. gpt-5.1 learns to ignore these; gpt-4.1-mini sometimes copies them verbatim during extraction.

**Fix (Phase 3+):** Strip all retrieval metadata tags from context *before* LLM injection. A simple regex pass (`re.sub(r'\[paragraph,.*?\]', '', context)`) on the assembled context string would eliminate the issue without affecting answer quality.

**Impact:** Cosmetic only — answer accuracy is unaffected. The leaked metadata does reduce F1 slightly because the gold answer doesn't contain those tags.

### Synthesis Model Selection (Resolved)

**Finding:** `gpt-4.1-mini` outperforms `gpt-5.1` on sentence-level extraction tasks (11W/1L/5T, +29% F1, 1.2x faster, ~10x cheaper). When context is precise (answer at rank #1), the reasoning overhead of gpt-5.1 is counterproductive — it sometimes reasons itself into "not stated" when the answer is right there.

**Decision:** `gpt-4.1-mini` is the default `SKELETON_SYNTHESIS_MODEL` for production.

### Reranker Assessment (Resolved — Not Needed)

**Finding:** All 5 previously-flagged "noisy" questions have their answer-bearing sentence at vector search rank #1. The architecture condition for adding a reranker ("answers in top-20 but not top-5") is NOT met. No reranker is needed at this time.

**Revisit:** Only if new documents/queries show ranking degradation (answers dropping below top-5).
