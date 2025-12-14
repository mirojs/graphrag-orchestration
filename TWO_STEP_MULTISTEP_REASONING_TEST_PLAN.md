# Two-Step Multi-Step Reasoning Test Plan

## Overview

This document outlines the two-step testing strategy for Azure Content Understanding API's multi-step reasoning capability, comparing AI-generated schemas against manually designed reference schemas.

## Reference Schema

**File**: `/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json`

**Purpose**: Invoice-Contract Verification - Identify ALL inconsistencies between invoice and contract documents

**Structure**:
- **AllInconsistencies** (array): Comprehensive list of all inconsistencies found
  - Category, InconsistencyType, Evidence, Severity
  - RelatedCategories (cross-category relationships)
  - Documents array (invoice-contract comparison pairs)
- **InconsistencySummary** (object): High-level summary
  - Counts by severity (Critical, High, Medium, Low)
  - CategoryBreakdown (PaymentTerms, Items, BillingLogistics, PaymentSchedule, TaxDiscount)
  - OverallRiskLevel, KeyFindings

## Critical Schema Rule

**IMPORTANT**: Only use `"method": "generate"` **ONCE** in the entire schema.

- All other fields are extracted based on the structure defined by that single generated field
- This ensures consistency and prevents conflicting AI interpretations

## Step 1: Schema Generation Quality Test

### Goal
Validate that Azure AI can generate high-quality, production-ready schemas from natural language prompts that match or exceed manually designed reference schemas.

### Test Script
`test_schema_generation_step1.py`

### Process
1. **Input**: Natural language prompt describing the verification task
   ```
   Compare invoice documents against contract documents to identify ALL inconsistencies.
   Extract comprehensive array of inconsistencies with categories, severity, evidence, etc.
   Include summary object with counts and risk assessment.
   ```

2. **Azure Processing**: 
   - Create analyzer with schema generator
   - Use `"method": "generate"` on **ONE** field: `GeneratedSchemaDefinition`
   - Azure AI analyzes the prompt and generates a complete static schema

3. **Output**: AI-generated schema (JSON)

4. **Validation**: Compare against reference schema
   - Field coverage (AllInconsistencies, InconsistencySummary)
   - Structure completeness (arrays, objects, nested properties)
   - Type accuracy (string, number, array, object)
   - Quality score (0-100)

### Success Criteria
- ✅ Quality score ≥ 70/100
- ✅ Both key fields present (AllInconsistencies + InconsistencySummary)
- ✅ Array structures with nested properties
- ✅ Object structures with nested properties
- ✅ Production-ready status

### Example Quality Report
```
SCHEMA GENERATION QUALITY REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 SUMMARY
   Reference Schema Fields: 2
   Generated Schema Fields: 2
   Coverage: 100.0%

🎯 KEY FIELD COVERAGE
   Found: 2
      ✅ AllInconsistencies
      ✅ InconsistencySummary

🏗️  STRUCTURE ANALYSIS
   Array Structures: ✅ Present
   Object Structures: ✅ Present
   Nested Array Properties: ✅ Present
   Nested Object Properties: ✅ Present

⭐ QUALITY SCORE: 90.0/100

🎯 STATUS: ✅ PRODUCTION READY
```

## Step 2: Multi-Step Reasoning Full Evaluation

### Goal
Compare data extraction results between:
- **Approach A**: Multi-step reasoning (AI generates schema → uses schema to extract data)
- **Approach B**: Direct extraction (use pre-defined reference schema)

### Process

#### Approach A: Multi-Step Reasoning (Two API Calls)

**Call 1 - Schema Generation**:
```python
# Analyzer with schema generator
{
  "fields": {
    "GeneratedSchemaDefinition": {
      "type": "object",
      "method": "generate",  # ONLY use "generate" once!
      "description": "Generate complete schema for invoice-contract verification..."
    }
  }
}
```

Result: AI-generated schema

