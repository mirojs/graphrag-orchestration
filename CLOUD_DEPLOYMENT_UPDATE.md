# Cloud Deployment Update for Hybrid Pipeline

**Date:** December 30, 2025  
**Purpose:** Enable gpt-4o-mini and gpt-4o deployments for hybrid pipeline in Azure

---

## Changes Required

### 1. Azure OpenAI Model Deployments

**File:** `infra/core/ai/openai-models.bicep`

**Added Models:**
- ✅ **gpt-4o-mini** - Hybrid Router Classification (fast, low-cost)
- ✅ **gpt-4o** - Hybrid NER & Intermediate Processing

**Updated Bicep:**
```bicep
// GPT-4o-mini - Hybrid Router Classification
resource gpt4oMiniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-4o-mini'
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: '2024-07-18'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt52Deployment]
}

// GPT-4o - Hybrid NER & Intermediate Processing
resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: openAiAccount
  name: 'gpt-4o'
  sku: {
    name: 'GlobalStandard'
    capacity: 50
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: '2024-11-20'
    }
    raiPolicyName: 'Microsoft.DefaultV2'
  }
  dependsOn: [gpt4oMiniDeployment]
}
```

### 2. Model Mapping (Already Configured)

**File:** `graphrag-orchestration/app/core/config.py`

Current configuration already uses the correct model names:
```python
HYBRID_ROUTER_MODEL: str = "gpt-4o-mini"           # ✅ Ready
HYBRID_NER_MODEL: str = "gpt-4o"                   # ✅ Ready
HYBRID_SYNTHESIS_MODEL: str = "gpt-5-2"            # ✅ Already deployed
HYBRID_DECOMPOSITION_MODEL: str = "gpt-4.1"        # ✅ Already deployed
HYBRID_INTERMEDIATE_MODEL: str = "gpt-4o"          # ✅ Ready
```

---

## Deployment Steps

### Step 1: Deploy Updated Infrastructure

```bash
# Navigate to project root
cd /afh/projects/graphrag-orchestration

# Deploy infrastructure with new models
azd up
```

This will:
- Create gpt-4o-mini deployment in Sweden Central
- Create gpt-4o deployment in Sweden Central
- Maintain existing deployments (gpt-4.1, o4-mini, o3-pro, gpt-5-2)

### Step 2: Deploy Application

```bash
# Deploy the application container
./deploy-graphrag.sh
```

The deployment script will:
- Build Docker image with latest code (includes aquery fix)
- Push to Azure Container Registry
- Update Container App with new image
- Configure environment variables

### Step 3: Verify Deployment

```bash
# Run cloud deployment tests
./test_cloud_deployment.sh <CONTAINER_APP_FQDN>

# Or get FQDN and test manually
FQDN=$(az containerapp show -n graphrag-orchestration -g rg-graphrag-feature --query properties.configuration.ingress.fqdn -o tsv)

# Test health
curl https://$FQDN/health

# Test hybrid pipeline
curl -H "X-Group-ID: test" https://$FQDN/hybrid/health
```

---

## Expected Model Costs

| Model | TPM Quota | $/1M Input | $/1M Output | Use Case |
|-------|-----------|------------|-------------|----------|
| gpt-4o-mini | 50K | $0.15 | $0.60 | Router (20-50 queries/min) |
| gpt-4o | 50K | $2.50 | $10.00 | NER + Intermediate (10-30/min) |
| gpt-4.1 | 50K | $3.00 | $12.00 | Decomposition (5-10/min) |
| gpt-5-2 | 100K | $5.00 | $15.00 | Synthesis (5-15/min) |

**Estimated monthly cost** (moderate usage - 10K queries/month):
- Router (gpt-4o-mini): ~$5/month ✅ Very low
- NER (gpt-4o): ~$50/month
- Synthesis (gpt-5-2): ~$200/month
- **Total: ~$255/month** (vs ~$1000/month without smart routing)

---

## Post-Deployment Checklist

### ✅ Immediate Verification

- [ ] Health endpoint returns 200 OK
- [ ] Hybrid pipeline health shows all components "ok"
- [ ] All 4 routes available (check `/hybrid/health`)
- [ ] Multi-tenancy enforced (401 without X-Group-ID header)
- [ ] Router model is gpt-4o-mini (check logs)

### ✅ Functional Testing

- [ ] Test simple query (Route 1 → Route 2 fallback)
- [ ] Test entity query (Route 2 - Local Search)
- [ ] Test global query (Route 3 - Global Search)
- [ ] Test ambiguous query (Route 4 - DRIFT)
- [ ] Verify PPR trace working (no aquery errors)

### ✅ Integration Testing

- [ ] Index sample documents via V3 endpoint
- [ ] Sync HippoRAG index
- [ ] Test queries with real data
- [ ] Verify evidence paths returned
- [ ] Check citation accuracy

---

## Verification Commands

### 1. Check Azure OpenAI Deployments

