# Comparison Button File Matching Fix

## Problem Analysis

The comparison button in the Analysis tab is failing to match files due to filename mismatches:

### Error Chain:
1. **Azure provides filenames**: `7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf`
2. **Available files have different names**: The uploaded files list contains files with process IDs that don't match
3. **Content search fails**: Document values don't match the extracted content
4. **Result**: No comparison can be performed

### Console Output:
```
[identifyComparisonDocuments] ⚠️ Azure provided filenames but files not found in uploaded list
[identifyComparisonDocuments] ❌ DocumentAValue not found in any document
[identifyComparisonDocuments] ❌ DocumentBValue not found in any document
[identifyComparisonDocuments] ❌ CONTENT SEARCH FAILED - Missing documents
```

## Root Cause

The file matching logic in `identifyComparisonDocuments` has multiple issues:

1. **Filename Matching**: Tries exact match on `file.name` but Azure provides process_id prefixed filenames
2. **Content Search**: Searches for document values in `currentAnalysis.result.contents` but:
   - Uses substring matching (first 100 chars) which may not be unique
   - Assumes array index alignment between `allDocuments` and `allFiles`
   - Doesn't handle UUID prefixes in filenames

## Solution: Align with FilesTab Approach

The FilesTab has a working file preview system that successfully:
1. Extracts `process_id` from file identifiers
2. Creates authenticated blob URLs using the process_id
3. Handles filename variations gracefully

### Key FilesTab Logic (Lines 119-192):

```typescript
// Extract process_id from file.id and get filename
const processId = file.process_id || file.id.split('_')[0];
const filename = file.name || (file as any).filename || 
                (file as any).original_name || (file as any).originalName || 
                `${file.relationship || 'file'}-${file.id}`;

const createAuthenticatedBlobUrl = async (processId: string, ...) => {
  const relativePath = `/pro-mode/files/${processId}/preview`;
  const response = await httpUtility.headers(relativePath);
  // ... blob creation logic
};
```

## Proposed Fix Strategy

### 1. Enhanced Filename Matching (Multi-Strategy)

```typescript
// Strategy 1: Exact name match
const exactMatch = allFiles.find(f => f.name === docAFileName);

// Strategy 2: Process ID match (extract UUID from both sides)
const extractProcessId = (str: string) => {
  const match = str.match(/^([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/);
  return match ? match[1] : null;
};

const azureProcessId = extractProcessId(docAFileName);
const processIdMatch = allFiles.find(f => {
  const fileProcessId = f.process_id || extractProcessId(f.id);
  return fileProcessId === azureProcessId;
});

// Strategy 3: Filename suffix match (ignore UUID prefix)
const cleanFilename = (name: string) => 
  name.replace(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}[_-]/, '');

const suffixMatch = allFiles.find(f => 
  cleanFilename(f.name).toLowerCase() === cleanFilename(docAFileName).toLowerCase()
);

const docA = exactMatch || processIdMatch || suffixMatch;
```

### 2. Improved Content Search

Instead of assuming index alignment, use the analysis results' source document metadata:

```typescript
// Find the document content that matches the file
const findDocumentContent = (file: ProModeFile) => {
  return currentAnalysis?.result?.contents?.find((content: any) => {
    if (content.startPageNumber === 0 && content.endPageNumber === 0) {
      return false; // Skip analysis metadata
    }
    
    const metadata = content.metadata || {};
    const contentFilename = metadata.filename || '';
    const fileProcessId = file.process_id || extractProcessId(file.id);
    const contentProcessId = extractProcessId(contentFilename);
    
    return contentProcessId === fileProcessId ||
           cleanFilename(contentFilename) === cleanFilename(file.name);
  });
};

// Search for value in the specific document's content
const docAContent = findDocumentContent(docA);
if (docAContent?.markdown?.includes(searchValueA)) {
  // Found! This confirms docA contains the expected value
}
```

### 3. Fallback to FilesTab Selection Logic

If Azure metadata is unreliable, fall back to user's file selection:

```typescript
// Use selected files from FilesTab
const selectedFiles = [
  ...selectedInputFiles.filter(f => selectedInputFileIds.includes(f.id)),
  ...selectedReferenceFiles.filter(f => selectedReferenceFileIds.includes(f.id))
];

if (selectedFiles.length >= 2) {
  return {
    documentA: selectedFiles[0],
    documentB: selectedFiles[1],
    comparisonType: 'user-selection' as const
  };
}
```

## Implementation Plan

