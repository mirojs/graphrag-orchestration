# Pro Mode Frontend Upload Fixes

## 🔍 Problem Analysis

Based on comprehensive testing, the issues are NOT CORS-related. Both standard mode and Pro Mode have identical CORS headers:
- `access-control-allow-origin: https://example.com`
- `access-control-allow-methods: GET,POST,PUT,DELETE,OPTIONS`
- `access-control-allow-headers: Authorization,Content-Type,*`

### ✅ Diagnostic Results (API Working Correctly):
- **Valid File Upload**: ✅ Status 200, returns proper response with file metadata
- **Empty File Handling**: ❌ Status 422 with validation error (frontend issue)
- **Response Format**: ✅ Consistent list format with proper file metadata

## 🎯 Real Issues Identified

### 1. **Frontend File Validation**
- Frontend sends empty file list causing 422 validation errors
- Error: `{"detail":[{"type":"missing","loc":["body","files"],"msg":"Field required","input":null}]}`
- Frontend doesn't validate files before sending to API

### 2. **Error Response Handling**
- 422 validation errors not handled gracefully by frontend
- "Something went wrong" generic messages hide actual API responses
- Frontend expects different error response format

### 3. **Response Format Mismatch**
- API returns: `{'files': [...], 'count': 1}` for uploads
- API returns: `[{file_metadata}, ...]` for listings  
- Frontend may expect consistent format across operations

### 4. **Missing CORS Headers in Error Responses**
- Success responses include proper headers
- Error responses (422) may be missing CORS headers
- Browser blocks error response reading due to missing headers

## 🛠️ Recommended Fixes

### Fix 1: Frontend File Validation & Error Handling

```javascript
// Enhanced Pro Mode upload with proper validation
async function uploadProModeFiles(files, endpoint) {
    try {
        // CRITICAL: Validate files before sending
        if (!files || files.length === 0) {
            throw new Error('No files selected for upload');
        }
        
        // Validate file properties
        for (let file of files) {
            if (!file || !file.name) {
                throw new Error('Invalid file detected');
            }
        }
        
        const formData = new FormData();
        
        // Add each file to FormData with correct field name
        for (let file of files) {
            formData.append('files', file);
        }
        
        const response = await fetch(`${API_BASE_URL}/pro/${endpoint}`, {
            method: 'POST',
            body: formData,
            // Don't set Content-Type - let browser handle multipart/form-data
        });
        
        // Handle different response types
        let responseData;
        const contentType = response.headers.get('content-type');
        
        if (contentType && contentType.includes('application/json')) {
            responseData = await response.json();
        } else {
            responseData = await response.text();
        }
        
        if (!response.ok) {
            // Handle 422 validation errors specifically
            if (response.status === 422 && responseData.detail) {
                const errorMsg = Array.isArray(responseData.detail) 
                    ? responseData.detail.map(e => e.msg).join(', ')
                    : responseData.detail;
                throw new Error(`Validation Error: ${errorMsg}`);
            }
            
            throw new Error(`Upload failed (${response.status}): ${responseData.message || responseData.detail || response.statusText}`);
        }
        
        return responseData;
        
    } catch (error) {
        console.error('Pro Mode upload error:', error);
        
        // Provide specific error messages
        if (error.message.includes('422')) {
            throw new Error('File validation failed. Please check your files and try again.');
        } else if (error.message.includes('No files')) {
            throw new Error('Please select files before uploading.');
        } else if (error.message.includes('fetch')) {
            throw new Error('Network error. Please check your connection and try again.');
        } else {
            throw error; // Re-throw with original message
        }
    }
}

// Frontend file selection handler
function handleFileSelection(inputElement, endpoint) {
    const files = Array.from(inputElement.files);
    
    if (files.length === 0) {
        showError('Please select at least one file');
        return;
    }
    
    // Show loading state
    showLoading('Uploading files...');
    
    uploadProModeFiles(files, endpoint)
        .then(result => {
            hideLoading();
            showSuccess(`Successfully uploaded ${result.count || result.length || files.length} file(s)`);
            refreshFileList(); // Refresh the file list
        })
        .catch(error => {
            hideLoading();
            showError(error.message);
        });
}
```

### Fix 2: Backend CORS Headers for Error Responses

The diagnostic shows that error responses (422) might be missing CORS headers. Add this to the Pro Mode router:

