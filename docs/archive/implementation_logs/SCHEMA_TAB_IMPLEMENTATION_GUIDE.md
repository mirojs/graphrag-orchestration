# Schema Tab Interface Implementation Guide

## Overview

This document provides a complete implementation guide for the dual-schema creation interface as requested. The interface features:

1. **AI Schema Extraction**: Upload document → AI extracts schema → Hierarchical table editing → Save to schema list
2. **Template-Based Schema Creation**: Select template → Answer guided questions → Generate schema → Hierarchical table editing → Save to schema list

## Interface Architecture

### Layout Structure

```
┌─────────────────────────────────────────────────────────────┐
│                     Schema Library                          │
│  [Schema Grid with all saved schemas + action buttons]     │
├─────────────────────┬───────────────────────────────────────┤
│   AI Extraction     │    Template Creation                  │
│                     │                                       │
│ • Upload Document   │ • Template Selection Cards           │
│ • Extraction Options│ • Guided Question Wizard             │
│ • Progress Indicator│ • Schema Preview                      │
│ • Extract Button    │ • Create Button                       │
├─────────────────────┴───────────────────────────────────────┤
│                Hierarchical Schema Editor                   │
│                                                             │
│ • Tree Grid with editable fields                           │
│ • Field details panel                                       │
│ • Validation indicators                                     │
│ • Save section with naming                                  │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Components

### 1. Schema Library Section (Top Panel)
- **Data Grid**: Shows all saved schemas with metadata
- **Columns**: Name, Type (AI/Template/Custom), Created Date, Field Count, Status, Actions
- **Actions**: Use for Analysis, Duplicate, Export, Delete
- **Selection**: Single-select to load schema for analysis

### 2. AI Schema Extraction Section (Left Panel)
- **File Upload**: Accepts PDF, DOCX, TXT, JSON
- **Extraction Options**: 
  - Mode: Automatic/Guided/Template-Assisted
  - Focus: Inconsistencies/Data/Validation/Compliance
  - Detail Level: Basic/Detailed/Comprehensive
- **Progress Indicator**: Shows 4-step extraction process
- **Output**: Feeds directly into hierarchical table editor

### 3. Template-Based Creation Section (Right Panel)
- **Template Cards**: Pre-built templates with complexity indicators
  - Invoice-Contract Verification
  - Expense Report Validation
  - Contract Data Extraction
  - Custom Template (guided questions)
- **Wizard Interface**: Step-by-step guided questions
- **Template Preview**: JSON preview of generated schema
- **Output**: Feeds directly into hierarchical table editor

### 4. Hierarchical Schema Editor Section (Bottom Panel)
- **Tree Grid**: Expandable/collapsible hierarchical table
- **Editable Fields**: 
  - Field Name (validated)
  - Type (dropdown: string/number/boolean/array/object)
  - Description (textarea)
  - Method (dropdown: extract/generate/classify)
  - Required (checkbox)
- **Field Details Panel**: Additional properties and validation rules
- **Azure Content Understanding Compliance**: Real-time validation
- **Save Section**: Name, description, tags input with save actions

## Integration with Existing Systems

### Connection to Current Codebase

1. **AI Extraction Integration**:
   ```python
   # Uses existing proMode.py AI extraction
   from proMode import extract_fields_with_llm
   
   # Connects to Azure OpenAI authentication
   from azure_openai import get_openai_client
   ```

2. **Template System Integration**:
   ```python
   # Uses existing template system
   from user_intention_template_system import UserIntentionTemplate
   from dual_way_schema_verification_training import SchemaGenerator
   ```

3. **Schema Validation Integration**:
   ```python
   # Uses existing validation systems
   from production_ready_iteration_logic import AzureContentUnderstandingValidator
   ```

### Workflow Implementation

#### AI Extraction Workflow
```python
def ai_extraction_workflow(uploaded_file, options):
    # Step 1: Document upload handled by UI
    
    # Step 2: Configure extraction options
    extraction_config = {
        'mode': options['extraction_mode'],
        'focus': options['analysis_focus'],
        'detail_level': options['output_detail']
    }
    
    # Step 3: AI processing using existing system
    extraction_result = extract_fields_with_llm(uploaded_file, extraction_config)
    
    # Step 4: Convert to hierarchical table format
    table_data = HierarchicalTableEditor().load_schema_into_table(extraction_result)
    
    # Step 5: Enable editing in UI
    return table_data
