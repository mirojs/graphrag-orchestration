# Knowledge Map Document Processing API Guide

**Version:** 1.0  
**Last Updated:** January 27, 2026

## Overview

The Knowledge Map API provides an asynchronous batch document processing interface. It follows the same polling pattern as [Azure Content Understanding](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/quickstart/use-rest-api) but with a simplified response structure designed for knowledge graph construction.

**Key Characteristics:**
- **Async Polling Pattern:** Submit batch → Poll for completion → Retrieve results
- **Batch-First Design:** All requests accept arrays (single doc = array of 1)
- **Fail-Fast Errors:** Any document failure stops entire batch (no partial results)
- **60-Second TTL:** Results expire 60 seconds after completion

---

## Quick Start

### 1. Submit a Processing Job

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge-map/process" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {"source": "https://your-storage.blob.core.windows.net/docs/contract.pdf"}
    ]
  }'
```

**Response:**
```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "pending"
}
```

### 2. Poll for Status

```bash
curl "http://localhost:8000/api/v1/knowledge-map/operations/km-1706356800-a1b2c3d4"
```

**Response (while processing):**
```http
HTTP/1.1 200 OK
Retry-After: 2

{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "running",
  "created_at": "2026-01-27T10:00:00Z"
}
```

### 3. Retrieve Results

Poll until `status` is `succeeded` or `failed`:

```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "succeeded",
  "created_at": "2026-01-27T10:00:00Z",
  "completed_at": "2026-01-27T10:00:12Z",
  "documents": [
    {
      "id": "doc-0",
      "source": "https://your-storage.blob.core.windows.net/docs/contract.pdf",
      "markdown": "# Service Agreement\n\nThis Agreement is entered into...",
      "chunks": [...],
      "metadata": {
        "page_count": 12,
        "language": "en",
        "tables_found": 3
      }
    }
  ]
}
```

---

## API Reference

### Base URL

```
http://localhost:8000/api/v1/knowledge-map
```

For production deployments:
```
https://your-service.azurecontainerapps.io/api/v1/knowledge-map
```

---

### POST /process

Submit documents for batch processing.

#### Request

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `Content-Type` | Yes | Must be `application/json` |
| `Authorization` | Conditional | Required if `KNOWLEDGE_MAP_AUTH_ENABLED=true` |

**Body:**
```json
{
  "inputs": [
    {
      "source": "string (URL to document)"
    }
  ],
  "options": {
    "enable_section_chunking": true,
    "model": "prebuilt-layout"
  }
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `inputs` | array | Yes | Array of document sources (1 or more) |
| `inputs[].source` | string | Yes | URL to the document (must be accessible) |
| `options` | object | No | Processing options |
| `options.enable_section_chunking` | boolean | No | Enable section-aware chunking (default: true) |
| `options.model` | string | No | Azure DI model: `prebuilt-layout`, `prebuilt-invoice`, etc. |

#### Response

**Success (202 Accepted):**
```json
{
  "operation_id": "km-{timestamp}-{random}",
  "status": "pending"
}
```

**Error (400 Bad Request):**
```json
{
  "detail": "No inputs provided"
}
```

**Error (422 Validation Error):**
```json
{
  "detail": [
    {
      "loc": ["body", "inputs", 0, "source"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

### GET /operations/{operation_id}

Poll operation status and retrieve results.

#### Request

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `operation_id` | string | The operation ID returned from POST /process |

#### Response Headers

| Header | Description |
|--------|-------------|
| `Retry-After` | Seconds to wait before next poll (present when status is `pending` or `running`) |

#### Response Body

**Status: `pending`** (job queued, not started)
```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "pending",
  "created_at": "2026-01-27T10:00:00Z"
}
```

**Status: `running`** (processing in progress)
```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "running",
  "created_at": "2026-01-27T10:00:00Z"
}
```

**Status: `succeeded`** (completed successfully)
```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "succeeded",
  "created_at": "2026-01-27T10:00:00Z",
  "completed_at": "2026-01-27T10:00:12Z",
  "documents": [
    {
      "id": "doc-0",
      "source": "https://example.com/document.pdf",
      "markdown": "# Document Title\n\nFull markdown content...",
      "chunks": [
        {
          "content": "Chunk text content...",
          "page_numbers": [1, 2],
          "section_hierarchy": ["1.0 Introduction", "1.1 Background"]
        }
      ],
      "metadata": {
        "page_count": 12,
        "language": "en",
        "tables_found": 3,
        "figures_found": 2,
        "key_value_pairs_found": 5
      }
    }
  ]
}
```

**Status: `failed`** (processing error)
```json
{
  "operation_id": "km-1706356800-a1b2c3d4",
  "status": "failed",
  "created_at": "2026-01-27T10:00:00Z",
  "completed_at": "2026-01-27T10:00:05Z",
  "error": {
    "code": "DocumentProcessingError",
    "message": "Failed to process document at index 0: HTTP 403 - Access denied to blob storage"
  }
}
```

**Error: Operation Not Found (404)**
```json
{
  "detail": "Operation km-invalid-id not found"
}
```

**Error: Operation Expired (410 Gone)**
```json
{
  "detail": "Operation km-1706356800-a1b2c3d4 has expired (TTL: 60s after completion)"
}
```

---

### DELETE /operations/{operation_id}

Delete an operation and free resources (optional cleanup).

#### Request

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `operation_id` | string | The operation ID to delete |

#### Response

**Success (204 No Content):**
No body returned.

**Error (404 Not Found):**
```json
{
  "detail": "Operation not found"
}
```

---

## Status Codes Summary

| Status Code | Meaning |
|-------------|---------|
| `200 OK` | Operation status retrieved successfully |
| `202 Accepted` | Processing job submitted successfully |
| `204 No Content` | Operation deleted successfully |
| `400 Bad Request` | Invalid request body |
| `404 Not Found` | Operation ID not found |
| `410 Gone` | Operation expired (TTL exceeded) |
| `422 Unprocessable Entity` | Validation error in request |
| `500 Internal Server Error` | Server-side processing error |

---

## Operation Lifecycle

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   pending   │ ──► │   running   │ ──► │  succeeded  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                           │                    │
                           │                    ▼
                           │              ┌───────────┐
                           └─────────────►│  failed   │
                                          └───────────┘
                                                │
                              After 60 seconds: │
                                                ▼
                                          ┌───────────┐
                                          │  expired  │
                                          └───────────┘
```

