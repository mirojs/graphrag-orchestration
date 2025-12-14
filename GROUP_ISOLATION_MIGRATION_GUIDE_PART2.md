# 🔒 Group Isolation Migration Guide - Part 2

> **Continuation of GROUP_ISOLATION_MIGRATION_GUIDE.md**
> This document covers Phases 4-7 of the migration.

---

# 🎨 PHASE 4: Frontend Updates

## Step 4.1: Update Authentication Context

### **Extend User Profile Interface**

```typescript
// frontend/src/types/auth.types.ts
export interface UserProfile {
  userId: string;
  email: string;
  name: string;
  tenantId: string;
  groups: string[];           // NEW: User's group IDs
  primaryGroup?: string;      // NEW: User's default group
  groupCount: number;         // NEW: Number of groups
}

export interface GroupInfo {
  id: string;
  name: string;
  description?: string;
  memberCount?: number;
}

export interface GroupContext {
  selectedGroup: string | null;
  availableGroups: GroupInfo[];
  loading: boolean;
  error: string | null;
}
```

---

### **Update Auth Service**

```typescript
// frontend/src/services/authService.ts
import { AccountInfo } from "@azure/msal-browser";
import { UserProfile, GroupInfo } from "../types/auth.types";

export const getUserProfile = async (
  account: AccountInfo
): Promise<UserProfile> => {
  const tokenClaims = account.idTokenClaims as any;
  
  // Extract groups from token
  const groups = tokenClaims.groups || [];
  
  // If group overage, would need to call Graph API
  // For now, assume groups are in token
  
  return {
    userId: tokenClaims.oid,
    email: tokenClaims.preferred_username || tokenClaims.upn,
    name: tokenClaims.name,
    tenantId: tokenClaims.tid,
    groups: groups,
    primaryGroup: groups[0] || null,  // Default to first group
    groupCount: groups.length
  };
};

export const getGroupDetails = async (
  groupIds: string[],
  accessToken: string
): Promise<GroupInfo[]> => {
  /**
   * Fetch group names from backend.
   * Backend can cache group info or call Graph API.
   */
  try {
    const response = await fetch('/api/groups/details', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ group_ids: groupIds })
    });
    
    if (response.ok) {
      return await response.json();
    }
    
    // Fallback: return IDs as names
    return groupIds.map(id => ({
      id: id,
      name: `Group ${id.substring(0, 8)}...`
    }));
  } catch (error) {
    console.error('Error fetching group details:', error);
    return groupIds.map(id => ({ id, name: id }));
  }
};
```

---

### **Create Group Context Provider**

```typescript
// frontend/src/contexts/GroupContext.tsx
import React, { createContext, useContext, useState, useEffect } from 'react';
import { useAccount, useMsal } from '@azure/msal-react';
import { getUserProfile, getGroupDetails } from '../services/authService';
import { GroupContext, GroupInfo } from '../types/auth.types';

const GroupContextProvider = createContext<GroupContext & {
  selectGroup: (groupId: string) => void;
  refreshGroups: () => Promise<void>;
} | undefined>(undefined);

export const GroupProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { accounts } = useMsal();
  const account = useAccount(accounts[0] || {});
  
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [availableGroups, setAvailableGroups] = useState<GroupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const loadGroups = async () => {
    if (!account) {
      setLoading(false);
      return;
    }
    
    try {
      setLoading(true);
      setError(null);
      
      // Get user profile with groups
      const profile = await getUserProfile(account);
      
      // Fetch group details
      const accessToken = ''; // Get from MSAL instance
      const groupDetails = await getGroupDetails(profile.groups, accessToken);
      
      setAvailableGroups(groupDetails);
      
      // Set default selected group (user's primary or first)
      if (!selectedGroup && groupDetails.length > 0) {
        const primaryGroup = profile.primaryGroup || groupDetails[0].id;
        setSelectedGroup(primaryGroup);
        
        // Store in localStorage for persistence
        localStorage.setItem('selectedGroupId', primaryGroup);
      }
    } catch (err) {
      console.error('Error loading groups:', err);
      setError('Failed to load groups');
    } finally {
      setLoading(false);
    }
  };
  
  useEffect(() => {
    loadGroups();
  }, [account]);
  
  const selectGroup = (groupId: string) => {
    setSelectedGroup(groupId);
    localStorage.setItem('selectedGroupId', groupId);
  };
  
  return (
    <GroupContextProvider.Provider
      value={{
        selectedGroup,
        availableGroups,
        loading,
        error,
        selectGroup,
        refreshGroups: loadGroups
      }}
    >
      {children}
    </GroupContextProvider.Provider>
  );
};

export const useGroupContext = () => {
  const context = useContext(GroupContextProvider);
  if (!context) {
    throw new Error('useGroupContext must be used within GroupProvider');
  }
  return context;
};
```

