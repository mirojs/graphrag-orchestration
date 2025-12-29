# DRIFT Debug Logging Guide

## Overview

This document explains how to enable and use the comprehensive DRIFT debug logging system added on 2025-12-28.

## Quick Start

### Enable Debug Logging for a Specific Group

Set these environment variables:

```bash
export V3_DRIFT_DEBUG_LOGGING=true
export V3_DRIFT_DEBUG_GROUP_ID=drift-ok-1766862426
```

Then make a DRIFT request to that group. You'll see detailed debug logs.

### Enable Debug Logging for All Groups

```bash
export V3_DRIFT_DEBUG_LOGGING=true
# Leave V3_DRIFT_DEBUG_GROUP_ID unset to log all groups
```

## What Gets Logged

### Stage 1: Text Unit Loading
When a DRIFT request loads text units from Neo4j, the debug logs will show:
- Number of text chunks loaded
- Number of RAPTOR nodes loaded
- Sample of first text unit (ID and text preview)
- **Search for specific content**: If you're looking for "10 business days", it will scan and report where it's found

### Stage 2: Context Builder Setup
Shows:
- Number of entities, relationships, text units, and communities passed to DRIFTSearchContextBuilder
- Confirms all prerequisites are present

### Stage 3: DRIFT Search Execution
Shows:
- **Execution path proof**: whether the request ran GraphRAG DRIFT or adapter fallback
- **Vectorstore proof**: whether entity mapping used Neo4j vector hits or the in-memory cosine fallback
- DRIFT result object attributes
- Raw result.response value
- Raw result.context_data value

### Stage 4: Source Extraction
Shows:
- Keys available in result.context_data
- Whether sources were found in "sources" vs "entities" fields
- Number of sources extracted
- Detailed trace of extraction logic

## Example Usage

### Test Command

```bash
# From host, with debug logging enabled
GROUP='drift-ok-1766862426'
BASE='https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io'

curl -sS -X POST "$BASE/graphrag/v3/query/drift" \
  -H 'Content-Type: application/json' \
  -H "X-Group-ID: $GROUP" \
  -d '{"query":"What is the notice period?"}' | jq .
```

### Expected Debug Output

In the container logs, you should see:

```
[DEBUG] load_text_units_with_raptor_as_graphrag_models: group=drift-ok-1766862426
[DEBUG]   Loaded 42 text chunks from Neo4j
[DEBUG]   Loaded 5 RAPTOR nodes from Neo4j
[DEBUG]   Sample chunk (first row): {...}
[DEBUG] Scanning 47 text units for specific content...
[DEBUG] Found '10 business days' in text unit 8: chunk-uuid-xyz
[DEBUG] Content preview: "...the notice period must be delivered within 10 business days..."
[DEBUG] DRIFTSearchContextBuilder initialized with:
[DEBUG]   - 23 entities
[DEBUG]   - 15 relationships
[DEBUG]   - 47 text units
[DEBUG]   - 3 communities/reports
[DRIFT_DEBUG] EXECUTION_PATH=graphrag_drift search_class=DRIFTSearchWithCandidates
[DRIFT_DEBUG] vectorstore(entity): neo4j_hits=10 result_count=10 in_memory_fallback=False cached_docs=9 k=10 fetch_k=250
[DEBUG] DRIFT result attributes: [...]
[DEBUG] result.response: "10 business days"
[DEBUG] result.context_data: {'sources': [...], ...}
[DEBUG] _extract_sources() called
[DEBUG] context_data keys: dict_keys(['sources', 'entities', ...])
[DEBUG] Found 'sources' in context_data: 5 items
[DEBUG] Extracted sources: [...]
[DEBUG] Number of sources: 5
```

## Configuration Options

All settings in `app/core/config.py`:

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `V3_DRIFT_DEBUG_LOGGING` | bool | False | Enable/disable all debug logging |
| `V3_DRIFT_DEBUG_GROUP_ID` | str \| None | None | Log only this group (or all if None) |
| `V3_DRIFT_DEBUG_FALLBACK` | bool | False | Allow fallback search when prerequisites missing |
| `V3_DRIFT_MAX_HISTORY_CHARS` | int | 120000 | Max serialized history chars (bounds reduce prompt growth) |
| `V3_DRIFT_MAX_HISTORY_MESSAGE_CHARS` | int | 40000 | Max chars per history message before truncation |

### If Logs Appear “Stuck”

If you see very large prompt lengths (e.g., `prompt_len=1134177`) or repeated messages like:

```
Reached token limit - reverting to previous context state
```

that usually means DRIFT reduce/history exploded the prompt beyond model context limits.

Mitigation:
- Lower `V3_DRIFT_MAX_HISTORY_CHARS` and/or `V3_DRIFT_MAX_HISTORY_MESSAGE_CHARS`.
- With `V3_DRIFT_DEBUG_LOGGING=true`, you should see:

```
[DRIFT_DEBUG] history truncated: max_total_chars=... max_msg_chars=...
```

This confirms the guardrail is active.

## Key Investigation Points

Use these logs to investigate:

1. **"Text units loaded but not used"** - Check if text units have empty text fields or are missing
2. **"Chunk content doesn't match Neo4j"** - Compare text in logs with what's in the database
3. **"10 business days not found"** - Check if it's in the database with different formatting (e.g., "10 business days", "10-business-days", etc.)
4. **"Sources empty"** - Check if result.context_data has "sources" or "entities" fields
5. **"Wrong sources returned"** - Check the source extraction logic logic to see which field is being used

## Proving DRIFT Is Really Running

Use these lines as definitive proof in ACA logs:

- Real GraphRAG DRIFT execution:
  - `[DRIFT_DEBUG] EXECUTION_PATH=graphrag_drift ...`

- Adapter fallback execution (should NOT appear during normal DRIFT runs):
  - `[DRIFT_DEBUG] EXECUTION_PATH=fallback_search reason=import_error]`

And for entity mapping / retrieval:

- Neo4j vector index produced in-tenant hits:
  - `in_memory_fallback=False` and `neo4j_hits>0`

- Neo4j vector index produced 0 in-tenant hits and the in-memory cosine path was used:
  - `in_memory_fallback=True` (requires `cached_docs>0`)

## Disabling Debug Logging

```bash
unset V3_DRIFT_DEBUG_LOGGING
unset V3_DRIFT_DEBUG_GROUP_ID
```

Or set:
```bash
export V3_DRIFT_DEBUG_LOGGING=false
```

## Performance Impact

Debug logging adds minimal overhead:
- Text scanning for "10 business days": ~10ms per 100 chunks
- Context data inspection: ~1ms
- Overall DRIFT query time still dominated by LLM calls (~30s+)

Safe to enable in production for specific groups during investigation.

## Next Steps After Debugging

Once you've identified the issue using these logs, you can:

1. **If chunk content is wrong**: Reindex with correct chunking strategy
2. **If sources not being extracted**: May need to modify `_extract_sources()` logic
3. **If text units not being used**: Check if DRIFT library expects different schema
4. **If content not in chunks**: Verify document was successfully indexed

---

**Last Updated**: 2025-12-28
**Related Files**: 
- `graphrag-orchestration/app/v3/services/drift_adapter.py`
- `graphrag-orchestration/app/core/config.py`
- `graphrag-orchestration/app/v3/routers/graphrag_v3.py`
