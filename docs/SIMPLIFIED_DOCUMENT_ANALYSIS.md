# Simplified Document Analysis Service

## Overview

The Simplified Document Analysis Service provides a clean, unified API for document analysis that serves as a drop-in replacement for Azure Content Understanding. It abstracts the complexity of choosing between different backends and provides a consistent interface for document processing.

## Features

- **Unified API**: Single interface for document analysis regardless of backend
- **Automatic Backend Selection**: Chooses the best available backend (Document Intelligence or Content Understanding)
- **Graceful Fallback**: Automatically falls back to alternative backends if primary fails
- **Batch Processing**: Process multiple documents concurrently with configurable limits
- **Transparent Authentication**: Handles both API key and managed identity authentication
- **Standardized Output**: Consistent response format across all backends
- **No Schema Complexity**: Removes unnecessary schema analyzer dependencies
- **Section-Aware Chunking**: Intelligent document chunking based on section hierarchy

## Architecture

### Backend Selection Logic

```
AUTO mode:
1. Check if Document Intelligence is configured → Use DI (preferred)
2. Check if Content Understanding is configured → Use CU
3. If neither configured → Raise error

Specific backend mode:
1. Validate requested backend is configured
2. Use requested backend
```

### Service Components

1. **SimpleDocumentAnalysisService**: Core service that manages backend selection and document processing
2. **DocumentAnalysisBackend**: Enum defining available backends (AUTO, DOCUMENT_INTELLIGENCE, CONTENT_UNDERSTANDING)
3. **DocumentAnalysisResult**: Standardized result dataclass

## API Endpoints

### POST `/api/v1/document-analysis/analyze`

Analyze documents from URLs or raw text content.

**Request Body:**
```json
{
  "urls": ["https://example.com/document.pdf"],
  "texts": ["Optional raw text content"],
  "enable_section_chunking": true,
  "backend": "auto",
  "max_concurrency": 5
}
```

**Response:**
```json
{
  "success": true,
  "backend_used": "document_intelligence",
  "documents_count": 1,
  "documents": [
    {
      "doc_id": "doc_123",
      "text_preview": "First 200 characters of document...",
      "metadata": {
        "page_count": 5,
        "section_count": 3,
        "table_count": 2
      }
    }
  ],
  "metadata": {
    "backend": "document_intelligence",
    "section_chunking_enabled": true,
    "total_urls": 1,
    "total_texts": 0,
    "documents_extracted": 1
  }
}
```

### POST `/api/v1/document-analysis/analyze-single`

Convenience endpoint for analyzing a single document.

**Query Parameters:**
- `url` (optional): Document URL
- `text` (optional): Raw text content
- `enable_section_chunking` (default: true): Enable section-aware chunking

**Response:**
Same as `/analyze` endpoint

### GET `/api/v1/document-analysis/backend-info`

Get information about available backends and configuration.

**Query Parameters:**
- `backend` (default: "auto"): Backend to check

**Response:**
```json
{
  "available_backends": ["document_intelligence", "content_understanding"],
  "selected_backend": null,
  "requested_backend": "auto",
  "max_concurrency": 5,
  "configuration": {
    "di_endpoint": true,
    "di_key": true,
    "cu_endpoint": true,
    "cu_key": true
  }
}
```

## Usage Examples

### Python Client

```python
import httpx

async def analyze_document(url: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/document-analysis/analyze",
            json={
                "urls": [url],
                "enable_section_chunking": True,
                "backend": "auto",
            }
        )
        result = response.json()
        
        if result["success"]:
            print(f"Extracted {result['documents_count']} documents")
            print(f"Using backend: {result['backend_used']}")
            for doc in result["documents"]:
                print(f"Document: {doc['doc_id']}")
                print(f"Preview: {doc['text_preview']}")
        else:
            print(f"Error: {result['error']}")

# Usage
await analyze_document("https://example.com/contract.pdf")
```

### cURL

```bash
# Analyze a document
curl -X POST "http://localhost:8000/api/v1/document-analysis/analyze" \
  -H "Content-Type: application/json" \
  -d '{
    "urls": ["https://example.com/document.pdf"],
    "backend": "auto",
    "max_concurrency": 5
  }'

# Check backend info
curl "http://localhost:8000/api/v1/document-analysis/backend-info?backend=auto"

# Analyze single document
curl -X POST "http://localhost:8000/api/v1/document-analysis/analyze-single?url=https://example.com/doc.pdf"
```

## Configuration

The service uses the following environment variables:

```bash
# Document Intelligence (Preferred)
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://your-di.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=your-di-key  # Optional with managed identity
AZURE_DOC_INTELLIGENCE_API_VERSION=2024-11-30

# Content Understanding (Fallback)
AZURE_CONTENT_UNDERSTANDING_ENDPOINT=https://your-cu.cognitiveservices.azure.com/
AZURE_CONTENT_UNDERSTANDING_API_KEY=your-cu-key  # Optional with managed identity
AZURE_CU_API_VERSION=2025-11-01
```

## Backend Comparison

| Feature | Document Intelligence | Content Understanding |
|---------|----------------------|---------------------|
| Stability | ✅ More mature | ⚠️ Less stable |
| Table Extraction | ✅ Better structure | ✅ Good |
| Bounding Boxes | ✅ Rich info | ⚠️ Limited |
| Batch Processing | ✅ Native support | ⚠️ Sequential |
| SDK Support | ✅ Official SDK | ⚠️ REST only |
| Managed Identity | ✅ Built-in | ✅ Supported |
| Section Chunking | ✅ V2 support | ✅ V2 support |

## Migration from Azure Content Understanding

The Simplified Document Analysis Service is designed as a drop-in replacement for Azure Content Understanding. To migrate:

1. **Update API calls**: Replace CU API calls with new `/api/v1/document-analysis/analyze` endpoint
2. **Configure backends**: Set environment variables for DI and/or CU
3. **Update response parsing**: Use standardized `DocumentAnalysisResult` format
4. **Remove schema dependencies**: No need for schema analyzers or converters

### Before (Direct CU API):
```python
from app.services.cu_standard_ingestion_service_v2 import CUStandardIngestionServiceV2

service = CUStandardIngestionServiceV2()
documents = await service.ingest_from_url(url)
```

### After (Simplified Service):
```python
from app.services.simple_document_analysis_service import SimpleDocumentAnalysisService

service = SimpleDocumentAnalysisService()
result = await service.analyze_documents(urls=[url])
if result.success:
    documents = result.documents
```

## Error Handling

The service provides graceful error handling:

- **No backends configured**: Returns clear error message
- **Backend unavailable**: Automatically tries fallback (in AUTO mode)
- **Individual document failures**: Continues processing other documents
- **Authentication errors**: Clear error messages about credentials

## Testing

Run the test suite:

```bash
pytest graphrag-orchestration/tests/test_simple_document_analysis_service.py -v
```

Tests cover:
- Backend selection logic
- Auto mode backend preference
- URL and text analysis
- Error handling
- Single document analysis
- Backend information retrieval

## Future Enhancements

Potential improvements:
- [ ] Add retry logic for transient failures
- [ ] Implement intelligent caching of analysis results
- [ ] Support for additional document formats
- [ ] Real-time progress tracking for batch operations
- [ ] Webhook support for async processing
- [ ] Cost tracking and reporting
- [ ] Enhanced metadata extraction

## Support

For issues or questions:
- Check logs for detailed error messages
- Verify environment variables are set correctly
- Use `/backend-info` endpoint to diagnose configuration
- Review Azure service health dashboards
