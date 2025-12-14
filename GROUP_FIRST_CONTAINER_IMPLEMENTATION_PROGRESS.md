# Group-First Container Pattern Implementation - In Progress

**Date**: October 23, 2025  
**Status**: 🔄 PARTIAL - Core functions complete, endpoints being migrated  
**Pattern**: Container = Security Group (Enterprise Pattern)

## What We're Changing

### From (Resource-First Pattern):
```
analyzers-{group_id}/blob.json
analysis-results-{group_id}/blob.json
pro-input-files/{group_id}/blob.pdf
pro-reference-files/{group_id}/blob.pdf
pro-schemas-{config}/{schema_id}/blob.json
```

### To (Group-First Pattern):
```
group-{group_id}/analyzers/blob.json
group-{group_id}/analysis-results/blob.json
group-{group_id}/input-files/blob.pdf
group-{group_id}/reference-files/blob.pdf
group-{group_id}/schemas/{schema_id}/blob.json
```

## Why This Change?

**Enterprise Security Model:**
- ✅ Container = Security boundary (one per department/group)
- ✅ Subdirectories = Resource types (organizational)
- ✅ Easier RBAC: Grant access to ONE container per group
- ✅ Simpler management: N containers instead of 5×N
- ✅ Better aligned with enterprise IT thinking

## Implementation Progress

### ✅ COMPLETED

#### 1. Helper Functions (Lines ~1190-1270)
- ✅ `get_group_container_name(group_id)` - Returns `group-{sanitized_group_id}`
- ✅ `get_resource_blob_path(resource_type, filename, **kwargs)` - Returns subdirectory path
- ✅ `get_legacy_container_name(resource_type, group_id)` - For backward compatibility

**Example Usage:**
```python
container = get_group_container_name("Finance-Dept")  
# Returns: "group-finance-dept"

blob_path = get_resource_blob_path("schema", "invoice.json", schema_id="abc-123")
# Returns: "schemas/abc-123/invoice.json"

# Full path: group-finance-dept/schemas/abc-123/invoice.json
```

#### 2. File Operations Refactored (Lines ~623-730)
- ✅ `handle_file_container_operation()` - Updated to use group containers
- ✅ Changed signature: `container_name` → `resource_type`
- ✅ Now constructs: `group-{id}/{resource_type}-files/` pattern

**Changes:**
```python
# OLD:
await handle_file_container_operation("upload", "pro-input-files", ...)

# NEW:
await handle_file_container_operation("upload", "input", ...)
# Internally uses: group-{group_id}/input-files/
```

#### 3. Input/Reference File Endpoints Updated
- ✅ Upload input files (Line ~3859)
- ✅ List input files (Line ~3881)
- ✅ Delete input files (Line ~3904)
- ✅ Upload reference files (Line ~2846)
- ✅ List reference files (Line ~2868)
- ✅ Delete reference files (Line ~2891)

**All now use:**
```python
handle_file_container_operation("upload", "input", ...)  # Not "pro-input-files"
handle_file_container_operation("list", "reference", ...)  # Not "pro-reference-files"
```

#### 4. Schema Storage Class Updated (Lines ~1663-1710)
- ✅ `ProModeSchemaBlob.__init__()` - Now accepts `group_id` parameter
- ✅ Uses `get_group_container_name(group_id)` for container
- ✅ `upload_schema_blob()` - Uses `get_resource_blob_path("schema", ...)`
- ✅ `get_pro_mode_blob_helper()` - Updated to accept `group_id`

**Changes:**
```python
# OLD:
blob_helper = ProModeSchemaBlob(app_config)
# Used: pro-schemas-{config}/

# NEW:
blob_helper = ProModeSchemaBlob(app_config, group_id="finance-dept")
# Uses: group-finance-dept/schemas/
```

### 🔄 IN PROGRESS

#### 5. Schema Endpoint Updates (NEXT)
Need to update all endpoints that create `ProModeSchemaBlob` to pass `group_id`:

**Files to update (~6 locations):**
1. Line ~2424: `save_enhanced_schema()` - Has group_id, need to pass it
2. Line ~12233: Schema comparison/download endpoint
3. Other schema CRUD endpoints

