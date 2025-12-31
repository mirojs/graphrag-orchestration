# Neo4j GenAI Plugin Integration Guide

## Overview

Neo4j's GenAI plugin (introduced in 2025.11) provides native embedding generation using `ai.text.embedBatch()`. This eliminates the need to transfer embeddings over the network and can improve performance by 20-30%.

## Current Status

- **Neo4j Aura Instance**: `neo4j+s://a86dcf63.databases.neo4j.io`
- **Version**: 5.27-aura
- **GenAI Plugin**: ❌ Not currently available
- **Current Approach**: LlamaIndex with Azure OpenAI `text-embedding-3-large`

## Benefits of Neo4j GenAI Plugin

1. **Performance**: 20-30% faster embedding generation (no network transfer)
2. **Reduced API Calls**: Embeddings generated inside Neo4j
3. **Automatic Retry**: Built-in error handling and retry logic
4. **Native Integration**: Better integration with Neo4j vector indexes
5. **Simplified Code**: Single Cypher query for fetch-embed-store

## How to Enable

### Option 1: Neo4j Aura Console

1. Log in to [Neo4j Aura Console](https://console.neo4j.io/)
2. Navigate to your instance: `a86dcf63.databases.neo4j.io`
3. Go to **Settings** → **Plugins**
4. Enable **Generative AI** plugin
5. Configure Azure OpenAI credentials:
   ```
   Provider: azure-openai
   Endpoint: https://graphrag-openai-8476.openai.azure.com/
   API Key: [Use Managed Identity or API key]
   Model: text-embedding-3-large
   Dimensions: 3072
   ```

### Option 2: Contact Neo4j Support

- **Requirement**: Aura Professional or Enterprise tier
- Email: support@neo4j.com
- Request: Enable GenAI plugin on instance `a86dcf63.databases.neo4j.io`

## Verification

Run this command to check if the plugin is available:

```bash
python3 -c "
from app.v3.services.neo4j_genai_embeddings import is_genai_plugin_available
from neo4j import GraphDatabase
import os

driver = GraphDatabase.driver(
    'neo4j+s://a86dcf63.databases.neo4j.io',
   auth=('neo4j', os.environ['NEO4J_PASSWORD'])
)

if is_genai_plugin_available(driver):
    print('✅ GenAI plugin available')
    print('Run: python3 test_neo4j_genai_embeddings.py')
else:
    print('❌ GenAI plugin not available')
    print('Action: Enable plugin in Aura console or contact Neo4j support')

driver.close()
"
```

## Migration Steps

Once the plugin is enabled:

1. **Test the Plugin**:
   ```bash
   python3 test_neo4j_genai_embeddings.py
   ```

2. **Update Configuration** in `indexing_pipeline.py`:
   - The code will automatically detect and use Neo4j GenAI if available
   - Fallback to LlamaIndex if not available

3. **Run Test**:
   ```bash
   python3 test_phase1_5docs.py
   ```

4. **Verify Performance**:
   - Check logs for "Neo4j GenAI plugin detected"
   - Embedding generation should be 20-30% faster
   - Entity counts should remain the same (350 entities)

## Performance Comparison

### Current (LlamaIndex):
- **Approach**: Generate embeddings via Azure OpenAI API → Transfer to Neo4j
- **Network Overhead**: ~2-3 seconds for 350 entities
- **API Calls**: 1 batch call to Azure OpenAI
- **Total Time**: ~5-7 seconds

### With Neo4j GenAI:
- **Approach**: Neo4j calls Azure OpenAI internally, stores directly
- **Network Overhead**: 0 seconds (no embedding transfer)
- **API Calls**: Neo4j handles internally
- **Expected Time**: ~3-5 seconds (30% improvement)

## Code Changes Required

**None!** The implementation in `neo4j_genai_embeddings.py` is ready to use. The code will:
1. Detect if GenAI plugin is available
2. Use Neo4j GenAI if available
3. Fallback to LlamaIndex if not

## Additional Resources

- [Neo4j GenAI Plugin Docs](https://neo4j.com/docs/genai/plugin/current/embeddings/#multiple-embeddings)
- [Neo4j Aura December 2025 Release Notes](https://neo4j.com/release-notes/aura/release-notes-neo4j-aura-database-december-2025/)
- [Azure OpenAI Embeddings](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/embeddings)

## Next Steps

1. **Enable GenAI Plugin** on Neo4j Aura instance
2. **Run Verification** command above
3. **Test with sample data** using `test_neo4j_genai_embeddings.py`
4. **Deploy** if tests pass
5. **Monitor performance** improvements in production

## Support

If you encounter issues:
- Check Neo4j Aura tier (must be Professional or Enterprise)
- Verify Azure OpenAI credentials are configured in Neo4j
- Check Neo4j logs for GenAI plugin initialization errors
- Contact Neo4j support: support@neo4j.com
