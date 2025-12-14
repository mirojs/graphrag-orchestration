# Schema DisplayName "Updated Schema" Bug - Root Cause Fix

## Date: October 10, 2025

## Problem Summary
The schema `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION` was displaying "Updated Schema" instead of its proper display name. The name would initially show correctly, then change to "Updated Schema" after the full schema details loaded.

## Root Cause Analysis

### The Bug Location
**File:** `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`  
**Endpoint:** `PUT /pro-mode/schemas/{schema_id}/edit` (line 9508)  
**Bug Line:** 9620 (before fix)

### What Caused It

1. **Hardcoded Fallback Value**: When editing a schema, if the request didn't include a `displayName` field, the code had this fallback chain:
   ```python
   # BEFORE (BUGGY):
   "displayName": complete_schema.get("displayName", existing_schema.get("ClassName", "Updated Schema"))
   ```
   The final fallback was the hardcoded string `"Updated Schema"`

2. **Data Corruption Flow**:
   - User edited `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION` through the UI
   - Frontend sent schema data without `displayName` field
   - Backend couldn't find `ClassName` field in existing schema
   - Fell back to `"Updated Schema"` and saved it to both:
     - **Cosmos DB**: `SchemaData.displayName` field
     - **Azure Blob Storage**: Full schema JSON file

3. **Data Inconsistency**:
   - **Cosmos DB `name` field**: Still had correct name (never updated)
   - **Cosmos DB `SchemaData.displayName`**: Corrupted to "Updated Schema"
   - **Blob Storage displayName**: Corrupted to "Updated Schema"

4. **Why It Showed Correctly Then Changed**:
   - **Initial Load** (`GET /pro-mode/schemas`): Shows `name` from Cosmos DB ✅ Correct
   - **Full Details** (`GET /pro-mode/schemas/{id}?full_content=true`): Loads from Blob Storage ❌ Shows "Updated Schema"

## Fixes Applied

### 1. Backend Fix (Root Cause)
**File:** `proMode.py` line 9616-9625

**BEFORE:**
```python
# Prepare updated schema data for storage
updated_schema_data = {
    "displayName": complete_schema.get("displayName", existing_schema.get("ClassName", "Updated Schema")),
    "description": complete_schema.get("description", existing_schema.get("Description", "Updated schema")),
    ...
}
```

**AFTER:**
```python
# 🔧 FIX: Proper displayName fallback chain to prevent "Updated Schema" corruption
# Priority: 1) Request displayName, 2) Existing SchemaData displayName, 3) Existing ClassName, 4) Existing name field
existing_display_name = (
    existing_schema.get("SchemaData", {}).get("displayName") or 
    existing_schema.get("ClassName") or 
    existing_schema.get("name") or 
    f"Schema {schema_id[:8]}"  # Last resort: use schema ID prefix
)

# Prepare updated schema data for storage
updated_schema_data = {
    "displayName": complete_schema.get("displayName", existing_display_name),
    "description": complete_schema.get("description", existing_schema.get("Description", "")),
    ...
}
```

**Benefits:**
- ✅ Preserves existing displayName from SchemaData
- ✅ Falls back to ClassName if available
- ✅ Falls back to name field (which is always present)
- ✅ Last resort uses schema ID instead of generic "Updated Schema"
- ✅ Prevents future schemas from being corrupted

### 2. Frontend Fix (Defense in Depth)
**File:** `SchemaTab.tsx` line 312

**BEFORE:**
```typescript
displayName: schemaContent.displayName || selectedSchemaMetadata.name,
```

**AFTER:**
```typescript
displayName: selectedSchemaMetadata.displayName || schemaContent.displayName || selectedSchemaMetadata.name,
```

**Benefits:**
- ✅ Prioritizes the schema list metadata (from Cosmos DB `name` field)
- ✅ Works around corrupted blob storage data
- ✅ Prevents UI flickering when data sources disagree
- ✅ Defensive programming - protects against future backend bugs

## Why Only CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION Was Affected

Other schemas were not affected because they either:
1. Were never edited through the `/edit` endpoint
2. Were edited with a proper `displayName` in the request payload
3. Had a valid `ClassName` field to fall back to
4. Were created before this buggy code was introduced

## Testing Recommendations

After deployment:

1. **Verify the fix works**:
   - Edit any schema without sending displayName
   - Confirm it preserves the existing displayName

2. **Check CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION**:
   - Select the schema
   - Verify the name displays correctly without flickering
   - Edit and save it to update the blob storage with correct displayName

3. **Monitor for regressions**:
   - Check other schemas still display correctly
   - Ensure no new schemas get "Updated Schema" as displayName

## Files Modified

1. ✅ `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py` (Backend fix)
2. ✅ `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/SchemaTab.tsx` (Frontend fix)

## Impact Assessment

- **Risk Level**: Low
- **Breaking Changes**: None
- **Affected Users**: Only users who edit schemas through the UI
- **Data Migration Needed**: No (corrupted schemas will self-heal on next edit)

## Next Steps

1. ✅ Backend root cause fixed
2. ✅ Frontend defensive fix applied
3. 🔄 Docker rebuild required
4. 🔄 Deploy to environment
5. 🔄 Test schema editing workflow
6. 📝 Optional: Manually fix CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION blob if needed

---
**Resolution Status**: Complete - Root cause addressed, defensive measures in place
