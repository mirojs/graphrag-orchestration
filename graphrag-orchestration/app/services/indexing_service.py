"""
Indexing Service for GraphRAG Knowledge Graph Construction.

Uses LlamaIndex PropertyGraphIndex with SchemaLLMPathExtractor to extract
entities and relationships from documents, storing them in Neo4j.

Phase 2 Migration: Added neo4j-graphrag LLMEntityRelationExtractor as 'native' mode.
This uses the official neo4j-graphrag package for entity/relation extraction.

Supports multiple extraction modes:
- native: LLMEntityRelationExtractor from neo4j-graphrag (Phase 2 - recommended)
- schema: SchemaLLMPathExtractor with entity/relation type hints (legacy)
- schema_aware: SchemaAwareExtractor with full schema descriptions + table support
- simple: SimpleLLMPathExtractor for free-form extraction
- dynamic: DynamicLLMPathExtractor with allowed types
"""

from typing import List, Optional, Dict, Any
import logging

from llama_index.core import PropertyGraphIndex, Document
from llama_index.core.indices.property_graph import (
    SchemaLLMPathExtractor,
    SimpleLLMPathExtractor,
    DynamicLLMPathExtractor,
)
from llama_index.core.schema import TextNode

# neo4j-graphrag native extractor (Phase 2 migration)
from neo4j_graphrag.experimental.components.entity_relation_extractor import LLMEntityRelationExtractor
from neo4j_graphrag.experimental.components.types import TextChunk as NativeTextChunk, TextChunks
from neo4j_graphrag.experimental.components.schema import (
    SchemaBuilder,
    SchemaEntity,
    SchemaRelation,
    SchemaConfig,
)
from neo4j_graphrag.llm import AzureOpenAILLM

from app.services.graph_service import GraphService, MultiTenantNeo4jStore
from app.services.schema_aware_extractor import SchemaAwareExtractor, TableAwareExtractor
from app.services.llm_service import LLMService
from app.services.schema_converter import SchemaConverter
from app.services.schema_service import SchemaService
from app.core.config import settings
import json

logger = logging.getLogger(__name__)