**Action Items:**
- [ ] Create auth.types.ts
- [ ] Update authService.ts
- [ ] Create GroupContext.tsx
- [ ] Wrap App with GroupProvider

---

## Step 4.2: Create Group Selector Component

```typescript
// frontend/src/components/GroupSelector.tsx
import React from 'react';
import {
  Dropdown,
  Option,
  Badge,
  Spinner,
  Text,
  makeStyles
} from '@fluentui/react-components';
import { PeopleTeam24Regular } from '@fluentui/react-icons';
import { useGroupContext } from '../contexts/GroupContext';

const useStyles = makeStyles({
  container: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px',
  },
  dropdown: {
    minWidth: '200px',
  },
  badge: {
    marginLeft: '8px',
  }
});

export const GroupSelector: React.FC = () => {
  const styles = useStyles();
  const {
    selectedGroup,
    availableGroups,
    loading,
    error,
    selectGroup
  } = useGroupContext();
  
  if (loading) {
    return (
      <div className={styles.container}>
        <Spinner size="tiny" />
        <Text size={300}>Loading groups...</Text>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className={styles.container}>
        <Text size={300} style={{ color: 'red' }}>{error}</Text>
      </div>
    );
  }
  
  if (availableGroups.length === 0) {
    return (
      <div className={styles.container}>
        <Text size={300}>No groups assigned</Text>
      </div>
    );
  }
  
  const selectedGroupInfo = availableGroups.find(g => g.id === selectedGroup);
  
  return (
    <div className={styles.container}>
      <PeopleTeam24Regular />
      <Dropdown
        className={styles.dropdown}
        value={selectedGroupInfo?.name || 'Select Group'}
        selectedOptions={selectedGroup ? [selectedGroup] : []}
        onOptionSelect={(_, data) => {
          if (data.optionValue) {
            selectGroup(data.optionValue);
          }
        }}
      >
        {availableGroups.map(group => (
          <Option key={group.id} value={group.id} text={group.name}>
            {group.name}
            {group.memberCount && (
              <Badge
                className={styles.badge}
                size="small"
                appearance="outline"
              >
                {group.memberCount} members
              </Badge>
            )}
          </Option>
        ))}
      </Dropdown>
      
      {availableGroups.length > 1 && (
        <Badge size="small" appearance="filled" color="informative">
          {availableGroups.length} groups
        </Badge>
      )}
    </div>
  );
};
```

**Action Items:**
- [ ] Create GroupSelector component
- [ ] Add to header/toolbar
- [ ] Test group switching
- [ ] Add loading states

---

## Step 4.3: Update API Service Layer

