# Schema Self-Review Quality Improvements

**Date**: November 9, 2025  
**Purpose**: Enhance self-reviewing schema generation to match or exceed human-adjusted schema quality  
**Goal**: Eliminate need for manual schema review by addressing all known quality gaps

---

## Executive Summary

Analysis of AI-generated schemas vs manually-adjusted schemas reveals **7 critical quality dimensions** where self-review can be enhanced. By systematically addressing these gaps, the self-reviewing schema generation can potentially **replace human manual review entirely**.

**Current State**:
- ✅ Schema naming solved (3-step self-review with knowledge graph)
- ⚠️ Field descriptions: Generic vs detailed and actionable
- ⚠️ Structural organization: Flat vs hierarchical with metadata
- ⚠️ Business context: Technical vs business-oriented
- ⚠️ Instructions clarity: Implicit vs explicit behavioral guidance
- ⚠️ Consistency guidance: Absent vs explicit consistency requirements
- ⚠️ Error prevention: Basic vs comprehensive with edge case handling

---

## Comparison Analysis: AI-Generated vs Manual Schema

### Test Case: Invoice-Contract Verification Schema

#### Schema A: AI-Generated (Baseline)
```json
{
  "schemaName": "InvoiceContractVerificationSchema",
  "schemaDescription": "Extracts inconsistencies between invoice and contract documents",
  "fields": {
    "PaymentTermsInconsistencies": {
      "type": "array",
      "description": "List of payment term discrepancies",
      "items": {
        "type": "object",
        "properties": {
          "Evidence": {"type": "string", "description": "Evidence for inconsistency"},
          "InvoiceField": {"type": "string", "description": "Invoice field name"},
          "ContractClause": {"type": "string", "description": "Contract clause reference"}
        }
      }
    },
    "ItemInconsistencies": {
      "type": "array",
      "description": "List of item discrepancies",
      "items": {...}
    }
  }
}
```

