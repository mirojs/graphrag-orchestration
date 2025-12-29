# Backend Virtual Folder Pattern Implementation - Complete ✅

## Summary

Successfully updated the backend to use **virtual folder pattern** for group isolation instead of separate containers.

## Key Changes Made

### File: `src/ContentProcessorAPI/app/routers/proMode.py`

#### 1. Updated `handle_file_container_operation` Function

**Pattern Changed:**
- ❌ **Old:** Separate containers per group: `pro-input-files-group-824be8de`
- ✅ **New:** Virtual folders within single container: `pro-input-files/{824be8de-0981-470e-97f2-3332855e22b2}/file.pdf`

**Code Changes:**

```python
# OLD APPROACH (Separate Containers)
group_id = kwargs.get('group_id')
if group_id:
    container_name = f"{container_name}-group-{group_id[:8]}"  # Different container per group

# NEW APPROACH (Virtual Folders)
group_id = kwargs.get('group_id')
blob_prefix = f"{group_id}/" if group_id else ""  # Virtual folder prefix
```

#### 2. Upload Operation

**Updated blob naming:**
```python
# Now includes virtual folder prefix
blob_name = f"{blob_prefix}{process_id}_{file.filename}"
# Example: "824be8de-0981-470e-97f2-3332855e22b2/abc123-def456_contract.pdf"
```

**Added group ID to response:**
```python
results.append({
    "processId": process_id,
    "filename": file.filename,
    "size": len(file_stream.getvalue()),
    "container": container_name,
    "groupId": group_id if group_id else None  # NEW
})
```

#### 3. List Operation

**Updated to filter by virtual folder:**
```python
# List only blobs within the group's virtual folder
blobs = container_client.list_blobs(name_starts_with=blob_prefix if blob_prefix else None)

# Remove group prefix when processing blob names
blob_name_without_prefix = blob.name[len(blob_prefix):] if blob_prefix else blob.name
```

**Added group ID to response:**
```python
file_list.append({
    "processId": process_id,
    "filename": original_filename,
    "size": blob.size,
    "lastModified": blob.last_modified.isoformat() if blob.last_modified else None,
    "container": container_name,
    "groupId": group_id if group_id else None  # NEW
})
```

#### 4. Delete Operation

**Updated to search within virtual folder:**
```python
# Search within the group's virtual folder only
blobs = container_client.list_blobs(name_starts_with=blob_prefix if blob_prefix else None)
blob_to_delete = f"{blob_prefix}{process_id}_"
```

## Benefits

### 1. **Works with Both Storage Types** ✅
- ✅ Standard Blob Storage (prefix-based virtual folders)
- ✅ Data Lake Gen2 (true hierarchical folders)
- ✅ Same code works for both - no changes needed when migrating

### 2. **Cleaner Organization** ✅
```
Container: pro-input-files
├── 824be8de-0981-470e-97f2-3332855e22b2/  (Owner-access group)
│   ├── abc123_contract.pdf
│   └── def456_invoice.pdf
├── fb0282b9-12e0-4dd5-94ab-3df84561994c/  (Testing-access group)
│   ├── xyz789_report.pdf
│   └── mno234_schema.json
└── (no group - legacy files at root)
    └── old-file.pdf
```

### 3. **Better Performance** ✅
- Fewer containers to manage
- Faster blob listing with prefix filters
- Reduced container creation overhead

### 4. **Backward Compatible** ✅
- If `group_id` is `None` or missing → files stored at container root (legacy behavior)
- Existing files without group folders still work
- Gradual migration path

### 5. **Multi-Region Ready** ✅
- Same pattern works across regions
- No container naming conflicts
- Easy to replicate

## Storage Structure Examples

### Upload File (With Group)
```
POST /pro-mode/input-files
X-Group-ID: 824be8de-0981-470e-97f2-3332855e22b2

Storage Path:
pro-input-files/824be8de-0981-470e-97f2-3332855e22b2/abc123-def456_contract.pdf
```

### Upload File (No Group - Legacy)
```
POST /pro-mode/input-files
(No X-Group-ID header)

Storage Path:
pro-input-files/abc123-def456_contract.pdf
```

### List Files (With Group)
```
GET /pro-mode/input-files
X-Group-ID: 824be8de-0981-470e-97f2-3332855e22b2

Returns: Only files in virtual folder "824be8de-0981-470e-97f2-3332855e22b2/"
```

