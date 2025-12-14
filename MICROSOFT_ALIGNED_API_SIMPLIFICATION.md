# Microsoft-Aligned API Simplification Plan

## 🎯 **Current Problems**

### ❌ **Over-complicated Endpoints**
- 3 schema upload variants (main, optimized, legacy)
- Mixed single/multiple file handling
- Inconsistent PUT/POST patterns
- Duplicate logic across endpoints

### ❌ **Non-Standard Patterns**
- PUT for relationship updates
- Separate endpoints for each operation
- Complex frontend dual-mode handling

## ✅ **Microsoft Repository Standard**

Based on Microsoft's content-processing-solution-accelerator repository analysis:

### **1. Single Upload Endpoint Pattern**
```python
# ✅ UNIFIED - Always handles multiple files (1 or more)
@router.post("/files", summary="Upload files")
async def upload_files(
    files: List[UploadFile] = File(...),
    file_type: str = Form(...),  # 'input', 'reference', 'schema'
    app_config: AppConfiguration = Depends(get_app_config)
):
    """Single endpoint for all file uploads - Microsoft aligned pattern."""
```

### **2. RESTful Resource Management**
```python
# ✅ STANDARD REST - Resource-based endpoints
@router.get("/files")           # List all files
@router.post("/files")          # Upload files
@router.get("/files/{id}")      # Get file details  
@router.delete("/files/{id}")   # Delete file
@router.patch("/files/{id}")    # Update file metadata
```

### **3. Simplified Schema Management**
```python
# ✅ UNIFIED - Single schema endpoint
@router.post("/schemas")        # Upload schemas (always multiple)
@router.get("/schemas")         # List schemas
@router.get("/schemas/{id}")    # Get schema
@router.delete("/schemas/{id}") # Delete schema
@router.patch("/schemas/{id}")  # Update schema
```

## 🚀 **Implementation Plan**

### **Phase 1: Backend Simplification**

#### **1.1 Replace Multiple Schema Endpoints**
```python
# REMOVE:
# - /pro-mode/schemas/upload
# - /pro-mode/schemas/upload-optimized  
# - /pro-mode/schemas/upload-legacy

# REPLACE WITH:
@router.post("/schemas")
async def upload_schemas(
    files: List[UploadFile] = File(...),
    app_config: AppConfiguration = Depends(get_app_config)
):
    """Upload multiple schema files - Microsoft aligned."""
    # Always handle multiple files (even if just 1)
    # Use optimized blob+DB pattern by default
    # Eliminate legacy patterns
```

#### **1.2 Unify File Upload Logic**
```python
# REMOVE:
# - /pro-mode/input-files
# - /pro-mode/reference-files

# REPLACE WITH:
@router.post("/files")
async def upload_files(
    files: List[UploadFile] = File(...),
    file_type: Literal["input", "reference"] = Form(...),
    app_config: AppConfiguration = Depends(get_app_config)
):
    """Upload multiple files with type classification."""
    # Single logic handles both input and reference files
    # Type parameter determines storage container
```

#### **1.3 Eliminate PUT Complexity**
```python
# REMOVE PUT endpoints:
# - PUT /pro-mode/reference-files/{id}/relationship
# - PUT /pro-mode/schemas/{id}/fields/{field}

# REPLACE WITH standard PATCH:
@router.patch("/files/{file_id}")
async def update_file(
    file_id: str,
    updates: FileUpdateRequest,
    app_config: AppConfiguration = Depends(get_app_config)
):
    """Update file metadata using standard REST pattern."""

@router.patch("/schemas/{schema_id}")  
async def update_schema(
    schema_id: str,
    updates: SchemaUpdateRequest,
    app_config: AppConfiguration = Depends(get_app_config)
):
    """Update schema using standard REST pattern."""
```

### **Phase 2: Frontend Simplification**

#### **2.1 Unified Upload Service**
```typescript
// REMOVE multiple upload functions:
// - uploadFiles()
// - uploadSchemas() 
// - uploadSchema()

// REPLACE WITH:
export const uploadFiles = async (
  files: File[], 
  fileType: 'input' | 'reference' | 'schema'
) => {
  const formData = new FormData();
  files.forEach(file => formData.append('files', file));
  formData.append('file_type', fileType);
  
  return httpUtility.upload('/files', formData);
};
```

#### **2.2 Single Upload Modal Component**
```typescript
// REMOVE separate modals:
// - ProModeUploadFilesModal
// - ProModeUploadSchemasModal

// REPLACE WITH:
<UnifiedUploadModal 
  fileType="input" | "reference" | "schema"
  onUpload={handleUpload}
  onClose={handleClose}
/>
```

### **Phase 3: Microsoft Compliance**

#### **3.1 Follow Microsoft REST Conventions**
- Use standard HTTP methods (GET, POST, PATCH, DELETE)
- Resource-based URLs (/files, /schemas, not /upload-files)
- Consistent response formats
- Proper HTTP status codes

#### **3.2 Eliminate Non-Standard Patterns**
- Remove PUT for updates (use PATCH)
- Remove custom relationship endpoints  
- Remove optimized/legacy variants
- Standardize error responses

#### **3.3 Align with Microsoft Repository Structure**
- Single upload logic per resource type
- Consistent file handling patterns
- Standard validation and error handling
- Unified storage and retrieval patterns

## 📊 **Benefits of Simplification**

### **✅ Reduced Complexity**
- **3 schema endpoints → 1 endpoint**
- **2 file upload endpoints → 1 endpoint** 
- **Multiple PUT patterns → Standard PATCH**
- **Dual frontend logic → Single unified logic**

### **✅ Microsoft Alignment**
- Follows standard REST conventions
- Matches Microsoft repository patterns
- Consistent with Azure API guidelines
- Standard HTTP methods and status codes

### **✅ Maintainability**
- Single code path for each operation
- Consistent validation and error handling
- Easier testing and debugging
- Reduced frontend complexity

### **✅ Performance**
- Always uses optimized blob+DB pattern
- Eliminates legacy code paths
- Consistent caching and storage
- Better error recovery

## 🔧 **Migration Strategy**

### **1. Backward Compatibility**
```python
# Keep old endpoints as aliases during transition
@router.post("/pro-mode/schemas/upload", deprecated=True)
async def upload_schemas_legacy(files: List[UploadFile] = File(...)):
    """Deprecated: Use POST /schemas instead."""
    return await upload_schemas(files, app_config)
```

### **2. Phased Rollout**
1. **Week 1**: Implement new unified endpoints
2. **Week 2**: Update frontend to use new endpoints
3. **Week 3**: Test compatibility and performance
4. **Week 4**: Remove deprecated endpoints

### **3. Documentation Update**
- Update API documentation
- Provide migration guide
- Update frontend components
- Test all scenarios

This approach eliminates unnecessary complexity while maintaining full Microsoft repository alignment! 🎉
