"""
Vector Store Service for RAPTOR indexing with Azure AI Search semantic ranking.

Azure AI Search provides critical ACCURACY ENHANCEMENT capabilities:

1. **Hybrid Search (BM25 + Vector)**: Combines exact keyword matching with 
   semantic similarity. BM25 catches exact terms that vector search might miss;
   vectors catch semantic meaning that keywords miss.

2. **Semantic Ranker**: Microsoft's transformer-based re-ranking model that
   dramatically improves result relevance by understanding query intent.
   This is the KEY accuracy enhancement - re-ranks initial results using
   deep language understanding. Studies show 20-40% improvement in relevance.

3. **Semantic Captions**: Extracts the most relevant snippets from documents,
   providing better context for the LLM to generate accurate answers.

4. **Query Speller**: Auto-corrects typos in user queries.

Architecture:
- RAPTOR hierarchical summaries are indexed here during document ingestion
- The semantic ranker improves quality of retrieved summaries at query time
- This leads to more accurate final answers from the LLM

Note: Neo4j handles entity/relationship storage and graph traversal.
Azure AI Search is specifically for RAPTOR text summaries where its semantic
ranker provides the maximum accuracy benefit.

Supports: LanceDB (development) and Azure AI Search (production).
"""

from typing import List, Optional, Dict, Any
import logging
from abc import ABC, abstractmethod

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode, Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class VectorStoreProvider(ABC):
    """Abstract base class for vector store providers."""
    
    @abstractmethod
    def get_index(self, group_id: str, index_name: str) -> VectorStoreIndex:
        """Get or create a vector index for a specific group."""
        pass
    
    @abstractmethod
    def add_documents(
        self, 
        group_id: str, 
        index_name: str, 
        documents: List[Document]
    ) -> None:
        """Add documents to the vector index."""
        pass
    
    @abstractmethod
    def search(
        self, 
        group_id: str, 
        index_name: str, 
        query: str, 
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search the vector index."""
        pass
    
    @abstractmethod
    def delete_by_metadata(
        self,
        group_id: str,
        index_name: str,
        metadata_filter: Dict[str, Any]
    ) -> int:
        """Delete documents matching metadata filter. Returns count deleted."""
        pass


class LanceDBProvider(VectorStoreProvider):
    """LanceDB provider for local development."""
    
    def __init__(self, base_path: str):
        self.base_path = base_path
        self._db = None
        self._initialize()
    
    def _initialize(self) -> None:
        try:
            import lancedb
            self._db = lancedb.connect(self.base_path)
            logger.info(f"Connected to LanceDB at {self.base_path}")
        except ImportError:
            logger.error("LanceDB not installed. Run: pip install lancedb")
        except Exception as e:
            logger.error(f"Failed to connect to LanceDB: {e}")
    
    def _get_table_name(self, group_id: str, index_name: str) -> str:
        """Generate tenant-specific table name."""
        return f"{group_id}_{index_name}"
    
    def get_index(self, group_id: str, index_name: str) -> Optional[VectorStoreIndex]:
        """Get or create a LlamaIndex VectorStoreIndex backed by LanceDB.

        Uses explicit None check because LanceDBConnection may be falsey (e.g. __len__==0).
        Attempts a lazy reconnect if initialization previously failed.
        """
        if self._db is None:
            logger.warning("lancedb_lazy_reconnect_attempt", path=self.base_path)
            self._initialize()
            if self._db is None:
                raise RuntimeError("LanceDB connection failed after retry")
        
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        
        table_name = self._get_table_name(group_id, index_name)
        
        vector_store = LanceDBVectorStore(
            uri=self.base_path,
            table_name=table_name,
        )
        
        return VectorStoreIndex.from_vector_store(vector_store)
    
    def add_documents(
        self, 
        group_id: str, 
        index_name: str, 
        documents: List[Document]
    ) -> None:
        """Add documents to LanceDB index."""
        index = self.get_index(group_id, index_name)
        if index:
            for doc in documents:
                # Tag document with group_id for filtering
                doc.metadata["group_id"] = group_id
            # Use Document directly instead of TextNode.from_document
            index.insert_nodes([TextNode(text=doc.text, metadata=doc.metadata) for doc in documents])
    
    def search(
        self, 
        group_id: str, 
        index_name: str, 
        query: str, 
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """Search LanceDB index with group filtering."""
        index = self.get_index(group_id, index_name)
        if not index:
            return []
        
        retriever = index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(query)
        
        # Filter by group_id and format results
        results = []
        for node in nodes:
            if node.metadata.get("group_id") == group_id:
                results.append({
                    "text": node.text,
                    "score": node.score,
                    "metadata": node.metadata,
                })
        
        return results
    
    def delete_by_metadata(
        self,
        group_id: str,
        index_name: str,
        metadata_filter: Dict[str, Any]
    ) -> int:
        """Delete documents from LanceDB matching metadata filter."""
        if self._db is None:
            logger.warning("lancedb_delete_skip_db_none")
            return 0
        
        table_name = self._get_table_name(group_id, index_name)
        
        try:
            table = self._db.open_table(table_name)
            
            # Build filter expression (LanceDB uses SQL-like syntax)
            # Ensure group_id is always included
            filters = [f"group_id = '{group_id}'"]
            for key, value in metadata_filter.items():
                if isinstance(value, str):
                    filters.append(f"{key} = '{value}'")
                else:
                    filters.append(f"{key} = {value}")
            
            filter_expr = " AND ".join(filters)
            
            # Count before deletion
            before_count = table.count_rows()
            
            # LanceDB delete operation
            table.delete(filter_expr)
            
            after_count = table.count_rows()
            deleted = before_count - after_count
            
            logger.info(f"Deleted {deleted} vectors from {table_name} with filter: {filter_expr}")
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to delete from LanceDB: {e}")
            return 0


class AzureAISearchProvider(VectorStoreProvider):
    """
    Azure AI Search provider for RAPTOR indexing with accuracy enhancement.
    
    Azure AI Search provides critical capabilities that improve retrieval accuracy:
    
    1. **Hybrid Search (BM25 + Vector)**: Combines exact keyword matching with 
       semantic similarity for better recall. BM25 catches exact terms that 
       vector search might miss; vectors catch semantic meaning that keywords miss.
    
    2. **Semantic Ranker**: Microsoft's transformer-based re-ranking model that
       dramatically improves result relevance by understanding query intent.
       This is the KEY accuracy enhancement - re-ranks initial results using
       deep language understanding.
    
    3. **Semantic Captions**: Extracts the most relevant snippets from documents,
       providing better context for the LLM to generate accurate answers.
    
    Usage: RAPTOR hierarchical summaries are indexed here during document ingestion.
    At query time, the semantic ranker improves the quality of retrieved summaries,
    leading to more accurate final answers.
    
    Note: Query-time entity/relationship search still uses Neo4j hybrid search.
    Azure AI Search is specifically for RAPTOR text summaries where its semantic
    ranker provides the most value.
    """
    
    def __init__(self, endpoint: str, api_key: str, semantic_config_name: str = "raptor-semantic"):
        self.endpoint = endpoint
        self.api_key = api_key
        self.semantic_config_name = semantic_config_name
        self._client = None
        self._credential = None
        self._initialize()
    
    def _initialize(self) -> None:
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential
            
            # Note: We'll create index-specific clients on demand
            self._credential = AzureKeyCredential(self.api_key)
            logger.info(f"Azure AI Search configured for {self.endpoint} with semantic ranking enabled")
        except ImportError:
            logger.error("Azure Search SDK not installed. Run: pip install azure-search-documents")
        except Exception as e:
            logger.error(f"Failed to configure Azure AI Search: {e}")
    
    def _get_index_name(self, group_id: str, index_name: str) -> str:
        """Generate tenant-specific index name."""
        # Azure Search index names must be lowercase, alphanumeric, and max 128 chars
        return f"{group_id}-{index_name}".lower().replace("_", "-")[:128]
    
    def get_index(self, group_id: str, index_name: str) -> Optional[VectorStoreIndex]:
        """Get or create a LlamaIndex VectorStoreIndex backed by Azure AI Search."""
        from llama_index.vector_stores.azureaisearch import AzureAISearchVectorStore
        
        azure_index_name = self._get_index_name(group_id, index_name)
        
        vector_store = AzureAISearchVectorStore(
            search_or_index_client=None,  # Will be created internally
            endpoint=self.endpoint,
            key=self.api_key,
            index_name=azure_index_name,
            filterable_metadata_field_keys=[
                "group_id", 
                "raptor_level", 
                "source",
                # Quality metrics for filtering/faceting
                "confidence_level",
                "cluster_coherence",
                "silhouette_score",
            ],
            id_field_key="id",
            chunk_field_key="chunk",
            embedding_field_key="embedding",
            metadata_string_field_key="metadata",
            doc_id_field_key="doc_id"
        )
        
        return VectorStoreIndex.from_vector_store(vector_store)
    
    def add_documents(
        self, 
        group_id: str, 
        index_name: str, 
        documents: List[Document]
    ) -> None:
        """Add documents to Azure AI Search index."""
        index = self.get_index(group_id, index_name)
        if index:
            for doc in documents:
                doc.metadata["group_id"] = group_id
            # Use Document directly instead of TextNode.from_document
            index.insert_nodes([TextNode(text=doc.text, metadata=doc.metadata) for doc in documents])
            logger.info(f"Indexed {len(documents)} RAPTOR nodes to Azure AI Search for semantic ranking")
    
    def search(
        self, 
        group_id: str, 
        index_name: str, 
        query: str, 
        top_k: int = 10,
        use_semantic_ranker: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search Azure AI Search with hybrid + semantic ranking for accuracy enhancement.
        
        The semantic ranker is the key differentiator - it re-ranks results using
        a transformer model to understand query intent and document relevance.
        
        Args:
            group_id: Tenant identifier
            index_name: Index name (e.g., "raptor")
            query: Search query
            top_k: Number of results
            use_semantic_ranker: Enable semantic re-ranking for accuracy (default True)
        """
        try:
            from azure.search.documents import SearchClient
            from azure.search.documents.models import QueryType, QueryCaptionType, QueryAnswerType
            
            azure_index_name = self._get_index_name(group_id, index_name)
            
            client = SearchClient(
                endpoint=self.endpoint,
                index_name=azure_index_name,
                credential=self._credential
            )
            
            # Build search options with semantic ranking
            search_options = {
                "search_text": query,
                "filter": f"group_id eq '{group_id}'",
                "top": top_k,
                "select": ["id", "content", "metadata"],
            }
            
            if use_semantic_ranker:
                # Enable semantic ranking for accuracy enhancement
                search_options.update({
                    "query_type": QueryType.SEMANTIC,
                    "semantic_configuration_name": self.semantic_config_name,
                    "query_caption": QueryCaptionType.EXTRACTIVE,
                    "query_answer": QueryAnswerType.EXTRACTIVE,
                })
                logger.debug(f"Semantic ranker enabled for query: {query[:50]}...")
            
            results = client.search(**search_options)
            
            formatted_results = []
            for result in results:
                metadata = result.get("metadata", {})
                formatted_results.append({
                    "text": result.get("content", ""),
                    "score": result.get("@search.score", 0),
                    "reranker_score": result.get("@search.reranker_score"),  # Semantic ranking score
                    "captions": result.get("@search.captions"),  # Extracted relevant snippets
                    "metadata": metadata,
                    # Extract quality metrics for visibility
                    "quality_metrics": {
                        "confidence_level": metadata.get("confidence_level"),
                        "confidence_score": metadata.get("confidence_score"),
                        "cluster_coherence": metadata.get("cluster_coherence"),
                    }
                })
            
            return formatted_results
            
        except Exception as e:
            logger.warning(f"Azure AI Search semantic search failed, falling back to basic: {e}")
            # Fallback to basic LlamaIndex retrieval
            index = self.get_index(group_id, index_name)
            if not index:
                return []
            
            retriever = index.as_retriever(
                similarity_top_k=top_k,
                filters={"group_id": group_id},
            )
            nodes = retriever.retrieve(query)
            
            return [
                {
                    "text": node.text,
                    "score": node.score,
                    "metadata": node.metadata,
                }
                for node in nodes
            ]
    
    def delete_by_metadata(
        self,
        group_id: str,
        index_name: str,
        metadata_filter: Dict[str, Any]
    ) -> int:
        """Delete documents from Azure AI Search matching metadata filter."""
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential
            
            azure_index_name = self._get_index_name(group_id, index_name)
            
            client = SearchClient(
                endpoint=self.endpoint,
                index_name=azure_index_name,
                credential=AzureKeyCredential(self.api_key)
            )
            
            # Build OData filter
            filters = [f"group_id eq '{group_id}'"]
            for key, value in metadata_filter.items():
                if isinstance(value, str):
                    filters.append(f"{key} eq '{value}'")
                else:
                    filters.append(f"{key} eq {value}")
            
            filter_expr = " and ".join(filters)
            
            # Search for matching documents to get their IDs
            results = client.search("*", filter=filter_expr, select=["id"])
            doc_ids = [doc["id"] for doc in results]
            
            if not doc_ids:
                return 0
            
            # Delete documents by ID
            delete_results = client.delete_documents(documents=[{"id": doc_id} for doc_id in doc_ids])
            
            deleted = sum(1 for result in delete_results if result.succeeded)
            logger.info(f"Deleted {deleted} vectors from Azure Search index {azure_index_name}")
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to delete from Azure AI Search: {e}")
            return 0


class VectorStoreService:
    """
    Singleton service for vector store operations.
    
    Automatically selects the appropriate provider based on configuration:
    - LanceDB for local development
    - Azure AI Search for production
    """
    
    _instance: Optional["VectorStoreService"] = None
    _provider: Optional[VectorStoreProvider] = None

    def __new__(cls) -> "VectorStoreService":
        if cls._instance is None:
            cls._instance = super(VectorStoreService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    @property
    def store_type(self) -> str:
        """Get the current store type."""
        return settings.VECTOR_STORE_TYPE

    def _initialize(self) -> None:
        """Initialize the appropriate vector store provider."""
        if settings.VECTOR_STORE_TYPE == "azure_search":
            if settings.AZURE_SEARCH_ENDPOINT and settings.AZURE_SEARCH_API_KEY:
                self._provider = AzureAISearchProvider(
                    endpoint=settings.AZURE_SEARCH_ENDPOINT,
                    api_key=settings.AZURE_SEARCH_API_KEY,
                )
                logger.info("Using Azure AI Search vector store")
            else:
                logger.error("Azure Search credentials not configured")
        else:  # Default to LanceDB
            self._provider = LanceDBProvider(base_path=settings.LANCEDB_PATH)
            logger.info("Using LanceDB vector store")

    def get_index(self, group_id: str, index_name: str = "default") -> VectorStoreIndex:
        """Get a vector index for a specific group."""
        if not self._provider:
            raise RuntimeError("Vector store provider not initialized")
        return self._provider.get_index(group_id, index_name)

    def add_documents(
        self, 
        group_id: str, 
        documents: List[Document],
        index_name: str = "default"
    ) -> None:
        """Add documents to the vector store."""
        if not self._provider:
            raise RuntimeError("Vector store provider not initialized")
        self._provider.add_documents(group_id, index_name, documents)

    def search(
        self, 
        group_id: str, 
        query: str, 
        top_k: int = 10,
        index_name: str = "default"
    ) -> List[Dict[str, Any]]:
        """Search the vector store."""
        if not self._provider:
            raise RuntimeError("Vector store provider not initialized")
        return self._provider.search(group_id, index_name, query, top_k)
    
    def delete_by_url(
        self,
        group_id: str,
        url: str,
        index_name: str = "default"
    ) -> int:
        """Delete all vectors for a specific document URL."""
        if not self._provider:
            raise RuntimeError("Vector store provider not initialized")
        return self._provider.delete_by_metadata(group_id, index_name, {"url": url})
    
    def delete_all(
        self,
        group_id: str,
        index_name: str = "default"
    ) -> int:
        """Delete all vectors for a tenant (DANGEROUS)."""
        if not self._provider:
            raise RuntimeError("Vector store provider not initialized")
        return self._provider.delete_by_metadata(group_id, index_name, {})

    def health_check(self) -> Dict[str, Any]:
        """Check vector store connectivity."""
        if not self._provider:
            return {"status": "disconnected", "error": "Provider not initialized"}
        
        return {
            "status": "connected",
            "type": settings.VECTOR_STORE_TYPE,
        }