### Delete File (With Group)
```
DELETE /pro-mode/input-files/{process_id}
X-Group-ID: 824be8de-0981-470e-97f2-3332855e22b2

Searches: Only within "824be8de-0981-470e-97f2-3332855e22b2/" folder
```

## API Endpoints Already Using X-Group-ID Header

✅ All pro-mode endpoints already have `X-Group-ID` header parameter:

```python
@router.post("/pro-mode/input-files")
async def upload_pro_input_files(
    files: List[UploadFile] = File(...),
    group_id: Optional[str] = Header(None, alias="X-Group-ID"),  # Already present
    ...
)
```

**Endpoints with group support:**
- `/pro-mode/input-files` (POST, GET, DELETE)
- `/pro-mode/reference-files` (POST, GET, DELETE)
- `/pro-mode/schemas/*` (various endpoints)

## What Still Needs to Be Done

### Frontend Changes Required

**File: `src/ContentProcessorWeb/src/Services/httpUtility.ts`**

Add X-Group-ID header to all API requests:

```typescript
// Get selected group from GroupContext
const selectedGroup = localStorage.getItem('selectedGroup');

// Add to request headers
headers['X-Group-ID'] = selectedGroup;
```

**Affected Components:**
- File upload components
- File list components
- Schema management components
- Any component making API calls to pro-mode endpoints

## Testing Checklist

### Backend (Ready to Test) ✅
- [ ] Upload file with X-Group-ID header → file stored in `{group_id}/` folder
- [ ] Upload file without header → file stored at container root
- [ ] List files with X-Group-ID → only returns files in that folder
- [ ] List files without header → returns all files at root
- [ ] Delete file with X-Group-ID → deletes from correct folder
- [ ] Verify group isolation (User A can't see User B's files)

### Frontend (Pending - needs X-Group-ID header)
- [ ] Add X-Group-ID to httpUtility requests
- [ ] Test file upload sends correct group ID
- [ ] Test file list filters by selected group
- [ ] Test group switching refreshes file list
- [ ] Verify user can only see their group's files

## Deployment Strategy

### Phase 1: Deploy Backend Changes ✅ (This Change)
```bash
# Backend changes are backward compatible
# Existing files without group folders continue to work
azd deploy
```

### Phase 2: Add Frontend X-Group-ID Header
```bash
# Update httpUtility.ts
# Deploy frontend
azd deploy
```

### Phase 3: Test in East US 2
- Upload files with different group IDs
- Verify virtual folder structure in Azure Portal
- Confirm group isolation works

### Phase 4: Deploy to West US (with Data Lake Gen2)
```bash
azd env new westus-env
azd env set AZURE_LOCATION westus
azd env set AZURE_ENV_ENABLE_HNS true
azd provision
```

## Verification Commands

Check virtual folder structure in Azure Portal or CLI:

```bash
# List blobs with prefix
az storage blob list \
  --account-name stcpsxh5lwkfq3vfm \
  --container-name pro-input-files \
  --prefix "824be8de-0981-470e-97f2-3332855e22b2/" \
  --auth-mode login \
  -o table
```

## Migration Path for Existing Files

If you have existing files in separate containers (old pattern), you can migrate them:

```bash
# Example: Move files from old container to new virtual folder
OLD_CONTAINER="pro-input-files-group-824be8de"
NEW_CONTAINER="pro-input-files"
GROUP_ID="824be8de-0981-470e-97f2-3332855e22b2"

# Copy blobs with new prefix
az storage blob copy start-batch \
  --source-container "$OLD_CONTAINER" \
  --destination-container "$NEW_CONTAINER" \
  --pattern "*" \
  --destination-path "$GROUP_ID/" \
  --account-name stcpsxh5lwkfq3vfm \
  --auth-mode login
```

## Related Files Changed

1. ✅ `src/ContentProcessorAPI/app/routers/proMode.py` - Virtual folder pattern implemented
2. ⏳ `src/ContentProcessorWeb/src/Services/httpUtility.ts` - Needs X-Group-ID header (next step)

## Status

✅ **Backend Implementation:** Complete  
⏳ **Frontend Implementation:** Pending (X-Group-ID header)  
✅ **Bicep Infrastructure:** Ready (parameter for Data Lake Gen2)  
✅ **Post-Deployment Script:** Ready (Graph API permissions)

**Next Step:** Add X-Group-ID header to frontend httpUtility.ts

---

**Last Updated:** 2025-01-20  
**Status:** Backend Ready for Testing