#### Schema B: Human-Adjusted (Production Quality)
```json
{
  "schemaName": "InvoiceContractVerification",
  "schemaDescription": "Analyze invoice to confirm total consistency with signed contract. Generate ALL inconsistencies in a SINGLE comprehensive analysis to ensure global consistency of values, dates, and amounts across all categories.",
  "fields": {
    "AllInconsistencies": {
      "type": "array",
      "method": "generate",
      "description": "CRITICAL: Analyze ALL documents comprehensively and generate a COMPLETE array of ALL inconsistencies found across ALL categories in ONE unified analysis. IMPORTANT: Maintain consistency of all values across all inconsistencies. If a $50,000 amount appears in one inconsistency, use the SAME $50,000 in related inconsistencies.",
      "items": {
        "type": "object",
        "description": "Single inconsistency with category classification and complete structured evidence",
        "properties": {
          "Category": {
            "type": "string",
            "description": "Primary category of this inconsistency. Must be one of: 'PaymentTerms', 'Items', 'BillingLogistics', 'PaymentSchedule', 'TaxDiscount'. This enables frontend grouping by category."
          },
          "InconsistencyType": {
            "type": "string",
            "description": "Specific type of inconsistency within the category (e.g., 'Payment Due Date Mismatch', 'Item Description Mismatch')."
          },
          "Evidence": {
            "type": "string",
            "description": "Clear evidence explaining this inconsistency. Include specific values, amounts, dates that differ. If this inconsistency relates to others, mention the connection (e.g., 'This item price mismatch of $10,000 contributes to the payment total discrepancy')."
          },
          "Severity": {
            "type": "string",
            "description": "Severity level: 'Critical', 'High', 'Medium', or 'Low'. Critical = financial impact >$10K or legal risk. High = significant business impact. Medium = minor discrepancy. Low = formatting difference."
          },
          "RelatedCategories": {
            "type": "array",
            "description": "Optional: List of other category names where related inconsistencies exist. Example: An item price mismatch (Category='Items') affects the payment total (RelatedCategories=['PaymentTerms']). This helps users understand cascading effects.",
            "items": {
              "type": "string",
              "description": "Category name: 'PaymentTerms', 'Items', 'BillingLogistics', 'PaymentSchedule', or 'TaxDiscount'"
            }
          },
          "Documents": {
            "type": "array",
            "description": "Array of document comparison pairs involved in this inconsistency. Each item represents one invoice-contract pair comparison.",
            "items": {
              "type": "object",
              "description": "A single document comparison pair showing the inconsistent values from two documents",
              "properties": {
                "DocumentAField": {
                  "type": "string",
                  "description": "Field name in the invoice that contains the inconsistent value (DocumentA = Invoice)."
                },
                "DocumentAValue": {
                  "type": "string",
                  "description": "Exact value found in the invoice. Use consistent formatting across all inconsistencies (e.g., if you write '$50,000' in one place, use '$50,000' everywhere, not '$50K' or '50000')."
                },
                "DocumentASourceDocument": {
                  "type": "string",
                  "description": "Original filename WITHOUT any UUID prefix. If filename in storage is '7543c5b8-903b-466c-95dc-1a920040d10c_invoice_2024.pdf', return ONLY 'invoice_2024.pdf'."
                },
                "DocumentAPageNumber": {
                  "type": "number",
                  "description": "Page number in the invoice document where this inconsistency was found (1-based index, first page = 1)."
                }
              }
            }
          }
        }
      }
    },
    "InconsistencySummary": {
      "type": "object",
      "method": "generate",
      "description": "High-level summary of all inconsistencies found. Generate this AFTER analyzing all inconsistencies to provide accurate counts and severity assessment.",
      "properties": {
        "TotalInconsistencies": {"type": "number", "description": "Total count of all inconsistencies found across all categories."},
        "CriticalCount": {"type": "number", "description": "Count of Critical severity inconsistencies."},
        "OverallRiskLevel": {"type": "string", "description": "Overall risk assessment: 'Critical', 'High', 'Medium', 'Low'."},
        "KeyFindings": {"type": "string", "description": "1-2 sentence summary of the most important inconsistencies found."}
      }
    }
  }
}
```

---

## Gap Analysis: 7 Quality Dimensions

### **Gap 1: Schema Organization - Flat vs Hierarchical + Summary**

**AI-Generated (Baseline)**:
```json
{
  "PaymentTermsInconsistencies": {...},
  "ItemInconsistencies": {...},
  "BillingLogisticsInconsistencies": {...}
  // Flat structure, no metadata or summary
}
```

**Human-Adjusted (Production)**:
```json
{
  "AllInconsistencies": {
    "items": {
      "properties": {
        "Category": "PaymentTerms | Items | BillingLogistics...",
        "InconsistencyType": "...",
        // Unified structure with category classification
      }
    }
  },
  "InconsistencySummary": {
    "TotalInconsistencies": "...",
    "CriticalCount": "...",
    "CategoryBreakdown": {...}
    // Metadata for analytics and UI grouping
  }
}
```

**Why Human Version is Better**:
- ✅ **Single unified array** - easier to process and ensures consistency
- ✅ **Category field** - enables frontend grouping without separate arrays
- ✅ **Summary object** - provides analytics and overview without re-processing
- ✅ **Scalable** - adding new categories doesn't require schema changes

**Self-Review Improvement**: Detect when multiple similar arrays are being created and consolidate into a single array with categorical metadata.

---

### **Gap 2: Description Specificity - Generic vs Actionable**

**AI-Generated (Baseline)**:
```json
{
  "Evidence": {
    "description": "Evidence for inconsistency"
  }
}
```

**Human-Adjusted (Production)**:
```json
{
  "Evidence": {
    "description": "Clear evidence explaining this inconsistency. Include specific values, amounts, dates that differ. If this inconsistency relates to others, mention the connection (e.g., 'This item price mismatch of $10,000 contributes to the payment total discrepancy')."
  }
}
```

