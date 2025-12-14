# Analysis 401 Error & Collection Key Investigation - Resolution

## Date: October 22, 2025

---

## Issue #1: Start Analysis 401 Errors ✅ FIXED

### Problem
The "Start Analysis" button under the Analysis tab was reporting 401 authentication errors, but the error handling wasn't providing clear guidance to users on how to resolve the issue.

### Root Cause
- The authentication token can expire during long analysis operations
- The existing error handling grouped 401 with other generic errors
- No user-friendly message or action button to refresh the page

### Solution Applied
Enhanced the error handling in `PredictionTab.tsx` (lines ~797-831) to:

1. **Detect 401 errors early** - Check multiple error properties:
   ```typescript
   const is401Error = error?.status === 401 || 
                     error?.response?.status === 401 ||
                     error?.message?.includes('401') || 
                     error?.message?.includes('Authentication') ||
                     error?.message?.includes('Unauthorized');
   ```

2. **Provide actionable feedback** - Show clickable toast message:
   ```typescript
   toast.error(
     'Session expired. Click here to refresh the page and try again.',
     {
       autoClose: false,
       closeButton: true,
       onClick: () => window.location.reload()
     }
   );
   ```

3. **Track error for analytics** - Log specific 401 events:
   ```typescript
   trackProModeEvent('ContentAnalysisError', { 
     error: '401_AUTHENTICATION_EXPIRED',
     errorType: 'HTTP_401'
   });
   ```

### Testing Recommendations
1. Start an analysis with a valid session
2. Clear/expire your auth token in browser DevTools
3. Click "Start Analysis" again
4. Verify the helpful "Session expired. Click here to refresh" message appears
5. Click the toast to verify page refresh works

---

## Issue #2: Collection Key Missing in Cosmos DB ⚠️ NEEDS CLARIFICATION

### Investigation Results

#### What IS Stored in Cosmos DB (ProSchemaMetadata)
When you upload a schema, the following fields are saved:

```python
{
  "id": "uuid-string",                    # Unique schema identifier
  "name": "schema_name",                  # Schema display name
  "description": "Schema description",    # Optional description
  "fieldCount": 10,                       # Number of fields
  "fieldNames": ["field1", "field2"],     # List of field names
  "fileSize": 1024,                       # Size in bytes
  "fileName": "original.json",            # Original filename
  "contentType": "application/json",      # MIME type
  "createdBy": "user@email.com",          # Creator
  "createdAt": "2025-10-22T...",          # Timestamp
  "version": "1.0.0",                     # Schema version
  "status": "active",                     # Status
  "baseAnalyzerId": "prebuilt-...",       # Analyzer ID
  "blobUrl": "https://...",               # ✅ Link to full schema in blob storage
  "blobContainer": "pro-schemas",         # ✅ Container name
  "group_id": "azure-ad-group-id",        # ✅ For group isolation (optional)
  "tags": [],                             # Optional tags
  "lastAccessed": null                    # Last access time
}
```

#### What is NOT Stored
❌ `collection_key` or `collectionKey` field

### Questions for You

**Please clarify what "collection key" means in your context:**

1. **Are you referring to the Cosmos DB collection name?**
   - The collection name is: `Schemas_pro`
   - It's accessed via: `get_pro_mode_container_name(app_config.app_cosmos_container_schema)`
   - This is a backend constant, not stored per-schema

2. **Are you referring to a partition key for Cosmos DB?**
   - Current partition key: MongoDB API doesn't require explicit partition keys
   - Group isolation uses: `group_id` field (optional)
   - Schema ID is unique: `id` field

3. **Are you expecting a different identifier?**
   - Schema-to-Analysis linking uses: `schemaId` in analysis requests
   - Blob storage reference uses: `blobUrl` field
   - Original filename uses: `fileName` field

4. **Is this related to Azure Content Understanding analyzers?**
   - Analyzer ID is stored: `baseAnalyzerId` field
   - Analysis uses: `analyzerId` generated at runtime

### How to Check Your Uploaded Schema

If you just uploaded a schema, you can check what was saved by:

**Option 1: Via Azure Portal**
1. Go to Azure Portal → Your Cosmos DB account
2. Navigate to Data Explorer
3. Select database → `Schemas_pro` collection
4. Find your recently uploaded schema by timestamp
5. Check all fields present

**Option 2: Via Backend API** (if you have access)
```bash
GET /pro-mode/schemas
# Returns all schemas with their fields
```

**Option 3: Via Backend Logs**
Check the backend logs when you uploaded - they show exactly what was saved:
```
[save-enhanced] Schema uploaded to blob storage: <blob_url>
[save-enhanced] ✅ Schema metadata saved to Cosmos DB
```

### Possible Solutions

#### If you need a collection reference field:
We can add a `collectionName` field to track which Cosmos DB collection contains the schema:

```python
metadata_dict = metadata.model_dump()
metadata_dict["collectionName"] = pro_container_name  # Add "Schemas_pro"
if group_id:
    metadata_dict["group_id"] = group_id
collection.insert_one(metadata_dict)
```

#### If you need a different partition key strategy:
We can add explicit partition key support for better query performance:

```python
metadata_dict = metadata.model_dump()
metadata_dict["partitionKey"] = group_id or "default"  # Partition by group
collection.insert_one(metadata_dict)
```

---

## Action Items

### ✅ Completed
- [x] Fix 401 error handling in Analysis tab
- [x] Add user-friendly "Session expired" message
- [x] Investigate schema upload code
- [x] Document current Cosmos DB schema structure

### ⏳ Awaiting Your Input
- [ ] Clarify what "collection key" means in your use case
- [ ] Confirm if current `group_id` field meets your needs
- [ ] Specify if additional identifiers are needed

### 🔄 Next Steps (After Clarification)
- [ ] Add missing field if needed
- [ ] Update schema upload endpoint
- [ ] Add migration script for existing schemas
- [ ] Update frontend to display/use new field

---

## Files Modified
- `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeComponents/PredictionTab.tsx`
  - Enhanced 401 error detection and user guidance
  - Added clickable toast with page refresh

---

## Related Documentation
- `GROUP_ISOLATION_COMPLETE_DOCUMENTATION.md` - Explains `group_id` usage
- `DUAL_STORAGE_ARCHITECTURE_VALIDATED.md` - Explains blob + Cosmos DB pattern
- `SCHEMA_PREDICTION_TABS_401_ANALYSIS.md` - Previous 401 error analysis

---

## Questions?

Please provide more context about:
1. What you expected to see as "collection key"
2. What you're trying to achieve with this identifier
3. Where/how you'll use this collection key

Once I understand your requirements, I can add the appropriate field to the schema metadata structure.
