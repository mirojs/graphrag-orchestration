# Sources vs Citations (All 4 Routes) — Discussion Notes (2025-12-31)

Date: 2025-12-31

## Why this note exists
We reviewed what “sources” currently mean in the system, how that differs from user-facing “citations”, and how (especially) page numbers from Azure Document Intelligence (DI) could be associated with results for Route 1 and Route 2. This is captured so we can revisit later and evaluate the full 4-route architecture together.

## Key definitions
- **Source (current API meaning)**: Items returned by retrieval and attached to the response in the `sources` field.
  - The *type/shape* of a source depends on which route produced it.
- **Citation (user-facing meaning)**: Usually implies something like:
  - document title and/or URL
  - optional page number
  - excerpt/snippet (quote) that supports the answer

Important: **More `sources` does not necessarily mean more answer detail**, because some routes return “retrieved entities” (many) while others return “retrieved text chunks” (fewer but more quote-like).

## What we observed in benchmarks
In the benchmark summary, the line:
- `vector: 38.2 chars / 3.0 sources` vs `local: 55.7 chars / 10.0 sources`
means:
- **3.0 sources is the average number of sources per response**, not “3 questions out of 10 had sources”.
- `top_k=10` is a **maximum**; routes can legitimately return fewer than 10.

## Route-by-route: what `sources` represent today
### Route 1 — `vector`
- Sources are **TextChunks** (chunk-level evidence).
- This is closest to “citations” because it is grounded in raw excerpt text.
- Practical output today includes chunk identifiers, scores, and `document_id` (and can include document metadata).

### Route 2 — `local`
- Sources are **Entities** (entity-level evidence).
- Useful for transparency ("which entities did you use"), but **not inherently document/page citations**.

### Route 3 — `global`
- Sources are **Communities** / higher-level summaries.
- Good for portfolio/thematic answers.
- Often not quote-level evidence; citations may be community-summary level unless augmented with chunk evidence.

### Route 4 — `drift`
- DRIFT returns sources aligned to its reasoning steps.
- Can be more explainable, but citation semantics depend on what DRIFT considers a “source” (often derived from stored graph/text-unit structures).

## Are citations possible with the current chunking settings?
Yes, **chunk-level citations are possible**.
- Vector route already retrieves `TextChunk` objects.
- As long as chunks are persisted with document metadata (and optionally page numbers), vector responses can provide citations like:
  - `document_title`, `document_source` (URL), `page_number` (if available), `chunk_index`, `text_preview`.

## Page numbers: how to associate Azure DI output to results
### What DI provides
Azure Document Intelligence extraction can provide page-level metadata (e.g., page number) and, depending on model/output, spans/bounding regions.

### Route 1 (vector) — most direct/clean
Logical association:
- **Store page numbers on TextChunks at indexing time**, then return them in vector `sources`.

Current state (as discussed):
- The indexing pipeline already *captures* `page_number` into chunk metadata when DI metadata is available.
- However, persistence may not yet store `page_number` on the Neo4j `TextChunk` node (so query-time cannot return it unless added).

### Route 2 (local) — needs provenance
Local route returns entities; to attach page numbers, we need a mapping from each entity to the chunk(s)/pages it was extracted from.

Two practical approaches:
1) **Provenance edges (best long-term)**
   - During extraction/indexing, create `(:Entity)-[:MENTIONED_IN]->(:TextChunk)` or store `text_chunk_ids` for each entity.
   - At query time, when returning entity sources, include 1–3 supporting chunk citations (with page numbers).

2) **Post-hoc citations (minimal change)**
   - Keep local route for answer generation.
   - Run a small vector citation pass to fetch supporting chunks and attach them as citations to the response.
   - This avoids immediate changes to entity extraction, but adds an extra retrieval step.

## Why Route 1 often returns fewer sources than Route 2
- Vector sources are chunk hits; the system may only have a few strong chunk matches (or fewer eligible chunks).
- Local sources are entities; there are typically many entities and it commonly fills `top_k=10`.

So “3 sources” does **not** mean missing sources; it typically means fewer, stronger chunk citations.

## Open questions for the future 4-route evaluation
- What exactly should `sources` mean in the product UI?
  - “retrieval items” (entities/communities/chunks), or
  - “citations” (doc/title/url/page/excerpt)?
- Should the API standardize a single citation schema across routes?
  - Option: always return `sources[]` as citations, with route-specific subfields.
  - Option: split into `sources` (retrieval items) and `citations` (doc/page/excerpt).
- For Route 2/3/4, do we want:
  - provenance-based citations (preferred), or
  - post-hoc vector citations (simpler but extra step)?

## Immediate, low-risk next step (if we choose to implement later)
- Persist `page_number` (and any other DI metadata needed) on `TextChunk` nodes in Neo4j.
- Include `page_number`, `document_title`, and `document_source` in Route 1 (vector) `sources` so it produces user-facing citations.

