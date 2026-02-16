"""
LlamaIndex-Native HippoRAG Retriever

A custom retriever implementing Personalized PageRank (PPR) for multi-hop 
graph retrieval, designed for use with Azure Managed Identity and LlamaIndex.

This replaces the upstream `hipporag` package with a native implementation
that directly integrates with:
- LlamaIndex's BaseRetriever interface
- llama-index-llms-azure-openai for entity extraction
- llama-index-embeddings-azure-openai for semantic matching
- llama-index-graph-stores-neo4j for graph access

Key Features:
- Personalized PageRank (PPR) for deterministic multi-hop traversal
- Azure AD/Managed Identity authentication (no API keys)
- Direct Neo4j Cypher queries for graph navigation
- LLM-powered seed entity extraction from queries
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Callable
import structlog

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, TextNode, QueryBundle
from llama_index.core.callbacks import CallbackManager

logger = structlog.get_logger(__name__)


@dataclass
class HippoRAGRetrieverConfig:
    """Configuration for HippoRAGRetriever."""
    
    # PPR parameters
    damping_factor: float = 0.85
    max_iterations: int = 20
    convergence_threshold: float = 1e-6
    
    # Retrieval parameters
    top_k: int = 15
    max_seeds: int = 10
    expand_seeds_per_entity: int = 3
    
    # Fallback parameters
    fallback_to_high_degree: bool = True
    high_degree_fallback_k: int = 5
    
    # Entity extraction prompt
    entity_extraction_prompt: str = field(default="""
Extract the key entities from the following query that would be useful for graph-based retrieval.
Return ONLY a markdown list of entity names, one per line.

Query: {query}

