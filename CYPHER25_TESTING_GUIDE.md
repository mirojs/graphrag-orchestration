# Cypher 25 Migration Testing Guide

**Date:** January 11, 2026  
**Status:** Stage 1 Complete — Ready for Testing

## Quick Start

### 1. Apply Database Migrations

```bash
cd /afh/projects/graphrag-orchestration
source .venv/bin/activate

# Apply uniqueness constraints and test Cypher 25 availability
python scripts/cypher25_migration.py
```

**Expected Output:**
- ✅ Cypher 25 runtime available
- ✅ Uniqueness constraints created for Entity, TextChunk, Document, Node
- ✅ MergeUniqueNode optimizer test passed

---

### 2. Run Baseline Benchmarks

#### Option A: Full Before/After Comparison

```bash
# Capture BEFORE baseline (if needed)
# Set USE_CYPHER_25 = False in async_neo4j_service.py first
python scripts/run_cypher25_baseline_benchmark.py --phase before

# Deploy with Cypher 25 enabled (USE_CYPHER_25 = True is already set)
# Then run AFTER baseline
python scripts/run_cypher25_baseline_benchmark.py --phase after

# Compare results
python scripts/run_cypher25_baseline_benchmark.py --compare \
  benchmarks/cypher25_baseline_before_*.json \
  benchmarks/cypher25_baseline_after_*.json
```

#### Option B: Quick Validation (Production)

Since Cypher 25 is already enabled via `USE_CYPHER_25 = True`:

```bash
# Run current state benchmark
python scripts/run_cypher25_baseline_benchmark.py --phase after
```

---

### 3. Run Full Route Tests

```bash
# Route 3 Global Search (comprehensive)
python scripts/benchmark_route3_global_search.py \
  --url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-cypher25-final-1768129960 \
  --repeats 3

# All 4 Routes (positive + negative)
python scripts/benchmark_all4_routes_posneg_qbank.py \
  --url https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io \
  --group-id test-5pdfs-1767429340223041632
```

---

## What Changed (Stage 1)

### Code Changes

#### `app/services/async_neo4j_service.py`
- Added `USE_CYPHER_25 = True` global toggle
- Added `cypher25_query()` helper function
- Updated 10 hot-path queries to use Cypher 25:
  - Entity retrieval queries
  - Graph traversal queries (PPR, neighbors, relationships)
  - Chunk retrieval via MENTIONS
  - Negative detection queries (field existence, pattern matching)
  - Semantic multi-hop beam search

#### `app/services/graph_service.py`
- Added `_initialize_uniqueness_constraints()` method
- Constraints created on startup:
  - `__Entity__.id` → UNIQUE
  - `TextChunk.id` → UNIQUE
  - `Document.id` → UNIQUE
  - `__Node__.id` → UNIQUE

#### New Scripts
1. **`scripts/cypher25_migration.py`**
   - Tests Cypher 25 runtime availability
   - Creates uniqueness constraints
   - Validates MergeUniqueNode optimizer
   - Provides detailed migration output

2. **`scripts/run_cypher25_baseline_benchmark.py`**
   - Runs Route 3 benchmark
   - Captures latency percentiles (p50, p95, p99)
   - Compares before/after results

---

## Expected Improvements

### MergeUniqueNode Optimizer
- **When:** MERGE operations on `id` properties
- **Benefit:** Bypasses "check then write" overhead
- **Impact:** Faster indexing, faster relationship creation

### Cypher 25 Query Planner
- **Parallel runtime optimizations** for declarative patterns
- **Better index utilization** for parameterized queries
- **Lower CPU overhead** for complex graph traversals

### Baseline Expectations
- **p95 latency:** Should improve or stay flat
- **p99 latency:** Should improve (fewer outliers)
- **Mean latency:** Likely small improvement (5-15%)

---

## Monitoring & Validation

### 1. Check Query Plans (Production)

Connect to Neo4j Browser and run:

```cypher
// Test Cypher 25 runtime
CYPHER 25
RETURN 1 AS test;

// Check MergeUniqueNode optimizer
CYPHER 25
PROFILE
MERGE (t:TextChunk {id: 'test-merge-unique-node'})
SET t.test = true
RETURN t.id;

// Look for "MergeUniqueNode" in the query plan
```

### 2. Monitor Application Logs

Look for:
- `async_neo4j_ppr_native_complete` — PPR query latency
- `semantic_multihop_beam_complete` — Multi-hop beam search latency
- `get_entities_by_importance` — Entity retrieval latency

### 3. Application Health Check

```bash
curl https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/health
```

---

## Rollback Plan

### If Performance Regresses

**Option 1: Disable Cypher 25 Runtime (Instant)**

Edit `app/services/async_neo4j_service.py`:
```python
USE_CYPHER_25: bool = False  # Change to False
```

Redeploy. All queries revert to Cypher 5 runtime immediately.

**Option 2: Drop Uniqueness Constraints (If Needed)**

```cypher
DROP CONSTRAINT entity_id_unique IF EXISTS;
DROP CONSTRAINT chunk_id_unique IF EXISTS;
DROP CONSTRAINT document_id_unique IF EXISTS;
DROP CONSTRAINT node_id_unique IF EXISTS;
```

### If Correctness Issues

1. Check query plans with `EXPLAIN` to debug differences
2. Capture failing queries and test with/without `CYPHER 25` prefix
3. Report to Neo4j if runtime behavior differs unexpectedly

---

## Next Steps (Stage 2)

After Stage 1 is validated:

1. **Conditional Branching:** Evaluate `WHEN...THEN...ELSE` for route selection logic
2. **REPEATABLE ELEMENTS:** Test if Route 4 multi-hop benefits from cyclic paths
3. **MergeInto:** Audit relationship MERGE patterns for optimization

See [NEO4J_CYPHER25_HANDOVER_2026-01-10.md](NEO4J_CYPHER25_HANDOVER_2026-01-10.md) for Stage 2 details.

---

## Troubleshooting

### Issue: "Cypher 25 runtime not available"

**Cause:** Neo4j version < 2025.x or Aura not upgraded

**Solution:**
- Verify Neo4j version: `CALL dbms.components()`
- If < 5.25, Cypher 25 is not available
- Set `USE_CYPHER_25 = False` until upgrade

### Issue: "Constraint already exists" error

**Cause:** Constraints created by hybrid store schema init

**Solution:**
- This is expected and safe
- The `IF NOT EXISTS` clause prevents actual errors
- Script reports "already exists" — this is correct

### Issue: Queries slower after migration

**Cause:** Possible query planner differences

**Solution:**
1. Run baseline comparison to quantify difference
2. Check query plans with `PROFILE` for unexpected operators
3. If regression > 10%, revert `USE_CYPHER_25 = False`
4. Report findings for investigation

---

## Success Criteria

✅ **Stage 1 Complete When:**
- All uniqueness constraints created
- Cypher 25 runtime tested and available
- Baseline benchmarks captured
- No latency regressions (p95 < +10%)
- No correctness regressions (all tests pass)

---

## Contact & Support

**Implementation:** GitHub Copilot (Claude Sonnet 4.5)  
**Date:** January 11, 2026  
**Repository:** graphrag-orchestration  
**Branch:** main

**Reference Documents:**
- [NEO4J_CYPHER25_HANDOVER_2026-01-10.md](NEO4J_CYPHER25_HANDOVER_2026-01-10.md) — Full migration plan
- [NEO4J_2025_AURA_MIGRATION_PLAN_2026-01-10.md](NEO4J_2025_AURA_MIGRATION_PLAN_2026-01-10.md) — Server upgrade plan
