# Bicep Infrastructure Update - Based on Debugging

## Changes Made

### 1. main.bicep - Core Infrastructure Configuration

#### Added Document Intelligence Endpoint Parameter
- Added `azureDocumentIntelligenceEndpoint` parameter with default value
- Included in container app environment variables for managed identity authentication

#### Updated Resource Group Reference
- Changed from creating new resource group to referencing existing `rg-graphrag-feature`
- Uses `existing` keyword to prevent recreation

#### Updated Container Registry Reference  
- Changed from module creating new ACR to direct reference of existing `graphragacr12153`
- Uses `existing` keyword with proper scope

#### Fixed Container App Name
- Changed from generated name to fixed `graphrag-orchestration` for consistency

#### Added Missing Environment Variables
- `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT`: Required for Document Intelligence SDK integration

### 2. role-assignments.bicep - Already Correct

The role assignments module was already properly configured with:
- **Cognitive Services User** role for Document Intelligence access
- **Storage Blob Data Reader** role for private blob access  
- **AcrPull** role for container image pulls

All three role assignments use:
- Proper role definition IDs
- Container app managed identity principal ID
- `ServicePrincipal` principal type
- Correct scoping to respective resources

### 3. container-app.bicep - Already Correct

The container app bicep already:
- Exports `identityPrincipalId` output for role assignments
- Configures system-assigned managed identity
- Configures registry authentication using managed identity (`identity: 'system'`)

## What These Changes Fix

### Before (Manual Steps Required)
1. Container app created in wrong location/resource group
2. Had to manually add `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` environment variable
3. Had to manually grant three role assignments:
   - Cognitive Services User on doc-intel-graphrag
   - Storage Blob Data Reader on neo4jstorage21224
   - AcrPull on graphragacr12153

### After (Automated)
1. Container app created in correct `rg-graphrag-feature` (Sweden Central)
2. Document Intelligence endpoint automatically configured
3. All three role assignments automatically granted via bicep module
4. Uses existing resources (ACR, storage, Document Intelligence) instead of creating new ones

## Key Infrastructure Resources

| Resource | Name | Location | Purpose |
|----------|------|----------|---------|
| Resource Group | rg-graphrag-feature | Sweden Central | Main resource group |
| Container Registry | graphragacr12153 | Sweden Central | Docker images |
| Container App | graphrag-orchestration | Sweden Central | GraphRAG V3 service |
| Document Intelligence | doc-intel-graphrag | Sweden Central | Text extraction from PDFs |
| Storage Account | neo4jstorage21224 | Sweden Central | Private blob storage |
| Neo4j | a86dcf63.databases.neo4j.io | Azure Aura | Graph database |

## Deployment Command

```bash
cd graphrag-orchestration
azd up
```

The role assignments will automatically be created during deployment, granting the container app's managed identity access to all required resources.

## Role Assignment Details

### Cognitive Services User (a97b65f3-24c7-4388-baec-2e87135dc908)
- **Scope**: doc-intel-graphrag
- **Purpose**: Call Document Intelligence API to analyze PDFs
- **SDK Usage**: `DocumentAnalysisClient` with `DefaultAzureCredential()`

### Storage Blob Data Reader (2a2b9908-6b1a-4c93-abf7-d80eab967e7d)  
- **Scope**: neo4jstorage21224
- **Purpose**: Download private blobs before sending to Document Intelligence
- **SDK Usage**: `BlobClient.from_blob_url()` with `DefaultAzureCredential()`

### AcrPull (7f951dda-4ed3-4680-a7ca-43fe172d538d)
- **Scope**: graphragacr12153
- **Purpose**: Pull container images during deployment
- **Configuration**: Set in container app registries config with `identity: 'system'`

## Testing the Deployment

After deployment, verify permissions:

```bash
# Check container app is running
az containerapp show --name graphrag-orchestration --resource-group rg-graphrag-feature --query "properties.provisioningState"

# Check managed identity
az containerapp show --name graphrag-orchestration --resource-group rg-graphrag-feature --query "identity.principalId" -o tsv

# Test Document Intelligence with 5 PDFs
curl -X POST "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io/graphrag/v3/index" \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-deployment-$(date +%s)" \
  -d '{
    "document_urls": [
      "https://neo4jstorage21224.blob.core.windows.net/pdfs/sample1.pdf",
      "https://neo4jstorage21224.blob.core.windows.net/pdfs/sample2.pdf",
      "https://neo4jstorage21224.blob.core.windows.net/pdfs/sample3.pdf",
      "https://neo4jstorage21224.blob.core.windows.net/pdfs/sample4.pdf",
      "https://neo4jstorage21224.blob.core.windows.net/pdfs/sample5.pdf"
    ],
    "schema": {
      "entities": ["Person", "Organization", "Contract"],
      "relationships": ["SIGNED_BY", "HAS_OBLIGATION"]
    }
  }'
```

Expected result after 60 seconds:
- 200+ entities extracted
- 200+ relationships created
- Stats endpoint returns correct counts (not 0)

## Debugging Reference

See conversation logs for the debugging process that led to these changes:
1. Fixed SDK usage to pass bytes directly (not wrapped in AnalyzeDocumentRequest)
2. Fixed stats query to count all relationship types (not hardcoded RELATES_TO)
3. Validated Document Intelligence working with 5 PDFs: 237 entities, 204 relationships
