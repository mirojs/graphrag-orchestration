"""
HippoRAG Service - Wrapper for HippoRAG 2 Integration

Provides a clean interface for initializing and using HippoRAG
within the Hybrid Pipeline architecture.

Key Features:
- Automatic initialization from dual index
- Personalized PageRank (PPR) retrieval
- Integration with Neo4j graph store
- LlamaIndex-native retriever with Azure MI support

Migration Note:
As of 2025-01, this service now prefers the LlamaIndex-native HippoRAGRetriever
over the upstream `hipporag` package. The native implementation provides:
- Direct Azure Managed Identity integration
- No external API key dependencies
- Full LlamaIndex BaseRetriever compatibility
"""

from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import json
import structlog

logger = structlog.get_logger(__name__)

# Try to import LlamaIndex-native HippoRAG retriever (preferred)
try:
    from src.worker.hybrid.retrievers.hipporag_retriever import (
        HippoRAGRetriever,
        HippoRAGRetrieverConfig,
        create_hipporag_retriever_from_service,
    )
    LLAMAINDEX_HIPPORAG_AVAILABLE = True
except ImportError:
    LLAMAINDEX_HIPPORAG_AVAILABLE = False
    HippoRAGRetriever = None  # type: ignore
    HippoRAGRetrieverConfig = None  # type: ignore
    create_hipporag_retriever_from_service = None  # type: ignore
    logger.warning("llamaindex_hipporag_not_available",
                  message="LlamaIndex HippoRAG retriever not importable")

# Try to import upstream HippoRAG as fallback
try:
    from hipporag import HippoRAG
    HIPPORAG_AVAILABLE = True
except ImportError:
    HIPPORAG_AVAILABLE = False
    logger.info("upstream_hipporag_not_installed",
               message="Using LlamaIndex-native implementation")


