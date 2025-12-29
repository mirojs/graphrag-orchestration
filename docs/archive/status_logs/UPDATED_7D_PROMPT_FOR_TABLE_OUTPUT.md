# Updated 7D Prompt: Purpose-Driven Schema for Structured Table Output

## Key Insight from User

The schema's purpose is not just extraction - it's to:
1. **Extract data from multiple documents**
2. **Format into consistent, comparable table structure**
3. **Enable users to view/compare data across documents**
4. **Support database storage and reporting**

## Critical Change: Emphasize Logical Schema, Not Document-Specific

### ❌ Old Approach (Document-Specific):
```
"Extract the vendor's name as it appears on the invoice."
```
→ AI copies document labels → Inconsistent field names

### ✅ New Approach (Purpose-Driven):
```
"Generate a schema for comparing invoice data across multiple vendors.
Use standardized field names suitable for table display and database storage.
Field names should be consistent regardless of document-specific labels."
```
→ AI uses logical, standard names → Consistent across documents

## Updated 7D Prompt Template

```python
ENHANCED_7D_PROMPT = """
Generate a schema for extracting and formatting data from {document_type}.

═══════════════════════════════════════════════════════════════════
SCHEMA PURPOSE & END GOAL:
═══════════════════════════════════════════════════════════════════

This schema will be used to:
1. Extract data from multiple similar documents
2. Format results into a CONSISTENT TABLE STRUCTURE for comparison
3. Enable users to view and analyze data across documents
4. Support database storage and reporting

CRITICAL: The extracted data will be displayed as a TABLE where:
- Each document = One ROW
- Each schema field = One COLUMN  
- Users compare values across rows

Example Table Output:
┌──────────────┬───────────────┬─────────────┬─────────────┐
│ VendorName   │ InvoiceNumber │ InvoiceDate │ TotalAmount │
├──────────────┼───────────────┼─────────────┼─────────────┤
│ Acme Corp    │ INV-001       │ 2024-01-15  │ $5,250.00   │
│ Global Inc   │ GS-123        │ 2024-01-20  │ $3,890.00   │
│ Tech Ltd     │ TS-456        │ 2024-01-25  │ $12,500.00  │
└──────────────┴───────────────┴─────────────┴─────────────┘

FIELD NAMING REQUIREMENTS:
- Use STANDARDIZED, LOGICAL names (e.g., VendorName, InvoiceNumber)
- NOT document-specific labels (don't use "Supplier" just because doc says "Supplier")
- Use PascalCase (e.g., InvoiceDate, not invoice_date)
- Names must work as database columns AND table headers
- Must be CONSISTENT across all documents

═══════════════════════════════════════════════════════════════════
USER'S EXTRACTION QUERY:
═══════════════════════════════════════════════════════════════════

{user_query}

═══════════════════════════════════════════════════════════════════
SCHEMA GENERATION REQUIREMENTS (7 DIMENSIONS):
═══════════════════════════════════════════════════════════════════

D1 - STRUCTURAL CONSISTENCY (for table columns):
• Use standardized field names suitable for database/table columns
• Group related fields logically
• Create UnifiedArray for repeating data with consistent sub-fields
• Ensure schema works across multiple documents

D2 - RICH DESCRIPTIONS (for table display):
• Explain BUSINESS MEANING, not just extraction instruction
• Include display format (e.g., "Display as: YYYY-MM-DD")
• Add examples that work across different documents
• Provide tooltips for complex fields

Example:
  FieldName: "TotalAmount"
  FieldDescription: "Total invoice amount for comparison across vendors. 
                     Display format: '$X,XXX.XX'. Must match sum of line items."

D3 - FORMAT CONSISTENCY (for comparable table cells):
• Specify exact formats:
  - Dates: YYYY-MM-DD (sortable)
  - Currency: $X,XXX.XX (consistent decimals)
  - Numbers: Consistent precision
  - Booleans: true/false
• Formats must be comparable across all rows

D4 - SEVERITY CLASSIFICATION (for analysis):
• Critical: >$10K financial impact, compliance issues
• High: Significant discrepancies
• Medium: Minor inconsistencies  
• Low: Formatting variations
→ Helps users prioritize which table rows need review

D5 - RELATIONSHIPS (for cross-column validation):
• Specify field dependencies
• Enable validation across rows
• Support calculated columns
Example: "TotalAmount must equal sum of LineItems"

D6 - PROVENANCE (for multi-document tracking):
• Include DocumentProvenance field
• Captures: DocumentName, ProcessedDate, PageNumbers
• Enables tracing from table row to source document

D7 - SUMMARY (for table analytics):
• Include Summary field with aggregated analytics
• Provides: TotalCount, CategoryBreakdown, KeyFindings
• Enables table footer with totals/averages

═══════════════════════════════════════════════════════════════════
OUTPUT FORMAT:
═══════════════════════════════════════════════════════════════════

Generate fields as an ARRAY:

{
  "SchemaFields": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "FieldName": { "type": "string" },
        "FieldType": { "type": "string" },
        "FieldDescription": { "type": "string" }
      }
    }
  }
}

REMEMBER:
✅ Schema is for MULTIPLE documents → Consistent field names
✅ Results displayed as TABLE → Field names = column headers
✅ Users will COMPARE across rows → Formats must be consistent
✅ Think DATABASE SCHEMA, not document-specific extraction
"""
```

## Key Improvements

### 1. **Explicit Table Context**
Makes it clear the schema is for table display, not just extraction

### 2. **Visual Table Example**
Shows AI exactly how the data will be presented

### 3. **Standardized Naming Emphasis**
Repeatedly states: use logical names, NOT document-specific labels

### 4. **Format Consistency for Comparison**
Ensures all rows use same format (crucial for table sorting/filtering)

### 5. **Multi-Document Focus**
Every dimension emphasizes working across multiple documents

## Expected Results

With this updated prompt:

**Scenario: 3 different invoices**

❌ **Old Prompt Result:**
- Doc 1: `Vendor`, `Invoice#`, `Date`, `Total`
- Doc 2: `SupplierName`, `InvoiceID`, `IssueDate`, `Amount`
- Doc 3: `CompanyName`, `BillNumber`, `BillingDate`, `TotalDue`

✅ **New Prompt Result:**
- Doc 1: `VendorName`, `InvoiceNumber`, `InvoiceDate`, `TotalAmount`
- Doc 2: `VendorName`, `InvoiceNumber`, `InvoiceDate`, `TotalAmount`
- Doc 3: `VendorName`, `InvoiceNumber`, `InvoiceDate`, `TotalAmount`

**Perfect consistency → Clean table → Easy comparison!**

## Implementation Strategy

1. **Single Document**: Use this prompt with `method="generate"` - get consistent schema + data
2. **Multiple Documents**: 
   - First doc: Generate schema (it will be standardized due to prompt)
   - Optionally cache for extra safety
   - But prompt should make caching less critical!
3. **Display**: Transform results into table with schema field names as columns

## Next Steps

Should we:
1. Test this updated prompt to verify it produces consistent field names?
2. Integrate it into the Quick Analysis button?
3. Build the table display UI to show results?