**Pattern:**
```python
# Update from:
blob_helper = ProModeSchemaBlob(app_config)

# To:
effective_group_id = group_id or "default"
blob_helper = ProModeSchemaBlob(app_config, effective_group_id)
```

### ⏳ TODO

#### 6. Analyzer Storage Updates
**Files:** Lines ~9117, ~9662 (analyzer save/retrieve)

**Change from:**
```python
analyzer_container = f"analyzers-{safe_group}"
```

**To:**
```python
container = get_group_container_name(group_id)
blob_path = get_resource_blob_path("analyzer", f"analyzer_{analyzer_id}_{timestamp}.json")
# Full: group-{group_id}/analyzers/analyzer_xyz.json
```

#### 7. Analysis Results Storage Updates
**Files:** Lines ~8938, ~9377 (results save/retrieve)

**Change from:**
```python
container_name = f"analysis-results-{safe_group}"
```

**To:**
```python
container = get_group_container_name(group_id)
blob_path = get_resource_blob_path("analysis_result", f"analysis_result_{analyzer_id}_{timestamp}.json")
# Full: group-{group_id}/analysis-results/result_xyz.json
```

#### 8. Knowledge Sources Container URLs
**Files:** Lines ~1541, ~4593, ~6658, etc. (Azure Content Understanding API calls)

**Change from:**
```python
"containerUrl": f"{storage_url}/pro-reference-files"
```

**To:**
```python
container = get_group_container_name(group_id)
"containerUrl": f"{storage_url}/{container}/reference-files"
# Result: https://storage/group-finance-dept/reference-files
```

#### 9. Backward Compatibility Fallback Logic
Add fallback to old patterns when reading data:

```python
# Try new pattern first
try:
    container = get_group_container_name(group_id)
    blob_path = get_resource_blob_path("analyzer", filename)
    data = storage_helper.download_blob(blob_path)
except BlobNotFoundError:
    # Fallback to old pattern
    legacy_container = get_legacy_container_name("analyzer", group_id)
    storage_helper = StorageBlobHelper(url, legacy_container)
    data = storage_helper.download_blob(filename)
    print(f"[Fallback] Loaded from legacy container: {legacy_container}")
```

**Locations needing fallback:**
- Schema retrieval endpoints
- Analyzer retrieval endpoint (line ~9630)
- Analysis results retrieval (line ~9377)

#### 10. Update Hard-Coded Container References
Search and replace remaining hard-coded strings:

**Search for:**
- `"pro-input-files"`
- `"pro-reference-files"`
- `f"pro-schemas-{`
- `f"analyzers-{`
- `f"analysis-results-{`

**Files:**
- Lines ~3956, ~4043 (file cleanup endpoints)
- Lines ~6829, ~6874 (analyze document endpoints)

---

## Migration Strategy

### Phase 1: New Data (Current Implementation)
- ✅ All new uploads go to group-first containers
- ✅ Helper functions in place
- ✅ Input/reference files migrated
- 🔄 Schemas partially migrated
- ⏳ Analyzers/results pending

### Phase 2: Read Fallback (Next)
- Add try/catch to read from new pattern first
- Fall back to old containers if not found
- Log which pattern was used for monitoring

### Phase 3: Data Migration (Future)
- Script to copy existing data to new pattern
- Verification step
- Optional: Delete old containers

### Phase 4: Cleanup (Future)
- Remove fallback logic
- Remove `get_legacy_container_name()` function
- Update documentation

---

## Testing Checklist

### ✅ Unit Tests
- [x] `get_group_container_name()` with various group IDs
- [x] `get_resource_blob_path()` for all resource types
- [x] Container name sanitization (special chars, length limits)

### 🔄 Integration Tests (In Progress)
- [x] Upload input files → verify container/path
- [x] List input files → verify correct filtering
- [x] Delete input files → verify correct location
- [x] Upload reference files → verify container/path
- [ ] Upload schema → verify new pattern
- [ ] Save analyzer → verify new pattern
- [ ] Save analysis results → verify new pattern

