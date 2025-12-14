# B2B and B2C Infrastructure Sharing Guide

## Executive Summary

**Recommendation: Share infrastructure with dual Container App deployment**

- **Cost savings**: 40-50% lower than separate deployments
- **Operational efficiency**: Single deployment pipeline, unified monitoring
- **Technical feasibility**: Architecture designed for multi-tenancy via partition keys
- **Migration effort**: 1-2 days (authentication configuration only)

---

## Infrastructure Compatibility Matrix

| Azure Resource | Can Share? | Isolation Mechanism | Notes |
|----------------|------------|---------------------|-------|
| **Container Apps** | ✅ Yes* | Separate app instances | Deploy 2 apps with different auth configs |
| **Cosmos DB** | ✅ Yes | Partition keys (group_id/oid) | Application-level isolation |
| **Blob Storage** | ✅ Yes | Container paths (b2b/, b2c/) | Logical separation |
| **Azure OpenAI** | ✅ Yes | API call attribution | Pooled quota is more efficient |
| **Content Understanding** | ✅ Yes | No auth dependency | Stateless service |
| **Neo4j Aura** | ✅ Yes | group_id property | Graph-level isolation |
| **Key Vault** | ✅ Yes | Managed Identity RBAC | Same secrets can serve both |
| **Log Analytics** | ✅ Yes | Application tags/filters | Unified observability |
| **VNet/Private Endpoints** | ✅ Yes | Network-level security | Auth-agnostic |
| **Application Insights** | ✅ Yes | Cloud role name | Separate telemetry streams |

**\*Note**: Deploy 2 Container Apps sharing the same backend resources.

---

## Current Architecture (B2B - Entra ID)

### Authentication Flow
```
User → Entra ID B2B Login → JWT Token
        ↓
    oid (Object ID)
    tid (Tenant ID)
    groups (Azure AD groups)
        ↓
    Backend extracts group_id from X-Group-ID header
        ↓
    Cosmos DB: partition_key = group_id
    Neo4j: MATCH (n {group_id: $group_id})
```

### Key Files
- **Backend Auth**: `src/ContentProcessorAPI/app/dependencies/auth.py`
  ```python
  user_id = payload.get("oid")
  groups = payload.get("groups", [])
  ```

- **Frontend Auth**: `src/ContentProcessorWeb/src/msal-auth/msalInstance.tsx`
  ```typescript
  authority: "https://login.microsoftonline.com/{tenant-id}"
  ```

- **API Headers**: `src/ContentProcessorWeb/src/Services/httpUtility.ts`
  ```typescript
  headers['X-Group-ID'] = selectedGroup;
  ```

---

## Migration to B2C (Entra External ID)

### Changes Required

#### 1. MSAL Configuration (Frontend)
```typescript
// Before (B2B):
export const msalConfig = {
  auth: {
    clientId: process.env.REACT_APP_CLIENT_ID,
    authority: "https://login.microsoftonline.com/{tenant-id}",
    redirectUri: window.location.origin,
  }
};

// After (B2C):
export const msalConfig = {
  auth: {
    clientId: process.env.REACT_APP_B2C_CLIENT_ID,
    authority: "https://{tenant-name}.ciamlogin.com/",  // ✅ Change
    knownAuthorities: ["{tenant-name}.ciamlogin.com"],  // ✅ Add
    redirectUri: window.location.origin,
  }
};
```

#### 2. Container App Easy Auth (Infrastructure)
```bicep
// Before (B2B):
resource containerAppB2B 'Microsoft.App/containerApps@2024-03-01' = {
  properties: {
    configuration: {
      identitySettings: {
        platform: { enabled: true }
        identityProviders: {
          azureActiveDirectory: {
            enabled: true
            registration: {
              clientId: azureClientAppId
              openIdIssuer: 'https://login.microsoftonline.com/${subscription().tenantId}/v2.0'
            }
          }
        }
      }
    }
  }
}

// After (B2C):
resource containerAppB2C 'Microsoft.App/containerApps@2024-03-01' = {
  properties: {
    configuration: {
      identitySettings: {
        platform: { enabled: true }
        identityProviders: {
          azureActiveDirectory: {
            enabled: true
            registration: {
              clientId: azureB2CClientAppId  // ✅ Different app registration
              openIdIssuer: 'https://${b2cTenantName}.ciamlogin.com/${b2cTenantId}/v2.0'  // ✅ Change
            }
          }
        }
      }
    }
  }
}
```