**Call 2 - Data Extraction**:
```python
# Use the AI-generated schema from Call 1
# Analyzer with generated schema as fieldSchema
{
  "fields": {
    "AllInconsistencies": {...},  # From generated schema
    "InconsistencySummary": {...} # From generated schema
  }
}
```

Result: Extracted inconsistencies using AI-generated schema

#### Approach B: Direct Extraction (One API Call)

```python
# Analyzer with reference schema directly
{
  "fields": {
    "AllInconsistencies": {
      "type": "array",
      "method": "generate",  # ONLY use "generate" once!
      "description": "CRITICAL: Analyze ALL documents...",
      "items": {...}
    },
    "InconsistencySummary": {
      "type": "object",
      "description": "High-level summary...",
      "properties": {...}
    }
  }
}
```

Result: Extracted inconsistencies using manually designed schema

### Comparison Metrics

1. **Data Quality**
   - Number of inconsistencies found
   - Completeness of evidence
   - Accuracy of categorization
   - Severity assessment correctness

2. **Structure Consistency**
   - Field naming consistency
   - Value formatting consistency
   - Nested structure handling

3. **Performance**
   - Total processing time
   - API call count (2 vs 1)
   - Token usage

4. **Usability**
   - Which approach found more relevant inconsistencies?
   - Which approach provided clearer evidence?
   - Which approach is easier to maintain/update?

### Expected Outcomes

| Aspect | Multi-Step (A) | Direct (B) |
|--------|----------------|------------|
| **Flexibility** | ✅ High - can adapt to new requirements | ⚠️ Low - requires manual schema updates |
| **API Calls** | ⚠️ 2 calls (generate + extract) | ✅ 1 call |
| **Development Time** | ✅ Faster - no manual schema design | ⚠️ Slower - requires schema expertise |
| **Control** | ⚠️ Less - AI decides structure | ✅ More - exact field control |
| **Consistency** | ⚠️ Variable - depends on prompt | ✅ Predictable - fixed schema |
| **Maintenance** | ✅ Easy - update prompt only | ⚠️ Hard - update JSON schema |

## Test Documents

For Step 2, we need:
- **Invoice document(s)**: PDF with line items, totals, payment terms
- **Contract document(s)**: PDF with agreed terms, pricing, schedules

Upload to Azure Storage container: `pro-input-files`

## Running the Tests

### Step 1: Schema Generation Quality
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939
python test_schema_generation_step1.py
```

Expected output:
- `schema_generation_result_*.json` - Raw API response
- `generated_schema_*.json` - Extracted schema
- `schema_comparison_*.json` - Comparison analysis
- Quality report printed to console

### Step 2: Multi-Step Reasoning Evaluation
(Script to be created after Step 1 succeeds)

```bash
python test_multistep_reasoning_step2.py
```

Expected output:
- `multistep_approach_a_result.json` - Results from AI-generated schema
- `direct_approach_b_result.json` - Results from reference schema
- `final_comparison_report.json` - Side-by-side evaluation
- Recommendations for production use

## Decision Criteria

Proceed to production with **Multi-Step Reasoning** if:
- ✅ Step 1 quality score ≥ 80/100
- ✅ Step 2 finds equal or more inconsistencies
- ✅ Evidence quality is comparable
- ✅ Schema structure is consistent
- ✅ Development/maintenance time savings justify 2 API calls

Use **Direct Extraction** if:
- ⚠️ Need exact control over field structure
- ⚠️ Schema is stable and rarely changes
- ⚠️ Single API call is critical for performance
- ⚠️ AI-generated schemas are inconsistent

## Next Steps

1. ✅ Complete Step 1: Run `test_schema_generation_step1.py`
2. ⏳ Review generated schema quality report
3. ⏳ If quality score ≥ 70: Create Step 2 test script
4. ⏳ Run comparative evaluation with real documents
5. ⏳ Make production decision based on results

---

**Last Updated**: Step 1 test script created, ready for execution
**Status**: Waiting for Step 1 execution and quality validation
