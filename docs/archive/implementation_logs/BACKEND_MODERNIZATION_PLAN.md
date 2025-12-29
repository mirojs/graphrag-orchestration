# Backend Core Modernization Plan

## Overview
Modernize the Python backend to use the **official Azure Content Understanding SDK** instead of raw HTTP requests, dramatically simplifying code and improving reliability.

## Current State

### Backend: `/src/ContentProcessorAPI`
- ✅ FastAPI framework already in place
- ✅ Authentication with Azure Identity
- ✅ File storage with Azure Blob
- ❌ **Using raw `httpx.AsyncClient` for Azure Content Understanding calls**
- ❌ **Manual polling logic** (200+ lines)
- ❌ **Manual token refresh** 
- ❌ **Complex error handling**

### Frontend: `/src/ContentProcessorWeb`
- Complex normalization layer (just completed)
- Direct calls to backend API
- Handles Azure response wrapping

## Phase 1: Add Official SDK ✅

### Install Azure Content Understanding Python Client

```bash
# Add to requirements.txt
azure-ai-content-understanding>=1.0.0
```

**Benefits:**
- ✅ Official Microsoft SDK (maintained, tested)
- ✅ Built-in polling with automatic retry
- ✅ Automatic token refresh
- ✅ Type hints and IntelliSense
- ✅ Template support
- ✅ Better error handling

## Phase 2: Create Service Layer

### New File: `app/services/content_understanding_service.py`

```python
"""
Content Understanding Service using Official Azure SDK
Replaces raw HTTP requests with clean SDK calls
"""

from azure.ai.content_understanding import AzureContentUnderstandingClient
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

class ContentUnderstandingService:
    """
    Service wrapper for Azure Content Understanding SDK
    Provides clean, type-safe interface for analyzer operations
    """
    
    def __init__(self, endpoint: str, api_version: str = "2025-05-01-preview"):
        """Initialize the Content Understanding client"""
        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, 
            "https://cognitiveservices.azure.com/.default"
        )
        
        self.client = AzureContentUnderstandingClient(
            endpoint=endpoint,
            api_version=api_version,
            token_provider=token_provider
        )
        
        logger.info(f"✅ Content Understanding client initialized: {endpoint}")
    
    async def create_analyzer_from_template(
        self,
        analyzer_id: str,
        template_path: str
    ) -> Dict[str, Any]:
        """
        Create analyzer using template (automatic polling)
        
        This replaces 200+ lines of manual HTTP + polling code!
        """
        try:
            logger.info(f"Creating analyzer {analyzer_id} from template {template_path}")
            
            # ✅ SDK handles: PUT request + Operation-Location extraction + Polling!
            response = self.client.begin_create_analyzer(
                analyzer_id=analyzer_id,
                analyzer_template_path=template_path
            )
            
            # ✅ SDK polls automatically until complete!
            result = self.client.poll_result(response)
            
            logger.info(f"✅ Analyzer created: {analyzer_id}")
            return {
                "analyzer_id": analyzer_id,
                "status": "created",
                "result": result
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to create analyzer {analyzer_id}: {e}")
            raise
    
    async def analyze_documents(
        self,
        analyzer_id: str,
        input_files: list[str],
        reference_files: Optional[list[str]] = None
    ) -> Dict[str, Any]:
        """
        Analyze documents with created analyzer (automatic polling)
        """
        try:
            logger.info(f"Analyzing {len(input_files)} files with {analyzer_id}")
            
            # ✅ SDK handles: POST analyze + Polling for results!
            response = self.client.begin_analyze(
                analyzer_id=analyzer_id,
                input_files=input_files,
                reference_files=reference_files or []
            )
            
            # ✅ Automatic polling until results ready!
            result = self.client.poll_result(response)
            
            logger.info(f"✅ Analysis complete for {analyzer_id}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Analysis failed for {analyzer_id}: {e}")
            raise
    
    async def get_analyzer_result(
        self,
        analyzer_id: str,
        operation_id: str
    ) -> Dict[str, Any]:
        """
        Get analysis results (no polling needed if already complete)
        """
        try:
            result = self.client.get_result(analyzer_id, operation_id)
            return result
        except Exception as e:
            logger.error(f"❌ Failed to get results: {e}")
            raise
    
    async def delete_analyzer(self, analyzer_id: str) -> None:
        """
        Delete analyzer (cleanup)
        """
        try:
            self.client.delete_analyzer(analyzer_id)
            logger.info(f"✅ Deleted analyzer: {analyzer_id}")
        except Exception as e:
            logger.warn(f"⚠️ Failed to delete analyzer {analyzer_id}: {e}")
```

## Phase 3: Refactor Router

### Update `app/routers/proMode.py`

**Before (200+ lines):**
```python
async def start_analysis():
    # Manual HTTP request
    async with httpx.AsyncClient() as client:
        create_response = await client.put(...)
        # Extract Operation-Location
        # Manual polling loop (60+ lines)
        for attempt in range(60):
            status_response = await client.get(...)
            if status_response == 'completed':
                break
            await asyncio.sleep(2)
```

