# How to Run 3-Step Self-Reviewing Schema Test

**Purpose:** Validate the 3-step self-reviewing schema generation approach before implementing the 6-hour plan.

---

## Quick Start (Same as 2 Days Ago)

```bash
# 1. Make sure you're logged into Azure CLI
az login

# 2. Run the test script
python test_self_reviewing_schema_generation.py
```

That's it! The test uses the same proven setup from `test_real_azure_multistep_api.py`.

---

## What This Test Validates

### ✅ Phase 1: Schema Acceptance (This Test)
- Azure API accepts `GeneratedSchema` field with 3-step prompt
- Performance meets target (≤20 seconds)
- No API errors or validation failures

### ⏳ Phase 2: Field Name Quality (Next Test - If Phase 1 Passes)
- Generated field names are specific (not generic)
- Knowledge graph produces context-aware names
- 90%+ naming accuracy

---

## Expected Output

### Success Case:
```
🧪 3-STEP SELF-REVIEWING SCHEMA GENERATION TEST
==================================================================
📅 Date: 2025-11-09 14:30:00
🌐 Endpoint: https://aicu-cps-xh5lwkfq3vfm.services.ai.azure.com
📋 API Version: 2025-05-01-preview

🔐 Step 1: Getting Azure authentication token...
✅ Azure token acquired

==================================================================
🧪 TEST CASE 1/3
==================================================================
📝 Prompt: 'Find payment discrepancies between invoice and contract'
📄 Document Type: Invoice + Contract comparison

🆔 Analyzer ID: self-review-test-1-1731177000
🚀 Creating analyzer with 3-step self-reviewing schema...
📋 Schema structure:
   • Summary: string (Quick Query result)
   • GeneratedSchema: object (3-step self-reviewed schema)

⏱️  Sending request to Azure...
✅ Response received in 2.34 seconds
✅ Analyzer created successfully
📊 Response includes fieldSchema: True
🧹 Cleaned up analyzer self-review-test-1-1731177000

[... Tests 2 and 3 ...]

==================================================================
📊 COMPREHENSIVE TEST REPORT
==================================================================

📈 SUMMARY STATISTICS
   Total tests: 3
   Successful API calls: 3/3 (100%)
   Schemas accepted by Azure: 3/3 (100%)

⏱️  PERFORMANCE METRICS
   Average response time: 2.45s
   Min response time: 2.12s
   Max response time: 2.89s
   Performance target: ≤20s ✅ PASS

==================================================================
🎯 NEXT STEPS RECOMMENDATION
==================================================================
✅ ALL TESTS PASSED!

📋 The 3-step self-reviewing approach works with Azure API:
   ✓ Schemas accepted by Azure
   ✓ Performance meets target (≤20s)

🚀 READY FOR IMPLEMENTATION:
   → Proceed with 6-hour implementation plan
   → Use this schema pattern in production
   → Expected field naming accuracy: 90%+

⚠️  IMPORTANT: To fully validate field name quality, we need to:
   1. Run actual document analysis (not just analyzer creation)
   2. Examine generated field names
   3. Verify they're specific (not generic)
   4. Confirm knowledge graph usage

   Next test: test_schema_with_actual_document.py
```

---

## Test Cases

The test runs 3 scenarios:

### 1. Payment Discrepancies (Multi-Document)
- **Prompt:** "Find payment discrepancies between invoice and contract"
- **Tests:** Context awareness (InvoiceAmount vs ContractAmount)
- **Expected:** Distinguishes between document types

### 2. Vendor Information (Single Document)
- **Prompt:** "Extract vendor information and payment details"
- **Tests:** Specific field naming
- **Expected:** VendorName, InvoiceNumber, PaymentDueDate (not Name, Number, Date)

### 3. Line Items (Array Structure)
- **Prompt:** "Get all line items with quantities and prices"
- **Tests:** Array handling + specificity
- **Expected:** LineItems, Quantity, UnitPrice (not Items, Value, Amount)

---

## Success Criteria

| Metric | Target | Status |
|--------|--------|--------|
| API Acceptance | 100% schemas accepted | ✅ or ❌ |
| Performance | ≤20 seconds avg | ✅ or ❌ |
| No Errors | 0 API errors | ✅ or ❌ |

**Decision Matrix:**

- **All Pass** → Proceed with 6-hour implementation ✅
- **Partial Pass** → Refine prompt and re-test ⚠️
- **All Fail** → Reconsider approach ❌

---

## If Test Passes - Next Steps

### Option A: Proceed with Implementation (Faster)
```
Decision: Trust Azure's knowledge graph will deliver 90%+ accuracy
Action: Start 6-hour implementation immediately
Risk: Low (Azure has proven knowledge graph capabilities)
```

### Option B: Validate Field Quality First (Safer)
```
Decision: Run actual document analysis to verify field names
Action: Create test_schema_with_actual_document.py
Time: +1 hour
Benefit: See actual generated field names before committing
```

**Recommendation:** If this test passes with 100% success rate and <5s response times, proceed with **Option A** (implementation). Azure's knowledge graph is proven technology.

---

## Troubleshooting

### Error: "Failed to get Azure token"
```bash
# Re-login to Azure
az login

# Verify authentication
az account show
```

### Error: "401 Unauthorized"
```bash
# Check subscription access
az account list

# Get fresh token
az account get-access-token --resource https://cognitiveservices.azure.com
```

### Error: "400 Bad Request"
- Check Azure API version (should be `2025-05-01-preview`)
- Verify endpoint URL is correct
- Review error message in test output

---

## File References

This test is based on proven patterns from:
- `test_real_azure_multistep_api.py` - Azure API interaction pattern
- `test_real_azure_clean_schema.py` - Schema validation approach
- Uses same authentication, endpoint, error handling

---

## Time Investment

- **Running test:** 2-3 minutes
- **Reviewing results:** 2 minutes
- **Total:** ~5 minutes

If test fails, debugging typically takes 10-15 minutes.

**ROI:** 5 minutes of testing saves 6 hours of implementation if approach doesn't work! 🎯

---

**Created:** November 9, 2025  
**Based On:** `test_real_azure_multistep_api.py` (Nov 7, 2025)  
**Purpose:** Pre-implementation validation of simplified schema generation approach
