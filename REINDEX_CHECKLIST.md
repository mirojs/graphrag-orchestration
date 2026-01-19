# Re-Index with Section-Aware Chunking - Checklist

**Date:** January 19, 2026  
**Group ID:** `test-5pdfs-1768557493369886422`  
**Goal:** Enable section-aware chunking to realize Phase 1 edge benefits

---

## ✅ Pre-Flight Checks

### 1. Pipeline Components Verified

| Component | Status | Location |
|-----------|--------|----------|
| Section-aware chunking code | ✅ Complete | `app/hybrid/indexing/section_chunking/` |
| `USE_SECTION_CHUNKING` flag | ✅ Reads from env | Line 50 in `lazygraphrag_pipeline.py` |
| Section graph building | ✅ Auto-enabled | Steps 4.5-4.7 in pipeline |
| Phase 1 foundation edges | ✅ Complete | `_create_foundation_edges()` |
| Phase 2 connectivity edges | ✅ Complete | `_create_connectivity_edges()` |
| Reindex support | ✅ Complete | `reindex=True` in script |

### 2. Current State (Before Re-Index)

```
Chunking: Fixed 512-token windows (SentenceSplitter)
Chunks: 74 total
  ├─ chunk_strategy: NOT SET (fixed chunking)
  └─ section_path: Present in metadata (but ignored during chunking)

Sections: 204 nodes (from metadata)
Edges:
  ├─ IN_SECTION: 74 (chunk → section, based on metadata)
  ├─ APPEARS_IN_SECTION: 739 (Phase 1)
  ├─ APPEARS_IN_DOCUMENT: 388 (Phase 1)
  ├─ HAS_HUB_ENTITY: 124 (Phase 1)
  └─ SHARES_ENTITY: 322 (Phase 2)
```

**Problem:** Chunks don't respect section boundaries → mixed content → Phase 1 edges don't improve retrieval quality.

### 3. Expected State (After Re-Index)

```
Chunking: Section-boundary aligned (SectionAwareChunker)
Chunks: ~100-150 expected (varies by section size)
  ├─ chunk_strategy: "section_aware_v2"
  ├─ section_title: Populated
  ├─ is_summary_section: True for Purpose/Introduction
  └─ section_path: Used to determine chunk boundaries

Sections: ~200+ nodes (from actual chunking)
Edges:
  ├─ IN_SECTION: All chunks linked to their parent section
  ├─ APPEARS_IN_SECTION: Auto-created (Phase 1)
  ├─ APPEARS_IN_DOCUMENT: Auto-created (Phase 1)
  ├─ HAS_HUB_ENTITY: Auto-created (Phase 1)
  └─ SHARES_ENTITY: Auto-created (Phase 2)
```

**Benefit:** Chunks aligned with sections → coherent content → Phase 1 edges improve retrieval quality.

---

## 🚀 Execution Plan

### Step 1: Re-Index with Section Chunking

```bash
# Set environment variable
export USE_SECTION_CHUNKING=1
export GROUP_ID=test-5pdfs-1768557493369886422

# Verify flag is set
echo "USE_SECTION_CHUNKING=$USE_SECTION_CHUNKING"
echo "GROUP_ID=$GROUP_ID"

# Run indexing (will delete existing data and recreate)
cd /afh/projects/graphrag-orchestration
python scripts/index_with_hybrid_pipeline.py \
  --group-id $GROUP_ID \
  --max-docs 5

# Expected output:
#   ✅ Chunks created: ~100-150
#   ✅ Entities extracted: ~350-400
#   ✅ Sections created: ~200+
#   ✅ Foundation edges: APPEARS_IN_SECTION, APPEARS_IN_DOCUMENT, HAS_HUB_ENTITY
#   ✅ Connectivity edges: SHARES_ENTITY
```

### Step 2: Verify Section-Aware Chunks

```bash
# Run verification script
python check_chunk_strategy.py

# Expected output:
#   Strategy: section_aware_v2 (10/10 chunks)
#   Section Path: Populated
#   Section Title: Populated
#   ✅ FINDING: Chunks are using SECTION-AWARE chunking
```

### Step 3: Re-Enable Phase 1 in Route 2

```bash
# Check current Route 2 retriever settings
grep -n "use_new_edges" graphrag-orchestration/app/hybrid/pipeline/enhanced_graph_retriever.py

# If use_new_edges=False, change to True (default should already be True)
# Location: enhanced_graph_retriever.py around line 656-793
```