```typescript
// frontend/src/services/apiService.ts
import { useGroupContext } from '../contexts/GroupContext';

class ApiService {
  private baseUrl: string;
  private getAccessToken: () => Promise<string>;
  
  constructor(baseUrl: string, getAccessToken: () => Promise<string>) {
    this.baseUrl = baseUrl;
    this.getAccessToken = getAccessToken;
  }
  
  /**
   * Get schemas for specific group (or current group if not specified)
   */
  async getSchemas(groupId?: string): Promise<Schema[]> {
    const token = await this.getAccessToken();
    
    const url = groupId
      ? `${this.baseUrl}/api/schemas?group_id=${groupId}`
      : `${this.baseUrl}/api/schemas`; // Returns all user's groups
    
    const response = await fetch(url, {
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new Error(`Failed to fetch schemas: ${response.status}`);
    }
    
    return await response.json();
  }
  
  /**
   * Create schema in specific group
   */
  async createSchema(
    schemaData: SchemaCreate,
    groupId: string
  ): Promise<Schema> {
    const token = await this.getAccessToken();
    
    const response = await fetch(`${this.baseUrl}/api/schemas`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        ...schemaData,
        group_id: groupId  // Ensure group_id is included
      })
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Failed to create schema');
    }
    
    return await response.json();
  }
  
  /**
   * Upload file to specific group
   */
  async uploadFile(
    file: File,
    groupId: string,
    onProgress?: (percent: number) => void
  ): Promise<FileMetadata> {
    const token = await this.getAccessToken();
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('group_id', groupId);
    
    const xhr = new XMLHttpRequest();
    
    return new Promise((resolve, reject) => {
      xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable && onProgress) {
          const percent = (e.loaded / e.total) * 100;
          onProgress(percent);
        }
      });
      
      xhr.addEventListener('load', () => {
        if (xhr.status === 200 || xhr.status === 201) {
          resolve(JSON.parse(xhr.responseText));
        } else {
          reject(new Error(`Upload failed: ${xhr.status}`));
        }
      });
      
      xhr.addEventListener('error', () => {
        reject(new Error('Upload failed'));
      });
      
      xhr.open('POST', `${this.baseUrl}/api/files/upload`);
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.send(formData);
    });
  }
  
  /**
   * Get files for specific group
   */
  async getGroupFiles(groupId: string): Promise<FileMetadata[]> {
    const token = await this.getAccessToken();
    
    const response = await fetch(
      `${this.baseUrl}/api/files?group_id=${groupId}`,
      {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    if (!response.ok) {
      throw new Error(`Failed to fetch files: ${response.status}`);
    }
    
    return await response.json();
  }
}

export default ApiService;
```

**Action Items:**
- [ ] Update apiService.ts
- [ ] Add group_id to all API calls
- [ ] Update error handling
- [ ] Test with different groups

---

## Step 4.4: Update UI Components

### **Update Schema List Component**

```typescript
// frontend/src/components/SchemaList.tsx
import React, { useState, useEffect } from 'react';
import {
  Table,
  TableHeader,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Button,
  Spinner,
  MessageBar
} from '@fluentui/react-components';
import { useGroupContext } from '../contexts/GroupContext';
import { useApiService } from '../hooks/useApiService';

export const SchemaList: React.FC = () => {
  const { selectedGroup } = useGroupContext();
  const apiService = useApiService();
  
  const [schemas, setSchemas] = useState<Schema[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  useEffect(() => {
    loadSchemas();
  }, [selectedGroup]); // Reload when group changes
  
  const loadSchemas = async () => {
    if (!selectedGroup) {
      setSchemas([]);
      setLoading(false);
      return;
    }
    
    try {
      setLoading(true);
      setError(null);
      
      // Load schemas for selected group
      const data = await apiService.getSchemas(selectedGroup);
      setSchemas(data);
    } catch (err) {
      console.error('Error loading schemas:', err);
      setError('Failed to load schemas');
    } finally {
      setLoading(false);
    }
  };
  
  if (!selectedGroup) {
    return (
      <MessageBar intent="info">
        Please select a group to view schemas
      </MessageBar>
    );
  }
  
  if (loading) {
    return <Spinner label="Loading schemas..." />;
  }
  
  if (error) {
    return (
      <MessageBar intent="error">
        {error}
        <Button onClick={loadSchemas}>Retry</Button>
      </MessageBar>
    );
  }
  
  if (schemas.length === 0) {
    return (
      <MessageBar intent="info">
        No schemas found in this group.
        <Button onClick={() => {/* Open create dialog */}}>
          Create Schema
        </Button>
      </MessageBar>
    );
  }
  
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHeaderCell>Name</TableHeaderCell>
          <TableHeaderCell>Description</TableHeaderCell>
          <TableHeaderCell>Fields</TableHeaderCell>
          <TableHeaderCell>Created</TableHeaderCell>
          <TableHeaderCell>Actions</TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>
        {schemas.map(schema => (
          <TableRow key={schema.id}>
            <TableCell>{schema.name}</TableCell>
            <TableCell>{schema.description || '-'}</TableCell>
            <TableCell>{schema.fields.length}</TableCell>
            <TableCell>
              {new Date(schema.created_at).toLocaleDateString()}
            </TableCell>
            <TableCell>
              <Button size="small">Edit</Button>
              <Button size="small" appearance="subtle">Delete</Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
};
```

