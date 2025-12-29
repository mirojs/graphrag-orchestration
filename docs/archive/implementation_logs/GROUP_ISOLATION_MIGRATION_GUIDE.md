# 🔒 Group Isolation Migration Guide - Step by Step

## 📋 Executive Summary

This guide walks you through implementing **group-based data isolation** where users within a group can share documents, but groups are isolated from each other.

### **Migration Overview**
- **Duration**: 5-7 days (can be done incrementally)
- **Downtime Required**: None (blue-green deployment supported)
- **Rollback Support**: Yes (detailed in each phase)
- **Azure Config Changes**: Minimal (Azure AD only)
- **Code Changes**: Moderate (backend + frontend)

---

## 🎯 Decision Point: Choose Your Group Strategy

Before starting, you must choose between two approaches:

### **Option A: Azure AD Security Groups** ⭐ **RECOMMENDED**
**Use when:** You want groups managed by IT/admins in Azure AD

**Pros:**
- ✅ Centralized group management in Azure AD Portal
- ✅ Integrates with existing enterprise groups
- ✅ IT can manage group membership independently
- ✅ Supports dynamic group membership (based on user attributes)
- ✅ Better for enterprise/organizational scenarios
- ✅ Works across multiple applications
- ✅ Easier compliance and auditing

**Cons:**
- ⚠️ Requires Azure AD admin permissions to create groups
- ⚠️ Group IDs are GUIDs (need mapping to friendly names)
- ⚠️ Can't easily customize group properties in your app

**Token structure:**
```json
{
  "oid": "user-id",
  "groups": [
    "a1234567-89ab-cdef-0123-456789abcdef",  // Marketing Group ID
    "b2345678-90bc-def0-1234-56789abcdef0"   // Sales Group ID
  ]
}
```

---

### **Option B: App Roles**
**Use when:** You want application-specific groups managed by developers

**Pros:**
- ✅ Application-specific group definitions
- ✅ Custom role names (e.g., "Marketing.Member", "Sales.Admin")
- ✅ Can define permissions in app manifest
- ✅ Easier to work with in code (string values vs GUIDs)
- ✅ Good for SaaS applications

**Cons:**
- ⚠️ Requires app manifest updates for new groups
- ⚠️ Less integration with enterprise identity
- ⚠️ Groups only work for this application
- ⚠️ Manual assignment of users to roles

**Token structure:**
```json
{
  "oid": "user-id",
  "roles": [
    "Marketing.Member",
    "Sales.Admin"
  ]
}
```

---

## 🏆 **RECOMMENDATION: Use Azure AD Security Groups (Option A)**

### **Why Security Groups Win for Your Scenario:**

1. **Enterprise Ready**: Your application appears to be an enterprise document processing system. Security groups align with how enterprises manage access.

2. **IT-Friendly**: IT departments can manage group membership without developer involvement.

3. **Scalability**: As your app grows, IT can create/manage groups independently.

4. **Compliance**: Better audit trails and compliance reporting through Azure AD.

5. **Multi-Application**: If you add more apps later, same groups can be reused.

6. **Dynamic Groups**: Can auto-assign users to groups based on department, location, etc.

### **When to Consider App Roles Instead:**
- You're building a SaaS product for external customers
- You need application-specific permissions (not just group membership)
- You want complete control over role definitions in code
- Groups are purely application concepts (not organizational)

---

## 📅 Migration Timeline

### **Phase 1: Planning & Preparation** (Day 1)
- Inventory existing data
- Define groups structure
- Create test plan
- Set up staging environment

### **Phase 2: Azure AD Configuration** (Day 1-2)
- Create security groups
- Configure token claims
- Test token structure
- Assign test users

### **Phase 3: Backend Implementation** (Day 2-4)
- Update authentication layer
- Update data models
- Update database queries
- Update blob storage logic
- Unit testing

### **Phase 4: Frontend Updates** (Day 4-5)
- Add group selector UI
- Update API calls
- Update file upload/download
- Integration testing

### **Phase 5: Data Migration** (Day 5-6)
- Migrate existing data to group structure
- Verify data integrity
- Test cross-group isolation

### **Phase 6: Deployment & Validation** (Day 6-7)
- Staged deployment
- Smoke testing
- User acceptance testing
- Monitoring

---

# 🚀 PHASE 1: Planning & Preparation

## Step 1.1: Inventory Current Data

Create a script to analyze your current data:

```python
# scripts/analyze_current_data.py
"""
Analyze current data structure before migration.
This helps you understand the scope and plan group assignments.
"""

import asyncio
from azure.cosmos.aio import CosmosClient
from azure.storage.blob.aio import BlobServiceClient
from datetime import datetime
import json

async def analyze_current_data():
    """Analyze current user-based data"""
    
    print("🔍 ANALYZING CURRENT DATA STRUCTURE")
    print("=" * 60)
    
    # Cosmos DB analysis
    cosmos_client = CosmosClient.from_connection_string(COSMOS_CONN_STR)
    db = cosmos_client.get_database_client(DB_NAME)
    
    # Analyze schemas
    schema_container = db.get_container_client("pro_schemas")
    schemas = await schema_container.read_all_items()
    
    user_schema_counts = {}
    total_schemas = 0
    
    async for schema in schemas:
        total_schemas += 1
        user_id = schema.get('user_id', 'unknown')
        user_schema_counts[user_id] = user_schema_counts.get(user_id, 0) + 1
    
    # Analyze blob storage
    blob_client = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
    containers = blob_client.list_containers()
    
    user_containers = []
    total_blobs = 0
    
    async for container in containers:
        if container.name.startswith('user-'):
            user_id = container.name.replace('user-', '')
            container_client = blob_client.get_container_client(container.name)
            
            blob_count = 0
            total_size = 0
            async for blob in container_client.list_blobs():
                blob_count += 1
                total_size += blob.size
            
            user_containers.append({
                'user_id': user_id,
                'blob_count': blob_count,
                'total_size_mb': total_size / (1024 * 1024)
            })
            total_blobs += blob_count
    
    # Generate report
    report = {
        'analysis_date': datetime.utcnow().isoformat(),
        'database_analysis': {
            'total_schemas': total_schemas,
            'unique_users': len(user_schema_counts),
            'schemas_per_user': user_schema_counts
        },
        'storage_analysis': {
            'total_user_containers': len(user_containers),
            'total_blobs': total_blobs,
            'containers_by_user': user_containers
        },
        'migration_estimates': {
            'estimated_groups_needed': max(5, len(user_schema_counts) // 10),
            'users_to_assign': len(user_schema_counts),
            'data_to_migrate_mb': sum(c['total_size_mb'] for c in user_containers)
        }
    }
    
    # Save report
    with open('data_analysis_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    
    print("\n📊 ANALYSIS COMPLETE")
    print(f"   Total Schemas: {total_schemas}")
    print(f"   Unique Users: {len(user_schema_counts)}")
    print(f"   Total Blobs: {total_blobs}")
    print(f"   Total Storage: {sum(c['total_size_mb'] for c in user_containers):.2f} MB")
    print(f"\n   Report saved to: data_analysis_report.json")
    
    await cosmos_client.close()
    await blob_client.close()

if __name__ == "__main__":
    asyncio.run(analyze_current_data())
```

**Action Items:**
- [ ] Run the analysis script
- [ ] Review the data_analysis_report.json
- [ ] Identify how many groups you'll need
- [ ] Plan initial group structure (e.g., by department, team, project)

---

## Step 1.2: Define Group Structure

Create a group planning document:

```yaml
# groups_structure.yaml
# Define your organizational groups

groups:
  - name: "Marketing Team"
    description: "Marketing department members"
    estimated_users: 15
    expected_data_volume: "500 MB"
    initial_members:
      - user@company.com
      - marketing.lead@company.com
    
  - name: "Sales Team"
    description: "Sales department members"
    estimated_users: 20
    expected_data_volume: "1 GB"
    initial_members:
      - sales.manager@company.com
      - sales.rep1@company.com
    
  - name: "Engineering Team"
    description: "Engineering department"
    estimated_users: 30
    expected_data_volume: "2 GB"
    initial_members:
      - eng.lead@company.com
      - developer1@company.com
    
  - name: "Executive Team"
    description: "C-level and executives"
    estimated_users: 5
    expected_data_volume: "200 MB"
    initial_members:
      - ceo@company.com
      - cfo@company.com

# User to group mapping (for migration)
user_group_mapping:
  "user1@company.com": ["Marketing Team"]
  "user2@company.com": ["Sales Team", "Marketing Team"]  # Multi-group user
  "user3@company.com": ["Engineering Team"]
  # ... add all users
```

**Action Items:**
- [ ] Create groups_structure.yaml
- [ ] Define all groups needed
- [ ] Map existing users to groups
- [ ] Identify users who need multi-group access
- [ ] Get approval from stakeholders

---

## Step 1.3: Set Up Test Environment

```bash
# scripts/setup_test_environment.sh
#!/bin/bash

echo "🧪 Setting up test environment for group isolation migration"

# 1. Create test resource group (if needed)
TEST_RG="rg-cps-test-group-isolation"
LOCATION="eastus2"

az group create \
  --name $TEST_RG \
  --location $LOCATION

# 2. Create test storage account
TEST_STORAGE="stcpstestgroups$(date +%s)"

az storage account create \
  --name $TEST_STORAGE \
  --resource-group $TEST_RG \
  --location $LOCATION \
  --sku Standard_LRS

# 3. Create test Cosmos DB account
TEST_COSMOS="cosmos-cps-test-groups"

az cosmosdb create \
  --name $TEST_COSMOS \
  --resource-group $TEST_RG \
  --kind MongoDB

# 4. Create test Azure AD groups
echo "📋 You'll need to create these groups in Azure AD Portal:"
echo "   - TEST-Marketing-Team"
echo "   - TEST-Sales-Team"
echo "   - TEST-Engineering-Team"

echo "✅ Test environment setup complete"
echo "   Resource Group: $TEST_RG"
echo "   Storage: $TEST_STORAGE"
echo "   Cosmos DB: $TEST_COSMOS"
```

**Action Items:**
- [ ] Run setup script
- [ ] Verify test resources created
- [ ] Create test data in test environment
- [ ] Document test environment details

---

# 🔐 PHASE 2: Azure AD Configuration

## Step 2.1: Create Security Groups in Azure AD

### **Via Azure Portal (Recommended for initial setup):**

