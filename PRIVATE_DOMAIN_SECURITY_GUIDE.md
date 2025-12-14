# Private Domain/Network Security Configuration Guide

## Overview

If you're using **private domains** (Azure Private Endpoints, VNet integration, or private DNS zones) for security, you need to make specific configuration changes for user authentication and data isolation.

## Current Architecture Support

The Microsoft Content Processing Solution Accelerator **already supports private networking** through the `enablePrivateNetworking` parameter. When enabled, it deploys:

✅ **Virtual Network (VNet)** with segmented subnets  
✅ **Private Endpoints** for all Azure resources  
✅ **Private DNS Zones** for name resolution  
✅ **Network Security Groups (NSGs)** for traffic control  
✅ **Disabled public network access** for resources

## What Changes When Using Private Networks

### 1. **JWT Token Validation (CRITICAL)**

When using private domains, Azure AD's public JWKS (JSON Web Key Set) endpoints may not be accessible from your private network. You need to configure proper connectivity.

#### Problem
Your backend API needs to validate JWT tokens by fetching Azure AD's public keys from:
```
https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys
```

If this endpoint isn't accessible due to private networking, token validation fails.

#### Solution Options

**Option A: Allow Azure AD Endpoints (Recommended)**

Add Azure AD endpoints to your NSG or firewall allow list:

```bicep
// In your NSG or firewall rules
securityRules: [
  {
    name: 'AllowAzureADOutbound'
    properties: {
      access: 'Allow'
      direction: 'Outbound'
      priority: 100
      protocol: 'Tcp'
      sourceAddressPrefix: 'VirtualNetwork'
      sourcePortRange: '*'
      destinationAddressPrefix: 'AzureActiveDirectory'
      destinationPortRange: '443'
    }
  }
]
```

**Option B: Use Service Endpoints**

Enable Azure AD service endpoints on your VNet subnets:

```bicep
subnets: [
  {
    name: 'snet-backend'
    addressPrefix: '10.0.0.0/24'
    serviceEndpoints: [
      {
        service: 'Microsoft.AzureActiveDirectory'
      }
    ]
  }
]
```

**Option C: Cache JWKS Keys Locally**

Implement a JWKS caching mechanism in your FastAPI app:

```python
# app/auth/jwks_cache.py
import requests
from jose import jwk
from datetime import datetime, timedelta
import os

class JWKSCache:
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.jwks_uri = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        self.keys = None
        self.last_fetch = None
        self.cache_duration = timedelta(hours=24)
    
    def get_keys(self):
        """Get JWKS keys, fetching from Azure AD if cache is stale"""
        if self._cache_is_valid():
            return self.keys
        
        try:
            response = requests.get(self.jwks_uri, timeout=10)
            response.raise_for_status()
            self.keys = response.json()['keys']
            self.last_fetch = datetime.utcnow()
            return self.keys
        except Exception as e:
            if self.keys:  # Use stale cache if fetch fails
                return self.keys
            raise Exception(f"Cannot fetch JWKS keys: {str(e)}")
    
    def _cache_is_valid(self):
        if not self.keys or not self.last_fetch:
            return False
        return datetime.utcnow() - self.last_fetch < self.cache_duration

# Global cache instance
jwks_cache = JWKSCache(os.getenv("AZURE_AD_TENANT_ID"))
```

### 2. **Private Endpoint Configuration for Your Services**

The solution already configures private endpoints when `enablePrivateNetworking=true`. However, you need to ensure all services can communicate:

#### Current Private Endpoint Configuration (from main.bicep)

```bicep
// These are automatically created when enablePrivateNetworking=true:
- Storage Account (Blob, Queue, File)
- Cosmos DB (MongoDB)
- Azure AI Services (OpenAI, Content Understanding)
- App Configuration
- Key Vault
- Container Registry
```

#### What You Need to Verify

1. **Container Apps can access Azure AD**
   - Container Apps Environment must allow outbound to Azure AD
   - Check: `publicNetworkAccess: 'Enabled'` on Container App Environment (line 1189 in main.bicep)

