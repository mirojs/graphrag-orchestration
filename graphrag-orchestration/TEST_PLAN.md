# GraphRAG Neo4j Integration Test Plan

## Test Stages

### Stage 1: Local Component Tests (No Container)
Test individual services and components in isolation using local Python environment.

**Prerequisites:**
- Python environment with dependencies installed
- Neo4j running locally (Docker or native)
- Azure credentials configured (for CU and OpenAI)

**Tests:**
1. **Schema Converter** - Standalone logic test
   ```bash
   cd services/graphrag-orchestration
   python -m pytest app/tests/test_schema_converter.py -v
   ```

2. **LLM Service** - Azure OpenAI connectivity
   ```bash
   python app/tests/test_llm_service.py
   ```

3. **Neo4j Connection** - Graph store health
   ```bash
   python app/tests/test_neo4j_connection.py
   ```

4. **CU Standard Ingestion** - Document extraction
   ```bash
   python app/tests/test_cu_ingestion_service.py
   ```

**Expected Outcomes:**
- ✅ All unit tests pass
- ✅ Schema conversion logic works correctly
- ✅ Azure services are reachable
- ✅ Neo4j connectivity confirmed

---

### Stage 2: Local Container Tests (Docker Build)
Test the containerized service locally using Docker Compose.

**Prerequisites:**
- Docker and Docker Compose installed
- `.env` file configured with all required variables
- Neo4j container running

**Tests:**
1. **Build Container**
   ```bash
   cd services/graphrag-orchestration
   docker build -t graphrag-orchestration:test .
   ```

2. **Start Services**
   ```bash
   docker-compose up -d
   ```

3. **Health Check**
   ```bash
   curl http://localhost:8001/health
   curl http://localhost:8001/api/v1/graphrag/health
   ```

4. **Basic Endpoint Test**
   ```bash
   python test_graphrag_indexing.py
   ```

5. **CU Ingestion Test**
   ```bash
   python test_cu_ingestion.py
   ```

**Expected Outcomes:**
- ✅ Container builds successfully
- ✅ All services report healthy
- ✅ API endpoints respond correctly
- ✅ CU Standard ingestion works
- ✅ Neo4j shows expected nodes/relationships

**Verification Commands:**
```bash
# Check Neo4j data
docker exec -it neo4j cypher-shell -u neo4j -p password
MATCH (n) WHERE n.group_id = 'test-group-123' RETURN count(n);

# Check container logs
docker logs graphrag-orchestration

# Check Neo4j logs
docker logs neo4j
```

---

### Stage 3: Deployed Container Tests (Azure Container Apps)
Test the deployed container in Azure environment.

**Prerequisites:**
- Service deployed to Azure Container Apps
- Managed identity configured
- Azure resources provisioned (Neo4j, Cosmos DB, etc.)

**Tests:**
1. **Deployment Verification**
   ```bash
   # Get container app URL
   GRAPHRAG_URL=$(az containerapp show \
     --name graphrag-orchestration \
     --resource-group <rg-name> \
     --query properties.configuration.ingress.fqdn -o tsv)
   
   echo "Service URL: https://$GRAPHRAG_URL"
   ```

2. **Health Check**
   ```bash
   curl https://$GRAPHRAG_URL/health
   curl https://$GRAPHRAG_URL/api/v1/graphrag/health
   ```

3. **Managed Identity Test**
   ```bash
   # Test with Azure AD token
   TOKEN=$(az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv)
   
   curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
     -H "Authorization: Bearer $TOKEN" \
     -H "X-Group-ID: test-group-123" \
     -H "Content-Type: application/json" \
     -d @test_payload.json
   ```

4. **Remote CU Ingestion Test**
   ```bash
   # Update test script to use deployed URL
   GRAPHRAG_URL="https://$GRAPHRAG_URL" python test_cu_ingestion.py
   ```

**Expected Outcomes:**
- ✅ Container app is running
- ✅ Managed identity auth works
- ✅ CU Standard calls succeed
- ✅ Azure OpenAI integration works
- ✅ Data persists in Azure Neo4j/Cosmos

**Debugging Commands:**
```bash
# Check container logs
az containerapp logs show \
  --name graphrag-orchestration \
  --resource-group <rg-name> \
  --follow

# Check environment variables
az containerapp show \
  --name graphrag-orchestration \
  --resource-group <rg-name> \
  --query properties.template.containers[0].env
```

---

### Stage 4: End-to-End Integration Tests
Test complete workflows across all services.

**Prerequisites:**
- All services deployed and healthy
- Test data prepared (schemas, documents)
- Frontend application connected

**Test Scenarios:**

