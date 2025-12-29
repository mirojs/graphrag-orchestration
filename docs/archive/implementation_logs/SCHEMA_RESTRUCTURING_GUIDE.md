# Schema Restructuring: From Numbered Suffixes to Structured Arrays

## Problem Statement

**Current Issue:** When comparing multiple document pairs (e.g., Invoice1 vs Contract1, Invoice2 vs Contract2), the old schema outputs flat fields with numbered suffixes:

```json
{
  "Evidence": "Payment terms differ",
  "DocumentAField1": "Payment Terms",
  "DocumentAValue1": "Net 30",
  "DocumentASourceDocument1": "invoice1.pdf",
  "DocumentAPageNumber1": 1,
  "DocumentBField1": "Payment Terms",
  "DocumentBValue1": "Net 60",
  "DocumentBSourceDocument1": "contract1.pdf",
  "DocumentBPageNumber1": 2,
  "DocumentAField2": "Payment Terms",
  "DocumentAValue2": "Net 45",
  "DocumentASourceDocument2": "invoice2.pdf",
  "DocumentAPageNumber2": 1,
  "DocumentBField2": "Payment Terms",
  "DocumentBValue2": "Net 90",
  "DocumentBSourceDocument2": "contract2.pdf",
  "DocumentBPageNumber2": 3
}
```

**Problems with this approach:**
- ❌ Frontend needs complex regex parsing to detect numbered suffixes
- ❌ Ambiguous edge cases (is `Version2` a party or a version field?)
- ❌ Hard to maintain and extend
- ❌ Doesn't scale to 3+ dimensional data

---

## Solution: Structured Arrays

**New Schema Structure:** Nest document comparisons in a `Documents` array:

```json
{
  "Evidence": "Payment terms differ",
  "InconsistencyType": "Payment Terms Mismatch",
  "Severity": "High",
  "Documents": [
    {
      "DocumentAField": "Payment Terms",
      "DocumentAValue": "Net 30",
      "DocumentASourceDocument": "invoice1.pdf",
      "DocumentAPageNumber": 1,
      "DocumentBField": "Payment Terms",
      "DocumentBValue": "Net 60",
      "DocumentBSourceDocument": "contract1.pdf",
      "DocumentBPageNumber": 2
    },
    {
      "DocumentAField": "Payment Terms",
      "DocumentAValue": "Net 45",
      "DocumentASourceDocument": "invoice2.pdf",
      "DocumentAPageNumber": 1,
      "DocumentBField": "Payment Terms",
      "DocumentBValue": "Net 90",
      "DocumentBSourceDocument": "contract2.pdf",
      "DocumentBPageNumber": 3
    }
  ]
}
```

**Advantages:**
- ✅ **Semantic correctness** - AI understands document pairs better than regex parsing
- ✅ **Simpler frontend** - just map over `Documents` array
- ✅ **More reliable** - no suffix parsing edge cases
- ✅ **Extensible** - easy to add document metadata later
- ✅ **Better for AI** - LLMs excel at structuring data

---

## Implementation Plan

### Step 1: Update Schema ✅ DONE

**File:** `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_WITH_PARTIES.json`

**Key Changes:**
- Added `InconsistencyType` field for better categorization
- Moved all `DocumentA*` and `DocumentB*` fields into nested `Documents` array
- Added clear instructions in descriptions to create ONE item per document pair
- Kept `Evidence` and `Severity` at the top level (shared across all document pairs)

### Step 2: Update Frontend Rendering

**File:** `DataRenderer.tsx` (or create new `DataRendererWithDocuments.tsx`)

**Logic:**
```typescript
// Detect if field contains Documents array structure
if (item.valueObject?.Documents?.type === 'array') {
  // This is a multi-document inconsistency
  // Render a table where each Documents array item is a row
  return <DocumentsTable 
    inconsistency={item}
    documents={item.valueObject.Documents.valueArray}
    onCompare={onCompare}
  />;
}
```

### Step 3: Create Simple Documents Table Component

**New Component:** `DocumentsComparisonTable.tsx`

**Features:**
- Maps over `Documents` array
- Displays each document pair as a row
- Shows shared `Evidence` and `Severity` at the top
- Single Compare button per row (no complex grouping logic needed)

---

## Migration Strategy

### Option A: Hard Cutover
- Deploy new schema
- Update all existing extractions to use new format
- Remove old detection logic

### Option B: Dual Support (Recommended)
- Frontend detects both formats:
  ```typescript
  // Check for new structured format
  if (item.valueObject?.Documents) {
    return <DocumentsTable />;
  }
  // Fall back to old numbered suffix detection
  else if (hasNumberedSuffixes(item)) {
    return <DataTableWithPartyGrouping />;
  }
  // Default table
  else {
    return <DataTable />;
  }
  ```

### Option C: Gradual Migration
- Phase 1: Deploy frontend with dual support
- Phase 2: Update backend to use new schema
- Phase 3: Re-extract old documents (optional)
- Phase 4: Remove old detection logic after verification

---

## Example Output Comparison

### Old Schema (Flat with Suffixes)
```json
{
  "PaymentTermsInconsistencies": [
    {
      "Evidence": "Payment terms differ",
      "DocumentAField1": "Payment Terms",
      "DocumentAValue1": "Net 30",
      "DocumentASourceDocument1": "invoice1.pdf",
      "DocumentAPageNumber1": 1,
      "DocumentBField1": "Payment Terms",
      "DocumentBValue1": "Net 60",
      "DocumentBSourceDocument1": "contract1.pdf",
      "DocumentBPageNumber1": 2,
      "DocumentAField2": "Payment Terms",
      "DocumentAValue2": "Net 45",
      "DocumentASourceDocument2": "invoice2.pdf",
      "DocumentAPageNumber2": 1,
      "Severity": "High"
    }
  ]
}
```

