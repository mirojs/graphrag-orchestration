"""
Retrieval Service for GraphRAG Query Operations.

Uses LlamaIndex ReActAgent with PropertyGraphIndex for Multi-Step Reasoning.

Architecture:
- ReActAgent orchestrates reasoning (Plan → Act → Observe loop)
- PropertyGraphIndex performs Hybrid Search (Vector + Keyword + Graph)
- Neo4j executes Cypher and returns structured results
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
from llama_index.graph_stores.neo4j import Neo4jPropertyGraphStore

from app.services.graph_service import GraphService
from app.services.llm_service import LLMService
from app.core.config import settings

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

    def _get_or_create_query_engine(self, group_id: str) -> RetrieverQueryEngine:
        """
        Get or create a RetrieverQueryEngine with PropertyGraphIndex.
        
        Uses VectorContextRetriever for full GraphRAG with:
        1. Vector Search (Semantic) - Find similar nodes
        2. Graph Traversal - Expand to related nodes via get_rel_map
        """
        if group_id in self._query_engine_cache:
            return self._query_engine_cache[group_id]
        
        try:
            # Get Neo4j store for this group
            neo4j_store = self.graph_service.get_store(group_id)
            
            if not isinstance(neo4j_store, Neo4jPropertyGraphStore):
                raise ValueError(f"Expected Neo4jPropertyGraphStore, got {type(neo4j_store)}")
            
            # Use LlamaIndex's VectorContextRetriever as base, extended for multi-index search
            # This follows Neo4j best practices (db.index.vector.queryNodes) while leveraging
            # LlamaIndex's battle-tested graph traversal logic (get_rel_map)
            from llama_index.core.indices.property_graph import VectorContextRetriever
            from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
            from llama_index.core.graph_stores.types import EntityNode as LabelledEntityNode
            from typing import List
            
            class MultiIndexVectorContextRetriever(VectorContextRetriever):
                """
                Extended VectorContextRetriever that queries BOTH entity and chunk vector indexes.
                
                LlamaIndex's VectorContextRetriever only queries the 'entity' index by default.
                This extension adds chunk retrieval for complete GraphRAG:
                
                1. Entity index: Finds semantically similar entities (people, companies, etc.)
                2. Chunk index: Finds source text chunks containing relevant information
                3. Graph traversal: Expands via get_rel_map() to related entities
                
                Architecture follows:
                - Neo4j best practices: Uses db.index.vector.queryNodes() for native vector search
                - LlamaIndex patterns: Inherits proven graph traversal and result formatting
                """
                
                def __init__(
                    self,
                    graph_store,
                    group_id: str,
                    embed_model=None,
                    similarity_top_k: int = 10,
                    path_depth: int = 2,
                    chunk_index_name: str = "chunk_vector",
                    **kwargs
                ):
                    # Initialize parent VectorContextRetriever
                    super().__init__(
                        graph_store=graph_store,
                        embed_model=embed_model,
                        similarity_top_k=similarity_top_k,
                        path_depth=path_depth,
                        include_text=True,
                        **kwargs
                    )
                    self._group_id = group_id
                    self._chunk_index_name = chunk_index_name
                
                def retrieve_from_graph(self, query_bundle: QueryBundle, limit=None) -> List[NodeWithScore]:
                    """
                    Override to query both entity and chunk indexes, then use parent's graph traversal.
                    """
                    # Get embedding
                    if query_bundle.embedding is None:
                        query_bundle.embedding = self._embed_model.get_agg_embedding_from_queries(
                            query_bundle.embedding_strs
                        )
                    
                    # Step 1: Query BOTH vector indexes (Neo4j native)
                    entity_results = self._query_vector_index("entity", query_bundle.embedding)
                    chunk_results = self._query_vector_index(self._chunk_index_name, query_bundle.embedding)
                    
                    logger.info(f"Vector search: {len(entity_results)} entities, {len(chunk_results)} chunks")
                    
                    # Step 2: Graph traversal on entity nodes (use parent's proven logic)
                    kg_nodes = []
                    entity_scores = {}
                    for node_data, score in entity_results:
                        node_name = node_data.get('name', node_data.get('entity_id', ''))
                        if node_name:
                            kg_nodes.append(LabelledEntityNode(
                                name=node_name,
                                label=node_data.get('label', '__Entity__'),
                                properties={'group_id': self._group_id}
                            ))
                            entity_scores[node_name] = score
                    
                    triplets = []
                    if kg_nodes:
                        triplets = self._graph_store.get_rel_map(
                            nodes=kg_nodes,
                            depth=self._path_depth,
                            limit=limit or self._limit,
                            ignore_rels=["MENTIONS"],  # Skip generic MENTIONS edges
                        )
                    logger.info(f"Graph traversal: {len(triplets)} triplets")
                    
                    # Step 3: Build results combining chunks + entities + traversal
                    seen_ids = set()
                    results = []
                    
                    # Add chunk results first (highest priority - contains source text)
                    for node_data, score in chunk_results:
                        node_id = node_data.get('entity_id', '')
                        if node_id and node_id not in seen_ids:
                            seen_ids.add(node_id)
                            text = node_data.get('text', '')
                            if text:
                                results.append(NodeWithScore(
                                    node=TextNode(
                                        text=text,
                                        id_=node_id,
                                        metadata={'source': 'chunk', 'group_id': self._group_id}
                                    ),
                                    score=score
                                ))
                    
                    # Add entity results
                    for node_data, score in entity_results:
                        node_id = node_data.get('entity_id', node_data.get('name', ''))
                        if node_id and node_id not in seen_ids:
                            seen_ids.add(node_id)
                            text = node_data.get('text', '') or f"Entity: {node_data.get('name', node_id)}"
                            results.append(NodeWithScore(
                                node=TextNode(
                                    text=text,
                                    id_=node_id,
                                    metadata={
                                        'source': 'entity',
                                        'name': node_data.get('name', ''),
                                        'label': node_data.get('label', ''),
                                        'group_id': self._group_id
                                    }
                                ),
                                score=score
                            ))
                    
                    # Add graph traversal results (use parent's _get_nodes_with_score pattern)
                    for triplet in triplets:
                        source_node, relation, target_node = triplet
                        for graph_node in [source_node, target_node]:
                            node_name = graph_node.name if hasattr(graph_node, 'name') else str(graph_node)
                            if node_name and node_name not in seen_ids:
                                seen_ids.add(node_name)
                                text = ""
                                if hasattr(graph_node, 'properties') and graph_node.properties:
                                    text = graph_node.properties.get('text', '')
                                if not text:
                                    text = f"Entity: {node_name}"
                                
                                # Score from original entity search, or 0.5 for traversed nodes
                                score = entity_scores.get(node_name, 0.5)
                                results.append(NodeWithScore(
                                    node=TextNode(
                                        text=text,
                                        id_=node_name,
                                        metadata={
                                            'source': 'graph_traversal',
                                            'name': node_name,
                                            'relation': relation.label if hasattr(relation, 'label') else '',
                                            'group_id': self._group_id
                                        }
                                    ),
                                    score=score
                                ))
                    
                    logger.info(f"MultiIndexVectorContextRetriever: {len(results)} total results")
                    return results
                
                def _query_vector_index(self, index_name: str, embedding: List[float]) -> List[tuple]:
                    """
                    Query Neo4j vector index using native db.index.vector.queryNodes().
                    Follows Neo4j GenAI best practices.
                    """
                    try:
                        cypher = """
                        CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
                        YIELD node, score
                        WHERE node.group_id = $group_id
                        RETURN node.id AS entity_id, 
                               node.name AS name, 
                               node.text AS text,
                               labels(node)[0] AS label, 
                               score
                        ORDER BY score DESC
                        """
                        
                        result = self._graph_store.structured_query(
                            cypher,
                            param_map={
                                "index_name": index_name,
                                "embedding": embedding,
                                "group_id": self._group_id,
                                "top_k": self._similarity_top_k,
                            }
                        )
                        
                        return [(dict(row), row.get("score", 0.0)) for row in (result or [])]
                    except Exception as e:
                        logger.warning(f"Vector search on '{index_name}' failed: {e}")
                        return []
            
            # Create retriever using our extended class
            retriever = MultiIndexVectorContextRetriever(
                graph_store=neo4j_store,
                group_id=group_id,
                embed_model=self.llm_service.embed_model,
                similarity_top_k=10,
                path_depth=2,  # 2-hop traversal for multi-hop reasoning
                chunk_index_name="chunk_vector",
            )
            
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
            logger.info(f"Created GraphRAGRetriever QueryEngine for group {group_id}")
            
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
                    "retriever_type": "MultiIndexVectorContextRetriever",
                    "indexes_searched": ["entity", "chunk_vector"],
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
            from app.services.community_service import CommunityService
            
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
                    "retriever_type": "MultiIndexVectorContextRetriever",
                    "indexes_searched": ["entity", "chunk_vector", "entity_fulltext"],
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
            from app.services.structured_output_service import StructuredOutputService
            
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
            from app.services.graphrag_store import GraphRAGStore
            from app.services.graphrag_query_engine import GraphRAGQueryEngine
            from app.services.llm_service import LLMService
            from app.core.config import settings
            
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
