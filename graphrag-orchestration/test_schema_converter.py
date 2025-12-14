"""
Test Schema Converter

Validates conversion from Azure Content Understanding schemas to GraphRAG schemas.
"""

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
                        "role": {"type": "string"},
                        "address": {"type": "string"}
                    }
                }
            },
            "effective_date": {"type": "string"},
            "expiration_date": {"type": "string"},
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
    for relation in result['relation_types'][:10]:  # Show first 10
        print(f"  - {relation}")
    
    # Assertions
    assert "ContractParty" in result['entity_types']
    assert "PartyName" in result['entity_types']
    assert "EffectiveDate" in result['entity_types']
    assert "CONTAINS_CONTRACT_PARTY" in result['relation_types']
    assert "HAS_EFFECTIVE_DATE" in result['relation_types']
    
    print("\n✅ Contract schema conversion successful!\n")
    return result


def test_medical_schema():
    """Test conversion of a medical records schema."""
    schema = {
        "title": "MedicalRecord",
        "type": "object",
        "properties": {
            "patient": {
                "type": "object",
                "properties": {
                    "patient_id": {"type": "string"},
                    "name": {"type": "string"},
                    "date_of_birth": {"type": "string"}
                }
            },
            "diagnoses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "diagnosis_code": {"type": "string"},
                        "description": {"type": "string"},
                        "diagnosis_date": {"type": "string"}
                    }
                }
            },
            "medications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "medication_name": {"type": "string"},
                        "dosage": {"type": "string"},
                        "frequency": {"type": "string"}
                    }
                }
            }
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
    for relation in result['relation_types'][:10]:
        print(f"  - {relation}")
    
    # Assertions
    assert "Patient" in result['entity_types']
    assert "Diagnosis" in result['entity_types']
    assert "Medication" in result['entity_types']
    assert "CONTAINS_DIAGNOSIS" in result['relation_types']
    assert "CONTAINS_MEDICATION" in result['relation_types']
    
    print("\n✅ Medical schema conversion successful!\n")
    return result


def test_simple_schema():
    """Test conversion of a simple flat schema."""
    schema = {
        "title": "Invoice",
        "type": "object",
        "properties": {
            "invoice_number": {"type": "string"},
            "invoice_date": {"type": "string"},
            "total_amount": {"type": "number"},
            "vendor_name": {"type": "string"}
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
    for relation in result['relation_types'][:10]:
        print(f"  - {relation}")
    
    # Simple schemas should still work
    assert len(result['entity_types']) > 0
    assert len(result['relation_types']) > 0
    
    print("\n✅ Simple schema conversion successful!\n")
    return result


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Schema Converter Tests")
    print("="*60 + "\n")
    
    test_contract_schema()
    test_medical_schema()
    test_simple_schema()
    
    print("="*60)
    print("All tests passed! ✅")
    print("="*60 + "\n")
