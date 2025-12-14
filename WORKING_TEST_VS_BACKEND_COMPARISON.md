# Working Test vs Backend Endpoint Comparison

## Test Script (WORKS ✅)
```python
# 1. CREATE ANALYZER
analyzer_config = {
    "description": f"Test Case {test_case_num}: {enhancement_prompt[:50]}...",
    "mode": "pro",
    "baseAnalyzerId": "prebuilt-documentAnalyzer",
    "processingLocation": "dataZone",
    **meta_schema  # Includes fieldSchema
}

create_url = f"{endpoint}/analyzers/{analyzer_id}?api-version={api_version}"

req = urllib.request.Request(
    create_url,
    data=json.dumps(analyzer_config).encode('utf-8'),
    headers=headers,
    method='PUT'
)

with urllib.request.urlopen(req) as response:
    if response.status == 201:
        print(f"✅ Analyzer created")
```

## Backend Endpoint (FAILS ❌)
```python
# 1. CREATE ANALYZER
create_url = f"{normalize_endpoint_url(endpoint)}/contentunderstanding/analyzers/{analyzer_id}?api-version={api_version}"

analyzer_payload = {
    "description": f"AI-enhanced schema for {request.schema_name}",
    "mode": "pro",
    "baseAnalyzerId": "prebuilt-documentAnalyzer",
    "processingLocation": "dataZone",
    "fieldSchema": enhancement_schema
}

async with httpx.AsyncClient(verify=certifi.where(), timeout=300.0) as client:
    create_response = await client.put(
        create_url,
        json=analyzer_payload,
        headers=headers
    )
```

---

## KEY DIFFERENCES FOUND

### 1. URL Path ⚠️

**Test (WORKS):**
```
/analyzers/{analyzer_id}
```

**Backend (WRONG?):**
```
/contentunderstanding/analyzers/{analyzer_id}
```

### 2. Meta-Schema Format

**Test (WORKS):**
```python
meta_schema = {
    "fieldSchema": {
        "NewFieldsToAdd": {...},
        "CompleteEnhancedSchema": {...},
        "EnhancementReasoning": {...}
    }
}

analyzer_config = {
    **meta_schema,  # Spreads fieldSchema at top level
    "description": "...",
    "mode": "pro",
    ...
}
```

**Backend:**
```python
analyzer_payload = {
    "fieldSchema": enhancement_schema,  # Nested, not spread
    "description": "...",
    "mode": "pro",
    ...
}
```

### 3. Response Status Code

**Test expects:** 201 Created  
**Backend checks:** 200 or 201

---

## CRITICAL FINDING

The test script uses `/analyzers/` path, but backend uses `/contentunderstanding/analyzers/` path!

Let me check if there's a URL normalization issue...

### Check normalize_endpoint_url()

The function `normalize_endpoint_url()` might be adding `/contentunderstanding` prefix. Need to verify this matches Azure's actual API.

---

## Analysis Path

**Test (WORKS):**
```
POST /analyzers/{analyzer_id}:analyze
```

**Backend:**
```
POST /contentunderstanding/analyzers/{analyzer_id}:analyze
```

---

## Wait for Ready

**Test (WORKS):**
```python
# Poll every 10 seconds, up to 30 times (5 minutes)
for _ in range(30):
    time.sleep(10)
    # GET /analyzers/{analyzer_id}
    if status == 'ready':
        break
```

**Backend:**
```python
# Poll every 5 seconds, 12 times (1 minute)
for status_attempt in range(12):
    await asyncio.sleep(5)
    # GET /contentunderstanding/analyzers/{analyzer_id}
    if analyzer_status == "ready":
        break
```

**Issue:** Backend timeout is too short! (60s vs 300s)

---

## Results Polling

**Test (WORKS):**
```python
# Poll every 10 seconds, up to 60 times (10 minutes)
for _ in range(60):
    time.sleep(10)
    # GET from operation_location
    if status == 'succeeded':
        break
```

**Backend:**
```python
# Poll every 5 seconds, 50 times (250 seconds = 4.16 minutes)
for poll_attempt in range(50):
    await asyncio.sleep(5)
    # GET from operation_location
    if analysis_status in ["succeeded", "completed"]:
        break
```

**Issue:** Different intervals and attempts

---

## ROOT CAUSE HYPOTHESIS

### Issue #1: URL Path Mismatch ⚠️⚠️⚠️

Backend adds `/contentunderstanding` prefix but test doesn't!

**Need to check:**
- Is the Azure endpoint URL already including this prefix?
- Is `normalize_endpoint_url()` double-adding it?

### Issue #2: Timeout Too Aggressive

Backend: 60s for analyzer ready (might need 3-5 minutes like test)

### Issue #3: Meta-Schema Structure

Test spreads `**meta_schema` to include fieldSchema at top level.
Backend nests it under `"fieldSchema": enhancement_schema`.

**Need to verify Azure API expects the spread version.**

---

## NEXT STEPS

1. **Check endpoint URL format** - Is it already `https://.../contentunderstanding` or base URL?
2. **Fix URL construction** - Match test script exactly
3. **Increase analyzer ready timeout** - 60s → 300s
4. **Test meta-schema structure** - Spread vs nested

Let me investigate the endpoint URL...
