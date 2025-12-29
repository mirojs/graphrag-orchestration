# GraphRAG Deployment Guide

## Overview

This guide covers deploying the GraphRAG Orchestration service to Azure Container Apps with Document Intelligence support.

## Prerequisites

- Azure CLI installed and logged in
- Docker installed and running
- Access to Azure subscription with permissions to create resources
- (Optional) Azure Developer CLI (`azd`) for environment management

## Quick Start

### Option 1: Automated Deployment (Recommended)

```bash
# Clone and navigate to repository
cd /afh/projects/graphrag-orchestration

# Set required environment variables
export AZURE_RESOURCE_GROUP="rg-graphrag-feature"
export CONTAINER_REGISTRY_NAME="graphragacr12153"
export CONTAINER_APP_NAME="graphrag-orchestration"

# Run deployment
./deploy-graphrag.sh
```

### Option 2: Using Azure Developer CLI (azd)

```bash
# Set environment values in azd
azd env set AZURE_RESOURCE_GROUP "rg-graphrag-feature"
azd env set CONTAINER_REGISTRY_NAME "graphragacr12153"
azd env set CONTAINER_APP_NAME "graphrag-orchestration"

# Run deployment
./deploy-graphrag.sh
```

## Configuration

### Required Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CONTAINER_REGISTRY_NAME` | Azure Container Registry name | *(required)* |
| `AZURE_RESOURCE_GROUP` | Resource group name | `rg-graphrag-feature` |
| `CONTAINER_APP_NAME` | Container App name | `graphrag-orchestration` |

### Optional Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AZURE_LOCATION` | Azure region | `swedencentral` |
| `AZURE_ENV_IMAGETAG` | Docker image tag | `latest` |
| `CONTAINER_APP_USER_IDENTITY_ID` | Managed identity resource ID | *(auto-detect)* |
| `DOCKER_CLEANUP_ENABLED` | Clean Docker resources after deploy | `true` |
| `NEO4J_PASSWORD` | Neo4j admin password | *(auto-detect)* |

## Features

### 🚀 Reliable Deployment Pattern

Based on proven `docker-build.sh` from dev/pro environments:

- **Smart Configuration**: Auto-detects values from azd or environment variables
- **Managed Identity Support**: Uses Azure managed identity for ACR authentication
- **Health Checks**: Validates Neo4j and Container App status post-deployment
- **Docker Cleanup**: Automatic cleanup to free disk space
- **Error Handling**: Comprehensive error checking with clear messages
- **Idempotent**: Safe to run multiple times

### 🔧 What It Does

1. **Authentication**
   - Verifies Azure login
   - Sets active subscription
   - Logs into Azure Container Registry

2. **Build & Push**
   - Builds Docker image with `--no-cache` for clean builds
   - Tags with configurable version
   - Pushes to Azure Container Registry
   - Adds build metadata (date, version)

3. **Container App Update**
   - Configures ACR authentication (managed identity or admin)
   - Updates image to latest build
   - Sets environment variables (including refresh timestamp)
   - Validates successful deployment

4. **Health Validation**
   - Checks Neo4j container status
   - Reports Container App endpoint URL
   - Provides next steps and troubleshooting commands

5. **Cleanup**
   - Removes dangling Docker images
   - Clears build cache
   - Frees disk space (configurable)

## Infrastructure Requirements

### Existing Resources

The deployment script expects these resources to already exist:

1. **Azure Container Apps Environment**
   ```bash
   az containerapp env create \
     --name graphrag-env \
     --resource-group rg-graphrag-feature \
     --location swedencentral
   ```

2. **Container App** (created via bicep or manually)
   ```bash
   az containerapp create \
     --name graphrag-orchestration \
     --resource-group rg-graphrag-feature \
     --environment graphrag-env \
     --image <initial-image> \
     --target-port 8000 \
     --ingress external
   ```

3. **Azure Container Registry**
   ```bash
   az acr create \
     --name graphragacr12153 \
     --resource-group rg-graphrag-feature \
     --sku Basic \
     --admin-enabled true
   ```

4. **Neo4j Container Instance** (optional but recommended)
   - Can be deployed separately using `./graphrag-orchestration/deploy-simple.sh`

### Managed Identity Setup

For Document Intelligence and blob storage access, ensure the Container App has these role assignments:

```bash
# Get Container App principal ID
PRINCIPAL_ID=$(az containerapp show \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --query identity.principalId -o tsv)

# Storage Blob Data Reader (for PDF access)
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Storage Blob Data Reader" \
  --scope /subscriptions/<sub-id>/resourceGroups/rg-graphrag-feature/providers/Microsoft.Storage/storageAccounts/neo4jstorage21224

# Cognitive Services User (for Document Intelligence)
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Cognitive Services User" \
  --scope /subscriptions/<sub-id>/resourceGroups/rg-graphrag-feature/providers/Microsoft.CognitiveServices/accounts/doc-intel-graphrag

# Cognitive Services OpenAI User (for embeddings)
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Cognitive Services OpenAI User" \
  --scope /subscriptions/<sub-id>/resourceGroups/rg-graphrag-feature/providers/Microsoft.CognitiveServices/accounts/graphrag-openai
```

Or use the provided bicep template:
```bash
az deployment group create \
  --resource-group rg-graphrag-feature \
  --template-file infra/core/security/role-assignments.bicep \
  --parameters containerAppPrincipalId=$PRINCIPAL_ID
```

## Post-Deployment Testing

### 1. Health Check

```bash
curl https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/health
```

Expected response:
```json
{
  "status": "healthy",
  "neo4j": "connected",
  "version": "3.0.0"
}
```

### 2. Swagger API Documentation

Open in browser:
```
https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/docs
```

### 3. Test PDF Processing

