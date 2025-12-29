# 7D Integration Implementation Plan

**Date**: November 11, 2025  
**Goal**: Integrate 7D enhancement into existing schema save workflow  
**Status**: Planning Phase

---

## Current State Analysis

### Existing Schema Save Workflow

**Frontend Flow:**
```
User executes Quick Query
  ↓
Clicks "Save as Schema"
  ↓
Quick Query re-executes with includeSchemaGeneration=true
  ↓
Backend returns GeneratedSchema (basic)
  ↓
SchemaReviewDialog shows editable fields
  ↓
User clicks Save
  ↓
PredictionTab.tsx converts to ProModeSchema format
  ↓
Calls createSchema() Redux action
  ↓
POST /pro-mode/schemas/create
  ↓
Schema saved to database WITHOUT 7D enhancement
```

**Key Files:**
- Frontend: `PredictionTab.tsx`, `SchemaReviewDialog.tsx`, `schemaActions.ts`
- Backend: `query_schema_generator.py`, schema create endpoint
- Result: Schema saved with basic descriptions, no 7D optimization

---

## Problem Statement

Current workflow generates **basic schemas**:
```json
{
  "VendorName": {
    "type": "string",
    "description": "Vendor name from document"
  }
}
```

Need **7D-enhanced schemas** for production use:
```json
{
  "VendorName": {
    "type": "string",
    "description": "
      [D1: STRUCTURAL] Use standardized naming for table display...
      [D2: DETAILED] Extract vendor name. Example: 'Contoso LLC'...
      [D3: CONSISTENCY] Same format across all documents...
      [D7: BEHAVIORAL] Extract from header or signature block...
    "
  }
}
```

---

## Implementation Tasks

### TASK #1: Quick Query Schema Generation & 7D Enhancement

#### 1.1 Create 7D Enhancement Utility

**File**: `backend/utils/schema_7d_enhancer.py` (NEW)

**Purpose**: Add 7D descriptions to generated schemas

