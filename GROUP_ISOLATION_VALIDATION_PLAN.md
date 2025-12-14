# Group-Based Data Isolation - Validation & Testing Plan

**Date:** October 16, 2025  
**Status:** 🔄 **IN PROGRESS**  
**Scope:** Comprehensive validation of all group isolation endpoints

---

## 📋 Validation Overview

This document outlines the complete validation strategy for the group-based data isolation implementation across all backend endpoints in `proMode.py`.

### Validation Goals
1. ✅ **Security:** Verify users can only access data within their groups
2. ✅ **Functionality:** Confirm all CRUD operations work with group isolation
3. ✅ **Backward Compatibility:** Ensure existing data remains accessible
4. ✅ **Performance:** Validate no significant performance degradation
5. ✅ **Error Handling:** Test proper error responses for unauthorized access

---

## 🧪 Test Environment Setup

### Prerequisites
```bash
# 1. Python environment with all dependencies
pip install pytest pytest-asyncio httpx faker

# 2. Test database (Cosmos DB or MongoDB)
# Use separate test database to avoid production data corruption

# 3. Azure Storage account for blob testing
# Configure test storage account in environment

# 4. Test user accounts with different group memberships
# User1: groups = ["group-a", "group-b"]
# User2: groups = ["group-b", "group-c"]
# User3: groups = ["group-a"]
# User4: groups = [] (no groups)
```

### Environment Variables
```bash
export TEST_COSMOS_CONNSTR="mongodb://..."
export TEST_COSMOS_DATABASE="test_content_processor"
export TEST_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;..."
export TEST_AZURE_AD_TENANT_ID="..."
export TEST_AZURE_AD_CLIENT_ID="..."
```

---

## 🔐 Test Data Setup

### Test Users & Groups
```python
# Test user configurations
TEST_USERS = {
    "user1": {
        "user_id": "user1@example.com",
        "email": "user1@example.com",
        "name": "Test User 1",
        "groups": ["group-a", "group-b"],
        "token": "eyJ..."  # JWT token with group claims
    },
    "user2": {
        "user_id": "user2@example.com",
        "email": "user2@example.com",
        "name": "Test User 2",
        "groups": ["group-b", "group-c"],
        "token": "eyJ..."
    },
    "user3": {
        "user_id": "user3@example.com",
        "email": "user3@example.com",
        "name": "Test User 3",
        "groups": ["group-a"],
        "token": "eyJ..."
    },
    "user4": {
        "user_id": "user4@example.com",
        "email": "user4@example.com",
        "name": "Test User 4 (No Groups)",
        "groups": [],
        "token": "eyJ..."
    }
}

# Test groups
TEST_GROUPS = ["group-a", "group-b", "group-c"]
```

### Test Data Creation
```python
# Create test schemas for each group
async def create_test_data():
    """Create test schemas, files, and analysis results for validation"""
    
    # Group A schemas
    schema_a1 = await create_schema(
        name="Group A Invoice Schema",
        group_id="group-a",
        user=TEST_USERS["user1"]
    )
    
    # Group B schemas
    schema_b1 = await create_schema(
        name="Group B Contract Schema",
        group_id="group-b",
        user=TEST_USERS["user1"]
    )
    
    # Group C schemas
    schema_c1 = await create_schema(
        name="Group C Form Schema",
        group_id="group-c",
        user=TEST_USERS["user2"]
    )
    
    # Legacy schema (no group_id)
    schema_legacy = await create_schema(
        name="Legacy Schema",
        group_id=None,
        user=None
    )
    
    return {
        "group_a": [schema_a1],
        "group_b": [schema_b1],
        "group_c": [schema_c1],
        "legacy": [schema_legacy]
    }
```

---

## 📝 Test Scenarios

### 1. Schema Management Tests

