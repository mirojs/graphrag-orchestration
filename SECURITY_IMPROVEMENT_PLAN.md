# Security & Malfunction Improvement Plan
**Created:** October 28, 2025  
**Based On:** PRO_MODE_SECURITY_AUDIT_REPORT.md & PRO_MODE_SECURITY_MALFUNCTION_AUDIT_REPORT.md  
**Target Completion:** 8 weeks (2 months)

---

## 🎯 Executive Summary

This plan addresses **36 security issues** identified across backend and frontend:
- **5 Critical** (Backend)
- **2 High** (Frontend)  
- **8 High Priority** (Backend)
- **17 Medium Priority** (Combined)
- **10 Low Priority** (Combined)

**Estimated Effort:** 200-240 hours (2 developers × 8 weeks)

---

## 📅 SPRINT-BY-SPRINT ROADMAP

### **Sprint 1 (Week 1-2): Critical Backend Issues**
**Goal:** Eliminate all critical security vulnerabilities  
**Effort:** 60 hours

#### Task 1.1: NoSQL Injection Prevention (16h)
**Priority:** 🔴 CRITICAL  
**Files:** `app/routers/proMode.py`

**Actions:**
```python
# 1. Create validation utility (2h)
# File: app/utils/validators.py

import re
from fastapi import HTTPException

def validate_container_name(name: str) -> str:
    """Validate MongoDB container/collection names"""
    if not re.match(r'^[a-z0-9_-]{3,63}$', name):
        raise HTTPException(
            status_code=400, 
            detail="Invalid container name format"
        )
    return name

def validate_uuid(value: str, field_name: str = "ID") -> str:
    """Validate UUID format"""
    uuid_pattern = r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'
    if not re.match(uuid_pattern, value.lower()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {field_name} format"
        )
    return value

def sanitize_blob_name(filename: str) -> str:
    """Sanitize blob storage names"""
    import os
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
    if len(filename) > 255:
        name, ext = os.path.splitext(filename)
        filename = name[:250] + ext
    return filename
```

```python
# 2. Update all MongoDB queries (8h)
# File: app/routers/proMode.py

# Before:
collection = db[pro_container_name]

# After:
from app.utils.validators import validate_container_name
collection = db[validate_container_name(pro_container_name)]

# Apply to lines: 2549, 2608, 3115, 3181, 3248, and ~20 other locations
```

```python
# 3. Add tests (4h)
# File: tests/test_validators.py

def test_validate_container_name():
    assert validate_container_name("valid-name_123") == "valid-name_123"
    
    with pytest.raises(HTTPException):
        validate_container_name("../../../etc/passwd")
    
    with pytest.raises(HTTPException):
        validate_container_name("invalid name with spaces")
```

**Acceptance Criteria:**
- [ ] All MongoDB queries use validated container names
- [ ] Unit tests cover edge cases (path traversal, special chars)
- [ ] No regression in functionality

---

#### Task 1.2: File Upload Security (20h)
**Priority:** 🔴 CRITICAL  
**Files:** `app/routers/proMode.py` (lines 587-610, 652-678)

**Actions:**
```python
# 1. Install dependencies (0.5h)
# requirements.txt
python-magic==0.4.27

# 2. Create enhanced validation (6h)
# File: app/utils/file_validation.py

import os
import magic
from typing import List
from fastapi import UploadFile, HTTPException

ALLOWED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.txt', '.png', '.jpg', '.jpeg', '.tiff', '.tif'}
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
    'text/plain',
    'image/png',
    'image/jpeg', 
    'image/tiff'
}

async def validate_upload_security(
    files: List[UploadFile], 
    max_files: int = 10,
    max_size_mb: int = 100
) -> None:
    """Comprehensive file upload validation"""
    
    if len(files) > max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_files} files allowed"
        )
    
    for file in files:
        # 1. Sanitize filename
        filename = os.path.basename(file.filename)
        if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid filename: {file.filename}"
            )
        
        # 2. Validate extension
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
        
        # 3. Read file content (limit to first 100MB to prevent memory issues)
        file_size = 0
        file_content = bytearray()
        chunk_size = 8192
        
        while chunk := await file.read(chunk_size):
            file_size += len(chunk)
            if file_size > max_size_mb * 1024 * 1024:
                raise HTTPException(
                    status_code=413,
                    detail=f"File {filename} exceeds {max_size_mb}MB limit"
                )
            file_content.extend(chunk)
        
        # Reset file pointer for later processing
        await file.seek(0)
        
        # 4. MIME type verification
        detected_mime = magic.from_buffer(bytes(file_content), mime=True)
        if detected_mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"File content type mismatch. Detected: {detected_mime}"
            )
        
        # 5. Basic malware signature detection (simple patterns)
        suspicious_patterns = [
            b'<script',
            b'javascript:',
            b'<?php',
            b'eval(',
        ]
        for pattern in suspicious_patterns:
            if pattern in file_content.lower():
                raise HTTPException(
                    status_code=400,
                    detail=f"File {filename} contains suspicious content"
                )
```

