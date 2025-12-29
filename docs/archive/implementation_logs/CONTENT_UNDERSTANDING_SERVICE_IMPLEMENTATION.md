# Content Understanding Service - Implementation Plan

## Overview
Create a lightweight async service layer for Azure Content Understanding API, based on Azure samples pattern but using httpx.AsyncClient.

---

## File Structure

```
app/
├── services/
│   ├── __init__.py
│   ├── content_understanding_service.py  # Main service (NEW)
│   └── analyzer_templates/               # Analyzer templates (NEW)
│       ├── prebuilt_document.json
│       ├── prebuilt_invoice.json
│       └── custom_pro_mode_template.json
├── routers/
│   └── proMode.py                        # Simplified router (REFACTOR)
└── appsettings.py                        # Add service config (UPDATE)
```

---

## Implementation: content_understanding_service.py

### Complete Implementation

```python
"""
Azure Content Understanding Service
Based on Azure samples pattern: https://github.com/Azure-Samples/azure-ai-content-understanding-python
Adapted for async with httpx.AsyncClient
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import json

from httpx import AsyncClient, Response


class ContentUnderstandingService:
    """
    Lightweight async client for Azure Content Understanding API.
    
    Based on Azure samples AzureContentUnderstandingClient but:
    - Uses httpx.AsyncClient instead of requests
    - All methods are async
    - Integrated with our auth patterns
    """
    
    DEFAULT_API_VERSION = "2025-05-01-preview"
    DEFAULT_TIMEOUT = 180  # seconds
    DEFAULT_POLLING_INTERVAL = 2  # seconds
    
    def __init__(
        self,
        endpoint: str,
        api_version: str = DEFAULT_API_VERSION,
        subscription_key: Optional[str] = None,
        token_provider: Optional[callable] = None,
        timeout: int = 300,
    ):
        """
        Initialize Content Understanding service.
        
        Args:
            endpoint: Azure AI endpoint (e.g., https://xxx.cognitiveservices.azure.com)
            api_version: API version (default: 2025-05-01-preview)
            subscription_key: Optional subscription key for auth
            token_provider: Optional callable that returns auth token
            timeout: HTTP client timeout in seconds
            
        Note: Either subscription_key OR token_provider must be provided
        """
        if not subscription_key and not token_provider:
            raise ValueError("Either subscription_key or token_provider must be provided")
        
        self.endpoint = endpoint.rstrip("/")
        self.api_version = api_version
        self._subscription_key = subscription_key
        self._token_provider = token_provider
        self._client = AsyncClient(timeout=timeout)
        self._logger = logging.getLogger(__name__)
    
    async def close(self):
        """Close the HTTP client"""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    # ==================== Helper Methods ====================
    
    def _get_headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        """Build request headers with authentication"""
        headers = {}
        
        if self._token_provider:
            token = self._token_provider()
            headers["Authorization"] = f"Bearer {token}"
        
        if self._subscription_key:
            headers["Ocp-Apim-Subscription-Key"] = self._subscription_key
        
        if content_type:
            headers["Content-Type"] = content_type
        
        return headers
    
    def _get_analyzer_url(self, analyzer_id: str) -> str:
        """Build analyzer detail URL"""
        return f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}?api-version={self.api_version}"
    
    def _get_analyzers_list_url(self) -> str:
        """Build analyzer list URL"""
        return f"{self.endpoint}/contentunderstanding/analyzers?api-version={self.api_version}"
    
    def _get_analyze_url(self, analyzer_id: str) -> str:
        """Build analyze endpoint URL"""
        return f"{self.endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze?api-version={self.api_version}"
    
    # ==================== Core Analysis Methods ====================
    
    async def begin_analyze(
        self,
        analyzer_id: str,
        file_data: Optional[bytes] = None,
        file_url: Optional[str] = None,
        multiple_files: Optional[List[Dict[str, Any]]] = None,
    ) -> Response:
        """
        Start document analysis operation.
        
        Args:
            analyzer_id: ID of analyzer to use (e.g., "prebuilt-documentAnalyzer")
            file_data: Binary file data for single file upload
            file_url: URL to file for analysis
            multiple_files: List of files for Pro mode (format: [{"name": "...", "data": base64}])
        
        Returns:
            Response object with operation-location header
            
        Raises:
            ValueError: If no file source provided
            HTTPError: If request fails
        """
        url = self._get_analyze_url(analyzer_id)
        
        if file_data:
            # Binary upload
            headers = self._get_headers(content_type="application/octet-stream")
            response = await self._client.post(url, headers=headers, content=file_data)
            
        elif file_url:
            # URL reference
            headers = self._get_headers(content_type="application/json")
            response = await self._client.post(url, headers=headers, json={"url": file_url})
            
        elif multiple_files:
            # Pro mode: multiple files
            headers = self._get_headers(content_type="application/json")
            response = await self._client.post(
                url, 
                headers=headers, 
                json={"inputs": multiple_files}
            )
            
        else:
            raise ValueError("Must provide file_data, file_url, or multiple_files")
        
        response.raise_for_status()
        self._logger.info(f"Started analysis with analyzer: {analyzer_id}")
        return response
    
    async def poll_result(
        self,
        response: Response,
        timeout_seconds: int = DEFAULT_TIMEOUT,
        polling_interval_seconds: int = DEFAULT_POLLING_INTERVAL,
    ) -> Dict[str, Any]:
        """
        Poll operation until complete.
        
        Args:
            response: Response from begin_analyze() or begin_create_analyzer()
            timeout_seconds: Maximum time to wait (default: 180)
            polling_interval_seconds: Time between polls (default: 2)
        
        Returns:
            Result dictionary with status and result data
            
        Raises:
            ValueError: If no operation-location header
            TimeoutError: If operation doesn't complete in time
            Exception: If operation fails
        """
        operation_location = response.headers.get("Operation-Location")
        if not operation_location:
            # Some operations return result immediately
            try:
                return response.json()
            except:
                raise ValueError("No operation-location header and no JSON response")
        
        deadline = datetime.now() + timedelta(seconds=timeout_seconds)
        poll_count = 0
        
        while datetime.now() < deadline:
            poll_count += 1
            
            poll_response = await self._client.get(
                operation_location,
                headers=self._get_headers()
            )
            poll_response.raise_for_status()
            result = poll_response.json()
            
            status = result.get("status", "").lower()
            
            if status == "succeeded":
                self._logger.info(f"Operation succeeded after {poll_count} polls")
                return result
                
            elif status == "failed":
                error = result.get("error", {})
                error_message = error.get("message", "Unknown error")
                self._logger.error(f"Operation failed: {error_message}")
                raise Exception(f"Analysis failed: {error_message}")
            
            # Status is still "running" or similar
            await asyncio.sleep(polling_interval_seconds)
        
        raise TimeoutError(
            f"Operation did not complete within {timeout_seconds} seconds "
            f"(polled {poll_count} times)"
        )
    
    # ==================== Analyzer Management ====================
    
    async def get_all_analyzers(self) -> Dict[str, Any]:
        """
        List all available analyzers.
        
        Returns:
            Dictionary with "value" key containing list of analyzers
        """
        url = self._get_analyzers_list_url()
        response = await self._client.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()
    
    async def get_analyzer(self, analyzer_id: str) -> Dict[str, Any]:
        """
        Get details of specific analyzer.
        
        Args:
            analyzer_id: ID of analyzer to retrieve
            
        Returns:
            Analyzer details dictionary
        """
        url = self._get_analyzer_url(analyzer_id)
        response = await self._client.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()
    
    async def begin_create_analyzer(
        self,
        analyzer_id: str,
        analyzer_template: Optional[Dict[str, Any]] = None,
        analyzer_template_path: Optional[str] = None,
        training_container_sas_url: Optional[str] = None,
        training_container_prefix: Optional[str] = None,
        knowledge_sources_container_sas_url: Optional[str] = None,
        knowledge_sources_prefix: Optional[str] = None,
    ) -> Response:
        """
        Create custom analyzer.
        
        Args:
            analyzer_id: Unique ID for new analyzer
            analyzer_template: Analyzer schema dict
            analyzer_template_path: Path to JSON template file
            training_container_sas_url: SAS URL for training data (standard mode)
            training_container_prefix: Path prefix in training container
            knowledge_sources_container_sas_url: SAS URL for knowledge sources (pro mode)
            knowledge_sources_prefix: Path prefix in knowledge sources container
        
        Returns:
            Response with operation-location for polling
            
        Raises:
            ValueError: If neither template nor template_path provided
        """
        # Load template
        if analyzer_template_path:
            with open(analyzer_template_path, 'r') as f:
                analyzer_template = json.load(f)
        
        if not analyzer_template:
            raise ValueError("Must provide analyzer_template or analyzer_template_path")
        
        # Add training data if provided (standard mode)
        if training_container_sas_url and training_container_prefix:
            prefix = training_container_prefix.rstrip('/') + '/'
            analyzer_template["trainingData"] = {
                "containerUrl": training_container_sas_url,
                "kind": "blob",
                "prefix": prefix,
            }
        
        # Add knowledge sources if provided (pro mode)
        if knowledge_sources_container_sas_url and knowledge_sources_prefix:
            prefix = knowledge_sources_prefix.rstrip('/') + '/'
            analyzer_template["knowledgeSources"] = [{
                "kind": "reference",
                "containerUrl": knowledge_sources_container_sas_url,
                "prefix": prefix,
                "fileListPath": "sources.jsonl",
            }]
        
        # Create analyzer
        url = self._get_analyzer_url(analyzer_id)
        headers = self._get_headers(content_type="application/json")
        response = await self._client.put(
            url,
            headers=headers,
            json=analyzer_template
        )
        response.raise_for_status()
        self._logger.info(f"Created analyzer: {analyzer_id}")
        return response
    
    async def delete_analyzer(self, analyzer_id: str) -> None:
        """
        Delete analyzer.
        
        Args:
            analyzer_id: ID of analyzer to delete
        """
        url = self._get_analyzer_url(analyzer_id)
        response = await self._client.delete(url, headers=self._get_headers())
        response.raise_for_status()
        self._logger.info(f"Deleted analyzer: {analyzer_id}")
    
    # ==================== Convenience Methods ====================
    
    async def analyze_and_wait(
        self,
        analyzer_id: str,
        file_data: Optional[bytes] = None,
        file_url: Optional[str] = None,
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        Convenience method: analyze and wait for result.
        
        Args:
            analyzer_id: ID of analyzer to use
            file_data: Binary file data
            file_url: URL to file
            timeout_seconds: Maximum wait time
            
        Returns:
            Complete analysis result
        """
        response = await self.begin_analyze(
            analyzer_id=analyzer_id,
            file_data=file_data,
            file_url=file_url
        )
        return await self.poll_result(response, timeout_seconds=timeout_seconds)
    
    async def create_analyzer_and_wait(
        self,
        analyzer_id: str,
        analyzer_template: Dict[str, Any],
        timeout_seconds: int = DEFAULT_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        Convenience method: create analyzer and wait for completion.
        
        Args:
            analyzer_id: ID for new analyzer
            analyzer_template: Analyzer schema
            timeout_seconds: Maximum wait time
            
        Returns:
            Analyzer creation result
        """
        response = await self.begin_create_analyzer(
            analyzer_id=analyzer_id,
            analyzer_template=analyzer_template
        )
        return await self.poll_result(response, timeout_seconds=timeout_seconds)
```

