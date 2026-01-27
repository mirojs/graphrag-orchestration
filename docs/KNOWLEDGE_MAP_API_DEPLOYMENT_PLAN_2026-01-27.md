# Knowledge Map API Deployment Plan

**Date:** January 27, 2026  
**Status:** Planning Complete, Ready for Implementation

---

## Executive Summary

Deploy the Knowledge Map Document Processing API as an independent Azure service using **Container Apps + Redis + Easy Auth** architecture. This approach provides production-ready deployment at minimal cost (~$50-65/month) without the complexity of Azure API Management.

---

## Architecture Decision

### Selected: Container Apps + Redis + Easy Auth

```
┌─────────────────────────────────────┐
│   Azure Container Apps Environment   │
│   ┌─────────────────────────────┐   │
│   │    Easy Auth Sidecar        │   │  ← Azure AD / API Key auth (FREE)
│   │    (Built-in Authentication)│   │
│   └──────────────┬──────────────┘   │
│                  │                   │
│   ┌──────────────▼──────────────┐   │
│   │    Knowledge Map API        │   │  ← FastAPI container
│   │    (FastAPI + Uvicorn)      │   │
│   └──────────────┬──────────────┘   │
│                  │                   │
└──────────────────┼──────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
┌─────────────┐         ┌─────────────┐
│ Azure Redis │         │  Azure DI   │
│   Cache     │         │  West US    │
│   (Basic)   │         │             │
└─────────────┘         └─────────────┘
 Operation Store         Document
 with TTL                Processing
```

### Why This Architecture

| Factor | Container Apps + Redis | vs. Alternatives |
|--------|------------------------|------------------|
| **Cost** | ~$50-65/month | App Service: $70+, Functions Premium: $175+ |
| **Complexity** | Low (no APIM config) | APIM adds $50/mo + complex policies |
| **Auth** | Built-in Easy Auth | Same as App Service |
| **Scaling** | 0-10 instances auto | Functions: cold start issues |
| **Fit** | Perfect for async polling | Functions: 5-min timeout risk |

### Alternatives Considered

1. **Container Apps + APIM** — Deferred until external clients need rate limiting/developer portal
2. **Function Apps** — Rejected due to timeout limits and cold start
3. **Dapr State Store** — Rejected as unnecessary abstraction for simple Redis use case
4. **App Service** — Rejected due to higher cost, no scale-to-zero

---

## Implementation Plan

### Phase 1: Redis Operation Store (2-3 hours)

**Goal:** Replace in-memory operation dict with Redis for stateless API.

#### 1.1 Create Abstract Store Interface

```python
# app/services/operation_store.py
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

class OperationStore(ABC):
    @abstractmethod
    async def save(self, operation_id: str, state: dict) -> None:
        """Save operation state."""
        pass
    
    @abstractmethod
    async def get(self, operation_id: str) -> Optional[dict]:
        """Get operation state, None if not found or expired."""
        pass
    
    @abstractmethod
    async def delete(self, operation_id: str) -> bool:
        """Delete operation, return True if existed."""
        pass
```

#### 1.2 Implement Redis Store

```python
# app/services/redis_operation_store.py
import json
import redis.asyncio as redis
from typing import Optional
from app.services.operation_store import OperationStore

class RedisOperationStore(OperationStore):
    def __init__(self, redis_url: str, ttl_seconds: int = 60):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl_seconds
        self.prefix = "km:op:"
    
    async def save(self, operation_id: str, state: dict) -> None:
        key = f"{self.prefix}{operation_id}"
        # Only set TTL after terminal state
        if state.get("status") in ("succeeded", "failed"):
            await self.redis.setex(key, self.ttl, json.dumps(state))
        else:
            await self.redis.set(key, json.dumps(state))
    
    async def get(self, operation_id: str) -> Optional[dict]:
        key = f"{self.prefix}{operation_id}"
        data = await self.redis.get(key)
        return json.loads(data) if data else None
    
    async def delete(self, operation_id: str) -> bool:
        key = f"{self.prefix}{operation_id}"
        return await self.redis.delete(key) > 0
    
    async def close(self):
        await self.redis.close()
```

#### 1.3 Keep In-Memory Store for Local Dev