```python
# 3. Update upload endpoints (6h)
# File: app/routers/proMode.py

from app.utils.file_validation import validate_upload_security

@router.post("/pro-mode/input-files")
async def upload_pro_input_files(
    files: List[UploadFile] = File(...),
    ...
):
    # Add validation before processing
    await validate_upload_security(files, max_files=10, max_size_mb=100)
    
    # Continue with existing logic
    ...
```

**Acceptance Criteria:**
- [ ] All file upload endpoints use new validation
- [ ] MIME type verification prevents content-type spoofing
- [ ] Path traversal attacks prevented
- [ ] File size limits enforced
- [ ] Tests cover malicious filenames and content

---

#### Task 1.3: Rate Limiting (12h)
**Priority:** 🔴 CRITICAL  
**Files:** All endpoints

**Actions:**
```python
# 1. Install dependencies (0.5h)
# requirements.txt
fastapi-limiter==0.1.5
redis==4.5.1

# 2. Configure rate limiter (2h)
# File: app/main.py

from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter
import redis.asyncio as redis

@app.on_event("startup")
async def startup():
    # Connect to Redis (use Azure Redis Cache in production)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    redis_client = await redis.from_url(redis_url, encoding="utf-8", decode_responses=True)
    await FastAPILimiter.init(redis_client)

# 3. Apply to endpoints (8h)
# File: app/routers/proMode.py

# High-cost operations (analysis, AI)
@router.post(
    "/pro-mode/content-analyzers/{analyzer_id}:analyze",
    dependencies=[Depends(RateLimiter(times=5, seconds=60))]  # 5 per minute
)

# File uploads
@router.post(
    "/pro-mode/input-files",
    dependencies=[Depends(RateLimiter(times=20, seconds=60))]  # 20 per minute
)

# Schema operations
@router.post(
    "/pro-mode/schemas/upload",
    dependencies=[Depends(RateLimiter(times=10, seconds=60))]  # 10 per minute
)

# Read operations (more permissive)
@router.get(
    "/pro-mode/schemas",
    dependencies=[Depends(RateLimiter(times=100, seconds=60))]  # 100 per minute
)
```

**Acceptance Criteria:**
- [ ] Redis configured for rate limit storage
- [ ] All POST/PUT/DELETE endpoints rate-limited
- [ ] Different limits for different operation types
- [ ] 429 errors returned with Retry-After header
- [ ] Rate limits documented in API docs

---

#### Task 1.4: Fix IDOR Vulnerabilities (8h)
**Priority:** 🔴 CRITICAL  
**Files:** Delete/download endpoints

**Actions:**
```python
# 1. Create ownership validation helper (2h)
# File: app/utils/authorization.py

from fastapi import HTTPException
from app.models.user_context import UserContext

async def verify_resource_ownership(
    resource_type: str,
    resource_id: str,
    group_id: str,
    db,
    collection_name: str
) -> dict:
    """Verify user's group owns the resource"""
    
    collection = db[collection_name]
    resource = collection.find_one({"id": resource_id})
    
    if not resource:
        # Don't reveal resource exists
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")
    
    resource_group = resource.get('group_id') or resource.get('groupId')
    if resource_group != group_id:
        # Don't reveal resource exists for security
        raise HTTPException(status_code=404, detail=f"{resource_type} not found")
    
    return resource

# 2. Update delete endpoint (3h)
@router.delete("/pro-mode/schemas/{schema_id}")
async def delete_pro_schema(
    schema_id: str,
    group_id: str = Header(..., alias="X-Group-ID"),
    current_user: UserContext = Depends(get_current_user),
    app_config: AppConfiguration = Depends(get_app_config)
):
    # 1. Validate group access first
    await validate_group_access(group_id, current_user)
    
    # 2. Get database connection
    client = MongoClient(app_config.app_cosmos_connstr)
    db = client[app_config.app_cosmos_database_name]
    
    try:
        # 3. Verify ownership BEFORE allowing delete
        schema = await verify_resource_ownership(
            resource_type="Schema",
            resource_id=schema_id,
            group_id=group_id,
            db=db,
            collection_name=pro_container_name
        )
        
        # 4. Now safe to delete
        blob_url = schema.get('blobUrl')
        
        # Delete from Cosmos DB
        collection = db[pro_container_name]
        delete_result = collection.delete_one({"id": schema_id})
        
        # Delete from blob storage
        if blob_url:
            storage_helper = StorageBlobHelper(
                app_config.app_storage_blob_url,
                get_group_container_name(group_id)
            )
            blob_name = extract_blob_name(blob_url)
            storage_helper.delete_blob(blob_name)
        
        return {"status": "deleted", "schemaId": schema_id}
        
    finally:
        client.close()
```

