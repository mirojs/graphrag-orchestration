# Case Creation Panel - File Preview Diagnostic Debugging

**Date:** October 15, 2025  
**Issue:** File preview not working in CaseCreationPanel after Redux state changes  
**Status:** ✅ Debugging added, ready for testing

---

## 🔍 Root Cause Analysis

### User Insight (100% Correct!)
> "after it works well, we updated the redux states yesterday, changing from a single state to two states"

**The Redux state was split:**
- ❌ **Before**: Single `files` array
- ✅ **After**: Separate `inputFiles` and `referenceFiles` arrays

### Investigation Results

#### ✅ Code Structure is CORRECT
The CaseCreationPanel **IS** using the new Redux state correctly:

```tsx
// Line 421-423: Correct Redux state access
const { inputFiles, referenceFiles, uploading } = useSelector(
  (state: RootState) => state.files
);

// Line 818: Correct file merging
const allFiles = [...inputFiles, ...referenceFiles];

// Line 819: Correct preview file lookup
const previewFile = allFiles.find(f => f.id === activePreviewFileId) || null;

// Line 586: Correct library file filtering
const allFiles = type === 'input' ? inputFiles : referenceFiles;
```

**All Redux state access is correct!** ✅

---

## 🐛 Possible Issues

### Scenario 1: Files Not Loaded in Redux State
**Symptom**: `inputFiles` and `referenceFiles` arrays are empty

**Cause**: Files may not be fetched when CaseCreationPanel mounts or when library browser opens

**Check**: Browser console logs will show:
```
[CaseCreationPanel] Files state: { inputFilesCount: 0, referenceFilesCount: 0 }
```

**Solution**: Need to fetch files when opening library browser

---

### Scenario 2: File IDs Don't Match
**Symptom**: `previewFile` is null even though `activePreviewFileId` is set

**Cause**: File object structure changed (e.g., `id` vs `fileId` vs `process_id`)

**Check**: Browser console logs will show:
```
[CaseCreationPanel] Preview state: {
  activePreviewFileId: "some-id",
  allFilesCount: 5,
  previewFile: null,  // ❌ Not found!
  allFileIds: ["id1", "id2", "id3"]
}
```

**Solution**: Verify file ID field name matches between click handler and lookup

---

### Scenario 3: Preview Component Not Rendering
**Symptom**: `previewFile` is found but preview doesn't show

**Cause**: `PreviewWithAuthenticatedBlob` component error or blob URL creation failure

**Check**: Browser console will show errors from PreviewWithAuthenticatedBlob

**Solution**: Check `createAuthenticatedBlobUrl` function and authentication

---

## ✅ Debugging Added

### Debug Log 1: Files State (Line 428)
```tsx
console.log('[CaseCreationPanel] Files state:', {
  inputFilesCount: inputFiles?.length || 0,
  referenceFilesCount: referenceFiles?.length || 0,
  inputFiles: inputFiles?.map(f => ({ id: f.id, name: f.name })) || [],
  referenceFiles: referenceFiles?.map(f => ({ id: f.id, name: f.name })) || []
});
```

**What to look for:**
- ✅ **Good**: `inputFilesCount: 5`, `referenceFilesCount: 2` → Files are loaded
- ❌ **Bad**: `inputFilesCount: 0`, `referenceFilesCount: 0` → Files not loaded

---

### Debug Log 2: Preview State (Line 830)
```tsx
console.log('[CaseCreationPanel] Preview state:', {
  activePreviewFileId,
  allFilesCount: allFiles.length,
  previewFile: previewFile ? { id: previewFile.id, name: previewFile.name } : null,
  allFileIds: allFiles.map(f => f.id)
});
```

**What to look for:**
- ✅ **Good**: `activePreviewFileId: "abc123"`, `previewFile: { id: "abc123", name: "document.pdf" }`
- ❌ **Bad**: `activePreviewFileId: "abc123"`, `previewFile: null` → ID mismatch issue

