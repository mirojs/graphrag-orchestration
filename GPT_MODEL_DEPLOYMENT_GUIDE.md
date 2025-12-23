# GPT Model Deployment Guide

## Overview
This guide explains how to deploy the recommended GPT model strategy for optimal GraphRAG performance.

## Model Strategy Summary

| Stage | Operation | Model | Rationale |
|-------|-----------|-------|-----------|
| **Indexing** | Entity/Relationship Extraction | **GPT-4.1** | 1M context window for bulk document ingestion; 3-5x faster than GPT-4o |
| **Indexing** | RAPTOR Clustering | **GPT-4.1** | Handles thematic clustering across large corpora without reasoning overhead |
| **Indexing** | Embeddings | **text-embedding-3-small** (1536 dims) | Optimal for Neo4j RAM efficiency; ~4% accuracy gap vs Large negligible |
| **Query** | Intent Routing | **GPT-5.2 Thinking Standard** | Native System 2 reasoning for 95%+ routing accuracy |
| **Query** | Answer Synthesis | **GPT-5.2 Pro High Reasoning** | Agentic self-correction to prevent hallucinations |

## Deployment Steps

### Prerequisites
- Azure OpenAI resource with appropriate quotas
- Access to GPT-4.1 and GPT-5.2 family models (availability varies by region)

### Step 1: Deploy Azure OpenAI Models

#### 1.1 Create GPT-4.1 Deployment (Indexing)
```bash
# Via Azure Portal:
# 1. Navigate to Azure OpenAI Studio > Deployments
# 2. Create new deployment:
#    - Model: gpt-4.1
#    - Deployment name: gpt-4.1-indexing
#    - TPM: 50K+ recommended for bulk indexing
```

```bash
# Via Azure CLI:
az cognitiveservices account deployment create \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --deployment-name gpt-4.1-indexing \
  --model-name gpt-4.1 \
  --model-version "2025-01-15" \
  --model-format OpenAI \
  --sku-capacity 50 \
  --sku-name "Standard"
```

#### 1.2 Create GPT-5.2 Thinking Deployment (Routing)
```bash
az cognitiveservices account deployment create \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --deployment-name gpt-5.2-thinking-standard \
  --model-name gpt-5.2-thinking-standard \
  --model-version "2025-01-15" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name "Standard"
```

#### 1.3 Create GPT-5.2 Pro Deployment (Synthesis)
```bash
az cognitiveservices account deployment create \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --deployment-name gpt-5.2-pro-high-reasoning \
  --model-name gpt-5.2-pro-high-reasoning \
  --model-version "2025-01-15" \
  --model-format OpenAI \
  --sku-capacity 20 \
  --sku-name "Standard"
```

#### 1.4 Deploy text-embedding-3-small (Cost Optimization)
```bash
az cognitiveservices account deployment create \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --deployment-name text-embedding-3-small \
  --model-name text-embedding-3-small \
  --model-version "2024-09-15" \
  --model-format OpenAI \
  --sku-capacity 50 \
  --sku-name "Standard"
```

### Step 2: Update Environment Configuration

Update your `.env` file or Azure Container App environment variables:

```bash
# Primary model (for synthesis and fallback)
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.2-pro-high-reasoning

# Specialized deployments
AZURE_OPENAI_INDEXING_DEPLOYMENT=gpt-4.1-indexing
AZURE_OPENAI_ROUTING_DEPLOYMENT=gpt-5.2-thinking-standard

# Embedding model (after migration from Large)
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536  # Changed from 3072
```

### Step 3: Update Azure Container App Configuration

```bash
# Get your Azure Container App name
APP_NAME=graphrag-orchestration
RESOURCE_GROUP=rg-graphrag-feature

# Update environment variables
az containerapp update \
  --name $APP_NAME \
  --resource-group $RESOURCE_GROUP \
  --set-env-vars \
    AZURE_OPENAI_DEPLOYMENT_NAME=gpt-5.2-pro-high-reasoning \
    AZURE_OPENAI_INDEXING_DEPLOYMENT=gpt-4.1-indexing \
    AZURE_OPENAI_ROUTING_DEPLOYMENT=gpt-5.2-thinking-standard \
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small \
    AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536
```

### Step 4: Verify Model Selection

Check that the correct models are being used:

```bash
# View current configuration
curl -X GET "https://<your-app>.azurecontainerapps.io/health" \
  -H "Content-Type: application/json" | jq .

# Expected output should show:
# {
#   "llm_model": "gpt-5.2-pro-high-reasoning",
#   "embedding_model": "text-embedding-3-small"
# }
```

### Step 5: Test Routing Logic

Test that different operations use the correct models:

```bash
# Test indexing (should use GPT-4.1)
curl -X POST "https://<your-app>.azurecontainerapps.io/graphrag/v3/index" \
  -H "X-Group-ID: test-group" \
  -H "Content-Type: application/json" \
  -d '{
    "document_url": "https://...",
    "extraction_mode": "balanced"
  }'

# Test query routing (should use specialized routing model if configured)
curl -X POST "https://<your-app>.azurecontainerapps.io/v3/query" \
  -H "X-Group-ID: test-group" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the payment terms?"
  }'
```

## Migration Timeline

### Current State: GPT-4o Baseline
- Keep using `AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o` for all operations
- No specialized deployments configured yet

### Phase 1: Deploy GPT-4.1 for Indexing (When Available)
- Deploy gpt-4-turbo-2024-04-09 (or equivalent GPT-4.1 in Azure)
- Set `AZURE_OPENAI_INDEXING_DEPLOYMENT=gpt-4-turbo-2024-04-09`
- Monitor indexing speed improvement (expect 3-5x faster)
- If not set, system continues using primary deployment

### Phase 2: Deploy GPT-5.2 Family for Queries (When Available)
- Deploy gpt-5.2-thinking and gpt-5.2-pro in Azure OpenAI
- Update `AZURE_OPENAI_ROUTING_DEPLOYMENT=<gpt-5.2-thinking-deployment-name>`
- Update `AZURE_OPENAI_DEPLOYMENT_NAME=<gpt-5.2-pro-deployment-name>`
- Monitor routing accuracy (expect 95%+ vs 85% with GPT-4o)

### Phase 3: Migrate to text-embedding-3-small (Recommended)
- Deploy text-embedding-3-small in Azure OpenAI
- Update `AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small`
- Update `AZURE_OPENAI_EMBEDDING_DIMENSIONS=1536`
- **Requires full reindex** - all documents must be re-embedded
- Update Neo4j vector index dimensions: `VECTOR<FLOAT32>(1536)`
- Monitor RAM usage reduction (expect 50% savings in Neo4j)

## Cost Analysis

### Current Baseline (GPT-4o + text-embedding-3-large)
- Indexing: $5.00 per 1M input tokens
- Query: $2.50 per 1M input tokens
- Embeddings: $0.13 per 1M tokens
- **Estimated monthly cost (10K docs, 1K queries):** ~$800

### Optimized Strategy (GPT-4.1 + GPT-5.2 + text-embedding-3-small)
- Indexing: $2.50 per 1M input tokens (GPT-4.1 - 50% cheaper + faster)
- Routing: $3.00 per 1M input tokens (GPT-5.2 Thinking)
- Synthesis: $5.00 per 1M input tokens (GPT-5.2 Pro - same as GPT-4o but better quality)
- Embeddings: $0.02 per 1M tokens (6.5x cheaper)
- **Estimated monthly cost (10K docs, 1K queries):** ~$550

**Savings: ~31% cost reduction + significant quality improvements**

## Monitoring & Observability

Add Application Insights queries to track model usage:

```kusto
// Model usage by operation
customMetrics
| where name == "llm_call"
| extend model = tostring(customDimensions.model)
| extend operation = tostring(customDimensions.operation)
| summarize count() by model, operation

// Indexing speed comparison
customMetrics
| where name == "indexing_duration"
| extend model = tostring(customDimensions.indexing_model)
| summarize avg(value) by model

// Routing accuracy
customMetrics
| where name == "routing_decision"
| extend correct = tobool(customDimensions.correct)
| summarize accuracy = todouble(countif(correct)) / count()
```

## Troubleshooting

### Issue: "Deployment not found" error
**Solution:** Verify deployment names match exactly:
```bash
az cognitiveservices account deployment list \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --query "[].{name:name, model:properties.model.name}" -o table
```

### Issue: High latency after migration
**Solution:** Ensure sufficient TPM quota allocated to each deployment
```bash
# Check current quota
az cognitiveservices account deployment show \
  --name <your-openai-resource> \
  --resource-group <your-rg> \
  --deployment-name gpt-4.1-indexing \
  --query "sku.capacity"
```

### Issue: Vector search failing after embedding migration
**Solution:** Must reindex all data with new embedding dimensions
```bash
# Drop existing Neo4j vector index
MATCH (n) WHERE n.embedding IS NOT NULL
CALL db.index.vector.dropIndex('entity_embeddings')

# Recreate with 1536 dimensions
CREATE VECTOR INDEX entity_embeddings
FOR (n:Entity)
ON n.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}
```

## Support

For issues or questions:
1. Check Application Insights logs for detailed error traces
2. Review Azure OpenAI quota and rate limits
3. Verify managed identity permissions for Azure OpenAI resource
4. Contact Azure OpenAI support for model availability in your region