1. **Navigate to Azure Active Directory**
   - Go to [Azure Portal](https://portal.azure.com)
   - Click **Azure Active Directory**

2. **Create Groups**
   - Click **Groups** → **New group**
   - For each group in your groups_structure.yaml:

   ```
   Group type: Security
   Group name: Marketing Team
   Group description: Marketing department document access
   Membership type: Assigned (or Dynamic if using rules)
   
   Members: Add initial members from groups_structure.yaml
   ```

3. **Note Group Object IDs**
   - After creating each group, click on it
   - Copy the **Object ID** (this is the group_id used in code)
   - Create a mapping file:

```json
// group_id_mapping.json
{
  "Marketing Team": {
    "object_id": "a1234567-89ab-cdef-0123-456789abcdef",
    "description": "Marketing department",
    "created_date": "2025-10-16"
  },
  "Sales Team": {
    "object_id": "b2345678-90bc-def0-1234-56789abcdef0",
    "description": "Sales department",
    "created_date": "2025-10-16"
  },
  "Engineering Team": {
    "object_id": "c3456789-01cd-ef01-2345-6789abcdef01",
    "description": "Engineering department",
    "created_date": "2025-10-16"
  }
}
```

### **Via Azure CLI (For automation):**

```bash
# scripts/create_azure_ad_groups.sh
#!/bin/bash

echo "🏢 Creating Azure AD Security Groups"

# Read groups from YAML (you'll need yq tool or convert to JSON)
GROUPS=(
  "Marketing Team:Marketing department members"
  "Sales Team:Sales department members"
  "Engineering Team:Engineering department"
)

GROUP_IDS_FILE="group_id_mapping.json"
echo "{" > $GROUP_IDS_FILE

for GROUP_INFO in "${GROUPS[@]}"; do
  IFS=':' read -r GROUP_NAME GROUP_DESC <<< "$GROUP_INFO"
  
  echo "Creating group: $GROUP_NAME"
  
  # Create group
  GROUP_ID=$(az ad group create \
    --display-name "$GROUP_NAME" \
    --mail-nickname "$(echo $GROUP_NAME | tr ' ' '-' | tr '[:upper:]' '[:lower:]')" \
    --description "$GROUP_DESC" \
    --query objectId -o tsv)
  
  echo "  \"$GROUP_NAME\": {"
  echo "    \"object_id\": \"$GROUP_ID\","
  echo "    \"description\": \"$GROUP_DESC\","
  echo "    \"created_date\": \"$(date -I)\""
  echo "  },"
  
  echo "✅ Created: $GROUP_NAME (ID: $GROUP_ID)"
done

echo "}" >> $GROUP_IDS_FILE

echo "✅ All groups created. IDs saved to $GROUP_IDS_FILE"
```

**Action Items:**
- [ ] Create all security groups (portal or CLI)
- [ ] Save group_id_mapping.json
- [ ] Verify groups visible in Azure AD
- [ ] Add yourself as test user to multiple groups

---

## Step 2.2: Configure Token to Include Group Claims

### **Method 1: Via Azure Portal (Easiest)**

1. **Navigate to App Registrations**
   - Azure Portal → Azure Active Directory → App registrations
   - Select your **API app registration**

2. **Add Groups Claim**
   - Click **Token configuration** (left sidebar)
   - Click **+ Add groups claim**
   - Select:
     - ✅ **Security groups**
     - ✅ **Group ID** (not sAMAccountName)
   - Click **Add**

3. **Verify Configuration**
   - Under "Token configuration", you should see:
     ```
     Claim: groups
     Claim type: groups
     Token type: ID, Access
     Source: Group membership
     ```

### **Method 2: Via App Manifest (For automation)**

1. **Edit Manifest**
   - In your app registration, click **Manifest**
   - Find `groupMembershipClaims` (should be `null`)
   - Change to:

```json
{
  "groupMembershipClaims": "SecurityGroup",
  "optionalClaims": {
    "idToken": [
      {
        "name": "groups",
        "source": null,
        "essential": false,
        "additionalProperties": []
      }
    ],
    "accessToken": [
      {
        "name": "groups",
        "source": null,
        "essential": false,
        "additionalProperties": []
      }
    ],
    "saml2Token": []
  }
}
```

2. **Save Manifest**

### **Important: Group Overage Handling**

If users are in more than 200 groups, Azure AD uses group overage claim instead:

```json
{
  "_claim_names": {
    "groups": "src1"
  },
  "_claim_sources": {
    "src1": {
      "endpoint": "https://graph.microsoft.com/v1.0/users/{user_id}/getMemberObjects"
    }
  }
}
```

**Handle this in code:**

```python
# backend/app/auth/group_resolver.py
from typing import List
import requests

async def resolve_user_groups(token_claims: dict, access_token: str) -> List[str]:
    """
    Resolve user groups, handling group overage claim.
    """
    # Direct groups in token (< 200 groups)
    if "groups" in token_claims:
        return token_claims["groups"]
    
    # Group overage - need to call Graph API
    if "_claim_names" in token_claims and "groups" in token_claims["_claim_names"]:
        graph_endpoint = token_claims["_claim_sources"]["src1"]["endpoint"]
        
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        
        response = requests.post(
            graph_endpoint,
            headers=headers,
            json={"securityEnabledOnly": True}
        )
        
        if response.status_code == 200:
            return response.json().get("value", [])
    
    # No groups found
    return []
```

**Action Items:**
- [ ] Configure token to include group claims
- [ ] Test with a user account
- [ ] Verify groups appear in JWT token
- [ ] Implement group overage handling (if needed)

---

## Step 2.3: Test Token Structure

Create a token verification script:

```python
# scripts/verify_token_groups.py
"""
Verify that Azure AD tokens now include group claims.
Run this after configuring token claims.
"""

import jwt
import json
import requests
from typing import Dict, Any

def decode_token_without_verification(token: str) -> Dict[str, Any]:
    """Decode JWT without verification for inspection"""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception as e:
        print(f"❌ Error decoding token: {e}")
        return {}

def verify_group_claims(token: str, group_mapping_file: str = "group_id_mapping.json"):
    """Verify token contains expected group claims"""
    
    print("🔍 VERIFYING TOKEN GROUP CLAIMS")
    print("=" * 60)
    
    # Decode token
    claims = decode_token_without_verification(token)
    
    if not claims:
        print("❌ Failed to decode token")
        return False
    
    # Check for groups claim
    has_groups = "groups" in claims
    has_overage = "_claim_names" in claims and "groups" in claims.get("_claim_names", {})
    
    print("\n📋 Token Claims Analysis:")
    print(f"   User ID (oid): {claims.get('oid', 'MISSING ❌')}")
    print(f"   Tenant ID (tid): {claims.get('tid', 'MISSING ❌')}")
    print(f"   Email: {claims.get('preferred_username', 'MISSING ❌')}")
    print(f"   Groups claim present: {'✅ YES' if has_groups else '❌ NO'}")
    print(f"   Group overage: {'⚠️ YES' if has_overage else '✅ NO'}")
    
    if has_groups:
        groups = claims["groups"]
        print(f"\n👥 User Groups ({len(groups)}):")
        
        # Load group mapping
        try:
            with open(group_mapping_file, 'r') as f:
                group_mapping = json.load(f)
            
            # Reverse mapping (ID -> Name)
            id_to_name = {v["object_id"]: k for k, v in group_mapping.items()}
            
            for group_id in groups:
                group_name = id_to_name.get(group_id, "Unknown Group")
                print(f"   - {group_id} ({group_name})")
        except:
            for group_id in groups:
                print(f"   - {group_id}")
    
    elif has_overage:
        print("\n⚠️ GROUP OVERAGE DETECTED")
        print("   User is in more than 200 groups.")
        print("   You'll need to call Microsoft Graph API to get full list.")
        print(f"   Endpoint: {claims['_claim_sources']['src1']['endpoint']}")
    
    else:
        print("\n❌ NO GROUPS FOUND IN TOKEN")
        print("   Possible issues:")
        print("   1. Token configuration not updated")
        print("   2. User not assigned to any groups")
        print("   3. Wrong app registration configured")
        return False
    
    print("\n✅ TOKEN VERIFICATION COMPLETE")
    return has_groups or has_overage

def main():
    print("🔐 Azure AD Token Group Claims Verification")
    print("=" * 60)
    print("\n📝 How to get your token:")
    print("   1. Log into your application")
    print("   2. Open Browser DevTools (F12)")
    print("   3. Go to Console tab")
    print("   4. Run: localStorage")
    print("   5. Find your MSAL token")
    print("\n   OR")
    print("   1. Go to Network tab in DevTools")
    print("   2. Make an API call")
    print("   3. Look at Request Headers → Authorization")
    print("   4. Copy the Bearer token\n")
    
    token = input("Paste your JWT token here: ").strip()
    
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "")
    
    verify_group_claims(token)

if __name__ == "__main__":
    main()
```

**Action Items:**
- [ ] Log into your application
- [ ] Extract JWT token from browser
- [ ] Run verification script
- [ ] Confirm groups appear in token
- [ ] Document any issues

---

## Step 2.4: Assign Users to Groups

### **Via Azure Portal:**

For each group:
1. Go to **Azure AD** → **Groups** → Select group
2. Click **Members** → **+ Add members**
3. Search for users
4. Select and add

### **Via PowerShell (Bulk assignment):**

```powershell
# scripts/assign_users_to_groups.ps1
# Bulk assign users to groups based on groups_structure.yaml

# Connect to Azure AD
Connect-AzureAD

# Read user-group mapping (convert your YAML to CSV first)
$mappings = Import-Csv -Path "user_group_mapping.csv"
# CSV format: UserEmail, GroupName

foreach ($mapping in $mappings) {
    $userEmail = $mapping.UserEmail
    $groupName = $mapping.GroupName
    
    Write-Host "Assigning $userEmail to $groupName..."
    
    try {
        # Get user
        $user = Get-AzureADUser -Filter "userPrincipalName eq '$userEmail'"
        
        # Get group
        $group = Get-AzureADGroup -Filter "displayName eq '$groupName'"
        
        # Add user to group
        Add-AzureADGroupMember -ObjectId $group.ObjectId -RefObjectId $user.ObjectId
        
        Write-Host "✅ Success: $userEmail → $groupName" -ForegroundColor Green
    }
    catch {
        Write-Host "❌ Failed: $userEmail → $groupName - $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`n✅ User assignment complete"
```

**Create user_group_mapping.csv:**
```csv
UserEmail,GroupName
user1@company.com,Marketing Team
user2@company.com,Sales Team
user2@company.com,Marketing Team
user3@company.com,Engineering Team
```

**Action Items:**
- [ ] Convert groups_structure.yaml to user_group_mapping.csv
- [ ] Run assignment script OR assign manually
- [ ] Verify users see their group memberships in Azure AD
- [ ] Test user tokens contain correct groups

---

# 💻 PHASE 3: Backend Implementation

## Step 3.1: Update Authentication Layer

### **Update UserContext Model**

```python
# backend/app/models/user_context.py
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class UserContext:
    """
    Enhanced user context with group membership.
    Extracted from Azure AD JWT token.
    """
    user_id: str              # oid claim
    email: str                # preferred_username or upn
    name: str                 # name claim
    tenant_id: str            # tid claim
    groups: List[str]         # NEW: groups claim (list of group object IDs)
    
    # Optional metadata
    primary_group: Optional[str] = None  # User's default group
    is_admin: bool = False
    
    def has_group_access(self, group_id: str) -> bool:
        """Check if user belongs to specific group"""
        return group_id in self.groups
    
    def has_any_group_access(self, group_ids: List[str]) -> bool:
        """Check if user belongs to any of the specified groups"""
        return any(gid in self.groups for gid in group_ids)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for logging/serialization"""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "tenant_id": self.tenant_id,
            "groups": self.groups,
            "primary_group": self.primary_group,
            "group_count": len(self.groups)
        }
```

**Action Items:**
- [ ] Create/update user_context.py
- [ ] Add unit tests for UserContext
- [ ] Test has_group_access methods

---

### **Update Authentication Dependency**

```python
# backend/app/auth/dependencies.py
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from typing import List
import os
from app.models.user_context import UserContext
from app.auth.group_resolver import resolve_user_groups

security = HTTPBearer()

# Azure AD configuration
AZURE_AD_TENANT_ID = os.getenv("AZURE_AD_TENANT_ID")
AZURE_AD_CLIENT_ID = os.getenv("AZURE_AD_CLIENT_ID")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserContext:
    """
    Extract user context from JWT token with group membership.
    
    This validates the token and extracts:
    - User ID (oid)
    - Tenant ID (tid)
    - Email (preferred_username)
    - Groups (groups claim or via Graph API if overage)
    
    Raises:
        HTTPException 401: If token is invalid
        HTTPException 403: If user has no group assignments
    """
    token = credentials.credentials
    
    try:
        # Decode token (in dev: without verification, in prod: with verification)
        if os.getenv("APP_ENV", "prod").lower() == "dev":
            claims = jwt.decode(token, options={"verify_signature": False})
        else:
            # TODO: Implement proper JWT signature validation
            # See: https://github.com/Intility/fastapi-azure-auth
            claims = jwt.decode(token, options={"verify_signature": False})
        
        # Extract standard claims
        user_id = claims.get("oid")
        email = claims.get("preferred_username") or claims.get("upn")
        name = claims.get("name")
        tenant_id = claims.get("tid")
        
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user ID (oid claim)"
            )
        
        # Extract groups (NEW!)
        groups = await resolve_user_groups(claims, token)
        
        if not groups:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User must be assigned to at least one group"
            )
        
        # Determine primary group (first group, or load from user preferences)
        primary_group = groups[0] if groups else None
        
        # TODO: Load user's preferred primary group from database
        
        return UserContext(
            user_id=user_id,
            email=email or "unknown",
            name=name or "unknown",
            tenant_id=tenant_id or "unknown",
            groups=groups,
            primary_group=primary_group
        )
        
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing authentication: {str(e)}"
        )

async def require_group_access(
    group_id: str,
    current_user: UserContext = Depends(get_current_user)
) -> UserContext:
    """
    Dependency that requires user to have access to specific group.
    
    Usage:
        @router.get("/groups/{group_id}/schemas")
        async def get_schemas(
            group_id: str,
            user: UserContext = Depends(require_group_access)
        ):
            # User is guaranteed to have access to this group
    """
    if not current_user.has_group_access(group_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"User does not have access to group {group_id}"
        )
    return current_user
```

**Action Items:**
- [ ] Update dependencies.py
- [ ] Add group_resolver.py (from Step 2.2)
- [ ] Test authentication with group claims
- [ ] Test unauthorized access rejection

---

## Step 3.2: Update Data Models

### **Update Schema Model**

```python
# backend/app/models/schema.py
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field

class SchemaBase(BaseModel):
    """Base schema model"""
    name: str
    description: Optional[str] = None
    fields: List[Dict[str, Any]] = []
    schema_version: str = "1.0"

class SchemaCreate(SchemaBase):
    """Schema creation request"""
    group_id: str = Field(..., description="Group that owns this schema")

class SchemaUpdate(BaseModel):
    """Schema update request"""
    name: Optional[str] = None
    description: Optional[str] = None
    fields: Optional[List[Dict[str, Any]]] = None

class Schema(SchemaBase):
    """Complete schema model with metadata"""
    id: str
    group_id: str = Field(..., description="Group that owns this schema")
    tenant_id: str
    created_by: str  # user_id
    created_at: datetime
    updated_at: datetime
    
    # Optional: track all users who can access
    accessible_by_groups: List[str] = Field(default_factory=list)
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "schema-123",
                "name": "Purchase Order Schema",
                "description": "Schema for processing purchase orders",
                "group_id": "a1234567-89ab-cdef-0123-456789abcdef",
                "tenant_id": "tenant-123",
                "created_by": "user-456",
                "fields": [
                    {"name": "vendor", "type": "string"},
                    {"name": "amount", "type": "number"}
                ],
                "created_at": "2025-10-16T10:00:00Z",
                "updated_at": "2025-10-16T10:00:00Z"
            }
        }

# Similar updates for other models
class FileMetadata(BaseModel):
    """File metadata with group ownership"""
    id: str
    name: str
    size: int
    group_id: str  # NEW
    tenant_id: str
    uploaded_by: str
    uploaded_at: datetime
    file_type: str

class AnalysisResult(BaseModel):
    """Analysis result with group ownership"""
    id: str
    file_id: str
    schema_id: str
    group_id: str  # NEW
    tenant_id: str
    created_by: str
    created_at: datetime
    results: Dict[str, Any]
```

**Action Items:**
- [ ] Update all data models to include group_id
- [ ] Add validation for group_id field
- [ ] Update API documentation/OpenAPI schema
- [ ] Create database migration scripts

---

## Step 3.3: Update Database Queries

### **Schema Service with Group Filtering**

```python
# backend/app/services/schema_service.py
from typing import List, Optional
from fastapi import HTTPException
from app.models.user_context import UserContext
from app.models.schema import Schema, SchemaCreate, SchemaUpdate
import uuid
from datetime import datetime

class SchemaService:
    """Schema service with group-based access control"""
    
    def __init__(self, db_client):
        self.db = db_client
        self.collection = db_client.get_collection("pro_schemas")
    
    async def get_user_schemas(
        self,
        user_context: UserContext,
        group_id: Optional[str] = None
    ) -> List[Schema]:
        """
        Get schemas accessible to user.
        
        Args:
            user_context: Current user context with group memberships
            group_id: Optional - filter to specific group, otherwise all user's groups
        
        Returns:
            List of schemas user can access
        """
        # Build query filter
        query = {
            "tenant_id": user_context.tenant_id
        }
        
        if group_id:
            # Filter to specific group (user must have access)
            if not user_context.has_group_access(group_id):
                raise HTTPException(403, f"No access to group {group_id}")
            query["group_id"] = group_id
        else:
            # Filter to all groups user belongs to
            query["group_id"] = {"$in": user_context.groups}
        
        # Execute query
        results = await self.collection.find(query).to_list(length=1000)
        
        return [Schema(**result) for result in results]
    
    async def get_schema_by_id(
        self,
        schema_id: str,
        user_context: UserContext
    ) -> Schema:
        """
        Get specific schema if user has group access.
        
        Raises:
            HTTPException 404: Schema not found
            HTTPException 403: No access to schema's group
        """
        schema = await self.collection.find_one({"id": schema_id})
        
        if not schema:
            raise HTTPException(404, f"Schema {schema_id} not found")
        
        # Verify user has access to schema's group
        if not user_context.has_group_access(schema["group_id"]):
            raise HTTPException(
                403,
                f"No access to schema {schema_id} (requires group {schema['group_id']})"
            )
        
        return Schema(**schema)
    
    async def create_schema(
        self,
        schema_data: SchemaCreate,
        user_context: UserContext
    ) -> Schema:
        """
        Create new schema in specified group.
        
        Args:
            schema_data: Schema creation data including group_id
            user_context: Current user
        
        Returns:
            Created schema
        
        Raises:
            HTTPException 403: User not member of specified group
        """
        # Verify user belongs to target group
        if not user_context.has_group_access(schema_data.group_id):
            raise HTTPException(
                403,
                f"Cannot create schema in group {schema_data.group_id} - not a member"
            )
        
        # Create schema document
        schema = {
            "id": str(uuid.uuid4()),
            "name": schema_data.name,
            "description": schema_data.description,
            "fields": schema_data.fields,
            "schema_version": schema_data.schema_version,
            "group_id": schema_data.group_id,
            "tenant_id": user_context.tenant_id,
            "created_by": user_context.user_id,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Insert into database
        await self.collection.insert_one(schema)
        
        return Schema(**schema)
    
    async def update_schema(
        self,
        schema_id: str,
        updates: SchemaUpdate,
        user_context: UserContext
    ) -> Schema:
        """
        Update schema if user has group access.
        
        Raises:
            HTTPException 403: No access to modify this schema
        """
        # Get existing schema (verifies access)
        existing = await self.get_schema_by_id(schema_id, user_context)
        
        # Build update document
        update_doc = {
            "updated_at": datetime.utcnow()
        }
        
        if updates.name is not None:
            update_doc["name"] = updates.name
        if updates.description is not None:
            update_doc["description"] = updates.description
        if updates.fields is not None:
            update_doc["fields"] = updates.fields
        
        # Update in database
        await self.collection.update_one(
            {"id": schema_id},
            {"$set": update_doc}
        )
        
        # Return updated schema
        return await self.get_schema_by_id(schema_id, user_context)
    
    async def delete_schema(
        self,
        schema_id: str,
        user_context: UserContext
    ) -> bool:
        """
        Delete schema if user has group access.
        
        Raises:
            HTTPException 403: No access to delete this schema
        """
        # Get existing schema (verifies access)
        await self.get_schema_by_id(schema_id, user_context)
        
        # Delete from database
        result = await self.collection.delete_one({"id": schema_id})
        
        return result.deleted_count > 0
    
    async def get_group_statistics(
        self,
        group_id: str,
        user_context: UserContext
    ) -> dict:
        """Get statistics for group's schemas"""
        
        if not user_context.has_group_access(group_id):
            raise HTTPException(403, f"No access to group {group_id}")
        
        # Aggregate statistics
        pipeline = [
            {"$match": {
                "group_id": group_id,
                "tenant_id": user_context.tenant_id
            }},
            {"$group": {
                "_id": None,
                "total_schemas": {"$sum": 1},
                "unique_creators": {"$addToSet": "$created_by"},
                "last_created": {"$max": "$created_at"}
            }}
        ]
        
        result = await self.collection.aggregate(pipeline).to_list(length=1)
        
        if result:
            stats = result[0]
            return {
                "group_id": group_id,
                "total_schemas": stats["total_schemas"],
                "unique_contributors": len(stats["unique_creators"]),
                "last_activity": stats["last_created"]
            }
        
        return {
            "group_id": group_id,
            "total_schemas": 0,
            "unique_contributors": 0,
            "last_activity": None
        }
```

**Action Items:**
- [ ] Create schema_service.py
- [ ] Add similar services for files, analyses
- [ ] Write unit tests for group access checks
- [ ] Test with multi-group users

---

## Step 3.4: Update Blob Storage Logic

### **Group-Based Blob Storage Service**

```python
# backend/app/services/blob_storage_service.py
from azure.storage.blob.aio import BlobServiceClient
from azure.core.exceptions import ResourceExistsError
from typing import List, Dict, Optional
from fastapi import HTTPException
import os
from app.models.user_context import UserContext

class GroupBlobStorageService:
    """
    Blob storage service with group-based isolation.
    Uses separate containers per group for maximum isolation.
    """
    
    def __init__(self, connection_string: str):
        self.blob_service = BlobServiceClient.from_connection_string(
            connection_string
        )
    
    def _sanitize_for_container_name(self, text: str) -> str:
        """
        Sanitize text for Azure container naming.
        
        Rules:
        - Lowercase letters, numbers, hyphens only
        - 3-63 characters
        - Must start with letter or number
        """
        # Convert to lowercase, replace invalid chars with hyphen
        sanitized = ''.join(
            c if c.isalnum() else '-' 
            for c in text.lower()
        )
        
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        
        # Ensure starts with letter/number
        if sanitized and not sanitized[0].isalnum():
            sanitized = 'g' + sanitized
        
        # Truncate to 63 chars
        return sanitized[:63]
    
    def _get_group_container_name(
        self,
        tenant_id: str,
        group_id: str
    ) -> str:
        """
        Generate container name for group.
        
        Format: tenant-{sanitized_tenant}-group-{sanitized_group_id}
        Example: tenant-abc123-group-marketing456
        """
        safe_tenant = self._sanitize_for_container_name(tenant_id)[:20]
        safe_group = self._sanitize_for_container_name(group_id)[:20]
        
        return f"tenant-{safe_tenant}-group-{safe_group}"
    
    async def ensure_group_container(
        self,
        tenant_id: str,
        group_id: str
    ) -> str:
        """
        Ensure group container exists, create if needed.
        
        Returns:
            Container name
        """
        container_name = self._get_group_container_name(tenant_id, group_id)
        container_client = self.blob_service.get_container_client(container_name)
        
        try:
            await container_client.create_container(
                metadata={
                    'tenant_id': tenant_id,
                    'group_id': group_id,
                    'created_at': datetime.utcnow().isoformat()
                }
            )
            print(f"✅ Created container: {container_name}")
        except ResourceExistsError:
            pass  # Container already exists
        
        return container_name
    
    async def upload_group_file(
        self,
        user_context: UserContext,
        group_id: str,
        file_name: str,
        file_content: bytes,
        content_type: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Upload file to group's container.
        
        Args:
            user_context: Current user (must be group member)
            group_id: Target group
            file_name: Name of file
            file_content: File bytes
            content_type: MIME type (optional)
        
        Returns:
            Dict with url, blob_name, container_name
        
        Raises:
            HTTPException 403: User not member of group
        """
        # Verify user has access to group
        if not user_context.has_group_access(group_id):
            raise HTTPException(
                403,
                f"Cannot upload to group {group_id} - not a member"
            )
        
        # Ensure container exists
        container_name = await self.ensure_group_container(
            user_context.tenant_id,
            group_id
        )
        
        # Build blob path: users/{user_id}/{file_name}
        blob_path = f"users/{user_context.user_id}/{file_name}"
        
        # Get blob client
        container_client = self.blob_service.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_path)
        
        # Upload with metadata
        metadata = {
            'uploaded_by': user_context.email,
            'user_id': user_context.user_id,
            'group_id': group_id,
            'tenant_id': user_context.tenant_id,
            'uploaded_at': datetime.utcnow().isoformat()
        }
        
        await blob_client.upload_blob(
            file_content,
            overwrite=True,
            metadata=metadata,
            content_settings={'content_type': content_type} if content_type else None
        )
        
        return {
            'url': blob_client.url,
            'blob_name': blob_path,
            'container_name': container_name,
            'group_id': group_id
        }
    
    async def list_group_files(
        self,
        user_context: UserContext,
        group_id: str,
        prefix: Optional[str] = None
    ) -> List[Dict]:
        """
        List all files in group container.
        
        Args:
            user_context: Current user
            group_id: Group to list files from
            prefix: Optional path prefix filter
        
        Returns:
            List of file metadata dicts
        """
        if not user_context.has_group_access(group_id):
            raise HTTPException(403, f"No access to group {group_id}")
        
        container_name = self._get_group_container_name(
            user_context.tenant_id,
            group_id
        )
        
        container_client = self.blob_service.get_container_client(container_name)
        
        # List blobs
        files = []
        kwargs = {'include': ['metadata']}
        if prefix:
            kwargs['name_starts_with'] = prefix
        
        try:
            async for blob in container_client.list_blobs(**kwargs):
                files.append({
                    'name': blob.name,
                    'size': blob.size,
                    'last_modified': blob.last_modified.isoformat(),
                    'content_type': blob.content_settings.content_type if blob.content_settings else None,
                    'uploaded_by': blob.metadata.get('uploaded_by') if blob.metadata else None,
                    'url': container_client.get_blob_client(blob.name).url
                })
        except Exception as e:
            # Container might not exist yet
            if "ContainerNotFound" in str(e):
                return []
            raise
        
        return files
    
    async def download_group_file(
        self,
        user_context: UserContext,
        group_id: str,
        blob_name: str
    ) -> bytes:
        """
        Download file from group container.
        
        Raises:
            HTTPException 403: No group access
            HTTPException 404: File not found
        """
        if not user_context.has_group_access(group_id):
            raise HTTPException(403, f"No access to group {group_id}")
        
        container_name = self._get_group_container_name(
            user_context.tenant_id,
            group_id
        )
        
        blob_client = self.blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )
        
        try:
            download_stream = await blob_client.download_blob()
            return await download_stream.readall()
        except Exception as e:
            if "BlobNotFound" in str(e):
                raise HTTPException(404, f"File {blob_name} not found")
            raise
    
    async def delete_group_file(
        self,
        user_context: UserContext,
        group_id: str,
        blob_name: str
    ) -> bool:
        """Delete file from group container"""
        
        if not user_context.has_group_access(group_id):
            raise HTTPException(403, f"No access to group {group_id}")
        
        container_name = self._get_group_container_name(
            user_context.tenant_id,
            group_id
        )
        
        blob_client = self.blob_service.get_blob_client(
            container=container_name,
            blob=blob_name
        )
        
        try:
            await blob_client.delete_blob()
            return True
        except Exception as e:
            if "BlobNotFound" in str(e):
                raise HTTPException(404, f"File {blob_name} not found")
            raise
```

**Action Items:**
- [ ] Create blob_storage_service.py
- [ ] Test container creation
- [ ] Test file upload/download with group access
- [ ] Test unauthorized access rejection
- [ ] Add integration tests

---

## Step 3.5: Update API Endpoints

### **Update Router to Include Group Operations**

```python
# backend/app/routers/schemas.py
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from app.models.user_context import UserContext
from app.models.schema import Schema, SchemaCreate, SchemaUpdate
from app.services.schema_service import SchemaService
from app.auth.dependencies import get_current_user
from app.dependencies import get_schema_service

router = APIRouter(prefix="/api/schemas", tags=["schemas"])

@router.get("/", response_model=List[Schema])
async def list_schemas(
    group_id: Optional[str] = Query(None, description="Filter by group ID"),
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """
    List schemas accessible to current user.
    
    - If group_id provided: Filter to that group (user must be member)
    - If no group_id: Return schemas from all user's groups
    """
    return await schema_service.get_user_schemas(current_user, group_id)

@router.get("/{schema_id}", response_model=Schema)
async def get_schema(
    schema_id: str,
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """Get specific schema (requires group access)"""
    return await schema_service.get_schema_by_id(schema_id, current_user)

@router.post("/", response_model=Schema, status_code=201)
async def create_schema(
    schema_data: SchemaCreate,
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """
    Create new schema in specified group.
    User must be member of the group.
    """
    return await schema_service.create_schema(schema_data, current_user)

@router.put("/{schema_id}", response_model=Schema)
async def update_schema(
    schema_id: str,
    updates: SchemaUpdate,
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """Update schema (requires group access)"""
    return await schema_service.update_schema(schema_id, updates, current_user)

@router.delete("/{schema_id}", status_code=204)
async def delete_schema(
    schema_id: str,
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """Delete schema (requires group access)"""
    await schema_service.delete_schema(schema_id, current_user)

@router.get("/groups/{group_id}/stats")
async def get_group_statistics(
    group_id: str,
    current_user: UserContext = Depends(get_current_user),
    schema_service: SchemaService = Depends(get_schema_service)
):
    """Get statistics for group's schemas"""
    return await schema_service.get_group_statistics(group_id, current_user)

# NEW: Group management endpoints
@router.get("/user/groups")
async def get_user_groups(
    current_user: UserContext = Depends(get_current_user)
):
    """
    Get current user's group memberships.
    Returns group IDs and names (if available).
    """
    # TODO: Fetch group names from cache or Azure AD Graph API
    return {
        "user_id": current_user.user_id,
        "groups": current_user.groups,
        "primary_group": current_user.primary_group,
        "group_count": len(current_user.groups)
    }
```

**Similar updates needed for:**
- [ ] Files router
- [ ] Analysis router
- [ ] Cases router (if applicable)

**Action Items:**
- [ ] Update all routers with group filtering
- [ ] Add group-specific endpoints
- [ ] Update API documentation
- [ ] Test all endpoints with Postman/curl

---

## Continue to PHASE 4 in next message...

Would you like me to continue with:
- **Phase 4: Frontend Updates**
- **Phase 5: Data Migration**
- **Phase 6: Deployment & Validation**
- **Phase 7: Rollback Procedures**
- **Testing Strategies**
- **Monitoring & Troubleshooting**

Let me know if you'd like me to continue or if you have questions about the sections above!