class HippoRAGService:
    """
    Service for managing HippoRAG instances for the Hybrid Pipeline.
    
    HippoRAG uses Personalized PageRank (PPR) for deterministic
    multi-hop retrieval - critical for audit-grade accuracy.
    
    Implementation Priority:
    1. LlamaIndex-native HippoRAGRetriever (Azure MI, no external deps)
    2. Upstream hipporag package (if installed)
    3. Local PPR fallback (if triples file exists)
    """
    
    def __init__(
        self,
        group_id: str = "default",
        index_dir: str = "./hipporag_index",
        llm_model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-small",
        graph_store: Optional[Any] = None,
        llm_service: Optional[Any] = None,
    ):
        """
        Initialize HippoRAG service for a specific group.
        
        Args:
            group_id: Tenant identifier
            index_dir: Base directory for HippoRAG indexes
            llm_model: LLM model for query understanding
            embedding_model: Embedding model for entity matching
            graph_store: Neo4j graph store (enables LlamaIndex-native retriever)
            llm_service: LLMService instance (provides Azure OpenAI LLM/embed)
        """
        self.group_id = group_id
        self.index_dir = Path(index_dir) / group_id
        self.llm_model = llm_model
        self.embedding_model = embedding_model
        self.graph_store = graph_store
        self.llm_service = llm_service
        
        self._instance: Optional[Any] = None
        self._llamaindex_retriever: Optional[Any] = None
        self._initialized = False
        self._use_llamaindex = False
        
        logger.info("hipporag_service_created",
                   group_id=group_id,
                   index_dir=str(self.index_dir),
                   llamaindex_available=LLAMAINDEX_HIPPORAG_AVAILABLE,
                   hipporag_available=HIPPORAG_AVAILABLE,
                   has_graph_store=graph_store is not None)
    
    @property
    def is_available(self) -> bool:
        """Check if any HippoRAG implementation is available."""
        return LLAMAINDEX_HIPPORAG_AVAILABLE or HIPPORAG_AVAILABLE
    
    @property
    def is_llamaindex_mode(self) -> bool:
        """Check if using LlamaIndex-native retriever."""
        return self._use_llamaindex
    
    async def initialize(self) -> bool:
        """
        Initialize HippoRAG instance using best available implementation.
        
        Priority:
        1. LlamaIndex-native HippoRAGRetriever (if graph_store provided)
        2. Upstream hipporag package
        3. Local PPR fallback
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        if self._initialized:
            logger.info("hipporag_already_initialized", 
                       mode="llamaindex" if self._use_llamaindex else "legacy")
            return True
        
        # Priority 1: LlamaIndex-native retriever (preferred)
        if LLAMAINDEX_HIPPORAG_AVAILABLE and self.graph_store is not None:
            try:
                logger.info("initializing_llamaindex_hipporag",
                           group_id=self.group_id)
                
                # Import dynamically to satisfy type checker
                from src.worker.hybrid.retrievers.hipporag_retriever import (
                    HippoRAGRetriever as _HippoRAGRetriever,
                    HippoRAGRetrieverConfig as _HippoRAGRetrieverConfig,
                    create_hipporag_retriever_from_service as _create_retriever,
                )
                
                config = _HippoRAGRetrieverConfig(
                    top_k=15,
                    damping_factor=0.85,
                    max_iterations=20,
                )
                
                if self.llm_service is not None:
                    self._llamaindex_retriever = _create_retriever(
                        graph_store=self.graph_store,
                        llm_service=self.llm_service,
                        config=config,
                        group_id=self.group_id,
                    )
                else:
                    self._llamaindex_retriever = _HippoRAGRetriever(
                        graph_store=self.graph_store,
                        config=config,
                        group_id=self.group_id,
                    )
                
                self._initialized = True
                self._use_llamaindex = True
                logger.info("llamaindex_hipporag_initialized_successfully",
                           stats=self._llamaindex_retriever.get_graph_stats())
                return True
                
            except Exception as e:
                logger.warning("llamaindex_hipporag_init_failed", 
                              error=str(e),
                              fallback="upstream_or_local")
        
        # Priority 2: Upstream hipporag package
        if HIPPORAG_AVAILABLE:
            try:
                triples_path = self.index_dir / "hipporag_triples.json"
                if not triples_path.exists():
                    logger.warning("hipporag_index_not_found",
                                 expected_path=str(triples_path))
                else:
                    logger.info("initializing_upstream_hipporag",
                               save_dir=str(self.index_dir),
                               llm_model=self.llm_model)
                    
                    self._instance = HippoRAG(
                        save_dir=str(self.index_dir),
                        llm_model_name=self.llm_model,
                        embedding_model_name=self.embedding_model
                    )
                    
                    self._initialized = True
                    self._use_llamaindex = False
                    logger.info("upstream_hipporag_initialized_successfully")
                    return True
                    
            except Exception as e:
                logger.warning("upstream_hipporag_init_failed", error=str(e))
        
        # Priority 3: Local PPR fallback
        triples_path = self.index_dir / "hipporag_triples.json"
        if triples_path.exists():
            try:
                self._instance = _LocalPPRHippoRAG(triples_path)
                self._initialized = True
                self._use_llamaindex = False
                logger.warning(
                    "hipporag_fallback_local_ppr_enabled",
                    triples_path=str(triples_path),
                )
                return True
            except Exception as e:
                logger.error("hipporag_fallback_local_ppr_failed", error=str(e))
        
        logger.error("hipporag_all_init_methods_failed")
        return False
    
    async def retrieve(
        self,
        query: str,
        seed_entities: Optional[List[str]] = None,
        top_k: int = 15
    ) -> List[Tuple[str, float]]:
        """
        Retrieve relevant entities using Personalized PageRank.
        
        Args:
            query: The user's query
            seed_entities: Optional list of entities to start from
            top_k: Number of top results to return
            
        Returns:
            List of (entity_name, ppr_score) tuples, ranked by relevance.
        """
        if not self._initialized:
            initialized = await self.initialize()
            if not initialized:
                logger.warning("hipporag_retrieve_fallback",
                             reason="not_initialized")
                return []
        
        try:
            logger.info("hipporag_retrieve_start",
                       query=query[:50],
                       num_seeds=len(seed_entities) if seed_entities else 0,
                       top_k=top_k,
                       mode="llamaindex" if self._use_llamaindex else "legacy")
            
            # Use LlamaIndex retriever if available
            if self._use_llamaindex and self._llamaindex_retriever is not None:
                from llama_index.core.schema import QueryBundle
                
                if seed_entities:
                    # Use pre-extracted seeds
                    nodes = self._llamaindex_retriever.retrieve_with_seeds(
                        query=query,
                        seed_entities=seed_entities,
                        top_k=top_k,
                    )
                else:
                    # Let retriever extract seeds
                    query_bundle = QueryBundle(query_str=query)
                    nodes = await self._llamaindex_retriever._aretrieve(query_bundle)
                
                # Convert NodeWithScore to (entity_name, score) tuples
                results = [
                    (node.node.metadata.get("entity_name", node.node.id_), node.score)
                    for node in nodes[:top_k]
                ]
                
                logger.info("hipporag_retrieve_complete",
                           num_results=len(results),
                           mode="llamaindex")
                return results
            
            # Legacy path: use upstream hipporag or local PPR
            results: Any
            if self._instance is None:
                results = []
            else:
                try:
                    results = self._instance.retrieve(
                        query=query,
                        top_k=top_k,
                        seeds=seed_entities,
                    )
                except TypeError:
                    # Fallback implementations may expose different kwarg names.
                    results = self._instance.retrieve(
                        query=query,
                        top_k=top_k,
                        seed_entities=seed_entities,
                    )
            
            logger.info("hipporag_retrieve_complete",
                       num_results=len(results),
                       mode="legacy")
            
            return results
            
        except Exception as e:
            logger.error("hipporag_retrieve_failed", error=str(e))
            return []
    
    async def get_entity_context(
        self,
        entity_name: str
    ) -> Dict[str, Any]:
        """
        Get full context for a specific entity.
        
        Returns entity details, related entities, and source texts.
        """
        try:
            # Load entity texts mapping
            entity_texts_path = self.index_dir / "entity_texts.json"
            if entity_texts_path.exists():
                import json
                with open(entity_texts_path) as f:
                    entity_texts = json.load(f)
                texts = entity_texts.get(entity_name, [])
            else:
                texts = []
            
            # Load entity index for metadata
            entity_index_path = self.index_dir / "entity_index.json"
            if entity_index_path.exists():
                import json
                with open(entity_index_path) as f:
                    entity_index = json.load(f)
                metadata = entity_index.get(entity_name, {})
            else:
                metadata = {}
            
            return {
                "entity": entity_name,
                "metadata": metadata,
                "source_texts": texts,
                "num_sources": len(texts)
            }
            
        except Exception as e:
            logger.error("get_entity_context_failed",
                        entity=entity_name,
                        error=str(e))
            return {
                "entity": entity_name,
                "error": str(e)
            }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health status of HippoRAG service."""
        health = {
            "llamaindex_available": LLAMAINDEX_HIPPORAG_AVAILABLE,
            "upstream_available": HIPPORAG_AVAILABLE,
            "initialized": self._initialized,
            "mode": "llamaindex" if self._use_llamaindex else "legacy",
            "group_id": self.group_id,
            "index_dir": str(self.index_dir),
            "index_exists": self.index_dir.exists(),
            "has_triples": (self.index_dir / "hipporag_triples.json").exists(),
            "has_graph_store": self.graph_store is not None,
            "has_llm_service": self.llm_service is not None,
        }
        
        # Add graph stats if using LlamaIndex mode
        if self._use_llamaindex and self._llamaindex_retriever is not None:
            health["graph_stats"] = self._llamaindex_retriever.get_graph_stats()
        
        return health
    
    def get_instance(self) -> Optional[Any]:
        """Get the raw HippoRAG instance (for direct access)."""
        return self._instance
    
    def get_llamaindex_retriever(self) -> Optional[Any]:
        """Get the LlamaIndex HippoRAG retriever (if available)."""
        return self._llamaindex_retriever


