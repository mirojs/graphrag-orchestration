# Schema-Guided Structured Retrieval Implementation

## Overview

You were absolutely right - **schemas are primarily for RETRIEVAL, not indexing**. This implementation adds the missing capability: extracting structured JSON output from the Knowledge Graph at query time using a user-provided JSON schema.

## What Was Implemented

### 1. New Service: `StructuredOutputService` (`app/services/structured_output_service.py`)

A dedicated service for schema-guided extraction that:
- Generates optimized prompts with schema descriptions
- Extracts structured JSON from retrieved context
- Validates output against the provided JSON schema
- Calculates confidence scores based on field completeness
- Tracks provenance (source nodes used for extraction)

### 2. New Endpoint: `POST /query/structured`

**Request:**
```json
{
    "query": "Extract invoice details from the uploaded documents",
    "output_schema": {
        "type": "object",
        "properties": {
            "vendor_name": {"type": "string", "description": "Name of the vendor"},
            "invoice_number": {"type": "string"},
            "total_amount": {"type": "number"},
            "due_date": {"type": "string"}
        },
        "required": ["vendor_name", "total_amount"]
    },
    "schema_name": "InvoiceExtraction",
    "top_k": 10
}
```

**Response:**
```json
{
    "query": "Extract invoice details from the uploaded documents",
    "mode": "structured-extraction",
    "answer": {
        "vendor_name": "Acme Corp",
        "invoice_number": "INV-2024-001",
        "total_amount": 15750.00,
        "due_date": "2024-02-15"
    },
    "sources": [
        {"id": "node-123", "score": 0.92, "entity_name": "Invoice Document"}
    ],
    "metadata": {
        "schema_name": "InvoiceExtraction",
        "confidence": 0.95,
        "validation_errors": [],
        "node_count": 5
    }
}
```

### 3. New Endpoint: `POST /query/structured-from-vault`

Same as above but references a schema by ID from Schema Vault:

```json
{
    "query": "Extract vendor and payment details from the invoice",
    "schema_id": "invoice-extraction-v1"
}
```

This fetches the schema from Cosmos DB Schema Vault automatically.

## Flow Diagram

```
User Query + JSON Schema
          │
          ▼
┌─────────────────────────┐
│  GraphRAG Retrieval     │
│  (Vector + Graph)       │
│  - Vector search        │
│  - 2-hop graph traversal│
└──────────┬──────────────┘
           │
           ▼ Retrieved Nodes
┌─────────────────────────┐
│  StructuredOutputService│
│  - Build context        │
│  - Generate prompt      │
│  - Call LLM             │
│  - Parse JSON           │
│  - Validate schema      │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  Structured JSON Output │
│  + Confidence Score     │
│  + Source Provenance    │
└─────────────────────────┘
```

## Schema vs Indexing vs Retrieval

| Aspect | Indexing-Time Schema | Retrieval-Time Schema |
|--------|---------------------|----------------------|
| **When** | Document ingestion | Query execution |
| **Purpose** | Guide entity extraction | Shape output format |
| **Schema Use** | Entity types, relations | Output field structure |
| **Flexibility** | Fixed after indexing | Different per query |
| **Example** | "Extract: Person, Organization, Contract" | "Output: {vendor, amount, date}" |

## Key Files Modified

1. **`app/services/structured_output_service.py`** (NEW)
   - `StructuredOutputService` class
   - `extract_structured()` async method
   - Schema validation, confidence calculation

2. **`app/services/retrieval_service.py`** (MODIFIED)
   - Added `structured_search()` method
   - Integrates StructuredOutputService

3. **`app/routers/graphrag.py`** (MODIFIED)
   - Added `StructuredQueryRequest` model
   - Added `StructuredQueryResponse` model  
   - Added `SchemaVaultQueryRequest` model
   - Added `POST /query/structured` endpoint
   - Added `POST /query/structured-from-vault` endpoint

## Usage Examples

### Example 1: Extract Contract Parties
```python
import requests

response = requests.post(
    "http://localhost:8001/graphrag/query/structured",
    headers={"X-Group-ID": "tenant-123"},
    json={
        "query": "Who are the buyer and seller in the purchase agreement?",
        "output_schema": {
            "type": "object",
            "properties": {
                "buyer": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"}
                    }
                },
                "seller": {
                    "type": "object", 
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"}
                    }
                },
                "contract_date": {"type": "string"}
            }
        }
    }
)

# Returns:
# {
#   "answer": {
#     "buyer": {"name": "TechCorp Inc.", "address": "123 Tech Blvd"},
#     "seller": {"name": "SupplyCo LLC", "address": "456 Supply Ave"},
#     "contract_date": "2024-01-15"
#   },
#   "metadata": {"confidence": 0.92}
# }
```

### Example 2: Extract from Schema Vault
```python
# First, save schema to vault
schema_response = requests.post(
    "http://localhost:8000/api/schemas",
    headers={"X-Group-ID": "tenant-123"},
    json={
        "name": "invoice-extraction",
        "schema": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "amount": {"type": "number"},
                "date": {"type": "string"}
            }
        }
    }
)
schema_id = schema_response.json()["schema_id"]

# Then use it for structured retrieval
response = requests.post(
    "http://localhost:8001/graphrag/query/structured-from-vault",
    headers={"X-Group-ID": "tenant-123"},
    json={
        "query": "What are the invoice details?",
        "schema_id": schema_id
    }
)
```

## Comparison with Previous Implementation

| Before | After |
|--------|-------|
| Schema used only at indexing time | Schema used at **retrieval time** |
| Free-text query responses | **Structured JSON** matching schema |
| No output format control | User-defined output structure |
| No confidence scores | **Confidence** based on completeness |
| No schema validation | **JSON Schema validation** |

## Testing

```bash
# Test structured retrieval endpoint
curl -X POST http://localhost:8001/graphrag/query/structured \
  -H "Content-Type: application/json" \
  -H "X-Group-ID: test-group" \
  -d '{
    "query": "Extract invoice details",
    "output_schema": {
      "type": "object",
      "properties": {
        "vendor": {"type": "string"},
        "amount": {"type": "number"}
      }
    }
  }'
```

## Architecture Notes

This implementation follows the same pattern as Azure Content Understanding:
1. User provides a JSON schema defining desired output
2. System retrieves relevant context (here: from Knowledge Graph)
3. LLM extracts structured data matching the schema
4. Output is validated and returned with confidence

The key difference is that we use the pre-built Knowledge Graph (entities, relationships, community summaries) instead of raw documents, enabling multi-document aggregation and relationship-aware extraction.
