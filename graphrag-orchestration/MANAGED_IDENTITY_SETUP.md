# Managed Identity Configuration

**Status:** ✅ CONFIGURED  
**Date:** December 4, 2025

## Document Intelligence - Managed Identity

### Configuration Applied:

1. **Enabled System-Assigned Managed Identity**
   ```bash
   az containerapp identity assign \
     --name graphrag-orchestration \
     --resource-group rg-graphrag-feature \
     --system-assigned
   ```
   - Principal ID: `66b279df-3c92-45fa-99c1-f875f2796e82`
   - Type: SystemAssigned

2. **Granted Cognitive Services User Role**
   ```bash
   az role assignment create \
     --assignee "66b279df-3c92-45fa-99c1-f875f2796e82" \
     --role "Cognitive Services User" \
     --scope "/subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/rg-graphrag-feature/providers/Microsoft.CognitiveServices/accounts/doc-intel-graphrag"
   ```

3. **Removed API Key from Environment**
   ```bash
   az containerapp update \
     --name graphrag-orchestration \
     --resource-group rg-graphrag-feature \
     --remove-env-vars AZURE_DOCUMENT_INTELLIGENCE_KEY
   ```

### How It Works:

The `DocumentIntelligenceService` automatically uses managed identity when no API key is configured:

```python
async def _create_client(self) -> DocumentIntelligenceClient:
    if self.api_key:
        credential = AzureKeyCredential(self.api_key)
    else:
        credential = DefaultAzureCredential()  # ← Uses managed identity
    
    return DocumentIntelligenceClient(
        endpoint=self.endpoint,
        credential=credential,
        api_version=self.api_version,
    )
```

### Benefits:

- ✅ **More Secure**: No API keys stored in environment variables
- ✅ **Automatic Rotation**: No manual key rotation needed
- ✅ **Azure AD Integration**: Uses Azure RBAC for access control
- ✅ **Audit Trail**: All API calls tracked via managed identity

### Environment Configuration:

**Deployed (Production):**
```bash
# Managed identity requires the resource's custom subdomain endpoint
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://doc-intel-graphrag.cognitiveservices.azure.com/
# No AZURE_DOCUMENT_INTELLIGENCE_KEY - uses managed identity
```

**Local Development:**
```bash
# Option A (recommended): use API key with the regional endpoint
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-region>.api.cognitive.microsoft.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-key-for-local-testing

# Option B: use managed identity, but only with the custom subdomain endpoint
# AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-di-resource-name>.cognitiveservices.azure.com/
# (no key)
```

### Verification:

```bash
# Check managed identity is enabled
az containerapp show --name graphrag-orchestration \
  --resource-group rg-graphrag-feature \
  --query "identity"

# Check role assignment
az role assignment list \
  --assignee "66b279df-3c92-45fa-99c1-f875f2796e82" \
  --scope "/subscriptions/3adfbe7c-9922-40ed-b461-ec798989a3fa/resourceGroups/rg-graphrag-feature/providers/Microsoft.CognitiveServices/accounts/doc-intel-graphrag"

# Test service health
curl -H "X-Group-ID: test" \
  https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io/health
```

### Resources:

- **Container App**: graphrag-orchestration
- **Document Intelligence**: doc-intel-graphrag  
- **Resource Group**: rg-graphrag-feature
- **Subscription**: 3adfbe7c-9922-40ed-b461-ec798989a3fa

### Future: Azure OpenAI Managed Identity

Same pattern can be applied to Azure OpenAI:
1. Enable managed identity (already done ✅)
2. Grant "Cognitive Services OpenAI User" role
3. Remove AZURE_OPENAI_API_KEY from environment
4. LLMService already supports managed identity via bearer token provider