class _LocalPPRHippoRAG:
    """Deterministic Personalized PageRank over a HippoRAG triple index.

    This is used as a fallback when the upstream HippoRAG class cannot be
    initialized due to missing LLM/embedding credentials. It only supports
    seed-based retrieval.
    """

    def __init__(self, triples_path: Path):
        self._triples_path = triples_path
        self._adj: Dict[str, List[str]] = {}
        self._rev_adj: Dict[str, List[str]] = {}
        self._nodes: List[str] = []
        self._nodes_lc: Dict[str, str] = {}
        self._load_triples()

    def _load_triples(self) -> None:
        with open(self._triples_path) as f:
            triples = json.load(f)

        adj: Dict[str, List[str]] = {}
        rev: Dict[str, List[str]] = {}
        nodes: set[str] = set()

        for t in triples:
            if not isinstance(t, list) or len(t) < 3:
                continue
            s, _, o = t[0], t[1], t[2]
            if not isinstance(s, str) or not isinstance(o, str):
                continue
            nodes.add(s)
            nodes.add(o)
            adj.setdefault(s, []).append(o)
            adj.setdefault(o, [])
            rev.setdefault(o, []).append(s)
            rev.setdefault(s, [])

        self._adj = adj
        self._rev_adj = rev
        self._nodes = sorted(nodes)
        self._nodes_lc = {n: n.lower() for n in self._nodes}

    def _normalize(self, text: str) -> str:
        return " ".join(text.lower().strip().split())

    def _expand_seeds(self, seed_list: List[str], max_per_seed: int = 3) -> List[str]:
        """Map free-form seed phrases to concrete node names using lightweight fuzzy matching."""

        expanded: List[str] = []
        for seed in seed_list:
            seed_norm = self._normalize(seed)
            if not seed_norm:
                continue

            # Exact (case-insensitive)
            for n, n_lc in self._nodes_lc.items():
                if n_lc == seed_norm:
                    expanded.append(n)
                    break

            # Substring hits
            substring_hits: List[str] = []
            for n, n_lc in self._nodes_lc.items():
                if seed_norm in n_lc or n_lc in seed_norm:
                    substring_hits.append(n)
            if substring_hits:
                expanded.extend(substring_hits[:max_per_seed])
                continue

            # Token overlap (Jaccard on word sets)
            seed_tokens = set(seed_norm.split())
            if not seed_tokens:
                continue

            scored: List[Tuple[float, str]] = []
            for n, n_lc in self._nodes_lc.items():
                n_tokens = set(n_lc.split())
                if not n_tokens:
                    continue
                inter = len(seed_tokens & n_tokens)
                if inter == 0:
                    continue
                score = inter / float(len(seed_tokens | n_tokens))
                scored.append((score, n))

            scored.sort(key=lambda x: x[0], reverse=True)
            expanded.extend([n for _s, n in scored[:max_per_seed]])

        # De-dupe while preserving order
        seen: set[str] = set()
        deduped: List[str] = []
        for n in expanded:
            if n not in seen:
                seen.add(n)
                deduped.append(n)
        return deduped

    def _degree_seeds(self, k: int = 5) -> List[str]:
        degrees: List[Tuple[int, str]] = []
        for n in self._nodes:
            out_d = len(self._adj.get(n, []))
            in_d = len(self._rev_adj.get(n, []))
            degrees.append((out_d + in_d, n))
        degrees.sort(key=lambda x: x[0], reverse=True)
        return [n for _d, n in degrees[:k]]

    def retrieve(
        self,
        query: str,
        top_k: int = 15,
        seeds: Optional[List[str]] = None,
        seed_entities: Optional[List[str]] = None,
        **_: Any,
    ) -> List[Tuple[str, float]]:
        seed_list = seeds or seed_entities or []
        seed_list = [s for s in seed_list if isinstance(s, str)]
        if not self._nodes:
            return []

        # If seeds don't match node names, expand via fuzzy mapping.
        expanded = self._expand_seeds(seed_list)
        if not expanded:
            # No usable seeds: fall back to high-degree nodes so we can still
            # produce evidence for generic summary queries.
            expanded = self._degree_seeds(k=5)

        damping = 0.85
        max_iter = 20

        # personalization vector over nodes
        p: Dict[str, float] = {n: 0.0 for n in self._nodes}
        for s in expanded:
            if s in p:
                p[s] += 1.0
        total_p = sum(p.values())
        if total_p <= 0:
            return []
        for n in p:
            p[n] /= total_p

        # initialize rank to personalization
        rank: Dict[str, float] = dict(p)

        for _i in range(max_iter):
            new_rank: Dict[str, float] = {n: (1.0 - damping) * p[n] for n in self._nodes}
            for u, outs in self._adj.items():
                if not outs:
                    continue
                share = damping * rank.get(u, 0.0) / float(len(outs))
                if share == 0.0:
                    continue
                for v in outs:
                    if v in new_rank:
                        new_rank[v] += share
            rank = new_rank

        ranked = sorted(rank.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:top_k]