**Acceptance Criteria:**
- [ ] All delete endpoints verify ownership
- [ ] All download endpoints verify ownership  
- [ ] 404 returned for both missing and unauthorized resources
- [ ] No resource enumeration possible
- [ ] Tests cover cross-group access attempts

---

#### Task 1.5: Sanitize Error Messages (8h)
**Priority:** 🔴 CRITICAL  
**Files:** All error handling

**Actions:**
```python
# 1. Create error sanitization (3h)
# File: app/utils/error_handling.py

import uuid
import logging
from fastapi import HTTPException

logger = logging.getLogger(__name__)

def sanitize_error_for_user(
    error: Exception,
    operation: str,
    user_id: str = None,
    group_id: str = None
) -> tuple[str, str]:
    """
    Return safe error message for users and detailed internal log
    Returns: (user_message, request_id)
    """
    request_id = str(uuid.uuid4())
    
    # Log full error internally with context
    logger.error(
        f"[{request_id}] Operation '{operation}' failed",
        extra={
            "request_id": request_id,
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "user_id": user_id,
            "group_id": group_id
        },
        exc_info=True
    )
    
    # Generic user-facing message
    user_message = (
        f"An error occurred during {operation}. "
        f"Please contact support with Request ID: {request_id}"
    )
    
    return user_message, request_id

# 2. Update exception handling (4h)
# File: app/routers/proMode.py

# Before:
raise HTTPException(
    status_code=500,
    detail=f"Upload failed: {str(e)}"
)

# After:
user_msg, req_id = sanitize_error_for_user(
    error=e,
    operation="file upload",
    user_id=current_user.user_id if current_user else None,
    group_id=group_id
)
raise HTTPException(
    status_code=500,
    detail=user_msg,
    headers={"X-Request-ID": req_id}
)
```

**Acceptance Criteria:**
- [ ] All error messages use sanitization
- [ ] Internal logs contain full details
- [ ] Users never see stack traces or paths
- [ ] Request IDs allow support to trace issues
- [ ] Tests verify no info leakage

---

### **Sprint 2 (Week 3-4): High Priority Backend + Frontend XSS**
**Goal:** Fix high-severity issues  
**Effort:** 70 hours

#### Task 2.1: Frontend XSS Prevention (12h)
**Priority:** 🟠 HIGH  
**Files:** Frontend components

**Actions:**
```bash
# 1. Install DOMPurify (0.5h)
cd code/content-processing-solution-accelerator/src/ContentProcessorWeb
npm install dompurify @types/dompurify
```

```typescript
// 2. Fix AdvancedDocumentViewer.tsx (3h)
import DOMPurify from 'dompurify';

// Before:
style.innerHTML = highlightStyles.replace(/<\/?style>/g, '');

// After:
style.textContent = highlightStyles.replace(/<\/?style>/g, '');
// OR if HTML is needed:
style.innerHTML = DOMPurify.sanitize(highlightStyles, {
  ALLOWED_TAGS: [],  // Only CSS, no HTML tags
  ALLOWED_ATTR: []
});
```

```typescript
// 3. Remove backup files (1h)
// Delete: FileComparisonModal_backup_1758449719.tsx

// Add to .gitignore:
*_backup_*.tsx
*_backup_*.ts
```

