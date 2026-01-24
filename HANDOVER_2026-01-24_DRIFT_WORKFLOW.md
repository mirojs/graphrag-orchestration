# DRIFT Workflow Migration Handover - 2026-01-24

## Summary

Implementing **LlamaIndex Workflow** for Route 4 DRIFT to parallelize sub-question processing. Target: ~700ms for 3 sub-questions (vs ~2.1s sequential).

## Current Status: 🟡 Deployed but Citation Bug

The workflow is deployed with `ROUTE4_WORKFLOW=1` but there's a **citation format mismatch** causing HTTP 500 errors on most Route 4 queries.

### What's Working
- ✅ Workflow files created and imports work
- ✅ `ctx.store.set/get` API updated for llama-index-core 0.14.12
- ✅ Parallel sub-question processing confirmed in logs (~400ms each, running concurrently)
- ✅ Feature flag `ROUTE4_WORKFLOW=1` enables workflow mode
- ✅ Date metadata queries (Q-D5, Q-D7) work fast (~200ms deterministic path)
- ✅ Negative tests (Q-N1, Q-N2, Q-N5, Q-N6, Q-N9, Q-N10) pass

### What's Broken
- ❌ Most Route 4 queries get HTTP 500 due to Citation format mismatch
- Error: `Citation.__init__() got an unexpected keyword argument 'citation'`

## Root Cause Analysis

The synthesizer (`app/hybrid/pipeline/synthesis.py`) returns citations with keys:
```python
{
    "citation": "[1]",      # Wrong - should be "index": 1
    "source": "...",        # Wrong - should be "document_id"
    "document": "...",      # Wrong - should be "document_title"
    "chunk_id": "...",      # Correct
    "text_preview": "..."   # Correct
}
```

But `Citation` class (`app/hybrid/routes/base.py`) expects:
```python
@dataclass
class Citation:
    index: int
    chunk_id: str
    document_id: str
    document_title: str
    score: float
    text_preview: str
```

## Fix Applied (Needs Testing)

**File:** `app/hybrid/routes/route_4_drift.py` (lines 90-117)

Changed from:
```python
citations=[Citation(**c) for c in result.get("citations", [])]
```

To:
```python
citations = []
for i, c in enumerate(result.get("citations", [])):
    citations.append(Citation(
        index=c.get("index", i + 1),
        chunk_id=c.get("chunk_id", ""),
        document_id=c.get("document_id", c.get("source", "")),
        document_title=c.get("document_title", c.get("document", "")),
        score=c.get("score", 0.0),
        text_preview=c.get("text_preview", ""),
    ))
```

**Last deployment:** `main-5b0eba3-20260124151823` (includes this fix)

---

## TODO List for Tomorrow

### 1. 🔴 Verify Citation Fix Works
```bash
cd /afh/projects/graphrag-orchestration
python scripts/benchmark_route4_drift_multi_hop.py --repeats 3
```
Expected: All Q-D* questions should return 200 with valid responses.

### 2. 🟡 If Still Failing - Check Logs
```bash
az containerapp logs show -n graphrag-orchestration -g rg-graphrag-feature --tail 100 | grep "hybrid_query_failed\|error"
```

### 3. 🟢 If Working - Run Full Benchmark Suite
```bash
# Route 4 only
python scripts/benchmark_route4_drift_multi_hop.py --repeats 3 | tee bench_route4_workflow_final.txt

# All routes (optional)
python scripts/benchmark_all4_routes_posneg_qbank.py --repeats 3
```

### 4. 🟢 Compare Performance
Look at timing in metadata:
- `workflow: true` should show faster sub-question processing
- Check `stage_4.2_ms` timing (parallel should be ~400-600ms vs ~1200-1800ms sequential)

### 5. 🟢 Commit Changes
```bash
git add .
git commit -m "feat(route4): LlamaIndex Workflow for parallel DRIFT sub-questions

- Add workflows/ package with DRIFTWorkflow class
- Use ctx.store.set/get API (llama-index-core 0.14.12)
- Enable with ROUTE4_WORKFLOW=1 env var
- Fix citation format mapping for workflow mode
- Parallel processing: ~700ms vs ~2.1s sequential"
git push
```

---

## Key Files Modified

| File | Changes |
|------|---------|
| `app/hybrid/workflows/__init__.py` | NEW - Package exports |
| `app/hybrid/workflows/events.py` | NEW - Event classes (Pydantic, NOT dataclass) |
| `app/hybrid/workflows/drift_workflow.py` | NEW - Main workflow with 7 steps |
| `app/hybrid/routes/route_4_drift.py` | Modified - Workflow integration + citation fix |
| `requirements.txt` | Updated - llama-index-core==0.14.12, added lancedb |
| `deploy-graphrag.sh` | Already has ROUTE4_WORKFLOW support |

## Environment Variables

```bash
export ROUTE4_WORKFLOW=1  # Enable parallel workflow (default: 0)
```

Set in `deploy-graphrag.sh` before deployment.

---

## API Differences: llama-index-core Versions

| Feature | 0.12.x | 0.14.x |
|---------|--------|--------|
| Context state | `await ctx.set()` / `await ctx.get()` | `await ctx.store.set()` / `await ctx.store.get()` |
| Events | Pydantic models | Pydantic models |
| Fan-out | `ctx.send_event()` + `return None` | Same |
| Parallel | `@step(num_workers=4)` | Same |

**Current:** Using 0.14.x API (`ctx.store.set/get`)

---

## Production Endpoint

```
https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io
```

Test command:
```bash
curl -s -X POST "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/hybrid/query" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-5pdfs-1769071711867955961" \
  -d '{"query": "Compare payment terms across all agreements"}' | python -m json.tool
```

---

## Benchmark Results (Pre-Fix)

From `bench_route4_workflow_parallel_20260124_152400.txt`:
- Date metadata queries (Q-D5, Q-D7): **~200ms** ✅ (deterministic fast path)
- Negative tests: **4-8 seconds** ✅ (expected, uses Route 2 fallback)
- Complex queries (Q-D1-D4, Q-D6, Q-D8-D10): **HTTP 500** ❌ (citation bug)

---

## Session Notes

1. **LlamaIndex Workflows docs:** https://developers.llamaindex.ai/python/llamaagents/workflows/
2. **Key pattern:** Use `ctx.send_event()` in loop + `return None` for fan-out
3. **Events must NOT use @dataclass** - they're Pydantic models inheriting from `Event`
4. **llama-index-packs-raptor removed** - was causing version conflicts, not used
5. **llama-index-vector-stores-lancedb** upgraded to 0.4.4 for 0.14.x compatibility
