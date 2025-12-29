# Document Comparison 401 Error Fix - Complete Resolution

## Problem Summary
The document comparison feature in the Prediction tab was failing with 401 authentication errors when trying to create authenticated blob URLs for document preview:

```
[Error] Failed to load resource: the server responded with a status of 401 ()
[Error] [FileComparisonModal] Failed to create authenticated blob URL: Error: Something went wrong
```

## Root Cause Analysis

### Primary Issue: Inconsistent Authentication Logic
The `FileComparisonModal` component uses `httpUtility.headers()` which calls `fetchHeadersWithAuth()`, but this function had inconsistent authentication bypass logic compared to the main `fetchWithAuth()` function.

**Key Problems Identified:**

1. **Missing Authentication Bypass**: `fetchHeadersWithAuth()` always added Authorization headers regardless of `REACT_APP_AUTH_ENABLED` setting
2. **Unsubstituted Placeholder Handling**: Environment variable placeholders like `"APP_AUTH_ENABLED"` were treated as truthy values, enabling authentication when it should be disabled
3. **Missing CORS Configuration**: `fetchHeadersWithAuth()` lacked proper CORS and credentials handling

### Secondary Issues:
- Backend API endpoints don't require JWT authentication (FastAPI app has no auth middleware)
- Deployment configuration sets `APP_AUTH_ENABLED=false` but placeholders weren't handled properly

## Solution Implemented

### 1. Fixed `fetchHeadersWithAuth()` Function
**File**: `/src/ContentProcessorWeb/src/Services/httpUtility.ts`

#### Authentication Bypass Logic:
```typescript
const fetchHeadersWithAuth = async <T>(url: string, method: string = 'GET', body: any = null): Promise<any> => {
  const token = localStorage.getItem('token');
  
  // 🔧 DEV MODE: Check if authentication should be bypassed
  const authEnabledValue = process.env.REACT_APP_AUTH_ENABLED;
  const authEnabled = authEnabledValue && 
                     authEnabledValue !== 'false' && 
                     authEnabledValue !== 'APP_AUTH_ENABLED'; // Handle unsubstituted placeholder
  const isDevelopment = process.env.NODE_ENV === 'development';

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Cache-Control': 'no-cache',
  };

  // Only add Authorization header if auth is enabled and token exists
  if (authEnabled && token) {
    headers['Authorization'] = `Bearer ${token}`;
    console.log('[httpUtility.headers] Using stored authentication token');
  } else if (!authEnabled && isDevelopment) {
    console.log('[httpUtility.headers] Authentication bypassed for development');
  } else if (authEnabled && !token) {
    console.warn('[httpUtility.headers] Authentication enabled but no token available - API calls may fail');
  }
```

#### Added CORS and Error Handling:
```typescript
  const options: RequestInit = {
    method,
    headers,
    mode: 'cors', // Explicitly set CORS mode
    credentials: 'omit', // Don't send credentials unless needed
  };

  // Enhanced error handling with network detection
  try {
    console.log(`[httpUtility.headers] Making ${method} request to: ${api}${url}`);
    const response = await fetch(`${api}${url}`, options);

    if (!response.ok) {
      const errorText = await response.text();
      console.error(`[httpUtility.headers] Response error: ${response.status} - ${errorText}`);
      throw new Error(errorText || 'Something went wrong');
    }
    
    console.log(`[httpUtility.headers] Response status: ${response.status}`);
    return response;

  } catch (error: any) {
    console.error('[httpUtility.headers] Request failed:', error);
    
    const isNetworkError = error instanceof TypeError && error.message === 'Failed to fetch';
    const isOffline = !navigator.onLine;

    const message = isOffline
      ? 'No internet connection. Please check your network and try again.'
      : isNetworkError
      ? 'Unable to connect to the server. Please try again later.'
      : error.message || 'An unexpected error occurred';

    throw new Error(message);
  }
```

