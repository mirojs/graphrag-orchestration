# Enhanced Schema and File Selection System

## Overview
This system allows users to:
1. Select one schema in the Schema tab as the "active schema"
2. Select multiple input files and reference files in the Files tab
3. Have the Prediction tab's analysis API automatically be aware of these selections
4. Provide visual feedback for selected items

## Implementation Strategy

### 1. Enhanced Redux State Management

Add a new slice to manage the analysis context:

```typescript
interface AnalysisContextState {
  activeSchemaId: string | null;
  selectedInputFiles: string[];
  selectedReferenceFiles: string[];
  analysisConfiguration: {
    schemaId: string | null;
    inputFileIds: string[];
    referenceFileIds: string[];
    isValid: boolean;
    validationErrors: string[];
  };
}
```

### 2. UI Design Patterns

#### Schema Tab Selection
- Use radio button selection mode for single schema selection
- Visual indicator showing which schema is "active" for analysis
- Clear "Use for Analysis" action button

#### Files Tab Selection
- Separate sections for Input Files and Reference Files
- Checkbox selection for multiple files
- Visual distinction between input and reference files
- Selection counter and management controls

#### Prediction Tab Integration
- Display current analysis configuration at the top
- Show active schema and selected files count
- Enable/disable analysis based on valid selection
- Real-time configuration updates

### 3. Best Practices for UI

1. **Clear Visual Hierarchy**
   - Use consistent selection patterns across tabs
   - Color coding for different file types
   - Status indicators for selection state

2. **User Feedback**
   - Real-time validation messages
   - Selection summaries
   - Progress indicators for analysis

3. **Consistent Actions**
   - Unified selection/deselection controls
   - Consistent naming conventions
   - Similar interaction patterns

## Implementation Steps

1. Enhance Redux store with analysis context
2. Update Schema tab for single selection
3. Update Files tab for multi-selection with categories
4. Update Prediction tab to use analysis context
5. Add cross-tab state synchronization
6. Implement validation and error handling
