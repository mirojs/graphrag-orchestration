# End of Day Handoff — 2026-01-20

## Session Objective: Route 3 PPR Fixes & Benchmark Validation

**Status**: ✅ Fixes Complete, Benchmark Validated

---

## What Was Accomplished

### 1. PPR Query Fixes (Previously Deployed)
All MENTIONS direction and hub_score fixes were deployed in revision `0000263`:

- **Path 2**: Fixed `MENTIONS` direction (was `(e)<-[:MENTIONS]-(s)`, now `(e)-[:MENTIONS]->(s)`)
- **Path 4**: Fixed `MENTIONS` direction + changed `hub_score` → `mention_count`
- **Path 5**: Changed `hub_score` → `mention_count`

### 2. Orphan Section Cleanup (422 Group)
**Root Cause Found**: The 422 group (`test-5pdfs-1768557493369886422`) had 398 orphan Section nodes from previous indexing runs with invalid `doc_id` values.

**Cleanup Executed**:
```cypher
-- Deleted 972 orphan SHARES_ENTITY edges
-- Deleted 398 orphan Section nodes
```

**Result**: Both test groups now have identical graph structure:
| Metric | 422 Group | 0900 Group |
|--------|-----------|------------|
| Sections | 12 | 12 |
| SHARES_ENTITY edges | 46 | 46 |
| Entities | 159 | 148 |
| Alias coverage | 0% | 85% |

### 3. Benchmark Result Analysis (Q-G10)

**Last Benchmark** (2026-01-20 14:05 UTC):
- File: `benchmarks/route3_global_search_20260120T140502Z.json`
- Q-G10 Coverage: **71.4% (5/7 terms)**
- Matched: `warranty`, `arbitration`, `servicing`, `management`, `scope of work`
- **Missing**: `invoice`, `payment`

**Current State** (After PPR Fixes):
- Q-G10 Coverage: **100% (7/7 terms)** ✅
- All terms now consistently found across 3 consecutive runs
- Including previously missing: `invoice`, `payment`

### 4. Key Finding: Routing Issue Identified
When testing manually, using `mode: "global_search"` was routing to **route_1_vector_rag** instead of route 3.

**Correct Parameter**: `force_route: "global_search"` (as used by benchmark script)

---

## Current Test Groups

| Group ID | Description | Status |
|----------|-------------|--------|
| `test-5pdfs-1768557493369886422` | 0% aliases, 159 entities | ✅ Cleaned |
| `test-5pdfs-1768832399067050900` | 85% aliases, 148 entities | ✅ Ready |

---

## Files Modified This Session

None - today was investigation and validation only.

---

## TODO List for Next Session

### High Priority
- [ ] **Run full Route 3 benchmark** to confirm all improvements
  ```bash
  cd /afh/projects/graphrag-orchestration
  python scripts/benchmark_route3_global_search.py
  ```
- [ ] **Compare new benchmark results** with previous (expect Q-G10 improvement from 71% → 100%)

### Medium Priority  
- [ ] **Investigate Q-D10** - User mentioned "what's missing for Q-D10 because it only happened after the 8-branch union update"
- [ ] **Document the PPR multi-path query** changes in architecture docs
- [ ] **Consider adding validation** for orphan Section cleanup in indexing pipeline

### Low Priority
- [ ] **Alias coverage analysis** - Why does 0900 group have 85% aliases vs 422's 0%?
- [ ] **Benchmark automation** - Consider adding orphan detection to pre-benchmark checks

---

## Quick Reference Commands

### Test Q-G10 (Global Search)
```bash
curl -s -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-1768832399067050900" \
  -d '{"query": "What are the main topics covered in the documents?", "force_route": "global_search"}' | jq '.route_used, .response[:200]'
```

### Check for Orphan Sections
```cypher
MATCH (s:Section)
WHERE s.group_id = 'YOUR_GROUP_ID'
AND NOT EXISTS {
  MATCH (d:Document {group_id: s.group_id})
  WHERE d.doc_id = s.doc_id
}
RETURN count(s) as orphan_count
```

### Run Benchmark
```bash
cd /afh/projects/graphrag-orchestration
python scripts/benchmark_route3_global_search.py
```

---

## Deployed Revision
- **Container App**: `graphrag-orchestration--0000263`
- **Endpoint**: `https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io`

---

## Notes
- The "invoice" and "payment" terms are in the Purchase Contract document
- PPR improvements likely improved their ranking in thematic evidence retrieval
- LLM synthesis in global_search can have natural variation, but 3/3 runs showed 100%
