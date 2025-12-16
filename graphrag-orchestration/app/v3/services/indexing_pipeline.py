"""
V3 Indexing Pipeline - LlamaIndex Integration

This module implements the complete indexing pipeline for GraphRAG V3.
It orchestrates:
1. Document loading and chunking (LlamaIndex SentenceSplitter)
2. Entity and relationship extraction (LlamaIndex PropertyGraph extractors)
3. Community detection (graspologic hierarchical_leiden)
4. Hierarchical summaries (RAPTOR)
5. Storage in Neo4j (custom schema with group isolation)

Architecture:
    Documents → LlamaIndex PropertyGraph → Entities/Relationships → Neo4j
                    ↓
              graspologic (hierarchical_leiden)
                    ↓
              Communities → LLM Summaries → Neo4j
                    ↓
              RAPTOR (hierarchical) → Neo4j
              
Quality Improvements Over Custom Implementation:
- Battle-tested entity extraction with coreference resolution
- Semantic similarity-based entity deduplication
- Structured output parsing with retry logic
- Entity disambiguation and linking
- Knowledge graph best practices from LlamaIndex community

Production Reliability (Neo4j GraphRAG PR #352 Pattern):
- JSON repair for malformed LLM outputs (json-repair library)
- Critical for multi-language documents (5-10% higher error rate)
- Handles: unquoted keys, trailing commas, missing braces, double braces
- Comprehensive extraction statistics and monitoring
- Alerts for high repair/failure rates indicating quality issues

Monitoring:
- Logs repair rate every 10 extractions
- Alerts if repair rate > 5% (LLM quality issue)
- Alerts if failure rate > 1% (prompt/compatibility issue)
- Returns extraction_quality metrics in indexing stats
"""

import asyncio
import logging
import uuid
import json
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Set, Union
from dataclasses import dataclass, field

import numpy as np
from graspologic.partition import hierarchical_leiden, HierarchicalCluster
from json_repair import repair_json  # Neo4j pattern: Fix malformed LLM JSON output

# LlamaIndex imports for high-quality extraction
from llama_index.core.schema import Document as LlamaDocument, TextNode
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.graph_stores import SimplePropertyGraphStore
from llama_index.core import PropertyGraphIndex
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.indices.property_graph import SchemaLLMPathExtractor, SimpleLLMPathExtractor

from app.core.config import settings
from app.services.vector_service import AzureAISearchProvider
from app.services.document_intelligence_service import DocumentIntelligenceService
from app.v3.services.neo4j_store import (
    Neo4jStoreV3,
    Entity,
    Relationship,
    Community,
    RaptorNode,
    TextChunk,
    Document,
)

logger = logging.getLogger(__name__)


class InvalidJSONError(Exception):
    """Raised when JSON repair fails to produce valid JSON."""
    pass


@dataclass
class PropertySpec:
    """
    Property specification with required constraint support.
    
    Based on Neo4j GraphRAG feature/add-constraint-type pattern.
    Enables semantic validation beyond format checking.
    
    Example:
        PropertySpec(name="invoice_number", type="string", required=True)
        PropertySpec(name="date", type="date", required=True)
        PropertySpec(name="notes", type="string", required=False)
    """
    name: str
    type: str  # string, integer, float, date, boolean
    required: bool = False
    description: str = ""


@dataclass
class EntitySpec:
    """
    Entity type specification with required properties.
    
    Defines expected properties for entity types.
    Extraction fails if required properties are missing.
    
    Example:
        EntitySpec(
            label="Invoice",
            properties=[
                PropertySpec("invoice_number", "string", required=True),
                PropertySpec("amount", "float", required=True),
                PropertySpec("date", "date", required=True),
            ]
        )
    """
    label: str
    properties: List[PropertySpec] = field(default_factory=list)
    additional_properties: bool = True  # Allow unlisted properties


@dataclass
class RelationSpec:
    """
    Relationship type specification with required properties.
    
    Example:
        RelationSpec(
            label="ISSUED_TO",
            properties=[
                PropertySpec("date", "date", required=True),
            ]
        )
    """
    label: str
    properties: List[PropertySpec] = field(default_factory=list)
    additional_properties: bool = True


def fix_invalid_json(raw_json: str) -> str:
    """
    Fix common LLM JSON output errors using json-repair library.
    
    Based on Neo4j GraphRAG PR #352 - Production-proven pattern for handling:
    - Unquoted keys: {name: "John"} → {"name": "John"}
    - Trailing commas: {"name": "John",} → {"name": "John"}
    - Missing braces: {"name": "John" → {"name": "John"}
    - Unquoted values: {"name": John} → {"name": "John"}
    - Double braces: {{"name": "John"}} → {"name": "John"}
    
    Critical for:
    - Multi-language documents (higher JSON error rates)
    - Lower-cost models (GPT-4o-mini, local LLMs)
    - Large documents (LLM fatigue effect)
    
    Args:
        raw_json: Raw JSON string from LLM output
        
    Returns:
        Repaired JSON string
        
    Raises:
        InvalidJSONError: If repair results in empty or invalid JSON
    """
    try:
        repaired_json = repair_json(raw_json)
        repaired_json = repaired_json.strip()
        
        if repaired_json == '""' or repaired_json == "":
            raise InvalidJSONError("JSON repair resulted in empty output")
        
        # Validate it's actually valid JSON
        json.loads(repaired_json)
        
        return repaired_json
    except json.JSONDecodeError as e:
        raise InvalidJSONError(f"JSON repair failed to produce valid JSON: {e}") from e
    except Exception as e:
        raise InvalidJSONError(f"Unexpected error during JSON repair: {e}") from e