### Step 4: Test Route 2 (Local Search)

```bash
# Run Route 2 benchmark
python benchmarks/run_route2_benchmark.py --group-id $GROUP_ID

# Expected improvements:
#   - Faster retrieval (1-hop vs 2-hop)
#   - Better context (section-aligned chunks)
#   - Higher relevance scores
```

### Step 5: Update Route 3 for Coverage Queries

**Changes needed in `enhanced_graph_retriever.py`:**

1. **Add method to get summary chunks via Section nodes:**
   ```python
   async def get_summary_chunks_via_sections(self, group_id: str) -> List[TextChunk]:
       """Get one summary chunk per document using Section nodes."""
       query = """
       MATCH (d:Document {group_id: $group_id})<-[:PART_OF]-(c:TextChunk)
             -[:IN_SECTION]->(s:Section)
       WHERE s.depth = 0  // Top-level sections
         OR toLower(s.title) CONTAINS 'purpose'
         OR toLower(s.title) CONTAINS 'summary'
         OR toLower(s.title) CONTAINS 'introduction'
       WITH d, c, s
       ORDER BY CASE 
         WHEN toLower(s.title) CONTAINS 'purpose' THEN 1
         WHEN toLower(s.title) CONTAINS 'summary' THEN 2
         WHEN toLower(s.title) CONTAINS 'introduction' THEN 3
         ELSE 4
       END, c.chunk_index
       WITH d, collect(c)[0] AS representative_chunk
       RETURN representative_chunk
       """
       # Implementation details...
   ```

2. **Update coverage query logic** to use Section-based retrieval

### Step 6: Test Route 3 (Global Search)

```bash
# Run Route 3 benchmark
python benchmarks/run_route3_benchmark.py --group-id $GROUP_ID

# Expected improvements:
#   - Coverage: 95%+ (vs current ~60%)
#   - Thematic score: 95%+ (vs current ~85%)
#   - Document citations: 5/5 (vs current 2-3/5)
```

---

## 📊 Success Criteria

### Route 2 (Local Search)
- [ ] Retrieval time improved vs old 2-hop path
- [ ] Context quality improved (section-coherent chunks)
- [ ] Test suite passes with `use_new_edges=True`

### Route 3 (Global Search)
- [ ] Coverage queries return 1 chunk per document
- [ ] Summary sections correctly identified
- [ ] Thematic scores ≥ 95%
- [ ] Document citations: 5/5 documents

### General
- [ ] All chunks have `chunk_strategy: "section_aware_v2"`
- [ ] Section nodes properly linked to chunks
- [ ] Phase 1 + Phase 2 edges all created
- [ ] No regression in Route 1 or Route 4

---

## 🔧 Troubleshooting

### Issue: Chunks still show fixed chunking
**Check:** Is `USE_SECTION_CHUNKING` set?
```bash
echo $USE_SECTION_CHUNKING  # Should show "1"
```

### Issue: No summary sections found
**Check:** Do sections have summary titles?
```bash
python -c "
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os
load_dotenv('graphrag-orchestration/.env')
driver = GraphDatabase.driver(os.getenv('NEO4J_URI'), auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD')))
with driver.session() as s:
    r = s.run('MATCH (sec:Section {group_id: \$gid}) WHERE toLower(sec.title) CONTAINS \"purpose\" RETURN count(sec)', gid='test-5pdfs-1768557493369886422')
    print(f'Purpose sections: {r.single()[0]}')
"
```

### Issue: Phase 2 edges not created
**Check:** Pipeline logs for connectivity edge creation
```bash
grep "connectivity_edges_created" <indexing-log-file>
```

---

## 📝 Notes

- **Backup not needed:** The group will be completely deleted and recreated (`reindex=True`)
- **Time estimate:** ~5-10 minutes for 5 PDFs
- **LLM calls:** Entity extraction will make OpenAI API calls
- **Cost:** Minimal (5 docs, ~200 chunks, embeddings + extraction)

---

## ✅ Completion Checklist

- [ ] Step 1: Re-index completed successfully
- [ ] Step 2: Verified section-aware chunks
- [ ] Step 3: Phase 1 enabled in Route 2
- [ ] Step 4: Route 2 benchmark shows improvement
- [ ] Step 5: Route 3 updated for coverage queries
- [ ] Step 6: Route 3 benchmark shows improvement
- [ ] Documentation updated
- [ ] Ready for Phase 3 (Route 4 DRIFT bridge)

---

**Ready to proceed? Start with Step 1!**
