# DRIFT Debug Logging - Code Changes Summary

## Quick Reference: All Code Changes

This document provides a line-by-line reference of all changes made on 2025-12-28.

## 1. Configuration Settings (`app/core/config.py`)

### Change 1: Added Debug Logging Settings

**Location**: After line 86 (after `V3_DRIFT_DEBUG_FALLBACK` setting)

**Added**:
```python
# DRIFT detailed logging for debugging text unit retrieval, sources, and chunk content
# Enable to trace text unit loading, chunk content, and source extraction
# Note: Can be verbose; use only for specific groups with V3_DRIFT_DEBUG_GROUP_ID
V3_DRIFT_DEBUG_LOGGING: bool = Field(default=False)

# Specific group ID to trace DRIFT processing (only logs for this group when V3_DRIFT_DEBUG_LOGGING=true)
# Example: "drift-ok-1766862426"
V3_DRIFT_DEBUG_GROUP_ID: Optional[str] = Field(default=None)
```

**Why**: These settings allow selective enabling of debug logging for specific groups.

---

## 2. DRIFT Adapter (`app/v3/services/drift_adapter.py`)

### Change 1: Text Unit Scan for Specific Content

**Location**: In `drift_search()` method, after line 479 (after "Loaded X entities..." message)

**Added**:
```python
# Debug logging: Check for "10 business days" in text units
is_debug_group = (
    settings.V3_DRIFT_DEBUG_LOGGING and 
    (settings.V3_DRIFT_DEBUG_GROUP_ID is None or settings.V3_DRIFT_DEBUG_GROUP_ID == group_id)
)
if is_debug_group and text_units:
    logger.info(f"[DEBUG] Scanning {len(text_units)} text units for specific content...")
    found_target = False
    for i, unit in enumerate(text_units[:10]):  # Check first 10 units
        if "10 business days" in (unit.text or "").lower():
            found_target = True
            logger.info(f"[DEBUG] Found '10 business days' in text unit {i}: {unit.id}")
            logger.info(f"[DEBUG] Content preview: {(unit.text or '')[:200]}...")
    if not found_target and len(text_units) > 0:
        logger.info(f"[DEBUG] '10 business days' not found in first 10 text units")
        # Log content of first unit as sample
        first_unit = text_units[0]
        logger.info(f"[DEBUG] First unit sample (ID: {first_unit.id}): {(first_unit.text or '')[:200]}...")
```

**Why**: Lets us know if the specific content we're looking for is in the loaded chunks.

### Change 2: Context Builder Initialization Logging

**Location**: In `drift_search()` method, after line 766 (after context_builder creation)

**Added**:
```python
if is_debug_group:
    logger.info(f"[DEBUG] DRIFTSearchContextBuilder initialized with:")
    logger.info(f"[DEBUG]   - {len(entities)} entities")
    logger.info(f"[DEBUG]   - {len(relationships)} relationships")
    logger.info(f"[DEBUG]   - {len(text_units)} text units")
    logger.info(f"[DEBUG]   - {len(communities)} communities/reports")
```

**Why**: Confirms what data is being passed to DRIFT.

### Change 3: DRIFT Result Inspection Logging

**Location**: In `drift_search()` method, after line 800 (after DRIFT search completes)

**Added**:
```python
if is_debug_group:
    logger.info(f"[DEBUG] DRIFT result attributes: {dir(result)}")
    logger.info(f"[DEBUG] result.response: {result.response if hasattr(result, 'response') else 'N/A'}")
    logger.info(f"[DEBUG] result.context_data: {result.context_data if hasattr(result, 'context_data') else 'N/A'}")
```

**Why**: Lets us see what DRIFT actually returned and what fields are available.

### Change 4: Source Extraction Logging

**Location**: In `drift_search()` method, around line 815

**Changed from**:
```python
extracted_sources = self._extract_sources(result)
if is_debug_group:
    logger.info(f"[DEBUG] Extracted sources: {extracted_sources}")
    logger.info(f"[DEBUG] Number of sources: {len(extracted_sources)}")
```

**To**:
```python
extracted_sources = self._extract_sources(result, group_id=group_id, is_debug=is_debug_group)
if is_debug_group:
    logger.info(f"[DEBUG] Extracted sources: {extracted_sources}")
    logger.info(f"[DEBUG] Number of sources: {len(extracted_sources)}")
```

**Why**: Passes debug flag to extraction method for detailed logging.

### Change 5: Enhanced _extract_sources Method

**Location**: In `_extract_sources()` method (around line 942), completely rewritten

**Changed from**:
```python
def _extract_sources(self, result: Any) -> List[str]:
    """Extract source references from DRIFT result."""
    sources = []
    if hasattr(result, "context_data") and result.context_data:
        if "sources" in result.context_data:
            sources = result.context_data["sources"]
        elif "entities" in result.context_data:
            sources = [e.get("id") for e in result.context_data["entities"]]
    return sources
```

