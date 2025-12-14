# 🚀 Deployment FAQ: Group-Based Isolation

## ❓ **"If I deploy the app now, will containers be created for all my current user groups?"**

### **Short Answer: NO** ❌

Containers are **NOT** created automatically for all groups on deployment. They are created **on-demand** when users actually use them.

---

## 📦 **How Container Creation Actually Works**

### **Container Creation is Lazy/On-Demand**

```python
# From StorageBlobHelper._ensure_container_exists()
def _ensure_container_exists(self, container_name: str):
    """Lazily ensure container exists only when first accessed."""
    container_client = self.blob_service_client.get_container_client(container_name)
    try:
        if not container_client.exists():
            container_client.create_container()  # ✅ Only creates if needed
    except Exception as e:
        print(f"Warning: Could not ensure container {container_name} exists: {e}")
```

### **When Are Containers Created?**

Containers are created **the first time** a user from a group performs an action:

| Action | Triggers Container Creation |
|--------|---------------------------|
| **Upload file** | ✅ First upload to group creates `pro-input-files-group-{group_id[:8]}` |
| **Upload reference file** | ✅ First upload creates `pro-reference-files-group-{group_id[:8]}` |
| **Run analysis** | ✅ Analysis results trigger prediction container creation |
| **Just logging in** | ❌ No container created |
| **Browsing UI** | ❌ No container created |
| **Listing files (empty)** | ❌ No container created |

---

## 📊 **Container Creation Timeline**

### **On Deployment** (App Starts Up)
```
✅ App deployed to Azure Container Apps
✅ Backend service starts
✅ Connects to Cosmos DB
✅ Connects to Blob Storage
❌ NO containers created yet!
❌ NO group-specific containers exist
```

### **User 1 Logs In (Group A)**
```
✅ User authenticates with Azure AD
✅ JWT token includes Group A ID
✅ Frontend loads
✅ Group selector shows Group A
❌ Still NO containers created!
```

### **User 1 Uploads First File (Group A)**
```
✅ User clicks "Upload Document"
✅ Frontend sends request with X-Group-ID: {Group A ID}
✅ Backend receives upload request
✨ Backend creates container: pro-input-files-group-{GroupA[:8]}
✅ File uploaded successfully
```

### **User 2 Logs In (Group B)**
```
✅ User authenticates with Azure AD
✅ JWT token includes Group B ID
✅ Group selector shows Group B
❌ NO container for Group B yet
```

### **User 2 Uploads First File (Group B)**
```
✅ User clicks "Upload Document"
✅ Backend receives request with Group B ID
✨ Backend creates NEW container: pro-input-files-group-{GroupB[:8]}
✅ File uploaded to Group B's container
```

---

## 🎯 **What This Means for Deployment**

### **Immediate After Deployment:**
```
Azure Blob Storage Account
└── (possibly some existing containers)
    
❌ No group-specific containers exist yet
✅ App is ready to create them on-demand
```

### **After First User Activity per Group:**
```
Azure Blob Storage Account
├── pro-input-files-group-abc12345/      ← Created when Group A uploaded first file
├── pro-reference-files-group-abc12345/  ← Created when Group A uploaded reference
├── pro-input-files-group-xyz78901/      ← Created when Group B uploaded first file
└── predictions-group-xyz78901/          ← Created when Group B ran first analysis
```

---

## 🔐 **Azure Tenant Requirements**

### **1. Azure AD Configuration** (REQUIRED)

#### **App Registration Must Have:**
- ✅ **Token Configuration** → "groups" claim enabled
- ✅ **Emit groups as group IDs** (not names)
- ✅ Choose configuration type:
  - **Option A**: All security groups (automatic)
  - **Option B**: Groups assigned to the application (manual)

#### **Microsoft Graph API Permissions:**
- ✅ **Directory.Read.All** OR **Group.Read.All**
- ✅ Admin consent granted

**Why needed?** 
- Frontend needs to fetch group names from Microsoft Graph API
- Users see friendly names like "Marketing Team" instead of GUIDs

---

### **2. Azure AD Groups** (REQUIRED)

#### **Groups Must:**
- ✅ Be **Security Groups** (not Microsoft 365 groups)
- ✅ Have members assigned
- ✅ Be in the same tenant as the app registration

#### **Users Must:**
- ✅ Be members of at least one security group
- ✅ Have the group appear in their JWT token
- ✅ Have valid authentication

---

### **3. Azure Storage Account** (REQUIRED)

#### **Storage Account Must Have:**
- ✅ **Account Kind**: StorageV2 (general purpose v2)
- ✅ **Performance**: Standard (Premium not required)
- ✅ **Replication**: LRS, GRS, or RAGRS
- ✅ **Blob Service** enabled