### New Schema (Structured Arrays)
```json
{
  "PaymentTermsInconsistencies": [
    {
      "Evidence": "Payment terms differ across invoice-contract pairs",
      "InconsistencyType": "Payment Terms Mismatch",
      "Severity": "High",
      "Documents": [
        {
          "DocumentAField": "Payment Terms",
          "DocumentAValue": "Net 30",
          "DocumentASourceDocument": "invoice1.pdf",
          "DocumentAPageNumber": 1,
          "DocumentBField": "Payment Terms",
          "DocumentBValue": "Net 60",
          "DocumentBSourceDocument": "contract1.pdf",
          "DocumentBPageNumber": 2
        },
        {
          "DocumentAField": "Payment Terms",
          "DocumentAValue": "Net 45",
          "DocumentASourceDocument": "invoice2.pdf",
          "DocumentAPageNumber": 1,
          "DocumentBField": "Payment Terms",
          "DocumentBValue": "Net 90",
          "DocumentBSourceDocument": "contract2.pdf",
          "DocumentBPageNumber": 3
        }
      ]
    }
  ]
}
```

---

## Frontend Rendering Logic

### Simplified Detection
```typescript
const hasDocumentsArray = (item: any): boolean => {
  const obj = item?.valueObject || item;
  return obj?.Documents?.type === 'array' && 
         Array.isArray(obj.Documents.valueArray);
};
```

### Simplified Rendering
```typescript
if (hasDocumentsArray(item)) {
  const documents = item.valueObject.Documents.valueArray;
  
  return (
    <div>
      {/* Show shared evidence/severity */}
      <div className="inconsistency-header">
        <strong>{extractDisplayValue(item.valueObject.InconsistencyType)}</strong>
        <span>{extractDisplayValue(item.valueObject.Severity)}</span>
      </div>
      <div className="evidence">
        {extractDisplayValue(item.valueObject.Evidence)}
      </div>
      
      {/* Render documents table */}
      <table>
        <thead>
          <tr>
            <th>Invoice Field</th>
            <th>Invoice Value</th>
            <th>Invoice Source</th>
            <th>Contract Field</th>
            <th>Contract Value</th>
            <th>Contract Source</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((doc, index) => (
            <tr key={index}>
              <td>{extractDisplayValue(doc.valueObject.DocumentAField)}</td>
              <td>{extractDisplayValue(doc.valueObject.DocumentAValue)}</td>
              <td>
                {extractDisplayValue(doc.valueObject.DocumentASourceDocument)}
                (p. {extractDisplayValue(doc.valueObject.DocumentAPageNumber)})
              </td>
              <td>{extractDisplayValue(doc.valueObject.DocumentBField)}</td>
              <td>{extractDisplayValue(doc.valueObject.DocumentBValue)}</td>
              <td>
                {extractDisplayValue(doc.valueObject.DocumentBSourceDocument)}
                (p. {extractDisplayValue(doc.valueObject.DocumentBPageNumber)})
              </td>
              <td>
                <ComparisonButton 
                  fieldName={`Document Pair ${index + 1}`}
                  item={doc}
                  onCompare={onCompare}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

## Benefits Summary

| Aspect | Old Approach (Numbered Suffixes) | New Approach (Structured Arrays) |
|--------|----------------------------------|----------------------------------|
| **Schema Clarity** | ❌ Flat fields with numbers | ✅ Nested, semantic structure |
| **AI Understanding** | ❌ AI generates flat keys | ✅ AI structures documents naturally |
| **Frontend Complexity** | ❌ Complex regex detection | ✅ Simple array mapping |
| **Maintenance** | ❌ Fragile regex patterns | ✅ Type-safe structure |
| **Extensibility** | ❌ Hard to add metadata | ✅ Easy to extend Documents array |
| **Edge Cases** | ❌ Many ambiguities | ✅ Clear semantics |
| **Performance** | ❌ Scanning/parsing overhead | ✅ Direct array access |

---

## Next Steps

1. **Test new schema** with AI extraction on sample documents
2. **Verify AI output** follows the Documents array structure correctly
3. **Update `DataRenderer.tsx`** to detect and render Documents arrays
4. **Create `DocumentsComparisonTable.tsx`** component
5. **Test with real data** to ensure proper rendering
6. **Consider migration strategy** (dual support vs. hard cutover)
7. **Update documentation** for schema usage

---

## Files to Update

- ✅ **Schema:** `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_WITH_PARTIES.json` (DONE)
- ⏳ **Renderer:** `DataRenderer.tsx` (add Documents array detection)
- ⏳ **New Component:** `DocumentsComparisonTable.tsx` (create)
- ⏳ **Type Definitions:** Add `DocumentComparison` interface
- ⏳ **Tests:** Add unit tests for new rendering logic

---

## Questions to Answer

1. Should we support both old and new formats during transition?
2. Do we need to re-extract existing documents with the new schema?
3. Should `Documents` array support more than 2 documents (DocumentA, DocumentB, DocumentC)?
4. Do we want to add document type metadata (Invoice, Contract, PO, etc.)?
5. Should we add a `ComparisonId` or `DocumentPairId` for tracking?