```typescript
// 4. Create secure HTML utility (4h)
// File: src/shared/utils/secureHtml.ts

import DOMPurify from 'dompurify';

export const sanitizeHtml = (dirty: string, allowedTags?: string[]): string => {
  return DOMPurify.sanitize(dirty, {
    ALLOWED_TAGS: allowedTags || ['b', 'i', 'em', 'strong', 'a', 'p', 'br'],
    ALLOWED_ATTR: ['href', 'target', 'rel']
  });
};

export const sanitizeStyleContent = (styleContent: string): string => {
  // Remove any HTML tags, keep only CSS
  return DOMPurify.sanitize(styleContent, {
    ALLOWED_TAGS: [],
    ALLOWED_ATTR: []
  });
};

// Usage:
import { sanitizeHtml } from '@/shared/utils/secureHtml';
<div dangerouslySetInnerHTML={{ __html: sanitizeHtml(userContent) }} />
```

**Acceptance Criteria:**
- [ ] No innerHTML without DOMPurify
- [ ] No dangerouslySetInnerHTML without sanitization
- [ ] Backup files deleted
- [ ] .gitignore prevents future backups
- [ ] Tests verify XSS prevention

---

#### Task 2.2: CSRF Protection (10h)
**Priority:** 🟠 HIGH

**Actions:**
```python
# 1. Install dependency (0.5h)
# requirements.txt
fastapi-csrf-protect==0.3.2

# 2. Configure CSRF (3h)
# File: app/main.py

from fastapi_csrf_protect import CsrfProtect
from fastapi_csrf_protect.exceptions import CsrfProtectError
from pydantic import BaseModel

class CsrfSettings(BaseModel):
    secret_key: str = os.getenv("CSRF_SECRET_KEY", "your-secret-key-change-in-production")
    cookie_name: str = "csrf_token"
    header_name: str = "X-CSRF-Token"

@CsrfProtect.load_config
def get_csrf_config():
    return CsrfSettings()

# 3. Add CSRF to state-changing endpoints (5h)
from fastapi_csrf_protect import CsrfProtect

@router.post("/pro-mode/schemas/upload")
async def upload_schemas(
    csrf_protect: CsrfProtect = Depends(),
    files: List[UploadFile] = File(...),
    ...
):
    # Validate CSRF token
    await csrf_protect.validate_csrf(request)
    
    # Continue with upload
    ...

# 4. Update CORS to be restrictive (1h)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://yourdomain.com",
        "https://*.azurewebsites.net"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

**Acceptance Criteria:**
- [ ] CSRF tokens required for all POST/PUT/DELETE
- [ ] CORS restricted to specific origins
- [ ] Frontend sends CSRF token in requests
- [ ] Tests verify CSRF protection

---

#### Task 2.3: Secure localStorage Wrapper (8h)
**Priority:** 🟠 HIGH (Frontend)

**Actions:**
```typescript
// 1. Create secure storage utility (5h)
// File: src/shared/utils/secureStorage.ts

type Validator<T> = (value: T) => boolean;

interface StorageOptions<T> {
  validator?: Validator<T>;
  encrypt?: boolean;
}

class SecureStorage {
  private readonly prefix = 'promode_';
  
  getItem<T = string>(
    key: string, 
    options?: StorageOptions<T>
  ): T | null {
    try {
      const fullKey = this.prefix + key;
      const raw = localStorage.getItem(fullKey);
      
      if (raw === null || raw === undefined) return null;
      
      // Try to parse JSON, fallback to raw string
      let parsed: any = raw;
      try {
        parsed = JSON.parse(raw);
      } catch {
        // Not JSON, use as-is
      }
      
      // Validate if validator provided
      if (options?.validator && !options.validator(parsed)) {
        console.warn(`[SecureStorage] Validation failed for ${key}, clearing`);
        this.removeItem(key);
        return null;
      }
      
      return parsed as T;
      
    } catch (error) {
      console.error(`[SecureStorage] Failed to read ${key}:`, error);
      return null;
    }
  }
  
  setItem<T>(key: string, value: T, options?: StorageOptions<T>): void {
    try {
      const fullKey = this.prefix + key;
      
      // Validate before storing
      if (options?.validator && !options.validator(value)) {
        throw new Error(`Validation failed for ${key}`);
      }
      
      const toStore = typeof value === 'string' 
        ? value 
        : JSON.stringify(value);
      
      localStorage.setItem(fullKey, toStore);
      
    } catch (error) {
      console.error(`[SecureStorage] Failed to write ${key}:`, error);
      throw error;
    }
  }
  
  removeItem(key: string): void {
    try {
      const fullKey = this.prefix + key;
      localStorage.removeItem(fullKey);
    } catch (error) {
      console.error(`[SecureStorage] Failed to remove ${key}:`, error);
    }
  }
}

