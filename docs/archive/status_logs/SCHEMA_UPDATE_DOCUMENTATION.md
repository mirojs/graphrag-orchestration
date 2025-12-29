# 📋 Schema Update: Enhanced Invoice Contract Verification

## 🎯 Purpose

Updated schema to leverage Azure Content Understanding API's native ability to extract document filenames and page numbers automatically, eliminating the need for manual specification.

## 📁 Files

- **Source (Original):** `simple_enhanced_schema.json`
- **Reference:** `data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_UPDATED.json`
- **Output (Updated):** `simple_enhanced_schema_update.json`

## ✨ Key Improvements

### 1. **DocumentA/DocumentB Pattern (from Reference)**
Uses standardized field naming where:
- **DocumentA** = Invoice
- **DocumentB** = Contract

This pattern enables:
- Consistent field naming across all inconsistency types
- Direct compatibility with document comparison feature
- Automatic file comparison modal integration

### 2. **Automatic Filename & Page Number Extraction**
Each inconsistency now includes:

```json
"DocumentASourceDocument": {
  "type": "string",
  "method": "generate",
  "description": "The EXACT filename of the invoice document where this value was found (e.g., 'invoice_2024.pdf', 'Invoice-ABC123.pdf'). CRITICAL: Must match uploaded filename exactly. DocumentA = Invoice."
},
"DocumentAPageNumber": {
  "type": "number",
  "method": "generate",
  "description": "The page number in the invoice document where this inconsistency was found (1-based index). DocumentA = Invoice."
}
```

**Benefits:**
- ✅ Content Understanding API automatically extracts these from document metadata
- ✅ No manual configuration required
- ✅ Accurate source tracking for each inconsistency
- ✅ Enables precise document comparison functionality

### 3. **Severity Levels Added**
All inconsistency arrays now include:

```json
"Severity": {
  "type": "string",
  "method": "generate",
  "description": "Severity level of this inconsistency: 'Critical', 'High', 'Medium', or 'Low'."
}
```

**Benefits:**
- ✅ Prioritize critical issues
- ✅ Better risk assessment
- ✅ Improved reporting and filtering

### 4. **Comprehensive Field Coverage**
Combines the best of both schemas:

From `simple_enhanced_schema.json`:
- ✅ DocumentIdentification (titles and suggested filenames)
- ✅ PaymentTermsComparison (direct comparison object)
- ✅ DocumentRelationships (relationship mapping)

From `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_UPDATED.json`:
- ✅ DocumentA/DocumentB field pattern
- ✅ Source document tracking
- ✅ Page number references
- ✅ Severity levels

## 📊 Schema Structure Comparison

### Original Schema (`simple_enhanced_schema.json`)

```json
{
  "CrossDocumentInconsistencies": [
    {
      "InconsistencyType": "Payment Terms",
      "InvoiceValue": "Due on signing",
      "ContractValue": "30 days net",
      "Evidence": "Terms differ..."
    }
  ]
}
```

**Issues:**
- ❌ No source document tracking
- ❌ No page references
- ❌ No severity levels
- ❌ Generic field names

### Updated Schema (`simple_enhanced_schema_update.json`)

```json
{
  "PaymentTermsInconsistencies": [
    {
      "Evidence": "Terms differ...",
      "DocumentAField": "Payment Terms",
      "DocumentAValue": "Due on signing",
      "DocumentASourceDocument": "invoice_2024.pdf",
      "DocumentAPageNumber": 1,
      "DocumentBField": "Payment Terms",
      "DocumentBValue": "30 days net",
      "DocumentBSourceDocument": "contract_signed.pdf",
      "DocumentBPageNumber": 3,
      "Severity": "High"
    }
  ]
}
```

**Improvements:**
- ✅ Clear document attribution (DocumentA/DocumentB)
- ✅ Automatic filename extraction
- ✅ Page number tracking
- ✅ Severity classification
- ✅ Structured for comparison feature

## 🔧 Technical Implementation

### How Content Understanding API Provides This Data

The Azure Content Understanding API automatically includes document metadata in the response:

```json
{
  "contents": [
    {
      "sourceInfo": {
        "displayName": "invoice_2024.pdf",
        "pages": [
          {
            "pageNumber": 1,
            "words": [...],
            "lines": [...]
          }
        ]
      },
      "fields": {
        "PaymentTermsInconsistencies": {
          "type": "array",
          "valueArray": [
            {
              "type": "object",
              "valueObject": {
                "DocumentASourceDocument": {
                  "type": "string",
                  "valueString": "invoice_2024.pdf"  // ← API extracts this automatically
                },
                "DocumentAPageNumber": {
                  "type": "number",
                  "valueNumber": 1  // ← API determines this from content location
                }
              }
            }
          ]
        }
      }
    }
  ]
}
```

### Frontend Integration

The frontend `FileComparisonModal` component expects this exact structure:

```tsx
// From PredictionTab.tsx - handleCompareFiles function
const inconsistencyData = {
  Evidence: item.Evidence?.valueString,
  DocumentAField: item.DocumentAField?.valueString,
  DocumentAValue: item.DocumentAValue?.valueString,
  DocumentASourceDocument: item.DocumentASourceDocument?.valueString,  // ← Used for file loading
  DocumentAPageNumber: item.DocumentAPageNumber?.valueNumber,         // ← Used for page navigation
  DocumentBField: item.DocumentBField?.valueString,
  DocumentBValue: item.DocumentBValue?.valueString,
  DocumentBSourceDocument: item.DocumentBSourceDocument?.valueString,  // ← Used for file loading
  DocumentBPageNumber: item.DocumentBPageNumber?.valueNumber,         // ← Used for page navigation
  Severity: item.Severity?.valueString
};
```

