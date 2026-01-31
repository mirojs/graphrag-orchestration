"""
Retrieval Service for GraphRAG Query Operations.

Phase 1 Migration: Now uses native neo4j-graphrag VectorCypherRetriever instead of
custom LlamaIndex MultiIndexVectorContextRetriever. This reduces code complexity and
leverages official Neo4j GraphRAG package for vector + Cypher retrieval.

Architecture:
- ReActAgent orchestrates reasoning (Plan → Act → Observe loop)
- VectorCypherRetriever performs Vector Search with custom Cypher for graph context
- Neo4j executes optimized Cypher and returns structured results
- Agent iteratively reasons and synthesizes results across multi-hop queries

This enables true multi-step reasoning where the agent can:
1. Decompose complex questions into sub-steps
2. Use the knowledge_graph_tool iteratively
3. Combine results to answer the original question

Schema-Guided Structured Retrieval:
- PRIMARY schema use case: output_schema at query time
- User provides JSON schema (e.g., {"vendor": str, "amount": float})
- GraphRAG retrieves context, LLM extracts structured JSON
"""

import re
from typing import List, Optional, Dict, Any
import logging
import asyncio
from fastapi import HTTPException

from llama_index.core.agent import ReActAgent
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import QueryEngineTool
from llama_index.core import PropertyGraphIndex
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.schema import TextNode, NodeWithScore

# neo4j-graphrag native retrievers (Phase 1 migration)
from neo4j_graphrag.retrievers import VectorCypherRetriever
from neo4j_graphrag.embeddings import AzureOpenAIEmbeddings

from src.worker.services.graph_service import GraphService, MultiTenantNeo4jStore
from src.worker.services.llm_service import LLMService
from src.core.config import settings

logger = logging.getLogger(__name__)