# Singleton cache for HippoRAG services per group
_hipporag_cache: Dict[str, HippoRAGService] = {}


def get_hipporag_service(
    group_id: str,
    index_dir: str = "./hipporag_index",
    graph_store: Optional[Any] = None,
    llm_service: Optional[Any] = None,
) -> HippoRAGService:
    """
    Get or create a HippoRAG service for the given group.
    
    Uses singleton pattern to avoid re-initialization.
    
    Args:
        group_id: Tenant identifier
        index_dir: Base directory for HippoRAG indexes
        graph_store: Neo4j graph store (enables LlamaIndex-native retriever)
        llm_service: LLMService instance (provides Azure OpenAI LLM/embed)
        
    Returns:
        HippoRAGService instance
    """
    cache_key = f"{group_id}:{index_dir}"
    
    if cache_key not in _hipporag_cache:
        _hipporag_cache[cache_key] = HippoRAGService(
            group_id=group_id,
            index_dir=index_dir,
            graph_store=graph_store,
            llm_service=llm_service,
        )
    elif graph_store is not None or llm_service is not None:
        # Update existing service with new dependencies if provided
        existing = _hipporag_cache[cache_key]
        if graph_store is not None and existing.graph_store is None:
            existing.graph_store = graph_store
            existing._initialized = False  # Force re-initialization
        if llm_service is not None and existing.llm_service is None:
            existing.llm_service = llm_service
            existing._initialized = False
    
    return _hipporag_cache[cache_key]
