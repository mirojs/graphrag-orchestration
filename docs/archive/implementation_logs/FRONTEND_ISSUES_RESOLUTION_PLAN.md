# 🚨 Frontend Issues Resolution Plan

## **Current Issues Analysis**

### **1. "Something went wrong" errors on file uploads**
- **Root Cause**: Frontend can't read error details due to missing CORS headers
- **Status**: ✅ Backend fixes completed, ⏳ Deployment needed

### **2. "Fetch API cannot load due to access control checks"**
- **Root Cause**: CORS headers missing in error responses
- **Status**: ✅ Backend fixes completed, ⏳ Deployment needed

### **3. Schema upload CORS issues**
- **Root Cause**: Schema endpoint was still using HTTPException
- **Status**: ✅ Just fixed with CORS responses

## **🎯 Resolution Steps**

### **Step 1: Deploy Updated Backend** ⚠️ **CRITICAL**

The backend changes need to be deployed to Azure Container Apps:

```bash
# Navigate to API directory
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/src/ContentProcessorAPI

# Build and deploy to Azure Container Apps
# Replace with your actual deployment commands
az containerapp up --name ca-cps-xh5lwkfq3vfm-api --resource-group <your-resource-group>

# OR if using Docker:
docker build -t promode-api .
docker tag promode-api <your-registry>/promode-api:latest
docker push <your-registry>/promode-api:latest
az containerapp update --name ca-cps-xh5lwkfq3vfm-api --image <your-registry>/promode-api:latest
```

### **Step 2: Verify Backend Deployment**

Test the updated endpoints:

```bash
# Test reference files endpoint
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files" \
  -F "files=" \
  -v

# Expected: Should see CORS headers in response:
# Access-Control-Allow-Origin: *
# Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
# Access-Control-Allow-Headers: Authorization, Content-Type, *

# Test schema upload endpoint
curl -X POST "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/schemas/upload" \
  -F "files=" \
  -v
```

### **Step 3: Update Frontend Error Handling**

Create improved error handling for the frontend:

```javascript
// Enhanced error handling for Pro Mode uploads
class ProModeUploadHandler {
    static async uploadFiles(endpoint, files, options = {}) {
        try {
            const formData = new FormData();
            
            // Validate files before sending
            if (!files || files.length === 0) {
                throw new Error('Please select files to upload');
            }
            
            if (files.length > 10) {
                throw new Error('Maximum 10 files allowed');
            }
            
            // Add files to form data
            Array.from(files).forEach(file => {
                if (!file.name) {
                    throw new Error('All files must have names');
                }
                if (file.size === 0) {
                    throw new Error(`File "${file.name}" is empty`);
                }
                if (file.size > 50 * 1024 * 1024) { // 50MB
                    throw new Error(`File "${file.name}" exceeds 50MB limit`);
                }
                formData.append('files', file);
            });
            
            const response = await fetch(endpoint, {
                method: 'POST',
                body: formData,
                headers: {
                    // Don't set Content-Type - let browser set it with boundary
                }
            });
            
            if (!response.ok) {
                // Try to parse error response
                let errorData;
                try {
                    errorData = await response.json();
                } catch (e) {
                    throw new Error(`Upload failed with status ${response.status}`);
                }
                
                // Handle structured error responses
                const message = this.getErrorMessage(errorData);
                throw new Error(message);
            }
            
            return await response.json();
            
        } catch (error) {
            console.error('Upload error:', error);
            throw error;
        }
    }
    
    static getErrorMessage(errorData) {
        if (!errorData) return 'Upload failed - unknown error';
        
        // Handle new structured error format
        if (errorData.code) {
            switch (errorData.code) {
                case 'NO_FILES':
                    return 'Please select files to upload';
                case 'TOO_MANY_FILES':
                    return 'Maximum 10 files allowed';
                case 'FILE_TOO_LARGE':
                    return 'One or more files exceed the size limit';
                case 'MISSING_FILENAME':
                    return 'All files must have names';
                case 'EMPTY_FILE':
                    return 'Empty files are not allowed';
                case 'INVALID_FILE_TYPE':
                    return 'Invalid file type - only specific formats allowed';
                case 'UPLOAD_ERROR':
                    return 'Upload failed - please try again';
                case 'DATABASE_ERROR':
                    return 'Database error - please contact support';
                case 'NETWORK_ERROR':
                    return 'Network error - check your connection';
                default:
                    return errorData.detail || 'Upload failed';
            }
        }
        
        // Handle legacy error format
        return errorData.detail || errorData.message || 'Upload failed';
    }
}

// Usage examples:
async function uploadReferenceFiles(files) {
    try {
        const result = await ProModeUploadHandler.uploadFiles(
            'https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files',
            files
        );
        
        // Show success message
        showSuccess(`Successfully uploaded ${result.count} file(s)`);
        
        // Refresh file list
        await refreshFileList();
        
    } catch (error) {
        showError(error.message);
    }
}

async function uploadInputFiles(files) {
    try {
        const result = await ProModeUploadHandler.uploadFiles(
            'https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/input-files',
            files
        );
        
        showSuccess(`Successfully uploaded ${result.count} file(s)`);
        await refreshFileList();
        
    } catch (error) {
        showError(error.message);
    }
}

async function uploadSchemaFiles(files) {
    try {
        // Additional validation for schema files
        for (const file of files) {
            if (!file.name.toLowerCase().endsWith('.json')) {
                throw new Error(`File "${file.name}" must be a JSON file`);
            }
            if (file.size > 5 * 1024 * 1024) { // 5MB for schemas
                throw new Error(`Schema file "${file.name}" exceeds 5MB limit`);
            }
        }
        
        const result = await ProModeUploadHandler.uploadFiles(
            'https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/schemas/upload',
            files
        );
        
        showSuccess(`Successfully uploaded ${result.count} schema(s)`);
        await refreshSchemaList();
        
    } catch (error) {
        showError(error.message);
    }
}

// UI Helper functions
function showSuccess(message) {
    // Replace with your success notification system
    console.log('✅ Success:', message);
    // Example: toast notification, modal, etc.
}

function showError(message) {
    // Replace with your error notification system
    console.error('❌ Error:', message);
    // Example: toast notification, modal, etc.
}
```

### **Step 4: Add OPTIONS Handler (if needed)**

Some browsers send preflight OPTIONS requests. Add this to handle them:

```python
# Add to proMode.py if CORS preflight issues persist
@router.options("/reference-files")
@router.options("/input-files") 
@router.options("/schemas/upload")
async def options_handler():
    """Handle CORS preflight requests."""
    from fastapi.responses import JSONResponse
    response = JSONResponse(content={})
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, *"
    return response
```

### **Step 5: Test Complete User Flow**

After deployment, test:

1. **Reference Files Upload**:
   - Empty files → Should show specific error message
   - Valid files → Should upload successfully
   - Too many files → Should show "Maximum 10 files allowed"

2. **Input Files Upload**:
   - Same validations as reference files
   - Should handle large files (up to 50MB)

3. **Schema Upload**:
   - Non-JSON files → Should show "Must be JSON file"
   - Empty JSON → Should show "File is empty"
   - Valid schema → Should upload and appear in schema list

## **🎯 Expected Results**

After implementing these changes:

- ✅ **No more "Something went wrong" errors**
- ✅ **No more CORS access control errors** 
- ✅ **Specific, actionable error messages**
- ✅ **Successful uploads work properly**
- ✅ **Schema uploads work without CORS issues**

## **🚨 Critical Dependencies**

1. **Backend deployment MUST happen first** - All fixes are in the code but not deployed
2. **Frontend updates should be tested after backend deployment**
3. **Test all three upload endpoints** after deployment

---

**Next Immediate Action**: Deploy the updated `proMode.py` to Azure Container Apps to enable the CORS fixes.