```python
# In app/routers/proMode.py - Add CORS headers to error responses
from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse

@router.post("/reference-files", summary="Upload multiple reference files for pro mode")
async def upload_pro_reference_files(files: List[UploadFile] = File(...), app_config: AppConfiguration = Depends(get_app_config)):
    """Upload multiple reference files (up to 10) for pro mode processing."""
    
    # Add CORS headers to all responses
    def create_cors_response(content, status_code=200):
        response = JSONResponse(content=content, status_code=status_code)
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, *"
        return response
    
    try:
        # Validate files input
        if not files:
            return create_cors_response(
                {"detail": "No files provided. Please select files to upload.", "code": "NO_FILES"},
                status_code=400
            )
        
        if len(files) > 10:
            return create_cors_response(
                {"detail": "Maximum 10 files allowed", "code": "TOO_MANY_FILES"},
                status_code=400
            )
        
        # Process files normally...
        # [existing file processing code]
        
        # Return success with CORS headers
        return create_cors_response({
            "files": uploaded_files,
            "count": len(uploaded_files),
            "message": f"Successfully uploaded {len(uploaded_files)} files"
        })
        
    except Exception as e:
        # Ensure error responses also have CORS headers
        return create_cors_response(
            {"detail": str(e), "code": "UPLOAD_ERROR"},
            status_code=500
        )
```

### Fix 3: Frontend Response Format Handling

```javascript
// Handle different response formats from Pro Mode API
function handleProModeResponse(response, operation) {
    if (!response) {
        throw new Error('No response received');
    }
    
    switch (operation) {
        case 'upload':
            // Upload response: {files: [...], count: N}
            if (response.files && Array.isArray(response.files)) {
                return {
                    success: true,
                    files: response.files,
                    count: response.count || response.files.length,
                    message: response.message || `Uploaded ${response.files.length} files`
                };
            }
            break;
            
        case 'list':
            // List response: [{file_metadata}, ...]
            if (Array.isArray(response)) {
                return {
                    success: true,
                    files: response,
                    count: response.length
                };
            }
            break;
            
        case 'delete':
            // Delete response: {status: "deleted", fileId: "..."}
            if (response.status === 'deleted') {
                return {
                    success: true,
                    message: `File ${response.fileId} deleted successfully`
                };
            }
            break;
    }
    
    // Fallback for unexpected response format
    return {
        success: true,
        data: response,
        message: 'Operation completed'
    };
}

// Usage example
async function uploadFiles(files) {
    try {
        const response = await uploadProModeFiles(files, 'reference-files');
        const result = handleProModeResponse(response, 'upload');
        
        showSuccess(result.message);
        updateFileList(result.files);
        
    } catch (error) {
        showError(error.message);
    }
}
```

## 🧪 Testing Commands (Verified Working)

### Test File Upload (✅ Working)
```python
import requests
import io

files = {'files': ('test.txt', io.BytesIO(b'test content'), 'text/plain')}
response = requests.post(
    'https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files',
    files=files
)
print(f"Status: {response.status_code}")  # Should be 200
print(f"Response: {response.text}")
# Expected: {"files": [...], "count": 1}
```

### Test Empty Upload (❌ Causes 422 Error)
```python
response = requests.post(
    'https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files',
    files={}
)
print(f"Status: {response.status_code}")  # Returns 422
print(f"Response: {response.text}")
# Returns: {"detail":[{"type":"missing","loc":["body","files"],"msg":"Field required","input":null}]}
```

### Test CORS Headers (✅ Working)
```bash
curl -v -H "Origin: https://your-frontend-domain.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: Content-Type" \
  -X OPTIONS \
  "https://ca-cps-xh5lwkfq3vfm-api.bravemoss-af9aee9a.eastus2.azurecontainerapps.io/pro/reference-files"
```

## 🎯 Next Steps (Priority Order)

1. **🔥 CRITICAL - Frontend File Validation**: Prevent empty file submissions that cause 422 errors
2. **🔥 CRITICAL - Error Response Handling**: Handle 422 validation errors gracefully
3. **⚠️ HIGH - CORS Headers in Errors**: Ensure error responses include CORS headers
4. **📊 MEDIUM - Response Format Consistency**: Standardize response handling between operations
5. **🔧 LOW - User Experience**: Improve loading states and error messages

## ✅ Expected Results

After implementing these fixes:
- **No more 422 errors** from empty file submissions
- **Clear error messages** instead of "Something went wrong"
- **Successful Pro Mode uploads** matching standard mode behavior
- **Schema uploads working** with proper response handling
- **No misleading CORS error messages**

## 📝 Verification Checklist

**Frontend Fixes:**
- [ ] Add file validation before API calls
- [ ] Handle 422 validation errors specifically
- [ ] Test empty file selection scenario
- [ ] Verify FormData construction matches working standard mode

**Backend Fixes:**
- [ ] Add CORS headers to error responses
- [ ] Test error response accessibility from frontend
- [ ] Verify consistent response formats

**Integration Testing:**
- [ ] Upload single file to Pro Mode ✅ (Already working)
- [ ] Upload multiple files to Pro Mode
- [ ] Handle empty file selection gracefully ❌ (Needs fix)
- [ ] Display meaningful error messages ❌ (Needs fix)
- [ ] Schema upload and display in list ⚠️ (Partially working)
- [ ] Compare behavior with standard mode
