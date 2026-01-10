# Neo4j Cypher 25 Migration Handover
**Date:** January 10, 2026  
**Status:** Partial Migration Complete (Native Functions Only)

## Executive Summary

We have completed **Phase 1** of the Neo4j upgrade: migrating from GDS functions to native Neo4j 5.x functions. However, we have **NOT** yet adopted Cypher 25 features, which require additional schema and runtime changes.

---

## What Was Completed Today

### ✅ Phase 1: Native Function Migration (DONE)

| Task | Status | Details |
|------|--------|---------|
| Replace `gds.similarity.cosine` with native | ✅ Complete | All query-time vector similarity migrated |
| Verify Neo4j Aura compatibility | ✅ Complete | Probe confirms 5.27-aura with native functions |
| Update architecture documentation | ✅ Complete | Section 14.5 added to ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md |
| Clean up GDS references | ✅ Complete | Updated comments in orchestrator.py |
| Create migration plan document | ✅ Complete | NEO4J_2025_AURA_MIGRATION_PLAN_2026-01-10.md |
| Test semantic beam (experimental) | ✅ Complete | Implemented but not wired (HippoRAG 2 PPR is default) |

### Files Modified

| File | Change | Commit |
|------|--------|--------|
| `app/v3/services/neo4j_store.py` | GDS → native vector similarity | `640bc25` |
| `app/hybrid/services/neo4j_store.py` | GDS → native vector similarity | `640bc25` |
| `app/hybrid/pipeline/enhanced_graph_retriever.py` | GDS → native vector similarity | `640bc25` |
| `scripts/neo4j_capability_probe.py` | Created capability probe | `640bc25` |
| `app/services/async_neo4j_service.py` | Added semantic_multihop_beam (experimental) | `61824aa` |
| `app/hybrid/pipeline/tracing.py` | Added trace_semantic_beam (experimental) | `61824aa` |
| `NEO4J_2025_AURA_MIGRATION_PLAN_2026-01-10.md` | Migration plan + appendix | `a637782`, `0be8c02` |
| `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` | Section 14.5: Native vector migration | `3c95c6b` |
| `app/hybrid/orchestrator.py` | Updated GDS comments | `3c95c6b` |

### Git Commits Pushed

```
3c95c6b - Docs: record native vector migration in architecture (Section 14.5)
0be8c02 - Docs: record semantic beam as experimental (keep HippoRAG 2 PPR default)
61824aa - Route 4: add semantic-guided multi-hop beam search (vector pruning)
a637782 - Docs: Neo4j Aura 2025 migration plan
640bc25 - Neo4j: use native vector similarity (drop GDS cosine)
```

---

## Current Architecture State

### Query-Time (Native Functions) ✅
- **Vector Similarity:** Using `vector.similarity.cosine()` (native)
- **Vector Index Queries:** Using `db.index.vector.queryNodes()` (native)
- **Fulltext Search:** Using `db.index.fulltext.queryNodes()` (native)
- **All Routes:** Fully operational with native functions

### Index-Time (Still Using GDS) ⚠️
- **Community Detection:** `gds.leiden.write()`, `gds.louvain.write()` (in `graph_service.py`)
- **Graph Projection:** `gds.graph.project.cypher()` (required for communities)
- **Why:** Neo4j has no native community detection; Aura Professional includes GDS for this

### Cypher Runtime ⚠️
- **Current:** Queries default to **Cypher 5** runtime
- **Not Using:** Cypher 25 features (dynamic labels, MergeUniqueNode, native VECTOR type)

---

## What's NOT Done Yet: Full Cypher 25 Adoption

### Phase 2 Tasks (NOT STARTED)

#### 1. Enable Cypher 25 Runtime
**Impact:** Required to access Cypher 25 optimizations

- [ ] Add `CYPHER 25` prefix to all Cypher queries OR
- [ ] Set database default: `CALL dbms.setDefaultRuntime('cypher-25')`
- [ ] Test all routes with Cypher 25 runtime
- [ ] Benchmark latency differences