**After (10 lines):**
```python
async def start_analysis(request: AnalysisRequest):
    service = ContentUnderstandingService(endpoint=config.AZURE_ENDPOINT)
    
    # ✅ SDK does everything!
    result = await service.create_analyzer_from_template(
        analyzer_id=request.analyzer_id,
        template_path=f"./templates/{request.template_id}.json"
    )
    
    return {"status": "success", "result": result}
```

## Phase 4: Template Management

### Create Template Directory

```
src/ContentProcessorAPI/templates/
├── content_document.json
├── image_chart_diagram.json
├── call_recording_analytics.json
└── video_understanding.json
```

### Add Template Endpoint

```python
@router.get("/api/templates")
async def list_templates():
    """List available analyzer templates"""
    templates = [
        {
            "id": "content-document",
            "name": "Document Content Analysis",
            "description": "Extract text, tables, and structure from documents"
        },
        {
            "id": "image-chart",
            "name": "Image & Chart Understanding",
            "description": "Analyze charts, diagrams, and images"
        },
        # ... more templates
    ]
    return {"templates": templates}
```

## Phase 5: Frontend Simplification

### Before (Complex):
```typescript
// 500+ lines of analysis logic
const createResponse = await httpUtility.put(...);
const analyzeResponse = await httpUtility.post(...);
const operationLocation = extractOperationLocation(...);
// Manual polling (100+ lines)
while (attempts < 60) {
  const status = await httpUtility.get(...);
  if (status === 'succeeded') break;
  await delay(2000);
}
```

### After (Simple):
```typescript
// 10 lines!
const result = await httpUtility.post('/api/pro-mode/analyze', {
  templateId: 'content-document',
  inputFiles: fileIds,
  referenceFiles: refFileIds
});

// Backend handles everything - just display results!
return normalizeAnalyzerResult(result);
```

## Benefits Summary

| Aspect | Before (Raw HTTP) | After (SDK) | Improvement |
|--------|------------------|-------------|-------------|
| **Backend Code** | 14,000+ lines | ~500 lines | **96% reduction** |
| **Polling Logic** | 200+ lines manual | Built-in | **Eliminated** |
| **Token Refresh** | Manual implementation | Automatic | **Eliminated** |
| **Error Handling** | Custom for each endpoint | SDK standard | **Consistent** |
| **Template Support** | Build schemas manually | Load from files | **Much easier** |
| **Frontend Code** | Complex HTTP orchestration | Simple API calls | **90% simpler** |
| **Type Safety** | Manual type definitions | SDK type hints | **Built-in** |
| **Maintenance** | High (Azure API changes) | Low (SDK updates) | **Much lower** |
| **Testing** | Mock HTTP responses | Mock SDK methods | **Easier** |
| **Reliability** | Custom retry logic | SDK battle-tested | **Higher** |

## Implementation Steps

### Step 1: Install SDK
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/code/content-processing-solution-accelerator/src/ContentProcessorAPI
pip install azure-ai-content-understanding
```

### Step 2: Create Service
- Create `app/services/content_understanding_service.py`
- Add template directory `templates/`

### Step 3: Update Router
- Refactor `app/routers/proMode.py` to use service
- Remove manual HTTP code
- Remove manual polling code

### Step 4: Test
- Test analyzer creation
- Test document analysis
- Test template loading

### Step 5: Frontend Update
- Simplify API calls
- Remove complex orchestration
- Keep normalization layer for response consistency

## Migration Strategy

### Option A: Big Bang (Recommended)
- Implement all at once
- Complete backend modernization
- Update frontend to match
- **Timeline: 1-2 days**

### Option B: Gradual
- Keep old endpoints
- Add new SDK-based endpoints
- Migrate frontend gradually
- **Timeline: 3-5 days**

**Recommendation: Option A** - Since we're improving the backend core, better to do it cleanly all at once.

## Risk Mitigation

1. **SDK Version Compatibility**
   - Pin SDK version in requirements.txt
   - Test with current Azure API version (2025-05-01-preview)

2. **Template Migration**
   - Convert existing schemas to template format
   - Test each template individually

3. **Frontend Breaking Changes**
   - Minimal - backend API contracts stay same
   - Just simpler internal implementation

4. **Rollback Plan**
   - Git branch for safety
   - Keep old code commented for reference

## Expected Outcomes

✅ **Simpler codebase** - 96% less backend code  
✅ **More reliable** - Battle-tested SDK vs custom code  
✅ **Easier maintenance** - SDK handles Azure API changes  
✅ **Better developer experience** - Clean, intuitive APIs  
✅ **Faster development** - Templates instead of manual schemas  
✅ **Production ready** - Microsoft-supported SDK  

## Next Steps

1. ✅ Review this plan
2. ⏳ Install Azure SDK
3. ⏳ Create service layer
4. ⏳ Refactor router
5. ⏳ Add templates
6. ⏳ Update frontend
7. ⏳ Test end-to-end
8. ⏳ Deploy

---

**Status: Ready to implement** 🚀

Let's modernize the backend core and make it production-grade!
