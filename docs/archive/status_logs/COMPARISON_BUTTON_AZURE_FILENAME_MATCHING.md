# Comparison Button - Azure Filename Matching Issue

## The Real Problem

### What's Happening:
1. **We defined schema** asking Azure to output `DocumentASourceDocument` and `DocumentBSourceDocument`
2. **Azure returns**: `7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf`
3. **Our code has**: Files in `selectedInputFiles`/`selectedReferenceFiles` arrays
4. **Matching fails**: Azure's filename ≠ our file.name

### The Question:
**What format do our uploaded files use for their `name` or `id` properties?**

## Possible Scenarios

### Scenario A: Files Have Same Format
If `file.name` = `7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf`
- **Solution**: Direct match should work
- **Issue**: Not happening, so this is NOT the case

### Scenario B: Files Have Clean Names
If `file.name` = `contoso_lifts_invoice.pdf` (without UUID prefix)
- **Solution**: Strip UUID from Azure's response and match
- **Code**: `cleanFilename()` function should work

### Scenario C: Files Have Different UUID
If `file.name` = `different-uuid_contoso_lifts_invoice.pdf`
- **Solution**: Match on clean filename (without any UUID)
- **Code**: `cleanFilename()` on both sides

### Scenario D: Files Use `id` Property for UUID
If `file.name` = `contoso_lifts_invoice.pdf` AND `file.id` = `7543c5b8-...`
- **Solution**: Extract UUID from Azure's response, match with `file.id`
- **Code**: `extractProcessId()` then match with `file.id` or `file.process_id`

## Debug Strategy

Need to add logging to see what's ACTUALLY in the uploaded files:

```typescript
console.log('[identifyComparisonDocuments] 📁 Azure vs Uploaded Files:', {
  azureDocAName: docAFileName,
  azureDocBName: docBFileName,
  uploadedFiles: allFiles.map(f => ({
    name: f.name,
    id: f.id,
    process_id: f.process_id,
    fileName: f.fileName,
    // Log ALL properties to see what's available
    allKeys: Object.keys(f)
  }))
});
```

## Expected Fix

Once we know the file structure, the fix is:

### If files have clean names (likely):
```typescript
// Azure: '7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf'
// File:  'contoso_lifts_invoice.pdf'

const cleanAzureName = docAFileName.replace(/^[a-f0-9-]{36}_/, '');
const docA = allFiles.find(f => f.name === cleanAzureName);
```

### If files have processId in separate property:
```typescript
// Azure: '7543c5b8-903b-466c-95dc-1a920040d10c_contoso_lifts_invoice.pdf'
// File:  { id: '7543c5b8-903b-466c-95dc-1a920040d10c', name: 'contoso_lifts_invoice.pdf' }

const azureProcessId = docAFileName.match(/^([a-f0-9-]{36})_/)?.[1];
const docA = allFiles.find(f => f.id === azureProcessId || f.process_id === azureProcessId);
```

## Content-Based Fallback

If filename matching truly fails, we SHOULD use content-based matching as fallback:
1. Get `DocumentAValue` from inconsistency data
2. Search in `currentAnalysis.result.contents[i].markdown`
3. When found at index `i`, use `allFiles[i-1]` (accounting for metadata at index 0)

This is the **previous working solution** that should be our fallback!

## Action Plan

1. **Add comprehensive logging** to see actual file structure
2. **Fix filename matching** based on actual structure
3. **Keep content-based fallback** as secondary strategy
4. **Validate array alignment** between files and contents