```python
"""
7D Schema Enhancer - Adds production-quality 7D descriptions to basic schemas
"""

from typing import Dict, Any, List


class Schema7DEnhancer:
    """Enhances basic schemas with 7D descriptions for production use"""
    
    def __init__(self):
        # 7D template for different field types
        self.templates = {
            "array_generate": self._get_array_7d_template,
            "object_generate": self._get_object_7d_template,
            "string": self._get_string_7d_template,
            "number": self._get_number_7d_template,
            "date": self._get_date_7d_template
        }
    
    def enhance_schema(
        self, 
        basic_schema: Dict[str, Any],
        schema_context: str = "general extraction"
    ) -> Dict[str, Any]:
        """
        Enhance basic schema with 7D descriptions
        
        Args:
            basic_schema: Schema from Quick Query generation
            schema_context: Analysis type (comparison, extraction, verification)
            
        Returns:
            Enhanced schema with full 7D descriptions
        """
        enhanced = basic_schema.copy()
        
        if "fieldSchema" in enhanced and "fields" in enhanced["fieldSchema"]:
            fields = enhanced["fieldSchema"]["fields"]
            for field_name, field_def in fields.items():
                fields[field_name] = self._enhance_field(
                    field_name, 
                    field_def, 
                    schema_context
                )
        
        return enhanced
    
    def _enhance_field(
        self, 
        field_name: str, 
        field_def: Dict[str, Any],
        context: str
    ) -> Dict[str, Any]:
        """Enhance a single field with appropriate 7D template"""
        
        field_type = field_def.get("type", "string")
        has_method_generate = field_def.get("method") == "generate"
        
        # Determine template key
        if has_method_generate and field_type == "array":
            template_key = "array_generate"
        elif has_method_generate and field_type == "object":
            template_key = "object_generate"
        elif field_type in ["date", "datetime"]:
            template_key = "date"
        elif field_type in ["number", "integer", "float"]:
            template_key = "number"
        else:
            template_key = "string"
        
        # Get template function
        template_fn = self.templates.get(template_key)
        if not template_fn:
            return field_def
        
        # Get base description
        base_description = field_def.get("description", f"Extract {field_name}")
        
        # Apply 7D template
        enhanced_def = field_def.copy()
        enhanced_def["description"] = template_fn(
            field_name, 
            base_description, 
            context
        )
        
        return enhanced_def
    
    def _get_array_7d_template(
        self, 
        field_name: str, 
        base_desc: str,
        context: str
    ) -> str:
        """7D template for arrays with method=generate"""
        
        return f"""
[D1: STRUCTURAL ORGANIZATION]
CRITICAL: Generate ALL items in ONE unified analysis.
{base_desc}
Do NOT create separate arrays for different categories.

[D2: DETAILED DESCRIPTIONS]
For each item provide:
- Specific values with examples
- Clear formatting specifications
- Business context explaining importance

[D3: CONSISTENCY REQUIREMENTS]
IMPORTANT: Maintain consistency across ALL items:
- Use same format for values (e.g., '$50,000' everywhere, not '$50K' or '50000')
- Generate ENTIRE array in ONE pass to ensure global understanding
- Same date format throughout (YYYY-MM-DD for sortable tables)

[D4: SEVERITY/CLASSIFICATION]
Include 'Category' field to classify each item (where applicable).
Add 'Severity' or 'Priority' with clear criteria:
- Critical: High financial impact or legal risk
- High: Significant business impact
- Medium: Minor discrepancy
- Low: Formatting or non-material difference

[D5: RELATIONSHIP MAPPING]
Add 'RelatedCategories' or 'RelatedFields' array:
- List other fields/items affected
- Helps understand cascading impacts and dependencies

[D6: DOCUMENT PROVENANCE]
Include source tracking for traceability:
- SourceDocument: Original filename (strip UUID prefixes)
- SourcePage: Page number where found (1-based)
- Enables audit trail from result to source

[D7: BEHAVIORAL INSTRUCTIONS]
Generate this array AFTER analyzing all relevant content to ensure:
- Global understanding of all items
- Proper cross-referencing between items
- Consistent value representation throughout
"""
    
    def _get_object_7d_template(
        self, 
        field_name: str, 
        base_desc: str,
        context: str
    ) -> str:
        """7D template for objects with method=generate (summaries)"""
        
        return f"""
[D7: SUMMARY ANALYTICS]
{base_desc}

Generate AFTER analyzing all related data.
Provide comprehensive analytics:
- TotalCount: Number of items found
- CategoryBreakdown: Counts per category/type
- OverallStatus or RiskLevel: High-level assessment
- KeyFindings: 1-2 sentence summary of most important insights

This summary enables quick understanding without reviewing all details.
"""
    
    def _get_string_7d_template(
        self, 
        field_name: str, 
        base_desc: str,
        context: str
    ) -> str:
        """7D template for string fields"""
        
        # Infer field purpose from name
        is_name = any(x in field_name.lower() for x in ["name", "vendor", "customer", "company"])
        is_id = any(x in field_name.lower() for x in ["id", "number", "reference"])
        
        template = f"{base_desc}\n\n"
        
        if is_name:
            template += """Format: Full legal name as appears in document.
Example: 'Contoso Lifts LLC'
Validation: Must be non-empty text.
Consistency: Use same capitalization across all occurrences."""
        
        elif is_id:
            template += """Format: Preserve original format with prefixes/suffixes.
Example: 'INV-2024-001' or 'PO-12345'
Validation: Alphanumeric string.
Consistency: Exact match for cross-document linking."""
        
        else:
            template += f"""Format: {base_desc.lower()}.
Validation: Must be non-empty text.
Consistency: Use standardized format for table display."""
        
        return template
    
    def _get_number_7d_template(
        self, 
        field_name: str, 
        base_desc: str,
        context: str
    ) -> str:
        """7D template for number fields"""
        
        is_currency = any(x in field_name.lower() for x in ["amount", "total", "price", "cost", "payment"])
        
        template = f"{base_desc}\n\n"
        
        if is_currency:
            template += """Format: Numeric value with 2 decimal places (e.g., 50000.00).
Display: Format as '$50,000.00' for presentation.
Validation: Must be positive number.
Consistency: Use same decimal precision across all amounts.
Relationships: Verify sum of line items matches totals where applicable."""
        else:
            template += """Format: Numeric value.
Validation: Must be valid number.
Consistency: Use same precision across all occurrences."""
        
        return template
    
    def _get_date_7d_template(
        self, 
        field_name: str, 
        base_desc: str,
        context: str
    ) -> str:
        """7D template for date fields"""
        
        return f"""{base_desc}

Format: YYYY-MM-DD (ISO 8601 standard for sortable tables).
Example: '2024-01-15'
Validation: Must be valid date.
Consistency: Use same format across all date fields.
Display: Can be reformatted for presentation (e.g., 'January 15, 2024').
Comparison: Sortable format enables timeline analysis."""


# Singleton instance
_enhancer = Schema7DEnhancer()

def enhance_schema_with_7d(
    basic_schema: Dict[str, Any],
    schema_context: str = "general extraction"
) -> Dict[str, Any]:
    """
    Convenience function to enhance schema with 7D descriptions
    
    Usage:
        enhanced = enhance_schema_with_7d(basic_schema, "invoice-contract comparison")
    """
    return _enhancer.enhance_schema(basic_schema, schema_context)
```

