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
import re
from typing import Any, Dict, List, Optional
import pandas as pd
import neo4j
from neo4j import AsyncGraphDatabase
from app.core.config import settings

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        na += fx * fx
        nb += fy * fy
    denom = (na ** 0.5) * (nb ** 0.5)
    return (dot / denom) if denom else 0.0


class DriftPrerequisitesError(RuntimeError):
    """Raised when a DRIFT search cannot run due to missing prerequisite graph data."""

    def __init__(self, message: str, *, missing: list[str] | None = None):
        super().__init__(message)
        self.missing = missing or []

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

    def _debug_term_scan(
        self,
        *,
        where: str,
        items: list[Any],
        term_groups: dict[str, list[str]],
        get_text: callable,
        get_id: callable,
        get_doc_ids: callable,
        max_samples_per_term: int = 2,
    ) -> None:
        """Best-effort diagnostics to answer: does the tenant corpus contain evidence?

        This is intentionally lightweight and log-only.
        Term strings can be plain substrings or prefixed with "re:" for regex.
        """

        def _matches(text: str, term: str) -> bool:
            if not text:
                return False
            if term.startswith("re:"):
                try:
                    return re.search(term[3:], text, flags=re.IGNORECASE) is not None
                except re.error:
                    return False
            return term.lower() in text.lower()

        print(f"[TERM_SCAN] where={where} items={len(items)} groups={list(term_groups.keys())}]", flush=True)

        # Pre-lower texts once to keep scan cheap.
        lowered: list[tuple[Any, str]] = []
        for it in items:
            try:
                text = str(get_text(it) or "")
            except Exception:
                text = ""
            lowered.append((it, text))

        for group_name, terms in term_groups.items():
            group_hits = 0
            term_counts: dict[str, int] = {t: 0 for t in terms}
            term_samples: dict[str, list[dict[str, Any]]] = {t: [] for t in terms}

            for it, text in lowered:
                if not text:
                    continue

                any_hit = False
                for term in terms:
                    if _matches(text, term):
                        any_hit = True
                        term_counts[term] += 1
                        if len(term_samples[term]) < max_samples_per_term:
                            try:
                                iid = str(get_id(it) or "")
                            except Exception:
                                iid = ""
                            try:
                                doc_ids = get_doc_ids(it)
                            except Exception:
                                doc_ids = None
                            term_samples[term].append(
                                {
                                    "id": iid or None,
                                    "document_ids": doc_ids,
                                }
                            )
                if any_hit:
                    group_hits += 1

            # Keep logs compact: only print terms that matched at least once.
            matched_terms = [(t, c) for (t, c) in term_counts.items() if c > 0]
            matched_terms.sort(key=lambda x: x[1], reverse=True)

            print(
                f"[TERM_SCAN] group={group_name} items_with_any_term={group_hits}/{len(items)} terms_matched={len(matched_terms)}/{len(terms)}]",
                flush=True,
            )
            for term, count in matched_terms[:12]:
                print(
                    f"[TERM_SCAN] group={group_name} term={term} hits={count} samples={term_samples.get(term) or []}]",
                    flush=True,
                )
            
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
        include_sources: bool = False,
        use_cache: bool = True,
        **kwargs,
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

        is_debug_group = (
            settings.V3_DRIFT_DEBUG_LOGGING
            and (settings.V3_DRIFT_DEBUG_GROUP_ID is None or settings.V3_DRIFT_DEBUG_GROUP_ID == group_id)
        )
        
        # DEBUG: Verify settings are being read correctly
        if is_debug_group:
            print(
                f"[DEBUG_SETTINGS] V3_DRIFT_DEBUG_LOGGING={settings.V3_DRIFT_DEBUG_LOGGING} (type={type(settings.V3_DRIFT_DEBUG_LOGGING)})",
                flush=True,
            )
            print(f"[DEBUG_SETTINGS] V3_DRIFT_DEBUG_GROUP_ID={settings.V3_DRIFT_DEBUG_GROUP_ID}", flush=True)
            print(f"[DEBUG_SETTINGS] Current group_id={group_id}", flush=True)
        
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
                if is_debug_group:
                    print(
                        "[DRIFT_DEBUG] EXECUTION_PATH=fallback_search reason=import_error]",
                        flush=True,
                    )
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

            # DRIFT relies on community structure and at least some relationship signal.
            # For debugging, we can fall back; by default we fail-fast with a clear 4xx.
            missing: list[str] = []
            if not relationships:
                missing.append("relationships")
            if not communities:
                missing.append("communities")
            if missing:
                message = (
                    "DRIFT prerequisites missing for this group. "
                    f"Missing: {', '.join(missing)}. "
                    "Reindex with community detection enabled (run_community_detection=true) "
                    "and ensure relationship extraction succeeded."
                )

                if settings.V3_DRIFT_DEBUG_FALLBACK:
                    logger.warning(
                        "DRIFT prerequisites missing; debug fallback enabled",
                        extra={
                            "group_id": group_id,
                            "missing": missing,
                        },
                    )
                    entities_df = self.load_entities(group_id, use_cache=use_cache)
                    relationships_df = self.load_relationships(group_id, use_cache=use_cache)
                    return await self._fallback_search(group_id, query, entities_df, relationships_df)

                raise DriftPrerequisitesError(message, missing=missing)
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 2/5] Loaded {len(entities)} entities, {len(relationships)} relationships, "
                       f"{len(text_units)} text units, {len(communities)} communities ({elapsed:.2f}s)")
            
            # Debug logging: Check for "10 business days" in text units
            if is_debug_group and settings.V3_DRIFT_DEBUG_TERM_SCAN and text_units:
                # Focused diagnostics for the question bank drift set (Q-D1..Q-D3)
                # to distinguish: data absence vs retrieval/ranking/context selection.
                term_groups = {
                    "Q-D1_warranty_emergency": [
                        "telephone",
                        "emergency",
                        "burst pipe",
                        "promptly notify",
                        "relieves",
                        "builder",
                    ],
                    "Q-D2_pma_reservations": [
                        "confirmed reservations",
                        "honor all confirmed reservations",
                        "owner shall honor",
                        "terminated",
                        "termination",
                        "sold",
                        "sale",
                    ],
                    "Q-D3_timeframes": [
                        # Numeric + parenthetical styles commonly found in contracts
                        "re:\\b\\d+\\s+business\\s+days\\b",
                        "re:\\b\\d+\\s+days\\b",
                        "re:\\bsixty\\s*\\(\\s*60\\s*\\)\\s*days\\b",
                        "re:\\bten\\s*\\(\\s*10\\s*\\)\\s*business\\s*days\\b",
                        "arbitration",
                        "written notice",
                    ],
                }

                self._debug_term_scan(
                    where="text_units",
                    items=text_units,
                    term_groups=term_groups,
                    get_text=lambda u: getattr(u, "text", ""),
                    get_id=lambda u: getattr(u, "id", None),
                    get_doc_ids=lambda u: getattr(u, "document_ids", None),
                )
            
            # Create Neo4j-backed vector store for entity embeddings
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 3/5] Building DRIFT context and vector stores...")
            entity_embeddings_store = Neo4jDRIFTVectorStore(
                driver=self.driver,
                group_id=group_id,
                index_name="entity_embedding",
                embedding_dimension=3072,  # text-embedding-3-large
            )

            # Root-cause guardrail: if entity embeddings exist on the entity models,
            # preload them into the vector store so query→entity mapping works even
            # when the Neo4j vector index returns no in-tenant hits.
            try:
                from graphrag.vector_stores.base import VectorStoreDocument

                embedded_entities: list[tuple[Any, list[float]]] = []
                for e in entities:
                    vec = getattr(e, "description_embedding", None)
                    if isinstance(vec, list) and len(vec) > 0:
                        embedded_entities.append((e, vec))

                if is_debug_group:
                    print(
                        f"[DEBUG] Entity embeddings present: {len(embedded_entities)}/{len(entities)}]",
                        flush=True,
                    )
                    if embedded_entities:
                        print(
                            f"[DEBUG] Entity embedding dims (sample): {len(embedded_entities[0][1])}]",
                            flush=True,
                        )

                docs = [
                    VectorStoreDocument(
                        id=str(getattr(e, "id", "")),
                        text=str(getattr(e, "title", "") or ""),
                        vector=vec,
                    )
                    for (e, vec) in embedded_entities
                    if getattr(e, "id", None)
                ]
                if docs:
                    entity_embeddings_store.load_documents(docs, overwrite=True)
            except Exception:
                # Best-effort only; do not fail the query if GraphRAG changes interfaces.
                pass
            
            # Create a wrapper for LlamaIndex LLM to make it compatible with MS GraphRAG DRIFT
            # MS GraphRAG expects ChatModel protocol: achat(prompt, history) -> ModelResponse
            class DRIFTModelOutput:
                """Model output with content attribute for MS GraphRAG compatibility."""
                def __init__(self, text: str):
                    self.content = text
                
                def __str__(self):
                    return self.content
            
            class DRIFTModelResponse(str):
                """ModelResponse implementation for MS GraphRAG DRIFT protocol.
                
                Inherits from str so json.loads() can use it directly, while providing
                ModelResponse protocol properties.
                """
                def __new__(cls, text: str, raw_response=None):
                    # Create string instance first (required for str subclass)
                    instance = str.__new__(cls, text)
                    return instance
                
                def __init__(self, text: str, raw_response=None):
                    # Store additional attributes (str.__init__ doesn't take params)
                    self._output = DRIFTModelOutput(text)
                    self._raw = raw_response
                
                @property
                def output(self):
                    """The output object with content attribute."""
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
                    self._prefix = (
                        "You are answering questions using ONLY the provided context. "
                        "If you can find any relevant clause or evidence in the provided context, answer using it (quote key phrases when possible). "
                        "Respond with \"Not specified in the provided documents.\" ONLY when there is no relevant clause/evidence in the provided context.\n\n"
                    )
                    # Guardrail: GraphRAG may pass very large history/context messages (especially
                    # during reduce). Because our underlying LlamaIndex interface accepts a single
                    # string prompt, serializing history naively can exceed model context limits.
                    # These limits are intentionally conservative and can be tuned via env.
                    self._max_history_chars = int(getattr(settings, "V3_DRIFT_MAX_HISTORY_CHARS", 120_000) or 120_000)
                    self._max_history_message_chars = int(
                        getattr(settings, "V3_DRIFT_MAX_HISTORY_MESSAGE_CHARS", 40_000) or 40_000
                    )
                    # Create config object that DRIFT expects
                    self.config = type('Config', (), {
                        'model': getattr(llama_llm, 'model', 'gpt-4o'),
                        'temperature': getattr(llama_llm, 'temperature', 0.0),
                        'max_tokens': getattr(llama_llm, 'max_tokens', 4000),
                        'top_p': getattr(llama_llm, 'top_p', 1.0),
                    })()

                @staticmethod
                def _wants_json(prompt: str, kwargs: dict) -> bool:
                    if kwargs.get("json", False):
                        return True
                    p = (prompt or "").lower()
                    # MS GraphRAG drift primer expects JSON for query decomposition; it usually
                    # includes explicit JSON instructions in the prompt, even if it doesn't pass
                    # a structured flag in kwargs.
                    return "json" in p

                @staticmethod
                def _strip_code_fences(text: str) -> str:
                    t = (text or "").strip()
                    if not t:
                        return ""
                    if t.startswith("```json"):
                        t = t[7:]
                    elif t.startswith("```"):
                        t = t[3:]
                    if t.endswith("```"):
                        t = t[:-3]
                    return t.strip()

                @staticmethod
                def _coerce_single_json(text: str) -> str:
                    """Return a single valid JSON object/array string.

                    Handles common LLM failure modes:
                    - Markdown fences
                    - Preface/suffix text around JSON (causing JSONDecodeError: Extra data)
                    - Minor JSON syntax issues (attempt repair)
                    """
                    import json

                    raw = DRIFTLLMWrapper._strip_code_fences(text)
                    if not raw:
                        return ""

                    # Try extracting the first JSON value via raw_decode.
                    decoder = json.JSONDecoder()
                    start = None
                    for i, ch in enumerate(raw):
                        if ch in "{[":
                            start = i
                            break
                    if start is not None:
                        try:
                            _, end = decoder.raw_decode(raw[start:])
                            candidate = raw[start : start + end].strip()
                            # Validate
                            json.loads(candidate)
                            return candidate
                        except Exception:
                            pass

                    # Fallback: attempt JSON repair and then parse again.
                    try:
                        from json_repair import repair_json

                        repaired = repair_json(raw).strip()
                        if repaired and repaired not in ('""', ""):
                            # Some repairs may still include leading/trailing text; repeat extraction.
                            start = None
                            for i, ch in enumerate(repaired):
                                if ch in "{[":
                                    start = i
                                    break
                            if start is not None:
                                _, end = decoder.raw_decode(repaired[start:])
                                candidate = repaired[start : start + end].strip()
                                json.loads(candidate)
                                return candidate
                            json.loads(repaired)
                            return repaired
                    except Exception:
                        pass

                    # Last resort: return stripped text (will surface error upstream).
                    return raw

                @staticmethod
                def _render_history(history: list | None) -> str:
                    """Render GraphRAG chat history into a single prompt string.

                    GraphRAG's ChatModel protocol passes context and instructions via
                    a list of messages (usually system messages). Our underlying
                    LlamaIndex LLM interface accepts a single string prompt, so we
                    must serialize the history.
                    """

                    if not history:
                        return ""

                    # NOTE: This method remains @staticmethod for compatibility with older
                    # call sites, but we still want truncation. If called as instance method,
                    # we can access self.* limits; otherwise we fall back to safe defaults.
                    return DRIFTLLMWrapper._render_history_with_limits(history)

                @staticmethod
                def _truncate_text(text: str, *, max_chars: int, keep: str = "start") -> str:
                    t = (text or "").strip()
                    if max_chars <= 0:
                        return ""
                    if len(t) <= max_chars:
                        return t
                    ellipsis = "\n...[TRUNCATED]...\n"
                    budget = max(0, max_chars - len(ellipsis))
                    if budget <= 0:
                        return t[:max_chars]
                    if keep == "end":
                        return ellipsis + t[-budget:]
                    return t[:budget] + ellipsis

                @staticmethod
                def _render_history_with_limits(history: list | None, *, max_total_chars: int = 120_000, max_msg_chars: int = 40_000) -> str:
                    if not history:
                        return ""

                    # Split roles so we can prioritize system instructions.
                    system_msgs: list[tuple[str, str]] = []
                    other_msgs: list[tuple[str, str]] = []
                    for msg in history:
                        if not isinstance(msg, dict):
                            continue
                        role_raw = str(msg.get("role") or "").strip().lower()
                        role = (role_raw or "message").upper()
                        content = str(msg.get("content") or "").strip()
                        if not content:
                            continue

                        # Per-message truncation: keep the *start* for SYSTEM, keep the *end*
                        # for non-system since recent details tend to be later.
                        keep = "start" if role_raw == "system" else "end"
                        content = DRIFTLLMWrapper._truncate_text(content, max_chars=max_msg_chars, keep=keep)
                        if role_raw == "system":
                            system_msgs.append((role, content))
                        else:
                            other_msgs.append((role, content))

                    def render(pairs: list[tuple[str, str]]) -> str:
                        return "\n\n".join([f"{r}:\n{c}" for (r, c) in pairs if c])

                    # Start with system; then add the last few non-system messages.
                    rendered_system = render(system_msgs)
                    if not other_msgs:
                        return DRIFTLLMWrapper._truncate_text(rendered_system, max_chars=max_total_chars, keep="start")

                    # Keep at most last 8 non-system entries to avoid runaway growth.
                    tail_other = other_msgs[-8:]
                    rendered_other = render(tail_other)

                    if rendered_system:
                        combined = f"{rendered_system}\n\n{rendered_other}" if rendered_other else rendered_system
                    else:
                        combined = rendered_other

                    # Enforce overall cap while preserving system preamble.
                    if len(combined) <= max_total_chars:
                        return combined

                    # If system alone is too large, truncate it and drop other.
                    if rendered_system and len(rendered_system) >= max_total_chars:
                        return DRIFTLLMWrapper._truncate_text(rendered_system, max_chars=max_total_chars, keep="start")

                    # Otherwise, keep full system and truncate non-system tail.
                    remaining = max_total_chars - (len(rendered_system) + 2)  # +2 for separator newlines
                    truncated_other = DRIFTLLMWrapper._truncate_text(rendered_other, max_chars=max(0, remaining), keep="end")
                    return f"{rendered_system}\n\n{truncated_other}".strip()

                def _build_prompt(self, prompt: str, history: list | None, kwargs: dict) -> tuple[str, bool]:
                    history_text = self._render_history_with_limits(
                        history,
                        max_total_chars=self._max_history_chars,
                        max_msg_chars=self._max_history_message_chars,
                    )
                    if (
                        getattr(settings, "V3_DRIFT_DEBUG_LOGGING", False)
                        and "[TRUNCATED]" in history_text
                    ):
                        print(
                            f"[DRIFT_DEBUG] history truncated: max_total_chars={self._max_history_chars} max_msg_chars={self._max_history_message_chars}",
                            flush=True,
                        )
                    if history_text:
                        full_prompt = f"{self._prefix}{history_text}\n\nUSER:\n{prompt}"
                    else:
                        full_prompt = f"{self._prefix}{prompt}"

                    json_mode = self._wants_json(full_prompt, kwargs)
                    if json_mode:
                        full_prompt = f"{full_prompt}\n\nIMPORTANT: Return ONLY valid JSON, no other text."
                    return full_prompt, json_mode

                @staticmethod
                def _extract_llm_kwargs(kwargs: dict) -> dict:
                    """Map GraphRAG model_parameters into LlamaIndex LLM kwargs (best-effort)."""
                    model_parameters = kwargs.get("model_parameters")
                    if not isinstance(model_parameters, dict):
                        return {}
                    allowed = {
                        "max_tokens",
                        "temperature",
                        "top_p",
                        "presence_penalty",
                        "frequency_penalty",
                        "seed",
                        "stop",
                        "timeout",
                    }
                    llm_kwargs: dict = {}
                    for k, v in model_parameters.items():
                        if k in allowed and v is not None:
                            llm_kwargs[k] = v
                    return llm_kwargs
                
                async def achat(self, prompt: str, history: list | None = None, **kwargs):
                    """MS GraphRAG ChatModel protocol: achat(prompt, history) -> ModelResponse."""
                    import sys

                    prompt, json_mode = self._build_prompt(prompt, history, kwargs)
                    llm_kwargs = self._extract_llm_kwargs(kwargs)
                    
                    # Debug: Print to stdout with flush
                    print(f"[DRIFT_DEBUG] achat called, json_mode={json_mode}, prompt_len={len(prompt)}", flush=True)
                    sys.stdout.flush()
                    logger.error(f"[DRIFT_DEBUG] achat called, json_mode={json_mode}")
                    
                    try:
                        print(f"[DRIFT_DEBUG] Calling LLM...", flush=True)
                        response = await self.llm.acomplete(prompt, **llm_kwargs)
                        text = response.text.strip() if response and hasattr(response, 'text') else ''
                        print(f"[DRIFT_DEBUG] LLM response: len={len(text)}, text='{text[:500] if text else 'EMPTY'}'", flush=True)
                        logger.error(f"[DRIFT_DEBUG] LLM returned: len={len(text)}, text={text[:200]}")

                        if text:
                            text = self._strip_code_fences(text)
                        if json_mode and text:
                            coerced = self._coerce_single_json(text)
                            if coerced != text:
                                print(f"[DRIFT_DEBUG] Coerced JSON output: len={len(coerced)}", flush=True)
                            text = coerced
                    except Exception as e:
                        print(f"[DRIFT_DEBUG] LLM call failed: {type(e).__name__}: {e}", flush=True)
                        logger.error(f"[DRIFT_DEBUG] LLM call failed: {e}")
                        raise
                    
                    result = DRIFTModelResponse(text=text, raw_response=response)
                    print(f"[DRIFT_DEBUG] Returning response type={type(result)}, str_value='{str(result)[:200]}'", flush=True)
                    return result
                
                async def achat_stream(self, prompt: str, history: list | None = None, **kwargs):
                    """MS GraphRAG ChatModel protocol: achat_stream(prompt, history) -> async iterator of str chunks."""
                    import sys

                    prompt, json_mode = self._build_prompt(prompt, history, kwargs)
                    llm_kwargs = self._extract_llm_kwargs(kwargs)

                    print(f"[DRIFT_DEBUG] achat_stream called, json_mode={json_mode}, prompt_len={len(prompt)}", flush=True)
                    
                    try:
                        # Use streaming if available, otherwise fallback to non-streaming
                        if hasattr(self.llm, 'astream_complete'):
                            print(f"[DRIFT_DEBUG] Using astream_complete...", flush=True)
                            accumulated_text = ""
                            async for chunk in self.llm.astream_complete(prompt, **llm_kwargs):
                                if chunk and hasattr(chunk, 'text'):
                                    accumulated_text += chunk.text
                                    yield chunk.text
                                elif chunk:
                                    accumulated_text += str(chunk)
                                    yield str(chunk)
                            
                            # Apply markdown stripping to full accumulated text if json_mode
                            if json_mode and accumulated_text:
                                cleaned_text = accumulated_text.strip()
                                if cleaned_text.startswith("```json"):
                                    cleaned_text = cleaned_text[7:]
                                elif cleaned_text.startswith("```"):
                                    cleaned_text = cleaned_text[3:]
                                if cleaned_text.endswith("```"):
                                    cleaned_text = cleaned_text[:-3]
                                # If we stripped anything, we need to yield the corrected version
                                if cleaned_text != accumulated_text:
                                    print(f"[DRIFT_DEBUG] Markdown stripped in stream", flush=True)
                        else:
                            # Fallback to non-streaming achat and yield as single chunk
                            print(f"[DRIFT_DEBUG] Fallback to non-streaming achat...", flush=True)
                            response = await self.llm.acomplete(prompt, **llm_kwargs)
                            text = response.text.strip() if response and hasattr(response, 'text') else ''
                            if text:
                                text = self._strip_code_fences(text)
                            if json_mode and text:
                                text = self._coerce_single_json(text)
                            yield str(text)
                    except Exception as e:
                        print(f"[DRIFT_DEBUG] achat_stream failed: {type(e).__name__}: {e}", flush=True)
                        logger.error(f"[DRIFT_DEBUG] achat_stream failed: {e}")
                        raise
                
                def chat(self, prompt: str, history: list | None = None, **kwargs):
                    """Sync version of chat."""
                    prompt, json_mode = self._build_prompt(prompt, history, kwargs)
                    llm_kwargs = self._extract_llm_kwargs(kwargs)
                    response = self.llm.complete(prompt, **llm_kwargs)

                    text = response.text.strip() if response and hasattr(response, 'text') else ''
                    if text:
                        text = self._strip_code_fences(text)
                    if json_mode and text:
                        text = self._coerce_single_json(text)
                    
                    return DRIFTModelResponse(text=text, raw_response=response)
            
            drift_llm = DRIFTLLMWrapper(self.llm)
            
            # Build DRIFT context builder with MS GraphRAG models
            # Required params: model, text_embedder, entities, entity_text_embeddings
            # IMPORTANT: MS GraphRAG DRIFT uses config.n_depth and config.drift_k_followups to control
            # how many sub-queries run (and how much concurrency). Without overriding config, the defaults
            # can easily cause long-running requests.
            from graphrag.config.models.drift_search_config import DRIFTSearchConfig

            safe_depth = max(1, min(int(max_iterations or 1), 5))
            drift_config = DRIFTSearchConfig(
                n_depth=safe_depth,
                drift_k_followups=5,
                primer_folds=2,
                concurrency=8,
                # Keep prompts bounded; smaller contexts reduce latency/cost.
                local_search_max_data_tokens=6000,
                primer_llm_max_tokens=4000,
                local_search_top_k_mapped_entities=10,
                local_search_top_k_relationships=10,
            )

            context_builder = DRIFTSearchContextBuilder(
                model=drift_llm,  # Use MS GraphRAG wrapper
                text_embedder=GraphRAGEmbeddingWrapper(self.embedder),  # EmbeddingModel protocol
                entities=entities,
                entity_text_embeddings=entity_embeddings_store,  # type: ignore - implements BaseVectorStore interface
                relationships=relationships,
                reports=communities,  # CommunityReport objects
                text_units=text_units,
                config=drift_config,
            )
            
            if is_debug_group:
                print(f"[DEBUG] DRIFTSearchContextBuilder initialized with:]", flush=True)
                print(f"[DEBUG]   - {len(entities)} entities]", flush=True)
                print(f"[DEBUG]   - {len(relationships)} relationships]", flush=True)
                print(f"[DEBUG]   - {len(text_units)} text units]", flush=True)
                print(f"[DEBUG]   - {len(communities)} communities/reports]", flush=True)
            
            # DRIFTSearch requires: model, context_builder
            # Config is set via DRIFTSearchContextBuilder or environment.
            # NOTE: Upstream GraphRAG hard-codes return_candidate_context=False inside
            # DRIFTSearch.init_local_search(), which results in empty SearchResult.context_data.
            # For V3, we enable candidate context ONLY when include_sources=True.
            from graphrag.query.structured_search.drift_search.search import DRIFTSearch

            DRIFTSearchImpl = DRIFTSearch
            if include_sources:
                class DRIFTSearchWithCandidates(DRIFTSearch):
                    def init_local_search(self):  # type: ignore[override]
                        local_search = super().init_local_search()
                        try:
                            local_search.context_builder_params["return_candidate_context"] = True
                        except Exception:
                            # Best-effort: if GraphRAG changes internals, don't fail the request.
                            pass
                        return local_search

                DRIFTSearchImpl = DRIFTSearchWithCandidates

            if is_debug_group:
                print(f"[DEBUG] Creating DRIFTSearch instance...]", flush=True)

            drift_search = DRIFTSearchImpl(
                model=drift_llm,
                context_builder=context_builder,
            )

            if is_debug_group:
                print(f"[DEBUG] DRIFTSearch instance created successfully]", flush=True)
                print(f"[DEBUG] include_sources={include_sources}]", flush=True)
                try:
                    rc = drift_search.local_search.context_builder_params.get("return_candidate_context")
                except Exception:
                    rc = None
                print(f"[DEBUG] return_candidate_context={rc} (search_class={type(drift_search).__name__})]", flush=True)
                print(
                    f"[DRIFT_DEBUG] EXECUTION_PATH=graphrag_drift search_class={type(drift_search).__name__}]",
                    flush=True,
                )
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 3/5] Context builder initialized ({elapsed:.2f}s)")
            
            # Execute search - DRIFT uses 'search' method
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 4/5] Executing DRIFT iterative search (max {safe_depth} iterations)...")
            result = await drift_search.search(
                query=query,
            )
            
            elapsed = time.time() - stage_start
            logger.info(f"[DRIFT STAGE 4/5] DRIFT search completed ({elapsed:.2f}s)")
            
            if is_debug_group:
                print(f"[DEBUG] DRIFT result attributes: {dir(result)}]", flush=True)
                print(f"[DEBUG] result.response: {result.response if hasattr(result, 'response') else 'N/A'}]", flush=True)
                print(f"[DEBUG] result.context_data: {result.context_data if hasattr(result, 'context_data') else 'N/A'}]", flush=True)
            
            stage_start = time.time()
            logger.info(f"[DRIFT STAGE 5/5] Extracting and formatting results...")
            
            # Extract answer from SearchResult (has 'response' field, not 'answer')
            answer = result.response if isinstance(result.response, str) else str(result.response)
            
            extracted_sources = self._extract_sources(result, group_id=group_id, is_debug=is_debug_group)
            if is_debug_group:
                print(f"[DEBUG] Extracted sources: {extracted_sources}]", flush=True)
                print(f"[DEBUG] Number of sources: {len(extracted_sources)}]", flush=True)

            if is_debug_group and settings.V3_DRIFT_DEBUG_TERM_SCAN and extracted_sources:
                term_groups = {
                    "Q-D1_warranty_emergency": [
                        "telephone",
                        "emergency",
                        "burst pipe",
                        "promptly notify",
                        "relieves",
                        "builder",
                    ],
                    "Q-D2_pma_reservations": [
                        "confirmed reservations",
                        "honor all confirmed reservations",
                        "owner shall honor",
                        "terminated",
                        "termination",
                        "sold",
                        "sale",
                    ],
                    "Q-D3_timeframes": [
                        "re:\\b\\d+\\s+business\\s+days\\b",
                        "re:\\b\\d+\\s+days\\b",
                        "arbitration",
                        "written notice",
                    ],
                }

                self._debug_term_scan(
                    where="extracted_sources",
                    items=extracted_sources,
                    term_groups=term_groups,
                    get_text=lambda s: s.get("text") if isinstance(s, dict) else "",
                    get_id=lambda s: s.get("id") if isinstance(s, dict) else None,
                    get_doc_ids=lambda s: None,
                )
            
            response = {
                "answer": answer,
                "confidence": 0.85,  # DRIFT doesn't provide score
                "iterations": safe_depth,
                "sources": extracted_sources,
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
                CALL db.index.vector.queryNodes('entity_embedding', $fetch_k, $embedding)
                YIELD node, score
                WITH node, score
                WHERE node.group_id = $group_id
                RETURN node.id AS id, node.name AS name, node.description AS description, score
                ORDER BY score DESC
                LIMIT $top_k
                """
                
                records, _, _ = self.driver.execute_query(
                    vector_query,
                    embedding=query_embedding,
                    top_k=10,
                    fetch_k=250,
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
    Only use the provided context. If the answer is not present, respond with: "Not specified in the provided documents.".

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
    
    def _extract_sources(self, result: Any, group_id: str = "", is_debug: bool = False) -> List[Dict[str, Any]]:
        """Extract source references from a DRIFT SearchResult.

        MS GraphRAG DRIFT returns nested context_data shaped like:
            {"<sub_query>": {"sources": DataFrame, "entities": DataFrame, ...}, ...}

        We normalize this to a V3-friendly list of dicts.
        """
        extracted: list[dict[str, Any]] = []

        if is_debug:
            print(f"[DEBUG] _extract_sources() called]", flush=True)
            print(f"[DEBUG] result has context_data: {hasattr(result, 'context_data')}]", flush=True)

        if not (hasattr(result, "context_data") and result.context_data):
            if is_debug:
                print(f"[DEBUG] No context_data available or it's empty]", flush=True)
            return []

        context_data = result.context_data
        if not isinstance(context_data, dict):
            if is_debug:
                print(f"[DEBUG] context_data is not a dict: {type(context_data)}]", flush=True)
            return []

        if is_debug:
            print(f"[DEBUG] top-level context_data keys: {list(context_data.keys())[:10]}]", flush=True)

        seen: set[tuple[str, str]] = set()

        for sub_query, sub_ctx in context_data.items():
            if not isinstance(sub_ctx, dict):
                continue

            sources_df = sub_ctx.get("sources")
            if sources_df is None:
                continue

            # sources_df is typically a pandas DataFrame with columns: id, text, ...
            try:
                rows = sources_df.to_dict("records") if hasattr(sources_df, "to_dict") else []
            except Exception:
                rows = []

            for row in rows:
                if not isinstance(row, dict):
                    continue
                sid = str(row.get("id") or "").strip()
                text = str(row.get("text") or "").strip()
                if not sid and not text:
                    continue

                key = (sid, text[:80])
                if key in seen:
                    continue
                seen.add(key)

                extracted.append(
                    {
                        "id": sid or None,
                        "type": "text_unit",
                        "text": text[:5000] if text else None,
                        "sub_query": str(sub_query)[:500],
                    }
                )

        if is_debug:
            print(f"[DEBUG] Extracted {len(extracted)} sources from nested context_data]", flush=True)

        return extracted
    
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
        
        is_debug_group = (
            settings.V3_DRIFT_DEBUG_LOGGING and 
            (settings.V3_DRIFT_DEBUG_GROUP_ID is None or settings.V3_DRIFT_DEBUG_GROUP_ID == group_id)
        )
        
        # Load both data sources
        chunks_df = self.load_text_chunks(group_id)
        raptor_df = self.load_raptor_nodes(group_id)
        
        if is_debug_group:
            print(f"[DEBUG] load_text_units_with_raptor_as_graphrag_models: group={group_id}]", flush=True)
            print(f"[DEBUG]   Loaded {len(chunks_df)} text chunks from Neo4j]", flush=True)
            print(f"[DEBUG]   Loaded {len(raptor_df)} RAPTOR nodes from Neo4j]", flush=True)
            if len(chunks_df) > 0:
                print(f"[DEBUG]   Sample chunk (first row): {chunks_df.iloc[0].to_dict() if len(chunks_df) > 0 else 'N/A'}]", flush=True)
        
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
        
        if is_debug_group:
            print(f"[DEBUG] Converted {len(chunks_df)} text chunks + {len(raptor_df)} RAPTOR nodes "
                       f"= {len(text_units)} total text units for DRIFT search (group {group_id})")
            if text_units:
                print(f"[DEBUG] First text unit sample: id={text_units[0].id}, text_len={len(text_units[0].text or '')}]", flush=True)
        
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
                embedding = [0.0] * 3072  # 3072 dimensions for text-embedding-3-large
            
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
        index_name: str = "entity_embedding",
        embedding_dimension: int = 3072,
    ):
        """
        Initialize Neo4j vector store adapter.
        
        Args:
            driver: Neo4j driver instance
            group_id: Tenant identifier for filtering
            index_name: Name of the Neo4j vector index
            embedding_dimension: Dimension of embeddings (default: 3072 for text-embedding-3-large)
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
        
        # Important: Neo4j vector indexes are global; if multiple group_ids share the same index,
        # a small top-k can easily return only other tenants' nodes. Oversample, then filter and trim.
        # We also do a single adaptive retry with a larger fetch_k when tenant hits are 0.
        def _run_query(fetch_k_val: int) -> list[Any]:
            query = """
            CALL db.index.vector.queryNodes($index_name, $fetch_k, $embedding)
            YIELD node, score
            WITH node, score
            WHERE node.group_id = $group_id
            RETURN node.id AS id, node.name AS text, node.embedding AS vector, score
            ORDER BY score DESC
            LIMIT $k
            """

            recs, _, _ = self.driver.execute_query(
                query,
                index_name=self.index_name,
                fetch_k=fetch_k_val,
                k=k,
                embedding=query_embedding,
                group_id=self.group_id,
            )
            return list(recs or [])

        fetch_k = min(max(int(k) * 25, int(k)), 500)
        records = _run_query(fetch_k)

        is_debug_group = (
            settings.V3_DRIFT_DEBUG_LOGGING
            and (settings.V3_DRIFT_DEBUG_GROUP_ID is None or settings.V3_DRIFT_DEBUG_GROUP_ID == self.group_id)
        )
        used_in_memory_fallback = False
        neo4j_hit_count = len(records)

        # Adaptive retry: if we got 0 in-tenant hits, check whether the index produced global hits.
        # If it did, we likely missed tenant items due to cross-tenant competition in the top-K.
        # Retry once with a larger fetch_k (bounded) before falling back to in-memory similarity.
        if neo4j_hit_count == 0 and query_embedding:
            diag_total_hits: int | None = None
            diag_tenant_hits: int | None = None
            try:
                diag_query = """
                CALL db.index.vector.queryNodes($index_name, $fetch_k, $embedding)
                YIELD node, score
                RETURN
                    count(*) AS total_hits,
                    sum(CASE WHEN node.group_id = $group_id THEN 1 ELSE 0 END) AS tenant_hits,
                    collect(DISTINCT coalesce(node.group_id, '<missing>'))[0..5] AS sample_group_ids,
                    head(collect(coalesce(node.id, '<missing>'))) AS sample_node_id
                """
                diag_records, _, _ = self.driver.execute_query(
                    diag_query,
                    index_name=self.index_name,
                    fetch_k=fetch_k,
                    embedding=query_embedding,
                    group_id=self.group_id,
                )
                if diag_records:
                    d = diag_records[0]
                    diag_total_hits = int(d.get("total_hits") or 0)
                    diag_tenant_hits = int(d.get("tenant_hits") or 0)
                    if is_debug_group:
                        print(
                            "[DRIFT_DEBUG] vectorstore_diag(entity): "
                            f"index={self.index_name} total_hits={d.get('total_hits')} tenant_hits={d.get('tenant_hits')} "
                            f"sample_group_ids={d.get('sample_group_ids')} sample_node_id={d.get('sample_node_id')}]",
                            flush=True,
                        )
            except Exception as e:
                if is_debug_group:
                    print(
                        f"[DRIFT_DEBUG] vectorstore_diag(entity) failed: {type(e).__name__}: {e}]",
                        flush=True,
                    )

            should_retry = (diag_total_hits is None) or (diag_total_hits > 0 and (diag_tenant_hits or 0) == 0)
            if should_retry:
                retry_fetch_k = min(max(fetch_k * 4, 2000), 5000)
                if retry_fetch_k > fetch_k:
                    if is_debug_group:
                        print(
                            f"[DRIFT_DEBUG] vectorstore_retry(entity): index={self.index_name} fetch_k={fetch_k} -> {retry_fetch_k}]",
                            flush=True,
                        )
                    fetch_k = retry_fetch_k
                    records = _run_query(fetch_k)
                    neo4j_hit_count = len(records)

        # (Diagnostics are emitted above as part of adaptive retry; no extra pass here.)
        
        results: list[Any] = []
        for record in records:
            from graphrag.vector_stores.base import VectorStoreDocument
            doc = VectorStoreDocument(
                id=record["id"],
                text=record["text"] or "",
                vector=record["vector"],
            )
            results.append(
                VectorStoreSearchResult(
                    document=doc,
                    score=record["score"],
                )
            )

        # If Neo4j vector search yields no in-tenant hits, fall back to in-memory
        # similarity over any preloaded documents. Without this, selected_entities
        # can be empty, which produces empty context_records and thus no sources.
        if not results and self._documents and query_embedding:
            used_in_memory_fallback = True
            scored: list[tuple[float, Any]] = []
            for doc in self._documents.values():
                vec = getattr(doc, "vector", None)
                if not vec or len(vec) != len(query_embedding):
                    continue
                score = _cosine_similarity(query_embedding, vec)
                scored.append((score, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            for score, doc in scored[:k]:
                results.append(VectorStoreSearchResult(document=doc, score=score))

        if is_debug_group:
            print(
                f"[DRIFT_DEBUG] vectorstore(entity): neo4j_hits={neo4j_hit_count} result_count={len(results)} "
                f"in_memory_fallback={used_in_memory_fallback} cached_docs={len(self._documents)} k={k} fetch_k={fetch_k}]",
                flush=True,
            )

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