#### Test 1.1: Create Schema with Group Isolation
```python
async def test_create_schema_with_group():
    """Verify schema creation tags data with group_id"""
    
    response = await client.post(
        "/pro-mode/schemas/create",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        json={
            "name": "Test Invoice Schema",
            "description": "Test schema for group A"
        }
    )
    
    assert response.status_code == 200
    schema = response.json()
    
    # Verify group_id is set
    assert schema["group_id"] == "group-a"
    assert schema["name"] == "Test Invoice Schema"
    assert schema["createdBy"] == "user1@example.com"
    
    print("✅ PASS: Schema created with correct group_id")
```

#### Test 1.2: Get Schemas Filtered by Group
```python
async def test_get_schemas_filtered_by_group():
    """Verify GET /schemas returns only schemas from specified group"""
    
    # User1 requests group-a schemas
    response = await client.get(
        "/pro-mode/schemas",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        }
    )
    
    assert response.status_code == 200
    schemas = response.json()
    
    # All returned schemas should belong to group-a
    for schema in schemas:
        assert schema.get("group_id") == "group-a", \
            f"Schema {schema['id']} has group_id={schema.get('group_id')}, expected group-a"
    
    print(f"✅ PASS: Returned {len(schemas)} schemas, all from group-a")
```

#### Test 1.3: Access Denied - Wrong Group
```python
async def test_access_denied_wrong_group():
    """Verify user cannot access schemas from groups they don't belong to"""
    
    # User3 (only in group-a) tries to access group-c schema
    response = await client.get(
        "/pro-mode/schemas",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user3']['token']}",
            "X-Group-ID": "group-c"  # User3 NOT in group-c
        }
    )
    
    assert response.status_code == 403
    error = response.json()
    assert "access" in error["detail"].lower() or "forbidden" in error["detail"].lower()
    
    print("✅ PASS: Access denied for user not in group")
```

#### Test 1.4: Delete Schema - Group Validation
```python
async def test_delete_schema_group_validation():
    """Verify schema deletion validates group ownership"""
    
    # Create schema in group-a
    schema = await create_schema("Test Schema", "group-a", TEST_USERS["user1"])
    schema_id = schema["id"]
    
    # User2 (not in group-a) tries to delete it
    response = await client.delete(
        f"/pro-mode/schemas/{schema_id}",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user2']['token']}",
            "X-Group-ID": "group-a"  # User2 not in group-a
        }
    )
    
    assert response.status_code == 403
    print("✅ PASS: Delete blocked for non-group member")
    
    # User1 (in group-a) can delete it
    response = await client.delete(
        f"/pro-mode/schemas/{schema_id}",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        }
    )
    
    assert response.status_code == 200
    print("✅ PASS: Delete succeeded for group member")
```

#### Test 1.5: Update Schema Field - Group Isolation
```python
async def test_update_schema_field_group_isolation():
    """Verify field updates validate group ownership"""
    
    # Create schema in group-b
    schema = await create_schema("Test Schema", "group-b", TEST_USERS["user1"])
    schema_id = schema["id"]
    
    # User1 (in group-b) can update field
    response = await client.put(
        f"/pro-mode/schemas/{schema_id}/fields/test_field",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-b"
        },
        json={
            "name": "test_field",
            "type": "string",
            "description": "Updated description"
        }
    )
    
    assert response.status_code in [200, 201]
    print("✅ PASS: Field update succeeded for group member")
    
    # User3 (not in group-b) cannot update
    response = await client.put(
        f"/pro-mode/schemas/{schema_id}/fields/test_field",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user3']['token']}",
            "X-Group-ID": "group-b"  # User3 not in group-b
        },
        json={
            "name": "test_field",
            "type": "string",
            "description": "Malicious update"
        }
    )
    
    assert response.status_code == 403
    print("✅ PASS: Field update blocked for non-group member")
```

