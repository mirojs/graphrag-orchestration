# Group Isolation Implementation Checklist

**Updated:** October 16, 2025  
**Based on:** Microsoft Content Processing Solution Accelerator architecture  
**Authentication Model:** Azure Container Apps built-in auth + MSAL frontend

---

## 📋 **Pre-Implementation Verification**

### ✅ **Completed Tasks**
- [x] Discovered Azure AD configuration (API/Web app registrations)
- [x] Identified existing security groups (Hulkdesign-AI-access, Owner-access, Testing-access)
- [x] Added group claims to API app token configuration
- [x] Added group claims to Web app token configuration
- [x] Verified group memberships

### 🔍 **Verify Current State**

Run these verification steps before proceeding:

```bash
# 1. Verify Azure AD group claims are configured
cd scripts
./discover-azure-params.sh

# 2. Test that tokens contain groups claim
# - Login to your app
# - Open DevTools → Network tab
# - Find any API request
# - Copy Authorization Bearer token
# - Decode at https://jwt.ms
# - Confirm "groups" array is present

# 3. Verify current data structure
# Check what data exists and how it's organized
```

**Expected in JWT token:**
```json
{
  "aud": "9f9b5bce-42a9-4eb0-b1dd-c7e5d454a2f5",
  "iss": "https://login.microsoftonline.com/...",
  "groups": [
    "7e9e0c33-a31e-4b56-8ebf-0fff973f328f",  // Hulkdesign-AI-access
    "824be8de-0981-470e-97f2-3332855e22b2",  // Owner-access
    "fb0282b9-12e0-4dd5-94ab-3df84561994c"   // Testing-access
  ],
  "name": "Jing Liu",
  "oid": "...",
  "email": "..."
}
```

---

## 🎯 **Phase 1: Backend Data Model Updates**

### **Task 1.1: Create UserContext Model**

**File:** `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/models/user_context.py` (create new)

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class UserContext:
    """User context extracted from Azure AD token."""
    user_id: str  # oid claim
    tenant_id: str  # tid claim
    email: str  # email or upn claim
    name: Optional[str] = None  # name claim
    groups: List[str] = field(default_factory=list)  # groups claim
    
    def has_group_access(self, group_id: str) -> bool:
        """Check if user belongs to a specific group."""
        return group_id in self.groups
    
    def get_first_group(self) -> Optional[str]:
        """Get user's first group (for default selection)."""
        return self.groups[0] if self.groups else None
```

**Checklist:**
- [ ] Create file `app/models/user_context.py`
- [ ] Add UserContext dataclass with all fields
- [ ] Add helper methods (`has_group_access`, `get_first_group`)
- [ ] Test import: `from app.models.user_context import UserContext`

---

### **Task 1.2: Update Schema Model**

**File:** `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/models/schema.py`

**Changes needed:**
```python
# Add to Schema class
class Schema:
    # ...existing fields...
    group_id: Optional[str] = None  # ADD THIS
    
    # Update to_dict method
    def to_dict(self):
        return {
            # ...existing fields...
            "group_id": self.group_id,  # ADD THIS
        }
```

**Checklist:**
- [ ] Add `group_id: Optional[str] = None` field to Schema class
- [ ] Update `to_dict()` method to include `group_id`
- [ ] Update `from_dict()` method (if exists) to handle `group_id`
- [ ] Run tests to ensure Schema serialization works

---

### **Task 1.3: Update File Model**

**File:** Find the File/Document model (likely in `app/models/`)

**Changes needed:**
```python
# Add to File/Document class
class File:
    # ...existing fields...
    group_id: Optional[str] = None  # ADD THIS
```

**Checklist:**
- [ ] Locate File/Document model file
- [ ] Add `group_id` field
- [ ] Update serialization methods
- [ ] Verify file upload/download logic still works

---

### **Task 1.4: Update Analysis/Results Model**

**File:** Find the Analysis/Results model

**Changes needed:**
```python
# Add to Analysis class
class Analysis:
    # ...existing fields...
    group_id: Optional[str] = None  # ADD THIS