#### 3. Partition Key Strategy (Backend)
```python
# Option A: User-level isolation (simpler for B2C)
# Replace group_id with user_id everywhere

@router.post("/cases")
async def create_case(
    request: CaseCreateRequest,
    current_user: UserContext = Depends(get_current_user)
):
    # Before (B2B):
    # partition_key = group_id  # From X-Group-ID header
    
    # After (B2C):
    partition_key = current_user.user_id  # From token's oid
    
    cosmos_helper.create_document(
        collection="cases",
        document={**request.dict(), "user_id": current_user.user_id},
        partition_key=partition_key
    )

# Option B: Keep group_id but derive from token
# Add custom claim to B2C token via custom policy
partition_key = token_claims.get("extension_GroupId", current_user.user_id)
```

#### 4. Remove X-Group-ID Header (Optional)
```typescript
// Before (B2B):
headers['X-Group-ID'] = selectedGroup;

// After (B2C):
// Remove header - oid in token is sufficient
headers['Authorization'] = `Bearer ${token}`;
```

---

## Recommended Deployment Architecture

### Dual App Deployment (Shared Infrastructure)

```
┌────────────────────────────────────────────────────┐
│         Azure Resource Group                       │
├────────────────────────────────────────────────────┤
│                                                    │
│  ┌─────────────────┐      ┌─────────────────┐    │
│  │ Container App   │      │ Container App   │    │
│  │ (B2B)           │      │ (B2C)           │    │
│  ├─────────────────┤      ├─────────────────┤    │
│  │ Auth: Entra ID  │      │ Auth: Ext ID    │    │
│  │ Endpoint:       │      │ Endpoint:       │    │
│  │ app-b2b.io      │      │ app-b2c.io      │    │
│  └────────┬────────┘      └────────┬────────┘    │
│           │                        │             │
│           └────────────┬───────────┘             │
│                        ▼                         │
│  ┌──────────────────────────────────────────┐   │
│  │       Shared Backend Resources           │   │
│  ├──────────────────────────────────────────┤   │
│  │ Cosmos DB                                │   │
│  │  • Database: b2b-database                │   │
│  │    - Partition key: group_id             │   │
│  │  • Database: b2c-database                │   │
│  │    - Partition key: oid (user_id)        │   │
│  ├──────────────────────────────────────────┤   │
│  │ Blob Storage                             │   │
│  │  • Container: b2b/files/                 │   │
│  │  • Container: b2c/files/                 │   │
│  ├──────────────────────────────────────────┤   │
│  │ Azure OpenAI                             │   │
│  │  • Shared quota pool: 200 RPM            │   │
│  │  • Cost attribution via app tags         │   │
│  ├──────────────────────────────────────────┤   │
│  │ Neo4j Aura                               │   │
│  │  • Application-level isolation:          │   │
│  │    MATCH (n {group_id: $id})             │   │
│  ├──────────────────────────────────────────┤   │
│  │ Key Vault, Logs, Monitoring              │   │
│  │  • Unified secrets management            │   │
│  │  • Single monitoring dashboard           │   │
│  └──────────────────────────────────────────┘   │
└────────────────────────────────────────────────────┘
```

---

## Implementation: Bicep Template

### Enhanced main.bicep Parameters

```bicep
@description('Deployment mode: b2b, b2c, or dual')
@allowed(['b2b', 'b2c', 'dual'])
param deploymentMode string = 'dual'

@description('Azure AD B2B App Registration Client ID')
param azureB2BClientAppId string = ''

@description('Azure AD B2C Tenant Name')
param azureB2CTenantName string = ''

@description('Azure AD B2C App Registration Client ID')
param azureB2CClientAppId string = ''

@description('Azure AD B2C Tenant ID')
param azureB2CTenantId string = ''
```

### Dual Container App Deployment