#### Test 1.6: Bulk Delete - Group Filtering
```python
async def test_bulk_delete_group_filtering():
    """Verify bulk delete only affects schemas within user's group"""
    
    # Create schemas in different groups
    schema_a = await create_schema("Schema A", "group-a", TEST_USERS["user1"])
    schema_b = await create_schema("Schema B", "group-b", TEST_USERS["user1"])
    schema_c = await create_schema("Schema C", "group-c", TEST_USERS["user2"])
    
    # User1 tries to bulk delete all three (but only in group-a and group-b)
    response = await client.post(
        "/pro-mode/schemas/bulk-delete",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        json={
            "schemaIds": [schema_a["id"], schema_b["id"], schema_c["id"]],
            "cleanupBlobs": True
        }
    )
    
    result = response.json()
    
    # Should only delete schema_a (group-a), not schema_b or schema_c
    assert result["successCount"] == 1
    assert schema_a["id"] in [s["id"] for s in result["successful"]]
    assert result["failureCount"] == 2  # schema_b and schema_c not deleted
    
    print("✅ PASS: Bulk delete only affected schemas in specified group")
```

#### Test 1.7: Backward Compatibility - No Group ID
```python
async def test_backward_compatibility_no_group():
    """Verify endpoints work without X-Group-ID header (legacy behavior)"""
    
    # Create schema without group_id
    response = await client.post(
        "/pro-mode/schemas/create",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}"
            # No X-Group-ID header
        },
        json={
            "name": "Legacy Schema",
            "description": "No group isolation"
        }
    )
    
    assert response.status_code == 200
    schema = response.json()
    
    # Should not have group_id field (or it's None)
    assert schema.get("group_id") is None
    print("✅ PASS: Schema created without group_id for backward compatibility")
    
    # Get schemas without group filter
    response = await client.get(
        "/pro-mode/schemas",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}"
            # No X-Group-ID header
        }
    )
    
    assert response.status_code == 200
    schemas = response.json()
    print(f"✅ PASS: Retrieved {len(schemas)} schemas without group filter")
```

---

### 2. File Management Tests

#### Test 2.1: Upload File with Group Isolation
```python
async def test_upload_file_with_group():
    """Verify file upload stores in group-specific container"""
    
    test_file = ("test.pdf", b"fake PDF content", "application/pdf")
    
    response = await client.post(
        "/pro-mode/files/upload",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        files={"files": test_file}
    )
    
    assert response.status_code == 200
    file_data = response.json()
    
    # Verify group_id is set
    assert file_data["group_id"] == "group-a"
    
    # Verify blob container is group-specific
    assert "group-group-a" in file_data.get("blobUrl", "") or \
           "container" in file_data and file_data["container"] == "group-group-a"
    
    print("✅ PASS: File uploaded to group-specific container")
```

#### Test 2.2: List Files - Group Filtering
```python
async def test_list_files_group_filtering():
    """Verify file listing returns only files from user's group"""
    
    # Upload files to different groups
    await upload_file("file_a.pdf", "group-a", TEST_USERS["user1"])
    await upload_file("file_b.pdf", "group-b", TEST_USERS["user1"])
    await upload_file("file_c.pdf", "group-c", TEST_USERS["user2"])
    
    # User1 lists files in group-a
    response = await client.get(
        "/pro-mode/files",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        }
    )
    
    files = response.json()
    
    # All files should belong to group-a
    for file in files:
        assert file.get("group_id") == "group-a"
    
    print(f"✅ PASS: Listed {len(files)} files, all from group-a")
```

#### Test 2.3: Delete File - Cross-Group Prevention
```python
async def test_delete_file_cross_group_prevention():
    """Verify user cannot delete files from other groups"""
    
    # User1 uploads file to group-a
    file_data = await upload_file("secure.pdf", "group-a", TEST_USERS["user1"])
    file_id = file_data["id"]
    
    # User2 (not in group-a) tries to delete it
    response = await client.delete(
        f"/pro-mode/files/{file_id}",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user2']['token']}",
            "X-Group-ID": "group-a"  # User2 not in group-a
        }
    )
    
    assert response.status_code == 403
    print("✅ PASS: Cross-group file deletion blocked")
```

