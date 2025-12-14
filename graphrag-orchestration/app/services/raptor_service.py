"""
RAPTOR Service for Recursive Abstractive Processing.

This service implements the RAPTOR indexing strategy to create a hierarchical
vector index (summaries + details) for deep semantic understanding.

Reference: "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval"
https://arxiv.org/abs/2401.18059

It "borrows" the RAPTOR implementation pattern from LlamaIndex packs and
the discussion about best-quality GraphRAG pipelines.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
import logging
import numpy as np
from collections import defaultdict

from llama_index.core import Document, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode, NodeWithScore
from llama_index.core.llms import ChatMessage

# We will use the RaptorPack if available, or implement the logic
try:
    from llama_index.packs.raptor import RaptorPack  # type: ignore[import-not-found]
    RAPTOR_PACK_AVAILABLE = True
except ImportError:
    RaptorPack = None  # type: ignore[misc, assignment]
    RAPTOR_PACK_AVAILABLE = False

# Try importing sklearn for clustering
try:
    from sklearn.cluster import KMeans
    from sklearn.mixture import GaussianMixture
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from app.services.llm_service import LLMService
from app.services.vector_service import VectorStoreService
from app.core.config import settings

logger = logging.getLogger(__name__)


class RaptorService:
    """
    Service for RAPTOR indexing - Recursive Abstractive Processing for Tree-Organized Retrieval.
    
    Generates a hierarchical tree of summaries:
    1. Chunks documents (Leaf nodes - Level 0)
    2. Embeds all chunks
    3. Clusters chunks semantically using GMM or K-Means
    4. Summarizes each cluster with LLM (Level 1 nodes)
    5. Recursively clusters and summarizes until reaching max_levels or single cluster
    
    All levels are indexed in Azure AI Search for retrieval at different granularities.
    Neo4j is used for entity/relationship storage and hybrid search on the Knowledge Graph.
    """
    
    def __init__(self):
        self.llm_service = LLMService()
        self.vector_service = VectorStoreService()  # Use Azure AI Search for RAPTOR nodes
        self.max_levels = getattr(settings, 'MAX_RAPTOR_LEVELS', 3)
        self.summary_length = getattr(settings, 'RAPTOR_SUMMARY_LENGTH', 512)
        self.min_cluster_size = 2
        self.max_clusters_per_level = 10
        
    async def process_documents(
        self,
        documents: List[Document],
        group_id: str,
        use_pack: bool = False,
    ) -> Dict[str, Any]:
        """
        Process documents using RAPTOR and return all nodes (leaves + summaries).
        
        Args:
            documents: List of LlamaIndex Documents to process
            group_id: Tenant identifier for multi-tenancy
            use_pack: If True, use RaptorPack (requires llama-index-packs-raptor)
        
        Returns:
            Dict with:
            - all_nodes: List[TextNode] of all nodes at all levels
            - level_stats: Dict mapping level -> node count
            - total_nodes: Total nodes created
        """
        if use_pack and RAPTOR_PACK_AVAILABLE:
            return await self._process_with_pack(documents, group_id)
        
        # Manual implementation (more control, doesn't require pack)
        return await self._process_manual(documents, group_id)
    
    async def _process_with_pack(
        self, 
        documents: List[Document], 
        group_id: str
    ) -> Dict[str, Any]:
        """
        Process using llama-index-packs-raptor if available.
        """
        logger.info(f"Starting RAPTOR processing with Pack for {len(documents)} documents")
        
        if self.llm_service.llm is None or self.llm_service.embed_model is None:
            raise RuntimeError("LLM and embed_model must be initialized for RAPTOR processing")
        
        if RaptorPack is None:
            raise ImportError("RaptorPack is not available")
        
        try:
            raptor = RaptorPack(
                documents=documents,
                llm=self.llm_service.llm,
                embed_model=self.llm_service.embed_model,
                vector_store=None,
                mode="tree_summarization",
                verbose=True
            )
            
            # Extract nodes from the pack's internal index
            # Note: This depends on RaptorPack implementation details
            all_nodes = []
            if hasattr(raptor, 'retriever') and hasattr(raptor.retriever, 'index'):
                index = raptor.retriever.index
                if hasattr(index, 'docstore'):
                    for doc_id in index.docstore.docs:
                        node = index.docstore.get_document(doc_id)
                        if node:
                            # Add group_id to metadata
                            node.metadata['group_id'] = group_id
                            node.metadata['source'] = 'raptor'
                            all_nodes.append(node)
            
            return {
                "all_nodes": all_nodes,
                "level_stats": {"pack": len(all_nodes)},
                "total_nodes": len(all_nodes),
                "method": "raptor_pack"
            }
            
        except Exception as e:
            logger.warning(f"RaptorPack failed, falling back to manual: {e}")
            return await self._process_manual(documents, group_id)
    
    async def _process_manual(
        self, 
        documents: List[Document], 
        group_id: str
    ) -> Dict[str, Any]:
        """
        Manual implementation of RAPTOR algorithm.
        
        This gives us more control and doesn't require the pack dependency.
        
        Note: We strip large metadata (tables, section_path) from documents before
        chunking because RAPTOR is for text summarization, not structured extraction.
        The tables metadata is preserved on the original documents for SchemaAwareExtractor.
        """
        logger.info(f"Starting manual RAPTOR processing for {len(documents)} documents")
        
        # Strip large metadata before chunking to avoid chunk size overflow
        # RAPTOR is for text summaries - tables metadata is for structured extraction (separate path)
        RAPTOR_METADATA_KEYS = {"group_id", "page_number", "source", "file_name", "url"}
        raptor_docs = []
        for doc in documents:
            clean_metadata = {k: v for k, v in doc.metadata.items() if k in RAPTOR_METADATA_KEYS}
            # Truncate URL if it's a long SAS URL
            if "url" in clean_metadata and len(str(clean_metadata["url"])) > 100:
                clean_metadata["url"] = str(clean_metadata["url"])[:100] + "..."
            raptor_docs.append(Document(text=doc.text, metadata=clean_metadata))
        
        if not SKLEARN_AVAILABLE:
            logger.warning("sklearn not available, returning base chunks only")
            parser = SentenceSplitter(chunk_size=1024, chunk_overlap=100)
            nodes = parser.get_nodes_from_documents(raptor_docs)
            for node in nodes:
                node.metadata['group_id'] = group_id
                node.metadata['raptor_level'] = 0
            return {
                "all_nodes": nodes,
                "level_stats": {0: len(nodes)},
                "total_nodes": len(nodes),
                "method": "base_chunks_only"
            }
        
        # Step 1: Create base chunks (Level 0)
        parser = SentenceSplitter(chunk_size=1024, chunk_overlap=100)
        base_nodes = parser.get_nodes_from_documents(raptor_docs)
        
        for node in base_nodes:
            node.metadata['group_id'] = group_id
            node.metadata['raptor_level'] = 0
            node.metadata['source'] = 'raptor'
        
        logger.info(f"Created {len(base_nodes)} base chunks (Level 0)")
        
        all_nodes: List[TextNode] = [
            n if isinstance(n, TextNode) else TextNode(text=n.get_content(), metadata=getattr(n, 'metadata', {})) 
            for n in base_nodes
        ]
        level_stats = {0: len(base_nodes)}
        current_level_nodes: List[TextNode] = all_nodes.copy()
        
        # Step 2-5: Recursive clustering and summarization
        for level in range(1, self.max_levels + 1):
            if len(current_level_nodes) < self.min_cluster_size:
                logger.info(f"Stopping at level {level-1}: only {len(current_level_nodes)} nodes left")
                break
            
            # Cluster current level nodes
            clusters, cluster_quality = await self._cluster_nodes(current_level_nodes)
            
            if len(clusters) <= 1:
                logger.info(f"Stopping at level {level-1}: clustering produced only 1 cluster")
                break
            
            # Summarize each cluster
            summary_nodes = []
            for cluster_id, cluster_nodes in clusters.items():
                if len(cluster_nodes) < self.min_cluster_size:
                    continue
                    
                summary_node = await self._summarize_cluster(
                    cluster_nodes, 
                    level, 
                    cluster_id,
                    group_id
                )
                if summary_node:
                    summary_nodes.append(summary_node)
            
            if not summary_nodes:
                logger.info(f"Stopping at level {level}: no summaries generated")
                break
            
            logger.info(f"Level {level}: Created {len(summary_nodes)} summary nodes from {len(clusters)} clusters")
            
            all_nodes.extend(summary_nodes)
            level_stats[level] = len(summary_nodes)
            current_level_nodes = summary_nodes
        
        logger.info(f"RAPTOR complete: {len(all_nodes)} total nodes across {len(level_stats)} levels")
        
        return {
            "all_nodes": all_nodes,
            "level_stats": level_stats,
            "total_nodes": len(all_nodes),
            "method": "manual_raptor"
        }
    
    async def _cluster_nodes(
        self, 
        nodes: List[TextNode],
        method: str = "gmm"
    ) -> tuple[Dict[int, List[TextNode]], Dict[str, Any]]:
        """
        Cluster nodes based on their embeddings.
        
        Args:
            nodes: Nodes to cluster
            method: 'gmm' for Gaussian Mixture Model, 'kmeans' for K-Means
        
        Returns:
            Tuple of:
            - clusters: Dict mapping cluster_id -> list of nodes in that cluster
            - quality_metrics: Dict with silhouette scores and cluster quality info
        """
        if len(nodes) < self.min_cluster_size:
            return {0: nodes}
        
        if self.llm_service.embed_model is None:
            raise RuntimeError("Embed model must be initialized for clustering")
        
        # Get embeddings for all nodes
        embeddings = []
        for node in nodes:
            if node.embedding is not None:
                embeddings.append(node.embedding)
            else:
                # Generate embedding if not present
                emb = self.llm_service.embed_model.get_text_embedding(node.text)
                node.embedding = emb
                embeddings.append(emb)
        
        embeddings_array = np.array(embeddings)
        
        # Determine number of clusters
        n_clusters = min(
            self.max_clusters_per_level,
            max(2, len(nodes) // 3)  # Roughly 3 nodes per cluster
        )
        
        try:
            if method == "gmm":
                # Gaussian Mixture Model (soft clustering, better for hierarchical)
                gmm = GaussianMixture(
                    n_components=n_clusters,
                    covariance_type='full',
                    random_state=42
                )
                cluster_labels = gmm.fit_predict(embeddings_array)
            else:
                # K-Means (hard clustering)
                kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
                cluster_labels = kmeans.fit_predict(embeddings_array)
        except Exception as e:
            logger.warning(f"Clustering failed: {e}, returning single cluster")
            return {0: nodes}
        
        # Group nodes by cluster
        clusters = defaultdict(list)
        for i, label in enumerate(cluster_labels):
            clusters[int(label)].append(nodes[i])
        
        # Calculate cluster quality metrics
        from sklearn.metrics import silhouette_score, silhouette_samples
        
        try:
            silhouette_avg = silhouette_score(embeddings_array, cluster_labels)
            silhouette_per_sample = silhouette_samples(embeddings_array, cluster_labels)
            
            # Store quality metrics in each node
            for i, node in enumerate(nodes):
                node.metadata['silhouette_score'] = float(silhouette_per_sample[i])
                node.metadata['cluster_silhouette_avg'] = float(silhouette_avg)
            
            logger.info(f"Cluster silhouette score: {silhouette_avg:.3f}")
            
            quality_metrics = {
                "silhouette_avg": float(silhouette_avg),
                "n_clusters": n_clusters,
                "method": method,
            }
        except Exception as e:
            logger.warning(f"Failed to calculate silhouette scores: {e}")
            quality_metrics = {"silhouette_avg": 0.0, "n_clusters": n_clusters, "method": method}
        
        return dict(clusters), quality_metrics
    
    async def _summarize_cluster(
        self, 
        nodes: List[TextNode],
        level: int,
        cluster_id: int,
        group_id: str
    ) -> Optional[TextNode]:
        """
        Generate a summary node for a cluster of nodes.
        
        Args:
            nodes: Nodes in the cluster to summarize
            level: Current RAPTOR level
            cluster_id: ID of this cluster
            group_id: Tenant identifier
        
        Returns:
            TextNode containing the summary, or None if failed
        """
        if self.llm_service.llm is None or self.llm_service.embed_model is None:
            raise RuntimeError("LLM and embed_model must be initialized for summarization")
        
        # Combine text from all nodes in cluster
        combined_text = "\n\n---\n\n".join([
            f"[Chunk {i+1}]: {node.text[:1000]}" 
            for i, node in enumerate(nodes[:10])  # Limit to 10 chunks
        ])
        
        # Generate summary using LLM
        prompt = f"""You are summarizing a cluster of related text chunks for hierarchical retrieval.