```python
# app/services/memory_operation_store.py
from typing import Optional
from datetime import datetime, timedelta
from app.services.operation_store import OperationStore

class MemoryOperationStore(OperationStore):
    def __init__(self, ttl_seconds: int = 60):
        self._store: dict = {}
        self.ttl = ttl_seconds
    
    async def save(self, operation_id: str, state: dict) -> None:
        self._store[operation_id] = {
            "state": state,
            "expires_at": datetime.utcnow() + timedelta(seconds=self.ttl)
                if state.get("status") in ("succeeded", "failed") else None
        }
    
    async def get(self, operation_id: str) -> Optional[dict]:
        entry = self._store.get(operation_id)
        if not entry:
            return None
        if entry["expires_at"] and datetime.utcnow() > entry["expires_at"]:
            del self._store[operation_id]
            return None
        return entry["state"]
    
    async def delete(self, operation_id: str) -> bool:
        if operation_id in self._store:
            del self._store[operation_id]
            return True
        return False
```

#### 1.4 Factory Function with Auto-Detection

```python
# app/services/operation_store.py (add to bottom)
import os
from app.services.operation_store import OperationStore

def get_operation_store() -> OperationStore:
    """Get appropriate store based on environment."""
    redis_url = os.getenv("REDIS_URL")
    
    if redis_url:
        from app.services.redis_operation_store import RedisOperationStore
        return RedisOperationStore(redis_url)
    else:
        from app.services.memory_operation_store import MemoryOperationStore
        return MemoryOperationStore()
```

#### 1.5 Update knowledge_map.py Router

```python
# Replace global dict with store instance
from app.services.operation_store import get_operation_store

store = get_operation_store()

# Update all operations[operation_id] = ... to:
await store.save(operation_id, state)

# Update all operations.get(operation_id) to:
state = await store.get(operation_id)
```

#### 1.6 Add redis Dependency

```bash
# requirements.txt
redis>=5.0.0
```

---

### Phase 2: Containerization (1-2 hours)

**Goal:** Create production-ready Docker image.

#### 2.1 Dockerfile

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 2.2 .dockerignore

```
__pycache__
*.pyc
.git
.env
*.md
tests/
scripts/
bench_*.txt
```

#### 2.3 Local Testing

```bash
# Build
docker build -t knowledge-map-api:local .

# Run with local Redis
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -p 8000:8000 \
    -e REDIS_URL=redis://host.docker.internal:6379 \
    -e AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=... \
    -e AZURE_DOCUMENT_INTELLIGENCE_KEY=... \
    knowledge-map-api:local

# Test
curl http://localhost:8000/health
```

---

### Phase 3: Azure Deployment (2-3 hours)

**Goal:** Deploy to Container Apps with Redis and Easy Auth.

#### 3.1 Create Azure Resources

```bash
# Variables
RG="knowledge-map-rg"
LOCATION="westus"
ENV_NAME="knowledge-map-env"
APP_NAME="knowledge-map-api"
REDIS_NAME="km-redis"
ACR_NAME="kmapiacr"

# Resource Group
az group create --name $RG --location $LOCATION

# Container Registry
az acr create --resource-group $RG --name $ACR_NAME --sku Basic
az acr login --name $ACR_NAME

# Redis Cache (Basic tier, ~$15/month)
az redis create \
    --resource-group $RG \
    --name $REDIS_NAME \
    --location $LOCATION \
    --sku Basic \
    --vm-size c0

# Get Redis connection string
REDIS_KEY=$(az redis list-keys --resource-group $RG --name $REDIS_NAME --query primaryKey -o tsv)
REDIS_HOST=$(az redis show --resource-group $RG --name $REDIS_NAME --query hostName -o tsv)
REDIS_URL="rediss://:${REDIS_KEY}@${REDIS_HOST}:6380/0"
```

#### 3.2 Push Docker Image

```bash
# Tag and push
docker tag knowledge-map-api:local $ACR_NAME.azurecr.io/knowledge-map-api:v1
docker push $ACR_NAME.azurecr.io/knowledge-map-api:v1
```

#### 3.3 Create Container Apps Environment