class RetrievalService:
    """
    Service for retrieving information from the Knowledge Graph using ReActAgent.
    
    Uses ReActAgent with PropertyGraphIndex for true multi-step reasoning:
    - Agent breaks down complex queries and creates a plan
    - Agent iteratively uses the knowledge_graph_tool to query Neo4j
    - Agent observes results and refines its approach
    - Final response synthesizes all multi-step reasoning
    
    Note: All query-time operations use Neo4j (vectors + full-text + graph traversal).
    Azure AI Search is used separately during indexing for RAPTOR summaries storage.
    """
    
    def __init__(self):
        self.graph_service = GraphService()
        self.llm_service = LLMService()
        
        # Cache for query engines per group
        self._query_engine_cache: Dict[str, RetrieverQueryEngine] = {}
        # Cache for agents per group
        self._agent_cache: Dict[str, ReActAgent] = {}
        # Cache for native neo4j-graphrag retrievers
        self._native_retriever_cache: Dict[str, VectorCypherRetriever] = {}
        # Neo4j driver (shared across retrievers)
        self._neo4j_driver = None
        # Native embedder for neo4j-graphrag
        self._native_embedder = None

    def _get_neo4j_driver(self):
        """Get or create Neo4j driver for native retrievers."""
        if self._neo4j_driver is None:
            import neo4j
            self._neo4j_driver = neo4j.GraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
            )
        return self._neo4j_driver
    
    def _get_native_embedder(self):
        """Get or create native neo4j-graphrag embedder."""
        if self._native_embedder is None:
            self._native_embedder = AzureOpenAIEmbeddings(
                model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_key=settings.AZURE_OPENAI_API_KEY,
                api_version=settings.AZURE_OPENAI_API_VERSION or "2024-10-21",
            )
        return self._native_embedder

    def _get_native_retriever(self, group_id: str) -> VectorCypherRetriever:
        """
        Get or create a native neo4j-graphrag VectorCypherRetriever.
        
        Phase 1 Migration: Replaces custom MultiIndexVectorContextRetriever (180+ lines)
        with native VectorCypherRetriever (~20 lines of config).
        
        Features:
        - Vector similarity search on chunk embeddings
        - Custom Cypher for graph traversal to related entities
        - Multi-tenant filtering via group_id
        """
        if group_id in self._native_retriever_cache:
            return self._native_retriever_cache[group_id]
        
        retriever = VectorCypherRetriever(
            driver=self._get_neo4j_driver(),
            index_name="chunk_embedding",  # Vector index on TextChunk.embedding
            embedder=self._get_native_embedder(),
            retrieval_query="""
                WITH node, score
                WHERE node.group_id = $group_id
                // Get chunk text and traverse to related entities
                OPTIONAL MATCH (entity)-[:MENTIONED_IN|PART_OF_CHUNK|FROM_CHUNK]->(node)
                WHERE entity.group_id = $group_id
                WITH node, score, collect(DISTINCT entity.name) AS related_entities
                RETURN node.text AS text,
                       node.id AS chunk_id,
                       related_entities,
                       labels(node)[0] AS type,
                       score
            """,
            neo4j_database=settings.NEO4J_DATABASE or "neo4j",
        )
        
        self._native_retriever_cache[group_id] = retriever
        logger.info(f"Created native VectorCypherRetriever for group {group_id}")
        return retriever

    def _get_or_create_query_engine(self, group_id: str) -> RetrieverQueryEngine:
        """
        Get or create a RetrieverQueryEngine with native neo4j-graphrag retriever.
        
        Phase 1 Migration: Uses VectorCypherRetriever (native) for:
        1. Vector Search (Semantic) - Find similar chunks
        2. Graph Traversal - Expand to related entities via Cypher
        """
        if group_id in self._query_engine_cache:
            return self._query_engine_cache[group_id]
        
        try:
            # Get native retriever (Phase 1 migration)
            native_retriever = self._get_native_retriever(group_id)
            
            # Create a LlamaIndex-compatible wrapper for the native retriever
            class NativeRetrieverWrapper:
                """Wrapper to make neo4j-graphrag retriever compatible with LlamaIndex query engine."""
                
                def __init__(self, native_retriever, group_id, llm_service):
                    self._native = native_retriever
                    self._group_id = group_id
                    self._llm_service = llm_service
                
                def retrieve(self, query_bundle):
                    """Retrieve nodes using native neo4j-graphrag retriever."""
                    from llama_index.core.schema import QueryBundle
                    
                    query_text = query_bundle.query_str if hasattr(query_bundle, 'query_str') else str(query_bundle)
                    
                    # Use native retriever (returns RawSearchResult with Neo4j records)
                    logger.info(f"Native retriever searching for: '{query_text[:50]}...'")
                    result = self._native.search(
                        query_text=query_text,
                        top_k=10,
                        effective_search_ratio=10,
                        query_params={"group_id": self._group_id},
                        filters={"group_id": self._group_id},
                    )
                    
                    # Convert Neo4j records to LlamaIndex NodeWithScore format
                    nodes = []
                    if result and result.records:
                        for record in result.records:
                            # Extract fields from Neo4j record based on retrieval_query
                            text = record.get('text', '')
                            chunk_id = record.get('chunk_id', '')
                            score = record.get('score', 0.0)
                            related_entities = record.get('related_entities', [])
                            
                            if text:
                                nodes.append(NodeWithScore(
                                    node=TextNode(
                                        text=text,
                                        id_=chunk_id,
                                        metadata={
                                            'source': 'native_vector_cypher',
                                            'group_id': self._group_id,
                                            'related_entities': related_entities,
                                        }
                                    ),
                                    score=float(score) if score else 0.0
                                ))
                    
                    logger.info(f"Native retriever returned {len(nodes)} nodes")
                    return nodes
            
            # Create retriever wrapper
            retriever = NativeRetrieverWrapper(native_retriever, group_id, self.llm_service)
            
            # Create query engine with our retriever
            from llama_index.core.response_synthesizers import get_response_synthesizer
            
            response_synthesizer = get_response_synthesizer(
                llm=self.llm_service.llm,
                response_mode="compact",  # Combine all retrieved text
            )
            
            query_engine = RetrieverQueryEngine(
                retriever=retriever,
                response_synthesizer=response_synthesizer,
            )
            
            # Cache it
            self._query_engine_cache[group_id] = query_engine
            logger.info(f"Created native VectorCypherRetriever QueryEngine for group {group_id}")
            
            return query_engine
            
        except Exception as e:
            logger.error(f"Failed to create query engine for group {group_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to initialize knowledge graph: {str(e)}"
            )

    def _get_or_create_agent(self, group_id: str) -> ReActAgent:
        """
        Get or create a ReActAgent for multi-step reasoning.
        """
        if group_id in self._agent_cache:
            return self._agent_cache[group_id]
        
        try:
            query_engine = self._get_or_create_query_engine(group_id)
            
            # Wrap query engine as a tool for the agent
            kg_tool = QueryEngineTool.from_defaults(
                query_engine=query_engine,
                name="knowledge_graph_tool",
                description=(
                    "Use this tool to retrieve information from the uploaded documents and files. "
                    "ALWAYS use this tool to answer questions about people, companies, contracts, "
                    "invoices, or any other entities mentioned in documents. "
                    "The tool searches the knowledge graph for relevant information."
                ),
            )
            
            # Use FunctionAgent for LLMs with native function calling (OpenAI, Azure OpenAI)
            # This is more reliable than ReActAgent for tool invocation
            # FunctionAgent uses the LLM's native tool/function calling API
            llm = self.llm_service.llm
            
            # Check if LLM supports function calling
            if hasattr(llm, 'metadata') and hasattr(llm.metadata, 'is_function_calling_model') and llm.metadata.is_function_calling_model:
                agent = FunctionAgent(
                    tools=[kg_tool],
                    llm=llm,
                    system_prompt=(
                        "You are a helpful assistant that answers questions using the knowledge graph. "
                        "ALWAYS use the knowledge_graph_tool to search for information before answering. "
                        "Do not rely on prior knowledge - only use information from the tool."
                    ),
                    # Force the tool to be called on first turn
                    initial_tool_choice="knowledge_graph_tool",
                )
                logger.info(f"Created FunctionAgent (native tool calling) for group {group_id}")
            else:
                # Fallback to ReActAgent for non-function-calling LLMs
                agent = ReActAgent(
                    tools=[kg_tool],
                    llm=llm,
                    verbose=True,
                    max_iterations=10
                )
                logger.info(f"Created ReActAgent (text-based) for group {group_id}")
            
            # Cache it
            self._agent_cache[group_id] = agent
            logger.info(f"Created ReActAgent with PropertyGraphIndex tool for group {group_id}")
            
            return agent
            
        except Exception as e:
            logger.error(f"Failed to create agent for group {group_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create reasoning agent: {str(e)}"
            )

    async def query(
        self,
        group_id: str,
        query_text: str,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """
        Execute multi-step reasoning query using ReActAgent.
        """
        logger.info(f"Multi-step reasoning query for group {group_id}: {query_text[:60]}...")
        
        try:
            agent = self._get_or_create_agent(group_id)
            
            # Execute query with agent
            logger.info(f"Executing ReActAgent query: {query_text}")
            # Workflow-based agent uses .run() and is async
            response = await agent.run(user_msg=query_text)
            
            # Extract response
            answer = str(response) if response else "No answer found"
            
            return {
                "query": query_text,
                "mode": "react-agent-multi-step",
                "answer": answer,
                "sources": [],
                "metadata": {
                    "agent_type": "ReActAgent",
                    "tool": "knowledge_graph_tool",
                    "reasoning_type": "multi-step-planning-acting-observing"
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Query failed for group {group_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Query execution failed: {str(e)}"
            )

    async def local_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """
        Local search: Vector similarity + graph traversal retrieval.
        Uses query_engine directly (no agent wrapper needed for simple retrieval).
        """
        logger.info(f"Local search for group {group_id}: {query[:60]}...")
        
        try:
            query_engine = self._get_or_create_query_engine(group_id)
            
            # Direct query - no agent overhead
            response = query_engine.query(query)
            
            # Extract source nodes for provenance
            sources = []
            if hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    sources.append({
                        "node_id": node.node_id,
                        "score": node.score if hasattr(node, 'score') else None,
                        "text": node.text[:200] if hasattr(node, 'text') else str(node)[:200],
                    })
            
            return {
                "query": query,
                "mode": "local",
                "answer": str(response),
                "sources": sources,
                "metadata": {
                    "retriever_type": "VectorCypherRetriever",
                    "package": "neo4j-graphrag",
                    "indexes_searched": ["chunk_vector"],
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Local search failed for group {group_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Local search failed: {str(e)}"
            )

    async def global_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """
        Global search: Community-based map-reduce over knowledge graph.
        
        Uses GraphRAG v2 pattern:
        1. Retrieves community summaries
        2. Generates answer from each community (map)
        3. Aggregates into final response (reduce)
        
        Best for broad questions like "What are the main themes?" or "Give me an overview"
        """
        logger.info(f"Global search for group {group_id}: {query[:60]}...")
        
        try:
            from src.worker.services.community_service import CommunityService
            
            community_service = CommunityService()
            
            # Get community summaries (builds them if not cached)
            summaries = community_service.get_community_summaries(group_id)
            
            if not summaries:
                # No communities yet - fall back to local search
                logger.warning(f"No community summaries for group {group_id}, falling back to local search")
                return await self.local_search(group_id, query, **kwargs)
            
            # Perform global search using community map-reduce
            answer = await community_service.global_search(group_id, query)
            
            return {
                "query": query,
                "mode": "global",
                "answer": answer,
                "sources": [{"type": "community_summaries", "count": len(summaries)}],
                "metadata": {
                    "search_type": "community_map_reduce",
                    "communities_queried": len(summaries),
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Global search failed for group {group_id}: {e}", exc_info=True)
            # Fall back to local search on error
            logger.info(f"Falling back to local search due to global search error")
            return await self.local_search(group_id, query, **kwargs)

    async def hybrid_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """
        Hybrid search: Combines vector + fulltext + graph traversal.
        Uses query_engine directly with fulltext enhancement.
        """
        logger.info(f"Hybrid search for group {group_id}: {query[:60]}...")
        
        try:
            query_engine = self._get_or_create_query_engine(group_id)
            
            # Direct query - the MultiIndexVectorContextRetriever already does hybrid
            response = query_engine.query(query)
            
            # Extract source nodes for provenance
            sources = []
            if hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    sources.append({
                        "node_id": node.node_id,
                        "score": node.score if hasattr(node, 'score') else None,
                        "text": node.text[:200] if hasattr(node, 'text') else str(node)[:200],
                    })
            
            return {
                "query": query,
                "mode": "hybrid",
                "answer": str(response),
                "sources": sources,
                "metadata": {
                    "retriever_type": "VectorCypherRetriever",
                    "package": "neo4j-graphrag",
                    "indexes_searched": ["chunk_vector"],
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Hybrid search failed for group {group_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Hybrid search failed: {str(e)}"
            )

    async def drift_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """Drift search: Currently uses local search as base."""
        return await self.local_search(group_id, query, **kwargs)

    async def text_to_cypher_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """Text-to-Cypher: Currently uses local search as base."""
        return await self.local_search(group_id, query, **kwargs)

    async def structured_search(
        self, 
        group_id: str, 
        query: str, 
        output_schema: Dict[str, Any],
        schema_name: Optional[str] = None,
        top_k: int = 10,
        **kwargs
    ) -> Dict[str, Any]:
        """
        PRIMARY SCHEMA USE CASE: Schema-guided structured retrieval.
        
        This is the main way schemas should be used - at RETRIEVAL time to
        produce structured JSON output matching the user's schema.
        
        Flow:
        1. GraphRAG retrieves relevant context (vector + graph traversal)
        2. LLM extracts structured data from context using the schema
        3. Output is validated against the schema
        4. Returns structured JSON with provenance
        
        Args:
            group_id: Tenant identifier
            query: Natural language query (e.g., "Extract invoice details")
            output_schema: JSON schema defining expected output structure
            schema_name: Optional name for logging/debugging
            top_k: Number of nodes to retrieve
            
        Returns:
            Dict with structured extraction results
        """
        logger.info(f"Structured search for group {group_id}: query='{query[:50]}...', schema={schema_name or 'unnamed'}")
        
        try:
            # Import here to avoid circular imports
            from src.worker.services.structured_output_service import StructuredOutputService
            
            # Step 1: Retrieve relevant nodes using GraphRAG
            query_engine = self._get_or_create_query_engine(group_id)
            
            # Get the retriever from the query engine
            retriever = query_engine.retriever
            
            # Build query bundle
            from llama_index.core.schema import QueryBundle
            query_bundle = QueryBundle(query_str=query)
            
            # Retrieve nodes
            retrieved_nodes = retriever.retrieve(query_bundle)
            logger.info(f"Retrieved {len(retrieved_nodes)} nodes for structured extraction")
            
            # Step 2: Extract structured data using the schema
            structured_service = StructuredOutputService(llm=self.llm_service.llm)
            result = await structured_service.extract_structured(
                query=query,
                retrieved_nodes=retrieved_nodes,
                output_schema=output_schema,
                schema_name=schema_name,
            )
            
            # Step 3: Format response
            return {
                "query": result.query,
                "mode": "structured-extraction",
                "answer": result.extracted_data,  # The structured JSON
                "sources": result.sources,
                "metadata": {
                    "schema_name": result.schema_name,
                    "confidence": result.confidence,
                    "validation_errors": result.validation_errors,
                    "node_count": result.metadata.get("node_count", 0),
                    "context_length": result.metadata.get("context_length", 0),
                }
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Structured search failed for group {group_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Structured extraction failed: {str(e)}"
            )

    async def comparison_search(self, group_id: str, query: str, **kwargs) -> Dict[str, Any]:
        """
        Perform a comparison search to find inconsistencies across documents.
        
        This uses the GraphRAGQueryEngine's comparison_query method to analyze
        community summaries and find discrepancies, contradictions, or differences.
        
        Best for:
        - "Compare the payment terms across contracts"
        - "Find inconsistencies between the invoice and purchase order"
        - "What are the differences between vendor proposals?"
        
        Args:
            group_id: Tenant identifier
            query: Natural language query asking for comparison/inconsistencies
            
        Returns:
            Dict with query results including identified inconsistencies
        """
        try:
            from src.worker.services.graphrag_store import GraphRAGStore
            from src.worker.services.graphrag_query_engine import GraphRAGQueryEngine
            from src.worker.services.llm_service import LLMService
            from src.core.config import settings
            
            # Initialize GraphRAG store for this group
            graph_store = GraphRAGStore(
                group_id=group_id,
                username=settings.NEO4J_USERNAME,
                password=settings.NEO4J_PASSWORD,
                url=settings.NEO4J_URI,
                database=settings.NEO4J_DATABASE,
            )
            
            # Load communities (from cache or Neo4j)
            graph_store.load_communities_from_neo4j()
            
            if not graph_store.community_summary:
                return {
                    "query": query,
                    "mode": "comparison",
                    "answer": "No community summaries available. Please run community detection first by indexing documents with run_community_detection=True.",
                    "sources": [],
                    "inconsistencies_found": 0,
                }
            
            # Initialize query engine
            llm_service = LLMService()
            query_engine = GraphRAGQueryEngine(
                graph_store=graph_store,
                llm=llm_service.llm,
            )
            
            # Run comparison query
            answer = query_engine.comparison_query(query)
            
            # Count inconsistencies mentioned in the answer
            inconsistency_count = answer.lower().count("inconsisten") + answer.lower().count("discrepan") + answer.lower().count("contradict")
            
            return {
                "query": query,
                "mode": "comparison",
                "answer": answer,
                "sources": [],
                "community_count": len(graph_store.community_summary),
                "inconsistencies_found": inconsistency_count,
            }
            
        except Exception as e:
            logger.error(f"Comparison search failed: {e}")
            return {
                "query": query,
                "mode": "comparison",
                "answer": f"Comparison search failed: {str(e)}",
                "sources": [],
                "error": str(e),
            }
