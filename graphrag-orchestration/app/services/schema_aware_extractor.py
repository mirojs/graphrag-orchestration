"""
Schema-Aware Entity Extractor with ADI Table Support.

Optimizations implemented:
1. Table-Aware Entity Extraction - Uses ADI structured table metadata for direct field mapping
2. Schema-Driven Prompting - Uses full schema with descriptions in extraction prompts
3. Hierarchical Schema → Graph Structure - Preserves parent-child relationships in KG
4. Batch Embeddings from ADI Sections - Pre-computes embeddings for ADI sections

This extractor significantly improves extraction quality by:
- Leveraging ADI's structured table output instead of parsing markdown
- Using schema field descriptions to guide the LLM
- Preserving schema hierarchy in entity relationships
- Optimizing embedding generation with batch processing
"""

import re
import json
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from concurrent.futures import ThreadPoolExecutor

from llama_index.core.schema import BaseNode, TextNode
from llama_index.core.graph_stores.types import EntityNode, Relation
from llama_index.core.llms import ChatMessage, LLM
from llama_index.core.async_utils import run_jobs
from llama_index.core.bridge.pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Schema-aware extraction prompt template
SCHEMA_AWARE_EXTRACT_PROMPT = """
You are extracting entities and relationships from a document to build a knowledge graph.

## Target Schema
The user wants to extract information matching this schema:
{schema_description}

## Entity Types to Extract
{entity_types_with_descriptions}

## Relationship Types to Use
{relation_types_with_descriptions}

## Structured Table Data (if available)
The following tables were extracted from the document with their headers and rows:
{table_data}

## Document Text
{text}

## Instructions
1. Extract entities that match the schema's entity types
2. For each entity, provide a detailed description
3. Map table rows to entities when column headers match schema fields
4. Create relationships that preserve the schema hierarchy (parent → CONTAINS → child)
5. Include relationship descriptions that explain how entities are connected

## Output Format (JSON)
{{
  "entities": [
    {{
      "name": "Entity name or value",
      "type": "EntityType from schema",
      "description": "Detailed description of this entity",
      "schema_path": "path.to.field if mapped from schema",
      "source": "text|table|inferred"
    }}
  ],
  "relationships": [
    {{
      "source": "Source entity name",
      "target": "Target entity name",
      "relationship": "RELATIONSHIP_TYPE",
      "description": "How these entities are related",
      "hierarchical": true/false
    }}
  ]
}}

Extract entities and relationships:
"""


class SchemaField(BaseModel):
    """Represents a field in the extraction schema."""
    name: str
    field_type: str
    description: str = ""
    path: str = ""  # JSON path like "invoice.line_items.product"
    is_array: bool = False
    children: List["SchemaField"] = Field(default_factory=list)


class ExtractedEntity(BaseModel):
    """An extracted entity with schema mapping."""
    name: str
    entity_type: str
    description: str = ""
    schema_path: str = ""
    source: str = "text"  # text, table, inferred
    properties: Dict[str, Any] = Field(default_factory=dict)


class ExtractedRelation(BaseModel):
    """An extracted relationship with hierarchy info."""
    source: str
    target: str
    relationship: str
    description: str = ""
    hierarchical: bool = False
    schema_path: str = ""


