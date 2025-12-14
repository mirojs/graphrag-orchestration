# Strategy Cleanup: Use Azure's Actual Response

## The Problem You Identified

**You're absolutely right:** The current code has **6 complex strategies** that are essentially **fallbacks hiding errors**, when Azure's API **already tells us which documents to compare!**

### Azure API Returns (from schema):
```python
"SourceDocument": {
    "type": "string",
    "description": "Primary source document - 'Invoice' or 'Contract'"
},
"InvoiceField": {
    "type": "string",
    "description": "Field in the invoice where inconsistency is found"
},
"ContractField": {
    "type": "string",
    "description": "Field in the contract that conflicts"
}
```

**Azure literally tells us:**
- Which document type has the inconsistency ("Invoice" or "Contract")
- Which field in the invoice
- Which field in the contract

**We should just USE THIS DATA!**

---

## Current Code is Over-Engineered

### What we're doing now (WRONG):
```typescript
// Strategy 1: Try to find content match ❌
// Strategy 2: Try to find DocumentTypes ❌
// Strategy 3: Use rowIndex math ❌ (arbitrary rotation)
// Strategy 4: Search for "invoice" in filename ❌
// Strategy 5: Use upload context ❌
// Strategy 6: Just use first two files ❌
```

**None of these use the fact that Azure ALREADY identified:**
- `SourceDocument: "Invoice"` → This inconsistency is FROM the invoice
- `InvoiceField: "Payment Terms"` → Found in invoice's Payment Terms section
- `ContractField: "Payment Schedule"` → Conflicts with contract's Payment Schedule

---

## What We SHOULD Do (ONE Strategy)

### **Use Azure's SourceDocument Field:**

```typescript
const identifyComparisonDocuments = (
  evidence: string,
  fieldName: string,
  inconsistencyData: any,
  rowIndex?: number
) => {
  // Extract what Azure TELLS us
  const sourceDoc = inconsistencyData?.SourceDocument?.valueString || 
                    inconsistencyData?.SourceDocument;
  
  const invoiceField = inconsistencyData?.InvoiceField?.valueString || 
                       inconsistencyData?.InvoiceField;
  
  const contractField = inconsistencyData?.ContractField?.valueString || 
                        inconsistencyData?.ContractField;
  
  // If Azure doesn't provide this data, ERROR LOUDLY (don't hide it!)
  if (!sourceDoc || !invoiceField || !contractField) {
    console.error('[identifyComparisonDocuments] ❌ MISSING AZURE DATA:', {
      hasSourceDoc: !!sourceDoc,
      hasInvoiceField: !!invoiceField,
      hasContractField: !!contractField,
      inconsistencyData
    });
    
    toast.error('Azure analysis did not provide document source information. Cannot identify comparison documents.');
    return null; // FAIL LOUDLY, don't fall back!
  }
  
  // Find the actual uploaded files by document type
  const invoiceFile = allFiles.find(f => 
    isInvoiceType(f, sourceDoc === 'Invoice')
  );
  
  const contractFile = allFiles.find(f => 
    isContractType(f, sourceDoc === 'Contract')
  );
  
  if (!invoiceFile || !contractFile) {
    console.error('[identifyComparisonDocuments] ❌ CANNOT MATCH FILES:', {
      sourceDoc,
      uploadedFiles: allFiles.map(f => f.name),
      foundInvoice: !!invoiceFile,
      foundContract: !!contractFile
    });
    
    toast.error('Cannot match Azure analysis results to uploaded files.');
    return null; // FAIL LOUDLY!
  }
  
  console.log('[identifyComparisonDocuments] ✅ Matched using Azure SourceDocument:', {
    sourceDoc,
    invoiceFile: invoiceFile.name,
    contractFile: contractFile.name,
    invoiceField,
    contractField
  });
  
  return {
    documentA: invoiceFile,
    documentB: contractFile,
    comparisonType: 'azure-source-document' as const,
    // Include field information for highlighting
    invoiceField,
    contractField
  };
};
```

---

## Why This is Better

### **Before (6 strategies):**
```
❌ Hides errors with fallbacks
❌ Uses arbitrary logic (rowIndex math, filename patterns)
❌ Ignores what Azure already told us
❌ Complex, hard to debug
❌ Each row shows different random files (not necessarily the RIGHT files)
```

### **After (1 strategy):**
```
✅ Uses Azure's explicit SourceDocument field
✅ Fails loudly if data is missing (so we can fix the schema)
✅ Shows the CORRECT documents (what Azure actually analyzed)
✅ Simple, easy to debug
✅ Each row shows the ACTUAL documents that have the inconsistency
```

---

## The Real Fix

### **Step 1: Verify Azure Returns SourceDocument**

Check your actual API response:
```javascript
// In console logs, look for:
inconsistencyData: {
  Evidence: "...",
  SourceDocument: "Invoice",  // ← THIS IS THE KEY!
  InvoiceField: "Payment Terms",
  ContractField: "Payment Schedule"
}
```

If Azure is NOT returning `SourceDocument`, that's the REAL problem to fix (schema or backend).

### **Step 2: Remove All Fallback Strategies**

```typescript
// DELETE these strategies:
// ❌ Strategy 1: Content-based matching
// ❌ Strategy 2: DocumentTypes
// ❌ Strategy 3: Row-specific selection (rowIndex math)
// ❌ Strategy 4: Filename pattern matching
// ❌ Strategy 5: Upload context
// ❌ Strategy 6: Final fallback

// KEEP only:
// ✅ ONE strategy: Use SourceDocument from Azure
```

### **Step 3: Fail Loudly When Data is Missing**

```typescript
if (!sourceDoc) {
  throw new Error('Azure API did not return SourceDocument field!');
  // Don't hide this with fallbacks - FIX THE ROOT CAUSE
}
```

---

## Your Key Insight

> "It's like fallback, just hiding errors. We only need one effective way."

**Exactly right!** The fallbacks are:
1. **Hiding the real problem** (Azure not returning SourceDocument)
2. **Showing wrong documents** (arbitrary files based on filename patterns)
3. **Making debugging impossible** (which strategy actually ran?)

**Instead:**
- Use what Azure provides
- If Azure doesn't provide it, fail with clear error
- Fix the schema/backend to return proper data

---

## Next Steps

Would you like me to:
1. **Check your actual API response** to see if SourceDocument exists?
2. **Simplify the code** to ONE strategy using SourceDocument?
3. **Fix the schema** if SourceDocument isn't being returned?

This is a much better approach than the complex strategy waterfall! 🎯