#### 4.1 Schema-Based Extraction Workflow
```bash
# 1. Upload schema to Schema Vault (via ContentProcessorAPI)
curl -X POST "https://<content-api>/api/schemavault/schemas" \
  -H "X-Group-ID: test-group-123" \
  -F "file=@test_schema.json" \
  -F "name=TestSchema"

# 2. Index documents using schema
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-schema" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_id": "<schema-id>",
    "documents": [{"url": "<blob-sas-url>"}],
    "ingestion": "cu-standard",
    "run_community_detection": true
  }'

# 3. Wait for indexing to complete (check status)

# 4. Query graph
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/query/local" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What entities are mentioned?",
    "top_k": 10
  }'
```

#### 4.2 Prompt-Based Quick Query
```bash
# 1. Upload document to blob storage
# (via ContentProcessorAPI or direct)

# 2. Run quick query with prompt
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_prompt": "Extract key people, organizations, and their relationships",
    "documents": [{"url": "<blob-sas-url>"}],
    "ingestion": "cu-standard",
    "run_community_detection": false
  }'

# 3. Query results
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/query/hybrid" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Who are the key people mentioned?",
    "top_k": 5
  }'
```

#### 4.3 Multi-Tenant Isolation Test
```bash
# Upload to different groups
for GROUP in group-finance group-legal group-hr; do
  curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
    -H "X-Group-ID: $GROUP" \
    -H "Content-Type: application/json" \
    -d "{
      \"schema_prompt\": \"Extract entities\",
      \"documents\": [\"Test document for $GROUP\"],
      \"run_community_detection\": false
    }"
done

# Verify isolation - each group sees only its data
for GROUP in group-finance group-legal group-hr; do
  echo "Testing $GROUP..."
  curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/query/local" \
    -H "X-Group-ID: $GROUP" \
    -H "Content-Type: application/json" \
    -d '{"query": "What data exists?", "top_k": 10}'
done
```

#### 4.4 Community Detection & Global Search
```bash
# 1. Index multiple documents
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_prompt": "Extract entities and relationships",
    "documents": [
      "Document 1 about topic A...",
      "Document 2 about topic B...",
      "Document 3 about topic C..."
    ],
    "run_community_detection": true
  }'

# 2. Wait for community detection to complete

# 3. Global search query
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/query/global" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the main themes?",
    "community_level": 0,
    "top_k": 5
  }'
```

**Expected Outcomes:**
- ✅ Schema Vault integration works end-to-end
- ✅ CU Standard extracts text from various formats
- ✅ GraphRAG indexes and creates knowledge graph
- ✅ Multi-tenant isolation is enforced
- ✅ Community detection produces summaries
- ✅ All query modes return relevant results
- ✅ No data leaks between groups

---

## Performance Tests

### Load Test
```bash
# Use Apache Bench or similar
ab -n 100 -c 10 \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -p test_payload.json \
  "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt"
```

### Large Document Test
```bash
# Test with 50MB PDF
curl -X POST "https://$GRAPHRAG_URL/api/v1/graphrag/index-from-prompt" \
  -H "X-Group-ID: test-group-123" \
  -H "Content-Type: application/json" \
  -d '{
    "schema_prompt": "Extract all entities",
    "documents": [{"url": "<large-pdf-blob-url>"}],
    "ingestion": "cu-standard"
  }'
```

---

## Rollback Plan

If any stage fails:

1. **Stage 1 Failure**: Fix code, re-run unit tests
2. **Stage 2 Failure**: Check Docker configuration, rebuild
3. **Stage 3 Failure**: Review Azure deployment, check managed identity
4. **Stage 4 Failure**: Investigate service integration, check logs

**Quick Rollback:**
```bash
# Rollback Azure Container App
az containerapp revision list \
  --name graphrag-orchestration \
  --resource-group <rg-name>

az containerapp revision activate \
  --name graphrag-orchestration \
  --resource-group <rg-name> \
  --revision <previous-revision-name>
```

---

## Success Criteria

### Stage 1 (Local Components)
- [ ] All unit tests pass
- [ ] Schema converter handles all test cases
- [ ] Azure services accessible
- [ ] Neo4j connectivity confirmed

### Stage 2 (Local Container)
- [ ] Docker build succeeds
- [ ] Health endpoints return 200
- [ ] Sample indexing completes
- [ ] Neo4j contains expected data

### Stage 3 (Deployed Container)
- [ ] Container app is healthy
- [ ] Managed identity works
- [ ] Remote endpoints accessible
- [ ] Azure integrations work

### Stage 4 (Integration)
- [ ] End-to-end workflows complete
- [ ] Multi-tenancy enforced
- [ ] Query modes return results
- [ ] Performance acceptable

---

## Next Steps

Run tests in order:
```bash
# Stage 1
./run_local_tests.sh

# Stage 2
./run_container_tests.sh

# Stage 3
./run_deployed_tests.sh

# Stage 4
./run_integration_tests.sh
```
