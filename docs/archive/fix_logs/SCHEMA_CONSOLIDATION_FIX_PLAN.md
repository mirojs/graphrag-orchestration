# Schema Consolidation Fix Plan

## Problem Summary

**Current State (BROKEN):**
AI enhancement creates multiple top-level fields, each with `"method": "generate"`:
```json
{
  "fieldSchema": {
    "fields": {
      "PaymentTermsInconsistencies": {"type": "object", "method": "generate", ...},
      "ItemInconsistencies": {"type": "object", "method": "generate", ...},
      "DateInconsistencies": {"type": "object", "method": "generate", ...}
    }
  }
}
```

**Target State (CORRECT):**
Should create ONE consolidated array field with all items:
```json
{
  "fieldSchema": {
    "fields": {
      "AllInconsistencies": {
        "type": "array",
        "method": "generate",
        "items": {
          "type": "object",
          "properties": {
            "Category": {"type": "string", "description": "Type of inconsistency"},
            "Description": {"type": "string", ...},
            "InvoiceReference": {"type": "string", ...},
            "ContractReference": {"type": "string", ...}
          }
        }
      }
    }
  }
}
```

**Why This Matters:**
- Azure Content Understanding API rejects schemas with object fields missing `properties`
- Current approach creates fragmented data instead of unified arrays
- Each field with separate `generate` method is inefficient
- Reference schema (CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json) shows correct pattern

---

## Files to Modify

### 1. `/code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`

**Function:** `generate_enhancement_schema_from_intent()` (around line 12400)

**Changes Needed:**

#### A. Update the meta-schema instruction for CompleteEnhancedSchema field:

**Current instruction:**
```python
"description": "The complete enhanced schema in JSON format with ALL fields (existing + new)..."
```

**New instruction:**
```python
"description": """The complete enhanced schema in JSON format following the CONSOLIDATED ARRAY PATTERN:

CRITICAL REQUIREMENTS:
1. Use SINGLE array field with "method": "generate" for collections (not multiple object fields)
2. Array items MUST have "properties" defining nested structure
3. Include a "Category" or type discriminator property in array items
4. Example structure:
   {
     "fieldSchema": {
       "fields": {
         "AllItems": {
           "type": "array",
           "method": "generate",
           "description": "All extracted items",
           "items": {
             "type": "object",
             "properties": {
               "Category": {"type": "string", "description": "Item type"},
               "Field1": {"type": "string", "description": "..."},
               "Field2": {"type": "number", "description": "..."}
             }
           }
         }
       }
     }
   }

DO NOT create multiple top-level fields with separate generate methods.
DO NOT use object type for collections - use array with items.properties.
ALWAYS include required Azure properties: "properties" for objects, "items" for arrays.
"""
```

#### B. Remove the NewFieldsToAdd field (creates confusion):

**Remove this entire field definition** (lines ~12430-12438):
```python
"NewFieldsToAdd": {
    "type": "array",
    "method": "generate",
    "description": "List of NEW field names that should be added...",
    ...
}
```

**Reason:** With consolidated pattern, we don't track individual field additions - the entire structure is generated as one cohesive unit.

---

### 2. Response Processing in `proMode.py`

**Function:** `orchestrated_ai_enhancement()` (around line 12650)

**Changes Needed:**

#### A. Remove NewFieldsToAdd extraction:

**Find and remove** (lines ~12668-12680):
```python
# 2. Extract NewFieldsToAdd for summary (list of field names added)
if "NewFieldsToAdd" in fields_data:
    new_fields_array = fields_data["NewFieldsToAdd"]
    if "valueArray" in new_fields_array:
        new_fields_to_add = [
            item.get("valueString", "")
            for item in new_fields_array["valueArray"]
            if item.get("valueString")
        ]
    print(f"📋 New fields to add: {new_fields_to_add}")
else:
    print(f"⚠️ NewFieldsToAdd field not found")
```

#### B. Update field counting logic:

