# DRIFT Debug Logging Flow Diagram

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DRIFT Search Request                             │
│              Query: "What is the notice period?"                         │
│              Group: drift-ok-1766862426                                  │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
                ┌──────────────▼──────────────┐
                │ Check Debug Settings        │
                │ - V3_DRIFT_DEBUG_LOGGING?   │
                │ - V3_DRIFT_DEBUG_GROUP_ID?  │
                └──────────────┬──────────────┘
                               │
                    ┌──────────▼───────────┐
                    │ is_debug_group = true │
                    └──────────┬────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 1: TEXT UNIT LOADING                                              │
├──────────────────────────────────────────────────────────────────────────┤
│ Function: load_text_units_with_raptor_as_graphrag_models()             │
│                                                                          │
│ [DEBUG] load_text_units_with_raptor_as_graphrag_models: group=...      │
│ [DEBUG]   Loaded 42 text chunks from Neo4j                             │
│ [DEBUG]   Loaded 5 RAPTOR nodes from Neo4j                             │
│ [DEBUG]   Sample chunk (first row): {...}                              │
│ [DEBUG] Converted 42 + 5 = 47 total text units                         │
│ [DEBUG] First text unit sample: id=chunk-xyz, text_len=2345             │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 2: CONTENT SCANNING                                               │
├──────────────────────────────────────────────────────────────────────────┤
│ Looking for: "10 business days"                                          │
│                                                                          │
│ [DEBUG] Scanning 47 text units for specific content...                  │
│ FOR i=0 to 10:                                                           │
│   IF text_unit[i].text contains "10 business days":                     │
│     [DEBUG] Found '10 business days' in text unit 8: chunk-abc-123      │
│     [DEBUG] Content preview: ...within 10 business days...              │
│   ELSE:                                                                  │
│     [DEBUG] '10 business days' not found in first 10                    │
│     [DEBUG] First unit sample: {first unit content}                     │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 3: ENTITIES/RELATIONSHIPS/COMMUNITIES LOADING                     │
├──────────────────────────────────────────────────────────────────────────┤
│ - Load 23 entities from Neo4j                                           │
│ - Load 15 relationships from Neo4j                                      │
│ - Load 3 community reports from Neo4j                                   │
│                                                                          │
│ [DRIFT STAGE 2/5] Loaded 23 entities, 15 relationships,                │
│                        47 text units, 3 communities                     │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 4: BUILD DRIFT CONTEXT BUILDER                                    │
├──────────────────────────────────────────────────────────────────────────┤
│ DRIFTSearchContextBuilder initialized with:                             │
│ - model = drift_llm (LlamaIndex wrapper)                                │
│ - text_embedder = GraphRAGEmbeddingWrapper                              │
│ - entities = [Entity, Entity, ...]  (23 items)                          │
│ - relationships = [Relationship, ...]  (15 items)                       │
│ - reports = [CommunityReport, ...]  (3 items)                          │
│ - text_units = [TextUnit, TextUnit, ...]  (47 items)                    │
│                                                                          │
│ [DEBUG] DRIFTSearchContextBuilder initialized with:                     │
│ [DEBUG]   - 23 entities                                                  │
│ [DEBUG]   - 15 relationships                                             │
│ [DEBUG]   - 47 text units                                                │
│ [DEBUG]   - 3 communities/reports                                        │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 5: EXECUTE DRIFT SEARCH                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ DRIFTSearch.search(query="What is the notice period?")                  │
│                                                                          │
│ DRIFT internally:                                                        │
│ 1. Decomposes query into sub-questions                                  │
│ 2. Searches entities, relationships, text units, reports                │
│ 3. Iterates (max 5 times) to refine answer                             │
│ 4. Returns SearchResult with:                                           │
│    - response: str (the answer)                                         │
│    - context_data: dict (sources, entities, reasoning, etc.)           │
│                                                                          │
│ [DRIFT STAGE 4/5] DRIFT search completed                                │
│ [DEBUG] DRIFT result attributes: [...]                                  │
│ [DEBUG] result.response: "Not specified..."                             │
│ [DEBUG] result.context_data: {...}                                      │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ STAGE 6: EXTRACT SOURCES                                                │
├──────────────────────────────────────────────────────────────────────────┤
│ Function: _extract_sources(result, group_id=..., is_debug=True)         │
│                                                                          │
│ [DEBUG] _extract_sources() called                                        │
│ [DEBUG] result has context_data: True                                    │
│                                                                          │
│ IF result.context_data exists:                                          │
│   [DEBUG] context_data keys: dict_keys(['sources', 'entities', ...])    │
│                                                                          │
│   IF 'sources' in context_data:                                         │
│     sources = context_data['sources']                                   │
│     [DEBUG] Found 'sources' in context_data: 5 items                    │
│                                                                          │
│   ELIF 'entities' in context_data:                                      │
│     sources = [e.get('id') for e in context_data['entities']]          │
│     [DEBUG] Found 'entities' in context_data: 5 items                   │
│                                                                          │
│   ELSE:                                                                  │
│     [DEBUG] Neither 'sources' nor 'entities' found                      │
│ ELSE:                                                                    │
│   [DEBUG] No context_data available or empty                            │
│                                                                          │
│ Return: sources (list of IDs)                                           │
│ [DEBUG] Extracted sources: ['entity-1', 'entity-2', ...]               │
│ [DEBUG] Number of sources: 5                                             │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│ FINAL RESPONSE                                                           │
├──────────────────────────────────────────────────────────────────────────┤
│ {                                                                        │
│   "answer": "Not specified in the provided documents.",                 │
│   "confidence": 0.85,                                                    │
│   "iterations": 5,                                                       │
│   "sources": [],  ← EMPTY (THE ISSUE)                                   │
│   "reasoning_path": [...]                                               │
│ }                                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