class SchemaAwareExtractor:
    """
    Extract entities and relationships using schema-guided prompts.
    
    Key Features:
    1. Table-Aware: Processes ADI table metadata for direct field extraction
    2. Schema-Guided: Uses field descriptions to improve LLM accuracy
    3. Hierarchical: Preserves schema nesting in graph relationships
    4. Batch Optimized: Pre-computes embeddings for efficiency
    
    Note: This is a standalone extractor, not a LlamaIndex TransformComponent.
    Use it via PropertyGraphIndex's kg_extractors parameter or call directly.
    """
    
    def __init__(
        self,
        llm: Optional[LLM] = None,
        embed_model: Optional[Any] = None,
        schema: Optional[Dict[str, Any]] = None,
        entity_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
        max_paths_per_chunk: int = 30,
        num_workers: int = 4,
        group_id: str = "",
        generate_embeddings: bool = True,
    ):
        """
        Initialize the schema-aware extractor.
        
        Args:
            llm: LLM instance for extraction
            embed_model: Embedding model for entity embeddings
            schema: Full JSON schema with field descriptions
            entity_types: List of entity type names (derived from schema if not provided)
            relation_types: List of relation type names (derived from schema if not provided)
            max_paths_per_chunk: Maximum entity-relationship paths per chunk
            num_workers: Parallel workers for async extraction
            group_id: Multi-tenancy group ID
            generate_embeddings: Whether to generate embeddings for entities
        """
        self._llm = llm
        self._embed_model = embed_model
        self._extraction_schema: Dict[str, Any] = schema or {}
        self.entity_types = entity_types or []
        self.relation_types = relation_types or []
        self.max_paths_per_chunk = max_paths_per_chunk
        self.num_workers = num_workers
        self.group_id = group_id
        self.generate_embeddings = generate_embeddings
        
        # Parse schema into structured fields
        self._schema_fields: List[SchemaField] = []
        self._entity_type_descriptions: Dict[str, str] = {}
        self._relation_type_descriptions: Dict[str, str] = {}
        
        if self._extraction_schema:
            self._parse_schema()
    
    @property
    def llm(self) -> LLM:
        """Lazy load LLM."""
        if self._llm is None:
            from app.services.llm_service import LLMService
            self._llm = LLMService().llm
        assert self._llm is not None, "LLM service failed to initialize"
        return self._llm
    
    @property
    def embed_model(self):
        """Lazy load embedding model."""
        if self._embed_model is None:
            from app.services.llm_service import LLMService
            self._embed_model = LLMService().embed_model
        return self._embed_model
    
    def _parse_schema(self) -> None:
        """
        Parse JSON schema into structured fields with descriptions.
        
        Extracts:
        - Entity types from object/array properties
        - Field descriptions for prompting
        - Hierarchical relationships between fields
        """
        schema_name = self._extraction_schema.get("title", self._extraction_schema.get("name", "Document"))
        schema_desc = self._extraction_schema.get("description", "")
        
        # Add root entity
        self._entity_type_descriptions[self._to_pascal_case(schema_name)] = schema_desc
        
        # Recursively extract fields
        self._schema_fields = self._extract_fields(
            self._extraction_schema, 
            parent_path="",
            parent_name=schema_name
        )
        
        # Derive entity and relation types if not provided
        if not self.entity_types:
            self.entity_types = list(self._entity_type_descriptions.keys())
        
        if not self.relation_types:
            self.relation_types = list(self._relation_type_descriptions.keys())
        
        logger.info(
            f"Parsed schema '{schema_name}': "
            f"{len(self.entity_types)} entity types, "
            f"{len(self.relation_types)} relation types"
        )
    
    def _extract_fields(
        self, 
        schema: Dict[str, Any], 
        parent_path: str = "",
        parent_name: str = ""
    ) -> List[SchemaField]:
        """Recursively extract fields from schema."""
        fields = []
        properties = schema.get("properties", {})
        
        for prop_name, prop_schema in properties.items():
            prop_type = prop_schema.get("type", "string")
            prop_desc = prop_schema.get("description", "")
            current_path = f"{parent_path}.{prop_name}" if parent_path else prop_name
            
            entity_name = self._to_pascal_case(prop_name)
            
            field = SchemaField(
                name=prop_name,
                field_type=prop_type,
                description=prop_desc,
                path=current_path,
                is_array=prop_type == "array"
            )
            
            if prop_type == "object":
                # Object becomes an entity type
                self._entity_type_descriptions[entity_name] = prop_desc
                
                # Add hierarchical relation
                if parent_name:
                    rel_name = f"HAS_{prop_name.upper()}"
                    self._relation_type_descriptions[rel_name] = (
                        f"{parent_name} contains {entity_name}"
                    )
                
                # Recurse into nested properties
                field.children = self._extract_fields(prop_schema, current_path, entity_name)
                
            elif prop_type == "array":
                items_schema = prop_schema.get("items", {})
                item_type = items_schema.get("type", "string")
                
                if item_type == "object":
                    # Array of objects - singular entity name
                    singular_name = entity_name.rstrip('s') if entity_name.endswith('s') else entity_name
                    item_desc = items_schema.get("description", prop_desc)
                    self._entity_type_descriptions[singular_name] = item_desc
                    
                    # Add CONTAINS relation for arrays
                    if parent_name:
                        rel_name = f"CONTAINS_{prop_name.upper()}"
                        self._relation_type_descriptions[rel_name] = (
                            f"{parent_name} contains multiple {singular_name} items"
                        )
                    
                    # Recurse into array item properties
                    field.children = self._extract_fields(
                        items_schema, 
                        f"{current_path}[]",
                        singular_name
                    )
                else:
                    # Array of primitives
                    self._entity_type_descriptions[entity_name] = prop_desc
            else:
                # Primitive fields can be value entities
                if prop_desc:  # Only if it has a description (likely important)
                    self._entity_type_descriptions[entity_name] = prop_desc
            
            fields.append(field)
        
        return fields
    
    @staticmethod
    def _to_pascal_case(snake_str: str) -> str:
        """Convert snake_case or kebab-case to PascalCase."""
        components = re.split(r'[_\\-\\s]', snake_str)
        return ''.join(x.title() for x in components if x)
    
    def _format_schema_description(self) -> str:
        """Format schema as human-readable description for prompt."""
        if not self._extraction_schema:
            return "No specific schema provided. Extract general entities and relationships."
        
        name = self._extraction_schema.get("title", self._extraction_schema.get("name", "Document"))
        desc = self._extraction_schema.get("description", "Extract structured information from this document.")
        
        return f"**{name}**: {desc}"
    
    def _format_entity_types(self) -> str:
        """Format entity types with descriptions for prompt."""
        if not self._entity_type_descriptions:
            return "- Extract any relevant entities (people, organizations, documents, amounts, dates)"
        
        lines = []
        for entity_type, description in self._entity_type_descriptions.items():
            if description:
                lines.append(f"- **{entity_type}**: {description}")
            else:
                lines.append(f"- **{entity_type}**")
        
        return "\n".join(lines)
    
    def _format_relation_types(self) -> str:
        """Format relation types with descriptions for prompt."""
        # Default relations
        default_relations = [
            ("CONTAINS", "Parent entity contains child entity"),
            ("MENTIONS", "Document mentions this entity"),
            ("RELATED_TO", "General relationship between entities"),
            ("PART_OF", "Entity is part of another entity"),
            ("HAS_VALUE", "Entity has this value or attribute"),
        ]
        
        lines = []
        
        # Add schema-derived relations first
        for rel_type, description in self._relation_type_descriptions.items():
            lines.append(f"- **{rel_type}**: {description}")
        
        # Add default relations
        for rel_type, description in default_relations:
            if rel_type not in self._relation_type_descriptions:
                lines.append(f"- **{rel_type}**: {description}")
        
        return "\n".join(lines)
    
    def _format_table_data(self, node: BaseNode) -> str:
        """
        Extract and format table data from node metadata.
        
        ADI stores tables in metadata as:
        {
            "tables": [
                {"headers": [...], "rows": [{...}, {...}], "row_count": N, "column_count": M}
            ]
        }
        """
        tables = node.metadata.get("tables", [])
        
        if not tables:
            return "No structured tables found in this section."
        
        lines = []
        for i, table in enumerate(tables):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            
            if not headers:
                continue
            
            lines.append(f"\n### Table {i + 1}")
            lines.append(f"Columns: {', '.join(headers)}")
            
            # Show first few rows as examples
            for j, row in enumerate(rows[:5]):
                row_str = ", ".join([f"{k}: {v}" for k, v in row.items() if v])
                lines.append(f"  Row {j + 1}: {row_str}")
            
            if len(rows) > 5:
                lines.append(f"  ... and {len(rows) - 5} more rows")
        
        return "\n".join(lines) if lines else "No structured tables found."
    
    def __call__(
        self, 
        nodes: List[BaseNode], 
        show_progress: bool = False,
        **kwargs
    ) -> List[BaseNode]:
        """Synchronous extraction for compatibility."""
        return asyncio.run(self.acall(nodes, show_progress=show_progress, **kwargs))
    
    async def acall(
        self, 
        nodes: List[BaseNode], 
        show_progress: bool = False,
        **kwargs
    ) -> List[BaseNode]:
        """
        Extract entities and relationships from nodes asynchronously.
        
        Returns:
            Original nodes plus extracted EntityNode and Relation objects
        """
        jobs = []
        for node in nodes:
            jobs.append(self._aextract(node))
        
        results = await run_jobs(
            jobs,
            workers=self.num_workers,
            show_progress=show_progress,
            desc="Schema-aware entity extraction",
        )
        
        # Collect all entities for batch embedding
        all_entity_nodes: List[EntityNode] = []
        all_relations: List[Relation] = []
        
        for entity_nodes, relations in results:
            all_entity_nodes.extend(entity_nodes)
            all_relations.extend(relations)
        
        # Batch generate embeddings for all entities
        if self.generate_embeddings and all_entity_nodes:
            await self._batch_generate_embeddings(all_entity_nodes)
        
        # Return original nodes + extracted entities
        # EntityNodes are returned separately; they'll be added to the graph store
        result_nodes: List[BaseNode] = list(nodes)
        # Note: EntityNode extends BaseNode, cast for type safety
        for entity_node in all_entity_nodes:
            result_nodes.append(cast(BaseNode, entity_node))
        
        logger.info(
            f"Schema-aware extraction complete: "
            f"{len(all_entity_nodes)} entities, {len(all_relations)} relations"
        )
        
        return result_nodes
    
    async def _aextract(
        self, 
        node: BaseNode
    ) -> Tuple[List[EntityNode], List[Relation]]:
        """Extract entities and relationships from a single node."""
        text = node.get_content()
        
        if not text or len(text.strip()) < 10:
            return [], []
        
        # Build schema-aware prompt
        prompt = SCHEMA_AWARE_EXTRACT_PROMPT.format(
            schema_description=self._format_schema_description(),
            entity_types_with_descriptions=self._format_entity_types(),
            relation_types_with_descriptions=self._format_relation_types(),
            table_data=self._format_table_data(node),
            text=text[:8000]  # Limit text length
        )
        
        try:
            messages = [ChatMessage(role="user", content=prompt)]
            response = await asyncio.to_thread(self.llm.chat, messages)
            response_text = str(response).strip()
            
            # Parse the JSON response
            entities, relationships = self._parse_extraction_response(response_text)
            
            # Convert to EntityNode and Relation objects
            entity_nodes = self._create_entity_nodes(entities, node.node_id)
            relations = self._create_relations(relationships, node.node_id)
            
            return entity_nodes, relations
            
        except Exception as e:
            logger.error(f"Schema-aware extraction failed: {e}")
            return [], []
    
    def _parse_extraction_response(
        self, 
        response_text: str
    ) -> Tuple[List[ExtractedEntity], List[ExtractedRelation]]:
        """Parse LLM response into structured entities and relations."""
        entities: List[ExtractedEntity] = []
        relations: List[ExtractedRelation] = []
        
        try:
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                logger.warning("No JSON found in extraction response")
                return [], []
            
            data = json.loads(json_match.group())
            
            # Parse entities
            for e in data.get("entities", []):
                if not e.get("name"):
                    continue
                
                entities.append(ExtractedEntity(
                    name=e["name"],
                    entity_type=e.get("type", "Entity"),
                    description=e.get("description", ""),
                    schema_path=e.get("schema_path", ""),
                    source=e.get("source", "text"),
                    properties=e.get("properties", {})
                ))
            
            # Parse relationships
            for r in data.get("relationships", []):
                if not r.get("source") or not r.get("target"):
                    continue
                
                relations.append(ExtractedRelation(
                    source=r["source"],
                    target=r["target"],
                    relationship=r.get("relationship", "RELATED_TO"),
                    description=r.get("description", ""),
                    hierarchical=r.get("hierarchical", False),
                    schema_path=r.get("schema_path", "")
                ))
            
            logger.debug(
                f"Parsed {len(entities)} entities and {len(relations)} relations"
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse extraction JSON: {e}")
        
        return entities, relations
    
    def _create_entity_nodes(
        self, 
        entities: List[ExtractedEntity],
        source_id: str
    ) -> List[EntityNode]:
        """Create EntityNode objects from extracted entities."""
        entity_nodes = []
        
        for entity in entities:
            # Build properties including schema path
            properties = {
                "description": entity.description,
                "group_id": self.group_id,
                "triplet_source_id": source_id,
                "schema_path": entity.schema_path,
                "source": entity.source,
            }
            properties.update(entity.properties)
            
            entity_node = EntityNode(
                name=entity.name,
                label=entity.entity_type,
                properties=properties
            )
            entity_nodes.append(entity_node)
        
        return entity_nodes
    
    def _create_relations(
        self, 
        relations: List[ExtractedRelation],
        source_id: str
    ) -> List[Relation]:
        """Create Relation objects with hierarchy support."""
        result = []
        
        for rel in relations:
            properties = {
                "relationship_description": rel.description,
                "group_id": self.group_id,
                "triplet_source_id": source_id,
                "hierarchical": rel.hierarchical,
                "schema_path": rel.schema_path,
            }
            
            result.append(Relation(
                source_id=rel.source,
                target_id=rel.target,
                label=rel.relationship,
                properties=properties
            ))
        
        return result
    
    async def _batch_generate_embeddings(
        self, 
        entity_nodes: List[EntityNode]
    ) -> None:
        """
        Generate embeddings for all entities in batch.
        
        Uses entity name + description for richer embeddings.
        """
        if not self.embed_model:
            logger.warning("No embedding model available for batch embeddings")
            return
        
        try:
            # Build embedding texts (name + description for better semantics)
            texts = []
            for entity in entity_nodes:
                description = entity.properties.get("description", "")
                if description:
                    texts.append(f"{entity.name}: {description}")
                else:
                    texts.append(entity.name)
            
            logger.info(f"Generating batch embeddings for {len(texts)} entities...")
            
            # Generate embeddings in batch
            embeddings = await asyncio.to_thread(
                self.embed_model.get_text_embedding_batch,
                texts
            )
            
            # Assign embeddings to entities
            for entity, embedding in zip(entity_nodes, embeddings):
                entity.embedding = embedding
            
            logger.info(f"Generated {len(embeddings)} embeddings successfully")
            
        except Exception as e:
            logger.error(f"Batch embedding generation failed: {e}")


class TableAwareExtractor:
    """
    Utility class to extract entities directly from ADI table metadata.
    
    This bypasses LLM extraction for structured table data,
    mapping table columns directly to schema fields.
    """
    
    def __init__(
        self,
        schema: Dict[str, Any],
        group_id: str = "",
    ):
        self.schema = schema
        self.group_id = group_id
        self._column_mappings: Dict[str, str] = {}
        self._build_column_mappings()
    
    def _build_column_mappings(self) -> None:
        """Build mappings from column headers to schema fields."""
        def extract_fields(obj: Dict[str, Any], prefix: str = "") -> None:
            props = obj.get("properties", {})
            for name, field in props.items():
                path = f"{prefix}.{name}" if prefix else name
                # Map various header formats to this field
                self._column_mappings[name.lower()] = path
                self._column_mappings[name.replace("_", " ").lower()] = path
                self._column_mappings[self._to_header_format(name)] = path
                
                # Handle nested objects
                if field.get("type") == "object":
                    extract_fields(field, path)
                elif field.get("type") == "array":
                    items = field.get("items", {})
                    if items.get("type") == "object":
                        extract_fields(items, path)
        
        extract_fields(self.schema)
    
    @staticmethod
    def _to_header_format(name: str) -> str:
        """Convert field name to likely table header format."""
        return " ".join(w.title() for w in name.split("_")).lower()
    
    def extract_from_tables(
        self, 
        tables: List[Dict[str, Any]],
        source_id: str = "table"
    ) -> Tuple[List[EntityNode], List[Relation]]:
        """
        Extract entities directly from table metadata.
        
        Args:
            tables: List of table metadata from ADI
            source_id: Source identifier for provenance
            
        Returns:
            Tuple of (entity_nodes, relations)
        """
        entities: List[EntityNode] = []
        relations: List[Relation] = []
        
        for table_idx, table in enumerate(tables):
            headers = table.get("headers", [])
            rows = table.get("rows", [])
            
            # Map headers to schema paths
            header_mappings = {}
            for i, header in enumerate(headers):
                header_lower = header.lower().strip()
                if header_lower in self._column_mappings:
                    header_mappings[header] = self._column_mappings[header_lower]
            
            if not header_mappings:
                continue  # No schema mapping for this table
            
            # Create entities from rows
            for row_idx, row in enumerate(rows):
                row_entity_name = f"Row_{table_idx}_{row_idx}"
                
                # Create row entity
                row_entity = EntityNode(
                    name=row_entity_name,
                    label="TableRow",
                    properties={
                        "group_id": self.group_id,
                        "triplet_source_id": source_id,
                        "source": "table",
                        "table_index": table_idx,
                        "row_index": row_idx,
                    }
                )
                entities.append(row_entity)
                
                # Create value entities for each mapped column
                for header, schema_path in header_mappings.items():
                    value = row.get(header, "")
                    if not value:
                        continue
                    
                    value_entity = EntityNode(
                        name=str(value),
                        label=self._path_to_entity_type(schema_path),
                        properties={
                            "group_id": self.group_id,
                            "triplet_source_id": source_id,
                            "source": "table",
                            "schema_path": schema_path,
                            "column_header": header,
                        }
                    )
                    entities.append(value_entity)
                    
                    # Relate value to row
                    relations.append(Relation(
                        source_id=row_entity_name,
                        target_id=str(value),
                        label="HAS_VALUE",
                        properties={
                            "group_id": self.group_id,
                            "schema_path": schema_path,
                            "column": header,
                        }
                    ))
        
        logger.info(
            f"Table extraction: {len(entities)} entities, {len(relations)} relations "
            f"from {len(tables)} tables"
        )
        
        return entities, relations
    
    @staticmethod
    def _path_to_entity_type(path: str) -> str:
        """Convert schema path to entity type name."""
        parts = path.split(".")
        return "".join(p.title() for p in parts[-1].split("_"))
