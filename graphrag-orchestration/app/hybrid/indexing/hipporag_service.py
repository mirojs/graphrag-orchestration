"""
HippoRAG Service - Wrapper for HippoRAG 2 Integration

Provides a clean interface for initializing and using HippoRAG
within the Hybrid Pipeline architecture.

Key Features:
- Automatic initialization from dual index
- Personalized PageRank (PPR) retrieval
- Integration with Neo4j graph store
"""

from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path
import structlog

logger = structlog.get_logger(__name__)

# Try to import HippoRAG, fallback gracefully if not installed
try:
    from hipporag import HippoRAG
    HIPPORAG_AVAILABLE = True
except ImportError:
    HIPPORAG_AVAILABLE = False
    logger.warning("hipporag_not_installed",
                  message="Install with: pip install hipporag")


class HippoRAGService:
    """
    Service for managing HippoRAG instances for the Hybrid Pipeline.
    
    HippoRAG uses Personalized PageRank (PPR) for deterministic
    multi-hop retrieval - critical for audit-grade accuracy.
    """
    
    def __init__(
        self,
        group_id: str = "default",
        index_dir: str = "./hipporag_index",
        llm_model: str = "gpt-4o",
        embedding_model: str = "text-embedding-3-small"
    ):
        """
        Initialize HippoRAG service for a specific group.
        
        Args:
            group_id: Tenant identifier
            index_dir: Base directory for HippoRAG indexes
            llm_model: LLM model for query understanding
            embedding_model: Embedding model for entity matching
        """
        self.group_id = group_id
        self.index_dir = Path(index_dir) / group_id
        self.llm_model = llm_model
        self.embedding_model = embedding_model
        
        self._instance: Optional[Any] = None
        self._initialized = False
        
        logger.info("hipporag_service_created",
                   group_id=group_id,
                   index_dir=str(self.index_dir),
                   hipporag_available=HIPPORAG_AVAILABLE)
    
    @property
    def is_available(self) -> bool:
        """Check if HippoRAG is installed and can be used."""
        return HIPPORAG_AVAILABLE
    
    async def initialize(self) -> bool:
        """
        Initialize HippoRAG instance from the synced index.
        
        Returns:
            True if initialization succeeded, False otherwise.
        """
        if not HIPPORAG_AVAILABLE:
            logger.warning("hipporag_init_skipped_not_installed")
            return False
        
        if self._initialized:
            logger.info("hipporag_already_initialized")
            return True
        
        try:
            # Check if index exists
            triples_path = self.index_dir / "hipporag_triples.json"
            if not triples_path.exists():
                logger.warning("hipporag_index_not_found",
                             expected_path=str(triples_path))
                return False
            
            # Initialize HippoRAG
            logger.info("initializing_hipporag",
                       save_dir=str(self.index_dir),
                       llm_model=self.llm_model)
            
            self._instance = HippoRAG(
                save_dir=str(self.index_dir),
                llm_model_name=self.llm_model,
                embedding_model_name=self.embedding_model
            )
            
            self._initialized = True
            logger.info("hipporag_initialized_successfully")
            return True
            
        except Exception as e:
            logger.error("hipporag_initialization_failed", error=str(e))
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
                       top_k=top_k)
            
            # HippoRAG retrieve returns ranked entities
            if self._instance is not None:
                results = self._instance.retrieve(
                    query=query,
                    top_k=top_k
                )
            else:
                results = []
            
            logger.info("hipporag_retrieve_complete",
                       num_results=len(results))
            
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
        return {
            "available": HIPPORAG_AVAILABLE,
            "initialized": self._initialized,
            "group_id": self.group_id,
            "index_dir": str(self.index_dir),
            "index_exists": self.index_dir.exists(),
            "has_triples": (self.index_dir / "hipporag_triples.json").exists()
        }
    
    def get_instance(self) -> Optional[Any]:
        """Get the raw HippoRAG instance (for direct access)."""
        return self._instance


# Singleton cache for HippoRAG services per group
_hipporag_cache: Dict[str, HippoRAGService] = {}


def get_hipporag_service(
    group_id: str,
    index_dir: str = "./hipporag_index"
) -> HippoRAGService:
    """
    Get or create a HippoRAG service for the given group.
    
    Uses singleton pattern to avoid re-initialization.
    """
    cache_key = f"{group_id}:{index_dir}"
    
    if cache_key not in _hipporag_cache:
        _hipporag_cache[cache_key] = HippoRAGService(
            group_id=group_id,
            index_dir=index_dir
        )
    
    return _hipporag_cache[cache_key]
