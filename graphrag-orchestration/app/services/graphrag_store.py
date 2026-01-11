"""
Microsoft GraphRAG Implementation with Neo4j and Multi-Tenancy.

This module implements the full Microsoft GraphRAG pipeline:
1. Entity/Relationship extraction from documents
2. Hierarchical Leiden clustering for community detection
3. LLM-generated community summaries
4. Local-to-Global retrieval for complex queries

Reference: https://www.microsoft.com/en-us/research/project/graphrag/
LlamaIndex Cookbook: https://github.com/run-llama/llama_index/blob/main/docs/examples/cookbooks/GraphRAG_v2.ipynb
"""

import re
import logging
import networkx as nx
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from llama_index.core.llms import ChatMessage, LLM
from llama_index.core.schema import BaseNode
from llama_index.core.graph_stores.types import EntityNode, Relation

from app.services.graph_service import MultiTenantNeo4jStore
from app.core.config import settings

logger = logging.getLogger(__name__)


class GraphRAGStore(MultiTenantNeo4jStore):
    """
    Microsoft GraphRAG implementation extending MultiTenantNeo4jStore.
    
    Adds:
    - Hierarchical Leiden community detection
    - LLM-generated community summaries
    - Entity-to-community mapping for efficient retrieval
    
    Speed Considerations:
    - build_communities() is SLOW (runs Leiden + LLM for each community)
    - Call it ONCE after indexing documents, not per-query
    - Community summaries are cached in Neo4j for fast retrieval
    """
    
    # Cache for community summaries (per group_id)
    community_summary: Dict[int, str] = {}
    # Mapping of entity -> list of community IDs
    entity_info: Dict[str, List[int]] = {}
    # Maximum nodes per community cluster
    max_cluster_size: int = 10
    
    def __init__(
        self, 
        group_id: str,
        username: str,
        password: str,
        url: str,
        database: str = "neo4j",
        llm: Optional[Any] = None,
        **kwargs
    ):
        super().__init__(
            group_id=group_id,
            username=username,
            password=password,
            url=url,
            database=database,
            **kwargs
        )
        self._llm = llm
        self.community_summary = {}
        self.entity_info = {}
        logger.info(f"Initialized GraphRAGStore for group: {group_id}")

    def upsert_relations(self, relations: List[Relation]) -> None:
        """
        Override to create relationships directly between __Entity__ nodes.
        
        The default LlamaIndex implementation creates __Node__ (Chunk) objects
        which don't link to the __Entity__ nodes we create via upsert_nodes().
        
        This method uses direct Cypher to MATCH existing __Entity__ nodes by id
        and creates relationships between them.
        """
        logger.info(f"GraphRAGStore.upsert_relations called with {len(relations)} relations")
        
        for relation in relations:
            # Add group_id to properties
            if relation.properties is None:
                relation.properties = {}
            relation.properties["group_id"] = self.group_id
            
            # Build property string for the relationship
            props = relation.properties.copy()
            prop_items = [f"`{k}`: ${k}" for k in props.keys()]
            prop_string = "{" + ", ".join(prop_items) + "}" if prop_items else ""
            
            # Cypher to create/merge relationship between existing __Entity__ nodes
            # Uses MERGE on both nodes to ensure they exist (in case they weren't created yet)
            cypher = f"""
            MERGE (source:`__Entity__` {{id: $source_id, group_id: $group_id}})
            MERGE (target:`__Entity__` {{id: $target_id, group_id: $group_id}})
            MERGE (source)-[r:`{relation.label}` {prop_string}]->(target)
            """
            
            params = {
                "source_id": relation.source_id,
                "target_id": relation.target_id,
                "group_id": self.group_id,
                **props
            }
            
            try:
                self.structured_query(cypher, param_map=params)
                logger.debug(f"Created relation: {relation.source_id} -[{relation.label}]-> {relation.target_id}")
            except Exception as e:
                logger.error(f"Failed to create relation {relation.source_id} -> {relation.target_id}: {e}")
        
        logger.info(f"Upserted {len(relations)} relations for group {self.group_id}")
    
    @property
    def llm(self) -> LLM:
        """Lazy load LLM to avoid circular imports."""
        if self._llm is None:
            from app.services.llm_service import LLMService
            self._llm = LLMService().llm
        assert self._llm is not None, "LLM service failed to initialize"
        return self._llm
    
    def generate_community_summary(self, text: str) -> str:
        """
        Generate a summary for a community's relationships using LLM.
        
        Args:
            text: Relationship descriptions in format "entity1->entity2->relation->description"
        
        Returns:
            Natural language summary of the community's key relationships
        """
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are provided with a set of relationships from a knowledge graph, each represented as "
                    "entity1->entity2->relation->relationship_description. Your task is to create a summary of these "
                    "relationships. The summary should include the names of the entities involved and a concise synthesis "
                    "of the relationship descriptions. The goal is to capture the most critical and relevant details that "
                    "highlight the nature and significance of each relationship. Ensure that the summary is coherent and "
                    "integrates the information in a way that emphasizes the key aspects of the relationships."
                ),
            ),
            ChatMessage(role="user", content=text),
        ]
        response = self.llm.chat(messages)
        clean_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
        return clean_response
    
    def build_communities(self) -> None:
        """
        Build communities from the graph using hierarchical Leiden clustering.
        
        This is the EXPENSIVE operation - run once after indexing, not per-query.
        
        Pipeline:
        1. Convert Neo4j graph to NetworkX
        2. Run hierarchical Leiden clustering
        3. Collect entity-to-community mappings
        4. Generate LLM summaries for each community
        5. Store summaries for fast retrieval
        """
        try:
            from graspologic.partition import hierarchical_leiden
        except ImportError:
            logger.warning(
                "graspologic not installed; skipping community detection. To enable, run: pip install -r requirements.community.txt"
            )
            return
        
        logger.info(f"Building communities for group {self.group_id}...")
        
        # Step 1: Convert to NetworkX graph
        nx_graph = self._create_nx_graph()
        
        if nx_graph.number_of_nodes() == 0:
            logger.warning("No nodes in graph, skipping community building")
            return
        
        logger.info(f"NetworkX graph has {nx_graph.number_of_nodes()} nodes and {nx_graph.number_of_edges()} edges")
        
        # Step 2: Run hierarchical Leiden clustering
        try:
            community_hierarchical_clusters = hierarchical_leiden(
                nx_graph, max_cluster_size=self.max_cluster_size
            )
            logger.info(f"Leiden clustering found {len(set(c.cluster for c in community_hierarchical_clusters))} communities")
        except Exception as e:
            logger.error(f"Leiden clustering failed: {e}")
            # Fallback: treat entire graph as one community
            community_hierarchical_clusters = []
        
        # Step 3 & 4: Collect community info and generate summaries
        self.entity_info, community_info = self._collect_community_info(
            nx_graph, community_hierarchical_clusters
        )
        
        # Step 5: Generate and store summaries
        self._summarize_communities(community_info)
        
        # Optionally persist to Neo4j for durability
        self._persist_communities_to_neo4j()
        
        logger.info(f"Built {len(self.community_summary)} community summaries")
    
    def _create_nx_graph(self) -> nx.Graph:
        """
        Convert Neo4j graph to NetworkX graph for community detection.
        
        Only includes entities from this group_id (multi-tenancy).
        Uses direct Cypher query instead of LlamaIndex get_triplets() to avoid 
        issues with None values in entity labels.
        """
        nx_graph = nx.Graph()
        
        # Use direct Cypher query that's more resilient to missing properties
        result = self.structured_query(
            """
            MATCH (a:`__Entity__`)-[r]->(b:`__Entity__`) 
            WHERE a.group_id = $group_id AND b.group_id = $group_id
            RETURN a.id AS source_id, a.name AS source_name,
                   type(r) AS rel_type,
                   r.relationship_description AS rel_desc,
                   b.id AS target_id, b.name AS target_name
            """,
            param_map={"group_id": self.group_id}
        )
        
        triplet_count = 0
        for row in (result or []):
            source_id = row.get("source_id") or row.get("source_name")
            target_id = row.get("target_id") or row.get("target_name")
            rel_type = row.get("rel_type", "RELATED_TO")
            rel_desc = row.get("rel_desc", rel_type)
            
            if source_id and target_id:
                nx_graph.add_node(source_id)
                nx_graph.add_node(target_id)
                nx_graph.add_edge(
                    source_id,
                    target_id,
                    relationship=rel_type,
                    description=rel_desc or rel_type,
                )
                triplet_count += 1
        
        logger.info(f"Found {triplet_count} triplets for group {self.group_id}")
        
        return nx_graph
    
    def _collect_community_info(
        self, 
        nx_graph: nx.Graph, 
        clusters: List[Any]
    ) -> Tuple[Dict[str, List[int]], Dict[int, List[str]]]:
        """
        Collect detailed information for each community.
        
        Returns:
            entity_info: Mapping of entity name -> list of community IDs
            community_info: Mapping of community ID -> list of relationship descriptions
        """
        entity_info = defaultdict(set)
        community_info = defaultdict(list)
        
        if not clusters:
            # Fallback: treat all nodes as community 0
            for node in nx_graph.nodes():
                entity_info[node].add(0)
                for neighbor in nx_graph.neighbors(node):
                    edge_data = nx_graph.get_edge_data(node, neighbor)
                    if edge_data:
                        detail = f"{node}->{neighbor}->{edge_data.get('relationship', 'RELATED')}->{edge_data.get('description', '')}"
                        community_info[0].append(detail)
            # Convert sets to lists
            entity_info = {k: list(v) for k, v in entity_info.items()}
            return dict(entity_info), dict(community_info)
        
        # Build mapping from node to cluster
        community_mapping = {item.node: item.cluster for item in clusters}
        
        for item in clusters:
            cluster_id = item.cluster
            node = item.node
            entity_info[node].add(cluster_id)
            
            # Collect relationship info within the community
            for neighbor in nx_graph.neighbors(node):
                if neighbor in community_mapping and community_mapping[neighbor] == cluster_id:
                    edge_data = nx_graph.get_edge_data(node, neighbor)
                    if edge_data:
                        detail = f"{node}->{neighbor}->{edge_data.get('relationship', 'RELATED')}->{edge_data.get('description', '')}"
                        community_info[cluster_id].append(detail)
        
        # Convert sets to lists for easier serialization
        entity_info = {k: list(v) for k, v in entity_info.items()}
        
        return dict(entity_info), dict(community_info)
    
    def _summarize_communities(
        self, 
        community_info: Dict[int, List[str]],
        max_concurrent: int = 10
    ) -> None:
        """
        Generate LLM summaries for each community using parallel processing.
        
        This is where most of the indexing cost comes from.
        Optimized for higher rate limits with concurrent LLM calls.
        
        Args:
            community_info: Dict of community_id -> list of relationship details
            max_concurrent: Maximum concurrent LLM requests (increase with higher rate limits)
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        
        logger.info(f"Generating summaries for {len(community_info)} communities (max_concurrent={max_concurrent})...")
        
        # Filter out empty communities
        communities_to_summarize = {
            cid: details for cid, details in community_info.items() 
            if details
        }
        
        if not communities_to_summarize:
            logger.warning("No communities to summarize")
            return
        
        def summarize_one(item: Tuple[int, List[str]]) -> Tuple[int, str]:
            """Summarize a single community."""
            community_id, details = item
            details_text = "\n".join(details) + "."
            
            try:
                summary = self.generate_community_summary(details_text)
                return community_id, summary
            except Exception as e:
                logger.error(f"Failed to summarize community {community_id}: {e}")
                return community_id, details_text
        
        # Use ThreadPoolExecutor for parallel LLM calls
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            results = list(executor.map(
                summarize_one, 
                communities_to_summarize.items()
            ))
        
        # Store results
        for community_id, summary in results:
            self.community_summary[community_id] = summary
        
        logger.info(f"Generated {len(self.community_summary)} community summaries")
    
    def _persist_communities_to_neo4j(self) -> None:
        """
        Store community summaries in Neo4j for durability and fast retrieval.
        
        Creates Community nodes linked to their member entities.
        """
        # Store community summaries as nodes
        for community_id, summary in self.community_summary.items():
            self.structured_query(
                """
                MERGE (c:__Community__ {id: $community_id, group_id: $group_id})
                SET c.summary = $summary
                SET c.updated_at = datetime()
                """,
                param_map={
                    "community_id": community_id,
                    "group_id": self.group_id,
                    "summary": summary
                }
            )
        
        # Link entities to their communities
        for entity_name, community_ids in self.entity_info.items():
            for community_id in community_ids:
                self.structured_query(
                    """
                    MATCH (e:`__Entity__` {id: $entity_name, group_id: $group_id})
                    MATCH (c:__Community__ {id: $community_id, group_id: $group_id})
                    MERGE (e)-[:BELONGS_TO]->(c)
                    """,
                    param_map={
                        "entity_name": entity_name,
                        "community_id": community_id,
                        "group_id": self.group_id
                    }
                )
        
        logger.info(f"Persisted {len(self.community_summary)} communities to Neo4j")
    
    def load_communities_from_neo4j(self) -> None:
        """
        Load previously computed community summaries from Neo4j.
        
        Call this instead of build_communities() if communities were already built.
        """
        # Load community summaries
        result = self.structured_query(
            """
            MATCH (c:__Community__ {group_id: $group_id})
            RETURN c.id AS community_id, c.summary AS summary
            """,
            param_map={"group_id": self.group_id}
        )
        
        self.community_summary = {}
        for row in (result or []):
            self.community_summary[row["community_id"]] = row["summary"]
        
        # Load entity-to-community mappings
        result = self.structured_query(
            """
            MATCH (e:`__Entity__` {group_id: $group_id})-[:BELONGS_TO]->(c:__Community__)
            RETURN e.id AS entity_name, collect(c.id) AS community_ids
            """,
            param_map={"group_id": self.group_id}
        )
        
        self.entity_info = {}
        for row in (result or []):
            self.entity_info[row["entity_name"]] = row["community_ids"]
        
        logger.info(f"Loaded {len(self.community_summary)} communities from Neo4j")
    
    def get_community_summaries(self) -> Dict[int, str]:
        """
        Get all community summaries, building them if not already done.
        
        Returns:
            Mapping of community_id -> summary text
        """
        if not self.community_summary:
            # Try loading from Neo4j first
            self.load_communities_from_neo4j()
        
        if not self.community_summary:
            # Build from scratch
            self.build_communities()
        
        return self.community_summary
    
    def get_entity_communities(self, entity_names: List[str]) -> List[int]:
        """
        Get all community IDs for a list of entities.
        
        Args:
            entity_names: List of entity names to look up
            
        Returns:
            Deduplicated list of community IDs
        """
        if not self.entity_info:
            self.load_communities_from_neo4j()
        
        community_ids = set()
        for entity in entity_names:
            if entity in self.entity_info:
                community_ids.update(self.entity_info[entity])
        
        return list(community_ids)