export const secureStorage = new SecureStorage();

// Validators
export const validators = {
  uuid: (val: string) => /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(val),
  jwt: (val: string) => val.startsWith('ey') && val.split('.').length === 3,
  nonEmpty: (val: string) => val.length > 0,
};
```

```typescript
// 2. Replace localStorage usage (3h)
// File: src/ProModeComponents/QuickQuerySection.tsx

import { secureStorage, validators } from '@/shared/utils/secureStorage';

// Before:
const selectedGroup = localStorage.getItem('selectedGroup');

// After:
const selectedGroup = secureStorage.getItem('selectedGroup', {
  validator: validators.uuid
});

// Before:
localStorage.setItem('selectedGroup', groupId);

// After:
secureStorage.setItem('selectedGroup', groupId, {
  validator: validators.uuid
});
```

**Acceptance Criteria:**
- [ ] All localStorage usage replaced with secureStorage
- [ ] Validators prevent invalid data storage
- [ ] Invalid data automatically cleared
- [ ] Tests cover validation edge cases

---

#### Task 2.4: Azure Token Caching (10h)
**Priority:** 🟠 HIGH

**Actions:**
```python
# 1. Create token cache (5h)
# File: app/utils/token_cache.py

from datetime import datetime, timedelta
from threading import Lock
from typing import Optional, Dict

class TokenCache:
    """Thread-safe token cache with automatic refresh"""
    
    def __init__(self):
        self._tokens: Dict[str, dict] = {}
        self._lock = Lock()
        self.refresh_buffer = timedelta(minutes=5)
    
    def get_token(self, credential, scope: str) -> str:
        """Get cached token or request new one"""
        with self._lock:
            cache_key = scope
            cached = self._tokens.get(cache_key)
            
            # Use cached if valid for at least 5 more minutes
            if cached:
                expires_on = cached['expires_on']
                if expires_on > datetime.now() + self.refresh_buffer:
                    logger.debug(f"Using cached token for {scope}")
                    return cached['token']
            
            # Request new token
            logger.info(f"Requesting new token for {scope}")
            token = credential.get_token(scope)
            
            self._tokens[cache_key] = {
                'token': token.token,
                'expires_on': datetime.fromtimestamp(token.expires_on)
            }
            
            return token.token
    
    def clear(self, scope: Optional[str] = None):
        """Clear cached tokens"""
        with self._lock:
            if scope:
                self._tokens.pop(scope, None)
            else:
                self._tokens.clear()

# Global instance
token_cache = TokenCache()

# 2. Update auth helper (3h)
# File: app/routers/proMode.py

from app.utils.token_cache import token_cache

def get_unified_azure_auth_headers(
    scope: str = "https://cognitiveservices.azure.com/.default"
) -> dict:
    """Get Azure AD auth headers with token caching"""
    credential = get_azure_credential()
    token = token_cache.get_token(credential, scope)
    return {"Authorization": f"Bearer {token}"}
```

**Acceptance Criteria:**
- [ ] Tokens cached for reuse
- [ ] Automatic refresh 5 minutes before expiry
- [ ] Thread-safe implementation
- [ ] Metrics show reduced token requests
- [ ] Tests verify caching behavior

---

#### Task 2.5: Security Headers & CSP (8h)
**Priority:** 🟠 HIGH

**Actions:**
```python
# 1. Create security headers middleware (4h)
# File: app/middleware/security_headers.py

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' https://*.azure.com https://*.azurewebsites.net; "
            "frame-ancestors 'none';"
        )
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        # HSTS (only if using HTTPS)
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return response

# 2. Apply middleware (1h)
# File: app/main.py

from app.middleware.security_headers import SecurityHeadersMiddleware