---

## 🧪 Testing Steps

### 1. Open Case Creation Panel
1. Navigate to Analysis tab
2. Expand "Create New Case" panel
3. **Check console** for `[CaseCreationPanel] Files state:`

**Expected**:
```javascript
{
  inputFilesCount: N,  // N > 0 if files uploaded
  referenceFilesCount: M,  // M >= 0
  inputFiles: [ { id: "...", name: "..." }, ... ]
}
```

---

### 2. Open Library Browser
1. Click "Browse Input Library" or "Browse Reference Library"
2. **Check console** for updated file state logs

**Expected**: File list appears in library table

---

### 3. Click File to Preview
1. Click any file row in library table
2. **Check console** for `[CaseCreationPanel] Preview state:`

**Expected**:
```javascript
{
  activePreviewFileId: "file-id-123",
  allFilesCount: 10,
  previewFile: { id: "file-id-123", name: "document.pdf" },
  allFileIds: ["file-id-123", "file-id-456", ...]
}
```

**Preview should appear** in right panel

---

## 🔧 Quick Fixes (If Needed)

### Fix 1: Files Not Loading
If `inputFilesCount` and `referenceFilesCount` are 0, add file fetching:

```tsx
// Add useEffect to fetch files when library opens
useEffect(() => {
  if (showInputLibrary && inputFiles.length === 0) {
    dispatch(fetchFilesByTypeAsync('input'));
  }
}, [showInputLibrary, dispatch, inputFiles.length]);

useEffect(() => {
  if (showReferenceLibrary && referenceFiles.length === 0) {
    dispatch(fetchFilesByTypeAsync('reference'));
  }
}, [showReferenceLibrary, dispatch, referenceFiles.length]);
```

---

### Fix 2: ID Mismatch
If `activePreviewFileId` is set but `previewFile` is null, check file object structure:

```tsx
// Debug: Log first file structure
console.log('Sample file object:', inputFiles[0]);

// Check if ID field name is correct
const previewFile = allFiles.find(f => 
  f.id === activePreviewFileId || 
  f.fileId === activePreviewFileId || 
  f.process_id === activePreviewFileId
) || null;
```

---

## 📊 Expected Console Output (Successful Preview)

```javascript
[CaseCreationPanel] Files state: {
  inputFilesCount: 5,
  referenceFilesCount: 2,
  inputFiles: [
    { id: "file-1", name: "invoice.pdf" },
    { id: "file-2", name: "contract.pdf" },
    ...
  ],
  referenceFiles: [
    { id: "ref-1", name: "template.pdf" },
    ...
  ]
}

// After clicking a file:
[CaseCreationPanel] Preview state: {
  activePreviewFileId: "file-1",
  allFilesCount: 7,
  previewFile: { id: "file-1", name: "invoice.pdf" },
  allFileIds: ["file-1", "file-2", ..., "ref-1", ...]
}

// From PreviewWithAuthenticatedBlob:
[PreviewWithAuthenticatedBlob] Creating authenticated blob URL for: file-1
[PreviewWithAuthenticatedBlob] Blob URL created successfully
```

---

## 🎯 Next Steps

1. ✅ Debugging logs added
2. 🔄 **Build and deploy** to test
3. 📋 **Open browser console**
4. 🧪 **Follow testing steps** above
5. 📊 **Check console logs** to identify exact issue
6. 🔧 **Apply appropriate fix** based on logs

---

## 💡 Key Insights

- ✅ Redux state access is **already correct**
- ✅ Code structure **matches FilesTab** perfectly
- 🔍 Need **runtime data** to identify the issue
- 📊 Console logs will reveal the exact problem

The debugging will tell us:
1. Are files loaded?
2. Is preview ID set correctly?
3. Does file lookup work?

Once we see the logs, we'll know exactly what to fix! 🎯