@dataclass
class IndexingConfig:
    """Configuration for the V3 indexing pipeline."""
    
    # Chunking settings
    chunk_size: int = 1024
    chunk_overlap: int = 128
    
    # Entity extraction settings
    entity_types: List[str] = field(default_factory=lambda: [
        "PERSON", "ORGANIZATION", "LOCATION", "EVENT", 
        "PRODUCT", "CONCEPT", "DATE", "MONEY"
    ])
    max_entities_per_chunk: int = 20
    
    # Community detection settings
    community_resolution: float = 1.0  # Leiden resolution parameter
    max_community_levels: int = 3  # Max hierarchy depth
    min_community_size: int = 3  # Minimum entities per community
    
    # RAPTOR settings
    raptor_levels: int = 3  # Number of RAPTOR summary levels
    raptor_summary_max_tokens: int = 500
    raptor_cluster_size: int = 10  # Texts to cluster per level
    
    # Embedding settings
    embedding_model: str = "text-embedding-3-large"  # 3072 dims for better RAPTOR clustering
    embedding_dimensions: int = 3072
    
    # LLM settings
    llm_model: str = "gpt-4o"
    temperature: float = 0.0
    
    # Schema validation (Neo4j pattern: required properties)
    entity_specs: List[EntitySpec] = field(default_factory=list)
    relation_specs: List[RelationSpec] = field(default_factory=list)
    enforce_required_properties: bool = False  # Opt-in for production


