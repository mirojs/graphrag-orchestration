# Route 3 (Global Search) Fast Mode Implementation

**Date:** January 24, 2026  
**Status:** Implementation  
**Branch:** main

---

## Summary

Implement `ROUTE3_FAST_MODE` toggle in `orchestrator.py` that skips redundant "boost" stages and makes PPR optional, reducing Route 3 latency by ~40-50% while preserving entity-based retrieval quality.

---

## Implementation Steps

### Step 1: Add Fast Mode Flag (~L2603)

At the start of `_execute_route_3_global_search()`, read the environment variable:

```python
fast_mode = os.getenv("ROUTE3_FAST_MODE", "1").strip().lower() in {"1", "true", "yes"}
logger.info("route3_fast_mode", fast_mode=fast_mode, profile=self.profile)
```

**Default:** `"1"` (enabled) for General Enterprise performance.

---

### Step 2: Skip Section Boost (~L2838)

Wrap the Section Boost block:

```python
if not fast_mode:
    # Section Boost logic here
    logger.info("stage_section_boost_start")
    ...
else:
    logger.info("stage_section_boost_skipped", reason="fast_mode")
```

---

### Step 3: Skip Keyword Boost (~L3105)

Wrap the Keyword Boost block:

```python
if not fast_mode:
    # Keyword Boost logic here
    logger.info("stage_keyword_boost_start")
    ...
else:
    logger.info("stage_keyword_boost_skipped", reason="fast_mode")
```

---

### Step 4: Skip Doc Lead Boost (~L3217)

Wrap the Doc Lead Boost block:

```python
if not fast_mode:
    # Doc Lead Boost logic here
    logger.info("stage_doc_lead_boost_start")
    ...
else:
    logger.info("stage_doc_lead_boost_skipped", reason="fast_mode")
```

---

### Step 5: Make PPR Conditional (~L3432)

PPR should be skipped in fast mode UNLESS the query has explicit entity mentions or relationship keywords:

```python
# Determine if PPR is needed
enable_ppr = True
if fast_mode:
    # Check for explicit entities or relationship keywords
    has_entities = self._has_explicit_entity(query)
    has_relationship_keywords = any(kw in query.lower() for kw in [
        "connected", "through", "linked", "related to", 
        "associated with", "path", "chain"
    ])
    enable_ppr = has_entities or has_relationship_keywords
    
    if not enable_ppr:
        logger.info("stage_ppr_skipped", reason="fast_mode_no_entities")

if enable_ppr:
    # Run PPR logic
    ...
```

---

### Step 6: Add KVP Fast-Path (Optional Enhancement)

At the very start of Route 3, before entity search, check for field-lookup queries:

```python
# KVP Fast-Path for field-lookup queries
if fast_mode and self._is_field_lookup_query(query):
    kvp_result = await self._search_kvp_by_embedding(query)
    if kvp_result and kvp_result.get("confidence", 0) > 0.8:
        logger.info("kvp_fast_path_hit", key=kvp_result.get("key"))
        return self._format_kvp_response(kvp_result, query)
    else:
        logger.info("kvp_fast_path_miss", query=query[:50])
        # Continue with normal pipeline (don't return strict negative on miss)
```

**Helper Method:**
```python
def _is_field_lookup_query(self, query: str) -> bool:
    """Check if query is asking for a specific field value."""
    field_patterns = [
        r"what is the .*(number|amount|date|address|name|id)",
        r"(invoice|policy|contract|registration) (number|#|no\.?)",
        r"(total|sum|balance|amount)",
    ]
    import re
    return any(re.search(p, query.lower()) for p in field_patterns)
```

---

### Step 7: Profile-Based Override

In the router or at Route 3 entry, force `fast_mode=False` for High Assurance:

```python
# High Assurance profile always uses full pipeline
if self.profile == "high_assurance":
    fast_mode = False
    logger.info("fast_mode_disabled", reason="high_assurance_profile")
```

---

## Files to Modify

1. **`graphrag-orchestration/app/hybrid/orchestrator.py`**
   - Add `fast_mode` flag at Route 3 entry
   - Wrap Section Boost, Keyword Boost, Doc Lead Boost in conditionals
   - Make PPR conditional based on query characteristics
   - Add KVP fast-path (optional)

2. **`graphrag-orchestration/app/hybrid/router/main.py`** (optional)
   - Pass profile to orchestrator for profile-based fast_mode override

---

## Testing Plan

1. **Smoke Test:** Run 5 Global Search queries with `ROUTE3_FAST_MODE=1` and verify answers
2. **A/B Comparison:** Run full 41-question benchmark with both modes, compare:
   - Accuracy scores
   - Latency (should be 40-50% faster)
   - Citation quality
3. **Negative Detection:** Verify negative queries still get strict refusals
4. **Edge Cases:** Test relationship queries to ensure PPR is enabled when needed

---

## Rollback Plan

```bash
# Disable fast mode (revert to full pipeline)
export ROUTE3_FAST_MODE=0
```

---

## Expected Outcomes

| Metric | Full Mode | Fast Mode |
|:-------|:----------|:----------|
| Latency | 20-30s | 8-16s |
| Accuracy | 100% | ~98-100% |
| PPR Usage | Always | Conditional |
| Stages | 12 | 5-6 |

---

## Implementation Checklist

- [ ] Add `fast_mode` flag to `_execute_route_3_global_search()`
- [ ] Wrap Section Boost in conditional
- [ ] Wrap Keyword Boost in conditional
- [ ] Wrap Doc Lead Boost in conditional
- [ ] Make PPR conditional with entity/relationship check
- [ ] Add KVP fast-path (optional)
- [ ] Add profile-based override for High Assurance
- [ ] Test with smoke queries
- [ ] Run full benchmark comparison
- [ ] Commit and deploy

---

*Created: January 24, 2026*
