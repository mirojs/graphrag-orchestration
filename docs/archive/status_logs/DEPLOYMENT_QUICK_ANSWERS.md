# ⚡ Quick Answers: Deployment Questions

## **Q: "If I deploy the app now, will containers be created for all my current user groups?"**

### **A: NO ❌**

**Containers are created ON-DEMAND, not at deployment time.**

- ✅ Deployment = App starts, connects to Azure, ready to serve
- ❌ Deployment ≠ Create containers for all groups
- ✅ First user action per group = Container created for that group

---

## **Q: "Will collections be created for all my current user groups?"**

### **A: NO ❌**

**Cosmos DB collections are SHARED, not per-group.**

- ✅ Collections already exist: `schema`, `analysisRuns`, `analysisCases`
- ✅ Groups use `group_id` field for filtering
- ❌ No separate collections/databases per group
- ✅ More cost-effective than database-per-group

---

## **Q: "Any requirements on the tenant?"**

### **A: YES ✅ - See full requirements in `DEPLOYMENT_GROUP_ISOLATION_FAQ.md`**

### **Critical Requirements:**

#### **1. Azure AD Configuration:**
- ✅ App Registration with "groups" claim in token configuration
- ✅ Microsoft Graph API permissions (Directory.Read.All or Group.Read.All)
- ✅ Admin consent granted
- ✅ Security groups created with members

#### **2. Azure Storage:**
- ✅ Storage Account exists
- ✅ Container App managed identity has **Storage Blob Data Contributor** role
- ✅ Container App managed identity has **Storage Account Contributor** role
  - ⚠️ **Both roles required** - Data Contributor for blobs, Account Contributor for creating containers

#### **3. Cosmos DB:**
- ✅ Cosmos DB account with SQL API
- ✅ Containers created: `schema`, `analysisRuns`, `analysisCases`
- ✅ Container App managed identity has **Cosmos DB Built-in Data Contributor** role

#### **4. Azure AD Roles for Group Management:**
- ✅ **Groups Administrator** - 2-3 people to create/manage groups
- ✅ **Application Administrator** - 1-2 people for app configuration
- ✅ **Group Owners** - Team leads for day-to-day member management

---

## 📚 **Documentation Index**

| Document | Purpose |
|----------|---------|
| **`DEPLOYMENT_GROUP_ISOLATION_FAQ.md`** | Complete deployment guide, requirements, testing |
| **`AZURE_PORTAL_ONLY_GROUP_MANAGEMENT.md`** | How to manage groups in Azure Portal |
| **`GROUP_REGISTRATION_DECISION_TREE.md`** | Do you need to register groups with the app? |
| **`AZURE_AD_ROLES_QUICK_REFERENCE.md`** | Role requirements quick reference |
| **`SINGLE_VS_MULTI_TENANT_DECISION_GUIDE.md`** | Single tenant vs multi-tenant architecture |
| **`MIGRATION_GUIDE_ALL_GROUPS_TO_ASSIGNED_GROUPS.md`** | Migrate from all groups to assigned groups only |

---

## 🎯 **Deployment Checklist (30 seconds)**

### **Before Deployment:**
- [ ] JWT tokens contain "groups" claim (test at https://jwt.ms)
- [ ] Graph API permissions granted with admin consent
- [ ] Storage Account has both RBAC roles on managed identity
- [ ] Cosmos DB has required collections created
- [ ] At least one security group exists with test user

### **After Deployment:**
- [ ] App loads successfully
- [ ] User can log in
- [ ] Group selector appears with friendly names
- [ ] Upload test file → Check Azure Portal for new container
- [ ] Verify container name: `pro-input-files-group-{8chars}`

---

## ⚡ **TL;DR**

**Deployment creates:**
- ✅ Running application
- ✅ Database connections
- ✅ Authentication flow

**Deployment does NOT create:**
- ❌ Group-specific blob containers (created on first use)
- ❌ Separate Cosmos DB collections (use shared collections with filtering)

**Requirements:**
- ✅ Azure AD groups configured with "groups" claim
- ✅ Storage RBAC with both Data Contributor + Account Contributor
- ✅ Graph API permissions for friendly group names

**First user action per group:**
- ✅ Creates blob container for that group
- ✅ Isolated storage from other groups
- ✅ No pre-configuration needed!

---

**Ready? Deploy and let the app create containers as needed! 🚀**