---

### 3. Analysis Results Tests

#### Test 3.1: Start Analysis with Group Tagging
```python
async def test_start_analysis_with_group():
    """Verify analysis results are tagged with group_id"""
    
    # Upload file and schema in group-b
    file_data = await upload_file("invoice.pdf", "group-b", TEST_USERS["user1"])
    schema_data = await create_schema("Invoice Schema", "group-b", TEST_USERS["user1"])
    
    # Start analysis
    response = await client.post(
        "/pro-mode/analyze",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-b"
        },
        json={
            "fileId": file_data["id"],
            "schemaId": schema_data["id"]
        }
    )
    
    assert response.status_code in [200, 202]
    result = response.json()
    
    # Verify group_id is set
    assert result.get("group_id") == "group-b"
    print("✅ PASS: Analysis result tagged with group_id")
```

#### Test 3.2: Get Analysis Results - Group Filtering
```python
async def test_get_analysis_results_filtering():
    """Verify analysis results are filtered by group"""
    
    # Create analysis results in different groups
    await create_analysis_result("group-a", TEST_USERS["user1"])
    await create_analysis_result("group-b", TEST_USERS["user1"])
    await create_analysis_result("group-c", TEST_USERS["user2"])
    
    # User1 gets results for group-a
    response = await client.get(
        "/pro-mode/analysis/results",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        }
    )
    
    results = response.json()
    
    # All results should be from group-a
    for result in results:
        assert result.get("group_id") == "group-a"
    
    print(f"✅ PASS: Retrieved {len(results)} results, all from group-a")
```

---

### 4. Content Analyzer Tests

#### Test 4.1: Create Analyzer with Group Isolation
```python
async def test_create_analyzer_with_group():
    """Verify content analyzer is tagged with group_id"""
    
    response = await client.put(
        "/pro-mode/content-analyzers/test-analyzer-123",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        json={
            "description": "Test analyzer for group A",
            "schema": {...}
        }
    )
    
    assert response.status_code in [200, 201]
    analyzer = response.json()
    
    assert analyzer.get("group_id") == "group-a"
    print("✅ PASS: Analyzer created with group_id")
```

#### Test 4.2: Get Analyzer Status - Group Validation
```python
async def test_get_analyzer_status_group_validation():
    """Verify analyzer status check validates group membership"""
    
    # Create analyzer in group-b
    analyzer = await create_analyzer("analyzer-123", "group-b", TEST_USERS["user1"])
    
    # User3 (not in group-b) tries to check status
    response = await client.get(
        f"/pro-mode/content-analyzers/{analyzer['id']}/status",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user3']['token']}",
            "X-Group-ID": "group-b"
        }
    )
    
    assert response.status_code == 403
    print("✅ PASS: Analyzer status check blocked for non-group member")
```

---

### 5. Orchestration Tests

#### Test 5.1: Field Extraction with Group Isolation
```python
async def test_orchestration_field_extraction():
    """Verify orchestrated field extraction respects group isolation"""
    
    file_data = await upload_file("contract.pdf", "group-a", TEST_USERS["user1"])
    
    response = await client.post(
        "/pro-mode/orchestration/extract-fields",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        json={
            "fileId": file_data["id"],
            "documentType": "contract"
        }
    )
    
    assert response.status_code in [200, 202]
    result = response.json()
    
    assert result.get("group_id") == "group-a"
    print("✅ PASS: Orchestration field extraction tagged with group_id")
```

#### Test 5.2: Schema Enhancement with Group Isolation
```python
async def test_orchestration_schema_enhancement():
    """Verify schema enhancement orchestration respects group isolation"""
    
    schema = await create_schema("Base Schema", "group-b", TEST_USERS["user1"])
    
    response = await client.post(
        "/pro-mode/orchestration/enhance-schema",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-b"
        },
        json={
            "schemaId": schema["id"],
            "enhancementType": "ai_powered"
        }
    )
    
    assert response.status_code in [200, 202]
    result = response.json()
    
    assert result.get("group_id") == "group-b"
    print("✅ PASS: Schema enhancement tagged with group_id")
```

