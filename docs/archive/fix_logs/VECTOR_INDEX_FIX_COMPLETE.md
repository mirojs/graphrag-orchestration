# GraphRAG V3 Vector Index Fix - Complete

## Issues Fixed

### 1. Neo4j Vector Index Configuration
**Problem:** Vector index used wrong label (`__Entity__`) and wrong dimensions (1536)
**Solution:**
- Updated index to use `Entity` label (correct for V3 data model)
- Changed dimensions from 1536 to 3072 for text-embedding-3-large model
- File: `create_neo4j_indexes.py`

```python
{
    "name": "entity_embedding",
    "query": "CREATE VECTOR INDEX entity_embedding IF NOT EXISTS FOR (n:Entity) ON (n.embedding) OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}",
}
```

### 2. Embedder Wrapper Missing Methods
**Problem:** `GraphRAGEmbeddingWrapper` missing `get_text_embedding()` method
**Solution:** Added method to wrapper class
- File: `app/v3/services/drift_adapter.py`

```python
class GraphRAGEmbeddingWrapper:
    def embed_query(self, text: str) -> List[float]:
        return self.embedder.get_text_embedding(text)
    
    def get_text_embedding(self, text: str) -> List[float]:
        return self.embedder.get_text_embedding(text)
```

### 3. None Embedder Handling
**Problem:** Crashes when embedder is None (missing Azure OpenAI config)
**Solution:** Added None check and proper error messages

```python
self.embedder = GraphRAGEmbeddingWrapper(embedder) if embedder else None

# In fallback search:
if not self.embedder:
    raise RuntimeError("Embedder not initialized. Please configure Azure OpenAI settings")
```

### 4. DRIFT API Key Requirement
**Problem:** MS GraphRAG DRIFT requires API key authentication, fails with managed identity
**Solution:** Fall back to basic search when API key not available

```python
if settings.AZURE_OPENAI_API_KEY:
    # Use DRIFT
    llm_config = LanguageModelConfig(...)
else:
    # Fall back to basic vector search
    return await self._fallback_search(...)
```

### 5. Docker Build Issues
**Problem:** `.venv` directory copied to container causing "no space left" errors
**Solution:** Created `.dockerignore` file

```
.venv/
venv/
.env
__pycache__/
*.pyc
```

## Deployment

Successfully deployed with full rebuild:
- Build time: 4 minutes 15 seconds (full rebuild after cache clear)
- Endpoint: `https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/`

## Testing Status

### ✅ Completed
- Neo4j vector index created correctly (verified ONLINE, 100% populated)
- Code deployed successfully
- Embedder wrapper has all required methods
- Safety checks prevent crashes

### ⚠️ Remaining
- **Entities lack embeddings:** The 10,867 entities in the deployed Neo4j don't have embedding vectors
  - Root cause: V3 indexing pipeline didn't compute/save embeddings
  - Fix needed: Re-run indexing with embedding computation enabled
  
- **Deployed API missing Azure OpenAI config:** Environment variables not set in Container App
  - `AZURE_OPENAI_ENDPOINT`
  - `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
  - Either `AZURE_OPENAI_API_KEY` or managed identity setup

## Next Steps

1. **For deployed API to work:**
   ```bash
   az containerapp update \
     --name graphrag-orchestration \
     --resource-group rg-graphrag-feature \
     --set-env-vars \
       AZURE_OPENAI_ENDPOINT="https://..." \
       AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large" \
       AZURE_OPENAI_API_KEY="..." 
   ```

2. **For entities to have embeddings:**
   - Re-run the indexing endpoint with proper embedder initialized
   - Verify embeddings are computed: `entity.embedding = await self._embed_text(desc_text)`
   - Check: `MATCH (e:Entity) WHERE e.embedding IS NOT NULL RETURN count(e)`

3. **To test vector search:**
   ```python
   CALL db.index.vector.queryNodes('entity_embedding', 10, $embedding)
   YIELD node, score
   RETURN node.name, score
   ```

## Files Modified

- `/graphrag-orchestration/create_neo4j_indexes.py` - Vector index configuration
- `/graphrag-orchestration/app/v3/services/drift_adapter.py` - Embedder wrapper and DRIFT logic
- `/graphrag-orchestration/app/main.py` - Force rebuild comment
- `/graphrag-orchestration/.dockerignore` - Exclude .venv and build artifacts

## Verification Commands

```bash
# Check Neo4j vector index
python3 create_neo4j_indexes.py

# Check entity embeddings
python3 -c "
from dotenv import load_dotenv
from neo4j import GraphDatabase
import os
load_dotenv()
driver = GraphDatabase.driver(os.getenv('NEO4J_URI'), 
    auth=(os.getenv('NEO4J_USERNAME'), os.getenv('NEO4J_PASSWORD')))
with driver.session() as session:
    result = session.run('MATCH (e:Entity) WHERE e.embedding IS NOT NULL RETURN count(e)')
    print(f'Entities with embeddings: {result.single()[0]}')
driver.close()
"

# Test deployed API
python3 /tmp/test_query.py
```