```bash
# Use the managed identity test (no SAS tokens needed)
python test_managed_identity_pdfs.py
```

Expected output:
```
✅ Successfully downloaded blob content (45231 bytes)
⏳ Starting Document Intelligence analysis (45231 bytes)...
✅ Document Intelligence analysis completed
✅ Indexing completed successfully in 8.5s
```

### 4. View Application Logs

```bash
# Real-time logs
az containerapp logs show \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --follow

# Recent logs
az containerapp logs show \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --tail 100
```

## Troubleshooting

### Image Build Fails

**Error:** `docker build` fails with disk space issues

**Solution:**
```bash
# Manual cleanup before deployment
docker system prune -a -f --volumes

# Or disable automatic cleanup
export DOCKER_CLEANUP_ENABLED=false
./deploy-graphrag.sh
```

### ACR Authentication Issues

**Error:** `unauthorized: authentication required`

**Solution:**
```bash
# Re-authenticate manually
az acr login --name graphragacr12153

# Check ACR admin is enabled
az acr update --name graphragacr12153 --admin-enabled true
```

### Container App Not Found

**Error:** `Container App 'graphrag-orchestration' not found`

**Solution:** Deploy infrastructure first using bicep:
```bash
cd infra
az deployment group create \
  --resource-group rg-graphrag-feature \
  --template-file main.bicep \
  --parameters main.bicepparam
```

### Neo4j Connection Errors

**Error:** Application logs show "Failed to connect to Neo4j"

**Solution:**
```bash
# Check Neo4j status
az container show \
  --name neo4j-graphrag \
  --resource-group rg-graphrag-feature \
  --query instanceView.state -o tsv

# Restart Neo4j if needed
az container restart \
  --name neo4j-graphrag \
  --resource-group rg-graphrag-feature
```

### Document Intelligence Timeouts

**Error:** 504 Gateway Timeout when processing PDFs

**Solution:** Verify the fix is deployed:
```bash
# Check image tag
az containerapp show \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --query "properties.template.containers[0].image" -o tsv

# Should show image with recent timestamp
# If not, re-run deployment:
./deploy-graphrag.sh
```

## Environment Variables in Container App

The deployment sets these environment variables automatically:

- `REFRESH_TIMESTAMP`: Deployment timestamp (forces container restart)
- `NEO4J_URI`: Neo4j connection string
- `NEO4J_PASSWORD`: Neo4j authentication
- `AZURE_OPENAI_ENDPOINT`: Azure OpenAI endpoint
- `AZURE_OPENAI_API_KEY`: *(empty - uses managed identity)*
- `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`: Document Intelligence endpoint
- `AZURE_DOCUMENT_INTELLIGENCE_KEY`: *(empty - uses managed identity)*

## Rollback

To rollback to a previous image:

```bash
# List available images
az acr repository show-tags \
  --name graphragacr12153 \
  --repository graphrag-orchestration \
  --orderby time_desc

# Update to specific tag
az containerapp update \
  --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --image graphragacr12153.azurecr.io/graphrag-orchestration:<tag>
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Deploy GraphRAG

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Azure Login
        uses: azure/login@v1
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      
      - name: Deploy
        run: |
          export CONTAINER_REGISTRY_NAME=graphragacr12153
          export AZURE_RESOURCE_GROUP=rg-graphrag-feature
          ./deploy-graphrag.sh
```

### Azure DevOps Pipeline

```yaml
trigger:
  branches:
    include:
      - main

pool:
  vmImage: 'ubuntu-latest'

steps:
  - task: AzureCLI@2
    inputs:
      azureSubscription: 'Azure-ServiceConnection'
      scriptType: 'bash'
      scriptLocation: 'scriptPath'
      scriptPath: 'deploy-graphrag.sh'
    env:
      CONTAINER_REGISTRY_NAME: graphragacr12153
      AZURE_RESOURCE_GROUP: rg-graphrag-feature
```

## Comparison with Original Scripts

### deploy-graphrag.sh vs deploy-simple.sh

| Feature | deploy-graphrag.sh | deploy-simple.sh |
|---------|-------------------|------------------|
| Configuration | azd + env vars | Hardcoded |
| Managed Identity | ✅ Yes | ❌ No (admin creds) |
| Docker Cleanup | ✅ Configurable | ⚠️ Manual only |
| Health Checks | ✅ Comprehensive | ⚠️ Basic |
| Error Handling | ✅ Detailed | ⚠️ Limited |
| Neo4j Deployment | ❌ Separate step | ✅ Included |
| Build Metadata | ✅ Date/version tags | ❌ None |

**Recommendation:** Use `deploy-graphrag.sh` for Container App updates, and `deploy-simple.sh` for initial Neo4j setup.

## Best Practices

1. **Use Managed Identity** - More secure than admin credentials
2. **Tag Images Properly** - Use semantic versioning or timestamps
3. **Test Locally First** - Verify Docker build works before deploying
4. **Monitor Logs** - Check application logs after deployment
5. **Validate Health** - Always run health checks post-deployment
6. **Keep Secrets Secure** - Never commit passwords or API keys
7. **Document Changes** - Update version tags and commit messages

## Additional Resources

- [Azure Container Apps Documentation](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Document Intelligence Fix Details](V3_DOCUMENT_INTELLIGENCE_HANG_FIX_COMPLETE.md)
- [GraphRAG API Documentation](https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/docs)
- [Neo4j Docker Documentation](https://neo4j.com/docs/operations-manual/current/docker/)

## Support

For issues or questions:
1. Check application logs: `az containerapp logs show ...`
2. Review health endpoint: `curl https://.../health`
3. Verify infrastructure: Check Azure Portal for resource status
4. Test Document Intelligence: Run `test_managed_identity_pdfs.py`