```

#### Template Creation Workflow
```python
def template_creation_workflow(template_id, user_answers):
    # Step 1: Template selection handled by UI
    
    # Step 2: Guided questions answered by user
    
    # Step 3: Generate schema from template
    template_creator = TemplateSchemaCreator()
    generation_result = template_creator.create_schema_from_template(template_id, user_answers)
    
    # Step 4: Convert to hierarchical table format
    table_data = HierarchicalTableEditor().load_schema_into_table(generation_result['generated_schema'])
    
    # Step 5: Enable editing in UI
    return table_data
```

## User Experience Flow

### Common User Journey

1. **User opens Schema Tab**: Sees existing schemas in the library grid
2. **Chooses creation method**: Either AI extraction or template-based
3. **Provides input**: Either uploads document or answers template questions
4. **Reviews generated schema**: In hierarchical table format with full editing capability
5. **Edits and refines**: Makes changes using inline editing or details panel
6. **Validates compliance**: Real-time Azure Content Understanding validation
7. **Saves with metadata**: Provides name, description, tags
8. **Schema appears in library**: Available for selection and analysis use

### Key UI/UX Features

- **Unified editing experience**: Both AI-extracted and template-generated schemas use the same hierarchical table editor
- **Real-time validation**: Immediate feedback on field changes and ACU compliance
- **Visual hierarchy**: Clear parent-child relationships with expand/collapse
- **Contextual help**: Tooltips and guidance for complex operations
- **Undo/redo**: Edit history for safe experimentation
- **Auto-save**: Prevents data loss during editing sessions

## Technical Implementation Details

### Frontend Components

1. **SchemaTabInterface**: Main orchestrator class
2. **HierarchicalTableEditor**: Tree grid with editing capabilities
3. **SchemaListManager**: CRUD operations for schema library
4. **AISchemaExtractor**: Document processing and AI extraction
5. **TemplateSchemaCreator**: Template-based schema generation

### Data Flow

```
Document Upload → AI Extraction → Schema Object → Hierarchical Table → User Edits → Validation → Save → Schema Library
     OR
Template Selection → Guided Questions → Schema Generation → Hierarchical Table → User Edits → Validation → Save → Schema Library
```

### State Management

- **Current Editing Schema**: Tracks schema being edited
- **Edit History**: Maintains undo/redo capability
- **Validation State**: Real-time validation results
- **UI State**: Panel visibility, selection state, progress indicators

## Benefits of This Approach

1. **Unified Interface**: Single consistent editing experience regardless of schema source
2. **User Accessibility**: Template system makes schema creation accessible to non-technical users
3. **AI Augmentation**: Leverages AI for intelligent field extraction from documents
4. **Quality Assurance**: Built-in validation ensures Azure Content Understanding compliance
5. **Flexibility**: Full editing capability allows fine-tuning after initial generation
6. **Organization**: Schema library provides centralized management and reuse

## Next Steps for Implementation

1. **Frontend Development**: Implement React/Vue components based on this specification
2. **Backend Integration**: Connect to existing AI extraction and template systems
3. **Database Schema**: Design storage for schema library with metadata
4. **API Endpoints**: Create REST/GraphQL APIs for CRUD operations
5. **Testing**: Comprehensive testing of both workflows and editing capabilities
6. **Documentation**: User guides for both technical and non-technical users

This implementation provides the exact dual-schema creation system you requested, with hierarchical table editing as the common editing interface for both AI-extracted and template-generated schemas.