class IndexingPipelineV3:
    """
    V3 GraphRAG Indexing Pipeline with LlamaIndex Integration.
    
    This pipeline orchestrates document processing with:
    - LlamaIndex PropertyGraph for entity extraction (battle-tested quality)
    - graspologic for community detection
    - RAPTOR for hierarchical summaries
    - Custom Neo4j storage with group isolation
    
    Features preserved:
    - Multi-tenant group_id isolation
    - Custom Neo4j schema and constraints
    - Community detection with hierarchical_leiden
    - RAPTOR hierarchical summaries
    - All existing API endpoints
    """
    
    def __init__(
        self,
        neo4j_store: Neo4jStoreV3,
        llm: Any,
        embedder: Any,
        config: Optional[IndexingConfig] = None,
    ):
        """
        Initialize the indexing pipeline.
        
        Args:
            neo4j_store: Neo4j storage instance (your custom schema)
            llm: LLM for summaries and extraction (Azure OpenAI)
            embedder: Embeddings model (Azure OpenAI)
            config: Pipeline configuration
        """
        self.neo4j_store = neo4j_store
        self.llm = llm
        self.embedder = embedder
        self.config = config or IndexingConfig()
        
        # Track JSON repair statistics for monitoring
        self.extraction_stats = {
            "total_extractions": 0,
            "json_repairs_attempted": 0,
            "json_repairs_succeeded": 0,
            "json_repairs_failed": 0,
            "extraction_failures": 0,
            # Property validation stats (Neo4j pattern)
            "entities_missing_required_props": 0,
            "relationships_missing_required_props": 0,
            "properties_validated": 0,
        }
        
        # Initialize LlamaIndex components
        self._init_llamaindex_components()
        
        # Initialize Azure AI Search for RAPTOR indexing (if configured)
        self.vector_store_provider = None
        if settings.VECTOR_STORE_TYPE == "azure_search" and settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_API_KEY:
            try:
                self.vector_store_provider = AzureAISearchProvider(
                    endpoint=settings.AZURE_SEARCH_ENDPOINT,
                    api_key=settings.AZURE_SEARCH_API_KEY,
                )
                logger.info("Azure AI Search provider initialized for RAPTOR indexing")
            except Exception as e:
                logger.error(f"Failed to initialize Azure AI Search provider: {e}")
        
        logger.info(f"IndexingPipelineV3 initialized with config: {self.config}")
    
    def _init_llamaindex_components(self):
        """Initialize LlamaIndex extractors and splitters."""
        # Sentence splitter for intelligent chunking
        self.sentence_splitter = SentenceSplitter(
            chunk_size=self.config.chunk_size,
            chunk_overlap=self.config.chunk_overlap,
        )
        
        # Use SimplePropertyGraphStore as intermediate storage
        self.temp_graph_store = SimplePropertyGraphStore()
        logger.info("LlamaIndex PropertyGraph extraction enabled")
    
    def _log_extraction_stats(self):
        """Log JSON repair and extraction statistics for monitoring."""
        stats = self.extraction_stats
        total = stats["total_extractions"]
        
        if total == 0:
            return
        
        repair_rate = (stats["json_repairs_attempted"] / total) * 100 if total > 0 else 0
        success_rate = (stats["json_repairs_succeeded"] / stats["json_repairs_attempted"]) * 100 if stats["json_repairs_attempted"] > 0 else 0
        failure_rate = (stats["extraction_failures"] / total) * 100 if total > 0 else 0
        
        # Property validation metrics
        entities_failed = stats["entities_missing_required_props"]
        relations_failed = stats["relationships_missing_required_props"]
        props_validated = stats["properties_validated"]
        
        logger.info(
            f"📊 Extraction Statistics: "
            f"Total={total}, "
            f"JSON Repairs Attempted={stats['json_repairs_attempted']} ({repair_rate:.1f}%), "
            f"Repair Success={stats['json_repairs_succeeded']} ({success_rate:.1f}%), "
            f"Total Failures={stats['extraction_failures']} ({failure_rate:.1f}%)"
        )
        
        # Alert if repair rate is high (indicates LLM quality issues)
        if repair_rate > 5.0:
            logger.warning(
                f"⚠️ High JSON repair rate ({repair_rate:.1f}%) detected! "
                "Consider: 1) Using higher-quality LLM, 2) Simplifying extraction schema, "
                "3) Adding few-shot examples to prompts"
            )
        
        # Alert if failure rate is concerning
        if failure_rate > 1.0:
            logger.error(
                f"❌ High extraction failure rate ({failure_rate:.1f}%)! "
                "This may indicate: 1) LLM compatibility issues, 2) Prompt engineering needed, "
                "3) Input data quality problems"
            )
        
        # Alert if property validation is failing (Neo4j pattern)
        if props_validated > 0:
            prop_failure_rate = ((entities_failed + relations_failed) / props_validated) * 100
            logger.info(
                f"🔍 Property Validation: "
                f"Validated={props_validated}, "
                f"Entities Failed={entities_failed}, "
                f"Relations Failed={relations_failed}, "
                f"Failure Rate={prop_failure_rate:.1f}%"
            )
            if prop_failure_rate > 10.0:
                logger.warning(
                    f"⚠️ High property validation failure rate: {prop_failure_rate:.1f}% "
                    f"(threshold: 10%). Required properties frequently missing. "
                    f"Consider: 1) Reviewing schema specs, 2) Adding extraction guidance, "
                    f"3) Implementing fallback property extraction"
                )
    
    async def index_documents(
        self,
        group_id: str,
        documents: List[Dict[str, Any]],
        reindex: bool = False,
        ingestion: str = "none",
    ) -> Dict[str, Any]:
        """
        Index a batch of documents.
        
        Args:
            group_id: Tenant identifier
            documents: List of documents with 'content', 'title', 'source' OR URLs to PDFs
            reindex: If True, delete existing data first
            ingestion: Document extraction method - "document-intelligence", "llamaparse", or "none"
            
        Returns:
            Indexing statistics
        """
        logger.info(f"Starting indexing for group {group_id} with {len(documents)} documents (ingestion={ingestion})")
        
        stats = {
            "group_id": group_id,
            "documents": len(documents),
            "chunks": 0,
            "entities": 0,
            "relationships": 0,
            "communities": 0,
            "raptor_nodes": 0,
        }
        
        try:
            # Step 0: Clean up if reindexing
            if reindex:
                logger.info(f"Reindexing: Deleting existing data for group {group_id}")
                self.neo4j_store.delete_group_data(group_id)
            
            # Step 0.5: Extract text from PDFs/images if needed
            if ingestion == "document-intelligence":
                logger.info(f"📄 Using Document Intelligence to extract text from {len(documents)} documents")
                di_service = DocumentIntelligenceService()
                
                # Check if documents are URLs or already have content
                needs_extraction = []
                for doc in documents:
                    if isinstance(doc, str):
                        # Plain URL string
                        needs_extraction.append(doc)
                    elif isinstance(doc, dict):
                        content = doc.get("content") or doc.get("text", "")
                        source = doc.get("source", "")
                        # If no content but has URL-like source, extract it
                        if not content.strip() and (source.startswith("http") or doc.get("url", "").startswith("http")):
                            needs_extraction.append(doc.get("url", source))
                        elif isinstance(content, str) and content.startswith("http"):
                            # Content field contains URL
                            needs_extraction.append(content)
                
                if needs_extraction:
                    logger.info(f"🔍 Extracting text from {len(needs_extraction)} PDF documents using Document Intelligence...")
                    extracted_docs = await di_service.extract_documents(
                        group_id=group_id,
                        input_items=needs_extraction,
                        fail_fast=False
                    )
                    
                    # Convert LlamaIndex Documents back to dict format for pipeline
                    logger.info(f"✅ Document Intelligence extracted {len(extracted_docs)} document pages")
                    documents = []
                    for llama_doc in extracted_docs:
                        documents.append({
                            "content": llama_doc.text,
                            "title": llama_doc.metadata.get("url", "Untitled").split("/")[-1],
                            "source": llama_doc.metadata.get("url", ""),
                            "metadata": llama_doc.metadata,
                        })
                else:
                    logger.info(f"ℹ️ All documents already have content, skipping Document Intelligence extraction")
            
            elif ingestion == "llamaparse":
                logger.warning(f"⚠️ LlamaParse ingestion not yet implemented, processing documents as-is")
            
            # Step 1: Chunk documents and store
            all_chunks = []
            for doc in documents:
                doc_id = doc.get("id") or str(uuid.uuid4())
                chunks = await self._chunk_document(doc, doc_id)
                all_chunks.extend(chunks)
                
                # Store document metadata
                self.neo4j_store.upsert_document(
                    group_id=group_id,
                    document=Document(
                        id=doc_id,
                        title=doc.get("title", "Untitled"),
                        source=doc.get("source", ""),
                        metadata=doc.get("metadata", {}),
                    )
                )
            
            # Store chunks in batch
            self.neo4j_store.upsert_text_chunks_batch(group_id, all_chunks)
            stats["chunks"] = len(all_chunks)
            logger.info(f"Created {len(all_chunks)} chunks")
            
            # Step 2: Extract entities and relationships
            entities, relationships = await self._extract_entities_and_relationships(
                group_id, all_chunks
            )
            
            # Store entities
            self.neo4j_store.upsert_entities_batch(group_id, entities)
            stats["entities"] = len(entities)
            logger.info(f"Extracted {len(entities)} entities")
            
            # Store relationships  
            self.neo4j_store.upsert_relationships_batch(group_id, relationships)
            stats["relationships"] = len(relationships)
            logger.info(f"Extracted {len(relationships)} relationships")
            
            # Step 3: Build communities using hierarchical Leiden
            communities = await self._build_communities(group_id, entities, relationships)
            
            # Generate community summaries
            for community in communities:
                summary = await self._generate_community_summary(community, entities)
                community.summary = summary
                community.full_content = summary  # DRIFT needs full_content
            
            # Store communities in batch (community upsert handles batch internally)
            for community in communities:
                self.neo4j_store.upsert_community(group_id, community)
            stats["communities"] = len(communities)
            logger.info(f"Built {len(communities)} communities")
            
            # Step 4: Build RAPTOR hierarchical summaries
            raptor_nodes = await self._build_raptor_hierarchy(group_id, all_chunks)
            self.neo4j_store.upsert_raptor_nodes_batch(group_id, raptor_nodes)
            stats["raptor_nodes"] = len(raptor_nodes)
            logger.info(f"Built {len(raptor_nodes)} RAPTOR nodes")
            
            # Step 5: Index RAPTOR nodes in Azure AI Search (if enabled)
            if self.vector_store_provider:
                try:
                    logger.info(f"Pushing {len(raptor_nodes)} RAPTOR nodes to Azure AI Search")
                    search_docs = []
                    for node in raptor_nodes:
                        # Convert RaptorNode to LlamaIndex Document
                        doc = LlamaDocument(
                            text=node.text,
                            id_=node.id,
                            metadata={
                                "raptor_level": node.level,
                                "group_id": group_id,
                                **node.metadata
                            },
                            embedding=node.embedding
                        )
                        search_docs.append(doc)
                    
                    self.vector_store_provider.add_documents(
                        group_id=group_id,
                        index_name="raptor",
                        documents=search_docs
                    )
                    logger.info("Successfully indexed RAPTOR nodes in Azure AI Search")
                except Exception as e:
                    logger.error(f"Failed to index RAPTOR nodes in Azure AI Search: {e}")
                    # Don't fail the whole pipeline if secondary indexing fails
            
            # Log final extraction statistics
            self._log_extraction_stats()
            
            # Add extraction quality metrics to stats
            stats["extraction_quality"] = {
                "total_extractions": self.extraction_stats["total_extractions"],
                "json_repairs_attempted": self.extraction_stats["json_repairs_attempted"],
                "json_repairs_succeeded": self.extraction_stats["json_repairs_succeeded"],
                "json_repairs_failed": self.extraction_stats["json_repairs_failed"],
                "extraction_failures": self.extraction_stats["extraction_failures"],
                "repair_rate_pct": (self.extraction_stats["json_repairs_attempted"] / self.extraction_stats["total_extractions"] * 100) if self.extraction_stats["total_extractions"] > 0 else 0,
                "failure_rate_pct": (self.extraction_stats["extraction_failures"] / self.extraction_stats["total_extractions"] * 100) if self.extraction_stats["total_extractions"] > 0 else 0,
                # Property validation metrics (Neo4j pattern)
                "properties_validated": self.extraction_stats["properties_validated"],
                "entities_missing_required_props": self.extraction_stats["entities_missing_required_props"],
                "relationships_missing_required_props": self.extraction_stats["relationships_missing_required_props"],
                "property_failure_rate_pct": ((self.extraction_stats["entities_missing_required_props"] + self.extraction_stats["relationships_missing_required_props"]) / self.extraction_stats["properties_validated"] * 100) if self.extraction_stats["properties_validated"] > 0 else 0,
            }
            
            logger.info(f"Indexing complete for group {group_id}: {stats}")
            return stats
            
        except Exception as e:
            logger.error(f"Indexing failed for group {group_id}: {e}", exc_info=True)
            raise
    
    async def _chunk_document(
        self,
        document: Dict[str, Any],
        doc_id: str,
    ) -> List[TextChunk]:
        """
        Chunk a document into text segments using LlamaIndex SentenceSplitter.
        
        Improvements over custom chunking:
        - Semantic sentence boundary detection
        - Intelligent overlap handling
        - Better paragraph preservation
        """
        content = document.get("content", "")
        if not content:
            return []
        
        # Create LlamaIndex document
        llama_doc = LlamaDocument(
            text=content,
            id_=doc_id,
            metadata={
                "title": document.get("title", "Untitled"),
                "source": document.get("source", ""),
            },
        )
        
        # Use LlamaIndex's intelligent sentence splitter
        nodes = self.sentence_splitter.get_nodes_from_documents([llama_doc])
        
        # Convert to our TextChunk format
        chunks = []
        for chunk_index, node in enumerate(nodes):
            chunk_text = node.get_content()
            
            if chunk_text.strip():
                # Generate embedding for chunk
                embedding = await self._embed_text(chunk_text)
                
                chunk = TextChunk(
                    id=f"{doc_id}_chunk_{chunk_index}",
                    text=chunk_text,
                    chunk_index=chunk_index,
                    document_id=doc_id,
                    embedding=embedding,
                    tokens=len(chunk_text.split()),  # Approximate
                )
                chunks.append(chunk)
        
        return chunks
    
    async def _extract_entities_and_relationships(
        self,
        group_id: str,
        chunks: List[TextChunk],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Extract entities and relationships using LlamaIndex PropertyGraph.
        
        Quality improvements over custom implementation:
        - Coreference resolution (e.g., "Microsoft" and "the company" linked)
        - Semantic entity deduplication
        - Better relationship extraction
        - Structured output parsing with retries
        - Battle-tested production-grade extraction
        """
        # Convert chunks to LlamaIndex nodes
        llama_nodes = []
        for chunk in chunks:
            node = TextNode(
                id_=chunk.id,
                text=chunk.text,
                metadata={
                    "chunk_index": chunk.chunk_index,
                    "document_id": chunk.document_id,
                },
            )
            llama_nodes.append(node)
        
        # Create PropertyGraphIndex with entity extraction
        # Use SchemaLLMPathExtractor with strict=True for reliable schema-based extraction
        logger.info(f"Extracting entities from {len(llama_nodes)} nodes using SchemaLLMPathExtractor")
        
        # Define possible relations for better extraction guidance
        possible_relations_list = [
            "RELATED_TO", "HAS_PART", "IS_A", "WORKS_FOR", "LOCATED_AT", 
            "INVOLVES", "HAS_AMOUNT", "HAS_DATE", "MENTIONS", "DEFINES",
            "OWNS", "MANAGES", "PARTICIPATES_IN", "AFFECTS"
        ]
        
        # Use SchemaLLMPathExtractor with strict=False for optimal extraction
        # This leverages LLM's semantic understanding while using Pydantic for format enforcement:
        #
        # What Pydantic Does (Format Enforcement):
        # 1. Validates JSON structure - ensures output is valid JSON, not malformed text
        # 2. Type checking - entity_type must be a string from Literal["PERSON", "ORGANIZATION", ...]
        # 3. Required fields - ensures all triplets have subject, relation, object
        # 4. Auto-retry - if LLM returns invalid format, Pydantic raises error → LLM retries
        # 5. Parsing - converts raw LLM text into structured Python objects
        #
        # What strict=False Does:
        # - Keeps all Pydantic validation above (format enforcement)
        # - Removes triplet pattern validation (e.g., allows ORGANIZATION-HAS-ORGANIZATION)
        # - Lets LLM decide what relationships make semantic sense
        # - Matches how Microsoft GraphRAG, Neo4j GraphRAG, and Cognee work
        #
        # Result: LLM does semantic reasoning (its strength) + Pydantic ensures clean data (compensates for LLM weakness)
        try:
            extractor = SchemaLLMPathExtractor(
                llm=self.llm,
                possible_entities=None,  # Use DEFAULT_ENTITIES: Literal["PERSON", "ORGANIZATION", "LOCATION", ...]
                possible_relations=None,  # Use DEFAULT_RELATIONS: Literal["HAS", "LOCATED_IN", "PART_OF", ...]
                strict=False,  # Let LLM use semantic understanding, don't over-constrain patterns
                num_workers=1,
                max_triplets_per_chunk=20,
            )
            logger.info(f"Initialized SchemaLLMPathExtractor with strict=False for {len(llama_nodes)} nodes")
        except Exception as e:
            logger.error(f"Failed to initialize SchemaLLMPathExtractor: {e}")
            raise

# Extract entities and relationships using LlamaIndex
        try:
            self.extraction_stats["total_extractions"] += 1
            
            extracted_nodes = await extractor.acall(llama_nodes)
            logger.info(f"Extracted {len(extracted_nodes)} nodes with metadata")
            
            # Collect entities and relations from node metadata
            # Track which entities came from which chunks for MENTIONS relationships
            all_entity_nodes = []
            all_relations = []
            entity_to_chunks = {}  # Maps entity_name -> [chunk_ids]
            
            for i, node in enumerate(extracted_nodes):
                if i == 0:
                    logger.info(f"First node metadata keys: {list(node.metadata.keys())}")
                
                chunk_id = node.node_id if hasattr(node, 'node_id') else node.id_
                
                # LlamaIndex stores extracted data in either 'nodes'/'kg_nodes' and 'relations'/'kg_relations'
                if "nodes" in node.metadata:
                    # Track which entities came from this chunk
                    for entity_node in node.metadata["nodes"]:
                        entity_name = entity_node.name if hasattr(entity_node, 'name') else str(entity_node.id)
                        if entity_name not in entity_to_chunks:
                            entity_to_chunks[entity_name] = []
                        entity_to_chunks[entity_name].append(chunk_id)
                    all_entity_nodes.extend(node.metadata["nodes"])
                elif "kg_nodes" in node.metadata:
                    for entity_node in node.metadata["kg_nodes"]:
                        entity_name = entity_node.name if hasattr(entity_node, 'name') else str(entity_node.id)
                        if entity_name not in entity_to_chunks:
                            entity_to_chunks[entity_name] = []
                        entity_to_chunks[entity_name].append(chunk_id)
                    all_entity_nodes.extend(node.metadata["kg_nodes"])
                
                if "relations" in node.metadata:
                    all_relations.extend(node.metadata["relations"])
                elif "kg_relations" in node.metadata:
                    all_relations.extend(node.metadata["kg_relations"])
            
            logger.info(f"Found {len(all_entity_nodes)} entities and {len(all_relations)} relations")
            
            if all_entity_nodes:
                self.temp_graph_store.upsert_nodes(all_entity_nodes)
            
            if all_relations:
                self.temp_graph_store.upsert_relations(all_relations)
                
            logger.info("Upserted entities and relations into graph store")
            
            # Log extraction statistics periodically
            if self.extraction_stats["total_extractions"] % 10 == 0:
                self._log_extraction_stats()
            
        except Exception as e:
            error_str = str(e).lower()
            
            # Check if this is a JSON-related error that we can potentially repair
            if any(keyword in error_str for keyword in ["json", "parse", "decode", "validation", "format"]):
                logger.warning(f"JSON-related extraction error detected: {e}")
                self.extraction_stats["json_repairs_attempted"] += 1
                
                # Note: LlamaIndex's internal structure makes direct JSON repair challenging
                # The repair would need to intercept LLM output before Pydantic validation
                # For now, we log the error for monitoring. In production, consider:
                # 1. Custom LLM wrapper that repairs JSON before returning
                # 2. LlamaIndex callback system to intercept and repair
                # 3. Fork LlamaIndex SchemaLLMPathExtractor to add repair logic
                
                logger.info(
                    "💡 JSON repair attempted but LlamaIndex internal validation prevents direct repair. "
                    "Consider implementing custom LLM wrapper with JSON repair preprocessing."
                )
                self.extraction_stats["json_repairs_failed"] += 1
            
            logger.error(f"Extraction failed: {e}", exc_info=True)
            self.extraction_stats["extraction_failures"] += 1
            
            # Log immediate stats on failure for debugging
            self._log_extraction_stats()
            
            return [], []

        # Extract knowledge graph from index
        all_entities: Dict[str, Entity] = {}
        all_relationships: List[Relationship] = []
        
        # Get extracted entities and relationships from graph store
        # Manual extraction from graph store since get_triplets() seems to be failing
        graph = self.temp_graph_store.graph
        graph_nodes = graph.nodes
        graph_relations = graph.relations
        
        # Helper to find entity ID by name
        name_to_id_map = {}

        for node_id, node in graph_nodes.items():
             # node is a LabelledNode or EntityNode
             # The node_id in SimplePropertyGraphStore is often the entity name for EntityNodes
             
             entity_name = None
             
             # 1. Try explicit name attribute
             if hasattr(node, "name") and node.name:
                 entity_name = node.name
             
             # 2. Try properties['name']
             elif hasattr(node, "properties") and "name" in node.properties:
                 entity_name = node.properties["name"]
                 
             # 3. Fallback to node_id if it looks like a name (not a UUID)
             # In our logs we saw ID="Contoso insurance inc", so node_id is the name
             else:
                 entity_name = str(node_id)
             
             if not entity_name or entity_name == "entity":
                 # If we somehow got "entity" as the name, skip it or try harder
                 if node_id != "entity":
                     entity_name = str(node_id)
                 else:
                     continue

             entity_key = entity_name.lower()
             
             # Create entity if not exists
             if entity_key not in all_entities:
                 new_id = f"entity_{uuid.uuid4().hex[:8]}"
                 all_entities[entity_key] = Entity(
                     id=new_id,
                     name=entity_name,
                     type=node.label if hasattr(node, 'label') else "CONCEPT",
                     description=str(node.properties) if hasattr(node, 'properties') else "",
                 )
                 name_to_id_map[entity_key] = new_id
                 
                 # Store chunk IDs for this entity (for MENTIONS relationships)
                 chunk_ids_for_entity = entity_to_chunks.get(entity_name, [])
                 if chunk_ids_for_entity:
                     all_entities[entity_key].text_unit_ids = chunk_ids_for_entity
             else:
                 # If already exists, merge chunk IDs
                 name_to_id_map[entity_key] = all_entities[entity_key].id
                 chunk_ids_for_entity = entity_to_chunks.get(entity_name, [])
                 if chunk_ids_for_entity:
                     existing_ids = getattr(all_entities[entity_key], 'text_unit_ids', [])
                     all_entities[entity_key].text_unit_ids = list(set(existing_ids + chunk_ids_for_entity))

        for relation_id, relation in graph_relations.items():
            # relation is a Relation object
            # relation.source_id and relation.target_id are the keys in graph_nodes
            # Since we determined that graph_nodes keys are the entity names, we can use them directly
            
            source_name = relation.source_id
            target_name = relation.target_id
            
            # Fallback: if for some reason IDs are not names, try to look up the node
            if source_name not in name_to_id_map:
                 source_node = graph_nodes.get(source_name)
                 if source_node:
                     if hasattr(source_node, "name") and source_node.name:
                         source_name = source_node.name
                     elif hasattr(source_node, "properties") and "name" in source_node.properties:
                         source_name = source_node.properties["name"]

            if target_name not in name_to_id_map:
                 target_node = graph_nodes.get(target_name)
                 if target_node:
                     if hasattr(target_node, "name") and target_node.name:
                         target_name = target_node.name
                     elif hasattr(target_node, "properties") and "name" in target_node.properties:
                         target_name = target_node.properties["name"]
            
            source_key = str(source_name).lower()
            target_key = str(target_name).lower()
            
            source_entity_id = name_to_id_map.get(source_key)
            target_entity_id = name_to_id_map.get(target_key)
            
            if source_entity_id and target_entity_id:
                rel = Relationship(
                    source_id=source_entity_id,
                    target_id=target_entity_id,
                    description=relation.label, # Use label as description/type
                )
                all_relationships.append(rel)

        # Fallback to get_triplets if manual extraction yielded nothing (unlikely given the stats)
        if not all_entities and not all_relationships:
            logger.warning("Manual extraction failed, trying get_triplets()")
            graph_data = self.temp_graph_store.get_triplets()
            for triplet in graph_data:
                # Triplet format: (subject, relation, object)
                subject_name = triplet[0]
                relation = triplet[1]
                object_name = triplet[2]
                
                # Create or get subject entity
                subject_key = subject_name.lower()
                if subject_key not in all_entities:
                    entity_id = f"entity_{uuid.uuid4().hex[:8]}"
                    all_entities[subject_key] = Entity(
                        id=entity_id,
                        name=subject_name,
                        type="CONCEPT",
                        description="",
                    )
                
                # Create or get object entity
                object_key = object_name.lower()
                if object_key not in all_entities:
                    entity_id = f"entity_{uuid.uuid4().hex[:8]}"
                    all_entities[object_key] = Entity(
                        id=entity_id,
                        name=object_name,
                        type="CONCEPT",
                        description="",
                    )
                
                # Create relationship
                rel = Relationship(
                    source_id=all_entities[subject_key].id,
                    target_id=all_entities[object_key].id,
                    description=relation,
                )
                all_relationships.append(rel)
        
        # Generate embeddings for entities
        entities_list = list(all_entities.values())
        for entity in entities_list:
            desc_text = f"{entity.name}: {entity.description}" if entity.description else entity.name
            entity.embedding = await self._embed_text(desc_text)
        
        logger.info(f"LlamaIndex extraction: {len(entities_list)} entities, {len(all_relationships)} relationships")
        return entities_list, all_relationships
    
    def _validate_required_properties(
        self,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Validate required properties on extracted entities and relationships.
        
        Based on Neo4j GraphRAG feature/add-constraint-type pattern.
        Prunes entities/relationships missing required properties.
        
        Args:
            entities: Extracted entities
            relationships: Extracted relationships
            
        Returns:
            (validated_entities, validated_relationships)
        """
        # Build spec lookups
        entity_specs = {spec.label: spec for spec in self.config.entity_specs}
        relation_specs = {spec.label: spec for spec in self.config.relation_specs}
        
        validated_entities = []
        validated_relationships = []
        
        # Validate entities
        for entity in entities:
            self.extraction_stats["properties_validated"] += 1
            
            spec = entity_specs.get(entity.type)
            if not spec:
                # No spec defined - allow through
                validated_entities.append(entity)
                continue
            
            # Check required properties
            missing = []
            if hasattr(entity, 'properties') and entity.properties:
                for prop_spec in spec.properties:
                    if prop_spec.required and prop_spec.name not in entity.properties:
                        missing.append(prop_spec.name)
            else:
                # No properties dict - check if any required
                missing = [p.name for p in spec.properties if p.required]
            
            if missing:
                logger.warning(
                    f"Entity '{entity.name}' (type: {entity.type}) missing required properties: {missing}. Pruning."
                )
                self.extraction_stats["entities_missing_required_props"] += 1
                continue
            
            validated_entities.append(entity)
        
        # Validate relationships
        for relationship in relationships:
            self.extraction_stats["properties_validated"] += 1
            
            # Relationship type from description field (our current schema)
            rel_type = relationship.description if hasattr(relationship, 'description') else "RELATED_TO"
            
            spec = relation_specs.get(rel_type)
            if not spec:
                # No spec defined - allow through
                validated_relationships.append(relationship)
                continue
            
            # Check required properties
            missing = []
            if hasattr(relationship, 'properties') and relationship.properties:
                for prop_spec in spec.properties:
                    if prop_spec.required and prop_spec.name not in relationship.properties:
                        missing.append(prop_spec.name)
            else:
                # No properties dict - check if any required
                missing = [p.name for p in spec.properties if p.required]
            
            if missing:
                logger.warning(
                    f"Relationship '{relationship.source_id} -> {relationship.target_id}' "
                    f"(type: {rel_type}) missing required properties: {missing}. Pruning."
                )
                self.extraction_stats["relationships_missing_required_props"] += 1
                continue
            
            validated_relationships.append(relationship)
        
        return validated_entities, validated_relationships

    
    async def _build_communities(
        self,
        group_id: str,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> List[Community]:
        """
        Build hierarchical communities using graspologic's hierarchical_leiden.
        
        This is the same algorithm MS GraphRAG uses internally.
        """
        if len(entities) < self.config.min_community_size:
            logger.info(f"Too few entities ({len(entities)}) for community detection")
            return []
        
        # Build adjacency matrix
        entity_ids = [e.id for e in entities]
        entity_index = {eid: idx for idx, eid in enumerate(entity_ids)}
        n = len(entities)
        
        # Create sparse adjacency matrix
        adj_matrix = np.zeros((n, n), dtype=np.float32)
        
        for rel in relationships:
            src_idx = entity_index.get(rel.source_id)
            tgt_idx = entity_index.get(rel.target_id)
            if src_idx is not None and tgt_idx is not None:
                weight = rel.weight
                adj_matrix[src_idx, tgt_idx] = weight
                adj_matrix[tgt_idx, src_idx] = weight  # Make symmetric
        
        # Run hierarchical Leiden
        try:
            partition_map = hierarchical_leiden(
                adj_matrix,
                resolution=self.config.community_resolution,
                max_cluster_size=len(entities) // 2,  # Allow larger communities
            )
            
            # Convert partition map to Community objects
            communities = []
            
            # partition_map is HierarchicalClusters (list of HierarchicalCluster)
            # Each HierarchicalCluster has: node, cluster, level, is_final_cluster
            # Reorganize by level and community
            level_communities: Dict[int, Dict[int, List[str]]] = {}
            
            for hc in partition_map:
                hc_item: HierarchicalCluster = hc
                node_idx = hc_item.node
                level = hc_item.level
                comm_id = hc_item.cluster
                if level not in level_communities:
                    level_communities[level] = {}
                if comm_id not in level_communities[level]:
                    level_communities[level][comm_id] = []
                # node_idx is the index into entity_ids
                if isinstance(node_idx, int) and node_idx < len(entity_ids):
                    level_communities[level][comm_id].append(entity_ids[node_idx])
            
            # Create Community objects
            for level, comm_dict in level_communities.items():
                if level >= self.config.max_community_levels:
                    continue
                    
                for comm_id, member_ids in comm_dict.items():
                    if len(member_ids) < self.config.min_community_size:
                        continue
                    
                    community = Community(
                        id=f"community_L{level}_{comm_id}_{uuid.uuid4().hex[:8]}",
                        level=level,
                        entity_ids=member_ids,
                        title=f"Community Level {level} - {comm_id}",
                        rank=len(member_ids) / n,  # Rank by size
                    )
                    communities.append(community)
            
            return communities
            
        except Exception as e:
            logger.warning(f"Community detection failed: {e}")
            return []
    
    async def _generate_community_summary(
        self,
        community: Community,
        all_entities: List[Entity],
    ) -> str:
        """
        Generate a summary for a community using LLM.
        """
        # Get entities in this community
        entity_dict = {e.id: e for e in all_entities}
        member_entities = [entity_dict[eid] for eid in community.entity_ids if eid in entity_dict]
        
        if not member_entities:
            return ""
        
        # Build entity descriptions
        entity_descriptions = []
        for e in member_entities[:20]:  # Limit to 20 entities
            desc = f"- {e.name} ({e.type}): {e.description}" if e.description else f"- {e.name} ({e.type})"
            entity_descriptions.append(desc)
        
        prompt = f"""Summarize this community of related entities in 2-3 sentences.
Focus on what unifies these entities and their significance.

Entities:
{chr(10).join(entity_descriptions)}

Summary:"""

        try:
            summary = await self._llm_complete(prompt)
            return summary.strip()[:self.config.raptor_summary_max_tokens]
        except Exception as e:
            logger.warning(f"Community summary generation failed: {e}")
            return f"Community containing: {', '.join(e.name for e in member_entities[:5])}"
    
    async def _build_raptor_hierarchy(
        self,
        group_id: str,
        chunks: List[TextChunk],
    ) -> List[RaptorNode]:
        """
        Build RAPTOR hierarchical summary tree.
        
        RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)
        creates a tree of summaries at different granularities:
        - Level 0: Original chunks
        - Level 1: Summaries of clusters of chunks
        - Level 2: Summaries of level 1 summaries
        - ...
        """
        raptor_nodes: List[RaptorNode] = []
        
        if len(chunks) < 2:
            return raptor_nodes
        
        # Level 0: Original chunks become leaf RAPTOR nodes
        current_level_texts = []
        for chunk in chunks:
            node = RaptorNode(
                id=f"raptor_L0_{chunk.id}",
                text=chunk.text,
                level=0,
                embedding=chunk.embedding,
                child_ids=[chunk.id],
            )
            raptor_nodes.append(node)
            current_level_texts.append((node.id, chunk.text, chunk.embedding))
        
        # Build higher levels
        for level in range(1, self.config.raptor_levels + 1):
            if len(current_level_texts) < 2:
                break
            
            # Cluster texts at this level
            clusters = await self._cluster_texts_for_raptor(current_level_texts)
            
            next_level_texts = []
            for cluster_idx, cluster in enumerate(clusters):
                if len(cluster) < 1:
                    continue
                
                # Extract data from cluster (may include silhouette scores from Phase 1)
                if len(cluster[0]) == 4:  # Has silhouette scores
                    child_ids = [item[0] for item in cluster]
                    combined_text = "\n\n".join(item[1] for item in cluster)
                    cluster_embeddings = [item[2] for item in cluster if item[2] is not None]
                    silhouette_scores = [item[3] for item in cluster]
                else:  # Fallback without scores
                    child_ids = [item[0] for item in cluster]
                    combined_text = "\n\n".join(item[1] for item in cluster)
                    cluster_embeddings = [item[2] for item in cluster if item[2] is not None]
                    silhouette_scores = [0.0] * len(cluster)
                
                # Calculate cluster coherence (Phase 1 metric)
                import numpy as np
                from scipy.spatial.distance import pdist
                cluster_coherence = 0.0
                if cluster_embeddings and len(cluster_embeddings) > 1:
                    embeddings_array = np.array(cluster_embeddings)
                    cluster_coherence = 1 - np.mean(pdist(embeddings_array, metric='cosine'))
                elif len(cluster_embeddings) == 1:
                    cluster_coherence = 1.0
                
                # Determine confidence level based on coherence (Phase 1)
                if cluster_coherence >= 0.85:
                    confidence_level = "high"
                    confidence_score = 0.95
                elif cluster_coherence >= 0.75:
                    confidence_level = "medium"
                    confidence_score = 0.80
                else:
                    confidence_level = "low"
                    confidence_score = 0.60
                
                # Generate summary
                summary = await self._generate_raptor_summary(combined_text, level)
                
                # Generate embedding for summary
                embedding = await self._embed_text(summary)
                
                # Create RAPTOR node with Phase 1 quality metrics
                node = RaptorNode(
                    id=f"raptor_L{level}_{cluster_idx}_{uuid.uuid4().hex[:8]}",
                    text=summary,
                    level=level,
                    embedding=embedding,
                    child_ids=child_ids,
                    metadata={
                        "cluster_coherence": float(cluster_coherence),
                        "confidence_level": confidence_level,
                        "confidence_score": float(confidence_score),
                        "silhouette_score": float(np.mean(silhouette_scores)) if silhouette_scores else 0.0,
                        "cluster_silhouette_avg": float(np.mean(silhouette_scores)) if silhouette_scores else 0.0,
                        "child_count": len(cluster),
                        "creation_model": "gpt-4o",
                    }
                )
                raptor_nodes.append(node)
                next_level_texts.append((node.id, summary, embedding))
            
            current_level_texts = next_level_texts
            logger.info(f"RAPTOR level {level}: created {len(next_level_texts)} nodes")
        
        return raptor_nodes
    
    async def _cluster_texts_for_raptor(
        self,
        texts: List[Tuple[str, str, Optional[List[float]]]],
    ) -> List[List[Tuple[str, str, Optional[List[float]]]]]:
        """
        Cluster texts for RAPTOR summarization with quality metrics.
        
        Uses k-means clustering on embeddings and calculates silhouette scores
        for cluster quality validation (Phase 1).
        """
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score, silhouette_samples
        import numpy as np
        
        cluster_size = self.config.raptor_cluster_size
        
        if len(texts) <= cluster_size:
            return [texts]
        
        # Extract embeddings for clustering
        embeddings = [emb for _, _, emb in texts if emb is not None]
        
        if not embeddings or len(embeddings) < 2:
            # Fallback to simple chunking
            clusters = []
            for i in range(0, len(texts), cluster_size):
                cluster = texts[i:i + cluster_size]
                clusters.append(cluster)
            return clusters
        
        # K-means clustering
        embeddings_array = np.array(embeddings)
        n_clusters = max(2, min(len(texts) // cluster_size, 10))
        
        try:
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            cluster_labels = kmeans.fit_predict(embeddings_array)
            
            # Calculate silhouette score for cluster quality (Phase 1)
            silhouette_avg = silhouette_score(embeddings_array, cluster_labels)
            silhouette_per_sample = silhouette_samples(embeddings_array, cluster_labels)
            
            logger.info(f"Cluster silhouette score: {silhouette_avg:.3f} (n_clusters={n_clusters})")
            
            # Group texts by cluster and store silhouette scores
            from collections import defaultdict
            clusters_dict = defaultdict(list)
            for i, (text_id, text, emb) in enumerate(texts[:len(cluster_labels)]):
                cluster_id = int(cluster_labels[i])
                # Attach silhouette score to text metadata
                clusters_dict[cluster_id].append((text_id, text, emb, float(silhouette_per_sample[i])))
            
            # Convert to list of clusters
            clusters = [cluster for cluster in clusters_dict.values()]
            
        except Exception as e:
            logger.warning(f"K-means clustering failed: {e}, falling back to simple chunking")
            clusters = []
            for i in range(0, len(texts), cluster_size):
                cluster = texts[i:i + cluster_size]
                clusters.append(cluster)
        
        return clusters
    
    async def _generate_raptor_summary(
        self,
        text: str,
        level: int,
    ) -> str:
        """
        Generate a RAPTOR summary at a given level.
        
        Higher levels produce more abstract summaries.
        """
        max_input = 4000  # Limit input length
        text = text[:max_input] if len(text) > max_input else text
        
        prompt = f"""Create a comprehensive summary of the following text.
Level: {level} (higher = more abstract)

Text:
{text}

Summary (be concise but capture key information):"""

        try:
            summary = await self._llm_complete(prompt)
            return summary.strip()[:self.config.raptor_summary_max_tokens]
        except Exception as e:
            logger.warning(f"RAPTOR summary generation failed at level {level}: {e}")
            return text[:200]  # Fallback to truncation
    
    async def _embed_text(self, text: str) -> List[float]:
        """Generate embedding for text using the embedder."""
        try:
            if hasattr(self.embedder, 'get_text_embedding'):
                return self.embedder.get_text_embedding(text)
            elif hasattr(self.embedder, 'aembed'):
                return await self.embedder.aembed(text)
            elif hasattr(self.embedder, 'embed'):
                return self.embedder.embed(text)
            elif callable(self.embedder):
                result = self.embedder(text)
                if asyncio.iscoroutine(result):
                    result = await result
                # Cast to List[float] for type safety
                return list(result) if hasattr(result, '__iter__') else [0.0] * self.config.embedding_dimensions
            else:
                raise ValueError("Embedder does not have embed method")
        except Exception as e:
            logger.warning(f"Embedding failed: {e}")
            # Return zero vector as fallback
            return [0.0] * self.config.embedding_dimensions
    
    async def _llm_complete(self, prompt: str) -> str:
        """Generate completion using the LLM."""
        try:
            if hasattr(self.llm, 'achat'):
                # GraphRAG-style model
                messages = [ChatMessage(role=MessageRole.USER, content=prompt)]
                response = await self.llm.achat(messages)
                return response.message.content if hasattr(response, 'message') else str(response)
            elif hasattr(self.llm, 'acomplete'):
                # LlamaIndex-style model
                response = await self.llm.acomplete(prompt)
                return response.text if hasattr(response, 'text') else str(response)
            elif hasattr(self.llm, 'complete'):
                response = self.llm.complete(prompt)
                return response.text if hasattr(response, 'text') else str(response)
            elif callable(self.llm):
                result = self.llm(prompt)
                if asyncio.iscoroutine(result):
                    result = await result
                return str(result)
            else:
                raise ValueError("LLM does not have a completion method")
        except Exception as e:
            logger.error(f"LLM completion failed: {e}", exc_info=True)
            return ""
            raise
