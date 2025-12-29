# Quick Reference: Generic Document Comparison Fields

## Required Schema Fields for Document Comparison

### ✅ New Generic Fields (Use These)

```json
{
  "CrossDocumentInconsistencies": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        // REQUIRED for document comparison to work
        "DocumentAValue": {
          "type": "string",
          "description": "Actual value/text from first document"
        },
        "DocumentBValue": {
          "type": "string",
          "description": "Actual value/text from second document"
        },
        "DocumentASourceDocument": {
          "type": "string",
          "description": "EXACT filename of first document (e.g., 'invoice_123.pdf')"
        },
        "DocumentBSourceDocument": {
          "type": "string",
          "description": "EXACT filename of second document (e.g., 'contract_456.pdf')"
        },
        
        // OPTIONAL but highly recommended
        "DocumentAPageNumber": {
          "type": "number",
          "description": "Page number in first document (1-based)"
        },
        "DocumentBPageNumber": {
          "type": "number",
          "description": "Page number in second document (1-based)"
        },
        "DocumentAField": {
          "type": "string",
          "description": "Field name/context in first document"
        },
        "DocumentBField": {
          "type": "string",
          "description": "Field name/context in second document"
        },
        
        // Standard inconsistency fields
        "InconsistencyType": {
          "type": "string"
        },
        "Evidence": {
          "type": "string"
        },
        "Severity": {
          "type": "string",
          "description": "Critical|High|Medium|Low"
        }
      }
    }
  }
}
```

### ❌ Old Invoice/Contract Fields (Don't Use)

```json
// DEPRECATED - These will NOT work with document comparison
{
  "InvoiceValue": "...",           // ❌ Use DocumentAValue instead
  "ContractValue": "...",          // ❌ Use DocumentBValue instead
  "InvoiceSourceDocument": "...",  // ❌ Use DocumentASourceDocument instead
  "ContractSourceDocument": "...", // ❌ Use DocumentBSourceDocument instead
  "InvoicePageNumber": 1,          // ❌ Use DocumentAPageNumber instead
  "ContractPageNumber": 2          // ❌ Use DocumentBPageNumber instead
}
```

---

## Document Matching Strategies (Priority Order)

### Strategy 1: Direct Filename Match (100% confidence) ⭐
**When used:** Azure provides exact filenames  
**Fields required:** `DocumentASourceDocument` + `DocumentBSourceDocument`  
**How it works:** Direct lookup by filename in uploaded files list

```typescript
// Example:
DocumentASourceDocument: "invoice_1256003.pdf"
DocumentBSourceDocument: "purchase_contract.pdf"
// System finds exact files by name - instant and 100% accurate
```

### Strategy 2: Content Value Search (95% confidence) ⭐
**When used:** Azure provides document values  
**Fields required:** `DocumentAValue` + `DocumentBValue`  
**How it works:** Searches Azure's extracted markdown content for values

```typescript
// Example:
DocumentAValue: "$29,900"
DocumentBValue: "$39,900"
// System searches each document's content for these values
// Matches the document containing each value
```

### Strategy 3: Document Type Index (80% confidence)
**When used:** `DocumentTypes` array available  
**Fields required:** `DocumentTypes` array from analysis  
**How it works:** Uses document position/index from DocumentTypes

```typescript
// Example:
DocumentTypes: [
  { DocumentType: "Invoice", DocumentTitle: "..." },
  { DocumentType: "Contract", DocumentTitle: "..." }
]
// System uses first and second documents by index
```

### ❌ No More Guessing Fallbacks
**Removed strategies:**
- Filename pattern matching (looked for "invoice"/"contract" in names)
- Evidence text search (extracted phrases and scored)
- "Use first 2 files" fallback (arbitrary selection)

**New behavior:** If reliable data is missing, system fails explicitly with error message.

---

## Error Messages & Solutions

### Error: "Azure analysis did not provide required document values"

**Cause:** Schema is missing required fields  
**Solution:** Add these fields to your schema:
- `DocumentAValue` + `DocumentBValue`, OR
- `DocumentASourceDocument` + `DocumentBSourceDocument`

### Error: "Azure provided filenames but files not found in uploaded list"

**Cause:** Filenames in schema don't match uploaded filenames exactly  
**Solution:** Ensure AI uses EXACT uploaded filenames (case-sensitive, including extension)

### Error: "Cannot find document containing the identified value"

**Cause:** DocumentA/BValue doesn't appear in any document's content  
**Solution:** Verify Azure extracted correct values and document content is complete

---

## Prompt Engineering Tips

### ✅ Good Prompt
```
For each inconsistency, extract:
1. DocumentAValue: The exact text/value from the first document
2. DocumentBValue: The exact text/value from the second document
3. DocumentASourceDocument: The EXACT filename (use actual uploaded filename)
4. DocumentBSourceDocument: The EXACT filename (use actual uploaded filename)
5. DocumentAPageNumber: Page number in first document
6. DocumentBPageNumber: Page number in second document

CRITICAL: For DocumentASourceDocument and DocumentBSourceDocument, 
use the EXACT uploaded filenames including extensions (e.g., "invoice_123.pdf").
```

### ❌ Bad Prompt
```
Find inconsistencies between invoice and contract
// No specific field instructions
// AI might not include required fields
// Won't work with non-invoice/contract documents
```

---

## Example: Invoice vs Contract

```json
{
  "CrossDocumentInconsistencies": [
    {
      "InconsistencyType": "Payment Terms",
      "DocumentAValue": "Net 30",
      "DocumentBValue": "Net 60",
      "DocumentASourceDocument": "invoice_1256003.pdf",
      "DocumentBSourceDocument": "purchase_contract.pdf",
      "DocumentAPageNumber": 1,
      "DocumentBPageNumber": 2,
      "DocumentAField": "Payment Terms",
      "DocumentBField": "Payment Terms",
      "Evidence": "Invoice specifies Net 30 but contract states Net 60",
      "Severity": "High"
    }
  ]
}
```

## Example: Purchase Order vs Receipt

```json
{
  "CrossDocumentInconsistencies": [
    {
      "InconsistencyType": "Item Quantity",
      "DocumentAValue": "50 units",
      "DocumentBValue": "45 units",
      "DocumentASourceDocument": "PO_2024_789.pdf",
      "DocumentBSourceDocument": "receipt_2024_790.pdf",
      "DocumentAPageNumber": 1,
      "DocumentBPageNumber": 1,
      "DocumentAField": "Quantity Ordered",
      "DocumentBField": "Quantity Received",
      "Evidence": "Purchase order shows 50 units but receipt confirms only 45 units delivered",
      "Severity": "Critical"
    }
  ]
}
```

---

## Testing Checklist

Before deploying a new schema, verify:

- [ ] Schema includes `DocumentAValue` + `DocumentBValue` fields
- [ ] Schema includes `DocumentASourceDocument` + `DocumentBSourceDocument` fields
- [ ] Schema includes page number fields (optional but recommended)
- [ ] Prompt instructs AI to use EXACT uploaded filenames
- [ ] Test with 2+ documents of same type (e.g., 2 invoices)
- [ ] Test with different document types (not just invoice/contract)
- [ ] Verify document comparison button opens correct files
- [ ] Verify no console errors about missing fields

---

## Code References

- **Schema Template:** `GENERIC_SCHEMA_TEMPLATE.json`
- **Pre-computation:** `documentMatchingEnhancer.ts`
- **Fallback Logic:** `PredictionTab.tsx` → `identifyComparisonDocuments()`
- **Full Documentation:** `DOCUMENT_COMPARISON_REFACTORING_COMPLETE.md`
