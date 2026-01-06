# Section/Subsection Graph Upgrade Plan (Routes 1/2/3/4)

**Date:** 2026-01-06

## Goal
Make section/subsection structure a first-class Neo4j graph primitive and use it to improve retrieval quality (especially clause-level obligations and numeric limits) across **all routes (1/2/3/4)**.

This plan assumes we are in a development stage with a small corpus (5 PDFs) and can re-index freely.

---

## Why this change (problem statement)
We have repeated evidence that the information exists in TextChunks, but **Stage 3.3 evidence selection** often fails to surface the right clause chunks. Today, `section_path` is treated as metadata, not as a traversal/scoring primitive.

Making sections explicit graph nodes enables:
- reliable **section-aware diversification** (avoid over-sampling one area)
- **graph-native routing** from query signals → entities → sections → chunks
- consistent behavior across routes (vector, local, global, drift)

---

## Current pipeline (reference)
### Route 3 (Global Search)
- Stage 3.1: Community matching
- Stage 3.2: Hub extraction
- Stage 3.3: Graph context retrieval
  - MENTIONS-derived chunks for hub entities
  - RELATED_TO relationships for entity context
  - `section_path` passed through but not used for retrieval selection
- Stage 3.4: PPR tracing
- Stage 3.5: Synthesis over `graph_context.source_chunks`

### Routes 1/2/4 (high-level)
- Route 1: Neo4j-native vector + fulltext + RRF retrieval of chunks
- Route 2: entity-driven graph traversal + synthesis
- Route 4: decomposition + entity discovery + tracing + synthesis

---

## Proposed data model (Section Graph)
### New nodes
- `(:Document)` (or reuse existing doc identity if already present)
- `(:Section {id, group_id, doc_id, path_key, title, depth})`
  - `id` = hash-based stable identifier: `section_{sha256(group_id + doc_id + path_key)[:12]}`
  - `path_key` = display identifier derived from full section path (e.g., joined with ` > `)
  - `title` = leaf section name (last element of path)
  - `depth` = 0-indexed depth in hierarchy

### New relationships
- `(:Document)-[:HAS_SECTION]->(:Section)` (top-level sections only)
- `(:Section)-[:SUBSECTION_OF]->(:Section)` (child → parent direction)
- `(:TextChunk)-[:IN_SECTION]->(:Section)` (chunk linked to its leaf section)

### Fallback for chunks without section metadata
- If a chunk has no `section_path` (e.g., raw-text ingestion), create a synthetic root section:
  - `path_key = "[Document Root]"`
  - `title = "[Document Root]"`
  - `depth = 0`
- This ensures **all chunks have an `IN_SECTION` edge**, enabling consistent diversification logic.

### Notes
- Preserve existing `TextChunk.metadata.section_path` and/or `TextChunk.section_path`, but treat it as source-of-truth for building the Section graph during indexing.
- This model supports both:
  - hierarchical navigation (sections/subsections)
  - fast bucketing for diversification (doc + section bucket)

---

## Indexing / Re-indexing plan (5 PDFs)
### Step 0 — Preflight checks
- Confirm Neo4j has:
  - `TextChunk` nodes with `group_id`, `text`, and section metadata
  - entity graph (`Entity`, `MENTIONS`, `RELATED_TO`) intact
  - vector index `chunk_embedding` and fulltext `textchunk_fulltext` healthy

### Step 0.5 — Add Section schema to Neo4j
Add to `Neo4jStoreV3.initialize_schema()` in `neo4j_store.py`:
```cypher
CREATE CONSTRAINT section_id IF NOT EXISTS FOR (s:Section) REQUIRE s.id IS UNIQUE
CREATE INDEX section_group IF NOT EXISTS FOR (s:Section) ON (s.group_id)
CREATE INDEX section_doc IF NOT EXISTS FOR (s:Section) ON (s.doc_id)
```

### Step 1 — Build Section graph during ingest
Update the indexing pipeline so that for every TextChunk:
1. parse section path into a list of section titles
2. create/find `Document` node for the chunk
3. create/find `Section` nodes for each depth
4. create `SUBSECTION_OF` edges for parent-child
5. connect chunk → leaf section via `IN_SECTION`

#### Exact repo pointers (where section metadata exists today)

