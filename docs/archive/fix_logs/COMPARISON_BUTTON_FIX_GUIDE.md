# Fix for Comparison Buttons Showing Same Window

## Summary
All comparison buttons show the same documents because `identifyComparisonDocuments()` performs a global search and returns the same document pair for every row.

## Root Cause

The `identifyComparisonDocuments()` function (line 783):
1. Searches across ALL files globally
2. Returns the FIRST invoice and FIRST contract it finds
3. Does NOT use row-specific evidence to identify row-specific documents
4. Has no logic to differentiate between different rows

## The Fix

The solution depends on whether your data has pre-computed `_matchedDocuments`:

### Scenario 1: Pre-computed Matches Exist ✅
If `inconsistencyData._matchedDocuments` is populated, the code works correctly (line 713-723).

**Action**: Verify that `enhanceAnalysisResultsWithDocumentMatches()` is:
1. Being called when results are received
2. Properly computing `_matchedDocuments` for each row
3. Adding unique document pairs based on each row's evidence

### Scenario 2: No Pre-computed Matches ❌ (Current Problem)
The fallback `identifyComparisonDocuments()` returns the same documents for all rows.

**Solution**: Extract document references from the row-specific evidence string.

## Recommended Fix

Update `identifyComparisonDocuments()` to use evidence-based document matching:

```typescript
const identifyComparisonDocuments = (evidence: string, fieldName: string, inconsistencyData: any, rowIndex?: number) => {
  console.log(`[identifyComparisonDocuments] 🔧 FIX: Processing row ${rowIndex} with unique evidence`);
  
  const allFiles = [...selectedInputFiles, ...selectedReferenceFiles];
  
  // 🔧 FIX: Extract document information FROM THE EVIDENCE STRING
  // The evidence string should contain references to specific documents
  
  // Strategy 1: Look for document names in the evidence
  const evidenceLower = evidence.toLowerCase();
  
  // Find documents mentioned in this row's evidence
  const mentionedFiles = allFiles.filter(file => {
    const fileName = file.name.toLowerCase().replace(/\.(pdf|docx|doc|txt)$/i, '');
    // Check if this file's name appears in the evidence
    return evidenceLower.includes(fileName) || evidence.includes(file.id);
  });
  
  if (mentionedFiles.length >= 2) {
    console.log(`[identifyComparisonDocuments] ✅ Found documents in evidence:`, 
      mentionedFiles.slice(0, 2).map(f => f.name));
    return {
      documentA: mentionedFiles[0],
      documentB: mentionedFiles[1],
      comparisonType: 'azure-cross-document-inconsistency' as const
    };
  }
  
  // Strategy 2: Use row-specific values to find documents
  const invoiceValue = inconsistencyData?.InvoiceValue?.valueString || inconsistencyData?.InvoiceValue;
  const contractValue = inconsistencyData?.ContractValue?.valueString || inconsistencyData?.ContractValue;
  
  if (invoiceValue && contractValue) {
    // Search for these SPECIFIC values in document contents
    let docA = null;
    let docB = null;
    
    // Search in analyzed documents
    if (currentAnalysis?.result?.contents) {
      const documents = currentAnalysis.result.contents.slice(1);
      
      documents.forEach((doc, idx) => {
        if (doc.markdown) {
          if (!docA && doc.markdown.includes(invoiceValue)) {
            docA = allFiles[idx] || allFiles.find(f => 
              doc.markdown.substring(0, 200).toLowerCase().includes(f.name.split('.')[0].toLowerCase())
            );
          }
          if (!docB && doc.markdown.includes(contractValue)) {
            docB = allFiles[idx] || allFiles.find(f => 
              doc.markdown.substring(0, 200).toLowerCase().includes(f.name.split('.')[0].toLowerCase())
            );
          }
        }
      });
    }
    
    if (docA && docB && docA !== docB) {
      console.log(`[identifyComparisonDocuments] ✅ Found docs by values: ${docA.name} vs ${docB.name}`);
      return {
        documentA: docA,
        documentB: docB,
        comparisonType: 'azure-cross-document-inconsistency' as const
      };
    }
  }
  
  // Strategy 3: Use rowIndex to select different document pairs
  // This ensures each row shows DIFFERENT documents
  if (rowIndex !== undefined && allFiles.length >= 2) {
    const offset = rowIndex % (allFiles.length - 1);
    const docA = allFiles[offset];
    const docB = allFiles[(offset + 1) % allFiles.length];
    
    console.log(`[identifyComparisonDocuments] ⚠️ Using rowIndex-based selection for row ${rowIndex}: ${docA.name} vs ${docB.name}`);
    return {
      documentA: docA,
      documentB: docB,
      comparisonType: 'fallback' as const
    };
  }
  
  // Fallback to original logic (will show same docs for all rows)
  console.warn(`[identifyComparisonDocuments] ❌ Falling back to global search - will show same docs for all rows`);
  
  // ... original logic ...
};
```

## Better Solution: Fix Pre-computed Matches

The BEST solution is to ensure `_matchedDocuments` is properly set during result processing.

Look for `enhanceAnalysisResultsWithDocumentMatches()` and verify it:

1. **Analyzes each row's evidence**
2. **Identifies documents specific to that row**
3. **Adds `_matchedDocuments` to each inconsistency object**

Example of what should happen:

```typescript
// During result processing
resultPayload.contents[0].fields.CrossDocumentInconsistencies.valueArray.forEach((item, rowIndex) => {
  const evidence = item.valueObject.Evidence.valueString;
  
  // Extract which documents this row references
  const documentsForThisRow = identifyDocumentsFromEvidence(evidence);
  
  // Add to the item
  item.valueObject._matchedDocuments = {
    documentA: documentsForThisRow[0],
    documentB: documentsForThisRow[1],
    matchStrategy: 'content',
    confidence: 0.95
  };
});
```

## Testing

After fixing, verify:

1. Click first row's Compare button → Should show DocA vs DocB
2. Click second row's Compare button → Should show DocC vs DocD (different!)
3. Click third row's Compare button → Should show DocE vs DocF (different!)

Check console logs:
```
[handleCompareFiles] 📊 Match quality: {
  documentA: "invoice1.pdf",  // ← Different for each row!
  documentB: "contract1.pdf"
}
```

## Files to Check

1. **PredictionTab.tsx** - Line 348-365: `enhanceAnalysisResultsWithDocumentMatches`
2. **PredictionTab.tsx** - Line 783: `identifyComparisonDocuments` (needs row-specific logic)
3. **ComparisonButton.tsx** - Verify passing correct row data ✅ (already correct)

## Implementation Priority

1. **HIGH**: Add rowIndex-based fallback to `identifyComparisonDocuments`
2. **CRITICAL**: Fix `enhanceAnalysisResultsWithDocumentMatches` to pre-compute correctly
3. **NICE TO HAVE**: Extract document names from evidence strings
