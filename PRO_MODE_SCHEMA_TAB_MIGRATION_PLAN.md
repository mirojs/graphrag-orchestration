# Pro Mode Schema Tab Migration Plan

## 🎯 **Current Situation Analysis**

### **Existing Schema Tabs in Pro Mode:**

1. **`SchemaTab.tsx`** - Currently Active ✅
   - Basic schema management with simple field editing
   - AI extraction functionality (with our fixed Azure OpenAI)
   - Schema upload/import capabilities
   - Currently used in `ProModeContainer.tsx`

2. **`EnhancedSchemaTab.tsx`** - Available but NOT in UI ❌
   - Enhanced schema management with dual storage (Azure + Cosmos DB)
   - More advanced schema operations
   - **NOT currently imported/used in ProModeContainer**

## 🚀 **Migration Strategy: Implement Complete 3-Workflow System**

Instead of deprecating the current schema tab, we should **enhance it with our 3-workflow system** while maintaining backward compatibility.

### **Recommended Approach:**

#### **Option 1: Enhance Current SchemaTab.tsx (RECOMMENDED)**
- ✅ Keep existing functionality working
- ✅ Add our 3 workflows on top of current features
- ✅ Gradual migration with no disruption
- ✅ Users keep their existing schemas and workflows

#### **Option 2: Replace with EnhancedSchemaTab.tsx**
- ❌ Potential disruption to existing users
- ❌ Need to migrate existing functionality
- ❌ More complex migration path

## 📋 **Implementation Plan for Enhanced Current Schema Tab**

### **Phase 1: Add 3-Workflow Tabbed Interface**

Update `SchemaTab.tsx` to include our 3 workflows:

```tsx
// Add to SchemaTab.tsx
const WORKFLOW_TABS = [
  { id: 'current', title: '📋 Current Schema Management' },
  { id: 'ai_extraction', title: '🤖 AI Schema Extraction' },
  { id: 'template_creation', title: '📝 Template Creation' },
  { id: 'training_upload', title: '🎓 Schema Training' }
];
```

### **Phase 2: Integrate Fixed Azure OpenAI**
The current SchemaTab already has AI extraction functionality. We need to:
- ✅ Verify it uses our fixed Azure OpenAI endpoint
- ✅ Enhance the AI extraction with our improved prompts
- ✅ Add document upload capabilities

### **Phase 3: Add Template Creation Workflow**
Add our template-based schema creation:
- ✅ Template gallery with pre-built templates
- ✅ Guided wizard interface
- ✅ Business-focused question flow

### **Phase 4: Add Training Upload Workflow**
Add our LLM training capabilities:
- ✅ Schema template upload for training
- ✅ Training cycle management
- ✅ Progress tracking and status

### **Phase 5: Enhance Hierarchical Editor**
Upgrade the current field editing to our hierarchical table:
- ✅ Tree structure for nested fields
- ✅ Inline editing with validation
- ✅ ACU compliance checking

## 🔧 **Technical Implementation Steps**

### **Step 1: Update ProModeContainer to Support Enhanced Tab**

```tsx
// Option A: Replace current import
import EnhancedProModeSchemaTab from './EnhancedSchemaTab';

// Option B: Keep current and add flag for enhanced version
import ProModeSchemaTab from './SchemaTab';
import EnhancedProModeSchemaTab from './EnhancedSchemaTab';

const useEnhancedSchemaTab = true; // Feature flag
```

### **Step 2: Create Complete Enhanced Schema Tab**

Merge our 3-workflow system with the existing functionality:

```tsx
// EnhancedSchemaTab.tsx - Complete implementation
const EnhancedSchemaTab = () => {
  return (
    <div>
      {/* Keep existing functionality */}
      <div>Current Schema Management</div>
      
      {/* Add our 3 workflows */}
      <TabList>
        <Tab value="current">Current Management</Tab>
        <Tab value="ai_extraction">🤖 AI Extraction</Tab>
        <Tab value="template_creation">📝 Template Creation</Tab>
        <Tab value="training_upload">🎓 Training Upload</Tab>
      </TabList>
      
      {/* Workflow content */}
      {activeTab === 'ai_extraction' && <AIExtractionWorkflow />}
      {activeTab === 'template_creation' && <TemplateCreationWorkflow />}
      {activeTab === 'training_upload' && <TrainingUploadWorkflow />}
    </div>
  );
};
```

### **Step 3: Implement Individual Workflow Components**

Create React components for each workflow:

1. **`AIExtractionWorkflow.tsx`**
   - Document upload zone
   - Fixed Azure OpenAI integration
   - Schema extraction with options

2. **`TemplateCreationWorkflow.tsx`**
   - Template gallery
   - Guided wizard
   - Schema generation

3. **`TrainingUploadWorkflow.tsx`**
   - Schema template upload
   - Training configuration
   - Progress tracking

### **Step 4: Integrate with Fixed Azure OpenAI**

Ensure all AI functionality uses our fixed endpoint:

```tsx
// Use the fixed LLM endpoint
const response = await fetch('/pro-mode/llm/extract-fields', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ messages, temperature: 0.1, max_tokens: 2000 })
});
```

## 🎯 **Benefits of This Approach**

### **User Benefits:**
- ✅ **No Disruption**: Existing functionality remains available
- ✅ **Progressive Enhancement**: Users can adopt new workflows gradually
- ✅ **Familiar Interface**: Builds on existing Pro Mode patterns
- ✅ **Feature Rich**: Combines best of both current and enhanced tabs

### **Technical Benefits:**
- ✅ **Backward Compatibility**: Existing schemas and workflows preserved
- ✅ **Incremental Migration**: Can be deployed in phases
- ✅ **Code Reuse**: Leverages existing Redux stores and services
- ✅ **Testing Strategy**: Can test new workflows alongside current ones

## 🚀 **Migration Timeline**

### **Week 1: Foundation**
- [ ] Update ProModeContainer to use enhanced tab
- [ ] Create tabbed interface structure
- [ ] Migrate current functionality to first tab

### **Week 2: AI Extraction**
- [ ] Implement AI extraction workflow
- [ ] Integrate fixed Azure OpenAI endpoint
- [ ] Add document upload capabilities

### **Week 3: Template Creation**
- [ ] Build template gallery
- [ ] Implement guided wizard
- [ ] Add schema generation logic

### **Week 4: Training Upload**
- [ ] Create training upload interface
- [ ] Implement training cycle management
- [ ] Add progress tracking

### **Week 5: Hierarchical Editor**
- [ ] Enhance field editing with tree structure
- [ ] Add inline validation
- [ ] Implement ACU compliance checking

## 📁 **File Structure After Migration**

```
ProModeComponents/
├── SchemaTab.tsx (deprecated - keep for reference)
├── EnhancedSchemaTab.tsx (main schema tab)
├── SchemaWorkflows/
│   ├── AIExtractionWorkflow.tsx
│   ├── TemplateCreationWorkflow.tsx
│   ├── TrainingUploadWorkflow.tsx
│   └── HierarchicalSchemaEditor.tsx
├── SchemaManagement.tsx (existing - enhanced)
└── SchemaEditorModal.tsx (existing - enhanced)
```

## ✅ **Ready to Implement**

The plan leverages:
- ✅ **Fixed Azure OpenAI authentication** from our previous work
- ✅ **Complete 3-workflow specification** we developed
- ✅ **Existing Pro Mode infrastructure** and Redux stores
- ✅ **Current user workflows** and schema management

**Next Step**: Update ProModeContainer to use EnhancedSchemaTab and begin implementing the 3-workflow tabbed interface!