### Phase 1: Add Filename Utility Functions (Lines 1175-1177)
```typescript
// Add before identifyComparisonDocuments function
const extractProcessId = (str: string): string | null => {
  if (!str) return null;
  const match = str.match(/^([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})/);
  return match ? match[1] : null;
};

const cleanFilename = (name: string): string => {
  if (!name) return '';
  return name.replace(/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}[_-]/, '');
};

const findFileByMultipleStrategies = (
  allFiles: ProModeFile[], 
  targetName: string
): ProModeFile | null => {
  if (!targetName) return null;
  
  // Strategy 1: Exact match
  let match = allFiles.find(f => f.name === targetName);
  if (match) {
    console.log('[findFile] ✅ Exact name match:', match.name);
    return match;
  }
  
  // Strategy 2: Process ID match
  const targetProcessId = extractProcessId(targetName);
  if (targetProcessId) {
    match = allFiles.find(f => {
      const fileProcessId = f.process_id || f.processId || extractProcessId(f.id);
      return fileProcessId === targetProcessId;
    });
    if (match) {
      console.log('[findFile] ✅ Process ID match:', { target: targetProcessId, found: match.name });
      return match;
    }
  }
  
  // Strategy 3: Clean filename match (ignore UUID prefixes)
  const cleanTarget = cleanFilename(targetName).toLowerCase();
  match = allFiles.find(f => cleanFilename(f.name).toLowerCase() === cleanTarget);
  if (match) {
    console.log('[findFile] ✅ Clean filename match:', match.name);
    return match;
  }
  
  console.warn('[findFile] ❌ No match found for:', { targetName, targetProcessId, cleanTarget });
  return null;
};
```

### Phase 2: Update identifyComparisonDocuments (Lines 1198-1230)
Replace the direct filename matching section with:

```typescript
// Step 2: If Azure provided exact filenames, use enhanced matching
if (docAFileName && docBFileName) {
  const docA = findFileByMultipleStrategies(allFiles, docAFileName);
  const docB = findFileByMultipleStrategies(allFiles, docBFileName);
  
  if (docA && docB) {
    console.log('[identifyComparisonDocuments] ✅ MULTI-STRATEGY FILE MATCH:', {
      docA: docA.name,
      docB: docB.name,
      docAPageNum,
      docBPageNum,
      docAProcessId: docA.process_id || extractProcessId(docA.id),
      docBProcessId: docB.process_id || extractProcessId(docB.id)
    });
    
    return {
      documentA: docA,
      documentB: docB,
      pageNumberA: docAPageNum,
      pageNumberB: docBPageNum,
      comparisonType: 'azure-direct-filename' as const
    };
  } else {
    console.warn('[identifyComparisonDocuments] ⚠️ Multi-strategy matching failed:', {
      docAFileName,
      docBFileName,
      foundDocA: !!docA,
      foundDocB: !!docB,
      availableFiles: allFiles.map(f => ({
        name: f.name,
        process_id: f.process_id || extractProcessId(f.id)
      }))
    });
  }
}
```

### Phase 3: Improve Content Search (Lines 1280-1340)
Replace array index matching with proper document content lookup:

```typescript
// Helper to find document content for a specific file
const findDocumentContentForFile = (file: ProModeFile): DocumentContent | null => {
  return currentAnalysis?.result?.contents?.find((content: any) => {
    // Skip analysis metadata
    if (content.startPageNumber === 0 && content.endPageNumber === 0) {
      return false;
    }
    
    const metadata = content.metadata || {};
    const contentFilename = metadata.filename || '';
    const fileProcessId = file.process_id || file.processId || extractProcessId(file.id);
    const contentProcessId = extractProcessId(contentFilename);
    
    // Match by process ID or clean filename
    return contentProcessId === fileProcessId ||
           cleanFilename(contentFilename).toLowerCase() === cleanFilename(file.name).toLowerCase();
  }) || null;
};

// Step 6: Search for DocumentAValue using proper document lookup
let docA: ProModeFile | null = null;
const searchValueA = docAValue.substring(0, 100);

for (const file of allFiles) {
  const content = findDocumentContentForFile(file);
  if (content?.markdown?.includes(searchValueA)) {
    docA = file;
    console.log('[identifyComparisonDocuments] ✅ FOUND DocumentAValue in file:', {
      fileName: file.name,
      processId: file.process_id || extractProcessId(file.id),
      searchValue: searchValueA.substring(0, 50),
      contentPreview: content.markdown.substring(0, 100)
    });
    break;
  }
}
```

### Phase 4: Add User Selection Fallback (After content search fails)

```typescript
// Step 8: Fallback to user's file selection if content search fails
if (!docA || !docB) {
  console.warn('[identifyComparisonDocuments] Content search failed, trying user selection fallback');
  
  const selectedFiles = [
    ...selectedInputFiles.filter(f => selectedInputFileIds.includes(f.id)),
    ...selectedReferenceFiles.filter(f => selectedReferenceFileIds.includes(f.id))
  ];
  
  if (selectedFiles.length >= 2) {
    console.log('[identifyComparisonDocuments] ✅ Using user-selected files as fallback:', {
      docA: selectedFiles[0].name,
      docB: selectedFiles[1].name,
      selectedCount: selectedFiles.length
    });
    
    return {
      documentA: selectedFiles[0],
      documentB: selectedFiles[1],
      comparisonType: 'user-selection-fallback' as const
    };
  }
}
```

## Expected Outcome

With these changes:

1. ✅ Filenames with UUID prefixes will be properly matched
2. ✅ Process IDs will be used for reliable file identification
3. ✅ Content search will use proper document-to-file mapping
4. ✅ User selection provides a reliable fallback
5. ✅ Comparison modal will successfully load and display documents

## Testing Checklist

- [ ] Azure-provided filenames match correctly
- [ ] Process ID matching works for UUID-prefixed files
- [ ] Clean filename matching works when UUIDs differ
- [ ] Content search finds correct documents
- [ ] User selection fallback works
- [ ] Comparison modal opens with correct documents
- [ ] Error messages are helpful and actionable