**Replace** the hardcoded field counting with actual schema inspection:

**Find** (around line 12640):
```python
if "fieldSchema" in enhanced_schema_result and "fields" in enhanced_schema_result["fieldSchema"]:
    total_fields = len(enhanced_schema_result["fieldSchema"]["fields"])
    field_names = list(enhanced_schema_result["fieldSchema"]["fields"].keys())
    print(f"✅ Enhanced schema has {total_fields} total fields: {field_names}")
```

**Add after this:**
```python
# Count nested items if using consolidated array pattern
nested_count = 0
for field_name, field_def in enhanced_schema_result["fieldSchema"]["fields"].items():
    if field_def.get("type") == "array" and "items" in field_def:
        if "properties" in field_def["items"]:
            nested_count = len(field_def["items"]["properties"])
            print(f"📊 Field '{field_name}' contains {nested_count} nested properties in array items")

if nested_count > 0:
    print(f"✅ Schema uses consolidated array pattern with {nested_count} nested properties")
else:
    print(f"✅ Schema has {total_fields} top-level fields (traditional pattern)")
```

#### C. Update the AIEnhancementResponse:

**Find** (around line 12770):
```python
return AIEnhancementResponse(
    success=True,
    status="completed",
    enhanced_schema=enhanced_schema_result,
    message=f"Schema enhancement completed successfully",
    new_fields_added=new_fields_to_add,  # ← REMOVE THIS
    ...
)
```

**Change to:**
```python
return AIEnhancementResponse(
    success=True,
    status="completed",
    enhanced_schema=enhanced_schema_result,
    message=f"Schema enhancement completed using {'consolidated array pattern' if nested_count > 0 else 'traditional pattern'}",
    field_count=total_fields,
    nested_property_count=nested_count,
    ...
)
```

---

### 3. Frontend Response Model Update

**File:** `/code/content-processing-solution-accelerator/src/ContentProcessorWeb/src/ProModeServices/intelligentSchemaEnhancerService.ts`

**Changes Needed:**

#### A. Update the enhancement result interface (if exists):

**Find interface definition** and update to match new response:
```typescript
interface EnhancementResult {
  enhancedSchema: any;
  originalHierarchicalSchema: any;
  enhancementSummary: string;
  fieldCount: number;          // Top-level fields
  nestedPropertyCount: number; // Nested properties in arrays
  confidence: number;
  suggestions?: string[];
}
```

#### B. Update success message logic:

**Find** (around line 260):
```typescript
toast.success(`✨ Schema optimized with AI! ${enhancementResult.newFields?.length || 0} new fields added.`);
```

**Replace with:**
```typescript
const message = enhancementResult.nestedPropertyCount > 0
  ? `✨ Schema optimized! Consolidated into ${enhancementResult.fieldCount} field(s) with ${enhancementResult.nestedPropertyCount} properties.`
  : `✨ Schema optimized! ${enhancementResult.fieldCount} fields ready.`;
toast.success(message, { autoClose: 6000 });
```

---

## Testing Plan

### Step 1: Deploy Changes
```bash
cd ./code/content-processing-solution-accelerator/infra/scripts
APP_CONSOLE_LOG_ENABLED=true ./docker-build.sh
```

### Step 2: Test with Quick Query
1. Run Quick Query with prompt: "Extract invoice payment terms and contract clauses"
2. Click "Enhance with AI"
3. **Expected Result:**
   - Backend logs show: "Schema uses consolidated array pattern with X nested properties"
   - Frontend shows: "Consolidated into 1-2 fields with X properties"
   - Saved schema has structure like CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json

### Step 3: Verify Saved Schema
1. Save the enhanced schema
2. Check blob storage schema JSON
3. **Verify:**
   - Top-level field is `array` type with `"method": "generate"`
   - Has `items.properties` with nested structure
   - No multiple object fields with separate generate methods