```

**Checklist:**
- [ ] Locate Analysis/Results model file
- [ ] Add `group_id` field
- [ ] Update serialization methods

---

## 🔧 **Phase 2: Authentication & Authorization**

### **Task 2.1: Extract User Context from Token**

**File:** `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/dependencies/auth.py` (create new)

```python
from fastapi import Header, HTTPException, status
from typing import Optional
import jwt
import logging
from app.models.user_context import UserContext

logger = logging.getLogger(__name__)

async def get_current_user(
    authorization: Optional[str] = Header(None)
) -> UserContext:
    """
    Extract user context from Azure AD JWT token.
    
    Note: Azure Container Apps with Easy Auth passes decoded claims
    in X-MS-CLIENT-PRINCIPAL header (base64 encoded JSON).
    For direct Bearer token, we decode it here.
    """
    if not authorization:
        logger.warning("No authorization header provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
    
    try:
        # Extract Bearer token
        if not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization header format"
            )
        
        token = authorization.split("Bearer ")[1]
        
        # Decode without verification (Azure Container Apps validates)
        # In production, Azure Container Apps Easy Auth handles validation
        payload = jwt.decode(token, options={"verify_signature": False})
        
        # Extract claims
        user_id = payload.get("oid")
        tenant_id = payload.get("tid")
        email = payload.get("email") or payload.get("upn")
        name = payload.get("name")
        groups = payload.get("groups", [])  # NEW: Extract groups
        
        if not user_id or not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing required claims"
            )
        
        user_context = UserContext(
            user_id=user_id,
            tenant_id=tenant_id,
            email=email,
            name=name,
            groups=groups
        )
        
        logger.info(f"User authenticated: {email}, groups: {len(groups)}")
        return user_context
        
    except jwt.DecodeError as e:
        logger.error(f"JWT decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format"
        )
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )
```

**Checklist:**
- [ ] Create `app/dependencies/auth.py`
- [ ] Implement `get_current_user` function
- [ ] Add logging for debugging
- [ ] Handle missing/invalid tokens gracefully
- [ ] Extract `groups` claim from token
- [ ] Test with real token from your app

---

### **Task 2.2: Add Group ID to API Endpoints**

**File:** `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`

**Example update for schema endpoint:**

```python
from fastapi import Depends, Header
from app.dependencies.auth import get_current_user
from app.models.user_context import UserContext

# BEFORE:
@router.post("/schema/natural-language")
async def create_schema_from_natural_language(request: NaturalLanguageSchemaRequest):
    # ...existing code...

# AFTER:
@router.post("/schema/natural-language")
async def create_schema_from_natural_language(
    request: NaturalLanguageSchemaRequest,
    group_id: str = Header(..., alias="X-Group-ID"),  # NEW: Required group header
    current_user: UserContext = Depends(get_current_user)  # NEW: User context
):
    # Validate user has access to this group
    if not current_user.has_group_access(group_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not have access to group {group_id}"
        )
    
    # Add group_id to schema creation
    # ...existing code...
    schema_dict["group_id"] = group_id  # NEW
    # ...rest of code...
```

**Checklist:**
- [ ] Update all POST endpoints to require `X-Group-ID` header
- [ ] Add `current_user: UserContext = Depends(get_current_user)` to all protected endpoints
- [ ] Add group access validation
- [ ] Include `group_id` when creating new records
- [ ] Test endpoints with Postman/curl

---

## 💾 **Phase 3: Database Query Updates**

### **Task 3.1: Update Schema Queries**

**File:** `code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py` (or service layer)

**Example for list schemas:**

```python
# BEFORE:
@router.get("/schemas")
async def list_schemas():
    schemas = await db.schemas.find({"user_id": user_id}).to_list(100)
    return schemas