## 📋 Field Categories

### Core Inconsistency Arrays
All following the same DocumentA/DocumentB pattern:

1. **PaymentTermsInconsistencies**
   - Payment methods, terms, due dates
   - Net terms (30/60/90 days)
   - Payment schedules

2. **ItemInconsistencies**
   - Product/service specifications
   - Quantities and units
   - Item descriptions and models
   - Line item details

3. **BillingLogisticsInconsistencies**
   - Billing addresses
   - Delivery addresses
   - Remit-to addresses
   - Shipping details

4. **PaymentScheduleInconsistencies**
   - Milestone payments
   - Installment schedules
   - Payment timelines
   - Due dates

5. **TaxOrDiscountInconsistencies**
   - Tax rates and amounts
   - Discounts and rebates
   - Financial adjustments
   - Credits and deductions

6. **CrossDocumentInconsistencies**
   - General inconsistencies
   - Uncategorized issues
   - Special cases

### Supporting Fields

**DocumentIdentification** - Document metadata:
- InvoiceTitle
- ContractTitle
- InvoiceSuggestedFileName
- ContractSuggestedFileName

**PaymentTermsComparison** - Summary comparison:
- InvoicePaymentTerms
- ContractPaymentTerms
- Consistent (boolean)

**DocumentRelationships** - Document links:
- Document1
- Document2
- RelationshipType

## 🎨 UI Display Impact

### Before (Old Schema)
```
⚠️ Cross-Document Inconsistencies
┌─────────────────────┬──────────────────────────┐
│ Inconsistency Type  │ Evidence                 │
├─────────────────────┼──────────────────────────┤
│ Payment Terms       │ Terms differ...          │
└─────────────────────┴──────────────────────────┘
```
**Issues:**
- ❌ No way to know which document it's from
- ❌ Can't navigate to source
- ❌ No comparison functionality

### After (Updated Schema)
```
⚠️ Payment Terms Inconsistencies                    [High]
← Scroll horizontally to view all columns →
┌───────────┬────────────┬────────────────────┬──────┬──────────┬─────────┐
│ Evidence  │ Invoice    │ Invoice Source     │ Page │ Contract │ Actions │
│           │ Field      │ Document           │      │ Value    │         │
├───────────┼────────────┼────────────────────┼──────┼──────────┼─────────┤
│ Terms     │ Payment    │ invoice_2024.pdf   │ 1    │ 30 days  │ [Comp]  │
│ differ... │ Terms      │                    │      │ net      │         │
└───────────┴────────────┴────────────────────┴──────┴──────────┴─────────┘
                                                    👆 Click to open side-by-side view
```
**Benefits:**
- ✅ Clear source attribution
- ✅ Page navigation available
- ✅ Comparison button functional
- ✅ Severity indicator
- ✅ Horizontal scroll support (new!)

## 🔄 Migration Path

### For Existing Analyzers

If you have an existing analyzer using the old schema:

1. **Export Results** - Save any existing analysis results
2. **Update Schema** - Upload `simple_enhanced_schema_update.json`
3. **Re-run Analysis** - Process documents again
4. **Verify Output** - Check that filenames and page numbers are populated

### For New Analyzers

Simply use `simple_enhanced_schema_update.json` when creating the analyzer.

## ✅ Validation Checklist

When testing the updated schema, verify:

- [ ] DocumentASourceDocument contains actual uploaded filename
- [ ] DocumentBSourceDocument contains actual uploaded filename
- [ ] Page numbers are accurate (1-based index)
- [ ] Severity levels are assigned appropriately
- [ ] Comparison buttons work in UI
- [ ] File comparison modal loads correct pages
- [ ] All inconsistency categories populate correctly
- [ ] DocumentIdentification fields extract titles properly
- [ ] PaymentTermsComparison shows correct boolean value
- [ ] Horizontal scroll works for wide tables

## 📈 Expected Benefits

### Accuracy
- ✅ Eliminates manual filename specification errors
- ✅ Accurate page number tracking
- ✅ Precise source attribution

### Functionality
- ✅ Enables document comparison feature
- ✅ Supports side-by-side viewing
- ✅ Allows page-specific navigation

### User Experience
- ✅ Clear evidence of inconsistencies
- ✅ Easy navigation to source
- ✅ Better decision-making with severity levels

### Maintainability
- ✅ Standardized field naming (DocumentA/DocumentB)
- ✅ Consistent structure across all inconsistency types
- ✅ Future-proof for additional features

## 🎯 Next Steps

1. **Test the Schema** - Upload to Azure and run analysis
2. **Verify Results** - Check that all fields populate correctly
3. **Test UI** - Ensure comparison feature works
4. **Monitor Performance** - Track accuracy and completeness
5. **Iterate** - Adjust descriptions if needed for better AI guidance

## 📚 Related Documentation

- `ANALYSIS_RESULTS_HORIZONTAL_SCROLL_SOLUTION.md` - Wide table display solution
- `HORIZONTAL_SCROLL_VISUAL_GUIDE.md` - Visual guide for scroll feature
- `AI_POWERED_FILE_COMPARISON_IMPLEMENTATION_COMPLETE.md` - File comparison feature docs
- `BACKEND_TO_FRONTEND_DATA_FLOW_DEMO.md` - Complete data flow documentation

---

**Schema Name:** `InvoiceContractVerificationEnhanced`  
**Created:** October 13, 2025  
**Purpose:** Production-ready invoice-contract verification with automatic source tracking