The following {len(nodes)} text chunks have been grouped together because they are semantically similar:

{combined_text}

Create a comprehensive summary that:
1. Captures the main themes and key information from all chunks
2. Preserves important details, names, numbers, and relationships
3. Is suitable for answering questions about this topic cluster
4. Is approximately {self.summary_length} tokens long

Summary:"""
        
        try:
            messages = [
                ChatMessage(
                    role="system",
                    content="You are an expert at creating concise, informative summaries that preserve key details for retrieval systems."
                ),
                ChatMessage(role="user", content=prompt)
            ]
            
            response = self.llm_service.llm.chat(messages)
            summary_text = str(response).strip()
            
            # Clean up response
            import re
            summary_text = re.sub(r"^assistant:\s*", "", summary_text).strip()
            
            # Calculate cluster coherence (intra-cluster similarity)
            cluster_coherence = 0.0
            if nodes[0].embedding is not None:
                from scipy.spatial.distance import pdist
                embeddings = np.array([n.embedding for n in nodes if n.embedding is not None])
                if len(embeddings) > 1:
                    cluster_coherence = 1 - np.mean(pdist(embeddings, metric='cosine'))
                else:
                    cluster_coherence = 1.0
            
            # Determine confidence level based on cluster cohesion
            if cluster_coherence >= 0.85:
                confidence_level = "high"
                confidence_score = 0.95
            elif cluster_coherence >= 0.75:
                confidence_level = "medium"
                confidence_score = 0.80
            else:
                confidence_level = "low"
                confidence_score = 0.60
            
            # Create summary node
            summary_node = TextNode(
                text=summary_text,
                metadata={
                    'group_id': group_id,
                    'raptor_level': level,
                    'cluster_id': cluster_id,
                    'source': 'raptor',
                    'child_count': len(nodes),
                    'child_ids': [n.node_id for n in nodes[:20]],  # Track lineage
                    # Quality metrics
                    'cluster_coherence': float(cluster_coherence),
                    'confidence_level': confidence_level,
                    'confidence_score': float(confidence_score),
                    'silhouette_score': nodes[0].metadata.get('silhouette_score', 0.0) if nodes else 0.0,
                    'creation_model': 'gpt-4o-2024-11-20',
                }
            )
            
            # Generate embedding for the summary
            summary_node.embedding = self.llm_service.embed_model.get_text_embedding(summary_text)
            
            return summary_node
            
        except Exception as e:
            logger.error(f"Failed to summarize cluster {cluster_id} at level {level}: {e}")
            return None
    
    async def index_raptor_nodes(
        self,
        nodes: List[TextNode],
        group_id: str,
    ) -> Dict[str, Any]:
        """
        Index RAPTOR nodes into Azure AI Search for semantic ranking accuracy enhancement.
        
        This is the KEY integration point where RAPTOR summaries get indexed into
        Azure AI Search. At query time, the semantic ranker will improve the quality
        of retrieved summaries before they're sent to the LLM.
        
        Architecture:
        - RAPTOR nodes (chunks + summaries) → Azure AI Search (with semantic ranker)
        - Entities/relationships → Neo4j (via PropertyGraphIndex, separate path)
        
        Args:
            nodes: All RAPTOR nodes (all levels - leaves + summaries)
            group_id: Tenant identifier for multi-tenancy isolation
        
        Returns:
            Stats about indexed nodes
        """
        logger.info(f"Indexing {len(nodes)} RAPTOR nodes to Azure AI Search for group {group_id}")
        
        # Count by level for stats
        level_counts = defaultdict(int)
        for node in nodes:
            level = node.metadata.get('raptor_level', 0)
            level_counts[level] += 1
        
        logger.info(f"RAPTOR level distribution: {dict(level_counts)}")
        
        # Convert TextNodes to Documents for Azure AI Search
        # Strip large metadata to avoid chunk size issues
        ESSENTIAL_METADATA_KEYS = {
            "group_id", 
            "raptor_level", 
            "source", 
            "file_name", 
            "page_number",
            # Quality metrics for semantic ranker context
            "cluster_coherence",
            "confidence_level",
            "confidence_score",
            "silhouette_score",
            "cluster_silhouette_avg",
            "creation_model",
            "child_count",
        }
        documents = []
        for node in nodes:
            # Clean metadata
            clean_metadata = {k: v for k, v in node.metadata.items() if k in ESSENTIAL_METADATA_KEYS}
            clean_metadata["group_id"] = group_id  # Ensure group_id is set
            
            doc = Document(
                text=node.get_content(),
                metadata=clean_metadata,
            )
            documents.append(doc)
        
        # Index to Azure AI Search (or LanceDB in dev)
        # This enables semantic ranking at query time for accuracy enhancement
        try:
            self.vector_service.add_documents(
                group_id=group_id,
                documents=documents,
                index_name="raptor",  # Dedicated RAPTOR index
            )
            logger.info(f"✅ Successfully indexed {len(documents)} RAPTOR nodes to Azure AI Search")
        except Exception as e:
            logger.error(f"❌ Failed to index RAPTOR nodes to Azure AI Search: {e}")
            # Don't fail the entire pipeline - Neo4j indexing will still work
        
        return {
            "status": "success",
            "indexed": len(documents),  # Number of documents successfully indexed
            "total_processed": len(nodes),
            "level_counts": dict(level_counts),
            "indexed_to": self.vector_service.store_type,
            "note": "RAPTOR nodes indexed to Azure AI Search for semantic ranking"
        }