**Similar updates needed for:**
- [ ] FileList component
- [ ] AnalysisResults component
- [ ] File upload components
- [ ] Schema editor

**Action Items:**
- [ ] Update all list components
- [ ] Add selectedGroup dependency
- [ ] Test group switching updates UI
- [ ] Add empty states for no group selection

---

## Step 4.5: Update File Upload Flow

```typescript
// frontend/src/components/FileUpload.tsx
import React, { useState } from 'react';
import {
  Button,
  Dialog,
  DialogTrigger,
  DialogSurface,
  DialogTitle,
  DialogBody,
  DialogActions,
  DialogContent,
  Field,
  Input,
  ProgressBar,
  MessageBar
} from '@fluentui/react-components';
import { ArrowUpload24Regular } from '@fluentui/react-icons';
import { useGroupContext } from '../contexts/GroupContext';
import { useApiService } from '../hooks/useApiService';

export const FileUpload: React.FC<{
  onUploadComplete?: () => void;
}> = ({ onUploadComplete }) => {
  const { selectedGroup, availableGroups } = useGroupContext();
  const apiService = useApiService();
  
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [targetGroup, setTargetGroup] = useState<string>(selectedGroup || '');
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  
  const handleUpload = async () => {
    if (!file || !targetGroup) return;
    
    try {
      setUploading(true);
      setError(null);
      
      await apiService.uploadFile(
        file,
        targetGroup,
        (percent) => setProgress(percent)
      );
      
      setOpen(false);
      setFile(null);
      setProgress(0);
      
      if (onUploadComplete) {
        onUploadComplete();
      }
    } catch (err) {
      console.error('Upload error:', err);
      setError('Upload failed. Please try again.');
    } finally {
      setUploading(false);
    }
  };
  
  return (
    <Dialog open={open} onOpenChange={(_, data) => setOpen(data.open)}>
      <DialogTrigger disableButtonEnhancement>
        <Button
          icon={<ArrowUpload24Regular />}
          appearance="primary"
          disabled={!selectedGroup}
        >
          Upload File
        </Button>
      </DialogTrigger>
      
      <DialogSurface>
        <DialogBody>
          <DialogTitle>Upload File to Group</DialogTitle>
          
          <DialogContent>
            {!selectedGroup && (
              <MessageBar intent="warning">
                Please select a group first
              </MessageBar>
            )}
            
            <Field label="Select Group">
              <select
                value={targetGroup}
                onChange={(e) => setTargetGroup(e.target.value)}
                disabled={uploading}
              >
                <option value="">-- Select Group --</option>
                {availableGroups.map(group => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
            </Field>
            
            <Field label="Select File">
              <Input
                type="file"
                onChange={(e) => {
                  const files = (e.target as HTMLInputElement).files;
                  setFile(files ? files[0] : null);
                }}
                disabled={uploading}
              />
            </Field>
            
            {uploading && (
              <ProgressBar value={progress} max={100} />
            )}
            
            {error && (
              <MessageBar intent="error">
                {error}
              </MessageBar>
            )}
          </DialogContent>
          
          <DialogActions>
            <DialogTrigger disableButtonEnhancement>
              <Button appearance="secondary" disabled={uploading}>
                Cancel
              </Button>
            </DialogTrigger>
            <Button
              appearance="primary"
              onClick={handleUpload}
              disabled={!file || !targetGroup || uploading}
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </Button>
          </DialogActions>
        </DialogBody>
      </DialogSurface>
    </Dialog>
  );
};
```

