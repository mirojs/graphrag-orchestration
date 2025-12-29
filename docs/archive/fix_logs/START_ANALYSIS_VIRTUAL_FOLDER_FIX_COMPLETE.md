# Start Analysis Button Fix - Virtual Folder Pattern ✅

## Issue
The "Start Analysis" button on the Analysis page was failing with error:
```
[PredictionTab] Orchestrated analysis failed: start analysis failed: [object Object]
```

## Root Cause
The backend's `analyze_content` function (in `proMode.py`) was still using the **old per-group container naming pattern**:

```python
input_container = "pro-input-files"
if group_id:
    input_container = f"{input_container}-group-{group_id[:8]}"  # ❌ OLD PATTERN
```

This attempted to find files in containers like `pro-input-files-group-abcd1234`, but we migrated to a **virtual-folder pattern** where:
- All groups use the **same base containers** (`pro-input-files`, `pro-reference-files`)
- Files are stored with **group_id as a blob prefix**: `{group_id}/{process_id}_{filename}`

The `resolve_blob_names_from_ids` helper function was also searching for blobs using just the `blob_id` prefix, not accounting for the `group_id/` prefix in the new pattern.

## Solution Implemented

### Files Modified
- **src/ContentProcessorAPI/app/routers/proMode.py**

### Changes Made

#### 1. Updated Container Naming Logic (Lines ~6645-6653)
**Before:**
```python
input_container = "pro-input-files"
if group_id:
    input_container = f"{input_container}-group-{group_id[:8]}"
```

**After:**
```python
# Use virtual-folder pattern: all groups use same base containers with group_id as blob prefix
input_container = "pro-input-files"

print(f"[AnalyzeContent] Using container: {input_container}")
print(f"[AnalyzeContent] Using group_id prefix: {group_id[:8] + '...' if group_id else 'none'}")
input_file_contents = resolve_blob_names_from_ids(request.inputFiles, input_container, "input", group_id)
```

#### 2. Updated `resolve_blob_names_from_ids` Function (Lines ~6583-6640)
**Added `group_id` parameter and virtual-folder prefix logic:**

```python
def resolve_blob_names_from_ids(blob_ids, container_name, file_type, group_id=None):
    """Resolve actual blob names from UUIDs efficiently (no download needed).
    
    Supports virtual-folder pattern: when group_id is provided, searches for blobs
    with prefix {group_id}/{blob_id} instead of just {blob_id}.
    """
    # ...
    for i, blob_id in enumerate(blob_ids):
        # Virtual-folder pattern: use group_id prefix if provided
        search_prefix = f"{group_id}/{blob_id}" if group_id else blob_id
        
        print(f"[AnalyzeContent] Searching with prefix: {search_prefix}")
        matching_blobs = container_client.list_blobs(name_starts_with=search_prefix)
        # ...
```

## How It Works Now

### Analysis Flow
1. **Frontend sends analysis request** with file IDs (e.g., `["abc123", "def456"]`)
2. **Backend receives request** with `X-Group-ID` header (e.g., `group_abc123...`)
3. **Container lookup**: Uses base container `"pro-input-files"` (same for all groups)
4. **Blob search**: Searches for blobs with prefix `{group_id}/{blob_id}`
   - Example: `group_abc123.../abc123_document.pdf`
5. **Analysis proceeds** with correctly resolved file paths

### Virtual-Folder Pattern Benefits
- **Single container** per file type (no per-group containers)
- **Scalable**: Works with any number of groups without creating new containers
- **Compatible**: Works with both Blob Storage and Data Lake Gen2 (HNS-enabled)
- **Consistent**: Same pattern used across upload, list, delete, preview, and analysis operations

## Related Changes
This fix aligns the analysis endpoint with the virtual-folder pattern already implemented in:
- ✅ File upload (`handle_file_container_operation`)
- ✅ File listing (`handle_file_container_operation`)
- ✅ File deletion (`handle_file_container_operation`)
- ✅ File preview (`preview_file`)
- ✅ File download (`download_file`)
- ✅ Analysis (NOW FIXED)

## Testing

### Expected Behavior
1. **Select files** on Files tab (ensures files are uploaded with virtual-folder pattern)
2. **Select schema** on Schema tab
3. **Click "Start Analysis"** on Analysis/Prediction tab
4. **Analysis should start successfully** without "start analysis failed" error
5. **Backend logs should show:**
   ```
   [AnalyzeContent] Using container: pro-input-files
   [AnalyzeContent] Using group_id prefix: abcd1234...
   [AnalyzeContent] Searching with prefix: {group_id}/{blob_id}
   [AnalyzeContent] Found actual blob: {group_id}/{process_id}_{filename}
   ```

### Test Scenarios
- [ ] **Single-group user**: Analysis with files from one group
- [ ] **Multi-group user**: Switch active group, upload files, run analysis
- [ ] **Reference files**: If reference files provided, ensure they're also found with prefix
- [ ] **Error handling**: Verify meaningful error if file not found

## Status
✅ **Implementation Complete**
- Backend code updated to use virtual-folder pattern
- No Python syntax errors
- Ready for deployment and testing

## Next Steps
1. **Deploy** updated backend using `docker-build.sh`
2. **Test** Start Analysis functionality with uploaded files
3. **Monitor** backend logs to confirm files are resolved correctly
4. **Verify** analysis completes successfully and returns results

---
**Date**: 2025-01-28  
**Component**: proMode.py (analyze_content function)  
**Type**: Bug Fix - Storage Pattern Migration