#### **Container App Managed Identity Must Have:**
- ✅ **Storage Blob Data Contributor** role on storage account
- ✅ **Storage Account Contributor** role (for container creation)

**Why both roles?**
- Storage Blob Data Contributor: Read/write blobs
- Storage Account Contributor: Create containers dynamically

---

### **4. Cosmos DB** (REQUIRED)

#### **Cosmos DB Must Have:**
- ✅ **API**: Core (SQL)
- ✅ **Partition Key**: `/id` for most containers
- ✅ Containers: `schema`, `analysisRuns`, `analysisCases`

#### **Container App Managed Identity Must Have:**
- ✅ **Cosmos DB Built-in Data Contributor** role

**Note:** 
- Cosmos DB collections are NOT created per-group
- Groups use `group_id` field for filtering within shared collections
- This is more cost-effective than separate databases per group

---

### **5. Azure RBAC Requirements** (REQUIRED)

#### **For Group Management (Azure AD):**

| Role | Needed For | Who Gets It |
|------|-----------|-------------|
| **Groups Administrator** | Create/manage security groups | 2-3 IT admins or team leads |
| **Application Administrator** | Configure app registration, token claims | 1-2 senior IT personnel |
| **Group Owners** | Day-to-day member management | Team leads (assigned per group) |

#### **For Azure Resources:**

| Role | Resource | Needed For |
|------|----------|-----------|
| **Storage Blob Data Contributor** | Storage Account | Container App to read/write blobs |
| **Storage Account Contributor** | Storage Account | Container App to create containers |
| **Cosmos DB Built-in Data Contributor** | Cosmos DB | Container App to read/write documents |
| **Contributor** | Resource Group | DevOps team for deployments |

---

## ✅ **Pre-Deployment Checklist**