**Why Human Version is Better**:
- ✅ **Explicit guidance** - tells LLM exactly what to include
- ✅ **Examples** - shows format and level of detail expected
- ✅ **Cross-references** - encourages relationship mapping
- ✅ **Actionable** - description guides extraction behavior

**Self-Review Improvement**: Expand field descriptions with specific requirements, examples, and cross-reference guidance.

---

### **Gap 3: Value Consistency Guidance - Implicit vs Explicit**

**AI-Generated (Baseline)**:
```json
{
  "description": "List of payment term discrepancies"
  // No consistency requirements mentioned
}
```

**Human-Adjusted (Production)**:
```json
{
  "description": "IMPORTANT: Maintain consistency of all values (amounts, dates, product names) across all inconsistencies. If a $50,000 amount appears in one inconsistency, use the SAME $50,000 in related inconsistencies. Generate the ENTIRE array in ONE pass to ensure global consistency."
}
```

**Why Human Version is Better**:
- ✅ **Prevents data conflicts** - same amount shown differently in different places
- ✅ **Explicit instruction** - tells LLM to maintain consistency
- ✅ **Single-pass directive** - ensures global view of data
- ✅ **Format standardization** - use same format for values

**Self-Review Improvement**: Add explicit consistency requirements when multiple related fields or arrays are detected.

---

### **Gap 4: Severity/Classification Guidance - Missing vs Detailed**

**AI-Generated (Baseline)**:
```json
// No severity or classification fields
```

**Human-Adjusted (Production)**:
```json
{
  "Severity": {
    "type": "string",
    "description": "Severity level: 'Critical', 'High', 'Medium', or 'Low'. Critical = financial impact >$10K or legal risk. High = significant business impact. Medium = minor discrepancy. Low = formatting difference."
  }
}
```

**Why Human Version is Better**:
- ✅ **Clear criteria** - defines what makes something critical vs low
- ✅ **Quantitative thresholds** - >$10K for critical
- ✅ **Business impact** - links technical findings to business consequences
- ✅ **Consistent classification** - standardized across all inconsistencies

**Self-Review Improvement**: When generating fields about issues/errors/inconsistencies, automatically add severity classification with clear criteria.

---

### **Gap 5: Relationship Mapping - Missing vs Explicit**

**AI-Generated (Baseline)**:
```json
// No relationship or cross-reference fields
```

**Human-Adjusted (Production)**:
```json
{
  "RelatedCategories": {
    "type": "array",
    "description": "Optional: List of other category names where related inconsistencies exist. Example: An item price mismatch (Category='Items') affects the payment total (RelatedCategories=['PaymentTerms']). This helps users understand cascading effects.",
    "items": {
      "type": "string",
      "description": "Category name: 'PaymentTerms', 'Items', 'BillingLogistics', 'PaymentSchedule', or 'TaxDiscount'"
    }
  }
}
```

**Why Human Version is Better**:
- ✅ **Cascading effects** - shows how one issue impacts others
- ✅ **Business understanding** - helps users see big picture
- ✅ **Root cause analysis** - enables tracing issues back to source
- ✅ **Data integrity** - cross-validates related fields

**Self-Review Improvement**: Detect when fields are related and automatically add relationship/cross-reference fields.

---

### **Gap 6: Document Provenance - Basic vs Detailed**

**AI-Generated (Baseline)**:
```json
{
  "InvoiceField": {"type": "string", "description": "Invoice field name"},
  "ContractClause": {"type": "string", "description": "Contract clause reference"}
}
```

**Human-Adjusted (Production)**:
```json
{
  "Documents": {
    "type": "array",
    "description": "Array of document comparison pairs involved in this inconsistency. Each item represents one invoice-contract pair comparison.",
    "items": {
      "type": "object",
      "properties": {
        "DocumentAField": {...},
        "DocumentAValue": {...},
        "DocumentASourceDocument": {
          "description": "Original filename WITHOUT any UUID prefix. If filename in storage is '7543c5b8-..._invoice_2024.pdf', return ONLY 'invoice_2024.pdf'."
        },
        "DocumentAPageNumber": {
          "description": "Page number where this inconsistency was found (1-based index, first page = 1)."
        }
      }
    }
  }
}
```