### Step 4: Test Analysis
1. Select the saved schema
2. Run "Start Analysis" on sample documents
3. **Expected Result:**
   - No "MissingProperty" errors from Azure API
   - Analysis completes successfully
   - Results show consolidated array data

---

## Rollback Plan

If changes cause issues:

1. **Revert commit:**
   ```bash
   git revert HEAD
   git push origin main
   ```

2. **Redeploy previous version:**
   ```bash
   cd ./code/content-processing-solution-accelerator/infra/scripts
   ./docker-build.sh
   ```

3. **Alternative:** Keep old schemas working by adding fallback in save logic:
   ```python
   # In save_quick_query_schema function
   if is_already_hierarchical:
       # Check if schema needs conversion to consolidated pattern
       if needs_consolidation(schema_fields):
           schema_fields = consolidate_to_array_pattern(schema_fields)
   ```

---

## Success Criteria

✅ **Meta-schema instruction explicitly requires consolidated array pattern**
✅ **NewFieldsToAdd field removed from meta-schema**
✅ **Response processing handles both patterns (legacy and consolidated)**
✅ **Frontend displays appropriate message based on pattern used**
✅ **Saved schemas pass Azure API validation (no MissingProperty errors)**
✅ **Analysis runs successfully with consolidated schema structure**
✅ **Nested fields preview in Quick Adjustments shows array item properties**

---

## Notes

- The consolidation pattern is more efficient for Azure Content Understanding
- Reduces API errors related to missing `properties`/`items` attributes
- Better aligns with reference schema best practices
- Maintains backward compatibility with existing saved schemas (they still work, just not optimal)

---

## Current Progress Status

**✅ COMPLETED:**
- Added hierarchical detection in `save_quick_query_schema()` (preserves AI-enhanced structure AS-IS)
- Created nested fields preview UI in Quick Adjustments (shows all AI-added fields)
- Simplified UI messaging to show only meaningful field counts
- Identified root cause and target architecture pattern
- Documented complete fix plan

**⚠️ IN PROGRESS (~30% complete):**
- Refactoring `generate_enhancement_schema_from_intent()` to use consolidated pattern
  - Started removing `NewFieldsToAdd` meta-field
  - Planning to update AI instruction prompt
  - Not yet implemented new consolidated pattern instruction

**❌ NOT STARTED:**
- Response processing logic updates (remove `NewFieldsToAdd` extraction)
- Frontend service updates (handle new response format)
- End-to-end testing with consolidated pattern
- Database cleanup of broken schemas
- Documentation updates

---

## Next Steps (Tomorrow)

### Priority 1: Complete Meta-Schema Refactoring ⚠️ CRITICAL
**Status:** 30% complete, must finish before other tasks

**Location:** `proMode.py` line ~14000, function `generate_enhancement_schema_from_intent()`

**Work Remaining:**
1. **Remove `NewFieldsToAdd` field completely** from meta-schema definition
   - Delete lines ~12430-12438 that define this field
   - Remove from `fields` dictionary in meta-schema
   
2. **Update `CompleteEnhancedSchema` field description** with detailed consolidation instruction:
   ```python
   "description": """The complete enhanced schema in JSON format following the CONSOLIDATED ARRAY PATTERN:
   
   CRITICAL REQUIREMENTS:
   1. Use SINGLE array field with "method": "generate" for collections (not multiple object fields)
   2. Array items MUST have "properties" defining nested structure
   3. Include a "Category" or type discriminator property in array items
   4. Example: {"AllItems": {"type": "array", "method": "generate", "items": {"type": "object", "properties": {...}}}}
   
   DO NOT create multiple top-level fields with separate generate methods.
   """
   ```

3. **Test meta-schema generation:**
   - Print generated meta-schema to logs
   - Verify `NewFieldsToAdd` is gone
   - Verify `CompleteEnhancedSchema` description has consolidation instruction
   - Confirm meta-schema matches target pattern requirements

### Priority 2: Update Response Processing Logic
**Status:** Not started, depends on Priority 1