---

## Example Analyzer Templates

### 1. Prebuilt Document Analyzer (prebuilt_document.json)
```json
{
  "description": "Prebuilt document analyzer for general content extraction",
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "config": {
    "returnDetails": true,
    "enableOcr": true,
    "enableLayout": true,
    "enableFormula": false,
    "disableContentFiltering": false,
    "estimateFieldSourceAndConfidence": false
  },
  "mode": "standard"
}
```

### 2. Custom Invoice Analyzer (custom_invoice.json)
```json
{
  "description": "Custom invoice field extraction",
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "mode": "standard",
  "fieldSchema": {
    "InvoiceNumber": {
      "type": "string",
      "description": "Invoice number from the document"
    },
    "InvoiceDate": {
      "type": "date",
      "description": "Date the invoice was issued"
    },
    "TotalAmount": {
      "type": "number",
      "description": "Total amount due on invoice"
    },
    "VendorName": {
      "type": "string",
      "description": "Name of the vendor or supplier"
    }
  }
}
```

### 3. Pro Mode Template (custom_pro_mode_template.json)
```json
{
  "description": "Pro mode analyzer with AI reasoning",
  "baseAnalyzerId": "prebuilt-documentAnalyzer",
  "mode": "pro",
  "fieldSchema": {
    "ContractValue": {
      "type": "number",
      "method": "extract",
      "description": "Total contract value"
    },
    "PaymentTerms": {
      "type": "string",
      "method": "extract",
      "description": "Payment terms and conditions"
    },
    "ComplianceIssues": {
      "type": "array",
      "items": {"type": "string"},
      "method": "generate",
      "description": "List any compliance issues found by comparing against reference documents"
    }
  }
}
```

