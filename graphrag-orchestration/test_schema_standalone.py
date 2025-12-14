"""
Standalone Schema Converter Test

No external dependencies required.
"""

import sys
import os

# Add app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from app.services.schema_converter import SchemaConverter


def test_contract_schema():
    """Test conversion of a contract schema."""
    schema = {
        "title": "Contract",
        "type": "object",
        "properties": {
            "contract_parties": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "party_name": {"type": "string"},
                        "role": {"type": "string"}
                    }
                }
            },
            "effective_date": {"type": "string"},
            "contract_value": {"type": "number"}
        }
    }
    
    result = SchemaConverter.convert_with_metadata(schema)
    
    print("=" * 60)
    print(f"Schema: {result['metadata']['schema_name']}")
    print("=" * 60)
    print(f"\nEntity Types ({result['metadata']['entity_count']}):")
    for entity in result['entity_types']:
        print(f"  - {entity}")
    
    print(f"\nRelation Types ({result['metadata']['relation_count']}):")
    for i, relation in enumerate(result['relation_types']):
        if i < 15:  # Show first 15
            print(f"  - {relation}")
    
    print(f"\n✅ Contract schema: {len(result['entity_types'])} entities, {len(result['relation_types'])} relations\n")
    return result


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Schema Converter Test")
    print("="*60 + "\n")
    
    result = test_contract_schema()
    
    print("="*60)
    print("Test passed! ✅")
    print("="*60 + "\n")
    
    print("Sample GraphRAG indexing call:")
    print(f"""
POST /graphrag/index-from-schema
{{
  "schema_id": "contract-schema-123",
  "documents": ["Contract text here..."]
}}

Will extract these entities: {result['entity_types'][:5]}...
And create these relationships: {result['relation_types'][:5]}...
""")
