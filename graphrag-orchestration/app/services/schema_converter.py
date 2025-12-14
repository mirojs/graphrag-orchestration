"""
Schema Converter Service

Converts Azure Content Understanding JSON schemas to GraphRAG PropertyGraphIndex
entity and relation types.
"""

from typing import Dict, List, Tuple, Any, Optional
import logging
import re

logger = logging.getLogger(__name__)


class SchemaConverter:
    """
    Converts Content Understanding schemas to GraphRAG schemas.
    
    Azure Content Understanding schemas are JSON Schema format with nested objects
    and arrays. GraphRAG needs flat lists of entity types and relation types.
    
    Conversion Strategy:
    - Top-level properties → Entity types
    - Object properties → Entity types  
    - Array items → Entity types
    - Property relationships → Relation types
    """
    
    @staticmethod
    def to_pascal_case(snake_str: str) -> str:
        """Convert snake_case or kebab-case to PascalCase."""
        components = re.split(r'[_-]', snake_str)
        return ''.join(x.title() for x in components if x)
    
    @staticmethod
    def extract_entity_types(schema: Dict[str, Any], parent_name: str = "") -> List[str]:
        """
        Extract entity types from JSON schema.
        
        Args:
            schema: JSON Schema object
            parent_name: Parent entity name for nested objects
            
        Returns:
            List of entity type names in PascalCase
        """
        entities = []
        
        # Get properties from schema
        properties = schema.get("properties", {})
        
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type")
            
            # Convert property name to PascalCase entity name
            entity_name = SchemaConverter.to_pascal_case(prop_name)
            
            if prop_type == "object":
                # Nested object becomes an entity
                entities.append(entity_name)
                
                # Recursively extract nested entities
                nested_entities = SchemaConverter.extract_entity_types(
                    prop_schema, 
                    entity_name
                )
                entities.extend(nested_entities)
                
            elif prop_type == "array":
                # Array items are entities
                items_schema = prop_schema.get("items", {})
                item_type = items_schema.get("type")
                
                if item_type == "object":
                    # Array of objects - singular entity name
                    singular_name = entity_name.rstrip('s') if entity_name.endswith('s') else entity_name
                    entities.append(singular_name)
                    
                    # Extract nested properties from array item
                    nested_entities = SchemaConverter.extract_entity_types(
                        items_schema,
                        singular_name
                    )
                    entities.extend(nested_entities)
                else:
                    # Array of primitives - treat as entity attribute
                    entities.append(entity_name)
            
            else:
                # Primitive types can be entities if they're important
                # (e.g., "effective_date" → "EffectiveDate")
                entities.append(entity_name)
        
        # Add parent as root entity if provided
        if parent_name and parent_name not in entities:
            entities.insert(0, parent_name)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_entities = []
        for entity in entities:
            if entity not in seen:
                seen.add(entity)
                unique_entities.append(entity)
        
        return unique_entities
    
    @staticmethod
    def extract_relation_types(schema: Dict[str, Any], root_entity: Optional[str] = None) -> List[str]:
        """
        Extract relation types from JSON schema.
        
        Relations are inferred from property ownership and array memberships.
        
        Args:
            schema: JSON Schema object
            root_entity: Root entity name (from schema metadata or top-level)
            
        Returns:
            List of relation type names in UPPER_SNAKE_CASE
        """
        relations = []
        properties = schema.get("properties", {})
        
        # Infer root entity from schema name or use default
        if not root_entity:
            schema_name = schema.get("title", schema.get("name", "Document"))
            root_entity = SchemaConverter.to_pascal_case(schema_name)
        
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type")
            entity_name = SchemaConverter.to_pascal_case(prop_name)
            
            if prop_type == "object":
                # Root entity HAS this object
                relation = f"HAS_{prop_name.upper()}"
                relations.append(relation)
                
                # Recursively extract nested relations
                nested_relations = SchemaConverter.extract_relation_types(
                    prop_schema,
                    entity_name
                )
                relations.extend(nested_relations)
                
            elif prop_type == "array":
                items_schema = prop_schema.get("items", {})
                item_type = items_schema.get("type")
                
                if item_type == "object":
                    # Root entity CONTAINS array items
                    singular = prop_name.rstrip('s') if prop_name.endswith('s') else prop_name
                    relation = f"CONTAINS_{singular.upper()}"
                    relations.append(relation)
                    
                    # Extract nested relations
                    singular_entity = SchemaConverter.to_pascal_case(singular)
                    nested_relations = SchemaConverter.extract_relation_types(
                        items_schema,
                        singular_entity
                    )
                    relations.extend(nested_relations)
                else:
                    # Array of primitives
                    relation = f"HAS_{prop_name.upper()}"
                    relations.append(relation)
            else:
                # Primitive property
                relation = f"HAS_{prop_name.upper()}"
                relations.append(relation)
        
        # Add common relations
        common_relations = [
            "RELATED_TO",
            "PART_OF",
            "REFERENCES",
            "MENTIONED_IN",
        ]
        relations.extend(common_relations)
        
        # Remove duplicates
        return list(set(relations))
    
    @staticmethod
    def convert(schema: Dict[str, Any]) -> Tuple[List[str], List[str]]:
        """
        Convert Content Understanding schema to GraphRAG entity/relation types.
        
        Args:
            schema: Azure Content Understanding JSON Schema
            
        Returns:
            Tuple of (entity_types, relation_types)
            
        Example:
            >>> schema = {
            ...     "type": "object",
            ...     "properties": {
            ...         "contract_parties": {
            ...             "type": "array",
            ...             "items": {
            ...                 "type": "object",
            ...                 "properties": {
            ...                     "party_name": {"type": "string"},
            ...                     "role": {"type": "string"}
            ...                 }
            ...             }
            ...         },
            ...         "effective_date": {"type": "string"}
            ...     }
            ... }
            >>> entities, relations = SchemaConverter.convert(schema)
            >>> print(entities)
            ['ContractParty', 'PartyName', 'Role', 'EffectiveDate']
            >>> print(relations)
            ['CONTAINS_CONTRACT_PARTY', 'HAS_PARTY_NAME', 'HAS_ROLE', ...]
        """
        # Get schema metadata
        schema_title = schema.get("title", schema.get("name", "Document"))
        root_entity = SchemaConverter.to_pascal_case(schema_title)
        
        # Extract entities and relations
        entity_types = SchemaConverter.extract_entity_types(schema, root_entity)
        relation_types = SchemaConverter.extract_relation_types(schema, root_entity)
        
        logger.info(
            f"Converted schema '{schema_title}': "
            f"{len(entity_types)} entities, {len(relation_types)} relations"
        )
        
        return entity_types, relation_types
    
    @staticmethod
    def convert_with_metadata(
        schema: Dict[str, Any], 
        include_document_entity: bool = True
    ) -> Dict[str, Any]:
        """
        Convert schema and return with metadata for debugging.
        
        Args:
            schema: JSON Schema
            include_document_entity: Add "Document" entity and document relations
            
        Returns:
            Dictionary with entity_types, relation_types, and metadata
        """
        entity_types, relation_types = SchemaConverter.convert(schema)
        
        if include_document_entity:
            # Add document-level entities and relations
            if "Document" not in entity_types:
                entity_types.insert(0, "Document")
            
            document_relations = [
                "EXTRACTED_FROM",
                "CONTAINS_ENTITY",
                "REFERENCES_DOCUMENT",
            ]
            relation_types.extend(document_relations)
            relation_types = list(set(relation_types))
        
        return {
            "entity_types": entity_types,
            "relation_types": relation_types,
            "metadata": {
                "schema_name": schema.get("title", schema.get("name", "unknown")),
                "entity_count": len(entity_types),
                "relation_count": len(relation_types),
                "original_properties": list(schema.get("properties", {}).keys()),
            }
        }
