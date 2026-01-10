# Neo4j (Aura) 2025 / Cypher 25 Migration Plan (2026-01-10)

This document covers a safe, staged approach to upgrading Neo4j **Aura Professional** to the Neo4j 2025.x / “Cypher 25” line, with special attention to GraphRAG (Routes 1–4), vector capabilities, and library compatibility.

## Current validated baseline (this repo)

- Aura version probe result: **Neo4j 5.27-aura (enterprise)**
- Native vector functions confirmed:
  - `vector.similarity.cosine` ✅
  - `vector.similarity.euclidean` ✅
- Vector/fulltext procedures confirmed:
  - `db.index.vector.queryNodes` ✅
  - `db.index.fulltext.queryNodes` ✅
- Code change: query-time similarity moved from `gds.similarity.cosine` to `vector.similarity.cosine`.

Probe script:
- [graphrag-orchestration/scripts/neo4j_capability_probe.py](graphrag-orchestration/scripts/neo4j_capability_probe.py)

## Goals

**Performance**
- Reduce p95/p99 latency for graph-heavy routes (Route 3 global search + Route 4 multi-hop).
- Reduce operational dependency on Neo4j GDS plugin for query-time similarity.

**Accuracy**
- Enable semantic-guided multi-hop pruning (beam-style expansion) using native `vector.*` functions.
- Improve “evidence quality per token” by retrieving fewer but more relevant multi-hop candidates.

## Compatibility matrix (key pins)

These are the versions currently pinned/used by this repo:
- Neo4j Python driver: `neo4j>=5.15.0` (requirements)
- Neo4j GraphRAG: `neo4j-graphrag==1.7.0` (requirements)
- LlamaIndex Neo4j store: `llama-index-graph-stores-neo4j==0.4.1`

Upstream guardrails (neo4j/neo4j-graphrag-python, high level):
- Enforces minimum Neo4j versions (Aura vs self-host).
- Parses Aura and CalVer strings (e.g., `2025.01-aura`).

**Recommendation**
- Keep the Aura upgrade and the client dependency upgrades as separate steps.
- If Aura moves to a `2025.xx-aura` version string, validate `neo4j-graphrag` compatibility first (its version parsing supports CalVer in newer releases).

## Staged rollout plan

### Stage 0 — Preconditions (today)

- Confirm current Aura version and capabilities via probe:
  - `python3 graphrag-orchestration/scripts/neo4j_capability_probe.py`
- Ensure vector similarity usage is native (`vector.similarity.cosine`).
- Ensure vector indexes exist and are healthy:
  - Entity index: `entity_embedding`
  - Chunk index: `chunk_embedding` / `chunk_vector` (depending on route)

### Stage 1 — Upgrade Aura (server-only)

- Upgrade Aura instance to the target Neo4j 2025.x track.
- Immediately re-run probe to confirm:
  - `dbms.components()` reports expected 2025.x / aura string
  - `vector.*` functions still present
  - `db.index.vector.*` and `db.index.fulltext.*` procedures present

No app changes should be required at this stage.

### Stage 2 — Verify routes in deployed environment

Run your existing benchmark harnesses against the deployed endpoint:
- Route 1 benchmark suite (latency + accuracy)
- Route 3 benchmark suite (especially negatives/guardrails)
- Route 4 smoke suite (DRIFT/multi-hop) focusing on:
  - timeouts
  - determinism/repeatability
  - evidence grounding

Acceptance criteria (suggested):
- No regressions in refusal precision/recall.
- Latency: Route 3 p95 improves or stays flat; Route 4 p95 improves or stays flat.

### Stage 3 — Optional: client dependency upgrades

Only after Stage 2 is stable:
- Evaluate upgrading:
  - `neo4j` Python driver (if Aura/2025.x recommends it)
  - `neo4j-graphrag` (if you want metadata-filtered vector retrieval features)

Do these in a single PR with a quick rollback option.

### Stage 4 — Multi-hop accuracy work (where the upgrade helps)

This is where the upgrade becomes accuracy-meaningful:
- Implement semantic-guided multi-hop pruning (beam search):
  - At hop $h$, expand candidates, then score using `vector.similarity.cosine(candidate.embedding, $query_embedding)`
  - Keep top-$k$ per hop (or top-$k$ overall) to avoid path explosion
- Prefer *early pruning* to “enumerate all paths then filter”, especially avoiding expensive APOC operations in the hot path.

## Risks and mitigations

### Risk: library version gating / version string parsing
- Symptom: `neo4j-graphrag` rejects the server as unsupported.
- Mitigation:
  - Separate Aura upgrade from client dependency upgrade.
  - If Aura reports `2025.xx-aura`, be ready to bump `neo4j-graphrag` to a version that explicitly supports CalVer (based on upstream release notes).

### Risk: query performance regressions due to planner differences
- Symptom: p95/p99 worsens on complex Cypher.
- Mitigation:
  - Capture `PROFILE` plans pre/post for representative Route 3/4 queries.
  - Keep query shapes stable during the server upgrade stage.

### Risk: path explosion in Route 4 / multi-hop patterns
- Symptom: timeouts, high memory, unstable latency.
- Mitigation:
  - Avoid “generate all variable-length paths then filter”.
  - Use algorithmic retrieval (PPR) or beam-pruned expansion using vectors.

## Rollback plan

- Aura: rollback to previous version (or restore snapshot) per Aura operational process.
- App: no code rollback should be needed for the server-only upgrade.
- If client deps were upgraded, rollback is a single revert PR.

## What’s next

1. Decide the target Aura version track (exact `2025.xx` if known).
2. Run Stage 2 benchmarks and capture p50/p95/p99 for Route 3 and Route 4.
3. Monitor if performance headroom improves.

---

## Appendix: Experimental — Semantic-Guided Multi-Hop (not enabled)

An alternative multi-hop approach was implemented but is **not wired into the default pipeline** to stay faithful to HippoRAG 2's PPR-based architecture.

### What it is

- `AsyncNeo4jService.semantic_multihop_beam(...)` — uses `vector.similarity.cosine` at each hop to prune candidates by query relevance.
- `DeterministicTracer.trace_semantic_beam(...)` — entry point for this alternative approach.

### How it differs from HippoRAG 2 (PPR)

| Aspect | HippoRAG 2 (current default) | Semantic Beam (experimental) |
|--------|------------------------------|------------------------------|
| Guidance signal | Graph topology (random walk) | Query embedding |
| Finds structurally central nodes | Yes | No |
| Stays semantically aligned | Not guaranteed | Yes |
| Theoretical basis | Personalized PageRank | Greedy semantic search |

### When to consider enabling

- If Route 4 benchmarks show evidence quality issues (irrelevant but structurally central nodes)
- If you want tighter semantic alignment at the cost of "discovery" capability
- For comparison A/B testing against PPR

### How to test (if needed later)

Replace in Route 4 orchestration:
```python
# Current (PPR-based, HippoRAG 2 faithful):
ranked = await tracer.trace(query, seed_entities, top_k=15)

# Experimental (semantic beam):
ranked = await tracer.trace_semantic_beam(
    query=query,
    query_embedding=query_embedding,
    seed_entities=seed_entities,
    max_hops=3,
    beam_width=10,
)
```

**Decision (2026-01-10):** Keep as optional/experimental. Default pipeline remains PPR-based per HippoRAG 2 design.