**State Transitions:**
1. `pending` → `running`: Background task started processing
2. `running` → `succeeded`: All documents processed successfully
3. `running` → `failed`: Any document failed (fail-fast)
4. Terminal states (`succeeded`/`failed`) → `expired`: After 60 seconds TTL

---

## Polling Best Practices

### Recommended Polling Strategy

```python
import time
import requests

def poll_operation(base_url: str, operation_id: str, timeout: int = 300) -> dict:
    """Poll operation until completion or timeout."""
    start_time = time.time()
    url = f"{base_url}/operations/{operation_id}"
    
    while True:
        response = requests.get(url)
        
        if response.status_code == 410:
            raise Exception("Operation expired before retrieval")
        
        if response.status_code != 200:
            raise Exception(f"Unexpected status: {response.status_code}")
        
        result = response.json()
        status = result["status"]
        
        if status in ("succeeded", "failed"):
            return result
        
        # Check timeout
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Operation did not complete within {timeout}s")
        
        # Use Retry-After header or default to 2 seconds
        retry_after = int(response.headers.get("Retry-After", 2))
        time.sleep(retry_after)
```

### Polling Guidelines

| Document Count | Expected Time | Recommended Timeout |
|----------------|---------------|---------------------|
| 1-5 documents | 5-30 seconds | 60 seconds |
| 5-20 documents | 30-120 seconds | 180 seconds |
| 20+ documents | 2-10 minutes | 600 seconds |

**Tips:**
- Always respect the `Retry-After` header
- Use exponential backoff if `Retry-After` is missing
- Set reasonable timeouts to avoid indefinite waiting
- Retrieve results immediately after `succeeded` (60s TTL)

---

## Batch Processing Examples

### Single Document

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge-map/process" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {"source": "https://storage.blob.core.windows.net/docs/invoice.pdf"}
    ]
  }'
```

### Multiple Documents

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge-map/process" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {"source": "https://storage.blob.core.windows.net/docs/contract1.pdf"},
      {"source": "https://storage.blob.core.windows.net/docs/contract2.pdf"},
      {"source": "https://storage.blob.core.windows.net/docs/invoice.pdf"},
      {"source": "https://storage.blob.core.windows.net/docs/receipt.pdf"},
      {"source": "https://storage.blob.core.windows.net/docs/agreement.pdf"}
    ]
  }'
```

