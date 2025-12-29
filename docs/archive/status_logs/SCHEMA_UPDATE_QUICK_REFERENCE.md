# ⚡ Quick Reference: Schema Updates

## 📋 What Changed?

Updated `simple_enhanced_schema.json` → `simple_enhanced_schema_update.json`

## 🎯 Key Additions

### Every Inconsistency Item Now Has:

```json
{
  "Evidence": "Why inconsistent",
  "DocumentAField": "Invoice field name",
  "DocumentAValue": "Invoice value",
  "DocumentASourceDocument": "invoice_2024.pdf",     // ← NEW: Auto-extracted
  "DocumentAPageNumber": 1,                          // ← NEW: Auto-extracted
  "DocumentBField": "Contract field name",
  "DocumentBValue": "Contract value",
  "DocumentBSourceDocument": "contract_signed.pdf",  // ← NEW: Auto-extracted
  "DocumentBPageNumber": 3,                          // ← NEW: Auto-extracted
  "Severity": "High"                                 // ← NEW: Risk level
}
```

## ✨ Benefits

| Feature | Before | After |
|---------|--------|-------|
| **Source Tracking** | ❌ No | ✅ Yes (auto-extracted) |
| **Page References** | ❌ No | ✅ Yes (1-based index) |
| **File Comparison** | ❌ Manual | ✅ Automatic |
| **Severity Levels** | ❌ No | ✅ Critical/High/Medium/Low |
| **Field Pattern** | ❌ Mixed | ✅ Standardized (DocumentA/B) |

## 🚀 How to Use

1. **Upload** `simple_enhanced_schema_update.json` to Azure
2. **Run Analysis** with invoice + contract documents
3. **View Results** with automatic filename and page tracking
4. **Click Compare** buttons to open side-by-side view

## 📊 Inconsistency Categories

All use the same DocumentA/DocumentB pattern:

1. ⚠️ **PaymentTermsInconsistencies** - Payment method/terms/dates
2. 📦 **ItemInconsistencies** - Products/services/specifications
3. 📍 **BillingLogisticsInconsistencies** - Addresses/delivery/remit-to
4. 📅 **PaymentScheduleInconsistencies** - Milestones/installments/timelines
5. 💰 **TaxOrDiscountInconsistencies** - Taxes/discounts/adjustments
6. 🔄 **CrossDocumentInconsistencies** - General/uncategorized

## 🎨 UI Features Enabled

### Before
```
│ Field       │ Evidence                    │
│ Payment     │ Terms differ...             │
```

### After (with horizontal scroll!)
```
← Scroll horizontally to view all columns →
│ Evidence │ Invoice │ invoice.pdf │ Page │ Contract │ [Compare] │
│ Terms... │ Due now │            │  1   │ 30 days  │           │
```

## ✅ Quick Validation

Check these in your results:

- [ ] `DocumentASourceDocument` = actual filename uploaded
- [ ] `DocumentBSourceDocument` = actual filename uploaded  
- [ ] `DocumentAPageNumber` = valid page number (≥1)
- [ ] `DocumentBPageNumber` = valid page number (≥1)
- [ ] `Severity` = Critical/High/Medium/Low
- [ ] Compare buttons work in UI

## 🔧 Technical Notes

- **DocumentA** = Invoice (first document)
- **DocumentB** = Contract (second document)
- Page numbers are **1-based** (first page = 1)
- Filenames must **exactly match** uploaded names
- API extracts these **automatically** - no manual config needed!

## 📚 Full Documentation

See `SCHEMA_UPDATE_DOCUMENTATION.md` for complete details.

---

**Updated:** October 13, 2025  
**Status:** ✅ Ready for production use