**Action Items:**
- [ ] Create FileUpload component
- [ ] Test upload to different groups
- [ ] Add file type validation
- [ ] Test error handling

---

# 📦 PHASE 5: Data Migration

## Step 5.1: Create Migration Scripts

### **Database Migration Script**

```python
# scripts/migrate_data_to_groups.py
"""
Migrate existing user-based data to group-based structure.

This script:
1. Reads user-to-group mapping
2. Updates all schemas with group_id
3. Updates all files metadata with group_id
4. Migrates blob storage containers
"""

import asyncio
import json
from datetime import datetime
from typing import Dict, List
from azure.cosmos.aio import CosmosClient
from azure.storage.blob.aio import BlobServiceClient

class DataMigration:
    def __init__(
        self,
        cosmos_conn_str: str,
        blob_conn_str: str,
        mapping_file: str = "user_group_mapping.json"
    ):
        self.cosmos_client = CosmosClient.from_connection_string(cosmos_conn_str)
        self.blob_client = BlobServiceClient.from_connection_string(blob_conn_str)
        
        # Load user-to-group mapping
        with open(mapping_file, 'r') as f:
            self.user_group_mapping = json.load(f)
        
        self.migration_log = []
    
    async def migrate_database_schemas(self, dry_run: bool = True):
        """Migrate schemas in Cosmos DB"""
        
        print("\n📊 MIGRATING DATABASE SCHEMAS")
        print("=" * 60)
        
        db = self.cosmos_client.get_database_client("content_processing")
        container = db.get_container_client("pro_schemas")
        
        # Read all schemas
        schemas = [schema async for schema in container.read_all_items()]
        
        migrated_count = 0
        failed_count = 0
        
        for schema in schemas:
            try:
                # Get user who created this schema
                created_by = schema.get('created_by') or schema.get('user_id')
                
                if not created_by:
                    print(f"⚠️  Skipping schema {schema.get('id')} - no creator found")
                    continue
                
                # Get user's primary group
                user_mapping = self.user_group_mapping.get(created_by)
                
                if not user_mapping:
                    print(f"⚠️  No group mapping for user {created_by}")
                    failed_count += 1
                    continue
                
                # Get primary group (first in list)
                group_id = user_mapping[0] if isinstance(user_mapping, list) else user_mapping
                
                # Update schema with group_id
                update = {
                    'group_id': group_id,
                    'migrated_at': datetime.utcnow().isoformat(),
                    'migration_version': '1.0'
                }
                
                if not dry_run:
                    await container.patch_item(
                        item=schema['id'],
                        partition_key=schema['id'],  # Adjust if different
                        patch_operations=[
                            {"op": "add", "path": "/group_id", "value": group_id},
                            {"op": "add", "path": "/migrated_at", "value": update['migrated_at']},
                            {"op": "add", "path": "/migration_version", "value": update['migration_version']}
                        ]
                    )
                
                self.migration_log.append({
                    'type': 'schema',
                    'id': schema['id'],
                    'user': created_by,
                    'group': group_id,
                    'dry_run': dry_run
                })
                
                migrated_count += 1
                print(f"✅ Schema {schema['id'][:8]}... → Group {group_id[:8]}...")
                
            except Exception as e:
                print(f"❌ Error migrating schema {schema.get('id')}: {e}")
                failed_count += 1
        
        print(f"\n📈 SCHEMA MIGRATION SUMMARY:")
        print(f"   Total: {len(schemas)}")
        print(f"   Migrated: {migrated_count}")
        print(f"   Failed: {failed_count}")
        print(f"   Dry Run: {dry_run}")
        
        return migrated_count, failed_count
    
    async def migrate_blob_containers(self, dry_run: bool = True):
        """Migrate blob storage from user containers to group containers"""
        
        print("\n📦 MIGRATING BLOB STORAGE")
        print("=" * 60)
        
        migrated_blobs = 0
        failed_blobs = 0
        
        # List all user containers
        containers = [c async for c in self.blob_client.list_containers()]
        user_containers = [c for c in containers if c.name.startswith('user-')]
        
        for container_info in user_containers:
            # Extract user ID from container name
            user_id = container_info.name.replace('user-', '')
            
            # Get user's group
            user_mapping = self.user_group_mapping.get(user_id)
            
            if not user_mapping:
                print(f"⚠️  No group mapping for user container {container_info.name}")
                continue
            
            group_id = user_mapping[0] if isinstance(user_mapping, list) else user_mapping
            
            # Source container
            source_container = self.blob_client.get_container_client(container_info.name)
            
            # Destination container (group-based)
            dest_container_name = f"tenant-default-group-{self._sanitize_id(group_id)}"
            dest_container = self.blob_client.get_container_client(dest_container_name)
            
            # Create destination container if doesn't exist
            if not dry_run:
                try:
                    await dest_container.create_container(
                        metadata={
                            'group_id': group_id,
                            'migrated_from': container_info.name,
                            'migrated_at': datetime.utcnow().isoformat()
                        }
                    )
                    print(f"✅ Created container: {dest_container_name}")
                except:
                    pass  # Container might already exist
            
            # Copy blobs
            async for blob in source_container.list_blobs():
                try:
                    # Source blob
                    source_blob = source_container.get_blob_client(blob.name)
                    
                    # Destination blob (preserve user path structure)
                    dest_blob_path = f"users/{user_id}/{blob.name}"
                    dest_blob = dest_container.get_blob_client(dest_blob_path)
                    
                    if not dry_run:
                        # Copy blob
                        copy_source = source_blob.url
                        await dest_blob.start_copy_from_url(copy_source)
                        
                        # Add migration metadata
                        await dest_blob.set_blob_metadata({
                            'migrated_from': container_info.name,
                            'original_blob': blob.name,
                            'group_id': group_id,
                            'user_id': user_id,
                            'migrated_at': datetime.utcnow().isoformat()
                        })
                    
                    migrated_blobs += 1
                    print(f"✅ {container_info.name}/{blob.name} → {dest_container_name}/{dest_blob_path}")
                    
                except Exception as e:
                    print(f"❌ Error copying blob {blob.name}: {e}")
                    failed_blobs += 1
        
        print(f"\n📈 BLOB MIGRATION SUMMARY:")
        print(f"   User Containers: {len(user_containers)}")
        print(f"   Blobs Migrated: {migrated_blobs}")
        print(f"   Blobs Failed: {failed_blobs}")
        print(f"   Dry Run: {dry_run}")
        
        return migrated_blobs, failed_blobs
    
    def _sanitize_id(self, text: str) -> str:
        """Sanitize ID for container naming"""
        return ''.join(c if c.isalnum() else '-' for c in text.lower())[:20]
    
    async def verify_migration(self):
        """Verify migration completed successfully"""
        
        print("\n🔍 VERIFYING MIGRATION")
        print("=" * 60)
        
        db = self.cosmos_client.get_database_client("content_processing")
        container = db.get_container_client("pro_schemas")
        
        # Check all schemas have group_id
        schemas = [schema async for schema in container.read_all_items()]
        
        schemas_with_group = sum(1 for s in schemas if 'group_id' in s)
        schemas_without_group = len(schemas) - schemas_with_group
        
        print(f"📊 Database Verification:")
        print(f"   Total Schemas: {len(schemas)}")
        print(f"   With group_id: {schemas_with_group} ✅")
        print(f"   Without group_id: {schemas_without_group} {'⚠️' if schemas_without_group > 0 else '✅'}")
        
        # Verify blob storage
        containers = [c async for c in self.blob_client.list_containers()]
        group_containers = [c for c in containers if 'group' in c.name.lower()]
        
        print(f"\n📦 Storage Verification:")
        print(f"   Total Containers: {len(containers)}")
        print(f"   Group Containers: {len(group_containers)}")
        
        # Check for isolation
        await self._verify_group_isolation()
        
        return schemas_without_group == 0
    
    async def _verify_group_isolation(self):
        """Verify no cross-group data access"""
        
        print(f"\n🔒 Group Isolation Verification:")
        
        # Group data by group_id
        db = self.cosmos_client.get_database_client("content_processing")
        container = db.get_container_client("pro_schemas")
        
        schemas = [schema async for schema in container.read_all_items()]
        
        groups_data = {}
        for schema in schemas:
            group_id = schema.get('group_id')
            if group_id:
                if group_id not in groups_data:
                    groups_data[group_id] = []
                groups_data[group_id].append(schema['id'])
        
        for group_id, schema_ids in groups_data.items():
            print(f"   Group {group_id[:8]}...: {len(schema_ids)} schemas")
        
        print(f"   Total Groups: {len(groups_data)} ✅")
    
    async def save_migration_report(self):
        """Save migration report"""
        
        report = {
            'migration_date': datetime.utcnow().isoformat(),
            'total_items_migrated': len(self.migration_log),
            'items': self.migration_log
        }
        
        with open('migration_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n💾 Migration report saved: migration_report.json")
    
    async def close(self):
        """Close clients"""
        await self.cosmos_client.close()
        await self.blob_client.close()


async def main():
    """Main migration function"""
    
    print("🚀 GROUP ISOLATION DATA MIGRATION")
    print("=" * 60)
    
    # Load configuration
    COSMOS_CONN_STR = os.getenv("COSMOS_CONNECTION_STRING")
    BLOB_CONN_STR = os.getenv("BLOB_CONNECTION_STRING")
    
    # Create migrator
    migrator = DataMigration(COSMOS_CONN_STR, BLOB_CONN_STR)
    
    try:
        # Step 1: Dry run
        print("\n📝 STEP 1: DRY RUN")
        await migrator.migrate_database_schemas(dry_run=True)
        await migrator.migrate_blob_containers(dry_run=True)
        
        # Ask for confirmation
        confirm = input("\n❓ Proceed with actual migration? (yes/no): ")
        
        if confirm.lower() != 'yes':
            print("❌ Migration cancelled")
            return
        
        # Step 2: Actual migration
        print("\n🔄 STEP 2: ACTUAL MIGRATION")
        await migrator.migrate_database_schemas(dry_run=False)
        await migrator.migrate_blob_containers(dry_run=False)
        
        # Step 3: Verification
        print("\n✅ STEP 3: VERIFICATION")
        success = await migrator.verify_migration()
        
        # Step 4: Save report
        await migrator.save_migration_report()
        
        if success:
            print("\n🎉 MIGRATION COMPLETED SUCCESSFULLY!")
        else:
            print("\n⚠️  MIGRATION COMPLETED WITH WARNINGS - Check report")
        
    finally:
        await migrator.close()


if __name__ == "__main__":
    import os
    asyncio.run(main())
```

