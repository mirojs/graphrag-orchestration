# GraphRAG Orchestration Service

This service implements the **"Gold Standard" Hybrid Architecture** for advanced RAG:
- **LlamaIndex PropertyGraphIndex**: For schema-guided, LLM-powered graph extraction.
- **Neo4j**: For high-performance graph storage and structural querying.
- **GraphRAG Methodology**: For community detection and global thematic reasoning.

## Architecture

## Booster patterns

This service uses small “boosters” (selection-stage recall boosts and post-reduce completeness boosters) to improve grounded recall and prevent map/reduce compression from dropping concrete anchors (e.g., deadlines, limits).

See: docs/BOOSTERS.md

### Components
1. **FastAPI Application**: Handles HTTP requests, auth, and orchestration.
2. **Neo4j Database**: Stores the Knowledge Graph (Nodes, Relationships, Properties).
3. **Vector Store**: Stores embeddings for semantic search (LanceDB for Dev, Azure AI Search for Prod).
4. **LlamaIndex**: The orchestration framework connecting LLMs, Graph, and Vectors.

### Multi-Tenancy
**CRITICAL:** Neo4j Community Edition does not support database-level multi-tenancy.
We enforce isolation at the **Application Level**:
- Every Node and Relationship MUST have a `group_id` property.
- Every Cypher query MUST include `WHERE n.group_id = $group_id`.
- The `GroupIsolationMiddleware` injects the `group_id` from the `X-Group-ID` header into the request state.

## Configuration
See `app/core/config.py` for all environment variables.

### Key Variables
- `GRAPH_STORE_TYPE`: `neo4j`
- `NEO4J_URI`: `bolt://neo4j:7687`
- `VECTOR_STORE_TYPE`: `lancedb` (or `azure_search`)
- `ENABLE_GROUP_ISOLATION`: `true`

### Document Ingestion Options

#### Option 1: Azure Document Intelligence (RECOMMENDED)
**Best for:** Production workloads, complex documents with tables, enterprise deployments

Azure Document Intelligence (formerly Form Recognizer) is Microsoft's mature, stable document layout extraction service:
- ✅ **Native Python SDK** - No manual REST API polling, automatic token refresh
- ✅ **Managed Identity Support** - Seamless Azure AD authentication out-of-the-box
- ✅ **Production-Ready** - Mature API (GA since 2020), enterprise SLA
- ✅ **Rich Layout Extraction** - Tables, sections, bounding boxes, reading order
- ✅ **Azure-Native** - Same ecosystem as other Azure AI services
- ✅ **Superior Table Structure** - Better than Content Understanding for complex tables

**Setup:**
1. Provision Azure Document Intelligence resource in Azure Portal
2. Set environment variables:
   ```bash
  # Preferred (Managed Identity / Entra ID): requires the resource's custom subdomain endpoint
  AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-di-resource-name>.cognitiveservices.azure.com/
  # Leave AZURE_DOCUMENT_INTELLIGENCE_KEY empty to use managed identity

  # Alternative (API key auth): regional endpoint also works, but requires a key
  # AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-region>.api.cognitive.microsoft.com/
  # AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key
   ```
3. Use `"ingestion": "document-intelligence"` in indexing requests (default)

**Example:**
```bash
curl -X POST http://localhost:8001/graphrag/index \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: tenant-001" \
  -d '{
    "documents": ["https://blob.url/contract.pdf"],
    "ingestion": "document-intelligence"
  }'
```

#### Option 2: LlamaParse (Alternative)
**Best for:** Non-Azure environments, highly complex layouts, research/experimentation

LlamaParse preserves document structure and integrates directly with LlamaIndex:
- ✅ Maintains table structure as metadata (not just markdown text)
- ✅ Preserves section hierarchy and reading order
- ✅ Provides bounding box information for spatial relationships
- ✅ Direct LlamaIndex Document integration (no manual conversion)
- ⚠️ Requires external API key (cloud.llamaindex.ai)
- ⚠️ Third-party dependency (not Azure-native)

**Setup:**
1. Get your free API key from [https://cloud.llamaindex.ai/](https://cloud.llamaindex.ai/)
2. Set environment variable: `LLAMA_CLOUD_API_KEY=llx-your-key`
3. Use `"ingestion": "llamaparse"` in indexing requests

#### Option 3: Azure Content Understanding (DEPRECATED)
**Status:** Legacy support only, not recommended for new deployments

⚠️ **Issues with Content Understanding:**
- ❌ Unstable API (frequent 422 validation errors)
- ❌ Poor table structure extraction compared to Document Intelligence
- ❌ Manual REST polling required (no mature SDK)
- ❌ Less reliable than Document Intelligence

**Use only if:**
- Already using CU in production and cannot migrate yet
- Use `"ingestion": "cu-standard"` for backward compatibility

## Development
```bash
# Start the service and Neo4j
docker-compose -f ../../docker-compose.dev.yml up graphrag neo4j

# Check health
curl http://localhost:8001/health
```

## API Endpoints

### GraphRAG Indexing
- `POST /graphrag/index` - Trigger indexing for a group
- `POST /graphrag/index-from-schema` - Index using Schema Vault schema
- `POST /graphrag/index-from-prompt` - Index using natural language prompt
- `GET /graphrag/index/{job_id}` - Check indexing status

### GraphRAG Query Endpoints

#### Local Search (Entity-Focused)
- `POST /graphrag/query/local`
- Best for: Specific entity lookups, relationship queries
- Example: "Tell me about Company X", "What's the relationship between A and B?"

#### Global Search (Community-Based)
- `POST /graphrag/query/global`
- Best for: Thematic questions, high-level summaries
- Example: "What are the main themes?", "Summarize key topics"

#### Hybrid Search (Vector + Graph)
- `POST /graphrag/query/hybrid`
- Best for: General semantic + structural queries
- Example: "Find documents about payment terms"

#### DRIFT Search (Multi-Step Reasoning) 🆕
- `POST /graphrag/query/drift`
- **Best for: Complex analytical questions requiring multiple reasoning steps**
- Uses GraphRAG's DRIFT algorithm (Dynamic Reasoning with Iterative Facts and Templates)
- Decomposes complex queries → iterative retrieval → synthesis
- Example queries:
  - "Compare warranty terms across all contracts and identify outliers"
  - "Analyze payment terms and find the most favorable conditions"
  - "What are the differences between vendor proposals?"
  - "Identify common failure patterns in warranty claims"

**Request Body:**
```json
{
  "query": "Your complex question",
  "conversation_history": [  // Optional: for context-aware follow-ups
    {"role": "user", "content": "Previous question"},
    {"role": "assistant", "content": "Previous answer"}
  ],
  "reduce": true,  // Whether to synthesize final answer
  "top_k": 10
}
```

### Orchestration
- `POST /orchestrate/analyze` - Route query to appropriate engine(s)
- `POST /orchestrate/extract` - Schema-based extraction via LlamaIndex

### Admin
- `GET /health` - Health check
- `GET /metrics` - Prometheus metrics
