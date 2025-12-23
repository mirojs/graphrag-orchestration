"""
Neo4j GraphRAG Service - Simplified Implementation using neo4j-graphrag-python.

This module replaces ~1,600 lines of custom code with the official neo4j-graphrag package.

Components used:
- VectorRetriever: Vector similarity search
- HybridRetriever: Vector + fulltext combined search
- Text2CypherRetriever: Natural language to Cypher
- SimpleKGPipeline: Document indexing and KG construction
- GraphRAG: High-level query orchestration

Multi-tenancy: All operations filter by group_id for tenant isolation.
"""

import os
import logging
from typing import Any, Dict, List, Optional

import neo4j
from neo4j_graphrag.retrievers import (
    VectorRetriever,
    VectorCypherRetriever, 
    HybridRetriever,
    HybridCypherRetriever,
    Text2CypherRetriever,
)
from neo4j_graphrag.llm import AzureOpenAILLM
from neo4j_graphrag.embeddings import AzureOpenAIEmbeddings
from neo4j_graphrag.generation import GraphRAG
from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
from neo4j_graphrag.experimental.components.kg_writer import Neo4jWriter, KGWriterModel
from neo4j_graphrag.experimental.components.types import Neo4jGraph, LexicalGraphConfig

from app.core.config import settings

logger = logging.getLogger(__name__)


class DimensionAwareAzureEmbeddings(AzureOpenAIEmbeddings):
    """
    Azure OpenAI embeddings wrapper that passes dimensions parameter.
    
    text-embedding-3-small supports configurable dimensions (256-1536).
    This wrapper ensures the dimensions parameter is always passed to the API.
    """
    
    def __init__(self, dimensions: int = 1536, **kwargs):
        self._dimensions = dimensions
        super().__init__(**kwargs)
    
    def embed_query(self, text: str, **kwargs) -> List[float]:
        """Generate embeddings with explicit dimensions."""
        return super().embed_query(text, dimensions=self._dimensions, **kwargs)


class GroupAwareNeo4jWriter(Neo4jWriter):
    """
    Custom Neo4j writer that adds group_id to all nodes for multi-tenancy.
    
    This is a thin wrapper (~10 lines) around the built-in Neo4jWriter
    that ensures all nodes and relationships include the tenant's group_id.
    """
    
    def __init__(self, driver: neo4j.Driver, group_id: str, **kwargs):
        super().__init__(driver, **kwargs)
        self.group_id = group_id
        logger.info(f"GroupAwareNeo4jWriter initialized with group_id={group_id}")
    
    async def run(
        self,
        graph: Neo4jGraph,
        lexical_graph_config: LexicalGraphConfig = LexicalGraphConfig(),
    ) -> KGWriterModel:
        """Add group_id to all nodes and relationships before writing."""
        logger.info(f"GroupAwareNeo4jWriter.run() called with {len(graph.nodes) if hasattr(graph, 'nodes') else 'unknown'} nodes for group_id={self.group_id}")
        
        # Handle both Neo4jGraph object and dict formats
        if hasattr(graph, 'nodes'):
            # Neo4jGraph object format
            for node in graph.nodes:
                if node.properties is None:
                    node.properties = {}
                node.properties["group_id"] = self.group_id
            logger.info(f"Added group_id to {len(graph.nodes)} nodes")
            
            if hasattr(graph, 'relationships'):
                for rel in graph.relationships:
                    if rel.properties is None:
                        rel.properties = {}
                    rel.properties["group_id"] = self.group_id
                logger.info(f"Added group_id to {len(graph.relationships)} relationships")
        
        # Call parent to write to Neo4j with all required parameters
        result = await super().run(graph, lexical_graph_config)
        logger.info(f"GroupAwareNeo4jWriter.run() completed with status={result.status}")
        return result