---

### 6. Quick Query Tests

#### Test 6.1: Initialize Quick Query with Group
```python
async def test_quick_query_initialize_with_group():
    """Verify Quick Query analyzer is tagged with group_id"""
    
    response = await client.post(
        "/pro-mode/quick-query/initialize",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        },
        json={
            "prompt": "Extract invoice total",
            "documentType": "invoice"
        }
    )
    
    assert response.status_code in [200, 201]
    analyzer = response.json()
    
    assert analyzer.get("group_id") == "group-a"
    print("✅ PASS: Quick Query analyzer tagged with group_id")
```

#### Test 6.2: Update Prompt - Group Validation
```python
async def test_quick_query_update_prompt_validation():
    """Verify prompt update validates group ownership"""
    
    # Create Quick Query in group-b
    analyzer = await initialize_quick_query("group-b", TEST_USERS["user1"])
    
    # User3 (not in group-b) tries to update prompt
    response = await client.put(
        "/pro-mode/quick-query/update-prompt",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user3']['token']}",
            "X-Group-ID": "group-b"
        },
        json={
            "analyzerId": analyzer["id"],
            "prompt": "Malicious prompt"
        }
    )
    
    assert response.status_code == 403
    print("✅ PASS: Prompt update blocked for non-group member")
```

---

## 🔍 Performance Validation

### Test 7.1: Query Performance with Group Filtering
```python
async def test_query_performance_with_group_filter():
    """Measure query performance impact of group filtering"""
    
    import time
    
    # Create 100 schemas across 3 groups
    for i in range(100):
        group = f"group-{i % 3}"
        await create_schema(f"Schema {i}", group, TEST_USERS["user1"])
    
    # Measure query time with group filter
    start = time.time()
    response = await client.get(
        "/pro-mode/schemas",
        headers={
            "Authorization": f"Bearer {TEST_USERS['user1']['token']}",
            "X-Group-ID": "group-a"
        }
    )
    elapsed = time.time() - start
    
    assert response.status_code == 200
    assert elapsed < 1.0  # Should complete in under 1 second
    
    print(f"✅ PASS: Query completed in {elapsed:.3f}s with group filter")
```

### Test 7.2: Concurrent Group Access
```python
async def test_concurrent_group_access():
    """Test concurrent access from multiple users/groups"""
    
    import asyncio
    
    async def user_workflow(user, group):
        # Create schema
        schema = await create_schema(f"Schema-{user}", group, TEST_USERS[user])
        # Upload file
        file = await upload_file(f"file-{user}.pdf", group, TEST_USERS[user])
        # Start analysis
        result = await start_analysis(file["id"], schema["id"], group, TEST_USERS[user])
        return result
    
    # Run 10 concurrent workflows across different users/groups
    tasks = [
        user_workflow("user1", "group-a"),
        user_workflow("user1", "group-b"),
        user_workflow("user2", "group-b"),
        user_workflow("user2", "group-c"),
        user_workflow("user3", "group-a"),
    ]
    
    start = time.time()
    results = await asyncio.gather(*tasks)
    elapsed = time.time() - start
    
    assert len(results) == 5
    assert all(r["status"] in ["success", "processing"] for r in results)
    
    print(f"✅ PASS: {len(tasks)} concurrent workflows completed in {elapsed:.3f}s")
```

---

## 📊 Validation Summary

### Test Execution Command
```bash
# Run all group isolation tests
pytest tests/test_group_isolation.py -v --tb=short

# Run specific test categories
pytest tests/test_group_isolation.py::TestSchemaManagement -v
pytest tests/test_group_isolation.py::TestFileManagement -v
pytest tests/test_group_isolation.py::TestAnalysis -v
pytest tests/test_group_isolation.py::TestPerformance -v

# Generate coverage report
pytest tests/test_group_isolation.py --cov=app/routers/proMode --cov-report=html
```