# AFTER:
@router.get("/schemas")
async def list_schemas(
    group_id: str = Header(..., alias="X-Group-ID"),
    current_user: UserContext = Depends(get_current_user)
):
    # Validate access
    if not current_user.has_group_access(group_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Query with group filter
    schemas = await db.schemas.find({
        "user_id": current_user.user_id,
        "group_id": group_id  # NEW: Filter by group
    }).to_list(100)
    
    return schemas
```

**Checklist:**
- [ ] Update GET /schemas to filter by `group_id`
- [ ] Update GET /schema/{id} to verify `group_id` matches
- [ ] Update DELETE /schema/{id} to check `group_id`
- [ ] Add group validation to all schema operations
- [ ] Test cross-group isolation (user A can't see group B data)

---

### **Task 3.2: Update File Queries**

**Similar pattern for file operations:**

```python
# List files
@router.get("/files")
async def list_files(
    group_id: str = Header(..., alias="X-Group-ID"),
    current_user: UserContext = Depends(get_current_user)
):
    if not current_user.has_group_access(group_id):
        raise HTTPException(status_code=403, detail="Access denied")
    
    files = await db.files.find({
        "user_id": current_user.user_id,
        "group_id": group_id
    }).to_list(100)
    
    return files
```

**Checklist:**
- [ ] Update GET /files
- [ ] Update GET /files/{id}
- [ ] Update POST /files (add group_id on upload)
- [ ] Update DELETE /files/{id}
- [ ] Update file preview/download endpoints

---

### **Task 3.3: Update Analysis Queries**

**Checklist:**
- [ ] Update all analysis/results queries to filter by `group_id`
- [ ] Add `group_id` when creating new analysis records
- [ ] Validate group access in all operations

---

## 📦 **Phase 4: Blob Storage Updates**

### **Task 4.1: Group-Based Container Organization**

**Current:** User-based containers (`user-{user_id}`)  
**Target:** Group-based containers (`tenant-{tenant_id}-group-{group_id}`)

**File:** Find blob storage service (likely in `app/services/`)

**Example update:**

```python
# BEFORE:
def get_container_name(self, user_id: str) -> str:
    return f"user-{user_id}"

# AFTER:
def get_container_name(self, tenant_id: str, group_id: str) -> str:
    return f"tenant-{tenant_id}-group-{group_id}"
```

**Checklist:**
- [ ] Update container naming function
- [ ] Update file upload to use group-based containers
- [ ] Update file download to use group-based containers
- [ ] Update file listing to use group-based containers
- [ ] Ensure containers are created automatically
- [ ] Test file operations in different groups

---

## 🎨 **Phase 5: Frontend Updates**

### **Task 5.1: Create GroupContext**

**File:** `code/content-processing-solution-accelerator/src/web/src/contexts/GroupContext.tsx` (create new)

```typescript
import React, { createContext, useContext, useState, useEffect } from 'react';
import { useMsal } from '@azure/msal-react';

interface GroupContextType {
  selectedGroup: string | null;
  setSelectedGroup: (groupId: string) => void;
  userGroups: string[];
  loading: boolean;
}

const GroupContext = createContext<GroupContextType | undefined>(undefined);

export const GroupProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { accounts } = useMsal();
  const [selectedGroup, setSelectedGroupState] = useState<string | null>(null);
  const [userGroups, setUserGroups] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Extract groups from MSAL account
    if (accounts.length > 0) {
      const account = accounts[0];
      const groups = (account.idTokenClaims as any)?.groups || [];
      setUserGroups(groups);
      
      // Load saved group or use first group
      const savedGroup = localStorage.getItem('selectedGroup');
      if (savedGroup && groups.includes(savedGroup)) {
        setSelectedGroupState(savedGroup);
      } else if (groups.length > 0) {
        setSelectedGroupState(groups[0]);
      }
      
      setLoading(false);
    }
  }, [accounts]);

  const setSelectedGroup = (groupId: string) => {
    setSelectedGroupState(groupId);
    localStorage.setItem('selectedGroup', groupId);
  };

  return (
    <GroupContext.Provider value={{ selectedGroup, setSelectedGroup, userGroups, loading }}>
      {children}
    </GroupContext.Provider>
  );
};