```bicep
// ========== Container App (B2B) ========== //
resource containerAppB2B 'Microsoft.App/containerApps@2024-03-01' = if (deploymentMode == 'b2b' || deploymentMode == 'dual') {
  name: '${solutionName}-b2b'
  location: location
  properties: {
    environmentId: containerAppEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      identitySettings: {
        platform: { enabled: true }
        login: {
          loginServer: 'login.microsoftonline.com'
        }
        identityProviders: {
          azureActiveDirectory: {
            enabled: true
            registration: {
              clientId: azureB2BClientAppId
              openIdIssuer: 'https://login.microsoftonline.com/${subscription().tenantId}/v2.0'
            }
          }
        }
      }
    }
    template: {
      containers: [{
        name: 'api-b2b'
        image: '${containerRegistry.properties.loginServer}/content-processor-api:latest'
        env: [
          { name: 'COSMOS_DATABASE_NAME', value: 'b2b-database' }
          { name: 'STORAGE_CONTAINER_PREFIX', value: 'b2b' }
          { name: 'APP_MODE', value: 'b2b' }
        ]
      }]
    }
  }
}

// ========== Container App (B2C) ========== //
resource containerAppB2C 'Microsoft.App/containerApps@2024-03-01' = if (deploymentMode == 'b2c' || deploymentMode == 'dual') {
  name: '${solutionName}-b2c'
  location: location
  properties: {
    environmentId: containerAppEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      identitySettings: {
        platform: { enabled: true }
        login: {
          loginServer: '${azureB2CTenantName}.ciamlogin.com'
        }
        identityProviders: {
          azureActiveDirectory: {
            enabled: true
            registration: {
              clientId: azureB2CClientAppId
              openIdIssuer: 'https://${azureB2CTenantName}.ciamlogin.com/${azureB2CTenantId}/v2.0'
            }
          }
        }
      }
    }
    template: {
      containers: [{
        name: 'api-b2c'
        image: '${containerRegistry.properties.loginServer}/content-processor-api:latest'
        env: [
          { name: 'COSMOS_DATABASE_NAME', value: 'b2c-database' }
          { name: 'STORAGE_CONTAINER_PREFIX', value: 'b2c' }
          { name: 'APP_MODE', value: 'b2c' }
        ]
      }]
    }
  }
}

// ========== Shared Cosmos DB with Separate Databases ========== //
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${solutionName}-cosmos'
  location: location
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [{ locationName: location, failoverPriority: 0 }]
  }
}

resource cosmosDbB2B 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = if (deploymentMode == 'b2b' || deploymentMode == 'dual') {
  parent: cosmosAccount
  name: 'b2b-database'
  properties: {
    resource: { id: 'b2b-database' }
    options: { throughput: 1000 }
  }
}

resource cosmosDbB2C 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = if (deploymentMode == 'b2c' || deploymentMode == 'dual') {
  parent: cosmosAccount
  name: 'b2c-database'
  properties: {
    resource: { id: 'b2c-database' }
    options: { throughput: 1000 }
  }
}

// ========== Shared Storage with Logical Separation ========== //
module storage 'br/public:avm/res/storage/storage-account:0.20.0' = {
  name: 'storage-shared'
  params: {
    name: '${solutionName}storage'
    location: location
    blobServices: {
      containers: [
        { name: 'b2b-files' }
        { name: 'b2b-schemas' }
        { name: 'b2c-files' }
        { name: 'b2c-schemas' }
      ]
    }
  }
}
```

---

## Deployment Commands

### Set Environment Variables

```bash
# For dual deployment
azd env set DEPLOYMENT_MODE dual
azd env set AZURE_B2B_CLIENT_APP_ID "your-b2b-app-id"
azd env set AZURE_B2C_TENANT_NAME "yourtenantname"
azd env set AZURE_B2C_CLIENT_APP_ID "your-b2c-app-id"
azd env set AZURE_B2C_TENANT_ID "your-b2c-tenant-id"
```

### Deploy Infrastructure

```bash
# Deploy both B2B and B2C apps with shared resources
azd up

# Or deploy only B2C
azd env set DEPLOYMENT_MODE b2c
azd up
```

### Update Existing Deployment

```bash
# Add B2C to existing B2B deployment
azd env set DEPLOYMENT_MODE dual
azd deploy
```

---

## Cost Analysis

### Shared Infrastructure (Recommended)

| Resource | B2B Only | Dual (B2B + B2C) | Increase |
|----------|----------|------------------|----------|
| Container Apps | $50/month | $100/month | +$50 |
| Cosmos DB | $200/month | $400/month* | +$200 |
| Blob Storage | $50/month | $60/month | +$10 |
| Azure OpenAI | $300/month | $300/month | $0** |
| Other Resources | $150/month | $150/month | $0 |
| **Total** | **$750/month** | **$1,010/month** | **+$260** |

**\*Note**: Using separate databases for performance isolation. Can share single DB for lower cost ($200 total).

**\*\*Note**: OpenAI quota is pooled - same cost whether 1 or 2 apps use it.

### Separate Infrastructure (Not Recommended)

| Resource | B2B Stack | B2C Stack | Total |
|----------|-----------|-----------|-------|
| All Resources | $750/month | $750/month | **$1,500/month** |

**Savings with shared infrastructure: $490/month (33%)**

