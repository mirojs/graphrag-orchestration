# GraphRAG Orchestration Service

Enterprise-grade knowledge graph service using Neo4j GraphRAG for intelligent document analysis and semantic querying.

## 🚀 Features

- **Neo4j GraphRAG Integration**: Official `neo4j-graphrag-python` package (v1.10.1)
- **3 Retrieval Methods**:
  - Vector similarity search (chunk-based)
  - Hybrid search (vector + fulltext fusion)
  - Text-to-Cypher (LLM-generated graph queries)
- **Document Indexing**: SimpleKGPipeline with automatic entity resolution
- **Multi-tenancy**: Group-based data isolation
- **Azure OpenAI**: GPT-4o + text-embedding-3-large (3072 dimensions)
- **91% Code Reduction**: Replaced 1,636 lines with ~150 lines

## 📋 Prerequisites

- Azure subscription
- Neo4j Aura Pro instance
- Azure OpenAI service (GPT-4o + text-embedding-3-large)
- Azure CLI (`az`)
- Azure Developer CLI (`azd`)
- Python 3.11+

## 🏗️ Architecture

```
┌─────────────────────────────────────────┐
│   FastAPI Application (Port 8000)      │
├─────────────────────────────────────────┤
│  Neo4j GraphRAG Service                 │
│  ├─ VectorCypherRetriever              │
│  ├─ HybridCypherRetriever              │
│  ├─ Text2CypherRetriever               │
│  └─ SimpleKGPipeline (Indexing)        │
├─────────────────────────────────────────┤
│  Azure OpenAI                           │
│  ├─ LLM: gpt-4o                        │
│  └─ Embeddings: text-embedding-3-large │
├─────────────────────────────────────────┤
│  Neo4j Aura Pro (Graph Database)       │
│  └─ Group-aware multi-tenancy          │
└─────────────────────────────────────────┘
```

## 🛠️ Local Development

### 1. Setup Environment

```bash
# Clone repository
cd /afh/projects/graphrag-orchestration

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r graphrag-orchestration/requirements.txt
```

### 2. Configure Environment Variables

Create `.env` file:

```bash
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://your-openai.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-large
AZURE_OPENAI_EMBEDDING_DIMENSIONS=3072
AZURE_OPENAI_API_VERSION=2024-10-21

# Neo4j
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j

# Multi-tenancy
ENABLE_GROUP_ISOLATION=true
```

### 3. Run Locally

```bash
cd graphrag-orchestration
python -m uvicorn app.main:app --reload --port 8000
```

API available at: `http://localhost:8000`
Docs available at: `http://localhost:8000/docs`

## ☁️ Azure Deployment

### Quick Deploy

```bash
# Login to Azure
az login
azd auth login

# Deploy
azd up
```

### Manual Deployment

```bash
# Provision infrastructure
azd provision

# Deploy application
azd deploy
```

## 📡 API Endpoints

### V2 Endpoints (Neo4j GraphRAG)

**Local Search** (Vector Similarity)
```bash
POST /graphrag/v2/query/local
{
  "query": "Who is the CEO of Acme Corporation?",
  "top_k": 10
}
```

**Hybrid Search** (Vector + Fulltext)
```bash
POST /graphrag/v2/query/hybrid
{
  "query": "Financial performance in 2024",
  "top_k": 10
}
```

**Structured Search** (Text-to-Cypher)
```bash
POST /graphrag/v2/query/structured
{
  "query": "Show all relationships for Jane Smith"
}
```

**Index Text**
```bash
POST /graphrag/v2/index/text
{
  "text": "Your document content...",
  "document_name": "annual_report_2024.txt"
}
```

### Required Headers

All requests must include:
```
X-Group-ID: your-tenant-id
Content-Type: application/json
```

## 🧪 Testing

```bash
# Run tests
pytest graphrag-orchestration/tests/

# Test specific module
pytest graphrag-orchestration/tests/services/test_neo4j_graphrag_service.py -v

# Run with coverage
pytest --cov=app graphrag-orchestration/tests/
```

## 📊 Performance

- **Code Reduction**: 91% (1,636 → ~150 lines)
- **Document Compression**: 84.5% (4,382 → 678 words)
- **Query Latency**: Sub-second
- **Embedding Quality**: 3,072 dimensions (text-embedding-3-large)

## 🔒 Multi-Tenancy

All data is isolated by `group_id`:
- Neo4j nodes have `group_id` property
- All Cypher queries filter by partition key
- Cross-tenant data leaks prevented at database level

## 📝 Configuration

See `graphrag-orchestration/app/core/config.py` for all available settings.

## 🐛 Troubleshooting

**Neo4j Connection Issues**
```bash
# Test connection
python -c "from neo4j import GraphDatabase; driver = GraphDatabase.driver('neo4j+s://...', auth=('neo4j', 'password')); driver.verify_connectivity(); print('OK')"
```

**Azure OpenAI API Issues**
```bash
# Check API version
curl https://your-openai.openai.azure.com/openai/deployments?api-version=2024-10-21
```

**Missing Dependencies**
```bash
pip install --upgrade neo4j-graphrag-python==1.10.1
```

## 📚 Documentation

- [Neo4j GraphRAG Python Docs](https://neo4j.com/docs/graphrag-python/)
- [Azure OpenAI Service](https://learn.microsoft.com/azure/ai-services/openai/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

## 🤝 Contributing

This is a standalone service extracted from the Content Processing Solution Accelerator.

## 📄 License

MIT License - See LICENSE file for details
