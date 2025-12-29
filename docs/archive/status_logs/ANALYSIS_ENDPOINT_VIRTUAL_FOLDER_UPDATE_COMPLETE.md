# Analysis Endpoint Virtual-Folder Pattern Update - Complete ✅

## Summary
Updated all references to input/reference file containers in the `analyze_content` function to use the virtual-folder pattern instead of per-group container naming.

## Files Modified
- `src/ContentProcessorAPI/app/routers/proMode.py`

## Changes Made

### 1. Blob Name Resolution (Line ~6645-6653)
**Changed:** Container naming from per-group pattern to base container + group prefix
```python
# BEFORE (OLD):
input_container = "pro-input-files"
if group_id:
    input_container = f"{input_container}-group-{group_id[:8]}"
input_file_contents = resolve_blob_names_from_ids(request.inputFiles, input_container, "input")

# AFTER (NEW - Virtual Folder):
input_container = "pro-input-files"
print(f"[AnalyzeContent] Using group_id prefix: {group_id[:8] + '...' if group_id else 'none'}")
input_file_contents = resolve_blob_names_from_ids(request.inputFiles, input_container, "input", group_id)
```

### 2. Helper Function `resolve_blob_names_from_ids` (Line ~6583-6640)
**Added:** `group_id` parameter and virtual-folder prefix logic
```python
# BEFORE:
def resolve_blob_names_from_ids(blob_ids, container_name, file_type):
    # ...
    matching_blobs = container_client.list_blobs(name_starts_with=blob_id)

# AFTER:
def resolve_blob_names_from_ids(blob_ids, container_name, file_type, group_id=None):
    """Supports virtual-folder pattern: when group_id is provided, searches for blobs
    with prefix {group_id}/{blob_id} instead of just {blob_id}."""
    # ...
    search_prefix = f"{group_id}/{blob_id}" if group_id else blob_id
    matching_blobs = container_client.list_blobs(name_starts_with=search_prefix)
```

### 3. File Verification Section (Line ~6823-6828)
**Removed:** Per-group container naming
```python
# BEFORE:
container_name = "pro-input-files"
if group_id:
    container_name = f"{container_name}-group-{group_id[:8]}"

# AFTER:
container_name = "pro-input-files"
```

### 4. SAS URL Generation (Line ~6868-6875)
**Removed:** Per-group container naming
```python
# BEFORE:
container_name = "pro-input-files"
if group_id:
    container_name = f"{container_name}-group-{group_id[:8]}"

# AFTER:
container_name = "pro-input-files"
```

## Schema Storage Pattern
**No changes needed** - Schemas use a different pattern:
- Container: `pro-schemas-{app_cps_configuration}` (single container, not per-group)
- Blob path: `{schema_id}/{filename}` (schema-ID based, not group-based)
- This pattern is correct and doesn't require updating

## Other Containers Not Updated
The following containers still use per-group naming (as designed):
- `predictions-group-{group_id}` (line ~7600) - Used for prediction results storage
- `analysis-results-group-{group_id}` (line ~9255) - Used for analysis result files

These are intentionally kept separate as they're results/outputs, not source files.

## Virtual-Folder Pattern Consistency
After this update, all input/reference file operations now use the same pattern:

| Operation | Container | Blob Path | Status |
|-----------|-----------|-----------|--------|
| Upload | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ |
| List | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ |
| Delete | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ |
| Preview | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ |
| Download | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ |
| **Analysis** | `pro-input-files` | `{group_id}/{process_id}_{filename}` | ✅ **FIXED** |

## Testing Checklist
- [ ] Deploy updated backend
- [ ] Upload files via Files tab (ensures virtual-folder storage)
- [ ] Select schema on Schema tab
- [ ] Click "Start Analysis" on Prediction/Analysis tab
- [ ] Verify analysis starts without "file not found" errors
- [ ] Check backend logs for correct blob resolution:
  ```
  [AnalyzeContent] Using group_id prefix: abcd1234...
  [AnalyzeContent] Searching with prefix: {group_id}/{blob_id}
  [AnalyzeContent] Found actual blob: {group_id}/{process_id}_{filename}
  ```

---
**Status**: ✅ Complete - All input/reference file container references updated  
**Date**: 2025-01-28  
**Component**: proMode.py (analyze_content function)
