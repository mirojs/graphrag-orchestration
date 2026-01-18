# Section Chunking Configuration Verification

**Date**: January 18, 2026  
**Service**: graphrag-orchestration  
**Image**: graphragacr12153.azurecr.io/graphrag-orchestration:main-5a23d2d-20260118115423  
**Deployment**: Container App (Azure)

## Configuration Status

✅ **Section chunking is ENABLED by default**

### Environment Variable

- **Name**: `SECTION_GRAPH_ENABLED`
- **Default Value**: `"1"` (enabled)
- **Accepted Values**: `"1"`, `"true"`, `"yes"` (case-insensitive)
- **Location in Code**:
  - `enhanced_graph_retriever.py` (line 290)
  - `orchestrator.py` (line 1226)

### Code Implementation

Both files implement the same pattern:

```python
section_graph_enabled = os.getenv("SECTION_GRAPH_ENABLED", "1").strip().lower() in {"1", "true", "yes"}
section_diversify = section_diversify and section_graph_enabled
```

**Key Points**:
1. If the environment variable is **not set**, it defaults to `"1"` (enabled)
2. If the environment variable is **set**, it must be one of: `"1"`, `"true"`, `"yes"`
3. Any other value (including `"0"`, `"false"`, `"no"`) will disable section chunking

### Deployment Verification

**Container App**: graphrag-orchestration  
**Resource Group**: rg-graphrag-feature  
**Region**: Sweden Central

Query executed:
```bash
az containerapp show --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --query 'properties.template.containers[0].env[] | [?name==`SECTION_GRAPH_ENABLED`]'
```

**Result**: Environment variable is **not explicitly set** → defaults to **enabled** (`"1"`)

### Health Check

✅ Service is running and healthy:
```
https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/health
```

Response:
```json
{
  "status": "healthy",
  "service": "graphrag-orchestration"
}
```

## Section-Based Retrieval Implementation

### Exhaustive Retrieval (Current)

Since the Q-D3/Q-D10 fix (commits 1ac9a10, bfdee95, c13ec95):

- **max_per_section**: `None` (returns ALL chunks per section)
- **Coverage Strategy**: `"section_based_exhaustive"`
- **Query Type**: Comprehensive/exhaustive queries

### Code Location

File: `orchestrator.py` (Stage 4.3.6)

```python
section_chunks = await self.graph_retriever.get_all_sections_chunks(
    group_id=group_id,
    section_ids=identified_section_ids,
    max_per_section=None  # Return ALL chunks
)
```

## Validation Results

### Neo4j Section Mapping
- **Total Chunks**: 74/74 (100%)
- **Script**: `scripts/validate_section_coverage.py`
- **Status**: ✅ All chunks properly mapped to sections

### Benchmark Performance
- **Test**: Route 4 (drift_multi_hop) with 19 questions, 3 repeats
- **Judge**: gpt-5.1 (Azure OpenAI)
- **Score**: 54/57 (94.7%)
- **Q-D3**: 2/3 (downgraded for "too comprehensive" scope, but technically correct)
- **Q-D10**: 3/3 (warranty non-transferability now included)

### Target Chunks Verified
- `doc_c54a49f1097e494d9f6d906dc7bcf838_chunk_1`: Contains "ten (10) business days" ✅
- `doc_c54a49f1097e494d9f6d906dc7bcf838_chunk_3`: Contains "60 days repair window" ✅
- Both chunks properly retrieved via section-based exhaustive retrieval

## To Disable Section Chunking (If Needed)

If you need to disable section chunking in the future, set the environment variable:

```bash
az containerapp update \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --set-env-vars SECTION_GRAPH_ENABLED=0
```

Or in the Azure Portal:
1. Navigate to Container App > graphrag-orchestration
2. Settings > Environment variables
3. Add: `SECTION_GRAPH_ENABLED` = `0`

## Summary

✅ **Section chunking is currently ENABLED** in the deployed service  
✅ **Default behavior**: Enabled when environment variable is not set  
✅ **Exhaustive retrieval**: Returns all chunks per section (no artificial limits)  
✅ **Validated**: 100% section mapping in Neo4j  
✅ **Tested**: Q-D3 and Q-D10 now include all expected content  

---

**Related Documentation**:
- Architecture Design: [ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md](ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md)
- Root Cause Analysis: [docs/ROOT_CAUSE_ANALYSIS_ROUTE4_2_3_SCORES.md](docs/ROOT_CAUSE_ANALYSIS_ROUTE4_2_3_SCORES.md)
- Commits: 1ac9a10, bfdee95, c13ec95, 5a23d2d
