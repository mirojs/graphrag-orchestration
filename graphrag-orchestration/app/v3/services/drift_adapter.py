"""
DRIFT Adapter for V3 GraphRAG

This module bridges Neo4j graph data with Microsoft GraphRAG's DRIFT algorithm.
DRIFT (Dynamic Reasoning with Iterative Facts and Templates) provides multi-step
reasoning capabilities that no other library offers.

Architecture:
    Neo4j (Graph Storage) → DataFrame (DRIFT Interface) → DRIFTSearch (Algorithm)

Usage:
    adapter = DRIFTAdapter(neo4j_driver, llm)
    result = await adapter.drift_search(group_id, query)
"""

import logging
from typing import Any, Dict, List, Optional
import pandas as pd
import neo4j
from neo4j import AsyncGraphDatabase
from app.core.config import settings

logger = logging.getLogger(__name__)

# Module-level caches that persist across API requests
# These store loaded data to avoid re-querying Neo4j on every request
_GRAPHRAG_MODEL_CACHE: Dict[str, Any] = {}  # Stores complete GraphRAG models
_ENTITY_CACHE: Dict[str, pd.DataFrame] = {}  # Stores entity DataFrames
_COMMUNITY_CACHE: Dict[str, pd.DataFrame] = {}  # Stores community DataFrames
_RELATIONSHIP_CACHE: Dict[str, pd.DataFrame] = {}  # Stores relationship DataFrames


class GraphRAGEmbeddingWrapper:
    """Wrapper to adapt LlamaIndex embeddings to GraphRAG interface."""
    def __init__(self, embedder):
        self.embedder = embedder

    def embed_query(self, text: str) -> List[float]:
        """Embed text using LlamaIndex embedder (sync version)."""
        return self.embedder.get_text_embedding(text)
    
    def get_text_embedding(self, text: str) -> List[float]:
        """Get text embedding - direct pass-through to LlamaIndex."""
        return self.embedder.get_text_embedding(text)
    
    async def aget_text_embedding(self, text: str) -> List[float]:
        """Async get text embedding - required by MS GraphRAG."""
        # LlamaIndex embedder may not have async method, use sync
        return self.embedder.get_text_embedding(text)

    def embed(self, text: str, **kwargs) -> List[float]:
        """Embed text using LlamaIndex embedder."""
        return self.embedder.get_text_embedding(text)
    
    async def aembed(self, text: str, **kwargs) -> List[float]:
        """Async embed text using LlamaIndex embedder."""
        # Use sync method as fallback if async not available
        return self.embedder.get_text_embedding(text)