**Location:** `proMode.py` line ~12650, function `orchestrated_ai_enhancement()`

**Tasks:**
1. Remove `NewFieldsToAdd` extraction (lines ~12668-12680)
2. Add nested property counting for consolidated arrays:
   ```python
   nested_count = 0
   for field_name, field_def in enhanced_schema_result["fieldSchema"]["fields"].items():
       if field_def.get("type") == "array" and "items" in field_def:
           if "properties" in field_def["items"]:
               nested_count = len(field_def["items"]["properties"])
   ```
3. Update `AIEnhancementResponse` to include:
   - `field_count` (top-level fields)
   - `nested_property_count` (properties in array items)
   - Remove `new_fields_added` field

### Priority 3: Frontend Service Updates
**Status:** Not started, depends on Priority 2

**Location:** `intelligentSchemaEnhancerService.ts` line ~260

**Tasks:**
1. Update enhancement result interface with new fields
2. Change success message to show appropriate text based on pattern:
   - If `nestedPropertyCount > 0`: "Consolidated into X field(s) with Y properties"
   - Otherwise: "X fields ready"
3. Remove references to `newFields` or `new_fields_added` from old response format

### Priority 4: Deployment & Testing
**Status:** Not started, depends on Priority 1-3

**Steps:**
1. Deploy changes: `cd infra/scripts && APP_CONSOLE_LOG_ENABLED=true ./docker-build.sh`
2. Run Quick Query with prompt requiring multiple data types
3. Enhance with AI
4. **Verify in logs:**
   - Meta-schema has consolidation instruction
   - Azure AI response creates single array field
   - Backend correctly identifies consolidated pattern
5. **Verify in UI:**
   - Success message shows consolidated pattern info
   - Nested fields preview displays array item properties
6. Save enhanced schema
7. **Verify saved schema:**
   - Top-level array field has `"method": "generate"`
   - Has `items.properties` with nested structure
   - No multiple fields with separate generate methods
8. Run analysis with saved schema
9. **Verify analysis:**
   - No Azure API validation errors
   - Analysis completes successfully
   - Results show consolidated array data

### Priority 5: Database Cleanup (Low priority)
- Delete broken schemas with multiple fields and separate `method: generate`
- Document migration path for existing schemas
- Can be done after validation in Priority 4

### Priority 6: Documentation (Low priority)
- Update schema architecture docs with consolidated pattern
- Add examples showing correct vs. incorrect structures
- Create migration guide for existing broken schemas

---

## CRITICAL CONTEXT FOR TOMORROW

**DO NOT DEPLOY PARTIAL CHANGES**
The refactoring is ~30% complete. All three priorities (1-3) must be finished before deployment.

**ARCHITECTURE ISSUE:**
- **Current (WRONG):** Multiple fields each with `method: generate` → Azure rejects (missing `properties`)
- **Target (CORRECT):** ONE array field with consolidated items → Azure accepts

**WHY THIS HAPPENED:**
The `generate_enhancement_schema_from_intent()` function creates a meta-schema that instructs Azure AI what to generate. The current meta-schema tells AI to create multiple independent fields. We need to change the instruction to tell AI to create ONE consolidated array field.

**REFERENCE FILE:**
`/afh/projects/.../data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_META_ARRAY_a.json` shows the target pattern. Use this as the model for what AI should generate.

**KEY INSIGHT:**
This is NOT a save logic issue (already fixed). This is NOT a UI display issue (already fixed with nested preview). This IS a schema generation instruction issue - we're telling AI to do the wrong thing in the meta-schema.

**TESTING IS CRITICAL:**
After deploying, must verify the ENTIRE flow:
1. Meta-schema has consolidation instruction
2. Azure AI actually generates consolidated pattern (not multiple fields)
3. Backend correctly processes consolidated response
4. Frontend displays appropriate messaging
5. Saved schema passes Azure API validation
6. Analysis runs successfully

````