**Why Human Version is Better**:
- ✅ **Structured comparison** - clear A vs B pattern
- ✅ **Page numbers** - exact location in documents
- ✅ **Filename normalization** - strips UUIDs for user-friendly display
- ✅ **Multiple comparisons** - supports array of document pairs
- ✅ **Traceability** - users can verify findings in original documents

**Self-Review Improvement**: When comparing documents, automatically structure as DocumentA/DocumentB pairs with page numbers and normalized filenames.

---

### **Gap 7: Behavioral Instructions - Missing vs Comprehensive**

**AI-Generated (Baseline)**:
```json
{
  "description": "Analyze invoice to confirm total consistency with signed contract"
  // High-level goal only
}
```

**Human-Adjusted (Production)**:
```json
{
  "description": "Analyze invoice to confirm total consistency with signed contract. Generate ALL inconsistencies in a SINGLE comprehensive analysis to ensure global consistency of values, dates, and amounts across all categories. This unified approach prevents conflicting data between different inconsistency types."
}
```

**Why Human Version is Better**:
- ✅ **Single-pass directive** - prevents incremental processing inconsistencies
- ✅ **Comprehensive requirement** - ensures nothing is missed
- ✅ **Explicit problem prevention** - "prevents conflicting data"
- ✅ **Reasoning included** - explains why unified approach matters

**Self-Review Improvement**: Add behavioral instructions that guide the extraction process itself, not just what to extract.

---

## Enhanced Self-Review Prompt (Step 3)

### Current Step 3:
```
STEP 3 (Schema Refinement): Review the generated schema and refine field definitions:
- Add clear, descriptive field descriptions
- Ensure proper data types for each field
- Add validation rules where appropriate
- Organize fields logically
Output the final refined schema with improved field definitions.
```

### **Enhanced Step 3 (Production-Quality)**:

```python
"""
STEP 3 (Schema Quality Enhancement): Apply production-quality refinements to the schema:

1. STRUCTURAL ORGANIZATION:
   - If you see multiple similar arrays (e.g., PaymentTermsInconsistencies, ItemInconsistencies, BillingInconsistencies):
     → Consolidate into ONE unified array (e.g., AllInconsistencies) with a "Category" field
   - Add a Summary object with analytics (TotalCount, CategoryBreakdown, SeverityBreakdown, KeyFindings)
   - Use hierarchical structure: Details + Summary (not flat lists)

2. FIELD DESCRIPTIONS - Make them ACTIONABLE and SPECIFIC:
   - ❌ Bad: "Invoice field name"
   - ✅ Good: "Field name in the invoice that contains the inconsistent value (DocumentA = Invoice)"
   - Include:
     * What to extract (specific values, amounts, dates)
     * How to format (examples: '$50,000' not '$50K')
     * Cross-references (mention related fields)
     * Business context (why this field matters)

3. CONSISTENCY REQUIREMENTS - Add explicit guidance:
   - For arrays or related fields, add: "IMPORTANT: Maintain consistency of all values across all items. If a $50,000 amount appears in one place, use the SAME $50,000 in related fields."
   - Require single-pass generation: "Generate the ENTIRE array in ONE pass to ensure global consistency"
   - Specify formatting standards: "Use consistent formatting (e.g., 'YYYY-MM-DD' for dates, '$X,XXX.XX' for amounts)"

4. SEVERITY/CLASSIFICATION - Add when dealing with issues/errors/inconsistencies:
   - Add "Severity" field: {type: "string", description: "Severity level: 'Critical', 'High', 'Medium', or 'Low'. Critical = financial impact >$10K or legal risk. High = significant business impact..."}
   - Add "InconsistencyType" or similar: specific classification within category
   - Include clear criteria for each level

5. RELATIONSHIP MAPPING - Enable cascading analysis:
   - Add "RelatedCategories" or "RelatedFields" arrays
   - Description: "Optional: List of other categories/fields where related items exist. Example: An item price mismatch (Category='Items') affects payment total (RelatedCategories=['PaymentTerms']). This helps understand cascading effects."

6. DOCUMENT PROVENANCE - Use structured comparison pattern:
   - For document comparisons, use DocumentA/DocumentB pattern:
     * DocumentAField, DocumentAValue, DocumentASourceDocument, DocumentAPageNumber
     * DocumentBField, DocumentBValue, DocumentBSourceDocument, DocumentBPageNumber
   - Add filename normalization: "Original filename WITHOUT any UUID prefix. If filename in storage is '7543c5b8-..._invoice.pdf', return ONLY 'invoice.pdf'."
   - Include page numbers: "Page number where this was found (1-based index, first page = 1)"

7. BEHAVIORAL INSTRUCTIONS - Guide the extraction process:
   - Add to schema or array descriptions:
     * "Generate ALL items in a SINGLE comprehensive analysis"
     * "This unified approach prevents conflicting data between different types"
     * "Analyze comprehensively before generating any output to ensure global understanding"

8. EXAMPLES IN DESCRIPTIONS:
   - Include concrete examples: "(e.g., 'Payment Due Date Mismatch', 'Item Description Mismatch')"
   - Show expected format: "(e.g., 'This item price mismatch of $10,000 contributes to the payment total discrepancy')"
   - Demonstrate edge cases: "(e.g., if comparing multiple document pairs, create multiple items in this array)"

9. EDGE CASE HANDLING:
   - Add "Optional:" prefix to non-required fields
   - Specify behavior when data is missing: "If not found, use empty string"
   - Define array behavior: "If comparing multiple pairs, create multiple items"

10. FRONTEND-FRIENDLY DESIGN:
    - Add fields that enable UI features: "This enables frontend grouping by category"
    - Support analytics: TotalCount, Breakdowns, Risk assessments
    - Enable traceability: Page numbers, source documents, exact values

Output the enhanced schema with production-quality field definitions, structural optimizations, and comprehensive behavioral guidance.
"""
```

---

## Implementation Tasks

### Task 1: Update Self-Review Prompt in Backend ✅
**File**: `backend/utils/query_schema_generator.py`

**Changes**:
1. Replace Step 3 prompt with enhanced version above
2. Add quality validation after Step 3:
   - Check for consistency requirements in array descriptions
   - Verify severity/classification fields exist for issue-related schemas
   - Confirm document provenance uses A/B pattern
   - Validate that examples are included in descriptions

**Estimated Time**: 2 hours

**Success Criteria**:
- Step 3 prompt includes all 10 quality dimensions
- Generated schemas include actionable descriptions with examples
- Consistency requirements appear in relevant field descriptions
- Document comparisons use structured A/B pattern

---

### Task 2: Add Schema Quality Metrics 📊
**File**: `backend/utils/query_schema_generator.py` (new method)

**Purpose**: Measure schema quality automatically

