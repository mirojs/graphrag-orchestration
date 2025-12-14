# Group Isolation - Quick Start Guide

**Last Updated:** October 16, 2025  
**Status:** ✅ Ready for Deployment Testing

---

## 🚀 Quick Start in 5 Minutes

### Step 1: Verify Prerequisites (1 minute)
```bash
# Check Python version (3.8+)
python --version

# Check if pytest is installed
pytest --version

# If not installed:
pip install pytest pytest-asyncio httpx
```

### Step 2: Validate Test Suite (1 minute)
```bash
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939

# Run validation script
python validate_tests.py
```

**Expected Output:**
```
✅ Test file syntax: VALID
✅ Pytest fixtures: DEFINED
✅ All 12 test scenarios defined
```

### Step 3: Review Implementation (2 minutes)
```bash
# Check key files exist
ls -lh GROUP_ISOLATION*.md
ls -lh tests/test_group_isolation.py
ls -lh run_group_isolation_tests.sh
```

### Step 4: Start API Server (1 minute)
```bash
cd code/content-processing-solution-accelerator/src/ContentProcessorAPI
uvicorn app.main:app --reload --port 8000
```

### Step 5: Run Tests (when ready)
```bash
# In a new terminal
cd /afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939
./run_group_isolation_tests.sh
```

---

## 📋 Test Execution Checklist

### Before Running Tests
- [ ] API server is running (`http://localhost:8000`)
- [ ] Database is accessible (Cosmos DB/MongoDB)
- [ ] Azure Storage is configured
- [ ] Test users have valid JWT tokens
- [ ] Environment variables are set

### Test Users Required
```python
# Update these in tests/test_group_isolation.py
TEST_USERS = {
    "user1": {
        "groups": ["group-a", "group-b"],
        "token": "YOUR_REAL_JWT_TOKEN_HERE"
    },
    "user2": {
        "groups": ["group-b", "group-c"],
        "token": "YOUR_REAL_JWT_TOKEN_HERE"
    },
    "user3": {
        "groups": ["group-a"],
        "token": "YOUR_REAL_JWT_TOKEN_HERE"
    }
}
```

### Running Tests
- [ ] Run validation script first
- [ ] Start with a subset of tests
- [ ] Review output for any failures
- [ ] Check server logs for errors
- [ ] Fix issues and re-run

---

## 🎯 Common Test Commands

### Run All Tests
```bash
pytest tests/test_group_isolation.py -v
```

### Run Specific Test Class
```bash
# Schema tests only
pytest tests/test_group_isolation.py::TestSchemaManagement -v

# Security tests only
pytest tests/test_group_isolation.py::TestSecurity -v
```

### Run Single Test
```bash
pytest tests/test_group_isolation.py::TestSecurity::test_no_cross_group_data_leakage -v
```

### Run with Coverage
```bash
pytest tests/test_group_isolation.py --cov=app/routers/proMode --cov-report=term
```

### Run with Verbose Output
```bash
pytest tests/test_group_isolation.py -v -s --tb=short
```

---

## 🔍 Quick Diagnostics

### Check API Health
```bash
curl http://localhost:8000/health
```

### Check Test Connectivity
```bash
curl http://localhost:8000/pro-mode/health
```

### Verify Authentication
```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://localhost:8000/pro-mode/schemas
```

---

## 📊 Expected Test Results

### All Tests Pass
```
12 passed in 15.23s
✅ ALL TESTS PASSED
```

### Some Tests Fail
1. Check error messages
2. Review server logs
3. Verify prerequisites
4. Fix issues
5. Re-run tests

---

## 🐛 Quick Troubleshooting

### Error: Connection Refused
**Fix:** Start the API server
```bash
uvicorn app.main:app --reload --port 8000
```

### Error: 401 Unauthorized
**Fix:** Update JWT tokens in test file
```python
# In tests/test_group_isolation.py
TEST_USERS["user1"]["token"] = "your_valid_token_here"
```

### Error: 500 Internal Server Error
**Fix:** Check server logs
```bash
# Look for stack traces in server terminal
```

### Error: Test Import Failed
**Fix:** Set PYTHONPATH
```bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

---

## 📚 Documentation Quick Links

| Document | Purpose | Size |
|----------|---------|------|
| `GROUP_ISOLATION_COMPLETE_DOCUMENTATION.md` | Full implementation guide | 24KB |
| `GROUP_ISOLATION_VALIDATION_PLAN.md` | Test scenarios | 26KB |
| `GROUP_ISOLATION_TESTING_COMPLETE.md` | Test summary | 12KB |
| `GROUP_ISOLATION_TEST_EXECUTION_SUMMARY.md` | Execution guide | 14KB |

---

## ✅ Success Indicators

### Test Suite is Ready When:
- ✅ Validation script passes
- ✅ No syntax errors
- ✅ All dependencies installed
- ✅ Documentation reviewed

### Tests are Ready to Run When:
- ✅ API server is running
- ✅ JWT tokens are configured
- ✅ Database is accessible
- ✅ Storage is configured

### Ready for Production When:
- ✅ All 12 tests pass
- ✅ No security issues found
- ✅ Performance is acceptable
- ✅ Backward compatibility verified

---

## 🎯 Next Actions

### Today
1. ✅ Validate test suite structure
2. ⏳ Set up test environment
3. ⏳ Configure test users with JWT tokens
4. ⏳ Run first test execution

### This Week
5. ⏳ Fix any test failures
6. ⏳ Performance testing
7. ⏳ Security audit
8. ⏳ Documentation review

### Before Production
9. ⏳ Staging deployment
10. ⏳ User acceptance testing
11. ⏳ Monitoring setup
12. ⏳ Production deployment

---

**Quick Reference Card:** Keep this guide handy for rapid test execution and troubleshooting!