export const useGroup = () => {
  const context = useContext(GroupContext);
  if (!context) {
    throw new Error('useGroup must be used within GroupProvider');
  }
  return context;
};
```

**Checklist:**
- [ ] Create `GroupContext.tsx`
- [ ] Extract groups from MSAL token claims
- [ ] Persist selected group to localStorage
- [ ] Export `useGroup` hook
- [ ] Test that groups are extracted correctly

---

### **Task 5.2: Create GroupSelector Component**

**File:** `code/content-processing-solution-accelerator/src/web/src/components/GroupSelector.tsx` (create new)

```typescript
import React from 'react';
import { Dropdown, IDropdownOption } from '@fluentui/react';
import { useGroup } from '../contexts/GroupContext';

// Map group IDs to friendly names
const GROUP_NAMES: Record<string, string> = {
  '7e9e0c33-a31e-4b56-8ebf-0fff973f328f': 'Hulkdesign AI Access',
  '824be8de-0981-470e-97f2-3332855e22b2': 'Owner Access',
  'fb0282b9-12e0-4dd5-94ab-3df84561994c': 'Testing Access',
};

export const GroupSelector: React.FC = () => {
  const { selectedGroup, setSelectedGroup, userGroups, loading } = useGroup();

  if (loading || userGroups.length === 0) {
    return null;
  }

  // Don't show selector if user only has one group
  if (userGroups.length === 1) {
    return null;
  }

  const options: IDropdownOption[] = userGroups.map(groupId => ({
    key: groupId,
    text: GROUP_NAMES[groupId] || groupId,
  }));

  return (
    <Dropdown
      label="Active Group"
      selectedKey={selectedGroup}
      onChange={(_, option) => option && setSelectedGroup(option.key as string)}
      options={options}
      styles={{ root: { width: 250 } }}
    />
  );
};
```

**Checklist:**
- [ ] Create `GroupSelector.tsx`
- [ ] Map group IDs to friendly names
- [ ] Handle single-group users (hide selector)
- [ ] Style appropriately for your UI
- [ ] Test group switching

---

### **Task 5.3: Update App.tsx**

**File:** `code/content-processing-solution-accelerator/src/web/src/App.tsx`

```typescript
import { GroupProvider } from './contexts/GroupContext';

function App() {
  return (
    <MsalProvider instance={msalInstance}>
      <GroupProvider>  {/* ADD THIS */}
        {/* ...existing components... */}
      </GroupProvider>
    </MsalProvider>
  );
}
```

**Checklist:**
- [ ] Wrap app with `<GroupProvider>`
- [ ] Add `<GroupSelector />` to header/nav
- [ ] Test that context is available everywhere

---

### **Task 5.4: Update API Service**

**File:** `code/content-processing-solution-accelerator/src/web/src/services/apiService.ts` (or similar)

```typescript
import { useGroup } from '../contexts/GroupContext';

