# Schema Fields Explanation: Where Do InvoiceValue and ContractValue Come From?

## ✅ Answer: **WE Define Them in the Schema!**

Azure Content Understanding API is **schema-driven**. It ONLY extracts fields that we explicitly define.

---

## The Complete Flow:

### Step 1: We Define What We Want (Schema)
```json
{
  "PaymentTermsInconsistencies": {
    "properties": {
      "Evidence": { "type": "string" },
      "InvoiceField": { "type": "string" },
      "InvoiceValue": { "type": "string" },      // ← WE define this
      "ContractField": { "type": "string" },
      "ContractValue": { "type": "string" }      // ← WE define this
    }
  }
}
```

### Step 2: Azure Analyzes Documents (Following Our Instructions)
- Reads invoice PDF
- Reads contract PDF  
- Extracts data **ONLY for the fields we defined**
- Returns JSON matching our schema structure

### Step 3: Backend Stores Results
```json
{
  "PaymentTermsInconsistencies": [
    {
      "Evidence": "The invoice states 'Due on contract signing' and totals $29,900...",
      "InvoiceField": "Payment Terms",
      "InvoiceValue": "$29,900",           // ← Azure extracted this
      "ContractField": "Payment Schedule",
      "ContractValue": "staged payment"    // ← Azure extracted this
    }
  ]
}
```

### Step 4: Frontend Uses the Data
```typescript
const invoiceValue = inconsistencyData.InvoiceValue;   // "$29,900"
const contractValue = inconsistencyData.ContractValue; // "staged payment"

// Search for these exact values in document contents to identify source files
```

---

## ❌ The Problem (Before Update):

**Old Schema:**
```json
{
  "properties": {
    "Evidence": { "type": "string" },
    "InvoiceField": { "type": "string" }
    // ❌ Missing: InvoiceValue, ContractValue, ContractField
  }
}
```

**What Azure Returned:**
```json
{
  "Evidence": "Full explanation with values embedded in text...",
  "InvoiceField": "Payment Terms"
  // ❌ No InvoiceValue (we didn't ask for it!)
  // ❌ No ContractValue (we didn't ask for it!)
}
```

**Frontend Tried to Use Missing Data:**
```typescript
const invoiceValue = inconsistencyData.InvoiceValue;  // undefined!
const contractValue = inconsistencyData.ContractValue; // undefined!
// ❌ Comparison buttons fail - no values to search for
```

---

## ✅ The Solution (After Update):

**New Schema (CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_UPDATED.json):**
```json
{
  "properties": {
    "Evidence": {
      "type": "string",
      "description": "Evidence or reasoning for the inconsistency"
    },
    "InvoiceField": {
      "type": "string",
      "description": "Invoice field that is inconsistent"
    },
    "InvoiceValue": {
      "type": "string",
      "description": "The EXACT value found in the invoice (e.g., '$29,900', 'Due on signing')"
    },
    "ContractField": {
      "type": "string",
      "description": "Contract field that is inconsistent"
    },
    "ContractValue": {
      "type": "string",
      "description": "The EXACT value found in the contract (e.g., 'staged payment')"
    }
  }
}
```

**What Azure Will Return (After Re-Analysis):**
```json
{
  "Evidence": "The invoice states 'Due on contract signing' and totals $29,900...",
  "InvoiceField": "Payment Terms",
  "InvoiceValue": "$29,900",           // ✅ Extracted!
  "ContractField": "Payment Schedule",
  "ContractValue": "staged payment"    // ✅ Extracted!
}
```

**Frontend Uses Real Data:**
```typescript
const invoiceValue = inconsistencyData.InvoiceValue;   // "$29,900" ✅
const contractValue = inconsistencyData.ContractValue; // "staged payment" ✅

// Search document contents for these exact values
// Find invoice.pdf contains "$29,900" → documentA
// Find contract.pdf contains "staged payment" → documentB
// Show correct files in comparison modal ✅
```

---

## Temporary Workaround (Current Code):

Since the current analysis results were created with the **old schema**, the frontend now:

1. **Tries to get InvoiceValue/ContractValue** (will be undefined with old data)
2. **Falls back to parsing Evidence field** (extracts quoted text, dollar amounts)
3. **Uses parsed values for document matching** (works, but not ideal)

```typescript
// Step 1: Try to get proper fields
let invoiceValue = inconsistencyData?.InvoiceValue;

// Step 2: Fallback - parse from Evidence if missing
if (!invoiceValue) {
  const evidence = inconsistencyData.Evidence;
  const quoteMatches = evidence.match(/'([^']+)'/g);
  invoiceValue = quoteMatches[0]; // "Due on contract signing"
}
```

---

## Next Steps:

1. **Upload Updated Schema** → Use `CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_UPDATED.json`
2. **Re-Run Analysis** → Azure will extract InvoiceValue and ContractValue
3. **Test Comparison Buttons** → Should work perfectly with proper data
4. **Remove Temporary Parsing** → No longer need Evidence fallback

---

## Key Insight:

**Azure doesn't magically know what to extract** - it follows our instructions!

- ✅ We define `InvoiceValue` → Azure extracts it
- ❌ We don't define `InvoiceValue` → Azure doesn't extract it
- 🔧 Missing field → We added temporary parsing workaround
- 🎯 Proper fix → Update schema, re-run analysis

**The schema IS the contract between us and Azure!** 🤝