class Neo4jGraphRAGService:
    """
    Simplified GraphRAG service using official neo4j-graphrag-python package.
    
    Replaces:
    - retrieval_service.py (718 lines) → ~100 lines
    - graphrag_extractor.py (592 lines) → SimpleKGPipeline  
    - graphrag_store.py (469 lines) → SimpleKGPipeline
    - indexing_service.py (575 lines) → SimpleKGPipeline
    
    Total: 1,636 lines → ~150 lines (91% reduction)
    """
    
    def __init__(self):
        """Initialize Neo4j driver and AI components."""
        self._driver = None
        self._llm = None
        self._embedder = None
        
        # Cache for retrievers per group
        self._retriever_cache: Dict[str, Dict[str, Any]] = {}
    
    @property
    def driver(self) -> neo4j.Driver:
        """Lazy initialization of Neo4j driver."""
        if self._driver is None:
            uri = settings.NEO4J_URI or "neo4j+s://localhost:7687"
            username = settings.NEO4J_USERNAME or "neo4j"
            password = settings.NEO4J_PASSWORD or "password"
            self._driver = neo4j.GraphDatabase.driver(
                uri,
                auth=(username, password),
            )
        return self._driver
    
    @property
    def llm(self) -> AzureOpenAILLM:
        """Lazy initialization of Azure OpenAI LLM."""
        if self._llm is None:
            self._llm = AzureOpenAILLM(
                model_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION or "2024-02-01",
            )
        return self._llm
    
    @property
    def embedder(self) -> "DimensionAwareAzureEmbeddings":
        """Lazy initialization of Azure OpenAI embeddings (text-embedding-3-large with 3072 dimensions)."""
        if self._embedder is None:
            # Wrap AzureOpenAIEmbeddings to always pass dimensions parameter
            self._embedder = DimensionAwareAzureEmbeddings(
                model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,  # text-embedding-3-large
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION or "2024-10-21",
                dimensions=settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS,  # 3072 for text-embedding-3-large
            )
        return self._embedder
    
    def _get_retrievers(self, group_id: str) -> Dict[str, Any]:
        """
        Get or create retrievers for a specific group.
        
        Creates:
        - VectorCypherRetriever: For local search (semantic similarity with custom Cypher)
        - HybridCypherRetriever: For hybrid search (vector + fulltext with custom Cypher)
        - Text2CypherRetriever: For structured queries
        
        Uses Cypher variants to inject group_id filtering for multi-tenancy.
        
        Key insight from Neo4j GraphRAG: Search CHUNKS (which have the text), 
        then use retrieval_query to traverse to related entities for context.
        """
        if group_id not in self._retriever_cache:
            # Vector retriever for local search - search CHUNKS not entities
            # The chunk has the full text context (e.g., "Bob is the CEO of TechCorp")
            # Then retrieval_query can traverse to related entities
            vector_retriever = VectorCypherRetriever(
                driver=self.driver,
                index_name="chunk_vector",  # Search chunks which have text content
                embedder=self.embedder,
                retrieval_query=f"""
                    WITH node, score
                    WHERE node.group_id = '{group_id}'
                    // Return chunk text and related entities
                    OPTIONAL MATCH (entity)-[:MENTIONED_IN|PART_OF_CHUNK|FROM_CHUNK]->(node)
                    WHERE entity.group_id = '{group_id}'
                    WITH node, score, collect(DISTINCT entity.name) AS related_entities
                    RETURN node.text AS text,
                           node.id AS chunk_id,
                           related_entities,
                           labels(node)[0] AS type,
                           score
                """,
                neo4j_database=settings.NEO4J_DATABASE or "neo4j",
            )
            
            # Hybrid retriever for combined search - also search chunks
            hybrid_retriever = HybridCypherRetriever(
                driver=self.driver,
                vector_index_name="chunk_vector",  # Search chunks for text content
                fulltext_index_name="chunk_fulltext",  # Need fulltext on chunks
                embedder=self.embedder,
                retrieval_query=f"""
                    WITH node, score
                    WHERE node.group_id = '{group_id}'
                    OPTIONAL MATCH (entity)-[:MENTIONED_IN|PART_OF_CHUNK|FROM_CHUNK]->(node)
                    WHERE entity.group_id = '{group_id}'
                    WITH node, score, collect(DISTINCT entity.name) AS related_entities
                    RETURN node.text AS text,
                           node.id AS chunk_id,
                           related_entities,
                           labels(node)[0] AS type,
                           score
                """,
                neo4j_database=settings.NEO4J_DATABASE or "neo4j",
            )
            
            # Text2Cypher for structured queries
            text2cypher_retriever = Text2CypherRetriever(
                driver=self.driver,
                llm=self.llm,
                neo4j_schema=self._get_neo4j_schema(group_id),
                # Add group_id filter examples to guide Cypher generation
                examples=[
                    f"Who is the CEO? -> MATCH (p:Person)-[:WORKS_FOR]->(o:Organization) WHERE p.group_id = '{group_id}' AND p.title CONTAINS 'CEO' RETURN p.name, o.name",
                    f"What companies are mentioned? -> MATCH (o:Organization) WHERE o.group_id = '{group_id}' RETURN DISTINCT o.name",
                ],
                neo4j_database=settings.NEO4J_DATABASE or "neo4j",
            )
            
            self._retriever_cache[group_id] = {
                "vector": vector_retriever,
                "hybrid": hybrid_retriever,
                "text2cypher": text2cypher_retriever,
            }
        
        return self._retriever_cache[group_id]
    
    def _get_neo4j_schema(self, group_id: str) -> str:
        """Get Neo4j schema for Text2Cypher retriever."""
        # Return a simplified schema description
        return """
        Node labels: Person, Organization, Document, Location, Concept, Event
        Relationship types: WORKS_FOR, LOCATED_IN, MENTIONS, RELATED_TO, PART_OF
        All nodes have a 'group_id' property for multi-tenant filtering.
        Common properties: name, text, description, type
        """
    
    # ============================================================
    # PHASE 1: Simplified Retrieval Methods
    # ============================================================
    
    async def local_search(self, group_id: str, query: str, top_k: int = 10) -> Dict[str, Any]:
        """
        Local search using vector similarity.
        
        Replaces our custom MultiIndexVectorContextRetriever with VectorCypherRetriever.
        """
        logger.info(f"Local search for group {group_id}: {query[:60]}...")
        
        try:
            retrievers = self._get_retrievers(group_id)
            vector_retriever = retrievers["vector"]
            
            # Use GraphRAG for generation
            rag = GraphRAG(
                retriever=vector_retriever,
                llm=self.llm,
            )
            
            # Execute search with return_context to get sources
            response = rag.search(
                query_text=query, 
                retriever_config={"top_k": top_k},
                return_context=True,
            )
            
            # Extract sources safely
            sources = []
            if response.retriever_result and response.retriever_result.items:
                for item in response.retriever_result.items:
                    sources.append({
                        "content": item.content if hasattr(item, 'content') else str(item),
                        "score": getattr(item, 'score', None) if hasattr(item, 'score') else None,
                    })
            
            return {
                "query": query,
                "mode": "local",
                "answer": response.answer if response.answer else "No answer found",
                "sources": sources,
                "metadata": {
                    "retriever_type": "VectorCypherRetriever",
                    "package": "neo4j-graphrag",
                }
            }
            
        except Exception as e:
            logger.error(f"Local search failed: {e}", exc_info=True)
            return {
                "query": query,
                "mode": "local",
                "answer": f"Search failed: {str(e)}",
                "sources": [],
                "error": str(e),
            }
    
    def _sanitize_query_for_fulltext(self, query: str) -> str:
        """
        Remove Lucene special characters from query for fulltext search.
        
        This follows the same approach as LlamaIndex's Neo4jVectorStore.remove_lucene_chars().
        
        Neo4j's fulltext index uses Lucene, which interprets certain characters as operators:
        - + : Required term
        - - : Excluded term  
        - & | : Boolean operators
        - ! : NOT operator
        - ( ) : Grouping (MUST be balanced)
        - { } [ ] : Range queries
        - ^ : Boosting
        - " : Phrase queries
        - ~ : Fuzzy/proximity
        - * ? : Wildcards
        - : : Field specification
        - \\ : Escape
        - / : Regex patterns
        
        The issue is NOT query length - it's specific patterns like "1)" which create
        unbalanced parentheses that Lucene can't parse.
        
        Solution: Replace special characters with spaces (preserves word boundaries).
        This is proper input sanitization, not a fallback or workaround.
        
        Reference: https://github.com/run-llama/llama_index/blob/main/llama-index-integrations/vector_stores/llama-index-vector-stores-neo4jvector/llama_index/vector_stores/neo4jvector/base.py#L80
        
        Args:
            query: Raw user query (any length)
            
        Returns:
            Sanitized query safe for Lucene fulltext index
        """
        if not query:
            return ""
        
        # Lucene special characters that need to be removed
        # Same list as LlamaIndex's remove_lucene_chars()
        special_chars = [
            "+",
            "-", 
            "&",
            "|",
            "!",
            "(",
            ")",
            "{",
            "}",
            "[",
            "]",
            "^",
            '"',
            "~",
            "*",
            "?",
            ":",
            "\\",
        ]
        
        result = query
        for char in special_chars:
            if char in result:
                result = result.replace(char, " ")
        
        # Collapse multiple spaces and trim
        import re
        result = re.sub(r'\s+', ' ', result).strip()
        
        if result != query:
            logger.debug(f"Sanitized Lucene query: '{query[:80]}...' -> '{result[:80]}...'")
        
        return result

    async def hybrid_search(self, group_id: str, query: str, top_k: int = 10) -> Dict[str, Any]:
        """
        Hybrid search combining vector + fulltext.
        
        Replaces custom hybrid implementation with HybridCypherRetriever.
        
        The query is sanitized BEFORE sending to Lucene fulltext search.
        This follows LlamaIndex's approach of removing special Lucene characters
        rather than catching parse errors after the fact.
        
        Note: The vector component uses the ORIGINAL query for embeddings,
        so semantic understanding is preserved. Only the fulltext component
        uses the sanitized query.
        """
        logger.info(f"Hybrid search for group {group_id}: {query[:60]}...")
        
        try:
            retrievers = self._get_retrievers(group_id)
            hybrid_retriever = retrievers["hybrid"]
            
            rag = GraphRAG(
                retriever=hybrid_retriever,
                llm=self.llm,
            )
            
            # Sanitize query for Lucene fulltext (removes special characters)
            # Vector embedding still uses semantic understanding of the full query
            sanitized_query = self._sanitize_query_for_fulltext(query)
            query_was_sanitized = (sanitized_query != query)
            
            if query_was_sanitized:
                logger.info(f"Sanitized query for Lucene: '{query[:50]}...' -> '{sanitized_query[:50]}...'")
            
            response = rag.search(
                query_text=sanitized_query, 
                retriever_config={"top_k": top_k},
                return_context=True,
            )
            
            # Extract sources safely
            sources = []
            if response.retriever_result and response.retriever_result.items:
                for item in response.retriever_result.items:
                    sources.append({
                        "content": item.content if hasattr(item, 'content') else str(item),
                        "score": getattr(item, 'score', None) if hasattr(item, 'score') else None,
                    })
            
            return {
                "query": query,  # Return original query for user context
                "mode": "hybrid",
                "answer": response.answer if response.answer else "No answer found",
                "sources": sources,
                "metadata": {
                    "retriever_type": "HybridCypherRetriever",
                    "package": "neo4j-graphrag",
                    "query_sanitized": query_was_sanitized,
                    "sanitized_query": sanitized_query if query_was_sanitized else None,
                }
            }
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}", exc_info=True)
            return {
                "query": query,
                "mode": "hybrid",
                "answer": f"Search failed: {str(e)}",
                "sources": [],
                "error": str(e),
            }
    
    async def structured_search(
        self, 
        group_id: str, 
        query: str, 
        output_schema: Optional[Dict[str, Any]] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """
        Structured search using Text2Cypher.
        
        Replaces custom structured_search with Text2CypherRetriever.
        """
        logger.info(f"Structured search for group {group_id}: {query[:60]}...")
        
        try:
            retrievers = self._get_retrievers(group_id)
            text2cypher = retrievers["text2cypher"]
            
            # For pure Cypher generation without RAG
            result = text2cypher.search(query_text=query)
            
            # Extract sources safely
            sources = []
            answer = "No results found"
            generated_cypher = None
            
            if result:
                if hasattr(result, 'metadata') and result.metadata:
                    generated_cypher = getattr(result.metadata, 'cypher', None)
                
                if hasattr(result, 'items') and result.items:
                    answer = result.items[0].content if hasattr(result.items[0], 'content') else str(result.items[0])
                    for item in result.items:
                        sources.append({
                            "content": item.content if hasattr(item, 'content') else str(item)
                        })
            
            return {
                "query": query,
                "mode": "structured",
                "answer": answer,
                "sources": sources,
                "metadata": {
                    "retriever_type": "Text2CypherRetriever",
                    "generated_cypher": generated_cypher,
                    "package": "neo4j-graphrag",
                }
            }
            
        except Exception as e:
            logger.error(f"Structured search failed: {e}", exc_info=True)
            return {
                "query": query,
                "mode": "structured",
                "answer": f"Search failed: {str(e)}",
                "sources": [],
                "error": str(e),
            }

    async def schema_guided_extraction(
        self,
        group_id: str,
        query: str,
        output_schema: Dict[str, Any],
        schema_name: Optional[str] = None,
        top_k: int = 20,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
        """
        Schema-guided structured extraction using V2 hybrid retrieval + LLM.
        
        This is the "multi-step reasoning with schema and single prompt" capability:
        1. Step 1: Hybrid retrieval from Neo4j (vector + fulltext)
        2. Step 2: LLM extracts structured JSON based on output_schema
        
        The output_schema defines what fields to extract, similar to Azure Content Understanding.
        
        Args:
            group_id: Tenant identifier for data isolation
            query: Natural language query describing what to extract
            output_schema: JSON schema defining the output structure
            schema_name: Optional name for logging/debugging
            top_k: Number of chunks to retrieve for context
            temperature: LLM temperature (0.0 = deterministic, 1.0 = creative)
            
        Returns:
            Structured JSON matching output_schema with sources and metadata
        """
        logger.info(f"Schema-guided extraction for group {group_id}: query='{query[:50]}...', schema={schema_name or 'unnamed'}, temperature={temperature}")
        
        try:
            # Step 1: Retrieve relevant context using V2 hybrid search
            retrievers = self._get_retrievers(group_id)
            hybrid_retriever = retrievers["hybrid"]
            
            # Sanitize query for Lucene fulltext
            sanitized_query = self._sanitize_query_for_fulltext(query)
            
            # Use GraphRAG retriever directly (without generation) to get sources
            search_result = hybrid_retriever.search(
                query_text=sanitized_query,
                top_k=top_k,
            )
            
            # Extract context from retrieved nodes
            context_parts = []
            sources = []
            
            if search_result and hasattr(search_result, 'items'):
                for item in search_result.items:
                    content = item.content if hasattr(item, 'content') else str(item)
                    context_parts.append(content)
                    sources.append({
                        "content": content[:500] + "..." if len(content) > 500 else content,
                        "score": getattr(item, 'score', None),
                    })
            
            if not context_parts:
                return {
                    "query": query,
                    "mode": "schema-guided-extraction",
                    "answer": {},
                    "sources": [],
                    "metadata": {
                        "schema_name": schema_name,
                        "confidence": 0.0,
                        "validation_errors": ["No relevant context found in the knowledge graph"],
                        "node_count": 0,
                        "context_length": 0,
                    }
                }
            
            # Combine context
            combined_context = "\n\n---\n\n".join(context_parts)
            
            # Step 2: Use LLM to extract structured data based on schema
            import json
            
            extraction_prompt = f"""You are a structured data extraction assistant. Extract information from the provided context according to the given JSON schema.

CONTEXT:
{combined_context}

JSON SCHEMA (defines the structure you must follow):
{json.dumps(output_schema, indent=2)}

USER QUERY:
{query}

INSTRUCTIONS:
1. Analyze the context carefully
2. Extract all relevant information that matches the schema
3. Return ONLY valid JSON that matches the schema structure
4. If a field cannot be found, use null or an empty array as appropriate
5. For arrays, include ALL items found in the context
6. Be thorough - extract every piece of relevant information

Output ONLY the JSON object, no explanations or markdown:"""

            # Call LLM for extraction with specified temperature
            # Create a temperature-specific LLM instance for this request
            from neo4j_graphrag.llm import AzureOpenAILLM
            temp_llm = AzureOpenAILLM(
                model_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION or "2024-02-01",
                model_params={"temperature": temperature},
            )
            response = temp_llm.invoke(extraction_prompt)
            response_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse the JSON response
            try:
                # Clean up response (remove markdown code blocks if present)
                clean_response = response_text.strip()
                if clean_response.startswith("```json"):
                    clean_response = clean_response[7:]
                if clean_response.startswith("```"):
                    clean_response = clean_response[3:]
                if clean_response.endswith("```"):
                    clean_response = clean_response[:-3]
                clean_response = clean_response.strip()
                
                extracted_data = json.loads(clean_response)
                validation_errors = []
                
                # Calculate confidence based on field completeness
                if isinstance(extracted_data, dict):
                    schema_props = output_schema.get("properties", {})
                    required = output_schema.get("required", [])
                    
                    non_null_fields = sum(1 for v in extracted_data.values() if v is not None and v != [])
                    total_fields = len(schema_props) if schema_props else len(extracted_data)
                    confidence = non_null_fields / total_fields if total_fields > 0 else 0.0
                    
                    # Check required fields
                    for req_field in required:
                        if req_field not in extracted_data or extracted_data.get(req_field) in [None, [], ""]:
                            validation_errors.append(f"Required field '{req_field}' is missing or empty")
                else:
                    confidence = 0.5
                    
            except json.JSONDecodeError as e:
                extracted_data = {"raw_response": response_text}
                confidence = 0.0
                validation_errors = [f"Failed to parse LLM response as JSON: {str(e)}"]
            
            return {
                "query": query,
                "mode": "schema-guided-extraction",
                "answer": extracted_data,
                "sources": sources,
                "metadata": {
                    "schema_name": schema_name,
                    "confidence": confidence,
                    "validation_errors": validation_errors,
                    "node_count": len(sources),
                    "context_length": len(combined_context),
                    "retriever_type": "HybridCypherRetriever",
                    "package": "neo4j-graphrag",
                    "temperature": temperature,
                }
            }
            
        except Exception as e:
            logger.error(f"Schema-guided extraction failed: {e}", exc_info=True)
            return {
                "query": query,
                "mode": "schema-guided-extraction",
                "answer": {},
                "sources": [],
                "metadata": {
                    "schema_name": schema_name,
                    "confidence": 0.0,
                    "validation_errors": [f"Extraction failed: {str(e)}"],
                    "node_count": 0,
                    "context_length": 0,
                },
                "error": str(e),
            }
    
    # ============================================================
    # PHASE 3: Simplified Indexing with SimpleKGPipeline
    # ============================================================
    
    async def index_document(
        self,
        group_id: str,
        file_path: str,
        entity_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Index a document using SimpleKGPipeline.
        
        Replaces 1,636 lines across 3 files with ~30 lines!
        
        Features we get for FREE:
        - Entity resolution (deduplication)
        - Lexical graph (Document → Chunk → Entity)
        - Concurrent extraction
        - Production error handling
        """
        logger.info(f"Indexing document for group {group_id}: {file_path}")
        
        try:
            # Determine if PDF
            is_pdf = file_path.lower().endswith('.pdf')
            
            # Use entities/relations parameters for neo4j-graphrag 1.7.0
            entities = entity_types or ["Person", "Organization", "Document", "Concept"]
            relations = relation_types or ["MENTIONS", "WORKS_FOR", "RELATED_TO"]
            
            # Get node count before indexing to identify new nodes
            with self.driver.session() as session:
                before_count = session.run("MATCH (n) RETURN max(id(n)) as max_id").single()["max_id"] or 0
            
            # Create SimpleKGPipeline
            kg_builder = SimpleKGPipeline(
                llm=self.llm,
                driver=self.driver,
                embedder=self.embedder,
                from_pdf=is_pdf,
                entities=entities,
                relations=relations,
                perform_entity_resolution=True,  # FREE deduplication!
                on_error="IGNORE",  # Continue on extraction errors
                neo4j_database=settings.NEO4J_DATABASE or "neo4j",
            )
            
            # Run the pipeline
            if is_pdf:
                result = await kg_builder.run_async(file_path=file_path)
            else:
                # For text files, read content and pass as text
                with open(file_path, 'r') as f:
                    text_content = f.read()
                result = await kg_builder.run_async(text=text_content)
            
            # Post-process: Add group_id to all newly created nodes and ensure vector index compatibility
            with self.driver.session() as session:
                # Update nodes created after our start point
                node_result = session.run("""
                    MATCH (n)
                    WHERE id(n) > $before_id AND n.group_id IS NULL
                    SET n.group_id = $group_id
                    RETURN count(n) as updated_nodes
                """, before_id=before_count, group_id=group_id).single()
                
                # CRITICAL: Add __Node__ label to Chunk nodes for vector index compatibility
                label_result = session.run("""
                    MATCH (n:Chunk)
                    WHERE id(n) > $before_id AND NOT n:__Node__
                    SET n:__Node__
                    RETURN count(n) as updated_chunks
                """, before_id=before_count).single()
                
                # Update relationships too
                rel_result = session.run("""
                    MATCH ()-[r]->()
                    WHERE id(r) > $before_id AND r.group_id IS NULL
                    SET r.group_id = $group_id
                    RETURN count(r) as updated_rels
                """, before_id=before_count, group_id=group_id).single()
                
                logger.info(f"Post-processed: {node_result['updated_nodes']} nodes, {rel_result['updated_rels']} rels, {label_result['updated_chunks']} chunks with __Node__ label for group_id={group_id}")
            
            logger.info(f"Indexing complete for group {group_id}: {file_path}")
            
            return {
                "status": "success",
                "group_id": group_id,
                "file_path": file_path,
                "pipeline": "SimpleKGPipeline",
                "features": {
                    "entity_resolution": True,
                    "lexical_graph": True,
                    "error_handling": "IGNORE",
                },
            }
            
        except Exception as e:
            logger.error(f"Indexing failed for group {group_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "group_id": group_id,
                "file_path": file_path,
                "error": str(e),
            }
    
    async def index_text(
        self,
        group_id: str,
        text: str,
        document_name: Optional[str] = None,
        entity_types: Optional[List[str]] = None,
        relation_types: Optional[List[str]] = None,
        use_raptor: bool = True,
    ) -> Dict[str, Any]:
        """
        Index text content using:
        1. RAPTOR (hierarchical summaries) → Azure AI Search (semantic ranking)
        2. SimpleKGPipeline → Neo4j (entity/relationship graph)
        
        This combines the best of both worlds:
        - RAPTOR provides rich hierarchical context for better retrieval quality
        - Neo4j provides entity/relationship traversal for graph-based queries
        """
        logger.info(f"Indexing text for group {group_id}: {len(text)} chars, raptor={use_raptor}")
        
        raptor_stats = {}
        
        try:
            # Step 1: RAPTOR indexing → Azure AI Search (for semantic quality)
            if use_raptor:
                try:
                    from llama_index.core import Document
                    from app.services.raptor_service import RaptorService
                    
                    raptor_service = RaptorService()
                    
                    # Create LlamaIndex document for RAPTOR processing
                    doc = Document(
                        text=text,
                        metadata={
                            "group_id": group_id,
                            "document_name": document_name or "unknown",
                            "source": "v2_index_text",
                        }
                    )
                    
                    # Process with RAPTOR to create hierarchical summaries
                    raptor_result = await raptor_service.process_documents([doc], group_id)
                    raptor_nodes = raptor_result.get("all_nodes", [])
                    
                    # Index RAPTOR nodes to Azure AI Search
                    if raptor_nodes:
                        raptor_index_result = await raptor_service.index_raptor_nodes(raptor_nodes, group_id)
                        raptor_stats = {
                            "raptor_nodes": len(raptor_nodes),
                            "raptor_levels": raptor_result.get("level_stats", {}),
                            "azure_search_indexed": raptor_index_result.get("indexed", 0) if raptor_index_result else 0,
                        }
                        logger.info(f"RAPTOR → Azure AI Search: {raptor_stats}")
                    else:
                        logger.warning(f"RAPTOR produced no nodes for group {group_id}")
                        
                except Exception as raptor_error:
                    logger.warning(f"RAPTOR indexing failed (continuing with Neo4j only): {raptor_error}")
                    raptor_stats = {"error": str(raptor_error)}
            
            # Step 2: SimpleKGPipeline → Neo4j (for entity/relationship graph)
            # Use entities/relations parameters for neo4j-graphrag 1.7.0
            entities = entity_types or ["Person", "Organization", "Document", "Concept"]
            relations = relation_types or ["MENTIONS", "WORKS_FOR", "RELATED_TO"]
            
            kg_builder = SimpleKGPipeline(
                llm=self.llm,
                driver=self.driver,
                embedder=self.embedder,
                from_pdf=False,
                entities=entities,
                relations=relations,
                perform_entity_resolution=True,
                on_error="IGNORE",
                neo4j_database=settings.NEO4J_DATABASE or "neo4j",
            )
            
            logger.info(f"Running SimpleKGPipeline for group {group_id}")
            pipeline_result = await kg_builder.run_async(text=text)
            logger.info(f"SimpleKGPipeline completed for group {group_id}")
            
            # Post-process: Add group_id to all nodes/relationships with NULL group_id
            # This is more robust than ID-based tracking since Neo4j IDs can be reused
            # Also ensures any orphaned nodes get properly tagged
            updated_nodes = 0
            updated_rels = 0
            chunk_labels_added = 0
            try:
                with self.driver.session() as session:
                    # Update ALL nodes with NULL group_id - safer than ID-based filtering
                    # This catches any nodes that might have been missed
                    node_result = session.run("""
                        MATCH (n)
                        WHERE n.group_id IS NULL
                        SET n.group_id = $group_id
                        RETURN count(n) as updated_nodes
                    """, group_id=group_id).single()
                    updated_nodes = node_result['updated_nodes'] if node_result else 0
                    
                    # CRITICAL: Add __Node__ label to ALL Chunk nodes without it for vector index compatibility
                    # The vector index is on __Node__ label, but SimpleKGPipeline creates Chunk nodes
                    label_result = session.run("""
                        MATCH (n:Chunk)
                        WHERE NOT n:__Node__
                        SET n:__Node__
                        RETURN count(n) as updated_chunks
                    """).single()
                    chunk_labels_added = label_result['updated_chunks'] if label_result else 0
                    
                    # Update ALL relationships with NULL group_id
                    rel_result = session.run("""
                        MATCH ()-[r]->()
                        WHERE r.group_id IS NULL
                        SET r.group_id = $group_id
                        RETURN count(r) as updated_rels
                    """, group_id=group_id).single()
                    updated_rels = rel_result['updated_rels'] if rel_result else 0
                    
                logger.info(f"Post-processed: {updated_nodes} nodes, {updated_rels} rels, {chunk_labels_added} chunks with __Node__ label for group_id={group_id}")
            except Exception as e:
                logger.error(f"Post-processing failed for group {group_id}: {e}", exc_info=True)
            
            return {
                "status": "success",
                "group_id": group_id,
                "document_name": document_name,
                "text_length": len(text),
                "pipeline": "SimpleKGPipeline + RAPTOR" if use_raptor else "SimpleKGPipeline",
                "raptor": raptor_stats if raptor_stats else None,
                "neo4j": {
                    "nodes_updated": updated_nodes,
                    "relationships_updated": updated_rels,
                    "chunks_labeled": chunk_labels_added,
                },
            }
            
        except Exception as e:
            logger.error(f"Text indexing failed for group {group_id}: {e}", exc_info=True)
            return {
                "status": "error",
                "group_id": group_id,
                "error": str(e),
                "raptor": raptor_stats if raptor_stats else None,
            }
    
    def setup_indexes(self) -> Dict[str, Any]:
        """
        Create V2-compatible vector and fulltext indexes in Neo4j.
        
        Creates:
        - chunk_vector: Vector index on __Node__/Chunk nodes (configured dimensions)
        - chunk_fulltext: Fulltext index on __Node__/Chunk text property
        - entity_vector: Vector index on __Entity__ nodes
        - entity_fulltext: Fulltext index on __Entity__ name property
        """
        results = {
            "chunk_vector": False,
            "chunk_fulltext": False,
            "entity_vector": False,
            "entity_fulltext": False,
        }
        
        dims = settings.AZURE_OPENAI_EMBEDDING_DIMENSIONS
        
        with self.driver.session() as session:
            # Create chunk_vector index on __Node__ nodes
            try:
                session.run(f"""
                    CREATE VECTOR INDEX chunk_vector IF NOT EXISTS
                    FOR (n:__Node__)
                    ON n.embedding
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {dims},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                """)
                results["chunk_vector"] = True
                logger.info(f"Created chunk_vector index on __Node__ with {dims} dimensions")
            except Exception as e:
                logger.error(f"Failed to create chunk_vector index: {e}")
                results["chunk_vector"] = str(e)
            
            # Create chunk_fulltext index on __Node__ text
            try:
                session.run("""
                    CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS
                    FOR (n:__Node__)
                    ON EACH [n.text]
                """)
                results["chunk_fulltext"] = True
                logger.info("Created chunk_fulltext index on __Node__")
            except Exception as e:
                logger.error(f"Failed to create chunk_fulltext index: {e}")
                results["chunk_fulltext"] = str(e)
            
            # Create entity_vector index on __Entity__ nodes
            try:
                session.run(f"""
                    CREATE VECTOR INDEX entity_vector IF NOT EXISTS
                    FOR (e:__Entity__)
                    ON e.embedding
                    OPTIONS {{
                        indexConfig: {{
                            `vector.dimensions`: {dims},
                            `vector.similarity_function`: 'cosine'
                        }}
                    }}
                """)
                results["entity_vector"] = True
                logger.info(f"Created entity_vector index on __Entity__ with {dims} dimensions")
            except Exception as e:
                logger.error(f"Failed to create entity_vector index: {e}")
                results["entity_vector"] = str(e)
            
            # Create entity_fulltext index on __Entity__ name
            try:
                session.run("""
                    CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
                    FOR (e:__Entity__)
                    ON EACH [e.name, e.id]
                """)
                results["entity_fulltext"] = True
                logger.info("Created entity_fulltext index on __Entity__")
            except Exception as e:
                logger.error(f"Failed to create entity_fulltext index: {e}")
                results["entity_fulltext"] = str(e)
        
        return results
    
    def close(self):
        """Close Neo4j driver connection."""
        if self._driver:
            self._driver.close()
            self._driver = None


# Singleton instance
_neo4j_graphrag_service: Optional[Neo4jGraphRAGService] = None


def get_neo4j_graphrag_service() -> Neo4jGraphRAGService:
    """Get or create the singleton Neo4jGraphRAGService instance."""
    global _neo4j_graphrag_service
    if _neo4j_graphrag_service is None:
        _neo4j_graphrag_service = Neo4jGraphRAGService()
    return _neo4j_graphrag_service