// Example: Update schema creation
export const createSchema = async (schemaData: any) => {
  const { selectedGroup } = useGroup(); // Get current group
  
  const response = await fetch(`${API_URL}/pro-mode/schema/natural-language`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-Group-ID': selectedGroup!,  // NEW: Add group header
    },
    body: JSON.stringify(schemaData),
  });
  
  return response.json();
};
```

**Alternative: Create a custom hook:**

```typescript
// useApiClient.ts
export const useApiClient = () => {
  const { selectedGroup } = useGroup();
  const { instance, accounts } = useMsal();
  
  const getHeaders = async () => {
    const token = await getAccessToken(instance, accounts);
    return {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'X-Group-ID': selectedGroup!,
    };
  };
  
  return { getHeaders };
};
```

**Checklist:**
- [ ] Update all API calls to include `X-Group-ID` header
- [ ] Create reusable API client hook
- [ ] Handle case where no group is selected
- [ ] Test API calls with correct headers

---

### **Task 5.5: Update List Components**

**Example: SchemaList component**

```typescript
const SchemaList: React.FC = () => {
  const { selectedGroup } = useGroup();
  const [schemas, setSchemas] = useState([]);
  
  useEffect(() => {
    if (selectedGroup) {
      loadSchemas();
    }
  }, [selectedGroup]);  // Reload when group changes
  
  const loadSchemas = async () => {
    const data = await apiService.getSchemas(); // Uses X-Group-ID header
    setSchemas(data);
  };
  
  // ...rest of component...
};
```

**Checklist:**
- [ ] Update SchemaList to reload on group change
- [ ] Update FileList to reload on group change
- [ ] Update AnalysisResults to reload on group change
- [ ] Show empty state when switching to empty group
- [ ] Test that data refreshes correctly

---

## 🔄 **Phase 6: Data Migration**

### **Task 6.1: Analyze Existing Data**

**Create script:** `scripts/analyze_current_data.py`

```python
import os
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def analyze_data():
    """Analyze existing data before migration."""
    client = AsyncIOMotorClient(os.getenv("COSMOS_CONNECTION_STRING"))
    db = client[os.getenv("DATABASE_NAME")]
    
    # Count schemas without group_id
    schemas_total = await db.schemas.count_documents({})
    schemas_no_group = await db.schemas.count_documents({"group_id": {"$exists": False}})
    
    # Count files without group_id
    files_total = await db.files.count_documents({})
    files_no_group = await db.files.count_documents({"group_id": {"$exists": False}})
    
    print(f"Schemas: {schemas_total} total, {schemas_no_group} need migration")
    print(f"Files: {files_total} total, {files_no_group} need migration")
    
    # List unique user_ids
    users = await db.schemas.distinct("user_id")
    print(f"Unique users: {len(users)}")
    for user in users:
        count = await db.schemas.count_documents({"user_id": user})
        print(f"  {user}: {count} schemas")

if __name__ == "__main__":
    asyncio.run(analyze_data())
```

**Checklist:**
- [ ] Create analysis script
- [ ] Run to understand current data
- [ ] Document findings
- [ ] Plan user-to-group mapping

---

### **Task 6.2: Create User-Group Mapping**

**Create file:** `scripts/user_group_mapping.json`

```json
{
  "ddd5567a-7d84-4703-bbdb-aa00b3b95bd8": "824be8de-0981-470e-97f2-3332855e22b2",
  "3cc06173-53d3-449a-b902-77befa51b015": "7e9e0c33-a31e-4b56-8ebf-0fff973f328f",
  "5e749121-d4a0-4894-855c-9e0c0837d549": "fb0282b9-12e0-4dd5-94ab-3df84561994c"
}
```

**Checklist:**
- [ ] Map each user_id to their primary group_id
- [ ] Verify all users are mapped
- [ ] Review with stakeholders

---

### **Task 6.3: Migration Script**

**Create script:** `scripts/migrate_data_to_groups.py`

```python
import os
import json
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def migrate_data(dry_run=True):
    """Migrate existing data to include group_id."""
    
    # Load mapping
    with open('user_group_mapping.json') as f:
        mapping = json.load(f)
    
    client = AsyncIOMotorClient(os.getenv("COSMOS_CONNECTION_STRING"))
    db = client[os.getenv("DATABASE_NAME")]
    
    # Migrate schemas
    for user_id, group_id in mapping.items():
        filter_query = {
            "user_id": user_id,
            "group_id": {"$exists": False}
        }
        update_query = {"$set": {"group_id": group_id}}
        
        if dry_run:
            count = await db.schemas.count_documents(filter_query)
            print(f"Would update {count} schemas for user {user_id} -> group {group_id}")
        else:
            result = await db.schemas.update_many(filter_query, update_query)
            print(f"Updated {result.modified_count} schemas for user {user_id}")
    
    # Migrate files
    for user_id, group_id in mapping.items():
        filter_query = {
            "user_id": user_id,
            "group_id": {"$exists": False}
        }
        update_query = {"$set": {"group_id": group_id}}
        
        if dry_run:
            count = await db.files.count_documents(filter_query)
            print(f"Would update {count} files for user {user_id} -> group {group_id}")
        else:
            result = await db.files.update_many(filter_query, update_query)
            print(f"Updated {result.modified_count} files for user {user_id}")
    
    print("\nMigration complete!" if not dry_run else "\nDry run complete!")