**Hybrid indexing entrypoint (recommended for the current architecture)**
- API endpoint: `POST /hybrid/index/documents` in `graphrag-orchestration/app/routers/hybrid.py`
- Router → background job → pipeline wiring:
  - `hybrid_index_documents()` starts `_run_indexing_job()`
  - `_run_indexing_job()` calls `get_lazygraphrag_indexing_pipeline()`
  - pipeline method: `LazyGraphRAGIndexingPipeline.index_documents()`

**Where `section_path` is attached to chunks (Hybrid pipeline)**
- Chunking is implemented in `graphrag-orchestration/app/hybrid/indexing/lazygraphrag_pipeline.py`.
- If ingestion is Document Intelligence, `_chunk_di_units()` copies DI fields into `TextChunk.metadata` including:
  - `section_path` (preferred)
  - `di_section_path` / `di_section_part`
  - `page_number`
- If ingestion is `none` (raw text), `_chunk_document()` currently does *not* generate section metadata.

**Where chunk metadata is stored in Neo4j**
- Storage is implemented by `Neo4jStoreV3.upsert_text_chunks_batch()` in `graphrag-orchestration/app/hybrid/services/neo4j_store.py`.
- Important constraint: `TextChunk.metadata` is persisted as a JSON string property (`t.metadata`), not a Neo4j map.
  - This is why a pure-Cypher backfill is awkward unless APOC JSON helpers are available.

**V3 indexing entrypoint (for parity / future convergence)**
- API endpoint: `POST /graphrag/v3/index/documents` in `graphrag-orchestration/app/v3/routers/graphrag_v3.py`
- Implementation: `GraphRAGIndexingPipeline.index_documents()` in `graphrag-orchestration/app/v3/services/indexing_pipeline.py`
- V3 DI chunking path: `_chunk_di_extracted_docs()` preserves `section_path`, `di_section_path`, `di_section_part` into `TextChunk.metadata`.

### Step 2 — Backfill Section graph for existing groups
Because corpus is small, backfill can be done in one of two ways:

**Option A (recommended): Python backfill script (no APOC dependency)**
- Add a script (e.g., `scripts/backfill_section_graph.py`) that:
  1. reads `(:TextChunk {group_id})` and joins to its `(:Document)` via `(:TextChunk)-[:PART_OF]->(:Document)`
  2. parses `t.metadata` JSON to extract:
     - `section_path` (preferred; list of strings)
     - fallback: `di_section_path` (string) or `di_section_part`
  3. normalizes the path into a stable `path_key` (e.g., `" > ".join(section_path)`)
  4. creates:
     - `(:Section {group_id, doc_id, path_key, title, depth})`
     - `(:Document)-[:HAS_SECTION]->(:Section)`
     - `(:Section)-[:SUBSECTION_OF]->(:Section)` parent chain
     - `(:TextChunk)-[:IN_SECTION]->(:Section)` (leaf only)

**Option B: Cypher backfill (only if APOC JSON parsing is available)**
- If Neo4j has APOC, you can parse `t.metadata` in Cypher via `apoc.convert.fromJsonMap(t.metadata)`.
- This is simpler to operate (one query), but it adds an operational dependency.

**Optional small schema tweak to make Cypher backfill easy**
- If we want backfills and section-aware retrieval to be Cypher-native without APOC, update `upsert_text_chunks_batch()` to also set:
  - `t.section_path = <list>` when present in metadata.
  - Keep `t.metadata` as JSON string for backwards compatibility.

### Step 3 — Re-index
Given development-stage constraints, we can choose the simplest reliable method:
- wipe the group and re-import, OR
- keep the group and run a deterministic backfill

---

## Retrieval improvements by route

### Route 1 (Vector RAG)
**Problem:** vector/fulltext returns top chunks, but they can cluster in one section.

**Change:** section-aware post-filter/diversification
- After RRF ranking, select top-K with caps:
  - `max_per_document`
  - `max_per_section`
- Prefer covering distinct leaf sections when scores are close.

**Expected benefit:** fewer misses for “threshold/limit/obligation” queries that reside in specific clause sections.

---

### Route 2 (Local Search)
**Problem:** entity neighborhoods can be broad; citations may not include the best clause subsection.

**Change:** entity → section expansion
- After seed entities are found:
  - expand to related entities (existing)
  - then expand to sections where those entities are mentioned:
    - entity ←MENTIONS— chunk —IN_SECTION→ section
- Select chunks by section diversity.

**Expected benefit:** more reliable clause discovery while keeping citations grounded.

---