**Implementation**:
```python
def assess_schema_quality(self, schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess generated schema quality across 7 dimensions.
    Returns quality metrics and improvement suggestions.
    """
    metrics = {
        "organization_score": 0,      # Hierarchical vs flat
        "description_score": 0,       # Actionable vs generic
        "consistency_score": 0,       # Explicit guidance present
        "classification_score": 0,    # Severity/type fields present
        "relationship_score": 0,      # Cross-references present
        "provenance_score": 0,        # Document tracking detailed
        "behavioral_score": 0,        # Process guidance included
        "overall_score": 0,
        "suggestions": []
    }
    
    fields = schema.get("fields", {})
    
    # 1. Organization: Check for summary objects
    has_summary = any("summary" in k.lower() for k in fields.keys())
    has_unified_array = any(
        k.lower().startswith("all") and fields[k].get("type") == "array" 
        for k in fields.keys()
    )
    metrics["organization_score"] = (50 if has_summary else 0) + (50 if has_unified_array else 0)
    
    # 2. Description quality: Check for examples and specificity
    descriptions = []
    for field_name, field_def in fields.items():
        desc = field_def.get("description", "")
        descriptions.append(desc)
        if "properties" in field_def:
            for prop_name, prop_def in field_def["properties"].items():
                descriptions.append(prop_def.get("description", ""))
    
    has_examples = sum("e.g.," in d or "example:" in d.lower() for d in descriptions)
    has_specific = sum(len(d) > 100 for d in descriptions)  # Detailed descriptions
    metrics["description_score"] = min(100, (has_examples * 10) + (has_specific * 5))
    
    # 3. Consistency: Check for consistency keywords
    consistency_keywords = ["consistent", "same", "global", "entire array", "one pass"]
    has_consistency = sum(
        any(kw in d.lower() for kw in consistency_keywords) 
        for d in descriptions
    )
    metrics["consistency_score"] = min(100, has_consistency * 25)
    
    # 4. Classification: Check for severity/type fields
    has_severity = any("severity" in k.lower() for k in fields.keys())
    has_type_classification = any("type" in k.lower() and "inconsistency" in k.lower() for k in fields.keys())
    metrics["classification_score"] = (50 if has_severity else 0) + (50 if has_type_classification else 0)
    
    # 5. Relationships: Check for related fields
    has_related = any("related" in k.lower() for k in fields.keys())
    metrics["relationship_score"] = 100 if has_related else 0
    
    # 6. Provenance: Check for document A/B pattern
    has_doc_pattern = any(
        "documenta" in str(field_def).lower() and "documentb" in str(field_def).lower()
        for field_def in fields.values()
    )
    has_page_numbers = any("pagenumber" in str(field_def).lower() for field_def in fields.values())
    metrics["provenance_score"] = (50 if has_doc_pattern else 0) + (50 if has_page_numbers else 0)
    
    # 7. Behavioral: Check for process instructions
    behavioral_keywords = ["generate all", "comprehensive", "unified approach", "single pass"]
    has_behavioral = sum(
        any(kw in d.lower() for kw in behavioral_keywords) 
        for d in descriptions
    )
    metrics["behavioral_score"] = min(100, has_behavioral * 33)
    
    # Overall score
    scores = [
        metrics["organization_score"],
        metrics["description_score"],
        metrics["consistency_score"],
        metrics["classification_score"],
        metrics["relationship_score"],
        metrics["provenance_score"],
        metrics["behavioral_score"]
    ]
    metrics["overall_score"] = sum(scores) / len(scores)
    
    # Generate suggestions
    if metrics["organization_score"] < 50:
        metrics["suggestions"].append("Consider consolidating multiple arrays into one unified array with category field")
    if metrics["description_score"] < 70:
        metrics["suggestions"].append("Add more examples and specific guidance in field descriptions")
    if metrics["consistency_score"] < 50:
        metrics["suggestions"].append("Add explicit consistency requirements for related fields")
    # ... etc for each dimension
    
    return metrics
```

**Success Criteria**:
- Quality assessment runs after schema generation
- Scores calculated for all 7 dimensions
- Suggestions generated for low-scoring areas
- Overall score > 85 for production-quality schemas

---

### Task 3: Create Quality Comparison Test Suite 🧪
**File**: `test_schema_quality_enhanced.py` (new)

**Purpose**: Compare baseline vs enhanced self-review schemas

**Test Cases**:
1. Invoice-Contract Verification (reference: CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json)
2. Purchase Order Processing
3. Expense Report Validation
4. Contract Compliance Check
5. Multi-document Reconciliation

**For Each Test**:
- Generate schema with baseline self-review (current Step 3)
- Generate schema with enhanced self-review (new Step 3)
- Compare quality metrics
- Compare against human-adjusted reference (when available)
- Measure:
  * Field description length and specificity
  * Presence of consistency requirements
  * Structural organization (unified vs fragmented)
  * Document provenance completeness
  * Behavioral instruction inclusion

