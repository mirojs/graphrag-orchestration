# ProMode API Testing Guide

## Overview
This guide provides comprehensive testing instructions for the ProMode API module, including unit tests, integration tests, and endpoint validation.

## Test Organization

### Test Structure
```
```
tests/
├── unit/
│   ├── test_proMode_models.py          # Model validation tests
│   └── test_proMode_endpoints.py       # Individual endpoint tests
├── integration/
│   ├── test_proMode_workflow.py        # End-to-end workflow tests
│   └── test_proMode_azure_integration.py # Azure services integration
├── api/
│   ├── test_proMode_api_validation.py  # API contract validation
│   └── test_proMode_performance.py     # Performance and load tests
├── conftest.py                         # Shared pytest fixtures and configuration
└── fixtures/
    ├── sample_schemas/                  # Test schema files
    ├── sample_files/                    # Test input/reference files
    └── mock_data.py                     # Mock data generators
```
```

## Test Categories

### 1. Unit Tests
Test individual components in isolation without external dependencies.

**File**: `tests/unit/test_proMode_models.py`
- Model validation (ProSchema, FieldSchema, etc.)
- Pydantic model serialization/deserialization
- Field type validation
- Business logic validation

**File**: `tests/unit/test_proMode_endpoints.py`
- Individual endpoint functionality
- Request/response validation
- Error handling
- Authentication checks

### 2. Integration Tests
Test interactions between multiple components and external services.

**File**: `tests/integration/test_proMode_workflow.py`
- Complete ProMode workflows
- Schema creation → File upload → Analysis
- Multi-file processing scenarios
- Error recovery scenarios

**File**: `tests/integration/test_proMode_azure_integration.py`
- Azure Blob Storage operations
- Azure Cosmos DB operations
- Azure Service Bus queue operations
- Authentication and authorization

### 3. API Tests
Test API contracts and performance.

**File**: `tests/api/test_proMode_api_validation.py`
- OpenAPI specification compliance
- Request/response schema validation
- HTTP status code validation
- API versioning compatibility

## Running Tests

### Prerequisites
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"
export COSMOS_CONNECTION_STRING="your_cosmos_connection"
export BLOB_STORAGE_URL="your_blob_storage_url"
export STORAGE_QUEUE_URL="your_queue_url"
```

### Test Execution Commands

#### Run All Tests
```bash
# Run all ProMode tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app.routers.proMode --cov-report=html
```

#### Run Specific Test Categories
```bash
# Unit tests only
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# API tests only
pytest tests/api/ -v
```

#### Run Specific Test Files
```bash
# Test ProMode models
pytest tests/unit/test_proMode_models.py -v

# Test ProMode workflows
pytest tests/integration/test_proMode_workflow.py -v

# Test API validation
pytest tests/api/test_proMode_api_validation.py -v
```

#### Run Tests with Filters
```bash
# Run tests matching pattern
pytest -k "test_upload" -v

# Run tests for specific class
pytest tests/unit/test_proMode_endpoints.py::TestProModeSchemas -v

# Run single test
pytest tests/unit/test_proMode_models.py::test_pro_schema_validation -v
```

### Test Configuration

#### pytest.ini
```ini
[tool:pytest]
minversion = 6.0
addopts = 
    -ra 
    -q 
    --strict-markers 
    --disable-warnings
    --tb=short
    --maxfail=5
    --durations=10

testpaths = tests
python_files = test_*.py *_test.py
python_classes = Test* *Tests
python_functions = test_*

markers =
    unit: Unit tests for individual components
    integration: Integration tests for workflows
    api: API contract and validation tests
    performance: Performance and load tests
    slow: Tests that take longer to run
    azure: Tests requiring Azure services
    mock: Tests using mocked dependencies
    smoke: Basic smoke tests for core functionality
    regression: Regression tests for bug fixes

timeout = 300
env =
    TESTING = true
    AZURE_MOCK_MODE = true
    LOG_LEVEL = WARNING
```

#### conftest.py
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_app_config():
    # Return mock configuration for testing
    pass
```

## Test Data Management

### Sample Test Files
- **Schema files**: JSON files with valid ProMode schema definitions
- **Input files**: PDF, image files for testing upload functionality
- **Reference files**: Supporting documents for multi-file analysis

### Mock Data
Use the `mock_data.py` file to generate consistent test data:
```python
from tests.fixtures.mock_data import generate_test_schema, generate_test_files
```

## Continuous Integration

### GitHub Actions Workflow
```yaml
name: ProMode API Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      - name: Run unit tests
        run: pytest tests/unit/ -v
      - name: Run integration tests
        run: pytest tests/integration/ -v --requires-azure
      - name: Generate coverage report
        run: pytest --cov=app.routers.proMode --cov-report=xml
```

## Test Scenarios

### Critical Test Scenarios
1. **Schema Upload and Validation**
   - Valid schema upload
   - Invalid JSON handling
   - Schema field validation
   - Duplicate schema handling

2. **File Upload Operations**
   - Single and multiple file uploads
   - File size validation
   - File type validation
   - Storage integration

3. **Multi-file Analysis**
   - Input and reference file relationships
   - Analysis workflow execution
   - Result comparison and aggregation

4. **Error Handling**
   - Authentication failures
   - Invalid request data
   - Azure service failures
   - Database connection issues

### Performance Test Scenarios
1. **Load Testing**
   - Multiple concurrent uploads
   - Large file handling
   - Schema processing performance

2. **Stress Testing**
   - Maximum file count limits
   - Memory usage under load
   - Database query performance

## Troubleshooting

### Common Issues
1. **Import Errors**: Ensure PYTHONPATH includes the src directory
2. **Azure Service Errors**: Check connection strings and permissions
3. **Database Errors**: Verify Cosmos DB connection and permissions
4. **Authentication Issues**: Check API keys and authentication setup

### Debug Mode
```bash
# Run tests with debug output
pytest tests/ -v -s --log-cli-level=DEBUG

# Run specific test with pdb debugger
pytest tests/unit/test_proMode_models.py::test_schema_validation -v -s --pdb
```

## Test Reporting

### Coverage Reports
- HTML coverage reports are generated in `htmlcov/`
- View detailed coverage: `open htmlcov/index.html`

### Test Results
- JUnit XML reports can be generated with `--junitxml=report.xml`
- Integration with CI/CD pipelines for automated reporting

## Best Practices

### Writing Tests
1. **Test Naming**: Use descriptive names that explain what is being tested
2. **Test Isolation**: Each test should be independent and not rely on others
3. **Mock External Dependencies**: Use mocks for Azure services in unit tests
4. **Test Data**: Use fixtures and factories for consistent test data
5. **Assertions**: Use specific assertions that clearly indicate test intent

### Test Maintenance
1. **Regular Updates**: Keep tests updated with API changes
2. **Performance Monitoring**: Monitor test execution time and optimize slow tests
3. **Coverage Goals**: Maintain minimum 80% code coverage
4. **Documentation**: Keep test documentation current with code changes

## Related Files
- **Main Module**: `app/routers/proMode.py`
- **Models**: Model definitions within proMode.py
- **Configuration**: `app/appsettings.py`
- **Main Application**: `app/main.py`