### **Azure AD Setup:**
- [ ] App Registration exists
- [ ] Token configuration includes "groups" claim
- [ ] Groups claim emits as group IDs
- [ ] Microsoft Graph API permissions granted
- [ ] Admin consent granted for Graph API
- [ ] Security groups created (at least one)
- [ ] Users assigned to security groups
- [ ] Test user JWT token contains groups claim (verify at https://jwt.ms)

### **Azure Resources Setup:**
- [ ] Storage Account created
- [ ] Container App has system-assigned managed identity
- [ ] Managed identity has Storage Blob Data Contributor role
- [ ] Managed identity has Storage Account Contributor role
- [ ] Cosmos DB account created
- [ ] Cosmos DB containers created (`schema`, `analysisRuns`, `analysisCases`)
- [ ] Managed identity has Cosmos DB Built-in Data Contributor role

### **Environment Variables Set:**
- [ ] `AZURE_AD_CLIENT_ID` (API app registration)
- [ ] `AZURE_AD_TENANT_ID`
- [ ] `AZURE_STORAGE_ACCOUNT_URL`
- [ ] `AZURE_COSMOS_DB_ENDPOINT`
- [ ] `AZURE_COSMOS_DB_DATABASE_NAME`
- [ ] Frontend `REACT_APP_CLIENT_ID` (frontend app registration)
- [ ] Frontend `REACT_APP_AUTHORITY` (tenant authority URL)

---

## 🧪 **Post-Deployment Testing**

### **Test 1: Verify Groups in Token**
```bash
1. Navigate to deployed app URL
2. Login with test user
3. Open browser DevTools → Application → Session Storage
4. Find MSAL token
5. Go to https://jwt.ms
6. Paste token
7. ✅ Check "groups" claim exists with group IDs
```

### **Test 2: Verify Group Selection**
```bash
1. Login to app
2. ✅ Group selector dropdown should appear in header
3. ✅ Should show friendly names (not GUIDs)
4. ✅ Can switch between groups
5. ✅ Selected group persists on refresh
```

### **Test 3: Verify Container Creation (Group A)**
```bash
1. Select Group A
2. Upload a document
3. Go to Azure Portal → Storage Account → Containers
4. ✅ Should see: pro-input-files-group-{first8chars}
5. ✅ Container should contain your uploaded file
```

### **Test 4: Verify Container Isolation (Group B)**
```bash
1. Switch to Group B
2. List files
3. ✅ Should see EMPTY list (no Group A files visible)
4. Upload a different document
5. Go to Azure Portal → Storage Account → Containers
6. ✅ Should see SEPARATE container: pro-input-files-group-{different8chars}
7. ✅ Each container should only have its group's files
```

### **Test 5: Verify Cosmos DB Filtering**
```bash
1. Login as Group A user
2. Create a schema
3. Go to Azure Portal → Cosmos DB → Data Explorer
4. Query: SELECT * FROM c WHERE c.group_id = "{Group A ID}"
5. ✅ Should see Group A's schema
6. Query: SELECT * FROM c WHERE c.group_id = "{Group B ID}"
7. ✅ Should NOT see Group A's schemas in Group B's results
```

---

## ⚠️ **Common Issues & Solutions**

### **Issue 1: "Groups not appearing in dropdown"**

**Cause:** Microsoft Graph API permissions not granted

**Fix:**
```bash
1. Azure Portal → App Registrations → [API App]
2. API permissions → Add permission
3. Microsoft Graph → Application permissions
4. Add: Directory.Read.All or Group.Read.All
5. ✅ Click "Grant admin consent for [tenant]"
6. Wait 5-10 minutes for permission propagation
7. Restart Container App
```

### **Issue 2: "No groups in JWT token"**

**Cause:** Token configuration not set up

**Fix:**
```bash
1. Azure Portal → App Registrations → [API App]
2. Token configuration → Add groups claim
3. Select: Security groups
4. ✅ Check: ID, Access, SAML
5. ✅ Emit as: Group IDs
6. Save
7. Users must log out and log back in
```

### **Issue 3: "Container creation fails"**

**Cause:** Missing Storage Account Contributor role

**Fix:**
```bash
# Get Container App managed identity
PRINCIPAL_ID=$(az containerapp show --name <app-name> --resource-group <rg> --query identity.principalId -o tsv)

# Assign Storage Account Contributor role
az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Storage Account Contributor" \
  --scope /subscriptions/<sub-id>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<account-name>
```

### **Issue 4: "Files not isolated between groups"**

**Cause:** Frontend not sending X-Group-ID header

**Check:**
```bash
# Browser DevTools → Network → Select upload request → Headers
# Should see: X-Group-ID: <group-id>
```

**Fix:** Ensure `httpUtility.ts` includes:
```typescript
const selectedGroup = localStorage.getItem('selectedGroup');
if (selectedGroup) {
  headers['X-Group-ID'] = selectedGroup;
}
```

---

## 📈 **Container Growth Estimation**

### **Formula:**
```
Number of Containers = Number of Active Groups × Number of Container Types
```

### **Container Types:**
- Input files: `pro-input-files-group-{id}`
- Reference files: `pro-reference-files-group-{id}`
- Predictions: `predictions-group-{id}`

### **Example Scenarios:**

#### **Scenario 1: 5 Groups, All Active**
```
5 groups × 3 container types = 15 containers maximum
Storage: Pay per GB stored (minimal overhead)
```

#### **Scenario 2: 20 Groups, 10 Active**
```
10 active groups × 3 container types = 30 containers created
10 inactive groups = 0 containers (not created until first use)
Storage: Only pay for what's actually used
```

#### **Scenario 3: 100 Groups, 30 Active**
```
30 active groups × 3 container types = 90 containers
Cost: Still minimal - containers themselves are free
Only charged for: Data storage + transactions
```

---

## 💰 **Cost Implications**

### **Storage Costs:**

| Item | Cost Model |
|------|-----------|
| **Container creation** | ❌ FREE (no charge for containers) |
| **Data storage** | ✅ Pay per GB stored |
| **Transactions** | ✅ Pay per 10,000 operations |
| **Bandwidth** | ✅ Pay per GB egress |

### **On-Demand Creation Benefits:**
- ✅ Only create containers for active groups
- ✅ Avoid paying for empty containers
- ✅ Reduce storage account clutter
- ✅ Easier to manage and audit

---

## 🎉 **Summary: What Happens on Deployment**

```
DEPLOYMENT TIME:
├── ✅ App code deployed
├── ✅ Backend starts up
├── ✅ Connects to Azure services
├── ❌ NO group containers created
└── ✅ Ready to create containers on-demand

FIRST USER ACTION PER GROUP:
├── User uploads file → Container created
├── User uploads reference → Container created
├── User runs analysis → Container created
└── ✅ Each group gets containers as needed

ONGOING:
├── ✅ Containers persist once created
├── ✅ New groups get containers on first use
├── ✅ Inactive groups = no containers = no cost
└── ✅ Full isolation maintained
```

---

## 🚀 **Ready to Deploy?**

**Minimum Requirements:**
1. ✅ Azure AD groups configured
2. ✅ Token claims include groups
3. ✅ Storage account with proper RBAC
4. ✅ Cosmos DB configured
5. ✅ Graph API permissions granted

**What Will Happen:**
1. ✅ App deploys successfully
2. ✅ Users can log in and select groups
3. ✅ First action per group creates containers
4. ✅ Each group gets isolated storage
5. ✅ No pre-creation needed!

**Deploy with confidence!** 🎊