```bash
# List all deployments
az cognitiveservices account deployment list \
  --name <your-openai-account> \
  --resource-group <your-rg> \
  --query "[].{name:name, model:properties.model.name, status:properties.provisioningState}" \
  --output table

# Expected output should include:
# gpt-4o-mini    gpt-4o-mini    Succeeded
# gpt-4o         gpt-4o         Succeeded
# gpt-4.1        gpt-4.1        Succeeded
# gpt-5-2        gpt-5.2        Succeeded
# o4-mini        o4-mini        Succeeded
```

### 2. Test Hybrid Pipeline Endpoints

```bash
FQDN="<your-container-app-fqdn>"

# Test 1: Health Check
curl -s https://$FQDN/health | jq .

# Test 2: Hybrid Health
curl -s -H "X-Group-ID: test" https://$FQDN/hybrid/health | jq .

# Test 3: Available Profiles
curl -s -H "X-Group-ID: test" https://$FQDN/hybrid/profiles | jq .

# Test 4: Sample Query
curl -s -X POST https://$FQDN/hybrid/query \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test" \
  -d '{"query": "What are the requirements?"}' | jq .
```

### 3. Check Application Logs

```bash
# Follow logs in real-time
az containerapp logs show \
  -n graphrag-orchestration \
  -g rg-graphrag-feature \
  --follow

# Look for these log entries:
# ✅ "llm_service_initialized" with model: "gpt-5-2"
# ✅ "router_initialized" (uses gpt-4o-mini internally)
# ✅ "hybrid_pipeline_initialized" with all components
# ✅ No "neo4j_ppr_trace_failed" errors (aquery fix verified)
```

---

## Troubleshooting

### Issue: Model Deployment Failed

**Symptom:** `azd up` fails with "Insufficient quota" or "Model not available"

**Solution:**
1. Check model availability in Sweden Central:
   ```bash
   az cognitiveservices account list-models \
     --location swedencentral \
     --resource-type Microsoft.CognitiveServices/accounts \
     --query "[?name=='gpt-4o-mini'].name"
   ```

2. Request quota increase in Azure Portal:
   - Navigate to Azure OpenAI resource
   - Go to "Quotas" → "Request quota"
   - Select model and region
   - Request at least 50K TPM

### Issue: Container App Not Starting

**Symptom:** Container app in "Provisioning" state or crashing

**Solution:**
1. Check logs:
   ```bash
   az containerapp logs show -n graphrag-orchestration -g rg-graphrag-feature --tail 100
   ```

2. Verify environment variables:
   ```bash
   az containerapp show -n graphrag-orchestration -g rg-graphrag-feature \
     --query "properties.template.containers[0].env" -o table
   ```

3. Ensure managed identity has permissions:
   - Cognitive Services OpenAI User role
   - Container Registry pull role

### Issue: Hybrid Pipeline Returns Errors

**Symptom:** Queries return 500 errors or "model not found"

**Solution:**
1. Verify model deployment names match config:
   - Config expects: `gpt-4o-mini`, `gpt-4o`, `gpt-5-2`, `gpt-4.1`
   - Bicep deploys: same names
   
2. Check Azure OpenAI endpoint in config:
   ```bash
   az containerapp show -n graphrag-orchestration -g rg-graphrag-feature \
     --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_ENDPOINT'].value" -o tsv
   ```

3. Test Azure OpenAI directly:
   ```bash
   curl https://<your-endpoint>.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21 \
     -H "api-key: $AZURE_OPENAI_API_KEY" \
     -H "Content-Type: application/json" \
     -d '{"messages":[{"role":"user","content":"test"}]}'
   ```

---

## Rollback Plan

If deployment fails, rollback to previous version:

```bash
# Get previous revision
PREVIOUS_REVISION=$(az containerapp revision list \
  -n graphrag-orchestration \
  -g rg-graphrag-feature \
  --query "[1].name" -o tsv)

# Activate previous revision
az containerapp revision activate \
  -n graphrag-orchestration \
  -g rg-graphrag-feature \
  --revision $PREVIOUS_REVISION

# Set 100% traffic to previous
az containerapp ingress traffic set \
  -n graphrag-orchestration \
  -g rg-graphrag-feature \
  --revision-weight $PREVIOUS_REVISION=100
```

---

## Summary

**Changes Made:**
- ✅ Added gpt-4o-mini deployment to bicep (router classification)
- ✅ Added gpt-4o deployment to bicep (NER + intermediate)
- ✅ Fixed aquery bug in MultiTenantNeo4jStore
- ✅ All tests passing (101/101)
- ✅ Deployment script ready

**Ready to Deploy:**
```bash
# 1. Deploy infrastructure
azd up

# 2. Deploy application
./deploy-graphrag.sh

# 3. Test deployment
./test_cloud_deployment.sh <FQDN>
```

**Expected Result:**
- All 4 routes operational
- Route 1 → Route 2 fallback working
- gpt-4o-mini handling router classification (fast, cheap)
- gpt-4o handling NER (high precision)
- No aquery errors in logs