---

## Usage Examples

### Example 1: Simple Document Analysis
```python
from app.services.content_understanding_service import ContentUnderstandingService

async def analyze_document(file_data: bytes):
    service = ContentUnderstandingService(
        endpoint=config.azure_ai_endpoint,
        api_version="2025-05-01-preview",
        token_provider=get_token,
        subscription_key=config.subscription_key,
    )
    
    try:
        # Analyze and wait for result
        result = await service.analyze_and_wait(
            analyzer_id="prebuilt-documentAnalyzer",
            file_data=file_data
        )
        return result
    finally:
        await service.close()
```

### Example 2: Using Context Manager
```python
async def analyze_with_context(file_data: bytes):
    async with ContentUnderstandingService(
        endpoint=config.azure_ai_endpoint,
        api_version="2025-05-01-preview",
        token_provider=get_token,
    ) as service:
        result = await service.analyze_and_wait(
            analyzer_id="prebuilt-documentAnalyzer",
            file_data=file_data
        )
        return result
```

### Example 3: Manual Polling (More Control)
```python
async def analyze_with_manual_polling(file_data: bytes):
    service = ContentUnderstandingService(...)
    
    try:
        # Start analysis
        response = await service.begin_analyze(
            analyzer_id="prebuilt-documentAnalyzer",
            file_data=file_data
        )
        
        # Poll with custom timeout
        result = await service.poll_result(
            response,
            timeout_seconds=300,  # 5 minutes
            polling_interval_seconds=5  # Check every 5 seconds
        )
        
        return result
    finally:
        await service.close()
```