def _ensure_openai_schema_compliance(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure JSON schema complies with OpenAI structured output requirements.
    
    OpenAI requires:
    - All object types must have "additionalProperties": false
    - This applies to nested objects, array items, and anyOf/oneOf variants
    
    This is borrowed from Azure Content Understanding schema format which has
    the same requirement.
    
    Args:
        schema: JSON schema to fix
        
    Returns:
        Fixed schema with additionalProperties added
    """
    if not isinstance(schema, dict):
        return schema
    
    # If this is an object type, ensure it has additionalProperties
    if schema.get("type") == "object":
        if "additionalProperties" not in schema:
            schema["additionalProperties"] = False
        
        # Recursively fix nested properties
        if "properties" in schema:
            for prop_name, prop_schema in schema["properties"].items():
                schema["properties"][prop_name] = _ensure_openai_schema_compliance(prop_schema)
    
    # Fix array items
    if schema.get("type") == "array" and "items" in schema:
        schema["items"] = _ensure_openai_schema_compliance(schema["items"])
    
    # Fix anyOf/oneOf/allOf variants
    for key in ["anyOf", "oneOf", "allOf"]:
        if key in schema:
            schema[key] = [_ensure_openai_schema_compliance(variant) for variant in schema[key]]
    
    return schema


# Default entity schema for GraphRAG
DEFAULT_ENTITY_TYPES = [
    "Person",
    "Organization", 
    "Location",
    "Event",
    "Document",
    "Concept",
    "Product",
    "Technology",
]

DEFAULT_RELATION_TYPES = [
    "WORKS_FOR",
    "LOCATED_IN",
    "RELATED_TO",
    "PART_OF",
    "MENTIONS",
    "AUTHORED_BY",
    "OCCURRED_AT",
    "USES",
    "CONTAINS",
]


class IndexingService:
    """
    Service for indexing documents into the Knowledge Graph.
    
    Workflow:
    1. Load documents from blob storage
    2. Chunk documents for processing
    3. Extract entities/relationships using LLM
    4. Store in Neo4j (graph with native vector indexes)
    5. Run community detection for GraphRAG Global Search
    """
    
    def __init__(self):
        self.graph_service = GraphService()
        self.llm_service = LLMService()
        self.schema_service = SchemaService()

    async def index_documents(
        self,
        group_id: str,
        documents: List[Document],
        entity_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
        extraction_mode: str = "native",  # native (recommended), schema_aware, simple, dynamic
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Index documents into the Knowledge Graph.
        
        Args:
            group_id: Tenant identifier for isolation
            documents: List of documents to index
            entity_types: Custom entity types (uses defaults if None)
            relation_types: Custom relation types (uses defaults if None)
            extraction_mode: Extraction strategy:
                - native: LLMEntityRelationExtractor from neo4j-graphrag (DEFAULT - recommended)
                - schema_aware: SchemaAwareExtractor with full schema + table support
                - simple: SimpleLLMPathExtractor for free extraction
                - dynamic: DynamicLLMPathExtractor with allowed types
            **kwargs: Additional arguments:
                - json_schema: Full JSON schema for schema_aware mode
            
        Returns:
            Indexing statistics
        """
        entity_types = entity_types or DEFAULT_ENTITY_TYPES
        relation_types = relation_types or DEFAULT_RELATION_TYPES
        
        # Use configured worker count (1=serial, 4=parallel)
        num_workers = settings.GRAPHRAG_NUM_WORKERS
        processing_mode = "serial" if num_workers == 1 else f"parallel ({num_workers} workers)"
        
        logger.info(
            f"Starting indexing for group {group_id}: "
            f"{len(documents)} documents, mode={extraction_mode}, "
            f"processing={processing_mode}"
        )
        
        # Get tenant-specific graph store
        graph_store = self.graph_service.get_store(group_id)
        
        # Configure extractor based on mode
        if extraction_mode == "native":
            # Phase 2: Use neo4j-graphrag LLMEntityRelationExtractor (DEFAULT)
            return await self._index_with_native_extractor(
                group_id=group_id,
                documents=documents,
                entity_types=entity_types,
                relation_types=relation_types,
                **kwargs,
            )
        elif extraction_mode == "schema_aware":
            # NEW: Schema-aware extractor with full schema descriptions + table support
            if not self.llm_service.llm:
                raise ValueError("LLM service not configured for schema-aware extraction")
            
            # Build full schema from entity/relation types if no raw schema provided
            schema = kwargs.get("json_schema", {})
            
            extractor = SchemaAwareExtractor(
                llm=self.llm_service.llm,
                embed_model=self.llm_service.embed_model,
                schema=schema,
                entity_types=entity_types,
                relation_types=relation_types,
                num_workers=num_workers,
                group_id=group_id,
                generate_embeddings=True,
            )
            logger.info(f"Using SchemaAwareExtractor with {len(entity_types)} entity types")
            
        elif extraction_mode == "schema":
            # Ensure LLM is available
            if not self.llm_service.llm:
                raise ValueError("LLM service not configured for schema-based extraction")
            
            # SchemaLLMPathExtractor expects entity/relation props as List[str]
            extractor = SchemaLLMPathExtractor(
                llm=self.llm_service.llm,
                possible_entity_props=entity_types,  # List of entity type names
                possible_relation_props=relation_types,  # List of relation type names
                strict=False,  # Allow entities outside schema
                num_workers=num_workers,  # 1=serial (low TPM), 4=parallel (high TPM)
            )
        elif extraction_mode == "simple":
            if not self.llm_service.llm:
                raise ValueError("LLM service not configured for simple extraction")
            
            extractor = SimpleLLMPathExtractor(
                llm=self.llm_service.llm,
                num_workers=num_workers,  # 1=serial (low TPM), 4=parallel (high TPM)
            )
        else:  # dynamic
            if not self.llm_service.llm:
                raise ValueError("LLM service not configured for dynamic extraction")
            
            extractor = DynamicLLMPathExtractor(
                llm=self.llm_service.llm,
                num_workers=num_workers,  # 1=serial (low TPM), 4=parallel (high TPM)
                allowed_entity_types=entity_types,
                allowed_relation_types=relation_types,
            )
        
        # Create PropertyGraphIndex for Neo4j entity/relationship extraction
        # Note: LlamaIndex's from_documents is synchronous, so we run it in executor
        import asyncio
        loop = asyncio.get_event_loop()
        
        def create_index():
            logger.info("Indexing documents directly")
            return PropertyGraphIndex.from_documents(
                documents,
                kg_extractors=[extractor],
                property_graph_store=graph_store,
                embed_model=self.llm_service.embed_model,
                show_progress=True,
            )

        index = await loop.run_in_executor(None, create_index)
        
        # NOTE: Dual indexing architecture:
        # 1. Azure AI Search: RAPTOR summaries with semantic ranking (accuracy enhancement)
        # 2. Neo4j: Entities/relationships via PropertyGraphIndex (graph traversal)
        
        # Get statistics
        nodes = graph_store.get()
        
        stats = {
            "group_id": group_id,
            "documents_indexed": len(documents),
            "nodes_created": len(nodes),
            "extraction_mode": extraction_mode,
            "entity_types": entity_types,
            "relation_types": relation_types,
        }
        
        logger.info(f"Indexing complete: {stats}")
        return stats

    async def _index_with_native_extractor(
        self,
        group_id: str,
        documents: List[Document],
        entity_types: List[str],
        relation_types: List[str],
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Phase 2: Index documents using neo4j-graphrag LLMEntityRelationExtractor.
        
        This uses the official neo4j-graphrag package for entity/relation extraction,
        providing better integration with Neo4j and potentially improved extraction quality.
        
        Args:
            group_id: Tenant identifier
            documents: List of documents to index
            entity_types: Entity types to extract
            relation_types: Relation types to extract
            
        Returns:
            Indexing statistics
        """
        import neo4j
        
        logger.info(f"Phase 2 native indexing for group {group_id}: {len(documents)} documents")
        
        # Create neo4j-graphrag LLM
        native_llm = AzureOpenAILLM(
            model_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION or "2024-02-01",
        )
        
        # Build SchemaConfig from entity/relation types.
        # The extractor accepts an optional schema to guide extraction.
        schema: Optional[SchemaConfig] = None
        if entity_types or relation_types:
            entities = [
                SchemaEntity(label=et, description=f"A {et} entity")
                for et in (entity_types or [])
            ]
            relations = [
                SchemaRelation(label=rt, description=f"A {rt} relationship")
                for rt in (relation_types or [])
            ]
            schema = SchemaBuilder.create_schema_model(
                entities=entities,
                relations=relations,
                potential_schema=None,
            )
        
        # Create native extractor
        extractor = LLMEntityRelationExtractor(
            llm=native_llm,
            create_lexical_graph=True,  # Also create text chunk nodes
            max_concurrency=settings.GRAPHRAG_NUM_WORKERS,
        )
        
        # Convert documents to neo4j-graphrag TextChunks
        chunks = []
        for i, doc in enumerate(documents):
            text = doc.text if hasattr(doc, 'text') else str(doc)
            chunks.append(NativeTextChunk(
                text=text,
                index=i,
                metadata={"group_id": group_id, "document_index": i},
                uid=f"{group_id}_doc_{i}",
            ))
        text_chunks = TextChunks(chunks=chunks)
        
        # Run extraction
        logger.info(f"Running native LLMEntityRelationExtractor on {len(chunks)} chunks...")
        graph = await extractor.run(chunks=text_chunks, schema=schema)
        
        # Add group_id to all nodes and relationships
        for node in graph.nodes:
            if node.properties is None:
                node.properties = {}
            node.properties["group_id"] = group_id
        
        for rel in graph.relationships:
            if rel.properties is None:
                rel.properties = {}
            rel.properties["group_id"] = group_id
        
        # Write to Neo4j using driver
        driver = neo4j.GraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
        
        try:
            with driver.session(database=settings.NEO4J_DATABASE or "neo4j") as session:
                # Write nodes
                for node in graph.nodes:
                    labels = ":".join(node.labels) if node.labels else "Entity"
                    props = node.properties or {}
                    props["id"] = node.id
                    
                    session.run(
                        f"MERGE (n:{labels} {{id: $id, group_id: $group_id}}) SET n += $props",
                        id=node.id,
                        props=props,
                        group_id=group_id,
                    )
                
                # Write relationships
                for rel in graph.relationships:
                    session.run(
                        f"""
                        MATCH (a {{id: $start_id, group_id: $group_id}})
                        MATCH (b {{id: $end_id, group_id: $group_id}})
                        MERGE (a)-[r:{rel.type}]->(b)
                        SET r += $props
                        SET r.group_id = $group_id
                        """,
                        start_id=rel.start_node_id,
                        end_id=rel.end_node_id,
                        props=rel.properties or {},
                        group_id=group_id,
                    )
                
                logger.info(f"Native extraction wrote {len(graph.nodes)} nodes, {len(graph.relationships)} relationships")
        finally:
            driver.close()
        
        stats = {
            "group_id": group_id,
            "documents_indexed": len(documents),
            "nodes_created": len(graph.nodes),
            "relationships_created": len(graph.relationships),
            "extraction_mode": "native",
            "extractor": "LLMEntityRelationExtractor",
            "package": "neo4j-graphrag",
            "entity_types": entity_types,
            "relation_types": relation_types,
        }
        
        logger.info(f"Native indexing complete: {stats}")
        return stats

    async def index_from_schema(
        self,
        group_id: str,
        schema_id: str,
        documents: List[Document],
        extraction_mode: str = "schema",
    ) -> Dict[str, Any]:
        """
        Index documents using a schema from the Schema Vault.
        
        This method fetches a Content Understanding schema from Cosmos DB,
        converts it to GraphRAG entity/relation types, and uses it for
        PropertyGraphIndex extraction.
        
        Args:
            group_id: Tenant identifier for isolation
            schema_id: Schema ID from Schema Vault
            documents: List of documents to index
            extraction_mode: Extraction strategy (schema, simple, dynamic)
            
        Returns:
            Indexing statistics including converted schema info
        """
        logger.info(
            f"Indexing from schema {schema_id} for group {group_id}: "
            f"{len(documents)} documents"
        )
        
        # Fetch schema from Cosmos DB
        schema_doc = self.schema_service.get_schema(schema_id, group_id)
        if not schema_doc:
            raise ValueError(f"Schema {schema_id} not found for group {group_id}")
        
        # Extract JSON Schema from document
        json_schema = self.schema_service.extract_json_schema(schema_doc)
        
        # Convert to GraphRAG entity/relation types
        conversion_result = SchemaConverter.convert_with_metadata(
            json_schema,
            include_document_entity=True
        )
        
        entity_types = conversion_result["entity_types"]
        relation_types = conversion_result["relation_types"]
        
        logger.info(
            f"Converted schema '{conversion_result['metadata']['schema_name']}': "
            f"{len(entity_types)} entities, {len(relation_types)} relations"
        )
        
        # Use schema_aware mode by default when we have a full schema
        # This leverages schema descriptions and table metadata for better extraction
        if extraction_mode == "schema":
            extraction_mode = "schema_aware"
            logger.info("Upgrading to schema_aware mode for full schema support")
        
        # Index documents with converted schema
        stats = await self.index_documents(
            group_id=group_id,
            documents=documents,
            entity_types=entity_types,
            relation_types=relation_types,
            extraction_mode=extraction_mode,
            json_schema=json_schema,  # Pass full schema for schema_aware mode
        )
        
        # Add schema conversion metadata to stats
        stats["schema_id"] = schema_id
        stats["schema_name"] = schema_doc.get("name", "unknown")
        stats["schema_conversion"] = conversion_result["metadata"]
        
        return stats

    async def index_from_schema_prompt(
        self,
        group_id: str,
        schema_prompt: str,
        documents: List[Document],
        extraction_mode: str = "simple",  # Changed from "schema" - avoids OpenAI strict validation
    ) -> Dict[str, Any]:
        """
        Index documents using a schema derived from a natural-language prompt.

        This mirrors the "quick query" behavior where the user provides a
        description and the system infers a suitable extraction schema.

        Args:
            group_id: Tenant identifier for isolation
            schema_prompt: Natural-language description of the desired schema
            documents: List of documents to index
            extraction_mode: Extraction strategy (simple, dynamic, schema)
                           Note: "schema" mode uses OpenAI structured output which has
                           strict validation requirements. Use "simple" for better compatibility.

        Returns:
            Indexing statistics including derived schema info
        """
        logger.info(
            f"Indexing from schema prompt for group {group_id}: "
            f"{len(documents)} documents"
        )

        # Ask LLM to draft a JSON Schema from the prompt
        prompt = (
            "You are a system that designs JSON Schemas for extracting entities "
            "and relations from documents to build a knowledge graph. Based on "
            "the following description, output ONLY a valid JSON object for a "
            "JSON Schema with these constraints: \n"
            "- include 'title' (CamelCase), 'type': 'object', and 'properties'\n"
            "- prefer nested 'object' or 'array' where appropriate\n"
            "- use snake_case for property keys\n"
            "- no additional commentary or code fences\n\n"
            f"Description: {schema_prompt}\n"
        )

        json_schema: Dict[str, Any]
        try:
            raw = self.llm_service.generate(prompt)
            # Attempt to extract JSON if surrounded by whitespace/code fences
            raw_str = str(raw).strip()
            if raw_str.startswith("```"):
                # remove code fences if present
                raw_str = "\n".join(
                    [line for line in raw_str.splitlines() if not line.strip().startswith("```")]
                )
                raw_str = raw_str.strip()
            json_schema = json.loads(raw_str)
            
            # Fix schema to comply with OpenAI structured output requirements
            # (borrowed from Azure CU format - requires additionalProperties: false)
            json_schema = _ensure_openai_schema_compliance(json_schema)
            
        except Exception as e:
            logger.warning(
                "Failed to derive JSON Schema from prompt, falling back to minimal schema",
                extra={"error": str(e)}
            )
            # Fallback minimal schema that still exercises the pipeline
            json_schema = {
                "title": "PromptSchema",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "mentions": {
                                    "type": "array",
                                    "items": {"type": "string"}
                                }
                            }
                        }
                    },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "source": {"type": "string"},
                                "target": {"type": "string"},
                                "relation": {"type": "string"}
                            }
                        }
                    }
                }
            }

        # Convert to GraphRAG entity/relation types
        conversion_result = SchemaConverter.convert_with_metadata(
            json_schema,
            include_document_entity=True
        )

        entity_types = conversion_result["entity_types"]
        relation_types = conversion_result["relation_types"]

        logger.info(
            f"Derived schema '{conversion_result['metadata']['schema_name']}': "
            f"{len(entity_types)} entities, {len(relation_types)} relations"
        )

        logger.info(f"🔍 About to index {len(documents)} documents with extracted content:")
        for i, doc in enumerate(documents[:3]):  # Log first 3 documents
            logger.info(f"   Doc {i+1}: {len(doc.text)} chars, metadata={doc.metadata}")

        # Index documents with converted schema
        stats = await self.index_documents(
            group_id=group_id,
            documents=documents,
            entity_types=entity_types,
            relation_types=relation_types,
            extraction_mode=extraction_mode,
        )

        # Add schema derivation metadata to stats
        stats["schema_source"] = "prompt"
        stats["schema_name"] = conversion_result["metadata"]["schema_name"]
        stats["schema_conversion"] = conversion_result["metadata"]
        stats["schema_prompt_excerpt"] = schema_prompt[:160]

        return stats

    async def run_community_detection(
        self,
        group_id: str,
        algorithm: str = "leiden",
    ) -> Dict[str, Any]:
        """
        Run community detection on the Knowledge Graph.
        
        This enables GraphRAG's Global Search capability by grouping
        related entities into communities for summarization.
        
        Args:
            group_id: Tenant identifier
            algorithm: Community detection algorithm (leiden, louvain)
            
        Returns:
            Community detection statistics
        """
        logger.info(f"Running {algorithm} community detection for group {group_id}")
        
        stats = self.graph_service.run_community_detection(
            group_id=group_id,
            algorithm=algorithm,
        )
        
        logger.info(f"Community detection complete: {stats}")
        return stats

    async def generate_community_summaries(
        self,
        group_id: str,
        level: int = 0,
    ) -> Dict[str, Any]:
        """
        Generate LLM summaries for each community.
        
        These summaries are used for GraphRAG Global Search to answer
        high-level, thematic questions.
        
        Args:
            group_id: Tenant identifier
            level: Community hierarchy level
            
        Returns:
            Summary generation statistics
        """
        communities = self.graph_service.get_community_summaries(group_id, level)
        
        summaries = []
        for community in communities:
            # Get all nodes in this community
            community_id = community["community_id"]
            members = community["sample_members"]
            
            # Generate summary using LLM
            prompt = f"""Summarize the following group of related entities from a knowledge graph.
            
Entities: {', '.join(members)}
Member count: {community['member_count']}

Provide a concise 2-3 sentence summary describing what this group represents and 
the key themes or relationships within it."""

            summary = self.llm_service.generate(prompt)
            
            summaries.append({
                "community_id": community_id,
                "member_count": community["member_count"],
                "summary": summary,
            })
        
        # Store summaries back in Neo4j
        graph_store = self.graph_service.get_store(group_id)
        for summary_data in summaries:
            query = """
            MATCH (n)
            WHERE n.group_id = $group_id AND n.community[$level] = $community_id
            WITH DISTINCT n.community[$level] AS cid LIMIT 1
            MERGE (c:Community {id: cid, group_id: $group_id, level: $level})
            SET c.summary = $summary, c.member_count = $member_count
            """
            graph_store.structured_query(
                query,
                {
                    "group_id": group_id,
                    "level": level,
                    "community_id": summary_data["community_id"],
                    "summary": summary_data["summary"],
                    "member_count": summary_data["member_count"],
                }
            )
        
        return {
            "group_id": group_id,
            "level": level,
            "communities_summarized": len(summaries),
        }