### 2. Updated Main `fetchWithAuth()` Function
Enhanced placeholder handling for consistent behavior:

```typescript
const authEnabledValue = process.env.REACT_APP_AUTH_ENABLED;
const authEnabled = authEnabledValue && 
                   authEnabledValue !== 'false' && 
                   authEnabledValue !== 'APP_AUTH_ENABLED'; // Handle unsubstituted placeholder
```

### 3. Updated UI Components
**Files Updated:**
- `/src/Components/Header/Header.tsx`
- `/src/msal-auth/AuthWrapper.tsx`

Both components now handle unsubstituted environment variable placeholders consistently.

## Environment Configuration Context

### Deployment Configuration
From GitHub Actions workflow (`.github/workflows/deploy.yml`):
```yaml
--set-env-vars APP_AUTH_ENABLED=false
```

### Environment Variables
- **Development**: `REACT_APP_AUTH_ENABLED = APP_AUTH_ENABLED` (placeholder)
- **Production**: Placeholder gets replaced with `false` during deployment
- **Unhandled**: If placeholder replacement fails, treat as authentication disabled

## Authentication Logic Summary

### New Logic Flow:
1. **Check Environment Variable**: Get `REACT_APP_AUTH_ENABLED` value
2. **Handle Placeholders**: Treat `"APP_AUTH_ENABLED"` as authentication disabled
3. **Validate Token**: Only add Authorization header if auth enabled AND token exists
4. **Bypass Mode**: Log authentication bypass in development mode
5. **Error Handling**: Provide clear warnings when auth enabled but no token

### Behavior Matrix:
| Environment Value | Authentication Enabled | Authorization Header |
|------------------|----------------------|---------------------|
| `undefined` | ❌ No | ❌ Not added |
| `"false"` | ❌ No | ❌ Not added |
| `"APP_AUTH_ENABLED"` | ❌ No | ❌ Not added |
| `"true"` | ✅ Yes (if token exists) | ✅ Added |
| Any other string | ✅ Yes (if token exists) | ✅ Added |

## Testing Results

### Before Fix:
```
[Error] Failed to load resource: the server responded with a status of 401 ()
[Error] [FileComparisonModal] Failed to create authenticated blob URL
```

### After Fix:
```
[Log] [httpUtility.headers] Authentication bypassed for development
[Log] [httpUtility.headers] Making GET request to: [API_URL]/pro-mode/files/{processId}/preview
[Log] [httpUtility.headers] Response status: 200
[Log] [FileComparisonModal] Rendering dialog with isOpen: true
```

## Files Modified

1. **`/src/ContentProcessorWeb/src/Services/httpUtility.ts`**
   - Fixed `fetchHeadersWithAuth()` authentication logic
   - Added CORS and error handling consistency
   - Enhanced placeholder handling in both auth functions

2. **`/src/Components/Header/Header.tsx`**
   - Updated authentication check logic

3. **`/src/msal-auth/AuthWrapper.tsx`**
   - Updated authentication check logic

## Impact

✅ **Document Comparison Feature**: Now works correctly without 401 errors
✅ **Authentication Consistency**: All components use the same auth logic
✅ **Environment Flexibility**: Handles both substituted and unsubstituted placeholders
✅ **Error Handling**: Better error messages and network detection
✅ **Development Experience**: Clear logging for authentication bypass mode

## Prevention Strategy

### Environment Variable Best Practices:
1. **Consistent Logic**: All authentication checks now use the same pattern
2. **Placeholder Handling**: Always check for unsubstituted placeholders
3. **Default Behavior**: Default to authentication disabled for safety
4. **Clear Logging**: Log authentication decisions for debugging

### Code Consistency:
- All HTTP utility functions now have the same authentication logic
- CORS and error handling patterns are consistent
- Environment variable parsing is standardized

The document comparison 401 error is now completely resolved, and the authentication system is more robust and consistent across the application.