### Route 3 (Global Search)
**Problem:** Stage 3.3 chunk recall/selection is the bottleneck.

**Change (core):** Stage 3.3 becomes section-aware and graph-aware
- Candidate generation:
  - MENTIONS chunks from hubs
  - MENTIONS chunks from 1-hop related entities (bounded)
  - (optional) hybrid candidate chunks (vector/fulltext) for the query
- Selection:
  - diversify across leaf sections and documents
  - cap total chunks budget

**Expected benefit:** significant improvement in thematic completeness (esp. obligations/numbers).

---

### Route 4 (DRIFT)
**Problem:** sub-questions often pull overlapping evidence; final synthesis misses coverage.

**Change:** section-aware evidence merging
- For each sub-question:
  - select per-section evidence
- When consolidating:
  - union and re-diversify across sections

**Expected benefit:** better breadth across multiple agreements/clauses.

---

## Measurement plan (quality + latency)

### Baseline capture (before changes)
Run:
- Route 3 benchmark (positives + negatives)
- Route 1 question bank smoke
- A small Route 2 and Route 4 smoke suite (existing integration tests)

Record:
- latency distribution (p50/p90) per route
- theme coverage for Route 3 Q-G questions
- negative pass rate for Q-N questions
- evidence stats per query:
  - num_chunks
  - per-document distribution
  - per-section distribution (will be `unknown` until section graph is built)

### After Step 1/2 (Section graph exists, no retrieval changes yet)
- Validate section graph correctness via `scripts/validate_section_graph.py`:
  - `% chunks with IN_SECTION edge` (target: 100%)
  - `orphan chunks count` (target: 0)
  - `sections per doc` (sanity check: typically 5–30 for legal PDFs)
  - `max depth` (sanity check: typically 1–4)
  - `sample traversal`: entity → chunk → section → document (spot check 3–5 entities)

### After retrieval changes (A/B)
Introduce flags to compare behavior quickly:
- `SECTION_GRAPH_ENABLED=0/1`
- `SECTION_DIVERSIFY_MAX_PER_SECTION=<int>`
- `SECTION_DIVERSIFY_MAX_PER_DOC=<int>`
- (optional) `ROUTE3_HYBRID_CANDIDATES=0/1`

Run A/B on the same group id:
- A: section graph off
- B: section graph on + diversification

### Primary success metrics
- Route 3 theme coverage:
  - target: improve weakest Q-G questions by +2 terms on average, while keeping best ones stable
- Route 3 evidence recall:
  - target: higher section diversity (more distinct leaf sections) without inflating total chunks
- Negative behavior:
  - do not worsen false positives (negative queries returning answers)

### Secondary success metrics
- Latency:
  - target: keep p50 within +10–20% vs baseline OR offset by reducing chunk budget once recall improves

---

## Implementation phases (concrete)

### Phase A — Data model + backfill (1–2 days)
1. Define Section schema and Cypher backfill
2. Add section graph creation to indexing pipeline
3. Re-index 5 PDFs (fresh group id)
4. Add quick validation script (counts + spot checks)

### Phase B — Route updates (2–4 days)
1. Route 3 Stage 3.3: section-aware candidate selection
2. Route 1: post-retrieval section diversification
3. Route 2: entity→section expansion path
4. Route 4: section-aware evidence merging

### Phase C — Tune + simplify (1–2 days)
1. Tune caps (per-doc, per-section, total chunks)
2. Turn off emergency heuristics that become redundant
3. Re-run full benchmark suite

---

## Risks / mitigations
- **Risk:** too many sections → retrieval becomes noisy
  - **Mitigation:** use leaf sections only; apply strict budgets
- **Risk:** indexing/backfill bugs create incorrect edges
  - **Mitigation:** validate with deterministic checks and sample queries
- **Risk:** latency increases due to extra traversal
  - **Mitigation:** cap candidates and reuse Neo4j indexes; reduce synthesis context size
- **Risk:** section graph causes quality regressions
  - **Mitigation:** rollback plan:
    1. Set `SECTION_GRAPH_ENABLED=0` in deployment
    2. (Optional) Clean up: `MATCH (s:Section) DETACH DELETE s`
    3. Routes fall back to current behavior (no section diversification)

---

## Deliverables
- Section graph schema + backfill script
- Updated indexing to create Section nodes/edges
- Retrieval updates in Routes 1/2/3/4
- Measurement runs and comparison report (baseline vs A/B)