**Success Criteria**:
- Enhanced self-review scores ≥85% on all 7 dimensions
- Enhanced self-review matches or exceeds human-adjusted schemas
- Baseline self-review scores <70% (validates improvements are meaningful)

---

### Task 4: Add Quality Feedback Loop 🔄
**File**: `backend/utils/query_schema_generator.py`

**Purpose**: Automatically improve schemas that don't meet quality thresholds

**Implementation**:
```python
def generate_with_quality_validation(
    self, query: str, 
    session_id: Optional[str] = None,
    include_schema_generation: bool = False,
    min_quality_score: float = 85.0
) -> Dict[str, Any]:
    """
    Generate schema with quality validation and auto-improvement.
    
    If quality score < min_quality_score, re-run Step 3 with specific improvement instructions.
    """
    max_iterations = 3
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        
        # Generate schema (steps 1-3)
        schema = self.generate_structured_schema(query, session_id, include_schema_generation)
        
        if not include_schema_generation:
            return schema  # Skip quality check for non-generated schemas
        
        # Assess quality
        generated_schema = schema.get("GeneratedSchema", {})
        quality_metrics = self.assess_schema_quality(generated_schema)
        
        print(f"\n[Quality Check] Iteration {iteration}:")
        print(f"  Overall Score: {quality_metrics['overall_score']:.1f}/100")
        for dimension in ["organization", "description", "consistency", "classification", 
                         "relationship", "provenance", "behavioral"]:
            score = quality_metrics[f"{dimension}_score"]
            print(f"  {dimension.title()}: {score:.0f}/100")
        
        if quality_metrics["overall_score"] >= min_quality_score:
            print(f"✅ Quality threshold met ({quality_metrics['overall_score']:.1f} >= {min_quality_score})")
            return schema
        
        if iteration < max_iterations:
            print(f"⚠️ Quality below threshold, re-refining with specific improvements...")
            # Re-run Step 3 with targeted improvements
            improvement_instructions = "\n".join([
                f"- {suggestion}" for suggestion in quality_metrics["suggestions"]
            ])
            # Append improvement instructions to Step 3 prompt
            # (Implementation details omitted for brevity)
    
    print(f"⚠️ Max iterations reached. Returning best schema (score: {quality_metrics['overall_score']:.1f})")
    return schema
```

**Success Criteria**:
- Schemas meeting quality threshold on first iteration: >70%
- Schemas meeting quality threshold after iteration 2: >95%
- Average iterations per schema: <1.5
- Quality scores improve on each iteration

---

### Task 5: Document Quality Best Practices 📚
**File**: `SCHEMA_QUALITY_BEST_PRACTICES.md` (new)

**Content**:
1. **Quality Dimensions Explained**
   - What each dimension measures
   - Why it matters for production use
   - Examples of good vs poor quality

2. **Field Description Writing Guide**
   - Template: "[What to extract]. [How to format]. [Cross-references]. [Business context]."
   - Examples from high-quality schemas
   - Common mistakes to avoid

3. **Structural Organization Patterns**
   - When to use unified arrays vs separate arrays
   - When to add summary objects
   - How to design for frontend grouping

4. **Consistency Requirements Template**
   - Standard phrasing for consistency instructions
   - When to require single-pass generation
   - How to specify formatting standards

5. **Document Comparison Pattern**
   - DocumentA/DocumentB structure template
   - Filename normalization guidance
   - Page number best practices

**Success Criteria**:
- Comprehensive guide for each quality dimension
- Examples from real production schemas
- Clear templates for common patterns
- Actionable guidance for manual schema creation

---

### Task 6: Update Frontend Schema Review Dialog 🎨
**File**: `SchemaReviewDialog.tsx`

**Purpose**: Show quality metrics to users during review