**Files to Update:**
- `app/services/graph_service.py` (all Cypher queries)
- `app/hybrid/orchestrator.py` (vector/fulltext searches)
- `app/hybrid/services/neo4j_store.py` (all queries)
- `app/v3/services/neo4j_store.py` (all queries)
- `app/services/async_neo4j_service.py` (all queries)

#### 2. Migrate to Native VECTOR Type
**Impact:** Performance improvement for vector operations

**Current State:**
```cypher
CREATE VECTOR INDEX chunk_embedding
FOR (t:TextChunk) ON (t.embedding)  -- t.embedding is LIST<FLOAT>
```

**Target State:**
```cypher
CREATE VECTOR INDEX chunk_embedding
FOR (t:TextChunk) ON (t.embedding::VECTOR<FLOAT>)
```

**Migration Steps:**
- [ ] Add schema migration script to convert `LIST<FLOAT>` → `VECTOR<FLOAT>`
- [ ] Update all embedding upsert operations to use VECTOR type
- [ ] Drop old vector indexes
- [ ] Recreate indexes with VECTOR type
- [ ] Update application code to handle VECTOR type

**Files to Update:**
- `app/services/graph_service.py` (`_initialize_vector_indices()`)
- `app/hybrid/services/neo4j_store.py` (index creation)
- `app/v3/services/neo4j_store.py` (index creation)
- All embedding upsert queries

#### 3. Add Uniqueness Constraints for MERGE Optimization
**Impact:** Leverages MergeUniqueNode operator for faster writes

**Current State:** MERGE operations without constraints (slower)

**Target State:**
```cypher
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (e:Entity) REQUIRE e.id IS UNIQUE;

CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (c:TextChunk) REQUIRE c.id IS UNIQUE;

CREATE CONSTRAINT document_id_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.id IS UNIQUE;
```

**Files to Update:**
- [ ] `app/services/graph_service.py` (add constraint creation method)
- [ ] Schema initialization scripts
- [ ] Test MERGE performance before/after

#### 4. Leverage Dynamic Label Indexing
**Impact:** Use indexes for runtime-determined labels

**Current State:** Static labels in all MATCH clauses

**Potential Use Cases:**
- Multi-tenant filtering by dynamic entity types
- Parameterized label matching

**Example:**
```cypher
CYPHER 25
MATCH (n:$(labelParam) {id: $id})  -- Can now use index
RETURN n
```

**Decision Needed:** Evaluate if dynamic labels would benefit our use cases

#### 5. Update Index Provider Syntax
**Impact:** Ensure using latest index syntax (future-proof)

**Current State:** Using older VECTOR INDEX syntax

**Target State:** Verify we're on latest Neo4j 2025.x index syntax (may require no changes)

---

## Testing & Validation TODO

### Before Cypher 25 Migration
- [ ] Run full benchmark suite on current setup (establish baseline)
- [ ] Capture query plans for all routes: `EXPLAIN` / `PROFILE`
- [ ] Document current latency metrics per route

### After Cypher 25 Migration
- [ ] Re-run benchmark suite
- [ ] Compare query plans (look for MergeUniqueNode, index-backed dynamic labels)
- [ ] Measure latency improvements
- [ ] Validate result correctness (no regressions)

---

## Decision Points for Next Session

### 1. Should We Proceed with Full Cypher 25 Migration?
**Pros:**
- Access to performance optimizations (MergeUniqueNode, dynamic labels)
- Native VECTOR type for better vector operations
- Future-proof for Neo4j 2025.x features

**Cons:**
- Schema migration required (downtime or live migration complexity)
- Testing effort for all routes
- Risk of breaking changes

**Recommendation:** YES, but staged:
1. **Stage 1:** Enable Cypher 25 runtime (low risk, reversible)
2. **Stage 2:** Add uniqueness constraints (low risk, high reward)
3. **Stage 3:** Migrate to VECTOR type (requires schema migration, plan carefully)