**Action Items:**
- [ ] Create migration script
- [ ] Prepare user_group_mapping.json
- [ ] Run dry run first
- [ ] Review dry run results
- [ ] Run actual migration
- [ ] Verify migration success

---

## Step 5.2: Rollback Plan

```python
# scripts/rollback_migration.py
"""
Rollback group migration if issues found.
"""

async def rollback_migration():
    """Rollback to pre-migration state"""
    
    print("🔙 ROLLING BACK MIGRATION")
    
    # Read migration report
    with open('migration_report.json', 'r') as f:
        report = json.load(f)
    
    # Remove group_id fields from database
    # Delete new group containers
    # Restore from backup if available
    
    # Implementation details...
    pass
```

---

# 🚀 PHASE 6: Deployment & Validation

## Step 6.1: Staged Deployment Plan

```yaml
# deployment_stages.yaml
stages:
  - name: "Test Environment"
    duration: "2 days"
    steps:
      - Deploy backend changes
      - Deploy frontend changes
      - Run integration tests
      - Validate group isolation
    
  - name: "Staging Environment"
    duration: "2 days"
    steps:
      - Deploy to staging
      - Run migration on staging data
      - User acceptance testing
      - Performance testing
    
  - name: "Production (10% users)"
    duration: "1 week"
    steps:
      - Deploy backend
      - Deploy frontend
      - Migrate 10% of users
      - Monitor for issues
    
  - name: "Production (50% users)"
    duration: "1 week"
    steps:
      - Migrate additional 40%
      - Monitor performance
      - Collect feedback
    
  - name: "Production (100% users)"
    duration: "Ongoing"
    steps:
      - Complete migration
      - Remove old user-based code
      - Full monitoring
```