**Status**: To be created

---

#### 1.2 Update Backend Schema Create Endpoint

**File**: Backend schema creation route (find and update)

**Change**: Add 7D enhancement before saving

```python
@router.post("/pro-mode/schemas/create")
async def create_schema(schema_data: Dict[str, Any]):
    """
    Create new schema with optional 7D enhancement
    """
    # Check if 7D enhancement requested (default: True for schemas from Quick Query)
    apply_7d = schema_data.get("apply7d", True)
    
    if apply_7d:
        from backend.utils.schema_7d_enhancer import enhance_schema_with_7d
        
        # Get context from schema metadata
        schema_context = schema_data.get("context", "general extraction")
        
        # Enhance with 7D
        schema_data = enhance_schema_with_7d(schema_data, schema_context)
        
        # Add metadata
        schema_data["enhanced_with_7d"] = True
        schema_data["enhancement_date"] = datetime.now().isoformat()
    
    # Save to database
    saved_schema = await save_schema_to_db(schema_data)
    
    return {
        "success": True,
        "message": "Schema created" + (" with 7D enhancement" if apply_7d else ""),
        "data": saved_schema
    }
```

**Status**: To be updated

---

#### 1.3 Update Frontend Schema Save Logic

**File**: `PredictionTab.tsx`

**Change**: Pass apply7d flag when saving

```typescript
const handleSchemaSave = async (editedSchema: GeneratedSchema) => {
  try {
    setIsSavingToLibrary(true);
    
    // Convert to ProModeSchema format
    const schemaToSave: Partial<ProModeSchema> = {
      schemaId: `quickquery-${Date.now()}`,
      schemaName: editedSchema.schemaName,
      schemaDescription: editedSchema.schemaDescription,
      fieldSchema: {
        name: editedSchema.schemaName,
        description: editedSchema.schemaDescription,
        fields: editedSchema.fields
      },
      createdAt: new Date().toISOString(),
      
      // NEW: Request 7D enhancement
      apply7d: true,  // ✅ Add this flag
      context: lastExecutedPrompt || "Quick Query extraction"  // ✅ Provide context
    };
    
    // Save to library
    await dispatch(createSchema(schemaToSave)).unwrap();
    
    toast.success('Schema saved to library with 7D enhancement');
    
  } catch (error) {
    toast.error('Failed to save schema');
  }
};
```

**Status**: To be updated

---

### TASK #2: Apply 7D to Existing Schemas

#### 2.1 Create Batch Enhancement Script

**File**: `backend/migrations/enhance_existing_schemas_with_7d.py` (NEW)

**Purpose**: Batch update all existing schemas

