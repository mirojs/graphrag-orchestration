# Schema Duplicate Detection - Frontend Implementation Guide

## Overview
The backend now supports duplicate schema detection and returns 409 conflicts when attempting to upload schemas with existing names. This guide shows how to update the frontend to handle these conflicts gracefully.

## Files to Update

### 1. proModeApiService.ts
**Location:** `src/ContentProcessorWeb/src/ProModeServices/proModeApiService.ts`
**Changes:**
- Update `uploadSchemas` function to accept `overwrite` parameter
- Add query parameter `?overwrite=true` when overwrite is requested
- Add new `checkSchemaDuplicates` function for pre-upload validation

**Implementation:** Copy code from `frontend_api_service_update.ts`

### 2. proModeStore.ts
**Location:** `src/ContentProcessorWeb/src/ProModeStores/proModeStore.ts`
**Changes:**
- Update `uploadSchemasAsync` thunk to handle duplicate errors (409 status)
- Add special error handling for `SCHEMA_EXISTS` responses
- Include overwrite parameter in upload payload
- Add new `checkSchemaDuplicatesAsync` thunk (optional)

**Implementation:** Copy code from `frontend_redux_store_update.ts`

### 3. SchemaTab.tsx
**Location:** `src/ContentProcessorWeb/src/ProModeComponents/SchemaTab.tsx`
**Changes:**
- Add state for duplicate confirmation dialog
- Update `handleUploadSchemas` to catch duplicate errors
- Add `handleOverwriteConfirm` function
- Add duplicate confirmation dialog component
- Add MessageBarType import

**Implementation:** Copy code from `frontend_schema_tab_update.tsx`

## Testing Steps

### 1. Backend Testing (Already Implemented)
```bash
# Test duplicate detection
python test_schema_duplicate_detection.py
```

### 2. Frontend Testing
1. Open ProMode application in browser
2. Go to Schema tab
3. Upload a schema file (should succeed)
4. Upload the same schema file again
   - Should show duplicate confirmation dialog
   - Dialog should show existing schema details
   - Should offer "Overwrite" and "Cancel" options
5. Click "Overwrite" - should update the schema
6. Upload a schema with different name - should succeed normally

### 3. Error Handling Testing
1. Test with invalid JSON files
2. Test with network errors
3. Test canceling duplicate dialog
4. Verify Redux state updates correctly

## Expected User Experience

### Before Fix
- User uploads schema → always creates new duplicate
- No indication of existing schemas
- Database fills with duplicate entries

### After Fix
- User uploads new schema → succeeds normally
- User uploads duplicate schema → shows confirmation dialog:
  ```
  Schema Already Exists
  
  A schema with this name already exists. What would you like to do?
  
  Existing Schema Details:
  • Name: Invoice Schema
  • Fields: 5
  • Version: 1.0.0
  • Created: 2025-08-03 10:30:15
  • Created by: upload
  
  Available Options:
  • Overwrite: Replace the existing schema with your new version
  • Rename: Change the schema name in your JSON file  
  • Cancel: Keep the existing schema unchanged
  
  [Overwrite Existing Schema] [Cancel]
  ```
- User chooses overwrite → updates existing schema with new version
- User chooses cancel → returns to upload dialog

## API Endpoints

### Upload Schema (Enhanced)
```
POST /pro/schemas/upload?overwrite=false
POST /pro/schemas/upload?overwrite=true
```

**Responses:**
- `200` - Success (new schema created or existing updated)
- `409` - Conflict (duplicate name, overwrite=false)
- `422` - Validation error (bad JSON, missing fields)
- `500` - Server error

### Example 409 Response
```json
{
  "detail": "Schema 'Invoice Schema' already exists",
  "code": "SCHEMA_EXISTS",
  "conflict_type": "duplicate_name",
  "existing_schema": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "name": "Invoice Schema",
    "field_count": 5,
    "created_at": "2025-08-03T10:30:15.123456",
    "created_by": "upload",
    "description": "Schema for invoice processing"
  },
  "suggested_actions": {
    "overwrite": "Add ?overwrite=true to URL to replace existing schema",
    "rename": "Rename the schema in your JSON file from 'Invoice Schema' to 'Invoice Schema_v2'",
    "cancel": "Cancel upload and keep existing schema"
  },
  "overwrite_url": "/pro/schemas/upload?overwrite=true"
}
```

## Deployment Notes

1. Deploy backend changes first (already done)
2. Test backend with curl/Postman
3. Deploy frontend changes
4. Test end-to-end user flow
5. Update user documentation

## Rollback Plan

If issues occur:
1. Frontend: Revert SchemaTab.tsx changes (upload will work but no duplicate detection)
2. Backend: Remove overwrite parameter (will create duplicates but won't break)
3. Both: Remove duplicate checking logic entirely

## Monitoring

Watch for:
- Increased 409 responses (normal - indicates duplicate detection working)
- User complaints about "broken uploads" (may indicate dialog issues)
- Database growth rate (should decrease with fewer duplicates)
- User adoption of overwrite feature vs. manual renaming

## Future Enhancements

1. **Batch Upload Handling:** Handle multiple files with some duplicates
2. **Smart Merge:** Compare schemas and suggest field-level merges
3. **Version History:** Show full version history of schema updates
4. **Auto-Rename:** Automatically suggest incremental names (v1, v2, etc.)
5. **Preview Diff:** Show visual comparison between existing and new schema