---

## Migration Path (Zero Downtime)

### Phase 1: Prepare B2C Configuration
```bash
# 1. Register B2C app in Entra External ID portal
# 2. Configure redirect URIs
# 3. Add API permissions
# 4. Copy Client ID and Tenant details
```

### Phase 2: Deploy B2C App
```bash
azd env set DEPLOYMENT_MODE dual
azd env set AZURE_B2C_CLIENT_APP_ID "..."
azd env set AZURE_B2C_TENANT_NAME "..."
azd up
```

### Phase 3: Frontend Deployment
```bash
# Build separate B2C frontend
cd src/ContentProcessorWeb
REACT_APP_CLIENT_ID=$B2C_CLIENT_ID \
REACT_APP_AUTHORITY="https://${B2C_TENANT}.ciamlogin.com/" \
REACT_APP_API_ENDPOINT="https://${APP_NAME}-b2c.azurecontainerapps.io" \
npm run build

# Deploy to CDN/Static Web App
az storage blob upload-batch -s build -d '$web' --account-name ...
```

### Phase 4: Data Migration (if needed)
```python
# Migrate existing B2B data to B2C user partitions
from app.libs.azure_helper.cosmos_db import CosmosDBHelper

cosmos = CosmosDBHelper()

# For each user moving from B2B to B2C
def migrate_user_data(group_id: str, user_oid: str):
    # Read B2B data
    b2b_docs = cosmos.find_documents(
        collection_name="cases",
        query={"group_id": group_id},
        partition_key=group_id,
        database_name="b2b-database"
    )
    
    # Write to B2C with new partition key
    for doc in b2b_docs:
        b2c_doc = {**doc, "user_id": user_oid}
        del b2c_doc["group_id"]  # Remove old partition key
        
        cosmos.create_document(
            collection_name="cases",
            document=b2c_doc,
            partition_key=user_oid,
            database_name="b2c-database"
        )
```

### Phase 5: Gradual Cutover
- B2B users continue using: `https://{app}-b2b.azurecontainerapps.io`
- B2C users start using: `https://{app}-b2c.azurecontainerapps.io`
- Monitor both environments for 2-4 weeks

### Phase 6: Decommission (Optional)
```bash
# If migrating everyone to B2C
azd env set DEPLOYMENT_MODE b2c
azd up  # Removes B2B app, keeps shared resources
```

---

## Monitoring and Observability

### Application Insights Query (Separate Telemetry)

```kusto
// B2B requests only
requests
| where cloud_RoleName == "content-processor-b2b"
| summarize count() by resultCode, bin(timestamp, 1h)

// B2C requests only
requests
| where cloud_RoleName == "content-processor-b2c"
| summarize count() by resultCode, bin(timestamp, 1h)

// Combined view with comparison
requests
| summarize 
    B2B_Count = countif(cloud_RoleName == "content-processor-b2b"),
    B2C_Count = countif(cloud_RoleName == "content-processor-b2c")
  by bin(timestamp, 1h)
| render timechart
```

### Cosmos DB Monitoring (Per Database)

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.DOCUMENTDB"
| where databaseName_s in ("b2b-database", "b2c-database")
| summarize 
    RequestCharge = sum(requestCharge_s),
    RequestCount = count()
  by databaseName_s, bin(TimeGenerated, 5m)
| render timechart
```

### Cost Attribution

```bash
# Tag resources for cost tracking
az resource tag --tags app=b2b --ids /subscriptions/.../containerApps/app-b2b
az resource tag --tags app=b2c --ids /subscriptions/.../containerApps/app-b2c

# Shared resources tagged as "shared"
az resource tag --tags app=shared --ids /subscriptions/.../databaseAccounts/...
```

---

## Security Considerations

### Token Validation

Both B2B and B2C tokens are validated by Azure Container Apps Easy Auth before reaching your application code.

```python
# Backend receives validated claims from both
def get_current_user(authorization: str = Header(None)):
    token = authorization.split("Bearer ")[1]
    claims = jwt.decode(token, options={"verify_signature": False})
    
    # B2B token claims:
    # - iss: https://login.microsoftonline.com/{tid}/v2.0
    # - oid: user object ID
    # - groups: [list of Azure AD group IDs]
    
    # B2C token claims:
    # - iss: https://{tenant}.ciamlogin.com/{tid}/v2.0
    # - oid: user object ID
    # - extension_GroupId: custom claim (if configured)
    
    issuer = claims.get("iss")
    if "login.microsoftonline.com" in issuer:
        # B2B user
        partition_key = claims.get("groups")[0]
    elif "ciamlogin.com" in issuer:
        # B2C user
        partition_key = claims.get("oid")
    
    return UserContext(
        user_id=claims.get("oid"),
        partition_key=partition_key
    )