### 2. When to Migrate?
**Options:**
- **Now (Jan 10):** Full migration while fresh in memory
- **After benchmarking:** Establish baseline, then migrate
- **Incremental:** Enable Cypher 25 runtime only, defer VECTOR type

**Recommendation:** Start with Stage 1 (runtime) + Stage 2 (constraints) tomorrow. Defer VECTOR type migration until we have benchmarks.

---

## Resources & References

### Documentation Created
1. **NEO4J_2025_AURA_MIGRATION_PLAN_2026-01-10.md** — Original migration plan
2. **ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md (Section 14.5)** — Native vector migration details
3. **scripts/neo4j_capability_probe.py** — Reusable probe for Neo4j version/capabilities

### Neo4j Version Confirmed
```
Neo4j Version: 5.27-aura (Aura Professional)
Edition: enterprise
Functions Available:
  ✅ vector.similarity.cosine
  ✅ vector.similarity.euclidean
  ✅ db.index.vector.queryNodes
  ✅ db.index.fulltext.queryNodes
```

### Key Neo4j Documentation
- Cypher 25 Features: https://neo4j.com/docs/cypher-manual/current/introduction/cypher_25/
- Native VECTOR Type: https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- MergeUniqueNode: Neo4j 2025 release notes
- Dynamic Label Indexing: Cypher 25 query planner improvements

---

## Next Steps (Prioritized)

### High Priority (Start Tomorrow)
1. **Enable Cypher 25 Runtime**
   - Add `CYPHER 25` to critical query paths
   - Test Route 1, Route 3 with Cypher 25
   - Measure latency differences

2. **Add Uniqueness Constraints**
   - Create constraints for Entity.id, TextChunk.id, Document.id
   - Test MERGE performance improvements
   - Verify no duplicate key violations

3. **Run Baseline Benchmarks**
   - Capture current Route 3 performance (positive + negative tests)
   - Document query plans with `PROFILE`

### Medium Priority (This Week)
4. **Plan VECTOR Type Migration**
   - Write schema migration script
   - Test on dev/staging environment
   - Plan production migration strategy (live vs maintenance window)

5. **Update All Queries for Cypher 25**
   - Systematically update all Cypher queries across codebase
   - Add regression tests

### Low Priority (Future)
6. **Evaluate Dynamic Label Indexing**
   - Identify use cases (if any)
   - Prototype and benchmark

7. **Explore Cypher 25 Path Features**
   - REPEATABLE ELEMENTS for path traversal
   - Evaluate if applicable to HippoRAG 2 PPR

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Cypher 25 runtime breaks queries | High | Test incrementally, easy rollback via query prefix |
| VECTOR type migration causes downtime | Medium | Live migration script OR maintenance window |
| Uniqueness constraints cause insert failures | Medium | Validate no duplicates exist before creating constraints |
| Performance regression | Low | Benchmark before/after, revert if needed |

---

## Contact & Continuity

**Work Completed By:** GitHub Copilot (Claude Sonnet 4.5)  
**Date:** January 10, 2026  
**Repository:** https://github.com/mirojs/graphrag-orchestration  
**Branch:** main  
**Last Commit:** `3c95c6b`

**To Resume:**
1. Review this handover document
2. Run capability probe to confirm Aura state: `python scripts/neo4j_capability_probe.py`
3. Decide on Stage 1 (Cypher 25 runtime) vs full migration
4. Follow "Next Steps" section above

---

## Appendix: Command Reference

### Run Capability Probe
```bash
cd /afh/projects/graphrag-orchestration
source .venv/bin/activate
python scripts/neo4j_capability_probe.py
```

### Check Current Schema
```bash
# Neo4j Browser or cypher-shell:
CALL db.indexes() YIELD name, type, labelsOrTypes, properties;
CALL db.constraints();
```

### Test Query with Cypher 25
```cypher
CYPHER 25
MATCH (n:TextChunk {id: "test"})
RETURN n;
```

### Profile Query Performance
```cypher
PROFILE
MATCH (n:TextChunk)
WHERE n.group_id = "test"
RETURN n
LIMIT 10;
```
