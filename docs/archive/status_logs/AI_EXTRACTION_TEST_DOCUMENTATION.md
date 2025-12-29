# AI Field Extraction Test Documentation

## Overview
This test framework provides an alternative analysis method alongside Azure Content Understanding, demonstrating AI-powered field extraction capabilities for invoice-contract verification scenarios.

## Purpose
- **Alternative Analysis Path**: Provides a backup/alternative to Azure Content Understanding services
- **Schema Validation**: Tests field extraction against predefined JSON schemas
- **Output Verification**: Validates the exact format and structure of AI responses
- **Development Testing**: Enables testing AI extraction logic without requiring live Azure OpenAI access

## Key Files

### Test Implementation
- **`test_actual_ai_extraction_output.py`**: Main test demonstrating AI field extraction
- **`ai_extraction_output_results.json`**: Sample output results for reference

### Schema Files
- **`data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION.json`**: Invoice-contract verification schema with 5 inconsistency detection fields

### Production Code
- **`code/content-processing-solution-accelerator/src/ContentProcessorAPI/app/routers/proMode.py`**: Fixed pro-mode implementation
- **`code/content-processing-solution-accelerator/src/ContentProcessor/src/libs/azure_helper/azure_openai.py`**: Standard mode reference pattern

## Test Capabilities

### 1. Schema Processing
```python
# Loads and validates JSON schema structure
schema = load_schema()
field_schema = schema['fieldSchema']
```

### 2. AI Response Simulation
```python
# Simulates realistic AI extraction results
ai_response = simulate_ai_extraction_output(schema)
```

### 3. Output Format Validation
```python
# Tests exact API response format
api_response = {
    "status": "success",
    "data": {
        "extraction_results": ai_results,
        "metadata": {
            "schema_name": schema['fieldSchema']['name'],
            "fields_processed": len(schema['fieldSchema']['fields']),
            "extraction_timestamp": datetime.now().isoformat(),
            "model_version": "gpt-4",
            "api_version": "2024-10-01-preview"
        }
    }
}
```

## Use Cases

### Development & Testing
- **Pre-deployment Validation**: Test extraction logic before Azure deployment
- **Schema Development**: Validate new schemas before production use
- **Response Format Testing**: Ensure API responses match expected structure

### Production Monitoring
- **Baseline Comparison**: Compare live results against expected outputs
- **Quality Assurance**: Validate extraction accuracy over time
- **Debugging**: Isolate issues in extraction vs. infrastructure

### Alternative Processing
- **Fallback Mechanism**: Use when Azure Content Understanding is unavailable
- **Cost Optimization**: Test locally before making expensive API calls
- **Development Environment**: Work offline or in restricted environments

## Future Enhancements

### 1. Multi-Schema Support
```python
# Support for multiple schema types
def load_multiple_schemas(schema_directory):
    schemas = {}
    for file in os.listdir(schema_directory):
        if file.endswith('.json'):
            schemas[file] = load_schema(os.path.join(schema_directory, file))
    return schemas
```

### 2. Real Data Integration
```python
# Process actual document content
def extract_from_document(document_path, schema):
    # Implementation for real document processing
    pass
```

### 3. Performance Benchmarking
```python
# Measure extraction performance
def benchmark_extraction(schema, iterations=100):
    # Performance testing implementation
    pass
```

## Running the Tests

### Basic Execution
```bash
python test_actual_ai_extraction_output.py
```

### Expected Output
- Schema validation results
- Simulated AI extraction results
- API response format validation
- Summary statistics
- Saved results file

### Output Files
- `ai_extraction_output_results.json`: Detailed extraction results
- Console output: Formatted display of results

## Integration Points

### With Azure Content Understanding
- Use as validation against Azure results
- Fallback when Azure services are unavailable
- Development testing without Azure costs

### With Production APIs
- Validate `/pro-mode/llm/extract-fields` endpoint responses
- Test schema compatibility before deployment
- Debug extraction issues in isolation

## Maintenance Notes

### Schema Updates
- Update simulation logic when schemas change
- Maintain realistic test data
- Validate against actual AI responses periodically

### Code Synchronization
- Keep test patterns aligned with production code
- Update API response formats as they evolve
- Maintain compatibility with authentication changes

## Historical Context
Created as part of Azure OpenAI authentication fix (September 2025), this test framework emerged from the need to validate AI extraction capabilities independently of live Azure services, providing a robust development and testing foundation for field extraction features.