app.add_middleware(SecurityHeadersMiddleware)
```

**Acceptance Criteria:**
- [ ] All responses include security headers
- [ ] CSP prevents inline script execution
- [ ] HSTS enforced on HTTPS
- [ ] Browser security tools verify headers

---

### **Sprint 3 (Week 5-6): Medium Priority Issues**
**Goal:** Address medium-severity vulnerabilities  
**Effort:** 50 hours

#### Task 3.1: Enhanced SAS Token Validation (8h)
#### Task 3.2: Input Sanitization for AI Prompts (8h)
#### Task 3.3: Structured Audit Logging (10h)
#### Task 3.4: Field-Level Encryption for Sensitive Data (12h)
#### Task 3.5: Blob URL Memory Cleanup (6h)
#### Task 3.6: File Integrity Verification (6h)

---

### **Sprint 4 (Week 7-8): Low Priority & Infrastructure**
**Goal:** Complete remaining issues and add monitoring  
**Effort:** 40 hours

#### Task 4.1: Environment-Aware Logging (6h)
#### Task 4.2: Query History Size Limit (3h)
#### Task 4.3: XHR Timeout Configuration (3h)
#### Task 4.4: Exponential Backoff for Retries (4h)
#### Task 4.5: Dependency Vulnerability Scanning (4h)
#### Task 4.6: API Documentation Updates (8h)
#### Task 4.7: Security Testing Suite (12h)

---

## 🔧 INFRASTRUCTURE SETUP

### Required Services
1. **Redis** - Rate limiting & caching
   - Azure Redis Cache (Standard tier)
   - Connection string in environment variables

2. **Application Insights** - Security monitoring
   - Track failed auth attempts
   - Alert on unusual patterns

3. **Azure Key Vault** - Secret management
   - Store CSRF secret, encryption keys
   - Rotate regularly

4. **Azure Security Center** - Threat detection

---

## 📊 SUCCESS METRICS

### Security Metrics
- Zero critical vulnerabilities
- < 5 high-severity issues
- All endpoints rate-limited
- 100% of errors sanitized
- CSRF protection on all state-changing operations

### Performance Metrics
- Token cache hit rate > 90%
- Rate limit violations < 1%
- File upload validation < 500ms overhead

### Quality Metrics
- Test coverage > 80% for security functions
- Zero regressions in functionality
- All security headers present

---

## 🧪 TESTING STRATEGY

### Security Testing
```bash
# 1. Static analysis
bandit -r app/
npm audit

# 2. Dependency scanning
safety check
npm audit fix

# 3. OWASP ZAP scanning
docker run -t owasp/zap2docker-stable zap-baseline.py -t https://your-api.com

# 4. Penetration testing
- SQL/NoSQL injection attempts
- XSS payload injection
- CSRF token bypass
- Rate limit validation
- File upload attacks
```

### Unit Tests
```python
# File: tests/security/test_validators.py
def test_validate_container_name_prevents_injection():
    with pytest.raises(HTTPException):
        validate_container_name("'; DROP TABLE users; --")

# File: tests/security/test_file_upload.py
async def test_upload_rejects_malicious_filename():
    with pytest.raises(HTTPException):
        await validate_upload_security([
            UploadFile(filename="../../../etc/passwd")
        ])
```

---

## 📋 DEPLOYMENT CHECKLIST

### Pre-Deployment
- [ ] All critical fixes merged
- [ ] Security tests passing
- [ ] Dependency vulnerabilities resolved
- [ ] Secrets moved to Key Vault
- [ ] Rate limits configured
- [ ] CSP policies tested

### Deployment
- [ ] Deploy to staging first
- [ ] Run OWASP ZAP scan
- [ ] Verify security headers
- [ ] Test rate limiting
- [ ] Check audit logs

### Post-Deployment
- [ ] Monitor error rates
- [ ] Check Application Insights
- [ ] Review audit logs daily (first week)
- [ ] Schedule penetration test
- [ ] Document lessons learned

---

## 🎯 PRIORITY SUMMARY

### Must Have (Before Production)
1. ✅ NoSQL injection prevention
2. ✅ File upload validation
3. ✅ Rate limiting
4. ✅ IDOR fixes
5. ✅ Error sanitization
6. ✅ XSS prevention

### Should Have (First Month)
7. ✅ CSRF protection
8. ✅ Secure localStorage
9. ✅ Token caching
10. ✅ Security headers
11. ✅ Audit logging

### Nice to Have (Second Month)
12. Field encryption
13. Dependency scanning
14. Enhanced monitoring
15. Documentation updates

---

## 📚 RESOURCES

### Tools
- **Bandit** - Python security linter
- **Safety** - Dependency checker
- **OWASP ZAP** - Security scanner
- **DOMPurify** - XSS prevention

### Documentation
- OWASP Top 10 2021
- FastAPI Security Best Practices
- Azure Security Baseline
- NIST Cybersecurity Framework

### Team Training
- OWASP Secure Coding Practices
- Azure Security Fundamentals
- Secure Code Review Workshop

---

**Plan Owner:** Development Team  
**Stakeholders:** Security Team, Product Owner, DevOps  
**Review Schedule:** Weekly progress updates  
**Next Review:** End of Sprint 1 (Week 2)