if __name__ == "__main__":
    import sys
    dry_run = "--execute" not in sys.argv
    if dry_run:
        print("DRY RUN MODE - no changes will be made")
        print("Run with --execute to apply changes\n")
    asyncio.run(migrate_data(dry_run))
```

**Checklist:**
- [ ] Create migration script
- [ ] Run in dry-run mode first
- [ ] Review output carefully
- [ ] Run with `--execute` flag
- [ ] Verify all records updated

---

### **Task 6.4: Blob Storage Migration**

**Note:** You may need to copy blobs to new group-based containers

```bash
# Script to copy blobs from user containers to group containers
# This depends on your user-to-group mapping
```

**Checklist:**
- [ ] Decide: migrate blobs or recreate on-demand?
- [ ] If migrating, create copy script
- [ ] Test with small dataset first
- [ ] Verify file access after migration

---

## 🧪 **Phase 7: Testing**

### **Test 7.1: Single Group User**

**Test user:** Jing (only in Hulkdesign-AI-access)

- [ ] Login as user with single group
- [ ] Verify no group selector appears
- [ ] Upload a schema
- [ ] Verify `group_id` is set in database
- [ ] Upload a file
- [ ] Verify file goes to correct group container
- [ ] Logout and login again
- [ ] Verify data persists

---

### **Test 7.2: Multi-Group User**

**Test user:** Jing Liu (in Owner-access + Testing-access)

- [ ] Login as multi-group user
- [ ] Verify group selector appears
- [ ] Create data in Group A
- [ ] Switch to Group B
- [ ] Verify Group A data is not visible
- [ ] Create data in Group B
- [ ] Switch back to Group A
- [ ] Verify Group A data reappears
- [ ] Verify both groups have separate data

---

### **Test 7.3: Cross-Group Isolation**

**Setup:** User A in Group 1, User B in Group 2

- [ ] User A creates schema in Group 1
- [ ] Note the schema ID
- [ ] User B tries to access schema directly via API
- [ ] Verify 403 Forbidden or 404 Not Found
- [ ] User B cannot see User A's files
- [ ] Verify blob storage isolation

---

### **Test 7.4: Group Access Changes**

- [ ] Remove user from a group in Azure AD
- [ ] User logs out and logs back in
- [ ] Verify group no longer appears
- [ ] Verify cannot access previous group's data
- [ ] Add user to new group
- [ ] Logout and login
- [ ] Verify new group appears
- [ ] Verify access to new group's data

---

## 🚀 **Phase 8: Deployment**

### **Task 8.1: Backup Production Data**

```bash
# Backup Cosmos DB
az cosmosdb backup --resource-group <rg> --account-name <account>