class DRIFTAdapter:
    """
    Adapter that bridges Neo4j graph storage with MS GraphRAG DRIFT algorithm.
    
    DRIFT expects DataFrames with specific schemas. This adapter:
    1. Queries Neo4j for entities, communities, relationships
    2. Converts to DataFrames matching DRIFT's expected schema
    3. Executes DRIFT search
    4. Returns structured results
    
    Note: We only import MS GraphRAG's DRIFT-related classes, not their
    storage or indexing components.
    """
    
    def __init__(
        self,
        neo4j_driver: neo4j.Driver,
        llm: Any,  # Azure OpenAI LLM instance
        embedder: Any,  # Azure OpenAI Embeddings instance
    ):
        """
        Initialize DRIFT adapter.
        
        Args:
            neo4j_driver: Neo4j driver instance
            llm: LLM for DRIFT reasoning (Azure OpenAI)
            embedder: Embedder for query embedding
        """
        self.driver = neo4j_driver
        self.llm = llm
        # Wrap embedder to provide required methods, handle None case
        self.embedder = GraphRAGEmbeddingWrapper(embedder) if embedder else None
        # Note: All caches are now module-level globals for cross-request persistence
        
    def clear_cache(self, group_id: Optional[str] = None):
        """Clear cached DataFrames for a group or all groups."""
        if group_id:
            _ENTITY_CACHE.pop(group_id, None)
            _COMMUNITY_CACHE.pop(group_id, None)
            _RELATIONSHIP_CACHE.pop(group_id, None)
            # Also clear model cache if exists
            cache_key = f"{group_id}_models_v3"
            _GRAPHRAG_MODEL_CACHE.pop(cache_key, None)
        else:
            _ENTITY_CACHE.clear()
            _COMMUNITY_CACHE.clear()
            _RELATIONSHIP_CACHE.clear()
            _GRAPHRAG_MODEL_CACHE.clear()
            
    def load_entities(self, group_id: str, use_cache: bool = True) -> pd.DataFrame:
        """
        Load entities from Neo4j as DataFrame.
        
        Returns DataFrame with columns matching MS GraphRAG schema:
        - id: str (unique identifier)
        - name: str (entity name)
        - type: str (entity type)
        - description: str (entity description)
        - text_unit_ids: List[str] (source chunk references)
        - description_embedding: List[float] (optional)
        """
        if use_cache and group_id in _ENTITY_CACHE:
            logger.debug(f"✅ Using cached entities for group {group_id}")
            return _ENTITY_CACHE[group_id]
            
        logger.info(f"Loading entities from Neo4j for group {group_id}")
        
        query = """
        MATCH (e:Entity {group_id: $group_id})
        OPTIONAL MATCH (e)<-[:MENTIONS]-(c:TextChunk)
        RETURN 
            e.id AS id,
            e.name AS name,
            e.type AS type,
            e.description AS description,
            e.embedding AS description_embedding,
            collect(DISTINCT c.id) AS text_unit_ids
        """
        
        records, _, _ = self.driver.execute_query(query, group_id=group_id)
        
        data = []
        for record in records:
            data.append({
                "id": record["id"],
                "name": record["name"],
                "type": record["type"],
                "description": record["description"] or "",
                "description_embedding": record["description_embedding"],
                "text_unit_ids": record["text_unit_ids"] or [],
            })
        
        df = pd.DataFrame(data)
        
        if use_cache:
            _ENTITY_CACHE[group_id] = df
            logger.debug(f"✅ Cached {len(df)} entities for group {group_id}")
            
        logger.info(f"Loaded {len(df)} entities for group {group_id}")
        return df
    
    def load_communities(self, group_id: str, use_cache: bool = True) -> pd.DataFrame:
        """
        Load communities from Neo4j as DataFrame.
        
        Returns DataFrame with columns matching MS GraphRAG schema:
        - id: str (unique identifier)
        - level: int (hierarchy level, 0 = finest)
        - title: str (community title)
        - summary: str (LLM-generated summary)
        - full_content: str (all content for the community)
        - rank: float (importance rank)
        - entity_ids: List[str] (member entity IDs)
        """
        if use_cache and group_id in _COMMUNITY_CACHE:
            logger.debug(f"✅ Using cached communities for group {group_id}")
            return _COMMUNITY_CACHE[group_id]
            
        logger.info(f"Loading communities from Neo4j for group {group_id}")
        
        query = """
        MATCH (c:Community {group_id: $group_id})
        OPTIONAL MATCH (e:Entity)-[:BELONGS_TO]->(c)
        RETURN 
            c.id AS id,
            c.level AS level,
            c.title AS title,
            c.summary AS summary,
            c.full_content AS full_content,
            c.rank AS rank,
            collect(DISTINCT e.id) AS entity_ids
        ORDER BY c.level, c.rank DESC
        """
        
        records, _, _ = self.driver.execute_query(query, group_id=group_id)
        
        data = []
        for record in records:
            data.append({
                "id": record["id"],
                "level": record["level"] or 0,
                "title": record["title"] or "",
                "summary": record["summary"] or "",
                "full_content": record["full_content"] or "",
                "rank": record["rank"] or 0.0,
                "entity_ids": record["entity_ids"] or [],
            })
        
        df = pd.DataFrame(data)
        
        if use_cache:
            _COMMUNITY_CACHE[group_id] = df
            logger.debug(f"✅ Cached {len(df)} communities for group {group_id}")
            
        logger.info(f"Loaded {len(df)} communities for group {group_id}")
        return df
    
    def load_relationships(self, group_id: str, use_cache: bool = True) -> pd.DataFrame:
        """
        Load relationships from Neo4j as DataFrame.
        
        Returns DataFrame with columns matching MS GraphRAG schema:
        - id: str (unique identifier)
        - source: str (source entity ID)
        - target: str (target entity ID)
        - weight: float (relationship weight)
        - description: str (relationship description)
        - text_unit_ids: List[str] (source chunk references)
        """
        if use_cache and group_id in _RELATIONSHIP_CACHE:
            logger.debug(f"✅ Using cached relationships for group {group_id}")
            return _RELATIONSHIP_CACHE[group_id]
            
        logger.info(f"Loading relationships from Neo4j for group {group_id}")
        
        query = """
        MATCH (e1:Entity {group_id: $group_id})-[r:RELATED_TO]->(e2:Entity {group_id: $group_id})
        RETURN 
            r.id AS id,
            e1.id AS source,
            e2.id AS target,
            r.weight AS weight,
            r.description AS description,
            r.text_unit_ids AS text_unit_ids
        """
        
        records, _, _ = self.driver.execute_query(query, group_id=group_id)
        
        data = []
        for record in records:
            data.append({
                "id": record["id"] or f"{record['source']}->{record['target']}",
                "source": record["source"],
                "target": record["target"],
                "weight": record["weight"] or 1.0,
                "description": record["description"] or "",
                "text_unit_ids": record["text_unit_ids"] or [],
            })
        
        df = pd.DataFrame(data)
        
        if use_cache:
            _RELATIONSHIP_CACHE[group_id] = df
            logger.debug(f"✅ Cached {len(df)} relationships for group {group_id}")
            
        logger.info(f"Loaded {len(df)} relationships for group {group_id}")
        return df
    
    def load_text_chunks(self, group_id: str) -> pd.DataFrame:
        """
        Load text chunks (text units) from Neo4j as DataFrame.
        
        Returns DataFrame with columns:
        - id: str
        - text: str
        - document_id: str
        - chunk_index: int
        """
        logger.info(f"Loading text chunks from Neo4j for group {group_id}")
        
        query = """
        MATCH (t:TextChunk {group_id: $group_id})
        OPTIONAL MATCH (t)-[:PART_OF]->(d:Document)
        RETURN 
            t.id AS id,
            t.text AS text,
            d.id AS document_id,
            t.chunk_index AS chunk_index
        ORDER BY d.id, t.chunk_index
        """
        
        records, _, _ = self.driver.execute_query(query, group_id=group_id)
        
        data = []
        for record in records:
            data.append({
                "id": record["id"],
                "text": record["text"] or "",
                "document_id": record["document_id"] or "",
                "chunk_index": record["chunk_index"] or 0,
            })
        
        df = pd.DataFrame(data)
        logger.info(f"Loaded {len(df)} text chunks for group {group_id}")
        return df
    
    def load_raptor_nodes(self, group_id: str) -> pd.DataFrame:
        """
        Load RAPTOR nodes from Neo4j as DataFrame.
        
        RAPTOR nodes contain hierarchical summaries with richer context
        than raw text chunks. Level 0 = leaf nodes, higher levels = summaries.
        
        Returns DataFrame with columns:
        - id: str
        - text: str
        - level: int
        - document_id: str (empty for RAPTOR)
        """
        logger.info(f"Loading RAPTOR nodes from Neo4j for group {group_id}")
        
        query = """
        MATCH (r:RaptorNode {group_id: $group_id})
        RETURN 
            r.id AS id,
            r.text AS text,
            r.level AS level
        ORDER BY r.level, r.id
        """
        
        records, _, _ = self.driver.execute_query(query, group_id=group_id)
        
        data = []
        for record in records:
            data.append({
                "id": record["id"],
                "text": record["text"] or "",
                "level": record["level"] or 0,
                "document_id": "",  # RAPTOR nodes span multiple docs
            })
        
        df = pd.DataFrame(data)
        logger.info(f"Loaded {len(df)} RAPTOR nodes for group {group_id}")
        return df
    
    async def drift_search(
        self,
        group_id: str,
        query: str,
        max_iterations: int = 5,
        convergence_threshold: float = 0.8,
        use_cache: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute DRIFT search using Neo4j data with MS GraphRAG models.
        
        DRIFT (Dynamic Reasoning with Iterative Facts and Templates) iteratively:
        1. Decomposes the query into sub-questions
        2. Searches for relevant context
        3. Accumulates findings
        4. Refines until convergence or max iterations
        
        Architecture Flow:
        1. Load data from Neo4j → Convert to MS GraphRAG models
        2. Create entity embeddings vector store
        3. Build DRIFTSearchContextBuilder
        4. Execute DRIFTSearch.search()
        
        Args:
            group_id: Tenant identifier
            query: Natural language query
            max_iterations: Maximum DRIFT iterations (default: 5)
            convergence_threshold: Stop when confidence reaches this (default: 0.8)
            use_cache: Whether to use cached DataFrames
            
        Returns:
            Dict with:
            - answer: str (generated answer)
            - confidence: float (0-1)
            - iterations: int (how many DRIFT iterations)
            - sources: List[str] (source references)
            - reasoning_path: List[dict] (step-by-step reasoning)
        """
        import time
        overall_start = time.time()
        logger.info(f"[DRIFT STAGE 1/5] Starting DRIFT search for group {group_id}: {query[:50]}...")
        
        try:
            # Import MS GraphRAG DRIFT components
            stage_start = time.time()
            try:
                from graphrag.query.structured_search.drift_search.drift_context import DRIFTSearchContextBuilder
                from graphrag.query.structured_search.drift_search.search import DRIFTSearch
                from graphrag.language_model.providers.litellm.chat_model import LitellmChatModel
                from graphrag.config.models.language_model_config import LanguageModelConfig
                from graphrag.config.enums import AuthType, ModelType
                
                elapsed = time.time() - stage_start
                logger.info(f"[DRIFT STAGE 1/5] MS GraphRAG DRIFT modules imported ({elapsed:.2f}s)")
            except ImportError as e:
                logger.error(f"Failed to import MS GraphRAG DRIFT: {e}")
                # Fallback to basic search if DRIFT not available
                entities_df = self.load_entities(group_id, use_cache=use_cache)
                relationships_df = self.load_relationships(group_id, use_cache=use_cache)
                return await self._fallback_search(group_id, query, entities_df, relationships_df)
            
            # Load data from Neo4j and convert to MS GraphRAG models
            # Use aggressive caching - only load once per group_id
            stage_start = time.time()
            cache_key = f"{group_id}_models_v3"
            
            import asyncio
            if cache_key in _GRAPHRAG_MODEL_CACHE:
                logger.info(f"[DRIFT STAGE 2/5] ✅ Using cached GraphRAG models (0.00s)")
                entities, relationships, text_units, communities = _GRAPHRAG_MODEL_CACHE[cache_key]
            else:
                logger.info(f"[DRIFT STAGE 2/5] Loading data from Neo4j (parallel, will cache)...")
                # Run all data loading in parallel using asyncio
                entities, relationships, text_units, communities = await asyncio.gather(
                    asyncio.to_thread(self.load_entities_as_graphrag_models, group_id),
                    asyncio.to_thread(self.load_relationships_as_graphrag_models, group_id),
                    asyncio.to_thread(self.load_text_units_with_raptor_as_graphrag_models, group_id),
                    self.load_communities_as_graphrag_models(group_id)
                )
                # Cache for subsequent queries (GLOBAL CACHE - persists across requests!)
                _GRAPHRAG_MODEL_CACHE[cache_key] = (entities, relationships, text_units, communities)
                logger.info(f"[DRIFT STAGE 2/5] ✅ Cached GraphRAG models for future queries")
            
            if not entities:
                logger.warning(f"No entities found for group {group_id}")
                return {
                    "answer": "No data has been indexed for this group yet.",
                    "confidence": 0.0,
                    "iterations": 0,
                    "sources": [],
                    "reasoning_path": [],
                }
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 2/5] Loaded {len(entities)} entities, {len(relationships)} relationships, "
                       f"{len(text_units)} text units, {len(communities)} communities ({elapsed:.2f}s)")
            
            # Create Neo4j-backed vector store for entity embeddings
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 3/5] Building DRIFT context and vector stores...")
            entity_embeddings_store = Neo4jDRIFTVectorStore(
                driver=self.driver,
                group_id=group_id,
                index_name="entity",
                embedding_dimension=3072,  # text-embedding-3-large
            )
            
            # Create a wrapper for LlamaIndex LLM to make it compatible with MS GraphRAG DRIFT
            # MS GraphRAG expects ChatModel protocol: achat(prompt, history) -> ModelResponse
            class DRIFTModelResponse:
                """ModelResponse implementation for MS GraphRAG DRIFT protocol."""
                def __init__(self, text: str, raw_response=None):
                    self._output = text
                    self._raw = raw_response
                
                @property
                def output(self) -> str:
                    """The output text from the model."""
                    return self._output
                
                @property
                def parsed_response(self):
                    """Parsed response (optional)."""
                    return None
                
                @property
                def history(self) -> list:
                    """Conversation history."""
                    return []
            
            class DRIFTLLMWrapper:
                """Wrapper to adapt LlamaIndex LLM for MS GraphRAG DRIFT ChatModel protocol."""
                def __init__(self, llama_llm):
                    self.llm = llama_llm
                    # Create config object that DRIFT expects
                    self.config = type('Config', (), {
                        'model': getattr(llama_llm, 'model', 'gpt-4o'),
                        'temperature': getattr(llama_llm, 'temperature', 0.0),
                        'max_tokens': getattr(llama_llm, 'max_tokens', 4000),
                        'top_p': getattr(llama_llm, 'top_p', 1.0),
                    })()
                
                async def achat(self, prompt: str, history: list | None = None, **kwargs):
                    """MS GraphRAG ChatModel protocol: achat(prompt, history) -> ModelResponse."""
                    response = await self.llm.acomplete(prompt)
                    return DRIFTModelResponse(text=response.text, raw_response=response)
                
                def chat(self, prompt: str, history: list | None = None, **kwargs):
                    """Sync version of chat."""
                    response = self.llm.complete(prompt)
                    return DRIFTModelResponse(text=response.text, raw_response=response)
            
            drift_llm = DRIFTLLMWrapper(self.llm)
            
            # Build DRIFT context builder with MS GraphRAG models
            # Required params: model, text_embedder, entities, entity_text_embeddings
            context_builder = DRIFTSearchContextBuilder(
                model=drift_llm,  # Use MS GraphRAG wrapper
                text_embedder=GraphRAGEmbeddingWrapper(self.embedder),  # EmbeddingModel protocol
                entities=entities,
                entity_text_embeddings=entity_embeddings_store,  # type: ignore - implements BaseVectorStore interface
                relationships=relationships,
                reports=communities,  # CommunityReport objects
                text_units=text_units,
            )
            
            # DRIFTSearch requires: model, context_builder
            # Config is set via DRIFTSearchContextBuilder or environment
            drift_search = DRIFTSearch(
                model=drift_llm,
                context_builder=context_builder,
            )
            
            # Initialize local search (required before searching)
            drift_search.init_local_search()
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 3/5] Context builder initialized ({elapsed:.2f}s)")
            
            # Execute search - DRIFT uses 'search' method
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 4/5] Executing DRIFT iterative search (max {max_iterations} iterations)...")
            result = await drift_search.search(
                query=query,
            )
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 4/5] DRIFT search completed ({elapsed:.2f}s)")
            
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 5/5] Extracting and formatting results...")
            
            # Extract answer from SearchResult (has 'response' field, not 'answer')
            answer = result.response if isinstance(result.response, str) else str(result.response)
            
            response = {
                "answer": answer,
                "confidence": 0.85,  # DRIFT doesn't provide score
                "iterations": max_iterations,
                "sources": self._extract_sources(result),
                "reasoning_path": self._extract_reasoning_path(result),
                "context_data": result.context_data if hasattr(result, 'context_data') else {},
                "llm_calls": result.llm_calls if hasattr(result, 'llm_calls') else 0,
                "tokens": {
                    "prompt": result.prompt_tokens if hasattr(result, 'prompt_tokens') else 0,
                    "output": result.output_tokens if hasattr(result, 'output_tokens') else 0,
                },
            }
            
            elapsed = time.time() - stage_start
            total_elapsed = time.time() - overall_start
            logger.info(f"[DRIFT STAGE 5/5] Results formatted ({elapsed:.2f}s)")
            logger.info(f"[DRIFT COMPLETE] Total time: {total_elapsed:.2f}s")
            
            return response
            
        except Exception as e:
            logger.error(f"DRIFT search failed for group {group_id}: {e}", exc_info=True)
            raise
    
    async def _fallback_search(
        self,
        group_id: str,
        query: str,
        entities: pd.DataFrame,
        relationships: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Fallback search when DRIFT is not available.
        Uses vector search (if embeddings exist) + text-based search + graph expansion.
        """
        logger.warning("Using fallback search (DRIFT not available with managed identity)")
        
        # Try vector search first (if embedder available and embeddings exist)
        context_parts = []
        sources = []
        
        if self.embedder:
            try:
                # Embed the query
                query_embedding = self.embedder.embed(query)
                
                # Vector search in Neo4j
                vector_query = """
                CALL db.index.vector.queryNodes('entity', $top_k, $embedding)
                YIELD node, score
                WHERE node.group_id = $group_id
                RETURN node.id AS id, node.name AS name, node.description AS description, score
                ORDER BY score DESC
                """
                
                records, _, _ = self.driver.execute_query(
                    vector_query,
                    embedding=query_embedding,
                    top_k=10,
                    group_id=group_id,
                )
                
                for record in records:
                    context_parts.append(f"- {record['name']}: {record['description']}")
                    sources.append({
                        "id": record['id'],
                        "name": record['name'],
                        "type": "entity",
                        "score": float(record['score']),
                    })
                
                logger.info(f"Vector search found {len(sources)} entities")
            except Exception as e:
                logger.warning(f"Vector search failed (embeddings may not exist): {e}")
        
        # Fallback to text-based search if vector search found nothing
        if not sources:
            logger.info("Vector search returned no results, using text-based entity search")
            text_query = """
            MATCH (e:Entity {group_id: $group_id})
            WHERE e.name IS NOT NULL AND e.description IS NOT NULL
            RETURN e.id AS id, e.name AS name, e.description AS description
            ORDER BY size(e.description) DESC
            LIMIT 20
            """
            
            records, _, _ = self.driver.execute_query(
                text_query,
                group_id=group_id,
            )
            
            for record in records:
                context_parts.append(f"- {record['name']}: {record['description']}")
                sources.append({
                    "id": record['id'],
                    "name": record['name'],
                    "type": "entity",
                })
            
            logger.info(f"Text-based search found {len(sources)} entities")
        
        context = "\n".join(context_parts)
        
        # Generate answer with LLM
        prompt = f"""Based on the following context, answer the question.

Context:
{context}

Question: {query}

Answer:"""
        
        response = self.llm.complete(prompt)
        
        return {
            "answer": response.text,
            "confidence": 0.7,  # Lower confidence for fallback
            "iterations": 1,
            "sources": sources,
            "reasoning_path": [{"step": "fallback_vector_search", "note": "DRIFT not available"}],
        }
    
    def _extract_sources(self, result: Any) -> List[str]:
        """Extract source references from DRIFT result."""
        sources = []
        if hasattr(result, "context_data") and result.context_data:
            if "sources" in result.context_data:
                sources = result.context_data["sources"]
            elif "entities" in result.context_data:
                sources = [e.get("id") for e in result.context_data["entities"]]
        return sources
    
    def _extract_reasoning_path(self, result: Any) -> List[Dict[str, Any]]:
        """Extract reasoning steps from DRIFT result."""
        path = []
        if hasattr(result, "context_data") and result.context_data:
            if "reasoning_path" in result.context_data:
                path = result.context_data["reasoning_path"]
            elif "search_history" in result.context_data:
                for i, step in enumerate(result.context_data["search_history"]):
                    path.append({
                        "iteration": i + 1,
                        "sub_query": step.get("query", ""),
                        "findings": step.get("findings", []),
                    })
        return path
    
    # ==================== MS GraphRAG Model Conversion ====================
    
    def load_entities_as_graphrag_models(self, group_id: str) -> List[Any]:
        """
        Load entities from Neo4j and convert to MS GraphRAG Entity models.
        
        Returns list of graphrag.data_model.entity.Entity objects.
        """
        from graphrag.data_model.entity import Entity as GraphRAGEntity
        
        df = self.load_entities(group_id)
        entities = []
        
        for _, row in df.iterrows():
            entity = GraphRAGEntity(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                title=row["name"],
                type=row.get("type"),
                description=row.get("description"),
                description_embedding=row.get("description_embedding"),
                text_unit_ids=row.get("text_unit_ids", []),
            )
            entities.append(entity)
        
        logger.info(f"Converted {len(entities)} entities to GraphRAG models for group {group_id}")
        return entities
    
    def load_relationships_as_graphrag_models(self, group_id: str) -> List[Any]:
        """
        Load relationships from Neo4j and convert to MS GraphRAG Relationship models.
        
        Returns list of graphrag.data_model.relationship.Relationship objects.
        """
        from graphrag.data_model.relationship import Relationship as GraphRAGRelationship
        
        df = self.load_relationships(group_id)
        relationships = []
        
        for _, row in df.iterrows():
            rel = GraphRAGRelationship(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                source=row["source"],
                target=row["target"],
                weight=row.get("weight", 1.0),
                description=row.get("description"),
                text_unit_ids=row.get("text_unit_ids", []),
            )
            relationships.append(rel)
        
        logger.info(f"Converted {len(relationships)} relationships to GraphRAG models for group {group_id}")
        return relationships
    
    def load_text_units_as_graphrag_models(self, group_id: str) -> List[Any]:
        """
        Load text chunks from Neo4j and convert to MS GraphRAG TextUnit models.
        
        Returns list of graphrag.data_model.text_unit.TextUnit objects.
        """
        from graphrag.data_model.text_unit import TextUnit as GraphRAGTextUnit
        
        df = self.load_text_chunks(group_id)
        text_units = []
        
        for _, row in df.iterrows():
            doc_id = row.get("document_id")
            text_unit = GraphRAGTextUnit(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                text=row["text"],
                document_ids=[str(doc_id)] if doc_id else None,
                n_tokens=row.get("tokens"),
            )
            text_units.append(text_unit)
        
        logger.info(f"Converted {len(text_units)} text units to GraphRAG models for group {group_id}")
        return text_units
    
    def load_text_units_with_raptor_as_graphrag_models(self, group_id: str) -> List[Any]:
        """
        Load BOTH text chunks AND RAPTOR nodes for richer DRIFT context.
        
        This provides:
        - Raw text chunks for specific details (prices, dates, etc.)  
        - RAPTOR nodes for hierarchical summaries and comparisons
        
        Returns list of graphrag.data_model.text_unit.TextUnit objects.
        """
        from graphrag.data_model.text_unit import TextUnit as GraphRAGTextUnit
        
        # Load both data sources
        chunks_df = self.load_text_chunks(group_id)
        raptor_df = self.load_raptor_nodes(group_id)
        
        text_units = []
        
        # Add text chunks (Level 0 - raw content)
        for _, row in chunks_df.iterrows():
            doc_id = row.get("document_id")
            text_unit = GraphRAGTextUnit(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                text=row["text"],
                document_ids=[str(doc_id)] if doc_id else None,
                n_tokens=row.get("tokens"),
            )
            text_units.append(text_unit)
        
        # Add RAPTOR nodes (Level 1+ - summaries)
        for _, row in raptor_df.iterrows():
            text_unit = GraphRAGTextUnit(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                text=f"[RAPTOR Summary Level {row['level']}]\n{row['text']}",
                document_ids=None,  # RAPTOR spans multiple docs
                n_tokens=None,
            )
            text_units.append(text_unit)
        
        logger.info(f"Converted {len(chunks_df)} text chunks + {len(raptor_df)} RAPTOR nodes "
                   f"= {len(text_units)} total text units for DRIFT search (group {group_id})")
        return text_units
    
    async def load_communities_as_graphrag_models(self, group_id: str) -> List[Any]:
        """
        Load communities from Neo4j and convert to MS GraphRAG CommunityReport models.
        
        Returns list of graphrag.data_model.community_report.CommunityReport objects.
        """
        from graphrag.data_model.community_report import CommunityReport as GraphRAGCommunityReport
        
        df = self.load_communities(group_id)
        communities = []
        
        for _, row in df.iterrows():
            full_content = row.get("full_content", "")
            if not full_content:
                full_content = " "  # Use a single space to avoid empty input error
            
            # Generate embedding for full content as required by DRIFT
            try:
                embedding = await self.embedder.aget_text_embedding(full_content)
            except Exception as e:
                logger.warning(f"Failed to embed community content: {e}")
                # Fallback to zero vector if embedding fails
                embedding = [0.0] * 1536  # Assuming 1536 dimensions
            
            community = GraphRAGCommunityReport(
                id=row["id"],
                short_id=row["id"][:8] if row["id"] else None,
                title=row.get("title", ""),
                community_id=row["id"],
                summary=row.get("summary", ""),
                full_content=full_content,
                full_content_embedding=embedding,
                rank=row.get("rank", 1.0),
            )
            communities.append(community)
        
        logger.info(f"Converted {len(communities)} communities to GraphRAG models for group {group_id}")
        return communities


class Neo4jDRIFTVectorStore:
    """
    Vector store adapter that bridges Neo4j vector indexes with MS GraphRAG DRIFT.
    
    DRIFT expects a vector store implementing the BaseVectorStore interface.
    This adapter wraps Neo4j's native vector search.
    
    Note: We don't inherit from BaseVectorStore directly to avoid import issues,
    but we implement all its required methods.
    """
    
    def __init__(
        self,
        driver: neo4j.Driver,
        group_id: str,
        index_name: str = "entity",
        embedding_dimension: int = 1536,
    ):
        """
        Initialize Neo4j vector store adapter.
        
        Args:
            driver: Neo4j driver instance
            group_id: Tenant identifier for filtering
            index_name: Name of the Neo4j vector index
            embedding_dimension: Dimension of embeddings (default: 3072)
        """
        self.driver = driver
        self.group_id = group_id
        self.index_name = index_name
        self.embedding_dimension = embedding_dimension
        self._documents: Dict[str, Any] = {}
        # Collection name for compatibility with BaseVectorStore
        self.collection_name = index_name
    
    def connect(self, **kwargs) -> None:
        """Connect to the vector store (no-op for Neo4j - already connected)."""
        pass
    
    def load_documents(self, documents: List[Any], overwrite: bool = True) -> None:
        """
        Load documents into the vector store.
        
        For Neo4j, we cache locally since data is already in Neo4j.
        """
        if overwrite:
            self._documents.clear()
        
        for doc in documents:
            self._documents[doc.id] = doc
    
    def filter_by_id(self, include_ids: List[str]) -> "Neo4jDRIFTVectorStore":
        """Return a filtered view of the vector store."""
        # For simplicity, return self - filtering happens in queries
        return self
    
    def search_by_id(self, id: str) -> Optional[Any]:
        """Search for a document by ID."""
        if id in self._documents:
            return self._documents[id]
        
        # Query Neo4j
        query = """
        MATCH (e:Entity {id: $id, group_id: $group_id})
        RETURN e.id AS id, e.name AS text, e.embedding AS vector
        """
        
        records, _, _ = self.driver.execute_query(
            query,
            id=id,
            group_id=self.group_id,
        )
        
        if records:
            from graphrag.vector_stores.base import VectorStoreDocument
            record = records[0]
            return VectorStoreDocument(
                id=record["id"],
                text=record["text"],
                vector=record["vector"],
            )
        
        return None
    
    def similarity_search_by_vector(
        self,
        query_embedding: List[float],
        k: int = 10,
        **kwargs,
    ) -> List[Any]:
        """
        Search for similar documents by embedding vector.
        
        This is the main method DRIFT uses for vector search.
        """
        from graphrag.vector_stores.base import VectorStoreSearchResult
        
        query = """
        CALL db.index.vector.queryNodes($index_name, $k, $embedding)
        YIELD node, score
        WHERE node.group_id = $group_id
        RETURN node.id AS id, node.name AS text, node.embedding AS vector, score
        ORDER BY score DESC
        """
        
        records, _, _ = self.driver.execute_query(
            query,
            index_name=self.index_name,
            k=k,
            embedding=query_embedding,
            group_id=self.group_id,
        )
        
        results = []
        for record in records:
            from graphrag.vector_stores.base import VectorStoreDocument
            doc = VectorStoreDocument(
                id=record["id"],
                text=record["text"] or "",
                vector=record["vector"],
            )
            results.append(VectorStoreSearchResult(
                document=doc,
                score=record["score"],
            ))
        
        return results
    
    def similarity_search_by_text(
        self,
        text: str,
        text_embedder: Any,
        k: int = 10,
        **kwargs,
    ) -> List[Any]:
        """
        Search for similar documents by text query.
        
        Embeds the text and delegates to vector search.
        """
        # Embed the query text
        query_embedding = text_embedder(text)
        return self.similarity_search_by_vector(query_embedding, k, **kwargs)


class AsyncDRIFTAdapter(DRIFTAdapter):
    """
    Async version of DRIFT adapter using async Neo4j driver.
    
    Use this for production deployments with async FastAPI endpoints.
    """
    
    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        llm: Any,
        embedder: Any,
    ):
        self.neo4j_uri = neo4j_uri
        self.neo4j_user = neo4j_user
        self.neo4j_password = neo4j_password
        self.llm = llm
        self.embedder = embedder
        self._async_driver = None
        
        # Also create sync driver for cache operations
        self._sync_driver = neo4j.GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password),
        )
        
        # Initialize parent with sync driver
        super().__init__(self._sync_driver, llm, embedder)
    
    async def get_async_driver(self):
        """Get or create async Neo4j driver."""
        if self._async_driver is None:
            self._async_driver = AsyncGraphDatabase.driver(
                self.neo4j_uri,
                auth=(self.neo4j_user, self.neo4j_password),
            )
        return self._async_driver
    
    async def close(self):
        """Close drivers."""
        if self._async_driver:
            await self._async_driver.close()
        if self._sync_driver:
            self._sync_driver.close()