### Example 4: Create Custom Analyzer
```python
async def create_custom_analyzer():
    service = ContentUnderstandingService(...)
    
    template = {
        "description": "Custom invoice analyzer",
        "baseAnalyzerId": "prebuilt-documentAnalyzer",
        "mode": "standard",
        "fieldSchema": {
            "InvoiceNumber": {
                "type": "string",
                "description": "Invoice number"
            }
        }
    }
    
    result = await service.create_analyzer_and_wait(
        analyzer_id="my-custom-analyzer",
        analyzer_template=template
    )
    
    return result
```

---

## Router Refactoring Example

### BEFORE (Current proMode.py)
```python
# 500+ lines of manual everything
async def analyze_document():
    # Manual token refresh
    token = await get_fresh_token()
    
    # Manual endpoint construction
    url = f"{endpoint}/contentunderstanding/analyzers/{analyzer_id}:analyze?api-version=2025-05-01-preview"
    
    # Manual request
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers={...}, content=file_data)
    
    # Manual polling
    operation_url = response.headers["Operation-Location"]
    while True:
        poll_response = await client.get(operation_url, headers={...})
        status = poll_response.json()["status"]
        if status == "succeeded":
            break
        await asyncio.sleep(2)
    
    # Manual result extraction
    result = poll_response.json()
    return result
```