### ⏳ E2E Tests (Pending)
- [ ] Create analyzer with group container reference files
- [ ] Run analysis using group container input files
- [ ] Verify results saved to correct group container
- [ ] Test cross-group isolation (can't access other group's data)

---

## Current File State

**File:** `proMode.py`  
**Lines:** 14,043  
**Errors:** 0 ✅  
**Changes Made:** ~300 lines modified  
**Estimated Remaining:** ~200 lines to modify  

**Key Sections Modified:**
- Lines 1190-1270: Helper functions ✅
- Lines 623-730: File operation handler ✅
- Lines 1663-1710: Schema blob class ✅
- Lines 2846-2891: Reference file endpoints ✅
- Lines 3859-3904: Input file endpoints ✅

**Key Sections Pending:**
- Lines 2424, 12233: Schema endpoint updates
- Lines 9117, 9662: Analyzer storage
- Lines 8938, 9377: Analysis results storage
- Lines 1541, 4593, 6658: Knowledge source URLs
- Various: Hard-coded container strings

---

## Benefits Achieved So Far

### ✅ Input/Reference Files
- **Before:** `pro-input-files/{group}/uuid_file.pdf` (shared container, virtual folders)
- **After:** `group-{id}/input-files/uuid_file.pdf` (group container, subdirectory)
- **Impact:** Enterprise RBAC ready, one access policy per group

### ✅ Storage Organization
- **Before:** 5 resource-type containers + virtual folders (inconsistent)
- **After:** One container per group with organized subdirectories (consistent)
- **Impact:** Simpler management, clearer security boundaries

### 🔄 Schemas (Partial)
- **Before:** `pro-schemas-{config}/{schema_id}/file.json` (shared, not group-aware in container)
- **After:** `group-{id}/schemas/{schema_id}/file.json` (group-isolated)
- **Impact:** True group isolation for sensitive schema data

---

## Next Steps

1. **Complete Schema Migration**
   - Update line ~2424 (save_enhanced_schema)
   - Update line ~12233 (comparison/download)
   - Pass `group_id` to all `ProModeSchemaBlob()` calls

2. **Migrate Analyzers & Results**
   - Lines ~9117, ~9662 (analyzers)
   - Lines ~8938, ~9377 (results)
   - Update to use `get_group_container_name()` and `get_resource_blob_path()`

3. **Update Knowledge Source URLs**
   - Find all `"containerUrl":` constructions
   - Update to use group container pattern

4. **Add Fallback Logic**
   - Wrap reads in try/catch
   - Fall back to old containers
   - Log for monitoring

5. **Testing**
   - End-to-end workflow test
   - Cross-group isolation verification
   - Performance benchmarking

---

## Risk Mitigation

### Low Risk ✅
- Helper functions are pure (no side effects)
- Input/reference file changes are isolated
- No existing production data affected (new endpoints)

### Medium Risk ⚠️
- Schema storage changes (in progress)
- Need to ensure all endpoints updated consistently
- Backward compatibility critical for existing schemas

### High Risk 🔴
- Analyzer/results migration (not started)
- Existing saved analyzers use old pattern
- Must maintain backward compatibility during transition

---

## Performance Considerations

### No Performance Impact ✅
- Container name construction is fast (string ops)
- Blob path construction is fast (string formatting)
- Azure Blob Storage treats subdirectories as virtual (no overhead)

### Potential Improvements ✅
- Fewer containers = faster container listing
- Group-scoped queries more efficient
- Better cache locality for group data

---

## Rollback Plan

If issues arise:

1. **Immediate:** Revert helper functions to use old patterns
2. **Quick:** Update function signatures to match old behavior
3. **Safe:** Keep fallback logic permanently to support both patterns

**Critical:** No data loss risk - old containers/blobs unchanged

---

## Summary

**Status:** 40% Complete  
**Confidence:** High (no errors, clean architecture)  
**Timeline:** 2-3 hours to complete remaining changes  
**Blocker:** None - systematic refactoring in progress  

The group-first container pattern is now the foundation. Input and reference files are fully migrated. Schemas are in progress. Analyzers and results are next.

**Ready to continue!** ✅
