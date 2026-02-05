# Upstream Tracking

**Repository:** Azure-Samples/azure-search-openai-demo  
**URL:** https://github.com/Azure-Samples/azure-search-openai-demo  
**Current Base:** Manual copy (pre-subtree)  
**Last Sync:** 2026-02-05  
**Last Cherry-picked Commit:** 8883e727 (Fix multimodal image download from non-default blob container)  

## Sync Strategy

This frontend was initially copied manually from the upstream repository.
Future syncs should use git subtree for cleaner tracking:

```bash
# Convert to subtree (one-time)
git subtree add --prefix=frontend \
  https://github.com/Azure-Samples/azure-search-openai-demo.git \
  main --squash

# Future updates
git subtree pull --prefix=frontend \
  https://github.com/Azure-Samples/azure-search-openai-demo.git \
  main --squash
```

## Applied Customizations

### API Integration
- **Modified:** `app/backend/approaches/` - GraphRAG route integration
- **Modified:** `app/frontend/src/api/` - Extended for GraphRAG endpoints

### Settings Panel
- **Modified:** `app/frontend/src/components/Settings/` - Added:
  - Route preference selector (Auto / Local / Global / DRIFT)
  - Algorithm version toggle (V1 / V2)
  - Group selector for multi-tenancy

### Removed Features (not applicable to GraphRAG)
- Semantic ranker options (Azure AI Search specific)
- Image search (not supported)
- Vector search options (GraphRAG uses Neo4j)

### Configuration
- **Modified:** `app/backend/config.py` - GraphRAG-specific settings
- **Added:** Environment variables for GraphRAG API connection

## Known Divergences

| Component | Upstream | GraphRAG | Notes |
|-----------|----------|----------|-------|
| Search backend | Azure AI Search | Neo4j + HippoRAG | Complete replacement |
| Embeddings | Azure OpenAI | Voyage AI (V2) | Configurable |
| Response format | Standard RAG | 4-route hybrid | Extended context |
| Auth | Easy Auth only | Easy Auth + X-Group-ID | Multi-tenant |

## Upstream Compatibility Notes

When syncing from upstream:
1. **Review changes to:** `app/backend/approaches/` - may conflict with GraphRAG integration
2. **Keep our version of:** Settings components, API models
3. **Accept upstream:** UI improvements, security patches, accessibility fixes
4. **Test thoroughly:** Chat flow, settings persistence, error handling

## Version History

| Date | Action | Notes |
|------|--------|-------|
| 2026-01-30 | Initial copy | Manual copy from upstream main branch |
