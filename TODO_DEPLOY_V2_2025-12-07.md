# GraphRAG V2 Deployment - TODO

## Current Status
- **Issue**: Deployed container has old `neo4j-graphrag` version that doesn't support `schema` parameter in `SimpleKGPipeline`
- **Error**: `SimpleKGPipeline.__init__() got an unexpected keyword argument 'schema'`

## Root Cause
Two locations for requirements.txt:
1. `/afh/projects/graphrag-orchestration/requirements.txt` - symlinked/shared
2. `/afh/projects/graphrag-orchestration/graphrag-orchestration/requirements.txt` - **Actually used by Dockerfile**

We updated (1) but Docker builds from (2).

## Steps to Complete Tomorrow

### 1. Update the correct requirements.txt
The file `/afh/projects/graphrag-orchestration/graphrag-orchestration/requirements.txt` needs these versions:

```
# LlamaIndex packages - need compatible versions
llama-index-core>=0.12.0
llama-index-llms-azure-openai>=0.3.0
llama-index-embeddings-azure-openai>=0.3.0
llama-index-vector-stores-azureaisearch>=0.3.0
llama-index-graph-stores-neo4j>=0.4.0
llama-index-packs-raptor>=0.3.0

# Key package - needs 1.10.1 for schema support
neo4j-graphrag==1.10.1

# Azure packages
azure-cosmos==4.14.2
azure-storage-blob==12.27.1
azure-identity==1.25.1
azure-ai-documentintelligence==1.0.2
azure-search-documents==11.6.0
openai>=1.0.0
```

**Note**: There's a dependency conflict with `llama-index-packs-raptor 0.4.1` requiring `llama-index-llms-openai>=0.5.0`. Either:
- Use looser version constraints (>=) instead of pinned versions (==)
- Or pin compatible versions that work together

### 2. Rebuild Docker Image
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration
az acr login -n graphragacr12153 -g rg-graphrag-feature --subscription "3adfbe7c-9922-40ed-b461-ec798989a3fa"
docker build --no-cache -t graphragacr12153.azurecr.io/graphrag-orchestration:latest .
docker push graphragacr12153.azurecr.io/graphrag-orchestration:latest
```

### 3. Update Container App
```bash
az containerapp update \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --subscription "3adfbe7c-9922-40ed-b461-ec798989a3fa" \
  --image graphragacr12153.azurecr.io/graphrag-orchestration:latest
```

### 4. Verify Deployment
```bash
# Check neo4j-graphrag version
curl -s "https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/health"

# Test V2 indexing endpoint
curl -s "https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/graphrag/v2/index/text" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-group" \
  -d '{"text": "Bill Gates and Paul Allen founded Microsoft in 1975."}' | python -m json.tool
```

### 5. Run 5-Document Benchmark
Once deployment is working, run the benchmark test:
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/services/graphrag-orchestration
python test_graphrag_5doc_api_benchmark.py
```

## Key Files
| File | Purpose |
|------|---------|
| `graphrag-orchestration/graphrag-orchestration/requirements.txt` | Docker build requirements |
| `graphrag-orchestration/graphrag-orchestration/Dockerfile` | Container build spec |
| `app/services/neo4j_graphrag_service.py` | V2 indexing with SimpleKGPipeline |
| `test_graphrag_5doc_api_benchmark.py` | 5-document benchmark test |

## Azure Resources
| Resource | Value |
|----------|-------|
| Container App | graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io |
| ACR | graphragacr12153.azurecr.io |
| Resource Group | rg-graphrag-feature |
| Subscription | 3adfbe7c-9922-40ed-b461-ec798989a3fa |
| Neo4j | neo4j-graphrag-23987.swedencentral.azurecontainer.io:7687 |

## Model Configuration
| Setting | Value |
|---------|-------|
| LLM | gpt-4o |
| Embeddings | text-embedding-3-large (3072 dims) |
| API Version | 2024-10-21 |