### AFTER (With Service)
```python
from app.services.content_understanding_service import ContentUnderstandingService

service = ContentUnderstandingService(
    endpoint=config.azure_ai_endpoint,
    token_provider=lambda: get_cached_token(),
    subscription_key=config.subscription_key,
)

@router.post("/analyze")
async def analyze_document(file: UploadFile):
    file_data = await file.read()
    
    result = await service.analyze_and_wait(
        analyzer_id="prebuilt-documentAnalyzer",
        file_data=file_data
    )
    
    return result
```

---

## Testing Strategy

### Unit Tests
```python
import pytest
from unittest.mock import Mock, AsyncMock

async def test_begin_analyze_with_file_data():
    service = ContentUnderstandingService(
        endpoint="https://test.com",
        subscription_key="test-key"
    )
    
    # Mock the client
    service._client.post = AsyncMock(return_value=Mock(
        headers={"Operation-Location": "https://test.com/operations/123"},
        status_code=202
    ))
    
    response = await service.begin_analyze(
        analyzer_id="test-analyzer",
        file_data=b"test data"
    )
    
    assert response.headers["Operation-Location"]
```

### Integration Tests
```python
async def test_full_analysis_flow():
    """Test with real Azure endpoint (requires config)"""
    service = ContentUnderstandingService(
        endpoint=os.getenv("AZURE_AI_ENDPOINT"),
        subscription_key=os.getenv("AZURE_AI_KEY")
    )
    
    with open("test_document.pdf", "rb") as f:
        file_data = f.read()
    
    result = await service.analyze_and_wait(
        analyzer_id="prebuilt-documentAnalyzer",
        file_data=file_data,
        timeout_seconds=60
    )
    
    assert result["status"] == "succeeded"
    assert "result" in result
```

---

## Implementation Checklist

### Phase 1: Service Creation
- [ ] Create `app/services/` directory
- [ ] Implement `content_understanding_service.py` (~500 lines)
- [ ] Add type hints throughout
- [ ] Add comprehensive docstrings
- [ ] Add logging statements

### Phase 2: Templates
- [ ] Create `app/services/analyzer_templates/` directory
- [ ] Add `prebuilt_document.json`
- [ ] Add `custom_invoice.json`
- [ ] Add `custom_pro_mode_template.json`

### Phase 3: Router Refactoring
- [ ] Import service in `proMode.py`
- [ ] Initialize service with config
- [ ] Replace manual analysis code with `service.analyze_and_wait()`
- [ ] Remove manual polling loops
- [ ] Remove manual token refresh code
- [ ] Remove 13,000+ lines of manual code

### Phase 4: Testing
- [ ] Write unit tests for service methods
- [ ] Write integration tests with mocks
- [ ] Test with real Azure endpoint
- [ ] Performance benchmarking

### Phase 5: Deployment
- [ ] Review all changes
- [ ] Update documentation
- [ ] Test in staging environment
- [ ] Deploy to production

---

## Expected Metrics

### Code Reduction
- **Service Layer:** New 500 lines (clean, maintainable)
- **Router:** 500+ lines → 50 lines (90% reduction)
- **Total Removed:** ~13,500 lines

### Performance
- **Same or Better:** httpx.AsyncClient is efficient
- **Better Error Handling:** Centralized retry logic
- **Better Logging:** Structured, consistent

### Maintainability
- **Single Responsibility:** Service handles API, router handles HTTP
- **Testable:** Easy to mock service in tests
- **Type Safe:** Full type hints
- **Documented:** Clear docstrings matching Azure patterns

---

**Ready to implement!** 🚀