### With Processing Options

```bash
curl -X POST "http://localhost:8000/api/v1/knowledge-map/process" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": [
      {"source": "https://storage.blob.core.windows.net/docs/invoice.pdf"}
    ],
    "options": {
      "model": "prebuilt-invoice",
      "enable_section_chunking": false
    }
  }'
```

---

## Python Client Example

```python
import requests
import time
from typing import Optional


class KnowledgeMapClient:
    """Client for Knowledge Map Document Processing API."""
    
    def __init__(self, base_url: str = "http://localhost:8000/api/v1/knowledge-map"):
        self.base_url = base_url
    
    def process_documents(
        self,
        sources: list[str],
        options: Optional[dict] = None,
        timeout: int = 300
    ) -> dict:
        """
        Process documents and wait for results.
        
        Args:
            sources: List of document URLs
            options: Optional processing options
            timeout: Maximum seconds to wait for completion
            
        Returns:
            Complete operation result with documents
        """
        # Submit batch
        payload = {
            "inputs": [{"source": url} for url in sources]
        }
        if options:
            payload["options"] = options
        
        response = requests.post(f"{self.base_url}/process", json=payload)
        response.raise_for_status()
        
        operation_id = response.json()["operation_id"]
        
        # Poll for completion
        return self._poll_until_complete(operation_id, timeout)
    
    def _poll_until_complete(self, operation_id: str, timeout: int) -> dict:
        """Poll operation until terminal state."""
        start_time = time.time()
        
        while True:
            response = requests.get(f"{self.base_url}/operations/{operation_id}")
            
            if response.status_code == 410:
                raise Exception("Operation expired")
            
            response.raise_for_status()
            result = response.json()
            
            if result["status"] in ("succeeded", "failed"):
                return result
            
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Timeout after {timeout}s")
            
            retry_after = int(response.headers.get("Retry-After", 2))
            time.sleep(retry_after)


# Usage
client = KnowledgeMapClient()

# Process single document
result = client.process_documents([
    "https://storage.blob.core.windows.net/docs/contract.pdf"
])

if result["status"] == "succeeded":
    for doc in result["documents"]:
        print(f"Document: {doc['source']}")
        print(f"Pages: {doc['metadata']['page_count']}")
        print(f"Content preview: {doc['markdown'][:200]}...")
else:
    print(f"Error: {result['error']['message']}")
```

---

## TypeScript/JavaScript Client Example

```typescript
interface ProcessInput {
  source: string;
}

interface ProcessOptions {
  model?: string;
  enable_section_chunking?: boolean;
}

interface OperationResult {
  operation_id: string;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  created_at: string;
  completed_at?: string;
  documents?: DocumentResult[];
  error?: { code: string; message: string };
}

interface DocumentResult {
  id: string;
  source: string;
  markdown: string;
  chunks: ChunkResult[];
  metadata: Record<string, any>;
}

interface ChunkResult {
  content: string;
  page_numbers: number[];
  section_hierarchy: string[];
}

async function processDocuments(
  baseUrl: string,
  sources: string[],
  options?: ProcessOptions,
  timeoutMs: number = 300000
): Promise<OperationResult> {
  // Submit batch
  const submitResponse = await fetch(`${baseUrl}/process`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      inputs: sources.map(source => ({ source })),
      options
    })
  });
  
  if (!submitResponse.ok) {
    throw new Error(`Submit failed: ${submitResponse.status}`);
  }
  
  const { operation_id } = await submitResponse.json();
  
  // Poll for completion
  const startTime = Date.now();
  
  while (true) {
    const pollResponse = await fetch(`${baseUrl}/operations/${operation_id}`);
    
    if (pollResponse.status === 410) {
      throw new Error('Operation expired');
    }
    
    if (!pollResponse.ok) {
      throw new Error(`Poll failed: ${pollResponse.status}`);
    }
    
    const result: OperationResult = await pollResponse.json();
    
    if (result.status === 'succeeded' || result.status === 'failed') {
      return result;
    }
    
    if (Date.now() - startTime > timeoutMs) {
      throw new Error('Timeout');
    }
    
    const retryAfter = parseInt(pollResponse.headers.get('Retry-After') || '2', 10);
    await new Promise(resolve => setTimeout(resolve, retryAfter * 1000));
  }
}

// Usage
const result = await processDocuments(
  'http://localhost:8000/api/v1/knowledge-map',
  ['https://storage.blob.core.windows.net/docs/contract.pdf']
);

if (result.status === 'succeeded') {
  for (const doc of result.documents!) {
    console.log(`Document: ${doc.source}`);
    console.log(`Pages: ${doc.metadata.page_count}`);
  }
}
```