## Debug Output Analysis

### Scenario 1: Content Found and Used ✓

```
[DEBUG] Found '10 business days' in text unit 8: chunk-abc
[DEBUG] DRIFTSearchContextBuilder initialized with: 47 text units
[DEBUG] result.response: "10 business days"
[DEBUG] Found 'sources' in context_data: 5 items
[DEBUG] Extracted sources: ['entity-1', ...]
[DEBUG] Number of sources: 5

STATUS: ✓ GOOD - Content found and returned
```

### Scenario 2: Content Found But Not Used ⚠

```
[DEBUG] Found '10 business days' in text unit 8: chunk-abc
[DEBUG] DRIFTSearchContextBuilder initialized with: 47 text units
[DEBUG] result.response: "Not specified in the provided documents."
[DEBUG] Found 'sources' in context_data: 0 items
[DEBUG] Extracted sources: []
[DEBUG] Number of sources: 0

STATUS: ⚠ ISSUE - Content loaded but DRIFT didn't use it
ACTION: Investigate DRIFT library's context building/search logic
```

### Scenario 3: Content Missing From Chunks ✗

```
[DEBUG] '10 business days' not found in first 10 text units
[DEBUG] First unit sample: "This is an insurance policy..."
[DEBUG] DRIFTSearchContextBuilder initialized with: 47 text units
[DEBUG] result.response: "Not specified in the provided documents."
[DEBUG] Extracted sources: []

STATUS: ✗ DATA ISSUE - Content not in chunks
ACTION: Check Neo4j for actual content, may need re-indexing
```

### Scenario 4: Sources Field Missing ✗

```
[DEBUG] DRIFTSearchContextBuilder initialized with: 47 text units
[DEBUG] result.response: "10 business days"
[DEBUG] context_data keys: dict_keys(['entities', 'reasoning'])
[DEBUG] Neither 'sources' nor 'entities' found in context_data
[DEBUG] Extracted sources: []

STATUS: ✗ SCHEMA ISSUE - DRIFT not populating sources
ACTION: Check DRIFT library version/configuration
```

## Decision Tree: What the Logs Tell You

```
                      Logs collected?
                            │
                ┌───────────┴───────────┐
                │                       │
                ▼                       ▼
         Yes, analyze            No, enable and
                                 re-run query
                │
                ▼
        "10 business days" found?
                │
        ┌───────┴───────┐
        │               │
        ▼               ▼
       YES              NO
        │               │
        │               ▼
        │         → Check Neo4j
        │         → Re-index if needed
        │
        ▼
   Sources extracted?
        │
    ┌───┴───┐
    │       │
    ▼       ▼
   YES     NO
    │       │
    ▼       ▼
   ✓ OK   context_data has
          'sources' field?
            │
        ┌───┴───┐
        │       │
        ▼       ▼
       YES      NO
        │       │
        ▼       ▼
    Field    DRIFT library
    empty?   not populating
    │        sources
    │        → Check version
    ▼        → Update config
   DRIFT not
   using     
   content
   → Trace DRIFT
     internals
```

## Log Filtering Tips

### See Only DEBUG Messages
```bash
docker logs <container> 2>&1 | grep DEBUG
```

### See DEBUG + DRIFT STAGE Messages
```bash
docker logs <container> 2>&1 | grep -E "DEBUG|DRIFT STAGE"
```

### Follow Logs in Real Time
```bash
docker logs -f <container> 2>&1 | grep DEBUG
```

### Search for Specific Content
```bash
docker logs <container> 2>&1 | grep "10 business days"
```

---

**Created**: 2025-12-28
**Purpose**: Visual guide to DRIFT debug logging flow
**Related**: DRIFT_DEBUG_LOGGING_GUIDE.md, DRIFT_DEBUG_LOGGING_IMPLEMENTATION.md