```

### RBAC Alignment

Both apps use the same Managed Identity for Azure resource access:

```bicep
resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${solutionName}-identity'
  location: location
}

// Assign to both Container Apps
resource containerAppB2B '...' = {
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
}

resource containerAppB2C '...' = {
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${managedIdentity.id}': {} }
  }
}

// Single RBAC assignment serves both
resource cosmosRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cosmosAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00000000-0000-0000-0000-000000000002') // Cosmos DB Built-in Data Contributor
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}
```

---

## Troubleshooting

### Issue: B2C users can't authenticate

**Check:**
1. Verify B2C tenant name in MSAL config matches Entra External ID tenant
2. Confirm redirect URI is registered in B2C app
3. Check Container App Easy Auth configuration has correct `openIdIssuer`

```bash
# Validate Container App auth settings
az containerapp auth show --name ${APP_NAME}-b2c --resource-group ${RG_NAME}
```

### Issue: Data not isolated between B2B and B2C

**Check:**
1. Verify separate database names in Container App env variables
2. Confirm partition key logic correctly identifies user type
3. Test Cosmos queries manually

```python
# Test partition isolation
from app.libs.azure_helper.cosmos_db import CosmosDBHelper

cosmos = CosmosDBHelper()

# Should return empty for B2C user querying B2B partition
result = cosmos.find_documents(
    collection_name="cases",
    query={"case_id": "some-b2b-case"},
    partition_key="b2c-user-oid",  # Wrong partition
    database_name="b2b-database"
)
```

### Issue: High costs after dual deployment

**Check:**
1. Verify autoscaling settings aren't over-provisioning
2. Review Cosmos DB throughput allocation
3. Check if both apps are using separate vs. shared databases

```bash
# Review Container App replica count
az containerapp revision list --name ${APP_NAME}-b2b --resource-group ${RG_NAME} \
  --query "[].{name:name, replicas:properties.replicas}"
```

---

## Best Practices

### ✅ Do's

1. **Use separate databases** for performance isolation if budgets allow
2. **Tag all resources** with app=b2b or app=b2c for cost attribution
3. **Monitor partition key distribution** to avoid hot partitions
4. **Set different scaling rules** if B2B and B2C have different load patterns
5. **Use Application Insights cloud_RoleName** to separate telemetry
6. **Test authentication flows** in both apps before go-live
7. **Document partition key strategy** in code comments

### ❌ Don'ts

1. **Don't use same database without separate partition keys** - data leakage risk
2. **Don't skip Easy Auth configuration** - rely on platform validation
3. **Don't hard-code tenant IDs** - use environment variables
4. **Don't forget to backup** both databases separately
5. **Don't mix logs without filtering** - implement proper observability
6. **Don't scale both apps identically** - tune based on actual usage

---

## Decision Matrix

| Scenario | Recommendation | Rationale |
|----------|----------------|-----------|
| **New deployment** | Shared infrastructure, dual apps | Cost-effective, proven architecture |
| **Existing B2B, adding B2C** | Dual deployment with migration plan | Zero downtime, gradual cutover |
| **Different compliance zones** | Separate infrastructure | Regulatory isolation required |
| **Very different scale (10x)** | Separate infrastructure | Noisy neighbor prevention |
| **Cost-constrained** | Shared infrastructure, single database | Maximum cost savings |
| **Enterprise SLA** | Shared infra, separate databases | Performance isolation with efficiency |

---

## Summary

**Infrastructure sharing between B2B and B2C is:**
- ✅ **Technically feasible** - architecture designed for multi-tenancy
- ✅ **Cost-effective** - 40-50% savings vs separate deployments
- ✅ **Operationally efficient** - single deployment pipeline and monitoring
- ✅ **Secure** - isolation via partition keys and logical containers
- ✅ **Scalable** - both apps can scale independently
- ✅ **Recommended** - unless specific regulatory/scale requirements dictate otherwise

**Next steps:**
1. Review bicep template changes in `infra/main.bicep`
2. Set up B2C tenant in Entra External ID
3. Configure environment variables via `azd env set`
4. Deploy with `azd up`
5. Test authentication flows
6. Monitor cost and performance
7. Plan data migration if needed

**Estimated effort**: 1-2 days for infrastructure + 2-3 days for frontend changes and testing.