```python
"""
Migration Script: Add 7D Descriptions to Existing Schemas

Updates all schemas in database and data/ folder to include 7D enhancement.
Creates backups before modification.
"""

import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

# Import the enhancer
import sys
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from utils.schema_7d_enhancer import enhance_schema_with_7d


class SchemaEnhancementMigration:
    """Migrate existing schemas to include 7D descriptions"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.backup_dir = self.data_dir / f"backups_pre_7d_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.backup_dir.mkdir(exist_ok=True)
        
        self.stats = {
            "total_schemas": 0,
            "enhanced": 0,
            "skipped": 0,
            "errors": []
        }
    
    def run(self):
        """Run the migration"""
        print("="*80)
        print("7D Schema Enhancement Migration")
        print("="*80)
        print(f"Data directory: {self.data_dir}")
        print(f"Backup directory: {self.backup_dir}")
        print()
        
        # Find all schema JSON files
        schema_files = list(self.data_dir.glob("**/*.json"))
        self.stats["total_schemas"] = len(schema_files)
        
        print(f"Found {len(schema_files)} schema files")
        print()
        
        # Process each file
        for schema_file in schema_files:
            self.process_schema_file(schema_file)
        
        # Print summary
        self.print_summary()
    
    def process_schema_file(self, file_path: Path):
        """Process a single schema file"""
        
        print(f"Processing: {file_path.name}")
        
        try:
            # Load schema
            with open(file_path, 'r') as f:
                schema = json.load(f)
            
            # Check if already enhanced
            if schema.get("enhanced_with_7d"):
                print(f"  ⏭️  Already enhanced - skipping")
                self.stats["skipped"] += 1
                return
            
            # Create backup
            backup_path = self.backup_dir / file_path.name
            shutil.copy2(file_path, backup_path)
            print(f"  💾 Backup created: {backup_path.name}")
            
            # Enhance with 7D
            enhanced = enhance_schema_with_7d(schema, context="production schema")
            enhanced["enhanced_with_7d"] = True
            enhanced["enhancement_date"] = datetime.now().isoformat()
            
            # Save enhanced version
            with open(file_path, 'w') as f:
                json.dump(enhanced, f, indent=2)
            
            print(f"  ✅ Enhanced with 7D")
            self.stats["enhanced"] += 1
            
        except Exception as e:
            error_msg = f"Error processing {file_path.name}: {str(e)}"
            print(f"  ❌ {error_msg}")
            self.stats["errors"].append(error_msg)
    
    def print_summary(self):
        """Print migration summary"""
        print()
        print("="*80)
        print("Migration Summary")
        print("="*80)
        print(f"Total schemas: {self.stats['total_schemas']}")
        print(f"Enhanced: {self.stats['enhanced']}")
        print(f"Skipped (already enhanced): {self.stats['skipped']}")
        print(f"Errors: {len(self.stats['errors'])}")
        print()
        
        if self.stats['errors']:
            print("Errors:")
            for error in self.stats['errors']:
                print(f"  - {error}")
            print()
        
        print(f"Backups saved to: {self.backup_dir}")
        print("="*80)


if __name__ == "__main__":
    migration = SchemaEnhancementMigration()
    migration.run()
```

**Usage**:
```bash
cd backend
python migrations/enhance_existing_schemas_with_7d.py
```

**Status**: To be created

---

#### 2.2 Update Schema Editor UI

**File**: Frontend schema editor component (find and update)

**Change**: Add 7D enhancement toggle

```typescript
// In schema editor form
<Checkbox
  label="Apply 7D Enhancement (recommended for production schemas)"
  checked={apply7d}
  onChange={(_, data) => setApply7d(data.checked)}
/>

<InfoLabel
  info="7D enhancement adds production-quality descriptions including:
    - Structural organization
    - Detailed examples and formatting
    - Consistency requirements
    - Classification and severity levels
    - Relationship mapping
    - Document provenance
    - Behavioral instructions"
>
  Learn more about 7D enhancement
</InfoLabel>
```

**Status**: To be added to schema editor

---

## Implementation Order

### Phase 1: Core Utility (Day 1)
1. ✅ Create `schema_7d_enhancer.py`
2. ✅ Write unit tests
3. ✅ Test with sample schemas

### Phase 2: Quick Query Integration (Day 2)
4. ✅ Update backend schema create endpoint
5. ✅ Update `PredictionTab.tsx` to pass apply7d flag
6. ✅ Test end-to-end: Quick Query → Save → Verify 7D in saved schema

### Phase 3: Existing Schema Enhancement (Day 3)
7. ✅ Create migration script
8. ✅ Test on sample schemas
9. ✅ Run migration on all schemas
10. ✅ Verify enhanced schemas work correctly

### Phase 4: UI Updates (Day 4)
11. ✅ Add 7D toggle to schema editor
12. ✅ Update schema list to show 7D status
13. ✅ Add 7D info tooltips

---

## Testing Plan

### Unit Tests
- Test 7D templates for each field type
- Test enhancement logic
- Test migration script

### Integration Tests
- Quick Query → Save → Verify 7D descriptions
- Manual schema create with 7D toggle
- Schema update preserves 7D enhancement

### E2E Tests
- User journey: Query → Save → Use schema → Verify results
- Batch migration: Before/after comparison

---

## Rollback Plan

If issues occur:
1. Backups created in `data/backups_pre_7d_YYYYMMDD_HHMMSS/`
2. Restore original schemas from backup
3. Disable 7D enhancement flag in schema create endpoint
4. Investigate and fix issues

---

## Success Criteria

✅ All new schemas from Quick Query have 7D descriptions  
✅ All existing schemas enhanced with 7D (with backups)  
✅ No breaking changes to schema functionality  
✅ UI shows 7D status clearly  
✅ Performance impact < 100ms per schema save  
✅ All tests passing  

---

## Next Steps

**Ready to start?**

Option A: Start with Phase 1 - Create `schema_7d_enhancer.py`  
Option B: Review and approve plan first  
Option C: Modify plan based on feedback  

Which would you like to do?
