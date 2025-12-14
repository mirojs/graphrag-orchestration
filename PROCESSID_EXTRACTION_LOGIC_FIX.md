# ProcessId Extraction Logic Fix - FileComparisonModal vs FilesTab

## Issue Identified

While comparing the working blob authentication implementation in the Files tab with the failing FileComparisonModal, I discovered a **critical difference in processId extraction logic**.

## Root Cause: Inconsistent ProcessId Extraction

### Working Implementation (FilesTab.tsx):
```tsx
// Line 73 - Always splits file.id by underscore if process_id is missing
const processId = file.process_id || file.id.split('_')[0];
```

### Previous Implementation (FileComparisonModal.tsx):
```tsx
// Conditional splitting only if the extracted value contains underscore
let processId = file.process_id || file.id;
if (typeof processId === 'string' && processId.includes('_')) {
    processId = processId.split('_')[0];
}
```

## Problem Analysis

The FileComparisonModal was using a **conditional splitting approach**, while the FilesTab uses **always split file.id approach**. This could lead to different processId values being generated for the same file, causing 401 errors when the backend expects a specific format.

### Example Scenario:
- **File ID**: `"abc123_filename.pdf"`
- **File process_id**: `undefined`

**FilesTab Result**: `"abc123"` (always splits file.id)
**FileComparisonModal Result**: `"abc123_filename.pdf"` (doesn't split because process_id fallback to full file.id)

The backend preview endpoint `/pro-mode/files/{processId}/preview` likely expects the clean processId format (`"abc123"`) that FilesTab generates.

## Solution Applied

Updated FileComparisonModal to use the **exact same processId extraction logic** as the working FilesTab:

```tsx
const createAuthenticatedBlobUrl = async (file: ProModeFile): Promise<BlobData | null> => {
  try {
    // Use the exact same processId extraction logic as FilesTab
    const processId = file.process_id || file.id.split('_')[0];
    console.log('[FileComparisonModal] ProcessId extraction (FilesTab logic):', {
      file_process_id: file.process_id,
      file_id: file.id,
      file_name: file.name,
      extracted_processId: processId
    });
    
    const relativePath = `/pro-mode/files/${processId}/preview`;
    console.log('[FileComparisonModal] Making preview request to:', relativePath);
    
    const response = await httpUtility.headers(relativePath);
    // ...rest of implementation
  }
}
```

## Enhanced Debugging

Added comprehensive logging to track:
- Original file properties (`process_id`, `id`, `name`)
- Extracted processId value
- API endpoint being called
- Response status
- Successful blob creation details

## Expected Impact

✅ **Consistent ProcessId Generation**: Both components now use identical logic
✅ **Correct API Endpoint Calls**: Properly formatted processId values sent to backend
✅ **Resolved 401 Errors**: Backend should now find the correct files
✅ **Enhanced Troubleshooting**: Detailed logging for future debugging

## Files Modified

1. **`/src/ProModeComponents/FileComparisonModal.tsx`**
   - Updated `createAuthenticatedBlobUrl()` function
   - Aligned processId extraction with FilesTab logic
   - Added detailed console logging for debugging

## Verification Steps

1. **Test Document Comparison**: Open comparison modal and check browser console
2. **Compare Logs**: Verify processId values match between FilesTab and FileComparisonModal
3. **Monitor API Calls**: Ensure `/pro-mode/files/{processId}/preview` calls succeed
4. **Check Blob Creation**: Confirm successful blob URL creation without 401 errors

This fix addresses the core inconsistency between the working Files tab implementation and the failing FileComparisonModal by ensuring both components generate identical processId values for the same files.