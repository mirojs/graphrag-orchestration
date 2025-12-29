# Comparison Button Real Fix - Content-Based Matching

## Problem Analysis

The current implementation is trying to match files by **filenames** from Azure's response:
```
DocumentASourceDocument: '7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf'
DocumentBSourceDocument: 'b4a7651c-6474-46cc-a6c5-5478dc3a1192_purchase_contract.pdf'
```

But the uploaded files have different identifiers, causing the match to fail.

## The Real Solution (From Previous Working Code)

The **correct approach** that was already working:

### Use Content-Based Matching (Not Filename Matching)

Azure API provides:
1. **`DocumentAValue`** and **`DocumentBValue`** - The actual text/values from the documents
2. **`currentAnalysis.result.contents`** - Array of document contents in markdown format
3. **Array Index Alignment**: `allFiles[i]` corresponds to `contents[i+1]` (skip index 0 which is metadata)

### Algorithm

```typescript
// 1. Get the values from Azure schema
const docAValue = inconsistencyData?.DocumentAValue?.valueString || 
                  inconsistencyData?.DocumentAValue || '';
const docBValue = inconsistencyData?.DocumentBValue?.valueString || 
                  inconsistencyData?.DocumentBValue || '';

// 2. Get document contents from Azure analysis
const allDocuments = currentAnalysis.result.contents.slice(1); // Skip index 0

// 3. Search for the VALUE in each document's markdown content
const searchValueA = docAValue.substring(0, 100);
for (let i = 0; i < allDocuments.length; i++) {
  const docContent = allDocuments[i]?.markdown || '';
  
  if (docContent.includes(searchValueA)) {
    docA = allFiles[i]; // CRITICAL: Use same index for files
    break;
  }
}

// 4. Repeat for Document B
const searchValueB = docBValue.substring(0, 100);
for (let i = 0; i < allDocuments.length; i++) {
  const docContent = allDocuments[i]?.markdown || '';
  
  if (docContent.includes(searchValueB)) {
    docB = allFiles[i];
    break;
  }
}
```

## Why This Works

1. **No Filename Dependency**: Doesn't rely on filename matching at all
2. **Uses Azure's Data**: Leverages the actual extracted values from the schema
3. **Array Alignment**: Azure maintains consistent ordering between `files` and `contents` arrays
4. **Direct Content Search**: Searches the actual document text for the extracted values

## Current Error Messages Explained

```
[identifyComparisonDocuments] ⚠️ Azure provided filenames but files not found in uploaded list
```
↓ Should be using content matching instead

```
[identifyComparisonDocuments] ❌ DocumentAValue not found in any document
```
↓ This means the content search is running but failing - need to check:
- Is `currentAnalysis.result.contents` populated?
- Is the array index alignment correct?
- Is the search value too specific?

## Implementation Plan

1. **Remove** complex filename matching logic (extractProcessId, cleanFilename, etc.)
2. **Keep** simple direct filename match as first attempt (in case Azure provides exact names)
3. **Use** content-based matching as primary strategy
4. **Validate** array alignment between files and contents
5. **Add** logging to debug content array structure

## Key Validation Checks

Before searching:
```typescript
if (!currentAnalysis?.result?.contents || currentAnalysis.result.contents.length <= 1) {
  toast.error('Document contents missing from analysis');
  return null;
}

if (allFiles.length !== (currentAnalysis.result.contents.length - 1)) {
  console.warn('Array length mismatch between files and contents');
}
```

## Fallback Strategy

Only if content search fails:
1. Log the mismatch for debugging
2. Show clear error to user
3. **DO NOT** guess or use random files

No silent fallbacks that hide the real issue!