2. **Frontend can reach Azure AD for MSAL**
   - Your React app (running in users' browsers) needs public access to Azure AD
   - Azure AD endpoints (`login.microsoftonline.com`) must be accessible

### 3. **MSAL Configuration (Frontend)**

When using private domains, your **frontend React app** still needs to communicate with Azure AD for login. This is **browser-based** traffic, not server-side.

#### No Changes Needed for MSAL (Usually)

MSAL runs in the **user's browser**, which typically has public internet access. Users authenticate through Azure AD's public login page, then your app gets tokens.

**If you have restricted browser access** (e.g., corporate network with firewall):

Add these domains to your firewall allow list:
```
login.microsoftonline.com
login.microsoft.com
graph.microsoft.com
*.windows.net
```

### 4. **API Communication Flow with Private Endpoints**

```
┌─────────────────┐
│   User Browser  │
│   (Public Net)  │
└────────┬────────┘
         │ MSAL Auth (HTTPS)
         ▼
┌─────────────────────────┐
│ Azure AD (Public)       │
│ login.microsoftonline.. │
└────────┬────────────────┘
         │ JWT Token
         ▼
┌─────────────────┐
│  React Web App  │
│  (Container)    │
└────────┬────────┘
         │ API Call + JWT (HTTPS)
         ▼
┌──────────────────────────────┐
│  FastAPI Backend             │
│  (Private VNet)              │
│  - Validate JWT ← needs AAD  │
│  - Extract user_id           │
└────────┬─────────────────────┘
         │ Private Endpoint
         ▼
┌──────────────────────────────┐
│  Azure Resources             │
│  (All Private Endpoints)     │
│  - Cosmos DB                 │
│  - Storage                   │
│  - AI Services               │
└──────────────────────────────┘
```

### 5. **DNS Resolution in Private Networks**

When using private endpoints, Azure creates Private DNS Zones. The solution already configures these:

```bicep
// Automatically created when enablePrivateNetworking=true:
- privatelink.cognitiveservices.azure.com
- privatelink.openai.azure.com
- privatelink.blob.core.windows.net
- privatelink.queue.core.windows.net
- privatelink.mongo.cosmos.azure.com
- privatelink.azconfig.io
- privatelink.vaultcore.azure.net
```

#### What You Need to Ensure

1. **VNet Links**: Private DNS zones are linked to your VNet (already done in the template)
2. **DNS Settings**: Container Apps use Azure-provided DNS (automatic)
3. **Custom DNS**: If you use custom DNS servers, configure them to forward Azure Private DNS queries

### 6. **User Context Extraction with Private Endpoints**

**No changes required** for user context extraction! The JWT token validation and claim extraction work the same way, regardless of whether you use public or private endpoints.

The only requirement is that your backend can reach Azure AD's JWKS endpoint (see Solution Options in #1 above).

### 7. **Network Security Group (NSG) Rules**

When using private networking, ensure your NSGs allow necessary traffic:

#### Required Outbound Rules for FastAPI Backend

```bicep
securityRules: [
  // Allow outbound to Azure AD for JWT validation
  {
    name: 'AllowAzureADOutbound'
    properties: {
      access: 'Allow'
      direction: 'Outbound'
      priority: 100
      protocol: 'Tcp'
      sourceAddressPrefix: 'VirtualNetwork'
      destinationAddressPrefix: 'AzureActiveDirectory'
      destinationPortRange: '443'
    }
  }
  // Allow outbound to Azure services via private endpoints
  {
    name: 'AllowAzureServicesOutbound'
    properties: {
      access: 'Allow'
      direction: 'Outbound'
      priority: 110
      protocol: '*'
      sourceAddressPrefix: 'VirtualNetwork'
      destinationAddressPrefix: 'VirtualNetwork'
      destinationPortRange: '*'
    }
  }
  // Deny other outbound (optional, for strictest security)
  {
    name: 'DenyAllOtherOutbound'
    properties: {
      access: 'Deny'
      direction: 'Outbound'
      priority: 4096
      protocol: '*'
      sourceAddressPrefix: '*'
      destinationAddressPrefix: '*'
      destinationPortRange: '*'
    }
  }
]
```

## Deployment Steps for Private Networking

### 1. Enable Private Networking in Bicep

```bash
# When deploying with azd
azd env set ENABLE_PRIVATE_NETWORKING true
azd up
```

Or directly in your `main.bicep`:

```bicep
@description('Optional. Enable WAF for the deployment.')
param enablePrivateNetworking bool = true  // Set to true
```

### 2. Verify Private Endpoint Creation

After deployment, verify private endpoints are created:

```bash
az network private-endpoint list \
  --resource-group <your-rg> \
  --output table
```

Expected output:
```
Name                                    ResourceGroup    ProvisioningState
--------------------------------------  ---------------  -------------------
storage-private-endpoint-blob-...       rg-cps-...       Succeeded
storage-private-endpoint-queue-...      rg-cps-...       Succeeded
cosmosdb-private-endpoint-...           rg-cps-...       Succeeded
ai-services-private-endpoint-...        rg-cps-...       Succeeded
appconfig-private-endpoint-...          rg-cps-...       Succeeded
```

### 3. Configure Authentication (Backend)

Update your FastAPI authentication to handle private networking:

```python
# app/auth/dependencies.py
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi_azure_auth import SingleTenantAzureAuthorizationCodeBearer

security = HTTPBearer()

# Option 1: Use fastapi-azure-auth (handles JWKS caching)
azure_scheme = SingleTenantAzureAuthorizationCodeBearer(
    app_client_id=os.getenv("AZURE_AD_CLIENT_ID"),
    tenant_id=os.getenv("AZURE_AD_TENANT_ID"),
    scopes={
        f"api://{os.getenv('AZURE_AD_CLIENT_ID')}/user_impersonation": "Access API",
    },
    # Important: Configure JWKS caching for private networks
    jwks_uri_cache_ttl=86400,  # Cache for 24 hours
    validate_iss=True,
    validate_aud=True,
)

class UserContext:
    def __init__(self, user_id: str, email: str, name: str, tenant_id: str):
        self.user_id = user_id
        self.email = email
        self.name = name
        self.tenant_id = tenant_id

async def get_current_user(
    token: dict = Depends(azure_scheme)
) -> UserContext:
    """Extract user context from validated Azure AD token"""
    return UserContext(
        user_id=token.get("oid"),
        email=token.get("preferred_username") or token.get("upn"),
        name=token.get("name"),
        tenant_id=token.get("tid")
    )
```

### 4. Test Private Connectivity

Create a simple test endpoint:

```python
# app/routers/health.py
from fastapi import APIRouter, Depends
from app.auth.dependencies import get_current_user, UserContext

router = APIRouter(prefix="/health", tags=["health"])

@router.get("/private-network-test")
async def test_private_network(
    current_user: UserContext = Depends(get_current_user)
):
    """
    Test that:
    1. JWT validation works (can reach Azure AD)
    2. User context extraction works
    3. Private endpoint connectivity works
    """
    return {
        "status": "ok",
        "user_id": current_user.user_id,
        "email": current_user.email,
        "network": "private",
        "message": "Authentication and private networking are working correctly"
    }
```

Test it:

```bash
# Get a token from your frontend
TOKEN="<your-jwt-token>"

# Call the test endpoint
curl -X GET "https://<your-api-endpoint>/health/private-network-test" \
  -H "Authorization: Bearer $TOKEN"
```

Expected response:
```json
{
  "status": "ok",
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "email": "user@example.com",
  "network": "private",
  "message": "Authentication and private networking are working correctly"
}
```

## Common Issues and Solutions

### Issue 1: "Cannot fetch JWKS keys"

**Cause**: Backend cannot reach Azure AD's JWKS endpoint

**Solution**:
1. Check NSG rules allow outbound to `AzureActiveDirectory` service tag
2. Verify Container App Environment has `publicNetworkAccess: 'Enabled'`
3. Implement JWKS caching (see Option C in #1)

### Issue 2: "MSAL login fails in browser"

**Cause**: Browser cannot reach Azure AD

**Solution**:
- This should not happen with standard deployments
- MSAL runs in user's browser, which typically has internet access
- If corporate firewall blocks it, add `login.microsoftonline.com` to allow list

### Issue 3: "Private endpoint not resolving"

**Cause**: DNS not correctly configured for private endpoints

**Solution**:
1. Verify Private DNS Zone is linked to VNet:
```bash
az network private-dns link vnet list \
  --resource-group <rg> \
  --zone-name privatelink.blob.core.windows.net
```

2. Test DNS resolution from within VNet:
```bash
# From a VM or Container in the VNet
nslookup <storage-account>.blob.core.windows.net
# Should resolve to 10.0.x.x (private IP), not public IP
```

## Architecture Diagram: Private Network + Authentication

```
                    Internet/Public Network
                            │
                            │ HTTPS
                            ▼
                  ┌─────────────────────┐
                  │   Azure AD (Public) │
                  │ login.microsoft... │
                  └──────────┬──────────┘
                             │
            ┌────────────────┼────────────────┐
            │ JWT Token      │ JWKS Keys      │
            ▼                ▼                │
┌──────────────────┐  ┌──────────────────┐  │
│  React Web App   │  │  FastAPI Backend │  │
│  (Container App) │→ │  (Container App) │  │
│                  │  │  - Validate JWT  │←─┘
│  Public Ingress  │  │  - Extract user  │
└──────────────────┘  └────────┬─────────┘
                               │
                               │ All traffic via Private Endpoints
                               ▼
        ┌──────────────────────────────────────────┐
        │         Azure Virtual Network            │
        │         (10.0.0.0/8)                    │
        │                                          │
        │  ┌────────────────────────────────────┐ │
        │  │  Private Endpoints                 │ │
        │  │  - Cosmos DB (10.0.0.x)           │ │
        │  │  - Storage (10.0.0.y)             │ │
        │  │  - AI Services (10.0.0.z)         │ │
        │  │  - App Config (10.0.0.w)          │ │
        │  └────────────────────────────────────┘ │
        │                                          │
        │  ┌────────────────────────────────────┐ │
        │  │  Private DNS Zones                 │ │
        │  │  - privatelink.blob.core...       │ │
        │  │  - privatelink.cosmos.azure...    │ │
        │  └────────────────────────────────────┘ │
        └──────────────────────────────────────────┘
```

## Summary: Changes Required for Private Domains

| Component | Change Required | Why |
|-----------|----------------|-----|
| **Bicep Deployment** | Set `enablePrivateNetworking=true` | Enables VNet, Private Endpoints, NSGs |
| **NSG Rules** | Allow outbound to `AzureActiveDirectory` | Backend needs to validate JWT tokens |
| **FastAPI Auth** | Install `fastapi-azure-auth` with JWKS caching | Handles token validation in private network |
| **User Context** | No changes needed | JWT claim extraction works the same |
| **MSAL (Frontend)** | No changes needed (usually) | Browser-based auth to public Azure AD |
| **DNS** | Automatic via Private DNS Zones | Already configured in template |
| **Data Isolation** | No changes needed | Uses `user_id` from JWT regardless of network |

## Key Takeaway

**For Stage 1 user isolation with private domains:**

1. ✅ Deploy with `enablePrivateNetworking=true`
2. ✅ Ensure NSG allows outbound to Azure AD
3. ✅ Use `fastapi-azure-auth` for JWT validation (handles JWKS caching)
4. ✅ Extract `user_id` from JWT claims (same as public network)
5. ✅ Use `user_id` as partition key in Cosmos DB

**No additional changes needed** for the user isolation logic itself - it works identically whether you use public or private endpoints. The only consideration is ensuring your backend can validate JWT tokens by reaching Azure AD's JWKS endpoint.
