# AI Enhancement Orchestration Refactoring

## 🎯 Overview

Refactoring the "AI Enhancement" functionality to move orchestration logic from frontend to backend, following the successful pattern from the Field Extraction refactoring and mapping to the real API test: `/natural_language_schema_creator_azure_api.py`

## 📋 Current AI Enhancement Implementation

### Frontend (`SchemaTab.tsx`)
- `handleAISchemaEnhancement()` function orchestrates the process
- Creates analyzer with complex schema structure
- Makes direct API calls (`PUT` to create analyzer, `POST` to analyze)
- Handles FormData upload and polling
- Complex error handling and state management

### Current Flow
1. **Frontend creates analyzer**: Complex MetaAISchemaEnhancer schema
2. **Frontend uploads schema as JSON file**: Creates FormData and uploads
3. **Frontend starts analysis**: POST to analyze endpoint  
4. **Frontend waits for results**: Polling or direct response

## 🚀 Target Implementation (Based on natural_language_schema_creator_azure_api.py)

### Real API Test Pattern Analysis
The `natural_language_schema_creator_azure_api.py` follows this pattern:
1. **Generate schema from natural language**: `create_schema_from_natural_language(description)`
2. **Create Azure analyzer**: PUT with generated schema
3. **Monitor status**: GET polling until ready
4. **Return validated schema**: Complete enhanced schema

### New Orchestrated Backend Endpoint
- **Endpoint**: `POST /pro-mode/ai-enhancement/orchestrated`
- **Handles complete flow internally**:
  1. Generate enhancement schema based on user intent 
  2. Create Azure analyzer (PUT)
  3. Monitor status (GET polling)
  4. Process and return enhanced schema results
- **Better error handling and retry logic**
- **Centralized business logic**

### Simplified Frontend
- Single API call to trigger enhancement
- Simple status monitoring
- Clean error handling
- Reduced complexity

## 📝 Implementation Plan

1. **Create new backend orchestration endpoint**
2. **Create new frontend service method**  
3. **Update SchemaTab component to use new method**
4. **Add proper error handling and status management**
5. **Update related documentation**

## 🔄 Benefits

- **Reliability**: Backend-to-backend API calls are more stable
- **Maintainability**: Business logic centralized in one place
- **Performance**: Reduced network round-trips
- **Security**: Sensitive logic kept on server
- **Easier Testing**: Can unit test the orchestration logic
- **Better Error Handling**: Centralized error management and retry logic
- **Mapping to Real API**: Follows the successful natural_language_schema_creator_azure_api.py pattern