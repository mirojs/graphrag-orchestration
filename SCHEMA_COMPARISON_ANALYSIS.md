# Schema Generation Comparison Analysis

## User Prompt (Original)
```
Find all inconsistencies between contract terms and invoice details
```

---

## 1. ORIGINAL REFERENCE SCHEMA (Target)
**Source:** `data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json`

### Key Structure:
```json
{
  "fieldSchema": {
    "name": "InvoiceContractVerification",
    "description": "Analyze invoice to confirm total consistency with signed contract...",
    "fields": {
      "AllInconsistencies": {
        "type": "array",
        "method": "generate",  // ✅ Has method
        "description": "CRITICAL: Analyze ALL documents comprehensively...",
        "items": {
          "type": "object",
          "properties": {
            "Category": {"type": "string", "description": "..."},
            "InconsistencyType": {"type": "string", "description": "..."},  // ✅ Present
            "Evidence": {"type": "string", "description": "..."},
            "Severity": {"type": "string", "description": "..."},
            "RelatedCategories": {
              "type": "array",
              "items": {"type": "string"}
            },
            "Documents": {  // ✅ Documents as ARRAY
              "type": "array",
              "description": "Array of document comparison pairs...",
              "items": {
                "type": "object",
                "properties": {
                  "DocumentAField": {"type": "string"},
                  "DocumentAValue": {"type": "string"},
                  "DocumentASourceDocument": {"type": "string"},
                  "DocumentAPageNumber": {"type": "number"},
                  "DocumentBField": {"type": "string"},
                  "DocumentBValue": {"type": "string"},
                  "DocumentBSourceDocument": {"type": "string"},
                  "DocumentBPageNumber": {"type": "number"}
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### Required Properties (6):
1. ✅ **Category** - string
2. ✅ **InconsistencyType** - string
3. ✅ **Evidence** - string
4. ✅ **Severity** - string
5. ✅ **RelatedCategories** - array of strings
6. ✅ **Documents** - array of objects with DocumentA/DocumentB structure

---

## 2. CURRENT GENERATED SCHEMA (Azure Result)
**Source:** `generated_schema_1762510132.json`
**Quality Score:** 60.0/100 ⚠️

### Key Structure:
```json
{
  "fieldSchema": {
    "name": "X",  // ⚠️ Generic name
    "fields": {
      "AllInconsistencies": {
        "type": "array",
        // ❌ NO "method": "generate"
        // ❌ NO "description"
        "items": {
          "type": "object",
          "properties": {
            "Category": {"type": "string"},  // ✅ Present
            "Type": {"type": "string"},  // ⚠️ Should be "InconsistencyType"
            "Evidence": {"type": "string"},  // ✅ Present
            "Severity": {"type": "string"},  // ✅ Present
            "RelatedCategories": {"type": "string"},  // ⚠️ Should be ARRAY
            "DocumentComparison": {  // ❌ Should be "Documents" (array)
              "type": "object",  // ❌ Should be ARRAY
              "properties": {
                "DocumentA": {
                  "type": "object",
                  "properties": {
                    "Field": {"type": "string"},  // ⚠️ Should be DocumentAField
                    "Value": {"type": "string"},  // ⚠️ Should be DocumentAValue
                    "Source": {"type": "string"},  // ⚠️ Should be DocumentASourceDocument
                    "PageNumber": {"type": "string"}  // ⚠️ Should be number, not string
                  }
                },
                "DocumentB": {
                  "type": "object",
                  "properties": {
                    "Field": {"type": "string"},
                    "Value": {"type": "string"},
                    "Source": {"type": "string"},
                    "PageNumber": {"type": "string"}
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### What's Missing/Wrong:
❌ **Missing:** `InconsistencyType` property (has "Type" instead)
❌ **Missing:** `Documents` as array (has "DocumentComparison" as object instead)
❌ **Wrong:** `RelatedCategories` is string, should be array
❌ **Wrong:** Document field names don't match (Field vs DocumentAField, etc.)
❌ **Wrong:** PageNumber is string, should be number
❌ **Missing:** `method: "generate"` on AllInconsistencies
❌ **Missing:** All descriptions

### What's Correct:
✅ Has fieldSchema root
✅ Has AllInconsistencies array
✅ Has Category, Evidence, Severity properties
✅ Basic structure resembles target (array of objects)

---

## 3. CURRENT PROMPT (Used in Test)
```
You are a schema design expert. Based on this user request:

Find all inconsistencies between contract terms and invoice details

Return a MINIMAL compact JSON schema object (no descriptions, no extra whitespace) that contains a
top-level 'fieldSchema' with an 'AllInconsistencies' array field. For each property include only the
property name and type. Example output (compact):
{"fieldSchema":{"name":"X","fields":{"AllInconsistencies":{"type":"array","items":{"type":"object","properties":{"Category":{"type":"string"},"Evidence":{"type":"string"}}}}}}}

Return ONLY the compact JSON object and nothing else.
```

### Issues with Current Prompt:
1. ⚠️ **Too vague** - doesn't specify required properties
2. ⚠️ **Example is too simple** - only shows Category and Evidence
3. ⚠️ **No guidance on Documents structure** - doesn't mention array of comparison pairs
4. ⚠️ **No field name guidance** - Azure invented "Type" and "DocumentComparison"
5. ⚠️ **No data type guidance** - Azure made PageNumber a string

---

## 4. PROPOSED REFINED PROMPT

```
You are a schema design expert. Based on this user request:

Find all inconsistencies between contract terms and invoice details

Return a MINIMAL compact JSON schema (no descriptions, minimal whitespace). Required structure:

MUST HAVE these exact properties in AllInconsistencies items:
1. Category (string)
2. InconsistencyType (string) - NOT "Type"
3. Evidence (string)
4. Severity (string)
5. RelatedCategories (array of strings) - NOT a single string
6. Documents (array of objects) - NOT "DocumentComparison", NOT a single object

Each Documents array item MUST have these 8 fields (note the exact names):
- DocumentAField (string)
- DocumentAValue (string)
- DocumentASourceDocument (string)
- DocumentAPageNumber (number) - NOT string
- DocumentBField (string)
- DocumentBValue (string)
- DocumentBSourceDocument (string)
- DocumentBPageNumber (number) - NOT string

Example compact output:
{"fieldSchema":{"name":"InvoiceContractVerification","fields":{"AllInconsistencies":{"type":"array","items":{"type":"object","properties":{"Category":{"type":"string"},"InconsistencyType":{"type":"string"},"Evidence":{"type":"string"},"Severity":{"type":"string"},"RelatedCategories":{"type":"array","items":{"type":"string"}},"Documents":{"type":"array","items":{"type":"object","properties":{"DocumentAField":{"type":"string"},"DocumentAValue":{"type":"string"},"DocumentASourceDocument":{"type":"string"},"DocumentAPageNumber":{"type":"number"},"DocumentBField":{"type":"string"},"DocumentBValue":{"type":"string"},"DocumentBSourceDocument":{"type":"string"},"DocumentBPageNumber":{"type":"number"}}}}}}}}}}

Return ONLY this compact JSON - no markdown, no explanations.
```

### Key Changes:
1. ✅ **Explicit property list** - lists all 6 required properties with exact names
2. ✅ **Clear array guidance** - specifies RelatedCategories and Documents are arrays
3. ✅ **Exact field names** - DocumentAField not Field, InconsistencyType not Type
4. ✅ **Data type guidance** - PageNumber is number not string
5. ✅ **Complete example** - shows the full structure with all properties
6. ✅ **Avoids common mistakes** - explicitly says "NOT DocumentComparison", "NOT Type"

### Expected Improvement:
- **Current Score:** 60.0/100
- **Target Score:** ≥70.0/100 (production ready)
- **Expected Score with Refined Prompt:** 80-90/100

The refined prompt should add:
- +10 points for InconsistencyType property
- +10 points for Documents as array
- +5 points for correct field naming
- **New Score Estimate:** ~85/100 ✅

---

## SUMMARY

| Aspect | Reference | Current Result | Gap |
|--------|-----------|----------------|-----|
| **Property Count** | 6/6 | 4/6 | -2 properties |
| **Documents Structure** | Array | Object | Wrong type |
| **Field Names** | Exact match | Abbreviated | Wrong names |
| **Data Types** | number for pages | string for pages | Wrong type |
| **Quality Score** | 100/100 | 60/100 | -40 points |

**Root Cause:** Current prompt is too vague and provides oversimplified example.

**Solution:** Use refined prompt with explicit requirements, exact field names, and complete example.

**Next Step:** Update test script with refined prompt and re-run to validate improvement.