```bash
# Container Apps Environment
az containerapp env create \
    --name $ENV_NAME \
    --resource-group $RG \
    --location $LOCATION

# Create Container App
az containerapp create \
    --name $APP_NAME \
    --resource-group $RG \
    --environment $ENV_NAME \
    --image $ACR_NAME.azurecr.io/knowledge-map-api:v1 \
    --registry-server $ACR_NAME.azurecr.io \
    --target-port 8000 \
    --ingress external \
    --min-replicas 0 \
    --max-replicas 10 \
    --cpu 1.0 \
    --memory 2Gi \
    --secrets \
        redis-url="$REDIS_URL" \
        di-endpoint="$AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT" \
        di-key="$AZURE_DOCUMENT_INTELLIGENCE_KEY" \
    --env-vars \
        REDIS_URL=secretref:redis-url \
        AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=secretref:di-endpoint \
        AZURE_DOCUMENT_INTELLIGENCE_KEY=secretref:di-key
```

#### 3.4 Enable Easy Auth (Optional)

```bash
# Enable Azure AD authentication
az containerapp auth update \
    --name $APP_NAME \
    --resource-group $RG \
    --unauthenticated-client-action RedirectToLoginPage \
    --enabled true
```

Or for API key auth, add custom middleware in FastAPI.

#### 3.5 Get Deployment URL

```bash
az containerapp show \
    --name $APP_NAME \
    --resource-group $RG \
    --query properties.configuration.ingress.fqdn -o tsv

# Output: knowledge-map-api.proudpond-12345678.westus.azurecontainerapps.io
```

---

### Phase 4: Testing & Validation (1 hour)

#### 4.1 Health Check

```bash
curl https://knowledge-map-api.proudpond-xxx.westus.azurecontainerapps.io/health
```

#### 4.2 End-to-End Test

```bash
# Submit
curl -X POST "https://knowledge-map-api.../api/v1/knowledge-map/process" \
    -H "Content-Type: application/json" \
    -d '{"inputs": [{"source": "https://your-blob.blob.core.windows.net/docs/test.pdf"}]}'

# Poll
curl "https://knowledge-map-api.../api/v1/knowledge-map/operations/{operation_id}"
```

#### 4.3 Scale Test

```bash
# Submit 10 concurrent batches
for i in {1..10}; do
    curl -X POST "https://knowledge-map-api.../api/v1/knowledge-map/process" \
        -H "Content-Type: application/json" \
        -d '{"inputs": [{"source": "https://..."}]}' &
done
wait

# Check Container Apps scaled up
az containerapp revision list \
    --name $APP_NAME \
    --resource-group $RG \
    --query "[].properties.replicas"
```

---

## Cost Estimate

| Resource | SKU | Monthly Cost |
|----------|-----|--------------|
| Container Apps | Consumption (0-10 replicas) | $30-50 |
| Azure Redis Cache | Basic C0 | $15 |
| Container Registry | Basic | $5 |
| Azure DI (existing) | Pay-per-use | Variable |
| **Total** | | **~$50-70** |

*Note: APIM (if added later) would add $50-500/month depending on tier.*

---

## Future Enhancements (Post-MVP)

1. **Add APIM** — When external clients need:
   - Rate limiting per subscription
   - Developer portal with API docs
   - OAuth2/OpenID Connect
   - Request/response transformation

2. **Add Monitoring** — Azure Monitor + Application Insights integration

3. **Add CI/CD** — GitHub Actions workflow for automated deployment

4. **Multi-region** — Deploy to East US for redundancy

---

## Implementation Timeline

| Phase | Task | Estimated Time |
|-------|------|----------------|
| 1 | Redis Operation Store | 2-3 hours |
| 2 | Containerization | 1-2 hours |
| 3 | Azure Deployment | 2-3 hours |
| 4 | Testing & Validation | 1 hour |
| **Total** | | **6-9 hours** |

---

## Dependencies

- Azure subscription with Container Apps enabled
- Azure Document Intelligence resource (already have: West US)
- Docker installed locally for testing
- Azure CLI installed and authenticated

---

## References

- [Azure Container Apps Documentation](https://learn.microsoft.com/en-us/azure/container-apps/)
- [Azure Redis Cache Quick Start](https://learn.microsoft.com/en-us/azure/azure-cache-for-redis/quickstart-create-redis)
- [Container Apps Easy Auth](https://learn.microsoft.com/en-us/azure/container-apps/authentication)
- [Knowledge Map API Guide](./KNOWLEDGE_MAP_API_GUIDE.md)