Entities:""")


class HippoRAGRetriever(BaseRetriever):
    """
    LlamaIndex-native HippoRAG retriever using Personalized PageRank.
    
    This retriever performs multi-hop graph traversal using PPR, starting from
    seed entities extracted from the user query. It's designed for audit-grade
    retrieval where deterministic, explainable paths are required.
    
    Architecture:
    1. Extract seed entities from query (using LLM or provided seeds)
    2. Map seeds to graph nodes (fuzzy matching)
    3. Run Personalized PageRank from seed nodes
    4. Return top-k nodes with relevance scores
    
    Usage:
        ```python
        from llama_index.llms.azure_openai import AzureOpenAI
        from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
        from src.worker.services.graph_service import GraphService
        
        graph_service = GraphService()
        neo4j_store = graph_service.get_store(group_id)
        
        retriever = HippoRAGRetriever(
            graph_store=neo4j_store,
            llm=azure_llm,
            embed_model=azure_embed,
            config=HippoRAGRetrieverConfig(top_k=20)
        )
        
        nodes = retriever.retrieve("What compliance policies apply to data transfers?")
        ```
    """
    
    def __init__(
        self,
        graph_store: Any,  # Neo4jPropertyGraphStore or compatible
        llm: Optional[Any] = None,  # LlamaIndex LLM for entity extraction
        embed_model: Optional[Any] = None,  # LlamaIndex embedding model
        config: Optional[HippoRAGRetrieverConfig] = None,
        callback_manager: Optional[CallbackManager] = None,
        group_id: Optional[str] = None,
    ):
        """
        Initialize the HippoRAG retriever.
        
        Args:
            graph_store: Neo4j graph store for accessing the knowledge graph
            llm: LlamaIndex LLM for extracting seed entities from queries
            embed_model: Embedding model for semantic entity matching
            config: Retriever configuration
            callback_manager: LlamaIndex callback manager
            group_id: Tenant ID for multi-tenant filtering
        """
        super().__init__(callback_manager=callback_manager)
        
        self.graph_store = graph_store
        self.llm = llm
        self.embed_model = embed_model
        self.config = config or HippoRAGRetrieverConfig()
        self.group_id = group_id
        
        # Graph cache (lazy loaded)
        self._adjacency: Dict[str, List[str]] = {}
        self._reverse_adjacency: Dict[str, List[str]] = {}
        self._nodes: List[str] = []
        self._nodes_lower: Dict[str, str] = {}
        self._node_properties: Dict[str, Dict[str, Any]] = {}
        self._alias_to_nodes: Dict[str, List[str]] = {}  # alias.lower() -> [node_id, ...]
        self._kvp_key_to_nodes: Dict[str, List[str]] = {}  # kvp_key.lower() -> [node_id, ...]
        self._graph_loaded = False
        
        logger.info(
            "hipporag_retriever_initialized",
            has_llm=llm is not None,
            has_embed=embed_model is not None,
            group_id=group_id,
            top_k=self.config.top_k,
        )
    
    def _load_graph_from_neo4j(self) -> None:
        """Load the graph structure from Neo4j into memory for PPR."""
        if self._graph_loaded:
            return
        
        try:
            # Get the Neo4j driver from the graph store
            driver = getattr(self.graph_store, '_driver', None)
            database = getattr(self.graph_store, '_database', 'neo4j')
            
            if driver is None:
                logger.warning("hipporag_no_driver", msg="Graph store has no _driver attribute")
                return
            
            # Build group filter for multi-tenant isolation
            group_filter = ""
            params: Dict[str, Any] = {}
            if self.group_id:
                group_filter = "WHERE n.group_id = $group_id AND m.group_id = $group_id AND r.group_id = $group_id"
                params["group_id"] = self.group_id
            
            # Query all relationships to build adjacency
            query = f"""
            MATCH (n)-[r]->(m)
            {group_filter}
            RETURN n.id AS source, m.id AS target, type(r) AS rel_type
            """
            
            adjacency: Dict[str, List[str]] = {}
            reverse_adjacency: Dict[str, List[str]] = {}
            nodes: set = set()
            
            with driver.session(database=database) as session:
                result = session.run(query, params)
                for record in result:
                    source = record["source"]
                    target = record["target"]
                    
                    if source and target:
                        nodes.add(source)
                        nodes.add(target)
                        adjacency.setdefault(source, []).append(target)
                        adjacency.setdefault(target, [])  # Ensure target exists
                        reverse_adjacency.setdefault(target, []).append(source)
                        reverse_adjacency.setdefault(source, [])
            
            # Also query node properties for context retrieval
            # Include aliases for Entity nodes and key for KeyValue nodes
            props_query = f"""
            MATCH (n)
            {group_filter.replace('AND m.group_id = $group_id', '')}
            RETURN n.id AS node_id, n.name AS name, n.text AS text, labels(n) AS labels,
                   coalesce(n.aliases, []) AS aliases,
                   n.key AS kvp_key
            LIMIT 50000
            """
            
            node_properties: Dict[str, Dict[str, Any]] = {}
            # Build alias-to-node and kvp_key-to-node lookup maps for seed resolution
            alias_to_nodes: Dict[str, List[str]] = {}  # alias.lower() -> [node_id, ...]
            kvp_key_to_nodes: Dict[str, List[str]] = {}  # kvp_key.lower() -> [node_id, ...]
            
            with driver.session(database=database) as session:
                result = session.run(props_query, params)
                for record in result:
                    node_id = record.get("node_id")
                    if node_id:
                        aliases = record.get("aliases") or []
                        kvp_key = record.get("kvp_key") or ""
                        
                        node_properties[node_id] = {
                            "name": record.get("name", node_id),
                            "text": record.get("text", ""),
                            "labels": record.get("labels", []),
                            "aliases": aliases,
                            "kvp_key": kvp_key,
                        }
                        
                        # Build alias lookup: map each alias to its node
                        for alias in aliases:
                            if alias:
                                alias_lc = alias.lower().strip()
                                if alias_lc:
                                    alias_to_nodes.setdefault(alias_lc, []).append(node_id)
                        
                        # Build KVP key lookup: map key to its node
                        if kvp_key:
                            kvp_key_lc = kvp_key.lower().strip()
                            if kvp_key_lc:
                                kvp_key_to_nodes.setdefault(kvp_key_lc, []).append(node_id)
            
            self._adjacency = adjacency
            self._reverse_adjacency = reverse_adjacency
            self._nodes = sorted(nodes)
            self._nodes_lower = {n: n.lower() for n in self._nodes}
            self._node_properties = node_properties
            self._alias_to_nodes = alias_to_nodes
            self._kvp_key_to_nodes = kvp_key_to_nodes
            self._graph_loaded = True
            
            logger.info(
                "hipporag_graph_loaded",
                num_nodes=len(self._nodes),
                num_edges=sum(len(v) for v in adjacency.values()),
                num_aliases=len(alias_to_nodes),
                num_kvp_keys=len(kvp_key_to_nodes),
                group_id=self.group_id,
            )
            
        except Exception as e:
            logger.error("hipporag_graph_load_failed", error=str(e))
            self._graph_loaded = False
    
    async def _extract_entities_with_llm(self, query: str) -> List[str]:
        """Use LLM to extract seed entities from the query."""
        if self.llm is None:
            return []

        try:
            import json

            prompt = self.config.entity_extraction_prompt.format(query=query)

            # Use the LLM to extract entities
            response = await self.llm.acomplete(prompt)
            response_text = str(response).strip()

            # Parse markdown list response
            entities = []
            for line in response_text.split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    entities.append(line[2:].strip())
                elif line.startswith('* '):
                    entities.append(line[2:].strip())

            if not entities:
                # Fallback: try JSON array parsing for backward compatibility
                if "[" in response_text:
                    start = response_text.index("[")
                    end = response_text.rindex("]") + 1
                    json_str = response_text[start:end]
                    parsed = json.loads(json_str)
                    if isinstance(parsed, list):
                        entities = [str(e).strip() for e in parsed if e]

            return [e for e in entities if e]

        except Exception as e:
            logger.warning("hipporag_entity_extraction_failed", error=str(e))
            return []
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text for matching."""
        return " ".join(text.lower().strip().split())
    
    def _vector_search_entities(self, seed: str, top_k: int = 3) -> List[str]:
        """
        Search for entities using vector similarity on entity embeddings.
        
        Uses Neo4j's native vector index 'entity_embedding' to find semantically
        similar entities when lexical matching fails.
        
        Args:
            seed: The seed phrase to search for
            top_k: Number of similar entities to return
            
        Returns:
            List of entity node IDs ordered by similarity
        """
        if self.embed_model is None:
            return []
        
        try:
            # Get embedding for the seed phrase
            seed_embedding = self.embed_model.get_query_embedding(seed)
            if not seed_embedding:
                return []
            
            # Get Neo4j driver from graph store
            driver = getattr(self.graph_store, '_driver', None)
            database = getattr(self.graph_store, '_database', 'neo4j')
            
            if driver is None:
                return []
            
            # Query vector index - use entity_embedding_v2 for V2 data
            # SEARCH clause with in-index group_id pre-filtering (Cypher 25)
            # No oversampling needed — SEARCH guarantees top_k results for the group.
            query = """CYPHER 25
            MATCH (node:Entity)
            SEARCH node IN (VECTOR INDEX entity_embedding_v2 FOR $embedding WHERE node.group_id = $group_id LIMIT $top_k)
            SCORE AS score
            RETURN node.id AS node_id, score
            ORDER BY score DESC
            """
            
            params = {
                "embedding": seed_embedding,
                "top_k": top_k,
                "group_id": self.group_id,
            }
            
            results: List[str] = []
            with driver.session(database=database) as session:
                result = session.run(query, params)
                for record in result:
                    node_id = record.get("node_id")
                    if node_id:
                        results.append(node_id)
            
            if results:
                logger.info(
                    "hipporag_vector_search_success",
                    seed=seed,
                    num_results=len(results),
                    top_match=results[0] if results else None,
                )
            
            return results
            
        except Exception as e:
            logger.warning("hipporag_vector_search_failed", seed=seed, error=str(e))
            return []
    
    def _expand_seeds_to_nodes(self, seeds: List[str]) -> List[str]:
        """
        Map seed phrases to actual graph nodes using multi-strategy matching.
        
        Matching strategies (in priority order):
        1. Exact match on node ID (case-insensitive)
        2. Alias match - check entity aliases for exact match
        3. KVP key match - check KeyValue node keys for exact match
        4. Substring match on node ID
        5. Token overlap (Jaccard similarity) on node ID
        6. Vector similarity - semantic search on entity embeddings (last resort)
        
        This ensures seeds like "Invoice" can match entities with:
        - ID: "Invoice #1256003"
        - Alias: ["Invoice", "inv-1256003"]
        - Or KeyValue nodes with key: "Invoice Number"
        - Or semantically similar entities via vector search
        """
        if not self._nodes:
            return []
        
        expanded: List[str] = []
        max_per_seed = self.config.expand_seeds_per_entity
        
        for seed in seeds:
            seed_norm = self._normalize_text(seed)
            if not seed_norm:
                continue
            
            seed_matches: List[str] = []
            
            # 1. Exact match on node ID (case-insensitive)
            for node, node_lc in self._nodes_lower.items():
                if node_lc == seed_norm:
                    seed_matches.append(node)
                    break
            
            # 2. Alias match - check if seed matches any entity alias exactly
            if not seed_matches and self._alias_to_nodes:
                alias_nodes = self._alias_to_nodes.get(seed_norm, [])
                if alias_nodes:
                    seed_matches.extend(alias_nodes[:max_per_seed])
            
            # 3. KVP key match - check if seed matches any KeyValue node key
            if not seed_matches and self._kvp_key_to_nodes:
                kvp_nodes = self._kvp_key_to_nodes.get(seed_norm, [])
                if kvp_nodes:
                    seed_matches.extend(kvp_nodes[:max_per_seed])
            
            # 4. Substring match on node ID
            if not seed_matches:
                substring_hits: List[str] = []
                for node, node_lc in self._nodes_lower.items():
                    if seed_norm in node_lc or node_lc in seed_norm:
                        substring_hits.append(node)
                if substring_hits:
                    seed_matches.extend(substring_hits[:max_per_seed])
            
            # 5. Token overlap (Jaccard similarity) on node ID
            if not seed_matches:
                seed_tokens = set(seed_norm.split())
                if seed_tokens:
                    scored: List[Tuple[float, str]] = []
                    for node, node_lc in self._nodes_lower.items():
                        node_tokens = set(node_lc.split())
                        if not node_tokens:
                            continue
                        intersection = len(seed_tokens & node_tokens)
                        if intersection == 0:
                            continue
                        jaccard = intersection / float(len(seed_tokens | node_tokens))
                        scored.append((jaccard, node))
                    
                    scored.sort(key=lambda x: x[0], reverse=True)
                    seed_matches.extend([n for _, n in scored[:max_per_seed]])
            
            # 6. Vector similarity on entity embeddings (last resort fallback)
            if not seed_matches:
                vector_hits = self._vector_search_entities(seed, top_k=max_per_seed)
                if vector_hits:
                    seed_matches.extend(vector_hits)
                    logger.info(
                        "hipporag_seed_matched_via_vector",
                        seed=seed,
                        matches=vector_hits[:3],
                        strategy="vector_similarity",
                    )
            
            # Log which strategy matched this seed
            if seed_matches:
                logger.debug(
                    "hipporag_seed_expanded",
                    seed=seed,
                    num_matches=len(seed_matches),
                    first_match=seed_matches[0] if seed_matches else None,
                )
            else:
                logger.warning(
                    "hipporag_seed_no_match",
                    seed=seed,
                    strategies_tried=["exact", "alias", "kvp", "substring", "jaccard", "vector"],
                )
            
            expanded.extend(seed_matches)
        
        # Deduplicate while preserving order
        seen: set = set()
        deduped: List[str] = []
        for n in expanded:
            if n not in seen:
                seen.add(n)
                deduped.append(n)
        
        return deduped[:self.config.max_seeds]
    
    def _get_high_degree_nodes(self, k: int = 5) -> List[str]:
        """Get top-k nodes by degree as fallback seeds."""
        if not self._nodes:
            return []
        
        degrees: List[Tuple[int, str]] = []
        for node in self._nodes:
            out_degree = len(self._adjacency.get(node, []))
            in_degree = len(self._reverse_adjacency.get(node, []))
            degrees.append((out_degree + in_degree, node))
        
        degrees.sort(key=lambda x: x[0], reverse=True)
        return [n for _, n in degrees[:k]]
    
    def _run_personalized_pagerank(
        self,
        seed_nodes: List[str],
    ) -> List[Tuple[str, float]]:
        """
        Run Personalized PageRank starting from seed nodes.
        
        PPR differs from standard PageRank by "teleporting" back to seed nodes
        rather than uniformly to all nodes. This focuses the ranking on nodes
        relevant to the seeds.
        
        Args:
            seed_nodes: Nodes to start from (teleport destinations)
            
        Returns:
            List of (node, score) tuples sorted by score descending
        """
        if not self._nodes or not seed_nodes:
            return []
        
        damping = self.config.damping_factor
        max_iter = self.config.max_iterations
        threshold = self.config.convergence_threshold
        
        # Build personalization vector (uniform over seeds)
        personalization: Dict[str, float] = {n: 0.0 for n in self._nodes}
        for seed in seed_nodes:
            if seed in personalization:
                personalization[seed] += 1.0
        
        total_p = sum(personalization.values())
        if total_p <= 0:
            return []
        
        for n in personalization:
            personalization[n] /= total_p
        
        # Initialize rank to personalization vector
        rank: Dict[str, float] = dict(personalization)
        
        # Power iteration
        for iteration in range(max_iter):
            new_rank: Dict[str, float] = {
                n: (1.0 - damping) * personalization[n] 
                for n in self._nodes
            }
            
            # Distribute rank through edges
            for source, targets in self._adjacency.items():
                if not targets:
                    continue
                share = damping * rank.get(source, 0.0) / len(targets)
                if share == 0.0:
                    continue
                for target in targets:
                    if target in new_rank:
                        new_rank[target] += share
            
            # Check convergence
            diff = sum(abs(new_rank[n] - rank[n]) for n in self._nodes)
            rank = new_rank
            
            if diff < threshold:
                logger.debug(
                    "ppr_converged",
                    iteration=iteration,
                    diff=diff,
                )
                break
        
        # Sort by score
        ranked = sorted(rank.items(), key=lambda kv: kv[1], reverse=True)
        return ranked
    
    def _retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """
        Synchronous retrieve implementation.
        
        This is the main entry point called by LlamaIndex's BaseRetriever.
        """
        query = query_bundle.query_str
        
        logger.info("hipporag_retrieve_start", query=query[:100])
        
        # Load graph if not already loaded
        self._load_graph_from_neo4j()
        
        if not self._nodes:
            logger.warning("hipporag_no_nodes", msg="Graph is empty or failed to load")
            return []
        
        # Extract seeds synchronously (run async in sync context)
        import asyncio
        
        seeds: List[str] = []
        if self.llm:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an async context, can't use run_until_complete
                    # Fall back to synchronous approach
                    seeds = self._extract_entities_sync(query)
                else:
                    seeds = loop.run_until_complete(
                        self._extract_entities_with_llm(query)
                    )
            except RuntimeError:
                # No event loop, create one
                seeds = asyncio.run(self._extract_entities_with_llm(query))
        
        # Expand seeds to actual graph nodes
        seed_nodes = self._expand_seeds_to_nodes(seeds)
        
        logger.info(
            "hipporag_seeds_expanded",
            original_seeds=len(seeds),
            expanded_nodes=len(seed_nodes),
        )
        
        # Fallback to high-degree nodes if no seeds found
        if not seed_nodes and self.config.fallback_to_high_degree:
            seed_nodes = self._get_high_degree_nodes(self.config.high_degree_fallback_k)
            logger.info("hipporag_fallback_high_degree", num_fallback=len(seed_nodes))
        
        if not seed_nodes:
            return []
        
        # Run PPR
        ppr_results = self._run_personalized_pagerank(seed_nodes)
        
        # Convert to NodeWithScore
        nodes_with_scores: List[NodeWithScore] = []
        for node_id, score in ppr_results[:self.config.top_k]:
            props = self._node_properties.get(node_id, {})
            
            text_node = TextNode(
                id_=node_id,
                text=props.get("text", f"Entity: {props.get('name', node_id)}"),
                metadata={
                    "entity_name": props.get("name", node_id),
                    "labels": props.get("labels", []),
                    "ppr_score": score,
                    "retriever": "hipporag",
                    "group_id": self.group_id,
                },
            )
            nodes_with_scores.append(NodeWithScore(node=text_node, score=score))
        
        logger.info(
            "hipporag_retrieve_complete",
            num_results=len(nodes_with_scores),
            top_score=nodes_with_scores[0].score if nodes_with_scores else 0.0,
        )
        
        return nodes_with_scores
    
    def _extract_entities_sync(self, query: str) -> List[str]:
        """Synchronous entity extraction fallback."""
        if self.llm is None:
            return []

        try:
            import json

            prompt = self.config.entity_extraction_prompt.format(query=query)
            response = self.llm.complete(prompt)
            response_text = str(response).strip()

            # Parse markdown list response
            entities = []
            for line in response_text.split('\n'):
                line = line.strip()
                if line.startswith('- '):
                    entities.append(line[2:].strip())
                elif line.startswith('* '):
                    entities.append(line[2:].strip())

            if not entities:
                # Fallback: try JSON array parsing for backward compatibility
                if "[" in response_text:
                    start = response_text.index("[")
                    end = response_text.rindex("]") + 1
                    json_str = response_text[start:end]
                    parsed = json.loads(json_str)
                    if isinstance(parsed, list):
                        entities = [str(e).strip() for e in parsed if e]

            return [e for e in entities if e]
            
        except Exception as e:
            logger.warning("hipporag_entity_extraction_sync_failed", error=str(e))
            return []
    
    async def _aretrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        """Async retrieve implementation."""
        query = query_bundle.query_str
        
        logger.info("hipporag_aretrieve_start", query=query[:100])
        
        # Load graph if not already loaded
        self._load_graph_from_neo4j()
        
        if not self._nodes:
            logger.warning("hipporag_no_nodes", msg="Graph is empty or failed to load")
            return []
        
        # Extract seeds asynchronously
        seeds = await self._extract_entities_with_llm(query)
        
        # Expand seeds to actual graph nodes
        seed_nodes = self._expand_seeds_to_nodes(seeds)
        
        logger.info(
            "hipporag_seeds_expanded",
            original_seeds=len(seeds),
            expanded_nodes=len(seed_nodes),
        )
        
        # Fallback to high-degree nodes if no seeds found
        if not seed_nodes and self.config.fallback_to_high_degree:
            seed_nodes = self._get_high_degree_nodes(self.config.high_degree_fallback_k)
            logger.info("hipporag_fallback_high_degree", num_fallback=len(seed_nodes))
        
        if not seed_nodes:
            return []
        
        # Run PPR (CPU-bound, but fast enough to not need async)
        ppr_results = self._run_personalized_pagerank(seed_nodes)
        
        # Convert to NodeWithScore
        nodes_with_scores: List[NodeWithScore] = []
        for node_id, score in ppr_results[:self.config.top_k]:
            props = self._node_properties.get(node_id, {})
            
            text_node = TextNode(
                id_=node_id,
                text=props.get("text", f"Entity: {props.get('name', node_id)}"),
                metadata={
                    "entity_name": props.get("name", node_id),
                    "labels": props.get("labels", []),
                    "ppr_score": score,
                    "retriever": "hipporag",
                    "group_id": self.group_id,
                },
            )
            nodes_with_scores.append(NodeWithScore(node=text_node, score=score))
        
        logger.info(
            "hipporag_aretrieve_complete",
            num_results=len(nodes_with_scores),
            top_score=nodes_with_scores[0].score if nodes_with_scores else 0.0,
        )
        
        return nodes_with_scores
    
    def retrieve_with_seeds(
        self,
        query: str,
        seed_entities: List[str],
        top_k: Optional[int] = None,
    ) -> List[NodeWithScore]:
        """
        Retrieve using pre-extracted seed entities (bypasses LLM extraction).
        
        Useful when seeds are already known from upstream processing,
        such as community hub entities from Route 3.
        
        Args:
            query: The user query (for logging)
            seed_entities: Pre-extracted seed entities
            top_k: Number of results to return (defaults to config.top_k)
            
        Returns:
            List of NodeWithScore objects
        """
        logger.info(
            "hipporag_retrieve_with_seeds",
            query=query[:100],
            num_seeds=len(seed_entities),
        )
        
        # Load graph if not already loaded
        self._load_graph_from_neo4j()
        
        if not self._nodes:
            return []
        
        # Expand seeds to actual graph nodes
        seed_nodes = self._expand_seeds_to_nodes(seed_entities)
        
        if not seed_nodes and self.config.fallback_to_high_degree:
            seed_nodes = self._get_high_degree_nodes(self.config.high_degree_fallback_k)
        
        if not seed_nodes:
            return []
        
        # Run PPR
        ppr_results = self._run_personalized_pagerank(seed_nodes)
        
        # Convert to NodeWithScore
        k = top_k or self.config.top_k
        nodes_with_scores: List[NodeWithScore] = []
        
        for node_id, score in ppr_results[:k]:
            props = self._node_properties.get(node_id, {})
            
            text_node = TextNode(
                id_=node_id,
                text=props.get("text", f"Entity: {props.get('name', node_id)}"),
                metadata={
                    "entity_name": props.get("name", node_id),
                    "labels": props.get("labels", []),
                    "ppr_score": score,
                    "retriever": "hipporag",
                    "group_id": self.group_id,
                },
            )
            nodes_with_scores.append(NodeWithScore(node=text_node, score=score))
        
        return nodes_with_scores
    
    def get_graph_stats(self) -> Dict[str, Any]:
        """Get statistics about the loaded graph."""
        self._load_graph_from_neo4j()
        
        return {
            "num_nodes": len(self._nodes),
            "num_edges": sum(len(v) for v in self._adjacency.values()),
            "graph_loaded": self._graph_loaded,
            "group_id": self.group_id,
            "has_llm": self.llm is not None,
            "has_embed": self.embed_model is not None,
        }


def create_hipporag_retriever_from_service(
    graph_store: Any,
    llm_service: Any,  # LLMService instance
    config: Optional[HippoRAGRetrieverConfig] = None,
    group_id: Optional[str] = None,
) -> HippoRAGRetriever:
    """
    Factory function to create HippoRAGRetriever from existing services.
    
    This integrates with the existing LLMService pattern used in the codebase.
    
    Args:
        graph_store: Neo4j graph store
        llm_service: LLMService instance (has .llama_llm and .llama_embed)
        config: Retriever configuration
        group_id: Tenant ID
        
    Returns:
        Configured HippoRAGRetriever instance
    """
    llm = getattr(llm_service, "llama_llm", None)
    embed_model = getattr(llm_service, "llama_embed", None)
    
    return HippoRAGRetriever(
        graph_store=graph_store,
        llm=llm,
        embed_model=embed_model,
        config=config,
        group_id=group_id,
    )
