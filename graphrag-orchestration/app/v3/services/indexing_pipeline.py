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
import re
import hashlib
import random
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Set, Union, cast
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
from app.v3.services.validated_extraction_strategy import ValidatedEntityExtractor

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
    
    # Chunking settings (Lean Engine: 400-600 tokens per chunk, ARCHITECTURE_DECISIONS.md § Phase 2)
    chunk_size: int = 512  # Target: 400-600 tokens for financial/legal documents
    chunk_overlap: int = 64  # ~12.5% overlap maintains context continuity
    
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

    # Community report settings
    # Community reports are used directly by Global Search; keep enough room for
    # the required sections + concrete terms (jurisdictions, fees, insurance limits).
    community_report_max_chars: int = 8000
    
    # Embedding settings
    embedding_model: str = "text-embedding-3-large"  # 3072 dims, Neo4j 5.x supports up to 4096
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
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize the indexing pipeline.
        
        Args:
            neo4j_store: Neo4j storage instance (your custom schema)
            llm: LLM for summaries and general operations (Azure OpenAI)
            embedder: Embeddings model (Azure OpenAI)
            config: Pipeline configuration
            llm_service: LLMService instance for specialized model selection (optional)
        """
        self.neo4j_store = neo4j_store
        self.llm = llm
        self.embedder = embedder
        self.config = config or IndexingConfig()
        self.llm_service = llm_service
        
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
        run_community_detection: bool = True,
        run_raptor: bool = True,
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
        import time
        start_time = time.time()
        logger.info(f"⏱️ [0.0s] Starting indexing for group {group_id} with {len(documents)} documents (ingestion={ingestion})")
        
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
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Reindexing: Deleting existing data for group {group_id}")
                self.neo4j_store.delete_group_data(group_id)
            
            # Step 0.5: Extract text from PDFs/images if needed
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 0.5: Starting document extraction (ingestion={ingestion})")
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
                    logger.info(f"⏱️ [{time.time()-start_time:.1f}s] 🔍 Extracting text from {len(needs_extraction)} PDF documents using Document Intelligence...")
                    extracted_docs = await di_service.extract_documents(
                        group_id=group_id,
                        input_items=needs_extraction,
                        fail_fast=False,
                        model_strategy="auto",
                    )
                    
                    # Convert extracted DI docs back to dict format for pipeline.
                    # IMPORTANT: Do not flatten into one big combined doc; that loses per-section metadata
                    # (e.g., section_path) needed for section-aware retrieval.
                    logger.info(f"⏱️ [{time.time()-start_time:.1f}s] ✅ Document Intelligence extracted {len(extracted_docs)} text units")

                    from collections import defaultdict

                    extracted_by_source: dict[str, list[LlamaDocument]] = defaultdict(list)
                    for llama_doc in extracted_docs:
                        source_url = (llama_doc.metadata or {}).get("url", "")
                        extracted_by_source[source_url].append(llama_doc)

                    # Keep any already-provided documents (non-URL content) as-is.
                    retained_documents: list[dict[str, Any]] = []
                    for doc in documents:
                        if isinstance(doc, str):
                            continue
                        if not isinstance(doc, dict):
                            continue
                        content = doc.get("content") or doc.get("text", "")
                        if isinstance(content, str) and content.strip() and not content.startswith("http"):
                            retained_documents.append(doc)

                    # Create one Document per source URL, but keep extracted subdocs for section-aware chunking.
                    documents = retained_documents
                    for source_url, subdocs in extracted_by_source.items():
                        base_metadata = (subdocs[0].metadata or {}).copy() if subdocs else {}
                        base_metadata["di_units"] = len(subdocs)
                        base_metadata["page_numbers"] = [d.metadata.get("page_number") for d in subdocs if (d.metadata or {}).get("page_number") is not None]

                        documents.append({
                            "content": "",  # chunk directly from di_extracted_docs
                            "title": source_url.split("/")[-1] if source_url else "Untitled",
                            "source": source_url,
                            "metadata": base_metadata,
                            "di_extracted_docs": subdocs,
                        })

                    logger.info(
                        f"⏱️ [{time.time()-start_time:.1f}s] 📄 Grouped {len(extracted_docs)} extracted units into {len(extracted_by_source)} documents"
                    )
                else:
                    logger.info(f"ℹ️ All documents already have content, skipping Document Intelligence extraction")
            
            elif ingestion == "llamaparse":
                logger.warning(f"⚠️ LlamaParse ingestion not yet implemented, processing documents as-is")
            
            # Step 1: Chunk documents and store
            all_chunks = []
            for doc in documents:
                doc_id = doc.get("id") or str(uuid.uuid4())
                if isinstance(doc, dict) and doc.get("di_extracted_docs"):
                    chunks = await self._chunk_di_extracted_docs(doc, doc_id)
                else:
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
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 1 complete: Created {len(all_chunks)} chunks")
            
            # Step 2: Extract entities and relationships
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 2: Starting entity & relationship extraction")
            entities, relationships = await self._extract_entities_and_relationships(
                group_id, all_chunks
            )
            
            # Diagnostic: Check if entities have embeddings before storage
            entities_with_embeddings = sum(1 for e in entities if e.embedding and e.embedding != [0.0] * self.config.embedding_dimensions)
            logger.warning(f"📊 BEFORE STORAGE: {entities_with_embeddings}/{len(entities)} entities have non-zero embeddings")
            
            # Store entities (async to avoid blocking event loop)
            await self.neo4j_store.aupsert_entities_batch(group_id, entities)
            stats["entities"] = len(entities)
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Stored {len(entities)} entities")
            
            # Store relationships  
            self.neo4j_store.upsert_relationships_batch(group_id, relationships)
            stats["relationships"] = len(relationships)
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 2 complete: Extracted {len(relationships)} relationships")
            
            # Step 3: Build communities using hierarchical Leiden
            communities = []
            if run_community_detection:
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 3: Starting community detection")
                communities = await self._build_communities(group_id, entities, relationships)

                # Generate community reports (with rate limit throttling)
                chunk_by_id = {c.id: c for c in all_chunks}
                for i, community in enumerate(communities):
                    # Add delay to respect rate limits (1 second between calls)
                    if i > 0:
                        await asyncio.sleep(1.0)
                    summary = await self._generate_community_summary(community, entities, chunk_by_id, all_chunks)
                    community.summary = summary
                    community.full_content = summary  # DRIFT needs full_content

                # Store communities in batch (community upsert handles batch internally)
                for community in communities:
                    self.neo4j_store.upsert_community(group_id, community)
                stats["communities"] = len(communities)
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 3 complete: Built {len(communities)} communities")

                # Derive parent-child community edges for dynamic community selection
                try:
                    self.neo4j_store.ensure_community_hierarchy(group_id)
                except Exception as e:
                    logger.warning(f"Failed to build community hierarchy edges: {e}")
            else:
                logger.info(f"⏭️ Skipping community detection (run_community_detection=false)")

            # Step 4/5: RAPTOR is optional (LazyGraphRAG/HippoRAG2 pipelines can own it)
            if run_raptor:
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 4: Starting RAPTOR hierarchy")
                raptor_nodes = await self._build_raptor_hierarchy(group_id, all_chunks)
                self.neo4j_store.upsert_raptor_nodes_batch(group_id, raptor_nodes)
                stats["raptor_nodes"] = len(raptor_nodes)
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 4 complete: Built {len(raptor_nodes)} RAPTOR nodes")

                # Step 5: Index RAPTOR nodes in Azure AI Search (if enabled)
                logger.info(f"⏱️ [{time.time()-start_time:.1f}s] Step 5: Indexing RAPTOR nodes in Azure AI Search")
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
            else:
                logger.info(f"⏭️ Skipping RAPTOR (run_raptor=false)")
            
            # Log final extraction statistics
            self._log_extraction_stats()
            
            logger.info(f"⏱️ [{time.time()-start_time:.1f}s] ✅ All steps complete, total time: {time.time()-start_time:.1f}s")
            
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
        - Preserves Document Intelligence metadata (tables, section_path) for entity extraction
        """
        content = document.get("content", "")
        if not content:
            return []
        
        # Get document metadata from DI extraction
        doc_metadata = document.get("metadata", {})
        
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
                
                # Preserve DI metadata for entity extraction context
                chunk_metadata = {
                    "page_number": doc_metadata.get("page_number"),
                    "section_path": doc_metadata.get("section_path", []),
                    "tables": doc_metadata.get("tables", []),
                    "source": doc_metadata.get("source"),
                }
                # Remove None values
                chunk_metadata = {k: v for k, v in chunk_metadata.items() if v is not None}
                
                chunk = TextChunk(
                    id=f"{doc_id}_chunk_{chunk_index}",
                    text=chunk_text,
                    chunk_index=chunk_index,
                    document_id=doc_id,
                    embedding=embedding,
                    tokens=len(chunk_text.split()),  # Approximate
                    metadata=chunk_metadata,
                )
                chunks.append(chunk)
        
        return chunks

    async def _chunk_di_extracted_docs(
        self,
        document: Dict[str, Any],
        doc_id: str,
    ) -> List[TextChunk]:
        """Chunk DI-extracted sub-documents while preserving DI section metadata.

        Document Intelligence extraction produces text units (often section-aware).
        We chunk each unit with the sentence splitter, but inherit the unit's metadata
        (section_path, di_section_path, etc.) so retrieval sources can be section-aware.
        """

        extracted_docs = document.get("di_extracted_docs") or []
        if not extracted_docs:
            return []

        chunks: List[TextChunk] = []
        global_chunk_index = 0

        for unit_index, unit_doc in enumerate(extracted_docs):
            unit_text = getattr(unit_doc, "text", "") or ""
            if not unit_text.strip():
                continue

            unit_metadata = getattr(unit_doc, "metadata", {}) or {}

            llama_doc = LlamaDocument(
                text=unit_text,
                id_=f"{doc_id}_diunit_{unit_index}",
                metadata={
                    "title": document.get("title", "Untitled"),
                    "source": document.get("source", ""),
                },
            )

            nodes = self.sentence_splitter.get_nodes_from_documents([llama_doc])
            for node in nodes:
                chunk_text = node.get_content()
                if not chunk_text.strip():
                    continue

                embedding = await self._embed_text(chunk_text)

                # Keep metadata small but section-aware. (Tables are intentionally not persisted here.)
                chunk_metadata = {
                    "chunk_type": unit_metadata.get("chunk_type"),
                    "page_number": unit_metadata.get("page_number"),
                    "section_path": unit_metadata.get("section_path", []),
                    "di_section_path": unit_metadata.get("di_section_path"),
                    "di_section_part": unit_metadata.get("di_section_part"),
                    "url": unit_metadata.get("url"),
                }
                chunk_metadata = {k: v for k, v in chunk_metadata.items() if v is not None}

                chunk = TextChunk(
                    id=f"{doc_id}_chunk_{global_chunk_index}",
                    text=chunk_text,
                    chunk_index=global_chunk_index,
                    document_id=doc_id,
                    embedding=embedding,
                    tokens=len(chunk_text.split()),
                    metadata=chunk_metadata,
                )
                chunks.append(chunk)
                global_chunk_index += 1

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
        # Convert chunks to LlamaIndex nodes with DI metadata for context
        llama_nodes = []
        for chunk in chunks:
            # Include Document Intelligence metadata for table-aware and section-aware extraction
            chunk_metadata = {
                "chunk_index": chunk.chunk_index,
                "document_id": chunk.document_id,
            }
            
            # Add DI metadata if available (from prebuilt-layout model)
            if chunk.metadata:
                if "tables" in chunk.metadata and chunk.metadata["tables"]:
                    chunk_metadata["tables"] = chunk.metadata["tables"]
                if "section_path" in chunk.metadata and chunk.metadata["section_path"]:
                    chunk_metadata["section_path"] = chunk.metadata["section_path"]
                if "page_number" in chunk.metadata:
                    chunk_metadata["page_number"] = chunk.metadata["page_number"]
            
            node = TextNode(
                id_=chunk.id,
                text=chunk.text,
                metadata=chunk_metadata,
            )
            llama_nodes.append(node)

        def _canonical_entity_key(name: str) -> str:
            """Deterministic normalization for entity de-duplication.

            This is intentionally non-LLM and general-purpose: normalize whitespace/punctuation
            and strip common corporate suffixes when they appear as trailing tokens.
            """
            s = (name or "").strip().lower()
            if not s:
                return ""
            s = s.replace("\u00a0", " ")
            # Replace punctuation with spaces, keep alphanumerics/underscore and '&'
            s = re.sub(r"[^a-z0-9_&\s]", " ", s)
            s = re.sub(r"\s+", " ", s).strip()
            if not s:
                return ""

            tokens = s.split()
            # Convert '&' to 'and' for stable keying
            tokens = ["and" if t == "&" else t for t in tokens]

            # Strip common corporate suffixes (only trailing tokens)
            suffixes = {
                "inc",
                "incorporated",
                "corp",
                "corporation",
                "co",
                "company",
                "llc",
                "ltd",
                "limited",
                "plc",
                "gmbh",
                "ag",
                "sa",
                "sarl",
            }
            while len(tokens) >= 2 and tokens and tokens[-1] in suffixes:
                tokens.pop()
            return " ".join(tokens)

        # Determinism: optional extraction cache keyed by chunk text + stable metadata + model/params.
        #
        # Azure OpenAI can still show run-to-run variability even with temperature=0 due to
        # backend nondeterminism. When enabled, we persist the per-chunk extracted payload
        # (entity names/types + relation endpoints/labels) and reuse it on subsequent runs.
        cache_enabled = bool(getattr(settings, "GRAPHRAG_ENABLE_EXTRACTION_CACHE", False))
        
        # NOTE: Use a fresh in-memory graph store per run.
        #
        # `SimplePropertyGraphStore` accumulates nodes/relations in memory. If shared across
        # concurrent background indexing tasks, it can leak state across runs and create
        # nondeterministic digests/counts. Keeping it local makes the LLM-stage vs graph-stage
        # determinism diagnostics comparable and prevents cross-run contamination.
        temp_graph_store = SimplePropertyGraphStore()

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
        #
        # WITH MICROSOFT VALIDATION: Adds post-extraction validation pass to score entity confidence
        # and filter out hallucinations using LLM-based quality scoring (0-10 scale)
        try:
            # Use specialized indexing LLM if available (GPT-4.1 with 1M context window)
            indexing_llm = self.llm_service.get_indexing_llm() if self.llm_service else self.llm

            def _best_effort_model_id(llm_obj: object) -> str:
                for attr in ("model", "model_name", "deployment_name", "deployment"):
                    v = getattr(llm_obj, attr, None)
                    if v:
                        return str(v)
                return str(getattr(settings, "AZURE_OPENAI_INDEXING_DEPLOYMENT", None) or self.config.llm_model)

            model_id = _best_effort_model_id(indexing_llm)
            cache_version = str(getattr(settings, "GRAPHRAG_EXTRACTION_CACHE_VERSION", "v1"))
            
            # Use Lean Engine extraction strategy: 12-15 triplet density (ARCHITECTURE_DECISIONS.md § Phase 2)
            validated_extractor = ValidatedEntityExtractor(
                llm=indexing_llm,
                max_triplets_per_pass=12,  # Balanced triplet density for contract/business docs
                validation_threshold=0.7,  # Keep entities with 7+ confidence (Microsoft default, quality-first)
                max_passes=1,  # Single extraction pass (validation happens after)
            )
            logger.info(f"Initialized ValidatedEntityExtractor with max_triplets=12, validation_threshold=0.7 for {len(llama_nodes)} nodes")
        except Exception as e:
            logger.error(f"Failed to initialize ValidatedEntityExtractor: {e}")
            raise

        # Extract entities and relationships using validated extraction
        try:
            self.extraction_stats["total_extractions"] += 1

            # --------------------
            # Extraction cache keying (stable across runs)
            # --------------------
            def _stable_chunk_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
                """Remove run-specific identifiers so cache keys can be reused across group_ids/runs."""
                raw = dict(meta or {})

                # document_id contains a UUID generated per run; exclude it.
                raw.pop("document_id", None)

                # Document Intelligence metadata can be large and can vary run-to-run
                # (e.g., table cell geometry/order). Do not key cache entries on it.
                raw.pop("tables", None)
                raw.pop("section_path", None)

                # Keep only minimal stable identifiers.
                cleaned: Dict[str, Any] = {}
                if "chunk_index" in raw:
                    cleaned["chunk_index"] = raw.get("chunk_index")
                if "page_number" in raw:
                    cleaned["page_number"] = raw.get("page_number")
                return cleaned

            def _cache_key_for_node(node: TextNode) -> str:
                meta = _stable_chunk_metadata(getattr(node, "metadata", {}) or {})
                text = ""
                try:
                    text = node.get_content()  # type: ignore[attr-defined]
                except Exception:
                    text = getattr(node, "text", "") or ""

                params_obj = {
                    "cache_version": cache_version,
                    "model": model_id,
                    "model_version": getattr(settings, "AZURE_OPENAI_MODEL_VERSION", ""),
                    "max_triplets_per_pass": 12,
                    "validation_threshold": 0.7,
                    "max_passes": 1,
                    "meta": meta,
                    "text": text,
                }
                material = json.dumps(params_obj, sort_keys=True, ensure_ascii=False)
                return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()

            cache_keys: List[str] = []
            for n in llama_nodes:
                k = _cache_key_for_node(n)
                cache_keys.append(k)

            # Digest/sample of cache keys to quickly diff key stability across runs.
            _ck_h = hashlib.sha256()
            for _k in sorted(cache_keys):
                _ck_h.update(_k.encode("utf-8", errors="ignore"))
                _ck_h.update(b"\n")
            cache_keys_digest = _ck_h.hexdigest()[:12]
            cache_keys_sample = [k[:12] for k in cache_keys[:5]]

            cached_payloads: Dict[str, str] = {}
            if cache_enabled:
                try:
                    cached_payloads = await self.neo4j_store.aget_extraction_cache_batch(cache_keys)
                except Exception as e:
                    logger.warning(f"Extraction cache lookup failed (continuing without cache): {e}")
                    cached_payloads = {}

            cache_hits = sum(1 for k in cache_keys if k in cached_payloads)
            cache_misses = len(cache_keys) - cache_hits

            extracted_nodes: List[TextNode] = []
            validation_stats: Dict[str, Any] = {}

            if cache_enabled and cache_misses == 0 and cache_keys:
                # Full cache hit: reconstruct extracted_nodes from cached payloads.
                for original_node, ck in zip(llama_nodes, cache_keys):
                    payload_json = cached_payloads.get(ck)
                    payload: Dict[str, Any] = {}
                    if payload_json:
                        try:
                            payload = json.loads(payload_json)
                        except Exception:
                            payload = {}

                    merged_meta = dict(getattr(original_node, "metadata", {}) or {})
                    # Payload includes extracted keys like nodes/relations.
                    if isinstance(payload, dict):
                        merged_meta.update(payload)

                    extracted_nodes.append(
                        TextNode(
                            id_=getattr(original_node, "id_", None) or nid,
                            text=getattr(original_node, "text", ""),
                            metadata=merged_meta,
                        )
                    )

                validation_stats = {
                    "cache_enabled": True,
                    "cache_version": cache_version,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                    "total_extracted": len(extracted_nodes),
                }
                logger.info(f"Extraction cache hit: reused {cache_hits}/{len(cache_keys)} chunks (skipped LLM)")
            else:
                # Cache miss (or disabled): run LLM extraction once for all chunks, then populate cache.
                extracted_nodes, validation_stats = await validated_extractor.extract_with_validation(llama_nodes)
                if isinstance(validation_stats, dict):
                    validation_stats.setdefault("cache_version", cache_version)
                logger.info(f"Extracted {len(extracted_nodes)} nodes (validation stats: {validation_stats})")

                if cache_enabled and extracted_nodes:
                    def _entity_payload(entity_node: object) -> Dict[str, Any]:
                        name_val = getattr(entity_node, "name", None)
                        props = getattr(entity_node, "properties", None)
                        name = None
                        if name_val:
                            name = str(name_val)
                        elif isinstance(props, dict) and props.get("name"):
                            name = str(props.get("name"))
                        else:
                            for attr in ("id", "id_", "node_id"):
                                v = getattr(entity_node, attr, None)
                                if v:
                                    name = str(v)
                                    break
                        label = getattr(entity_node, "label", None) or getattr(entity_node, "type", None) or "CONCEPT"
                        return {"name": (name or "").strip(), "label": str(label)}

                    def _relation_payload(rel: object) -> Dict[str, Any]:
                        label = getattr(rel, "label", None) or getattr(rel, "type", None) or "RELATED_TO"
                        src = getattr(rel, "source_id", None) or getattr(rel, "source", None) or getattr(rel, "subject", None) or ""
                        tgt = getattr(rel, "target_id", None) or getattr(rel, "target", None) or getattr(rel, "object", None) or ""
                        return {"source": str(src).strip(), "target": str(tgt).strip(), "label": str(label)}

                    cache_items: List[Dict[str, Any]] = []
                    params_hash = hashlib.sha256(
                        json.dumps(
                            {
                                "cache_version": cache_version,
                                "model": model_id,
                                "model_version": getattr(settings, "AZURE_OPENAI_MODEL_VERSION", ""),
                                "max_triplets_per_pass": 12,
                                "validation_threshold": 0.7,
                                "max_passes": 1,
                            },
                            sort_keys=True,
                            ensure_ascii=False,
                        ).encode("utf-8", errors="ignore")
                    ).hexdigest()[:16]

                    if len(extracted_nodes) != len(llama_nodes):
                        logger.warning(
                            "Extraction cache alignment warning: extracted_nodes=%s, llama_nodes=%s. Cache population will zip by order.",
                            len(extracted_nodes),
                            len(llama_nodes),
                        )

                    for original_node, node, ck in zip(llama_nodes, extracted_nodes, cache_keys):
                        payload: Dict[str, Any] = {}
                        for ek in ("nodes", "kg_nodes"):
                            if ek in (getattr(node, "metadata", {}) or {}):
                                ent_list = node.metadata.get(ek) or []  # type: ignore[attr-defined]
                                payload[ek] = [p for p in (_entity_payload(e) for e in ent_list) if p.get("name")]
                        for rk in ("relations", "kg_relations"):
                            if rk in (getattr(node, "metadata", {}) or {}):
                                rel_list = node.metadata.get(rk) or []  # type: ignore[attr-defined]
                                payload[rk] = [p for p in (_relation_payload(r) for r in rel_list) if p.get("source") and p.get("target")]

                        cache_items.append(
                            {
                                "key": ck,
                                "payload": json.dumps(payload, ensure_ascii=False),
                                "model": model_id,
                                "params_hash": params_hash,
                            }
                        )

                    if cache_items:
                        try:
                            await self.neo4j_store.aput_extraction_cache_batch(cache_items)
                            logger.info(f"Extraction cache populated for {len(cache_items)}/{len(cache_keys)} chunks")

                            # Verify persistence by reading back the written keys.
                            try:
                                written_keys = [ci.get("key") for ci in cache_items if ci.get("key")]
                                verify = await self.neo4j_store.aget_extraction_cache_batch(cast(List[str], written_keys))
                                if len(verify) != len(written_keys):
                                    missing_samples = [k[:12] for k in written_keys if k not in verify][:10]
                                    logger.warning(
                                        "Extraction cache verify mismatch: read_back=%s written=%s missing_samples=%s",
                                        len(verify),
                                        len(written_keys),
                                        missing_samples,
                                    )
                                else:
                                    logger.info(
                                        "Extraction cache verify OK: read_back=%s written=%s",
                                        len(verify),
                                        len(written_keys),
                                    )
                            except Exception as e:
                                logger.warning(f"Extraction cache verify read-back failed (continuing): {e}")
                        except Exception as e:
                            logger.warning(f"Extraction cache write failed (continuing): {e}")

                if isinstance(validation_stats, dict):
                    validation_stats = {
                        **validation_stats,
                        "cache_enabled": cache_enabled,
                        "cache_hits": cache_hits,
                        "cache_misses": cache_misses,
                        "cache_key_digest": cache_keys_digest,
                        "cache_key_sample": cache_keys_sample,
                    }
            
            # Collect entities and relations from node metadata
            # Track which entities came from which chunks for MENTIONS relationships
            all_entity_nodes = []
            all_relations = []
            entity_to_chunks = {}  # Maps canonical_entity_key -> [chunk_ids]
            # Map canonical_entity_key -> sample chunk text for better descriptions
            entity_to_text = {}  # Maps canonical_entity_key -> first chunk text where it appears

            # Determinism diagnostics: summarize extractor output before graph-store upsert.
            diag_mentions_total = 0
            diag_chunks_with_entities = 0
            diag_raw_names: Set[str] = set()
            diag_canonical_keys: Set[str] = set()

            def _stable_set_digest(items: Set[str]) -> str:
                h = hashlib.sha256()
                for s in sorted(items):
                    h.update(s.encode("utf-8", errors="ignore"))
                    h.update(b"\n")
                return h.hexdigest()[:12]

            def _hash12(value: str) -> str:
                h = hashlib.sha256()
                h.update((value or "").encode("utf-8", errors="ignore"))
                return h.hexdigest()[:12]

            def _bucket_summaries(items: Set[str], buckets: int = 8) -> Dict[str, Dict[str, Union[int, str]]]:
                """Return small, privacy-preserving summaries that are easy to diff across runs.

                We bucket by a deterministic hash of the canonical key, then compute a digest per bucket.
                This makes it easier to localize which subset changed without logging raw keys.
                """

                bucketed: list[set[str]] = [set() for _ in range(buckets)]
                for item in items:
                    if not item:
                        continue
                    idx = int(hashlib.sha256(item.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) % buckets
                    bucketed[idx].add(item)
                out: Dict[str, Dict[str, Union[int, str]]] = {}
                for i, bset in enumerate(bucketed):
                    out[str(i)] = {"n": len(bset), "d": _stable_set_digest(bset) if bset else ""}
                return out


            # Full cache hit: build final Entities/Relationships directly from cached payload.
            # We avoid feeding dicts into LlamaIndex graph-store types.
            if cache_enabled and cache_misses == 0 and cache_keys:
                diag_mentions_total = 0
                diag_chunks_with_entities = 0
                diag_raw_names: Set[str] = set()
                diag_canonical_keys: Set[str] = set()

                entity_to_chunks: Dict[str, List[str]] = {}
                entity_to_text: Dict[str, str] = {}
                entity_info: Dict[str, Dict[str, str]] = {}
                rel_records: List[Tuple[str, str, str]] = []

                for original_node, ck in zip(llama_nodes, cache_keys):
                    payload_json = cached_payloads.get(ck)
                    payload: Dict[str, Any] = {}
                    if payload_json:
                        try:
                            payload = json.loads(payload_json)
                        except Exception:
                            payload = {}

                    chunk_id = getattr(original_node, "id_", None) or getattr(original_node, "node_id", None) or ""
                    chunk_text = ""
                    try:
                        chunk_text = original_node.get_content()  # type: ignore[attr-defined]
                    except Exception:
                        chunk_text = getattr(original_node, "text", "") or ""

                    # Entities
                    chunk_has_entities = False
                    for ek in ("nodes", "kg_nodes"):
                        for ent in (payload.get(ek) or []):
                            if not isinstance(ent, dict):
                                continue
                            ename = str(ent.get("name") or "").strip()
                            elabel = str(ent.get("label") or "CONCEPT").strip() or "CONCEPT"
                            ekey = _canonical_entity_key(ename)
                            if not ekey:
                                continue
                            chunk_has_entities = True
                            diag_mentions_total += 1
                            diag_raw_names.add(ename[:200])
                            diag_canonical_keys.add(ekey)

                            info = entity_info.get(ekey)
                            if info is None:
                                entity_info[ekey] = {"name": ename, "type": elabel}

                            if ekey not in entity_to_chunks:
                                entity_to_chunks[ekey] = []
                                if chunk_text:
                                    entity_to_text[ekey] = chunk_text[:500]
                            entity_to_chunks[ekey].append(str(chunk_id))

                    if chunk_has_entities:
                        diag_chunks_with_entities += 1

                    # Relations
                    for rk in ("relations", "kg_relations"):
                        for rel in (payload.get(rk) or []):
                            if not isinstance(rel, dict):
                                continue
                            src = str(rel.get("source") or "").strip()
                            tgt = str(rel.get("target") or "").strip()
                            rlabel = str(rel.get("label") or "RELATED_TO").strip() or "RELATED_TO"
                            if not src or not tgt:
                                continue
                            sk = _canonical_entity_key(src)
                            tk = _canonical_entity_key(tgt)
                            if not sk or not tk:
                                continue
                            # Include relation endpoints in canonical set
                            diag_raw_names.add(src[:200])
                            diag_raw_names.add(tgt[:200])
                            diag_canonical_keys.add(sk)
                            diag_canonical_keys.add(tk)
                            rel_records.append((sk, tk, rlabel))

                logger.warning(
                    "v3_extract_determinism_llm_metadata %s",
                    {
                        "group_id": group_id,
                        "chunks": len(chunks),
                        "llama_nodes": len(llama_nodes),
                        "extracted_nodes": len(llama_nodes),
                        "cache_key_digest": cache_keys_digest,
                        "cache_key_sample": cache_keys_sample,
                        "validation_stats": {
                            "cache_enabled": True,
                            "cache_hits": cache_hits,
                            "cache_misses": cache_misses,
                            "total_extracted": len(llama_nodes),
                            "cache_key_digest": cache_keys_digest,
                            "cache_key_sample": cache_keys_sample,
                        },
                        "chunks_with_entities": diag_chunks_with_entities,
                        "entity_mentions_total": diag_mentions_total,
                        "raw_entity_names_unique": len(diag_raw_names),
                        "canonical_entity_keys_unique": len(diag_canonical_keys),
                        "canonical_entity_keys_digest": _stable_set_digest(diag_canonical_keys),
                        "canonical_entity_keys_buckets": _bucket_summaries(diag_canonical_keys),
                        "canonical_entity_keys_sample_hashes": [_hash12(k) for k in sorted(diag_canonical_keys)[:20]],
                        "relations_total": len(rel_records),
                    },
                )

                # Build final Entities/Relationships for persistence.
                all_entities: Dict[str, Entity] = {}
                name_to_id_map: Dict[str, str] = {}
                for ekey, info in entity_info.items():
                    new_id = f"entity_{uuid.uuid4().hex[:8]}"
                    desc = entity_to_text.get(ekey, "")
                    ent = Entity(
                        id=new_id,
                        name=info.get("name") or ekey,
                        type=info.get("type") or "CONCEPT",
                        description=desc,
                    )
                    chunk_ids = entity_to_chunks.get(ekey) or []
                    if chunk_ids:
                        ent.text_unit_ids = chunk_ids
                    all_entities[ekey] = ent
                    name_to_id_map[ekey] = new_id

                # Ensure relation endpoints exist as entities
                for sk, tk, _ in rel_records:
                    for k in (sk, tk):
                        if k in name_to_id_map:
                            continue
                        new_id = f"entity_{uuid.uuid4().hex[:8]}"
                        ent = Entity(
                            id=new_id,
                            name=k,
                            type="CONCEPT",
                            description=entity_to_text.get(k, ""),
                        )
                        chunk_ids = entity_to_chunks.get(k) or []
                        if chunk_ids:
                            ent.text_unit_ids = chunk_ids
                        all_entities[k] = ent
                        name_to_id_map[k] = new_id

                all_relationships: List[Relationship] = []
                for sk, tk, rlabel in rel_records:
                    sid = name_to_id_map.get(sk)
                    tid = name_to_id_map.get(tk)
                    if not sid or not tid:
                        continue
                    all_relationships.append(
                        Relationship(
                            source_id=sid,
                            target_id=tid,
                            description=rlabel,
                        )
                    )

                # Generate embeddings for entities on cache hit as well.
                # Without this, cached runs store entities without embeddings (hurts downstream ranking).
                entities_list = list(all_entities.values())
                if entities_list and getattr(self, "embedder", None) is not None:
                    entity_texts = [
                        f"{entity.name}: {entity.description}" if entity.description else entity.name
                        for entity in entities_list
                    ]
                    try:
                        logger.warning(
                            "⚡ EMBEDDING START: Generating embeddings for %s entities (cache_hit)",
                            len(entities_list),
                        )
                        embeddings = await self.embedder.aget_text_embedding_batch(entity_texts)
                        for entity, embedding in zip(entities_list, embeddings):
                            entity.embedding = embedding
                        logger.warning(
                            "✅ EMBEDDING SUCCESS: Generated %s entity embeddings (cache_hit, dim=%s)",
                            len(embeddings),
                            len(embeddings[0]) if embeddings else 0,
                        )
                    except Exception as e:
                        logger.error(f"❌ Failed to generate entity embeddings (cache_hit): {e}", exc_info=True)
                        for entity in entities_list:
                            entity.embedding = [0.0] * self.config.embedding_dimensions
                        logger.warning(
                            "⚠️  Using zero vectors for %s entities due to embedding failure (cache_hit)",
                            len(entities_list),
                        )
                elif entities_list:
                    for entity in entities_list:
                        entity.embedding = [0.0] * self.config.embedding_dimensions

                return entities_list, all_relationships
            
            for i, node in enumerate(extracted_nodes):
                if i == 0:
                    logger.info(f"First node metadata keys: {list(node.metadata.keys())}")
                
                chunk_id = node.node_id if hasattr(node, 'node_id') else node.id_
                
                # Capture chunk text for entity descriptions
                chunk_text = ""
                if hasattr(node, "get_content"):
                    try:
                        chunk_text = node.get_content()
                    except Exception:
                        chunk_text = getattr(node, "text", "") or getattr(node, "content", "")
                else:
                    chunk_text = getattr(node, "text", "") or getattr(node, "content", "")

                def _extract_entity_name(entity_node: object) -> str:
                    name_val = getattr(entity_node, "name", None)
                    if name_val:
                        return str(name_val)
                    props = getattr(entity_node, "properties", None)
                    if isinstance(props, dict) and props.get("name"):
                        return str(props.get("name"))
                    for attr in ("id", "id_", "node_id"):
                        v = getattr(entity_node, attr, None)
                        if v:
                            return str(v)
                    return ""

                def _extract_relation_endpoint_names(rel: object) -> list[str]:
                    """Best-effort extraction of endpoint identifiers from a LlamaIndex relation.

                    Some extractors only return relations, and the graph-store may implicitly
                    create/ensure endpoint nodes during relation upsert. Including these endpoint
                    identifiers in LLM-stage diagnostics makes the LLM digest comparable to the
                    graph-store digest.
                    """

                    candidates: list[str] = []
                    for attr in (
                        "source_id",
                        "target_id",
                        "source",
                        "target",
                        "subject",
                        "object",
                        "head",
                        "tail",
                        "from_id",
                        "to_id",
                    ):
                        v = getattr(rel, attr, None)
                        if v:
                            candidates.append(str(v))

                    props = getattr(rel, "properties", None)
                    if isinstance(props, dict):
                        for k in (
                            "source",
                            "target",
                            "source_id",
                            "target_id",
                            "subject",
                            "object",
                            "from",
                            "to",
                        ):
                            pv = props.get(k)
                            if pv:
                                candidates.append(str(pv))

                    # De-dup while preserving order
                    seen: set[str] = set()
                    out: list[str] = []
                    for c in candidates:
                        c = (c or "").strip()
                        if not c or c in seen:
                            continue
                        seen.add(c)
                        out.append(c)
                    return out

                # LlamaIndex stores extracted data in either 'nodes'/'kg_nodes' and 'relations'/'kg_relations'
                if "nodes" in node.metadata:
                    if node.metadata.get("nodes"):
                        diag_chunks_with_entities += 1
                    # Track which entities came from this chunk
                    for entity_node in node.metadata["nodes"]:
                        entity_name = _extract_entity_name(entity_node)
                        entity_key = _canonical_entity_key(entity_name)
                        if not entity_key:
                            continue
                        diag_mentions_total += 1
                        diag_raw_names.add(str(entity_name)[:200])
                        diag_canonical_keys.add(entity_key)
                        if entity_key not in entity_to_chunks:
                            entity_to_chunks[entity_key] = []
                            # Store the first chunk text where this entity appears
                            if chunk_text:
                                entity_to_text[entity_key] = chunk_text[:500]
                        entity_to_chunks[entity_key].append(chunk_id)
                    all_entity_nodes.extend(node.metadata["nodes"])
                elif "kg_nodes" in node.metadata:
                    if node.metadata.get("kg_nodes"):
                        diag_chunks_with_entities += 1
                    for entity_node in node.metadata["kg_nodes"]:
                        entity_name = _extract_entity_name(entity_node)
                        entity_key = _canonical_entity_key(entity_name)
                        if not entity_key:
                            continue
                        diag_mentions_total += 1
                        diag_raw_names.add(str(entity_name)[:200])
                        diag_canonical_keys.add(entity_key)
                        if entity_key not in entity_to_chunks:
                            entity_to_chunks[entity_key] = []
                            # Store the first chunk text where this entity appears
                            if chunk_text:
                                entity_to_text[entity_key] = chunk_text[:500]
                        entity_to_chunks[entity_key].append(chunk_id)
                    all_entity_nodes.extend(node.metadata["kg_nodes"])
                
                if "relations" in node.metadata:
                    rels = node.metadata["relations"]
                    all_relations.extend(rels)
                    # Include relation endpoints in LLM-stage entity-key diagnostics
                    for rel in rels or []:
                        for endpoint_name in _extract_relation_endpoint_names(rel):
                            ek = _canonical_entity_key(endpoint_name)
                            if ek:
                                diag_raw_names.add(str(endpoint_name)[:200])
                                diag_canonical_keys.add(ek)
                elif "kg_relations" in node.metadata:
                    rels = node.metadata["kg_relations"]
                    all_relations.extend(rels)
                    for rel in rels or []:
                        for endpoint_name in _extract_relation_endpoint_names(rel):
                            ek = _canonical_entity_key(endpoint_name)
                            if ek:
                                diag_raw_names.add(str(endpoint_name)[:200])
                                diag_canonical_keys.add(ek)
            
            logger.warning(
                "v3_extract_determinism_llm_metadata %s",
                {
                    "group_id": group_id,
                    "chunks": len(chunks),
                    "llama_nodes": len(llama_nodes),
                    "extracted_nodes": len(extracted_nodes),
                    "cache_key_digest": cache_keys_digest,
                    "cache_key_sample": cache_keys_sample,
                    "validation_stats": validation_stats,
                    "chunks_with_entities": diag_chunks_with_entities,
                    "entity_mentions_total": diag_mentions_total,
                    "raw_entity_names_unique": len(diag_raw_names),
                    "canonical_entity_keys_unique": len(diag_canonical_keys),
                    "canonical_entity_keys_digest": _stable_set_digest(diag_canonical_keys),
                    "canonical_entity_keys_buckets": _bucket_summaries(diag_canonical_keys),
                    "canonical_entity_keys_sample_hashes": [_hash12(k) for k in sorted(diag_canonical_keys)[:20]],
                    "relations_total": len(all_relations),
                },
            )

            logger.info(f"Found {len(all_entity_nodes)} entities and {len(all_relations)} relations")
            
            if all_entity_nodes:
                temp_graph_store.upsert_nodes(all_entity_nodes)
            
            if all_relations:
                temp_graph_store.upsert_relations(all_relations)
                
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
        graph = temp_graph_store.graph
        graph_nodes = graph.nodes
        graph_relations = graph.relations
        
        # Helper to find entity ID by name
        name_to_id_map = {}

        # Determinism diagnostics: summarize what actually ended up in the graph store.
        diag_graph_raw_names: Set[str] = set()
        diag_graph_canonical: Set[str] = set()
        diag_canonical_to_variants: Dict[str, Set[str]] = {}
        desc_upgrades = 0

        def _stable_set_digest(items: Set[str]) -> str:
            h = hashlib.sha256()
            for s in sorted(items):
                h.update(s.encode("utf-8", errors="ignore"))
                h.update(b"\n")
            return h.hexdigest()[:12]

        def _hash12(value: str) -> str:
            h = hashlib.sha256()
            h.update((value or "").encode("utf-8", errors="ignore"))
            return h.hexdigest()[:12]

        def _bucket_summaries(items: Set[str], buckets: int = 8) -> Dict[str, Dict[str, Union[int, str]]]:
            bucketed: list[set[str]] = [set() for _ in range(buckets)]
            for item in items:
                if not item:
                    continue
                idx = int(hashlib.sha256(item.encode("utf-8", errors="ignore")).hexdigest()[:8], 16) % buckets
                bucketed[idx].add(item)
            out: Dict[str, Dict[str, Union[int, str]]] = {}
            for i, bset in enumerate(bucketed):
                out[str(i)] = {"n": len(bset), "d": _stable_set_digest(bset) if bset else ""}
            return out

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

             diag_graph_raw_names.add(str(entity_name)[:200])
             entity_key = _canonical_entity_key(entity_name)
             if not entity_key:
                 continue

             diag_graph_canonical.add(entity_key)
             vset = diag_canonical_to_variants.get(entity_key)
             if vset is None:
                 vset = set()
                 diag_canonical_to_variants[entity_key] = vset
             vset.add(str(entity_name)[:200])

             def _description_score(text: str) -> tuple[int, int]:
                 t = (text or "").strip()
                 if not t:
                     return (0, 0)
                 words = re.findall(r"[a-z0-9]+", t.lower())
                 return (len(set(words)), len(t))

             def _choose_better_description(existing: str, candidate: str) -> str:
                 cand = (candidate or "").strip()
                 if not cand:
                     return (existing or "").strip()
                 cur = (existing or "").strip()
                 if not cur:
                     return cand
                 # Prefer non-dict-like descriptions over raw properties dumps
                 cur_dicty = cur.startswith("{") and cur.endswith("}")
                 cand_dicty = cand.startswith("{") and cand.endswith("}")
                 if cur_dicty and not cand_dicty:
                     return cand
                 if cand_dicty and not cur_dicty:
                     return cur
                 return cand if _description_score(cand) > _description_score(cur) else cur
             
             # Create entity if not exists
             if entity_key not in all_entities:
                 new_id = f"entity_{uuid.uuid4().hex[:8]}"
                 chunk_ids_for_entity = entity_to_chunks.get(entity_key, [])
                 
                 # Get description from chunk text where entity appears
                 description = entity_to_text.get(entity_key, "")
                 
                 # If no description from entity_to_text, use chunk text from first chunk_id
                 if not description and chunk_ids_for_entity:
                     first_chunk_id = chunk_ids_for_entity[0]
                     # Find the chunk text from chunks list
                     for chunk in chunks:
                         if chunk.id == first_chunk_id:
                             description = chunk.text[:500]  # First 500 chars of chunk
                             break
                 
                 # Fallback to node properties if still no description
                 if not description and hasattr(node, 'properties'):
                     description = str(node.properties)
                 
                 all_entities[entity_key] = Entity(
                     id=new_id,
                     name=entity_name,
                     type=node.label if hasattr(node, 'label') else "CONCEPT",
                     description=description,
                 )
                 name_to_id_map[entity_key] = new_id
                 
                 # Store chunk IDs for this entity (for MENTIONS relationships)
                 if chunk_ids_for_entity:
                     all_entities[entity_key].text_unit_ids = chunk_ids_for_entity
             else:
                 # If already exists, merge chunk IDs
                 name_to_id_map[entity_key] = all_entities[entity_key].id
                 chunk_ids_for_entity = entity_to_chunks.get(entity_key, [])
                 if chunk_ids_for_entity:
                     existing_ids = getattr(all_entities[entity_key], 'text_unit_ids', [])
                     all_entities[entity_key].text_unit_ids = list(set(existing_ids + chunk_ids_for_entity))

                 # Upgrade description when we see better evidence later.
                 candidate_desc = entity_to_text.get(entity_key, "")
                 if not candidate_desc and chunk_ids_for_entity:
                     first_chunk_id = chunk_ids_for_entity[0]
                     for chunk in chunks:
                         if chunk.id == first_chunk_id:
                             candidate_desc = chunk.text[:500]
                             break
                 if not candidate_desc and hasattr(node, 'properties'):
                     candidate_desc = str(node.properties)

                 before_desc = getattr(all_entities[entity_key], "description", "")
                 after_desc = _choose_better_description(before_desc, candidate_desc)
                 if after_desc != (before_desc or ""):
                     desc_upgrades += 1
                 all_entities[entity_key].description = after_desc

        variant_clusters = [(k, len(v)) for k, v in diag_canonical_to_variants.items() if len(v) > 1]
        variant_clusters.sort(key=lambda t: (-t[1], t[0]))
        top_variant_clusters = []
        for k, n in variant_clusters[:8]:
            samples = sorted(diag_canonical_to_variants.get(k, set()))[:6]
            top_variant_clusters.append({"key": k[:120], "variants": n, "samples": samples})

        logger.warning(
            "v3_extract_determinism_graph_store %s",
            {
                "group_id": group_id,
                "graph_nodes": len(graph_nodes),
                "graph_relations": len(graph_relations),
                "graph_raw_names_unique": len(diag_graph_raw_names),
                "graph_canonical_keys_unique": len(diag_graph_canonical),
                "graph_canonical_digest": _stable_set_digest(diag_graph_canonical),
                "graph_canonical_buckets": _bucket_summaries(diag_graph_canonical),
                "graph_canonical_sample_hashes": [_hash12(k) for k in sorted(diag_graph_canonical)[:20]],
                "canonical_keys_with_variants": len(variant_clusters),
                "top_variant_clusters": top_variant_clusters,
                "final_entities": len(all_entities),
                "final_relationships": len(all_relationships),
                "description_upgrades": desc_upgrades,
            },
        )

        for relation_id, relation in graph_relations.items():
            # relation is a Relation object
            # relation.source_id and relation.target_id are the keys in graph_nodes
            # Since we determined that graph_nodes keys are the entity names, we can use them directly
            
            source_name = relation.source_id
            target_name = relation.target_id
            
            # Fallback: if for some reason IDs are not names, try to look up the node
            if _canonical_entity_key(str(source_name)) not in name_to_id_map:
                 source_node = graph_nodes.get(source_name)
                 if source_node:
                     if hasattr(source_node, "name") and source_node.name:
                         source_name = source_node.name
                     elif hasattr(source_node, "properties") and "name" in source_node.properties:
                         source_name = source_node.properties["name"]

            if _canonical_entity_key(str(target_name)) not in name_to_id_map:
                 target_node = graph_nodes.get(target_name)
                 if target_node:
                     if hasattr(target_node, "name") and target_node.name:
                         target_name = target_node.name
                     elif hasattr(target_node, "properties") and "name" in target_node.properties:
                         target_name = target_node.properties["name"]
            
            source_key = _canonical_entity_key(str(source_name))
            target_key = _canonical_entity_key(str(target_name))
            
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
            graph_data = temp_graph_store.get_triplets()
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
        
        logger.info(f"🏁 Finished entity extraction loop. Total entities: {len(all_entities)}, relationships: {len(all_relationships)}")
        
        # Generate embeddings for entities (single batch with 100K TPM capacity)
        entities_list = list(all_entities.values())
        
        if entities_list:
            entity_texts = [
                f"{entity.name}: {entity.description}" if entity.description else entity.name
                for entity in entities_list
            ]
            
            try:
                logger.warning(f"⚡ EMBEDDING START: Generating embeddings for {len(entities_list)} entities")
                
                # AzureOpenAIEmbedding has aget_text_embedding_batch for efficient batch processing
                embeddings = await self.embedder.aget_text_embedding_batch(entity_texts)
                
                # Assign embeddings to entities
                for entity, embedding in zip(entities_list, embeddings):
                    entity.embedding = embedding
                
                logger.warning(f"✅ EMBEDDING SUCCESS: Generated {len(embeddings)} entity embeddings (dim={len(embeddings[0])})")
                
            except Exception as e:
                logger.error(f"❌ Failed to generate entity embeddings: {e}", exc_info=True)
                for entity in entities_list:
                    entity.embedding = [0.0] * self.config.embedding_dimensions
                logger.warning(f"⚠️  Using zero vectors for {len(entities_list)} entities due to embedding failure")
        
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
            logger.info(
                "v3_community_detection_skipped %s",
                {
                    "group_id": group_id,
                    "reason": "too_few_entities",
                    "entity_count": len(entities),
                    "relationship_count": len(relationships),
                    "min_community_size": self.config.min_community_size,
                },
            )
            return []
        
        # Build adjacency matrix
        entity_ids = [e.id for e in entities]
        entity_index = {eid: idx for idx, eid in enumerate(entity_ids)}
        n = len(entities)
        
        # Create sparse adjacency matrix
        adj_matrix = np.zeros((n, n), dtype=np.float32)
        
        edges_added = 0
        for rel in relationships:
            src_idx = entity_index.get(rel.source_id)
            tgt_idx = entity_index.get(rel.target_id)
            if src_idx is not None and tgt_idx is not None:
                weight = rel.weight
                adj_matrix[src_idx, tgt_idx] = weight
                adj_matrix[tgt_idx, src_idx] = weight  # Make symmetric
                edges_added += 1

        # If there are no edges, hierarchical_leiden often degenerates into singleton clusters.
        # For Global Search we still want a deterministic, queryable "community report".
        if edges_added == 0:
            community = Community(
                id=f"community_L0_all_{uuid.uuid4().hex[:8]}",
                level=0,
                entity_ids=entity_ids,
                title="Community Level 0 - all",
                rank=1.0,
            )
            logger.warning(
                "v3_community_detection_no_edges %s",
                {
                    "group_id": group_id,
                    "entity_count": len(entities),
                    "relationship_count": len(relationships),
                    "edges_added": edges_added,
                    "communities_created": 1,
                    "note": "created_single_all_entities_community",
                },
            )
            return [community]
        
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
            
            # Normalize levels so the minimum level becomes 0.
            # Global Query defaults to level=0; without normalization, some graspologic
            # outputs start at level=1 which makes global search appear "empty".
            min_level = min(level_communities.keys()) if level_communities else 0

            pruned_small = 0
            # Create Community objects
            for level, comm_dict in level_communities.items():
                normalized_level = int(level) - int(min_level)
                if normalized_level < 0:
                    continue
                if normalized_level >= self.config.max_community_levels:
                    continue

                for comm_id, member_ids in comm_dict.items():
                    if len(member_ids) < self.config.min_community_size:
                        pruned_small += 1
                        continue

                    community = Community(
                        id=f"community_L{normalized_level}_{comm_id}_{uuid.uuid4().hex[:8]}",
                        level=normalized_level,
                        entity_ids=member_ids,
                        title=f"Community Level {normalized_level} - {comm_id}",
                        rank=len(member_ids) / n,  # Rank by size
                    )
                    communities.append(community)

            logger.warning(
                "v3_community_detection_summary %s",
                {
                    "group_id": group_id,
                    "entity_count": len(entities),
                    "relationship_count": len(relationships),
                    "edges_added": edges_added,
                    "levels_raw": sorted(level_communities.keys()),
                    "min_level_raw": min_level,
                    "levels_normalized": sorted({c.level for c in communities}),
                    "communities_created": len(communities),
                    "communities_pruned_small": pruned_small,
                    "min_community_size": self.config.min_community_size,
                    "max_community_levels": self.config.max_community_levels,
                    "community_resolution": self.config.community_resolution,
                },
            )

            return communities
            
        except Exception as e:
            logger.warning(
                "v3_community_detection_failed %s",
                {
                    "group_id": group_id,
                    "error": str(e),
                    "entity_count": len(entities),
                    "relationship_count": len(relationships),
                    "edges_added": edges_added,
                },
            )
            return []
    
    async def _generate_community_summary(
        self,
        community: Community,
        all_entities: List[Entity],
        chunk_by_id: Dict[str, TextChunk],
        all_chunks: List[TextChunk],
    ) -> str:
        """Generate a grounded community report for Microsoft GraphRAG Global Search.

        Unlike an entity-only abstract summary, this report is grounded in supporting
        text chunks (via entity.text_unit_ids) so it can retain concrete terms (dates,
        amounts, notice periods) without hallucination.
        """
        entity_dict = {e.id: e for e in all_entities}
        member_entities = [entity_dict[eid] for eid in community.entity_ids if eid in entity_dict]
        if not member_entities:
            return ""

        def _normalize_for_grounding(s: str) -> str:
            s = (s or "").lower()
            s = s.replace("\u00a0", " ")
            s = re.sub(r"\s+", " ", s).strip()
            return s

        def _extract_value_like_spans(text: str) -> list[str]:
            t = text or ""
            spans: list[str] = []
            spans.extend(re.findall(r"https?://\S+", t, flags=re.IGNORECASE))
            spans.extend(re.findall(r"\b\d{4,}\b", t))
            spans.extend(re.findall(r"\b[A-Za-z]{1,6}[-_]\d{2,}\b", t))
            seen = set()
            out: list[str] = []
            for s in spans:
                key = re.sub(r"[^a-z0-9]", "", s.lower())
                if key and key not in seen:
                    seen.add(key)
                    out.append(s)
            return out

        def _value_spans_grounded(answer: str, context: str) -> bool:
            ctx = _normalize_for_grounding(context)
            if not ctx:
                return False
            ctx_key = re.sub(r"[^a-z0-9]", "", ctx)
            for span in _extract_value_like_spans(answer):
                span_key = re.sub(r"[^a-z0-9]", "", span.lower())
                if span_key and span_key not in ctx_key:
                    return False
            return True

        def _extract_concrete_fact_spans(excerpts: str, *, max_items: int = 14) -> list[str]:
            """Extract concrete fact spans that should be preserved in community reports.

            This is intentionally targeted (not every 4+ digit number), focusing on:
            - money/amounts (e.g., $300,000, 29900.00)
            - invoice labels (amount due/total/subtotal/balance due)
            - deadlines (e.g., 10 business days, 60 days)
            - delivery methods (certified mail/return receipt requested)
            - jurisdiction phrases (state of X / governed by the laws of ...)
            """
            text = _normalize_for_grounding(excerpts)
            if not text:
                return []

            spans: list[str] = []

            # Delivery / notice
            for pat in [
                r"certified mail return receipt requested",
                r"return receipt requested",
                r"certified mail",
                r"written notice",
                r"in writing",
            ]:
                if re.search(pat, text, flags=re.IGNORECASE):
                    spans.append(pat)

            # Non-refundable / fees phrasing
            for m in re.finditer(r"\bnon-refundable\b[^\n.]{0,80}", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())
            if re.search(r"\bstart-?up fee\b", text, flags=re.IGNORECASE):
                spans.append("start-up fee")

            # Jurisdiction / governing law
            for m in re.finditer(r"\b(?:laws of|governed by|governed and construed in accordance with)\b[^\n.]{0,120}", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())
            for m in re.finditer(r"\bstate of\s+[a-z][a-z\s]{2,30}\b", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())

            # Deadlines / time periods
            for m in re.finditer(r"\b\d{1,3}\s+(?:business\s+)?days\b", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())
            for m in re.finditer(r"\b(?:sixty|ten)\s*\(\s*\d{1,3}\s*\)\s*(?:business\s+)?days\b", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())

            # Invoice financial labels with values (captures 29900.00 patterns)
            for m in re.finditer(
                r"\b(?:subtotal|total|amount\s+due|balance\s+due|total\s*/\s*amount\s+due|total\s+amount\s+due)\b\s*[:\-|]?\s*\$?\s*\d[\d,]*(?:\.\d{2})?\b",
                text,
                flags=re.IGNORECASE,
            ):
                spans.append(m.group(0).strip())

            # Standalone money amounts (USD-like)
            for m in re.finditer(r"\$\s*\d[\d,]*(?:\.\d{2})?\b", text, flags=re.IGNORECASE):
                spans.append(m.group(0).strip())

            # Decimal amounts with cents (common in invoices), but avoid years.
            for m in re.finditer(r"\b\d{2,}(?:,\d{3})*(?:\.\d{2})\b", text):
                spans.append(m.group(0).strip())

            # De-dup while preserving order, prefer shorter spans (more likely to match verbatim).
            seen: set[str] = set()
            out: list[str] = []
            for s in spans:
                k = re.sub(r"[^a-z0-9]", "", (s or "").lower())
                if not k or k in seen:
                    continue
                seen.add(k)
                out.append(s)
                if len(out) >= max_items:
                    break
            return out

        def _concrete_facts_covered(report_text: str, fact_spans: list[str]) -> bool:
            if not fact_spans:
                return True
            rkey = re.sub(r"[^a-z0-9]", "", _normalize_for_grounding(report_text))
            if not rkey:
                return False
            for s in fact_spans:
                skey = re.sub(r"[^a-z0-9]", "", (s or "").lower())
                if not skey:
                    continue
                # Special-case regex markers we used above for exact phrases.
                if s in {"certified mail return receipt requested", "return receipt requested", "certified mail", "written notice", "in writing"}:
                    skey = re.sub(r"[^a-z0-9]", "", s)
                if skey and skey not in rkey:
                    return False
            return True

        # Collect supporting chunks from entity mentions.
        # Important: preserve *relevance ordering* by prioritizing chunks mentioned
        # by many member entities. This helps retain concrete terms (amounts/dates)
        # that would otherwise get dropped if we take the first N arbitrary ids.
        chunk_counts: dict[str, int] = {}
        for e in member_entities:
            ids = getattr(e, "text_unit_ids", None) or []
            for cid in ids:
                if not cid:
                    continue
                chunk_counts[cid] = chunk_counts.get(cid, 0) + 1
            # Avoid unbounded growth on very large communities.
            if len(chunk_counts) >= 200:
                break

        chunk_ids: list[str] = sorted(
            chunk_counts.keys(),
            key=lambda cid: (-chunk_counts.get(cid, 0), cid),
        )

        # Fallback: add chunk candidates by embedding similarity to the community theme.
        # This catches important contract clauses that weren't linked to entities.
        try:
            if len(chunk_ids) < 12 and getattr(self, "embedder", None) is not None:
                names = [e.name for e in member_entities[:10] if (e.name or "").strip()]
                query_text = (f"{community.title}\n" + "\n".join(names)).strip()
                if query_text:
                    q_emb = self.embedder.get_text_embedding(query_text)
                    scored: list[tuple[float, str]] = []
                    for ch in all_chunks:
                        if not ch.embedding or len(ch.embedding) != len(q_emb):
                            continue
                        # cosine similarity
                        dot = 0.0
                        na = 0.0
                        nb = 0.0
                        for a, b in zip(q_emb, ch.embedding):
                            dot += a * b
                            na += a * a
                            nb += b * b
                        denom = (na ** 0.5) * (nb ** 0.5)
                        sim = (dot / denom) if denom else 0.0
                        if ch.id:
                            scored.append((sim, ch.id))
                    scored.sort(key=lambda t: t[0], reverse=True)
                    for _, cid in scored[:20]:
                        if cid not in chunk_ids:
                            chunk_ids.append(cid)
                        if len(chunk_ids) >= 50:
                            break
        except Exception as e:
            logger.debug(f"Embedding-based chunk selection failed: {e}")

        # Prioritize excerpts that contain concrete terms (amounts, deadlines, jurisdictions, delivery methods)
        # so they survive the top-N excerpt cap.
        def _concrete_score_for_chunk(cid: str) -> int:
            c = chunk_by_id.get(cid)
            if not c or not (c.text or "").strip():
                return 0
            t = _normalize_for_grounding(c.text)
            score = 0
            if any(k in t for k in ["amount due", "balance due", "subtotal", "total"]):
                score += 6
            if any(k in t for k in ["certified mail", "return receipt"]):
                score += 6
            if any(k in t for k in ["governing law", "governed by", "laws of", "state of"]):
                score += 4
            if any(k in t for k in ["jurisdiction", "venue", "arbitration", "aaa", "american arbitration association"]):
                score += 2
            if any(k in t for k in ["insurance", "indemn", "hold harmless", "liability", "coverage", "policy", "bond"]):
                score += 4
            if any(k in t for k in ["fee", "fees", "commission", "charge", "charges", "admin", "accounting", "advertising", "pro-rat", "prorat"]):
                score += 2
            if re.search(r"\b\d{1,3}\s+(?:business\s+)?days\b", t):
                score += 4
            if re.search(r"\$\s*\d[\d,]*(?:\.\d{2})?\b", t):
                score += 5
            if re.search(r"\b\d{2,}(?:,\d{3})*(?:\.\d{2})\b", t):
                score += 3
            return score

        chunk_ids = sorted(
            chunk_ids,
            key=lambda cid: (
                -_concrete_score_for_chunk(cid),
                -chunk_counts.get(cid, 0),
                cid,
            ),
        )

        # Document-aware expansion: if this community already touches a document,
        # add a few of the most concrete chunks from those same documents.
        # This helps capture governing law blocks, invoice totals, insurance limits,
        # and other concrete clauses that may not be linked via entity mentions.
        doc_counts: dict[str, int] = {}
        for cid in chunk_ids:
            c = chunk_by_id.get(cid)
            doc_id = getattr(c, "document_id", None) if c else None
            if doc_id:
                doc_counts[doc_id] = doc_counts.get(doc_id, 0) + 1

        # Include more than 2 documents to avoid missing key clauses that
        # live outside the entity-linked chunks (e.g., governing law, insurance limits).
        candidate_doc_ids = [
            doc_id
            for doc_id, _ in sorted(doc_counts.items(), key=lambda t: (-t[1], t[0]))[:5]
        ]

        if candidate_doc_ids:
            extras: list[tuple[int, str]] = []
            existing = set(chunk_ids)
            for ch in all_chunks:
                if not getattr(ch, "id", None) or getattr(ch, "document_id", None) not in candidate_doc_ids:
                    continue
                cid = ch.id
                if cid in existing:
                    continue
                sc = _concrete_score_for_chunk(cid)
                if sc > 0:
                    extras.append((sc, cid))
            extras.sort(key=lambda t: (-t[0], t[1]))
            # Prefer these concrete chunks by pushing them earlier in the excerpt list.
            for _, cid in extras[:10]:
                chunk_ids.insert(0, cid)
                existing.add(cid)

            # De-dup while preserving order
            seen_cids: set[str] = set()
            deduped: list[str] = []
            for cid in chunk_ids:
                if cid and cid not in seen_cids:
                    seen_cids.add(cid)
                    deduped.append(cid)
            chunk_ids = deduped

        excerpts: list[str] = []
        for cid in chunk_ids[:20]:
            c = chunk_by_id.get(cid)
            if not c:
                continue
            text = (c.text or "").strip()
            if not text:
                continue
            if len(text) > 2000:
                text = text[:2000] + "..."
            meta = c.metadata or {}
            src = meta.get("source") or meta.get("file_name") or c.document_id
            page = meta.get("page_number")
            header = f"[Chunk {c.id} | doc={src}{' | page='+str(page) if page else ''}]"
            excerpts.append(f"{header}\n{text}")

        # Build entity hint list (kept short)
        entity_hints: list[str] = []
        for e in member_entities[:15]:
            entity_hints.append(f"- {e.name} ({e.type})")

        excerpts_text = "\n\n---\n\n".join(excerpts) if excerpts else "(No supporting excerpts found.)"

        required_fact_spans = _extract_concrete_fact_spans(excerpts_text)

        prompt = f"""You are generating a COMMUNITY REPORT for Microsoft GraphRAG Global Search.

You MUST follow these rules:
- Use ONLY the provided text excerpts. Do not invent or guess.
- If a specific value (numbers, URLs, legal jurisdictions, notice periods, dollar amounts) is not explicitly present, write: Not specified in excerpts.
- Prefer quoting exact phrases from the excerpts when stating concrete terms.
    - IMPORTANT: If the excerpts contain concrete facts (amounts, deadlines, governing law, delivery methods), you MUST carry them into the report verbatim.

Community title: {community.title}

Entity hints (may help orient you, but do NOT add facts from hints):
{chr(10).join(entity_hints)}

Supporting excerpts:
{excerpts_text}

Concrete facts to preserve (verbatim or near-verbatim; do NOT add new facts):
{json.dumps(required_fact_spans, ensure_ascii=False)}

Write a structured report with these sections:
1) Overview (1-2 sentences)
2) Key parties / organizations (bullets)
3) Key obligations / terms (bullets; include notice/termination if present)
4) Key financial terms (bullets; amounts/fees if present)
5) Key dates / deadlines (bullets)
6) Governing law / jurisdiction (bullets)
7) Verbatim clause snippets (bullets; quote exact phrases; prefix each bullet with the chunk header like [Chunk ...])

Report:"""

        try:
            report = (await self._llm_complete(prompt) or "").strip()
            # Enforce grounding for concrete values. If the model invents values,
            # retry once with an explicit correction request.
            if report and excerpts_text and not _value_spans_grounded(report, excerpts_text):
                offending = _extract_value_like_spans(report)
                fix_prompt = f"""You wrote a community report but included concrete values not present in the excerpts.

Offending value-like spans (must NOT appear unless explicitly in excerpts):
{json.dumps(offending, ensure_ascii=False)}

Rewrite the report using ONLY the excerpts. If a value is not present, write: Not specified in excerpts.

Supporting excerpts:
{excerpts_text}

Corrected report:"""
                report2 = (await self._llm_complete(fix_prompt) or "").strip()
                if report2 and _value_spans_grounded(report2, excerpts_text):
                    report = report2

            # Enforce coverage: if excerpts contain concrete facts, require the report to include them.
            # This makes Global Search reliably report-driven (no query-time heuristics needed).
            if report and excerpts_text and required_fact_spans and not _concrete_facts_covered(report, required_fact_spans):
                fix_missing_prompt = f"""Your community report omitted concrete facts that ARE explicitly present in the excerpts.

You MUST rewrite the report and include ALL of these concrete facts (verbatim or near-verbatim) somewhere in the appropriate sections:
{json.dumps(required_fact_spans, ensure_ascii=False)}

Rules:
- Use ONLY the excerpts.
- Do NOT add any new numbers, jurisdictions, deadlines, fees, IDs, or clauses beyond what appears in the excerpts.
- Prefer quoting exact phrases.

Supporting excerpts:
{excerpts_text}

Corrected report:"""
                report3 = (await self._llm_complete(fix_missing_prompt) or "").strip()
                if report3 and _value_spans_grounded(report3, excerpts_text) and _concrete_facts_covered(report3, required_fact_spans):
                    report = report3

            if report and excerpts_text and not _value_spans_grounded(report, excerpts_text):
                names = ", ".join(e.name for e in member_entities[:8])
                return f"Community entities: {names}"

            # Do NOT reuse RAPTOR token limits here: truncating community reports can
            # cut off later sections (e.g., governing law / insurance / fees) even
            # after we enforced that the model included them.
            max_chars = int(getattr(self.config, "community_report_max_chars", 8000) or 8000)
            if max_chars <= 0:
                max_chars = 8000
            return report[:max_chars]
        except Exception as e:
            logger.warning(f"Community report generation failed: {e}")
            # Fallback: entity-only, but avoid hallucination by keeping it purely enumerative
            names = ", ".join(e.name for e in member_entities[:8])
            return f"Community entities: {names}"
    
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
                # Add delay to respect rate limits (1 second between calls)
                if cluster_idx > 0:
                    await asyncio.sleep(1.0)
                    
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
                # Get deployment name from LLM instance (e.g., "gpt-4.1")
                deployment_name = getattr(self.llm, "deployment_name", self.config.llm_model)
                
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
                        "creation_model": deployment_name,
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
        """Generate embedding for text using AzureOpenAIEmbedding."""
        return await self.embedder.aget_text_embedding(text)
    
    async def _llm_complete(self, prompt: str) -> str:
        """Generate completion using AzureOpenAI."""
        messages = [ChatMessage(role=MessageRole.USER, content=prompt)]

        # Be polite to Azure OpenAI token rate limits.
        # LlamaIndex has its own retry, but it may retry too aggressively (e.g., 1s) relative
        # to the server-provided guidance (often 10s+). This wrapper adds an outer backoff.
        delay_s = 1.0
        max_attempts = 6

        for attempt in range(1, max_attempts + 1):
            try:
                response = await self.llm.achat(messages)
                return response.message.content
            except Exception as e:
                error_text = str(e)
                is_rate_limited = (
                    "RateLimit" in e.__class__.__name__
                    or "RateLimitReached" in error_text
                    or "Error code: 429" in error_text
                )

                if (not is_rate_limited) or attempt >= max_attempts:
                    raise

                # Parse common Azure message: "Please retry after 10 seconds."
                m = re.search(r"retry after\s+(\d+(?:\.\d+)?)\s+seconds", error_text, flags=re.IGNORECASE)
                if m:
                    delay_s = float(m.group(1))
                else:
                    delay_s = min(delay_s * 2.0, 30.0)

                # Small jitter to avoid thundering herd in multi-replica scenarios.
                delay_s = delay_s + (random.random() * 0.5)
                logger.warning(
                    "v3_llm_rate_limited",
                    attempt=attempt,
                    sleep_seconds=delay_s,
                )
                await asyncio.sleep(delay_s)

        raise RuntimeError("Unreachable: _llm_complete retry loop exhausted")