### Expected Results
- ✅ **Security Tests:** 100% pass rate (no unauthorized access)
- ✅ **Functionality Tests:** 100% pass rate (all operations work correctly)
- ✅ **Backward Compatibility:** 100% pass rate (legacy behavior preserved)
- ✅ **Performance Tests:** <10% degradation from baseline
- ✅ **Error Handling:** All error cases return appropriate HTTP status codes

---

## 🚨 Known Issues & Resolutions

### Issue 1: Missing Group ID Validation
**Status:** ✅ RESOLVED  
**Description:** Some endpoints were missing group access validation  
**Resolution:** Added `validate_group_access()` to all endpoints

### Issue 2: Blob Container Naming
**Status:** ✅ RESOLVED  
**Description:** Group-based container naming not consistent  
**Resolution:** Standardized to `group-{group_id}` format

### Issue 3: Legacy Data Access
**Status:** ✅ RESOLVED  
**Description:** Schemas without `group_id` were inaccessible  
**Resolution:** Made `group_id` optional, backward compatible

---

## ✅ Validation Checklist

### Pre-Testing
- [x] Test environment configured
- [x] Test users created with different group memberships
- [x] Test data prepared across multiple groups
- [x] Database indexes created for `group_id` field

### Schema Management
- [ ] Create schema with group isolation
- [ ] Get schemas filtered by group
- [ ] Update schema field with group validation
- [ ] Delete schema with group validation
- [ ] Bulk operations respect group boundaries
- [ ] Backward compatibility without group_id

### File Management
- [ ] Upload file to group-specific container
- [ ] List files filtered by group
- [ ] Delete file with group validation
- [ ] Cross-group access prevention

### Analysis
- [ ] Start analysis with group tagging
- [ ] Get results filtered by group
- [ ] Delete results with group validation

### Content Analyzers
- [ ] Create analyzer with group tagging
- [ ] Get analyzer status with group validation
- [ ] Delete analyzer with group validation

### Orchestration
- [ ] Field extraction respects group isolation
- [ ] Schema enhancement respects group isolation
- [ ] Document analysis respects group isolation

### Quick Query
- [ ] Initialize with group tagging
- [ ] Update prompt with group validation

### Performance
- [ ] Query performance acceptable with filtering
- [ ] Concurrent access from multiple groups
- [ ] Bulk operations performance

### Security
- [ ] Unauthorized access returns 403
- [ ] Group membership validation enforced
- [ ] No data leakage between groups

---

## 📝 Test Execution Log

### Test Run: [Date/Time]
**Environment:** Test  
**Executor:** [Name]  

| Test Category | Total | Passed | Failed | Skipped | Duration |
|--------------|-------|--------|--------|---------|----------|
| Schema Mgmt  | 7     | -      | -      | -       | -        |
| File Mgmt    | 3     | -      | -      | -       | -        |
| Analysis     | 2     | -      | -      | -       | -        |
| Analyzers    | 2     | -      | -      | -       | -        |
| Orchestration| 2     | -      | -      | -       | -        |
| Quick Query  | 2     | -      | -      | -       | -        |
| Performance  | 2     | -      | -      | -       | -        |
| **TOTAL**    | **20**| **-**  | **-**  | **-**   | **-**    |

---

## 🎯 Next Steps

1. **Create Test Suite:** Implement all test scenarios in pytest
2. **Execute Tests:** Run full test suite in test environment
3. **Document Results:** Update this document with test outcomes
4. **Fix Issues:** Address any failures or security concerns
5. **Performance Tuning:** Optimize queries if performance degrades
6. **Production Validation:** Run smoke tests in production after deployment

---

**Document Version:** 1.0  
**Last Updated:** October 16, 2025  
**Status:** Ready for Test Execution
