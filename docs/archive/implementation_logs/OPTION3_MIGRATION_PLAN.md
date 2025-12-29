# Option 3 Migration Plan - Single Container Architecture

## Overview
Migrate from separate Web + API containers to Azure OpenAI Demo pattern (single backend serving both static frontend and API).

## Target Environment
- **Phase 1 (DONE)**: Production - Quick fix with nginx proxy (Option 2)
- **Phase 2 (TODO)**: Development - Implement Option 3
- **Phase 3 (TODO)**: Production - Deploy Option 3 after dev validation

---

## Phase 2: Implement in Development Environment

### Step 1: Update Frontend Build Configuration

**File:** `src/ContentProcessorWeb/vite.config.ts`

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../ContentProcessorAPI/app/static',  // ← Change from 'build'
    emptyOutDir: true,
    sourcemap: true,
  },
  server: {
    proxy: {
      '/auth_setup': 'http://localhost:8000',
      '/pro-mode': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
      '/groups': 'http://localhost:8000',
      '/schemavault': 'http://localhost:8000',
    }
  }
});
```

---

### Step 2: Update Frontend API Base URL

**File:** `src/ContentProcessorWeb/src/config.ts` (or wherever API_BASE_URL is defined)

```typescript
// Change from absolute URL to empty string (same origin)
export const API_BASE_URL = '';  // Was: 'https://...'
```

---

### Step 3: Add Static File Serving to Backend

**File:** `src/ContentProcessorAPI/app/main.py`

Add after existing routes, before `if __name__ == "__main__"`:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from pathlib import Path

# Serve static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    
    @app.get("/")
    async def serve_spa():
        """Serve the React SPA"""
        return FileResponse(static_dir / "index.html")
    
    @app.get("/{full_path:path}")
    async def serve_spa_routes(full_path: str):
        """Catch-all route for React Router - serve index.html for client-side routing"""
        # Don't intercept API routes
        if full_path.startswith(("api/", "pro-mode/", "auth_setup", "health", "startup")):
            raise HTTPException(status_code=404)
        
        # Try to serve static file, fallback to index.html for SPA routes
        file_path = static_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(static_dir / "index.html")
```

---

### Step 4: Update Backend Dockerfile

**File:** `src/ContentProcessorAPI/Dockerfile`

Replace with multi-stage build:

```dockerfile
# Stage 1: Build React frontend
FROM mcr.microsoft.com/vscode/devcontainers/javascript-node:22-bookworm AS frontend-builder

WORKDIR /frontend
COPY ../ContentProcessorWeb/package.json ../ContentProcessorWeb/yarn.lock ./
RUN yarn install

COPY ../ContentProcessorWeb/ ./
RUN yarn build

# Stage 2: Python backend
FROM mcr.microsoft.com/azurelinux/base/python:3.12

WORKDIR /app

# Copy backend code
COPY app/ ./app/
COPY requirements.txt ./

# Copy frontend build from previous stage
COPY --from=frontend-builder /frontend/build ./app/static

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

### Step 5: Update Infrastructure (Remove Web Container)

**File:** `infra/main.bicep`

1. **Remove web container module** (around line 900-950):
```bicep
// DELETE THIS ENTIRE SECTION:
// module avmContainerApp_Web 'br/public:avm/res/app/container-app:0.11.0' = {
//   ...
// }
```

2. **Update custom domain to point to API**:
```bicep
// In the API container module, add:
module avmContainerApp_API 'br/public:avm/res/app/container-app:0.11.0' = {
  // ... existing config ...
  params: {
    // ... existing params ...
    customDomains: [
      {
        name: 'map.hulkdesign.com'
        certificateId: resourceId('Microsoft.App/managedEnvironments/managedCertificates', 
          'cae-cps-y22yd4amoxqu', 'map.hulkdesign.com-cae-cps-y22yd4amoxqu')
        bindingType: 'SniEnabled'
      }
    ]
  }
}
```

3. **Remove web container role assignments** (search for references to `avmContainerApp_Web.outputs`)

---

### Step 6: Clean Up Deleted Files

Delete these files (no longer needed):
- `src/ContentProcessorWeb/Dockerfile`
- `src/ContentProcessorWeb/nginx-custom.conf`
- `src/ContentProcessorWeb/env.sh`

---

### Step 7: Test Locally

```bash
# Build frontend
cd src/ContentProcessorWeb
yarn build  # Should output to ../ContentProcessorAPI/app/static

# Run backend (serves both API and frontend)
cd ../ContentProcessorAPI
python -m uvicorn app.main:app --reload

# Test in browser: http://localhost:8000
# Should see React app AND /auth_setup should work
```

---

### Step 8: Deploy to Development Environment

```bash
# Switch to development environment
azd env select dev  # Or create if doesn't exist: azd env new dev

# Set environment variables
azd env set AZURE_CLIENT_APP_ID <dev-app-registration-id>
azd env set AZURE_LOCATION swedencentral  # Or your preferred region

# Deploy
azd up

# This will:
# 1. Provision new resources in dev environment
# 2. Build single container with frontend included
# 3. Deploy to Azure Container Apps
```

---

### Step 9: Test Development Deployment

- [ ] Access dev URL and verify app loads
- [ ] Test `/auth_setup` returns correct config
- [ ] Test authentication flow
- [ ] Test group selector appears
- [ ] Test file upload
- [ ] Test schema creation
- [ ] Test document analysis
- [ ] Verify all API calls work (no CORS errors)

---

## Phase 3: Deploy to Production

Once dev is validated:

```bash
# Switch back to production
azd env select prod

# Deploy Option 3 to production
azd up

# This will:
# 1. Remove old web container
# 2. Update API container with frontend
# 3. Migrate custom domain to API container
```

---

## Rollback Plan

If Option 3 has issues in production:

```bash
# Revert to Option 2 (nginx proxy version)
git revert <option-3-commits>
azd deploy
```

---

## Benefits After Migration

✅ Simpler deployment (1 container instead of 2)
✅ No CORS configuration needed
✅ No nginx proxy maintenance
✅ Faster deployments (no separate web build)
✅ Custom domain "just works"
✅ Authentication works seamlessly
✅ Follows Microsoft's recommended pattern

---

## Timeline Estimate

- **Phase 1 (Option 2 - Production)**: DONE ✓
- **Phase 2 (Option 3 - Development)**: 2-3 hours
- **Phase 3 (Option 3 - Production)**: 30 minutes (after dev validation)

**Total: ~3-4 hours**