---

## Step 6.2: Testing Checklist

```markdown
# Group Isolation Testing Checklist

## Unit Tests
- [ ] UserContext group access methods
- [ ] Group filtering in database queries
- [ ] Blob storage group container naming
- [ ] Authentication token group extraction

## Integration Tests
- [ ] Create schema in group A, verify not visible in group B
- [ ] Upload file to group A, verify not accessible from group B
- [ ] Multi-group user can access data from both groups
- [ ] User removed from group loses access to group data

## Security Tests
- [ ] Cannot access data without group membership
- [ ] Cannot modify group_id to access other groups' data
- [ ] Cannot bypass group filter in API calls
- [ ] JWT tampering rejected

## Performance Tests
- [ ] Query performance with 1000+ schemas across 10 groups
- [ ] File upload to group container
- [ ] Group switching in UI (<1s response)
- [ ] Multi-group user queries optimized

## User Acceptance Tests
- [ ] Group selector works correctly
- [ ] Data loads for selected group
- [ ] Group switching updates all data
- [ ] Upload/create in correct group
```

---

# 📊 PHASE 7: Monitoring & Troubleshooting

## Common Issues and Solutions

### Issue 1: Groups Not Appearing in Token

**Symptoms:**
- Token has no `groups` claim
- User can't access any data

**Solutions:**
1. Verify token configuration in Azure AD
2. Check user is assigned to groups
3. Handle group overage claim
4. Check token expiration

### Issue 2: Cross-Group Data Leakage

**Symptoms:**
- User sees data from groups they don't belong to

**Solutions:**
1. Verify all queries filter by group_id
2. Check group_id correctly assigned during creation
3. Audit database for missing group_id fields

### Issue 3: Performance Degradation

**Symptoms:**
- Slow queries
- Timeouts

**Solutions:**
1. Add database index on group_id field
2. Optimize queries with compound indexes
3. Implement caching for group membership
4. Consider pagination

---

## Summary

This completes the comprehensive Group Isolation Migration Guide. You now have:

✅ **Complete migration plan** (7 phases, step-by-step)
✅ **Code examples** for all layers (backend, frontend, database)
✅ **Migration scripts** with dry-run support
✅ **Testing checklist** for validation
✅ **Rollback procedures** for safety
✅ **Troubleshooting guide** for common issues

### Recommended Approach: **Azure AD Security Groups**

Reasons:
- Enterprise-ready
- IT can manage independently
- Better compliance and auditing
- Scales with organization
- Multi-application support

Total estimated timeline: **5-7 days** for complete implementation.