# Backup Blob Storage
az storage blob snapshot --account-name <account> --container-name <container>
```

**Checklist:**
- [ ] Backup all Cosmos DB collections
- [ ] Backup all blob containers
- [ ] Store backups securely
- [ ] Document restore procedure

---

### **Task 8.2: Deploy to Staging**

**Checklist:**
- [ ] Deploy backend changes to staging
- [ ] Deploy frontend changes to staging
- [ ] Run migration script on staging data
- [ ] Run full test suite
- [ ] Test with real user accounts
- [ ] Verify no regressions

---

### **Task 8.3: Deploy to Production**

```bash
cd code/content-processing-solution-accelerator/infra/scripts
conda deactivate
./docker-build.sh
```

**Checklist:**
- [ ] Schedule maintenance window
- [ ] Notify users of deployment
- [ ] Deploy backend
- [ ] Deploy frontend
- [ ] Run migration script
- [ ] Verify deployment health
- [ ] Monitor for errors
- [ ] Test critical user flows

---

### **Task 8.4: Post-Deployment Monitoring**

**Monitor for 24-48 hours:**

- [ ] Check Application Insights for errors
- [ ] Monitor authentication success rate
- [ ] Check API response times
- [ ] Verify group claims in tokens
- [ ] Monitor database query performance
- [ ] Check blob storage access patterns
- [ ] Review user feedback

**Key metrics:**
```bash
# Check for auth errors
az monitor app-insights query --app <app> --analytics-query "exceptions | where timestamp > ago(1h) | where message contains '401'"

# Check API success rate
az monitor app-insights query --app <app> --analytics-query "requests | where timestamp > ago(1h) | summarize success_rate = 100.0 * countif(success == true) / count()"
```

---

## 🔍 **Troubleshooting Guide**

### **Issue: 401 Unauthorized Errors**

**Symptoms:** API returns 401, frontend can't fetch data

**Solutions:**
- [ ] Verify token contains `groups` claim (jwt.ms)
- [ ] Check backend extracts groups correctly
- [ ] Verify Azure Container Apps auth config
- [ ] Check CORS settings
- [ ] Logout and login to get fresh token

---

### **Issue: 403 Forbidden Errors**

**Symptoms:** User authenticated but can't access resource

**Solutions:**
- [ ] Verify user belongs to the group
- [ ] Check `X-Group-ID` header is sent
- [ ] Verify backend validates group membership
- [ ] Check database query includes correct group filter

---

### **Issue: Groups Claim Missing**

**Symptoms:** Token decoded but no groups array

**Solutions:**
- [ ] Verify token configuration in Azure Portal
- [ ] Check optional claims are set
- [ ] Verify groupMembershipClaims = "SecurityGroup"
- [ ] Wait 10 minutes for Azure AD propagation
- [ ] Force logout/login

---

### **Issue: Data Not Visible After Group Switch**

**Symptoms:** User switches groups but sees wrong data

**Solutions:**
- [ ] Check frontend reloads data on group change
- [ ] Verify API includes X-Group-ID header
- [ ] Check backend filters by group_id
- [ ] Clear browser cache
- [ ] Check database records have group_id set

---

### **Issue: Migration Failed**

**Symptoms:** Some records not updated

**Solutions:**
- [ ] Review migration script logs
- [ ] Check user_group_mapping.json is complete
- [ ] Verify all user_ids are mapped
- [ ] Re-run migration with dry-run
- [ ] Manually update remaining records

---

## 📊 **Success Criteria**

### **Must Have:**
- [ ] All users can login and see their groups
- [ ] Users with multiple groups can switch between them
- [ ] Data is isolated between groups (cross-group access blocked)
- [ ] All new data includes group_id
- [ ] All existing data migrated to groups
- [ ] No 401/403 errors for valid users
- [ ] Performance is acceptable (< 500ms API response)

### **Nice to Have:**
- [ ] Group names displayed (not IDs)
- [ ] Analytics on group usage
- [ ] Admin UI to manage group memberships
- [ ] Audit log of group access
- [ ] Automated group assignment

---

## 📝 **Final Verification**

Before marking complete, verify:

- [ ] All checklist items completed
- [ ] All tests passing
- [ ] Production deployment successful
- [ ] No critical errors in logs
- [ ] Users can access their data
- [ ] Documentation updated
- [ ] Team trained on new workflow
- [ ] Rollback plan documented

---

## 🎉 **Completion**

**Completed Date:** _______________  
**Deployed By:** _______________  
**Sign-off:** _______________

---

**Next Steps:**
- Monitor for 1 week
- Collect user feedback
- Plan enhancements (group admin UI, analytics, etc.)
- Document lessons learned