---

## Error Handling

### Common Errors

| Error Code | Cause | Solution |
|------------|-------|----------|
| `DocumentProcessingError` | Azure DI failed to process document | Check document URL is accessible, format is supported |
| `AccessDenied` | Blob storage returned 403 | Verify SAS token or managed identity permissions |
| `InvalidDocumentFormat` | Unsupported file type | Use PDF, DOCX, XLSX, PNG, JPG, TIFF |
| `DocumentTooLarge` | File exceeds size limit | Split document or reduce resolution |
| `BackendUnavailable` | Azure DI/CU service unavailable | Retry later, check Azure status page |

### Fail-Fast Behavior

When processing multiple documents, **any failure stops the entire batch**:

```json
{
  "status": "failed",
  "error": {
    "code": "DocumentProcessingError",
    "message": "Failed to process document at index 2: HTTP 404 - Document not found"
  }
}
```

**Rationale:** Partial results complicate error recovery. It's better to:
1. Fix the failing document
2. Resubmit the entire batch
3. Get complete, consistent results

---

## Comparison with Azure Content Understanding

| Aspect | Azure Content Understanding | Knowledge Map API |
|--------|----------------------------|-------------------|
| **Submit Endpoint** | `POST /contentunderstanding/analyzers/{name}:analyze` | `POST /process` |
| **Poll Endpoint** | `GET /contentunderstanding/analyzers/{name}/results/{id}` | `GET /operations/{id}` |
| **Status Values** | `notStarted`, `running`, `succeeded`, `failed` | `pending`, `running`, `succeeded`, `failed` |
| **Retry Header** | `Retry-After: 5` | `Retry-After: 2` |
| **Response Structure** | Nested `contents[].fields` | Flat `documents[]` |
| **Schema Required** | Yes (analyzer definition) | No |
| **Partial Results** | Yes (some docs may succeed) | No (fail-fast) |
| **TTL** | Configurable | Fixed 60 seconds |
| **Authentication** | Azure AD / API Key | Optional (`KNOWLEDGE_MAP_AUTH_ENABLED`) |

### Migration from Azure CU

If you're migrating from Azure Content Understanding:

1. **Remove schema/analyzer setup** — Knowledge Map needs no pre-configuration
2. **Update endpoint paths** — See table above
3. **Flatten response handling** — Access `documents[]` directly instead of `contents[].fields`
4. **Handle fail-fast** — Add batch retry logic instead of individual document retry
5. **Respect TTL** — Retrieve results within 60 seconds of completion

---

## Configuration

### Environment Variables

```bash
# Knowledge Map API (Optional)
KNOWLEDGE_MAP_AUTH_ENABLED=false  # Set to true for APIM integration

# Azure Document Intelligence (Required - Primary Backend)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://westus.api.cognitive.microsoft.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-api-key

# Azure Content Understanding (Optional - Fallback Backend)
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=https://eastus.api.cognitive.microsoft.com/
AZURE_CONTENT_UNDERSTANDING_KEY=your-api-key
```

### Backend Priority

1. **Azure Document Intelligence** (if configured) — Preferred for layout-aware extraction
2. **Azure Content Understanding** (if DI unavailable) — Fallback option

---

## Health Check

Verify the API is running:

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

---

## See Also

- [Azure Content Understanding REST API](https://learn.microsoft.com/en-us/azure/ai-services/content-understanding/quickstart/use-rest-api)
- [Azure Document Intelligence](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/)
- [Simplified Document Analysis Service](./SIMPLIFIED_DOCUMENT_ANALYSIS.md) (sync API)
- [Architecture Design](../ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md#61-knowledge-map-document-processing-api-january-27-2026)