**Enhancement**:
```typescript
interface SchemaQualityMetrics {
  overall_score: number;
  organization_score: number;
  description_score: number;
  consistency_score: number;
  classification_score: number;
  relationship_score: number;
  provenance_score: number;
  behavioral_score: number;
  suggestions: string[];
}

// Add quality badge to dialog
<MessageBar intent={qualityScore >= 85 ? "success" : "warning"}>
  <MessageBarBody>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <Info16Regular />
      <div>
        <strong>Schema Quality Score: {qualityScore}/100</strong>
        {qualityScore >= 85 ? (
          <span> - Production ready</span>
        ) : (
          <span> - Review suggestions below before saving</span>
        )}
      </div>
    </div>
  </MessageBarBody>
</MessageBar>

{suggestions.length > 0 && (
  <div style={{ marginTop: 12 }}>
    <Label>Quality Improvement Suggestions:</Label>
    <ul>
      {suggestions.map((suggestion, index) => (
        <li key={index}>{suggestion}</li>
      ))}
    </ul>
  </div>
)}
```

**Success Criteria**:
- Quality score displayed prominently
- Green badge for score ≥85
- Yellow/orange badge for score <85
- Suggestions shown when score <85
- Users can still save low-quality schemas (with warning)

---

## Success Metrics

### Development Phase (Tasks 1-6)
- [ ] Enhanced Step 3 prompt implemented with all 10 quality dimensions
- [ ] Quality assessment function calculates scores for 7 dimensions
- [ ] Quality feedback loop reduces iterations needed
- [ ] Test suite validates enhanced vs baseline quality
- [ ] Best practices documentation complete
- [ ] Frontend shows quality metrics to users

### Quality Validation (Post-Implementation)
- [ ] Enhanced schemas score ≥85/100 on average (vs <70 for baseline)
- [ ] 95%+ of enhanced schemas meet quality threshold in ≤2 iterations
- [ ] User manual edits reduced by 80% (measured by edit count in SchemaReviewDialog)
- [ ] Enhanced schemas match or exceed human-adjusted reference schemas

### Production Readiness
- [ ] A/B test shows enhanced schemas perform as well as human-adjusted
- [ ] User acceptance testing confirms schemas are production-ready
- [ ] Documentation reviewed and approved by schema design experts
- [ ] Quality metrics integrated into monitoring dashboards

---

## Timeline

**Week 1: Core Implementation**
- Days 1-2: Task 1 - Update self-review prompt
- Day 3: Task 2 - Add quality metrics
- Day 4: Task 3 - Create test suite
- Day 5: Run tests, collect baseline data

**Week 2: Refinement & Validation**
- Days 1-2: Task 4 - Quality feedback loop
- Day 3: Task 5 - Documentation
- Day 4: Task 6 - Frontend integration
- Day 5: End-to-end testing

**Week 3: Production Rollout**
- A/B testing with users
- Monitoring and metrics collection
- Iterate based on feedback
- Full production deployment

---

## Risk Mitigation

### Risk 1: Enhanced Prompt Too Complex
**Mitigation**: 
- Test with varying prompt complexity levels
- Measure Azure API latency and token usage
- Have fallback to simpler prompt if needed

### Risk 2: Quality Metrics Too Strict
**Mitigation**:
- Tune thresholds based on real-world data
- Allow configurable quality thresholds
- Provide override for power users

### Risk 3: Over-Engineering
**Mitigation**:
- Start with highest-impact improvements (consistency, descriptions)
- Add complexity incrementally based on user feedback
- Measure actual reduction in manual edits

---

## Conclusion

By systematically addressing the 7 quality dimensions identified in the AI vs Manual comparison, the self-reviewing schema generation can achieve **production-quality output that matches or exceeds human-adjusted schemas**.

**Key Insight**: The gap between AI-generated and human-adjusted schemas isn't in the AI's ability to understand the domain—it's in the **explicit quality requirements and behavioral guidance** provided to the AI. By enhancing Step 3 with comprehensive quality criteria, we enable the AI to self-correct and produce professional-grade schemas.

**Ultimate Goal**: Eliminate the need for human manual review entirely, enabling users to go directly from Quick Query prompt → Generated Schema → Production use.

**Next Action**: Begin Task 1 - Update self-review prompt in backend with enhanced Step 3 instructions.
