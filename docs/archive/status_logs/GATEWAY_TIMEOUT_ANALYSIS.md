# 504 Gateway Timeout Issue - Analysis

## Problem
When sending 5 PDFs (base64 encoded, 0.26 MB total) to `/graphrag/v3/index`:
```
Status Code: 504
Response Text: stream timeout
Time: 240.07 seconds (4 minutes)
```

## Root Cause

### 1. Gateway/Proxy Timeout
The 504 error indicates the **Azure Container Apps gateway** timed out waiting for the backend to respond, not our client. Timeline:
- Our client timeout: 600 seconds (10 minutes)
- Gateway timeout: ~240 seconds (4 minutes) ⚠️
- Actual processing time needed: Unknown (process killed before completion)

### 2. Why 5 PDFs Take So Long

Processing chain for each PDF:
1. **Base64 decode** (~100ms per PDF)
2. **Document Intelligence extraction** (10-30 seconds per PDF) ⚠️ Slowest
3. **Text chunking** (~1 second per PDF)
4. **Entity extraction via LLM** (5-10 seconds per chunk) ⚠️
5. **Embedding computation** (1-2 seconds per chunk) ⚠️
6. **Neo4j storage** (1-2 seconds per batch)
7. **Community detection** (10-30 seconds) ⚠️
8. **RAPTOR summarization** (20-60 seconds) ⚠️

**Total estimated time for 5 PDFs:** 3-8 minutes per document = 15-40 minutes total

### 3. Azure Container Apps Default Timeout
Azure Container Apps has a default request timeout of **240 seconds (4 minutes)**, which cannot be extended via client timeout settings.

## Solutions

### Option 1: Background Processing (RECOMMENDED)
Modify API to return immediately and process in background:

```python
# Client sends request
response = requests.post("/graphrag/v3/index", json={
    "documents": pdfs,
    "async": True  # NEW: Process in background
})

# API returns immediately with job ID
{
    "status": "processing",
    "job_id": "abc123",
    "group_id": "pdf-test-123"
}

# Client polls for completion
while True:
    status = requests.get(f"/graphrag/v3/status/{job_id}")
    if status["complete"]:
        break
    time.sleep(10)
```

**Pros:**
- ✅ No timeout issues
- ✅ Scalable to any number of documents
- ✅ Client can monitor progress

**Cons:**
- ❌ Requires API changes (add background task + status endpoint)
- ❌ More complex client code

### Option 2: Batch Processing
Send PDFs one at a time or in smaller batches:

```python
# Instead of 5 at once
for pdf in pdfs:
    response = requests.post("/graphrag/v3/index", json={
        "documents": [pdf]  # ONE at a time
    })
```

**Pros:**
- ✅ Works with current API
- ✅ Each request completes within timeout
- ✅ Can see per-document results

**Cons:**
- ❌ Slower total time (no parallelization)
- ❌ Multiple API calls
- ❌ Duplicate RAPTOR/community detection for each batch

### Option 3: Use Blob Storage URLs (BEST FOR TESTING)
Instead of base64-encoding PDFs, upload to blob storage and send URLs:

```python
# Upload PDFs to blob storage
pdf_urls = []
for pdf_file in pdf_files:
    url = upload_to_blob(pdf_file)  # Returns SAS URL
    pdf_urls.append(url)

# Send URLs instead of base64
response = requests.post("/graphrag/v3/index", json={
    "documents": pdf_urls,  # URLs, not base64
    "ingestion": "document-intelligence"
})
```

**Pros:**
- ✅ Smaller payload (URLs vs base64)
- ✅ Faster request/response
- ✅ DI can fetch directly from blob
- ✅ Works with current API

**Cons:**
- ❌ Requires blob storage setup
- ❌ More complex test script

### Option 4: Increase Gateway Timeout (NOT POSSIBLE)
Azure Container Apps request timeout is **hardcoded at 240 seconds** and cannot be changed.

## Recommended Approach

### Short-term: Test with Fewer PDFs
Test with 1-2 PDFs to verify the pipeline works:

```python
# Test with 2 PDFs first
PDF_FILES = [
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf",
]
```

**Expected time:** 2 PDFs × 36 seconds = ~72 seconds ✅ Under 240s limit

### Long-term: Implement Background Processing
The API already has background task support for >10 documents:

```python
# In graphrag_v3.py (line ~240)
if len(docs_for_pipeline) <= 10:
    # Synchronous for small batches
    stats = await pipeline.index_documents(...)
else:
    # Background for large batches
    background_tasks.add_task(run_indexing)
```

**Change threshold from 10 to 3** to trigger background processing for 5 PDFs:

```python
if len(docs_for_pipeline) <= 2:  # Changed from 10
    # Synchronous
else:
    # Background
```

## Implementation: Batch Processing

Let me modify the test to process PDFs in batches of 2:

```python
def test_indexing_batched(files_data: List[Dict]) -> Tuple[Dict[str, Any], float]:
    """Test document indexing with batched processing"""
    batch_size = 2
    total_stats = {
        "documents_processed": 0,
        "entities_created": 0,
        "relationships_created": 0,
        "communities_created": 0,
        "raptor_nodes_created": 0
    }
    
    with Timer("PDF Indexing (Batched)") as timer:
        for i in range(0, len(files_data), batch_size):
            batch = files_data[i:i+batch_size]
            print(f"\n  Batch {i//batch_size + 1}: {len(batch)} PDFs")
            
            documents = [
                {
                    "text": pdf["content"],
                    "metadata": {"filename": pdf["filename"]}
                }
                for pdf in batch
            ]
            
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/index",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': TEST_GROUP_ID
                },
                json={
                    "documents": documents,
                    "ingestion": "document-intelligence",
                    "run_raptor": True,
                    "run_community_detection": True
                },
                timeout=240  # Match gateway timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                for key in total_stats:
                    total_stats[key] += result.get(key, 0)
            else:
                print(f"  ❌ Batch failed: {response.status_code}")
    
    return total_stats, timer.elapsed
```

This way:
- Each batch processes within 240s timeout
- All 5 PDFs get indexed
- We can measure per-batch and total time