**To**:
```python
def _extract_sources(self, result: Any, group_id: str = "", is_debug: bool = False) -> List[str]:
    """Extract source references from DRIFT result."""
    sources = []
    
    if is_debug:
        logger.info(f"[DEBUG] _extract_sources() called")
        logger.info(f"[DEBUG] result has context_data: {hasattr(result, 'context_data')}")
    
    if hasattr(result, "context_data") and result.context_data:
        if is_debug:
            logger.info(f"[DEBUG] context_data keys: {result.context_data.keys()}")
        
        if "sources" in result.context_data:
            sources = result.context_data["sources"]
            if is_debug:
                logger.info(f"[DEBUG] Found 'sources' in context_data: {len(sources)} items")
        elif "entities" in result.context_data:
            sources = [e.get("id") for e in result.context_data["entities"]]
            if is_debug:
                logger.info(f"[DEBUG] Found 'entities' in context_data: {len(sources)} items")
        else:
            if is_debug:
                logger.info(f"[DEBUG] Neither 'sources' nor 'entities' found in context_data")
    else:
        if is_debug:
            logger.info(f"[DEBUG] No context_data available or it's empty")
    
    return sources
```

**Why**: Traces the exact path through source extraction logic with detailed logging.

### Change 6: Enhanced Text Unit Loading Method

**Location**: In `load_text_units_with_raptor_as_graphrag_models()` method (around line 1029)

**Added at beginning**:
```python
is_debug_group = (
    settings.V3_DRIFT_DEBUG_LOGGING and 
    (settings.V3_DRIFT_DEBUG_GROUP_ID is None or settings.V3_DRIFT_DEBUG_GROUP_ID == group_id)
)
```

**Added after loading data**:
```python
if is_debug_group:
    logger.info(f"[DEBUG] load_text_units_with_raptor_as_graphrag_models: group={group_id}")
    logger.info(f"[DEBUG]   Loaded {len(chunks_df)} text chunks from Neo4j")
    logger.info(f"[DEBUG]   Loaded {len(raptor_df)} RAPTOR nodes from Neo4j")
    if len(chunks_df) > 0:
        logger.info(f"[DEBUG]   Sample chunk (first row): {chunks_df.iloc[0].to_dict() if len(chunks_df) > 0 else 'N/A'}")
```

**Added before return**:
```python
if is_debug_group:
    logger.info(f"[DEBUG] Converted {len(chunks_df)} text chunks + {len(raptor_df)} RAPTOR nodes "
               f"= {len(text_units)} total text units for DRIFT search (group {group_id})")
    if text_units:
        logger.info(f"[DEBUG] First text unit sample: id={text_units[0].id}, text_len={len(text_units[0].text or '')}")
```

**Why**: Shows what's being loaded from Neo4j with sample content.

---

## Testing the Changes

### Verify Syntax
```bash
cd graphrag-orchestration
python -m py_compile graphrag-orchestration/app/core/config.py
python -m py_compile graphrag-orchestration/app/v3/services/drift_adapter.py
```

### Enable Debug Logging
```bash
export V3_DRIFT_DEBUG_LOGGING=true
export V3_DRIFT_DEBUG_GROUP_ID=drift-ok-1766862426
```

### Run Test
```bash
curl -X POST "https://graphrag-orchestration.../graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: drift-ok-1766862426" \
  -d '{"query":"What is the notice period?"}'
```

### Check Logs
Watch for `[DEBUG]` messages in container logs:
```bash
docker logs -f <container-id> | grep DEBUG
```

---

## Changes Summary Table

| Component | Change Type | Lines | Purpose |
|-----------|------------|-------|---------|
| config.py | Add | 2 settings | Enable/configure debug logging |
| drift_adapter.py | Add | 6 logger.info | Log text unit content scan |
| drift_adapter.py | Add | 4 logger.info | Log context builder init |
| drift_adapter.py | Add | 3 logger.info | Log DRIFT result attributes |
| drift_adapter.py | Enhance | 1 method call | Pass debug flag to extraction |
| drift_adapter.py | Rewrite | 1 method | Enhanced _extract_sources with trace |
| drift_adapter.py | Add | 10 logger.info | Log text unit loading details |

**Total Changes**: 7 code locations, ~40 lines of debug logging code

---

## Debug Output Examples

### Example 1: Content Found
```
[DEBUG] Scanning 47 text units for specific content...
[DEBUG] Found '10 business days' in text unit 8: chunk-abc-123
[DEBUG] Content preview: ...delivered within 10 business days of receiving...
```

### Example 2: Content Not Found
```
[DEBUG] Scanning 47 text units for specific content...
[DEBUG] '10 business days' not found in first 10 text units
[DEBUG] First unit sample (ID: chunk-xyz): ...this is an insurance policy document...
```

### Example 3: Sources Extracted Successfully
```
[DEBUG] _extract_sources() called
[DEBUG] result has context_data: True
[DEBUG] context_data keys: dict_keys(['sources', 'entities', 'reasoning'])
[DEBUG] Found 'sources' in context_data: 5 items
[DEBUG] Extracted sources: ['entity-1', 'entity-2', ...]
[DEBUG] Number of sources: 5
```

### Example 4: Sources Empty (The Issue)
```
[DEBUG] _extract_sources() called
[DEBUG] result has context_data: True
[DEBUG] context_data keys: dict_keys(['sources', 'entities', 'reasoning'])
[DEBUG] Found 'sources' in context_data: 0 items
[DEBUG] Extracted sources: []
[DEBUG] Number of sources: 0
```

---

## Backward Compatibility

✅ **Fully backward compatible**:
- Debug logging disabled by default (`V3_DRIFT_DEBUG_LOGGING=false`)
- Zero overhead when disabled
- No changes to method signatures (optional parameters only)
- No changes to return values
- No breaking changes to existing code

---

**Last Updated**: 2025-12-28
**Status**: ✅ All changes complete and syntax-verified
