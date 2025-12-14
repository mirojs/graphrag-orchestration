"""
Community Detection and Summarization Service for GraphRAG.

This implements the GraphRAG Global Search capability by:
1. Building communities using hierarchical Leiden algorithm
2. Generating LLM summaries for each community
3. Providing map-reduce query capability over communities

Borrowed from LlamaIndex GraphRAG v2 cookbook:
https://github.com/run-llama/llama_index/tree/main/docs/examples/cookbooks/GraphRAG_v2.ipynb
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
import logging
import re
import asyncio

from llama_index.core.llms import ChatMessage
from llama_index.core.graph_stores.types import LabelledNode, Relation

from app.services.graph_service import GraphService, MultiTenantNeo4jStore
from app.services.llm_service import LLMService
from app.core.config import settings

if TYPE_CHECKING:
    import networkx as nx

logger = logging.getLogger(__name__)


class CommunityService:
    """
    Service for community detection and summarization.
    
    Implements GraphRAG Global Search pattern:
    - Build communities from knowledge graph
    - Generate summaries for each community
    - Query across all communities (map-reduce)
    """
    
    def __init__(self):
        self.graph_service = GraphService()
        self.llm_service = LLMService()
        
        # Community summaries cache per group
        self._community_summaries: Dict[str, Dict[int, str]] = {}
        
        # Max cluster size for Leiden algorithm
        self.max_cluster_size = settings.GRAPHRAG_MAX_CLUSTER_SIZE or 10
    
    def _create_nx_graph_from_neo4j(self, group_id: str) -> "nx.Graph":  # type: ignore[name-defined]
        """
        Convert Neo4j graph to NetworkX for community detection.
        
        Uses direct Cypher queries for efficiency (avoids LlamaIndex's heavy 
        schema introspection queries that can timeout on large graphs).
        
        Strategy:
        1. First try entity-to-entity relationships (e.g., WORKS_AT, REPORTS_TO)
        2. If none exist, fall back to co-occurrence (entities in same chunks)
        
        For very large graphs (100k+ nodes), consider using Neo4j GDS plugin directly.
        """
        import networkx as nx
        
        G = nx.Graph()
        
        # Get Neo4j driver directly for efficient querying
        driver = self.graph_service.driver
        if not driver:
            raise RuntimeError("Neo4j driver not initialized")
        
        with driver.session(database=settings.NEO4J_DATABASE) as session:
            # Strategy 1: Try direct entity-to-entity relationships
            cypher_direct = """
            MATCH (source:__Entity__ {group_id: $group_id})-[rel]->(target:__Entity__ {group_id: $group_id})
            WHERE type(rel) <> 'MENTIONS'
            RETURN 
                source.id AS source_id,
                source.name AS source_name,
                labels(source) AS source_labels,
                type(rel) AS rel_type,
                rel.description AS rel_description,
                target.id AS target_id,
                target.name AS target_name,
                labels(target) AS target_labels
            """
            
            result = session.run(cypher_direct, group_id=group_id)
            direct_records = list(result)
            
            if direct_records:
                logger.info(f"Found {len(direct_records)} direct entity relationships for group {group_id}")
                records = direct_records
            else:
                # Strategy 2: Fall back to co-occurrence (entities in same chunks)
                logger.info(f"No direct entity relationships found for group {group_id}, using co-occurrence")
                
                cypher_cooccurrence = """
                MATCH (e1:__Entity__ {group_id: $group_id})-[:MENTIONS]->(chunk:Chunk)<-[:MENTIONS]-(e2:__Entity__ {group_id: $group_id})
                WHERE e1.id < e2.id  // Avoid duplicates
                RETURN 
                    e1.id AS source_id,
                    e1.name AS source_name,
                    labels(e1) AS source_labels,
                    'CO_OCCURS_WITH' AS rel_type,
                    chunk.text AS rel_description,
                    e2.id AS target_id,
                    e2.name AS target_name,
                    labels(e2) AS target_labels,
                    count(chunk) AS weight
                """
                
                result = session.run(cypher_cooccurrence, group_id=group_id)
                records = list(result)
                logger.info(f"Found {len(records)} co-occurrence relationships for group {group_id}")
        
        # Build NetworkX graph from results
        for record in records:
            source_id = record["source_name"] or record["source_id"]
            target_id = record["target_name"] or record["target_id"]
            
            # Add nodes with properties
            if source_id not in G:
                G.add_node(source_id, **{
                    'label': record["source_labels"][0] if record["source_labels"] else 'Entity',
                    'neo4j_id': record["source_id"],
                })
            if target_id not in G:
                G.add_node(target_id, **{
                    'label': record["target_labels"][0] if record["target_labels"] else 'Entity',
                    'neo4j_id': record["target_id"],
                })
            
            # Add edge with relation info
            edge_attrs = {
                'label': record["rel_type"] or 'RELATED_TO',
                'description': record.get("rel_description") or '',
            }
            if "weight" in record:
                edge_attrs['weight'] = record["weight"]
            
            G.add_edge(source_id, target_id, **edge_attrs)
        
        logger.info(f"Created NetworkX graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")
        return G
    
    def _collect_community_info(
        self, 
        nx_graph: "nx.Graph",  # type: ignore[name-defined]
        clusters: List[Any],
        max_members: int = 100
    ) -> Dict[int, Dict[str, Any]]:
        """
        Collect information about each community for summarization.
        
        Returns dict mapping community_id to:
        - members: List of node names
        - relationships: List of relationship strings (entity1->entity2->relation)
        """
        community_info = {}
        
        for community_id, members in enumerate(clusters):
            # Limit to max_members for very large communities
            member_list = list(members)[:max_members]
            
            # Collect relationships within this community
            relationships = []
            for node in member_list:
                for neighbor in nx_graph.neighbors(node):
                    if neighbor in members:
                        edge_data = nx_graph.edges[node, neighbor]
                        rel_label = edge_data.get('label', 'RELATED_TO')
                        rel_desc = edge_data.get('properties', {}).get('description', '')
                        
                        rel_str = f"{node}->{neighbor}->{rel_label}"
                        if rel_desc:
                            rel_str += f"->{rel_desc}"
                        relationships.append(rel_str)
            
            community_info[community_id] = {
                'members': member_list,
                'member_count': len(members),
                'relationships': relationships,
                'relationship_count': len(relationships),
            }
        
        return community_info
    
    def _generate_community_summary(self, community_info: Dict[str, Any]) -> str:
        """
        Generate a summary for a community using LLM.
        
        Based on GraphRAG_v2 pattern:
        - Takes relationship strings as input
        - Asks LLM to synthesize key aspects
        """
        if not self.llm_service.llm:
            raise ValueError("LLM service not configured")
        
        # Build the text representation of relationships
        rel_text = "\n".join(community_info['relationships'][:50])  # Limit for context
        
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are provided with a set of relationships from a knowledge graph, "
                    "each represented as entity1->entity2->relation->relationship_description. "
                    "Your task is to create a summary of these relationships. "
                    "The summary should include the names of the entities involved and a concise "
                    "synthesis of the relationship descriptions. The goal is to capture the most "
                    "critical and relevant details that highlight the nature and significance of "
                    "each relationship. Ensure that the summary is coherent and integrates the "
                    "information in a way that emphasizes the key aspects of the relationships."
                ),
            ),
            ChatMessage(
                role="user", 
                content=f"Relationships:\n{rel_text}\n\nProvide a concise summary:"
            ),
        ]
        
        response = self.llm_service.llm.chat(messages)
        
        # Clean up response
        clean_response = re.sub(r"^assistant:\s*", "", str(response)).strip()
        return clean_response
    
    async def build_communities(
        self, 
        group_id: str,
        use_neo4j_gds: bool = False
    ) -> Dict[str, Any]:
        """
        Build communities and generate summaries.
        
        Args:
            group_id: Tenant identifier for isolation
            use_neo4j_gds: If True, use Neo4j GDS (requires plugin). 
                          If False, use graspologic in Python.
        
        Returns:
            Statistics about communities created
        """
        logger.info(f"Building communities for group {group_id}")
        
        if use_neo4j_gds:
            # Use Neo4j Graph Data Science plugin
            return self.graph_service.run_community_detection(group_id)
        
        # Use graspologic in Python (borrowed from LlamaIndex v2)
        try:
            from graspologic.partition import hierarchical_leiden
        except ImportError:
            logger.error("graspologic not installed. Run: pip install graspologic")
            raise ImportError("graspologic required for community detection")
        
        # Create NetworkX graph from Neo4j
        nx_graph = self._create_nx_graph_from_neo4j(group_id)
        
        if nx_graph.number_of_nodes() == 0:
            logger.warning(f"No nodes found for group {group_id}")
            return {
                "community_count": 0,
                "node_count": 0,
                "summaries_generated": 0,
            }
        
        # Run hierarchical Leiden algorithm
        logger.info(f"Running hierarchical Leiden with max_cluster_size={self.max_cluster_size}")
        community_hierarchical_clusters = hierarchical_leiden(
            nx_graph, 
            max_cluster_size=self.max_cluster_size
        )
        
        # Convert HierarchicalCluster results to dict: cluster_id -> set of nodes
        # hierarchical_leiden returns list of HierarchicalCluster(node, cluster, ...)
        cluster_to_nodes: Dict[int, set] = {}
        for hc in community_hierarchical_clusters:
            cluster_id = hc.cluster
            if cluster_id not in cluster_to_nodes:
                cluster_to_nodes[cluster_id] = set()
            cluster_to_nodes[cluster_id].add(hc.node)
        
        # Convert to list of sets for _collect_community_info
        clusters = list(cluster_to_nodes.values())
        logger.info(f"Found {len(clusters)} communities from Leiden algorithm")
        
        community_info = self._collect_community_info(nx_graph, clusters)
        
        # Generate summaries for each community
        logger.info(f"Generating summaries for {len(community_info)} communities")
        summaries = {}
        
        for community_id, info in community_info.items():
            if info['relationship_count'] > 0:
                try:
                    summary = self._generate_community_summary(info)
                    summaries[community_id] = summary
                    logger.debug(f"Community {community_id}: {len(info['members'])} members, summary generated")
                except Exception as e:
                    logger.error(f"Failed to generate summary for community {community_id}: {e}")
                    summaries[community_id] = f"Community with {info['member_count']} members"
            else:
                summaries[community_id] = f"Community with {info['member_count']} members (no relationships)"
        
        # Cache summaries
        self._community_summaries[group_id] = summaries
        
        # Optionally store summaries back to Neo4j
        await self._store_summaries_to_neo4j(group_id, community_info, summaries)
        
        return {
            "community_count": len(clusters),
            "node_count": nx_graph.number_of_nodes(),
            "relationship_count": nx_graph.number_of_edges(),
            "summaries_generated": len(summaries),
        }
    
    async def _store_summaries_to_neo4j(
        self, 
        group_id: str, 
        community_info: Dict[int, Dict[str, Any]],
        summaries: Dict[int, str]
    ) -> None:
        """
        Store community assignments and summaries back to Neo4j.
        
        Creates Community nodes and links Entity nodes to their communities.
        """
        store = self.graph_service.get_store(group_id)
        
        # Create Community nodes with summaries
        for community_id, summary in summaries.items():
            info = community_info.get(community_id, {})
            
            # Create community node
            try:
                store.structured_query(
                    """
                    MERGE (c:Community {id: $community_id, group_id: $group_id})
                    SET c.summary = $summary,
                        c.member_count = $member_count,
                        c.relationship_count = $relationship_count
                    """,
                    param_map={
                        "community_id": f"{group_id}_community_{community_id}",
                        "group_id": group_id,
                        "summary": summary,
                        "member_count": info.get('member_count', 0),
                        "relationship_count": info.get('relationship_count', 0),
                    }
                )
                
                # Link members to community
                members = info.get('members', [])
                for member in members:
                    store.structured_query(
                        """
                        MATCH (c:Community {id: $community_id, group_id: $group_id})
                        MATCH (e) WHERE e.name = $member_name AND e.group_id = $group_id
                        MERGE (e)-[:BELONGS_TO]->(c)
                        """,
                        param_map={
                            "community_id": f"{group_id}_community_{community_id}",
                            "group_id": group_id,
                            "member_name": member,
                        }
                    )
            except Exception as e:
                logger.error(f"Failed to store community {community_id}: {e}")
        
        logger.info(f"Stored {len(summaries)} community summaries to Neo4j")
    
    def get_community_summaries(self, group_id: str) -> Dict[int, str]:
        """
        Get cached community summaries for a group.
        
        If not cached, tries to load from Neo4j.
        """
        if group_id in self._community_summaries:
            return self._community_summaries[group_id]
        
        # Try to load from Neo4j
        store = self.graph_service.get_store(group_id)
        
        try:
            result = store.structured_query(
                """
                MATCH (c:Community)
                WHERE c.group_id = $group_id
                RETURN c.id AS community_id, c.summary AS summary
                """,
                param_map={"group_id": group_id}
            )
            
            summaries = {}
            for record in result or []:
                # Extract community number from ID
                cid = record.get('community_id', '')
                if '_community_' in cid:
                    num = int(cid.split('_community_')[-1])
                    summaries[num] = record.get('summary', '')
            
            self._community_summaries[group_id] = summaries
            return summaries
            
        except Exception as e:
            logger.error(f"Failed to load community summaries: {e}")
            return {}
    
    async def global_search(
        self, 
        group_id: str, 
        query: str,
        top_k: int = 10
    ) -> str:
        """
        Perform GraphRAG Global Search using map-reduce over communities.
        
        Based on LlamaIndex v2 GraphRAGQueryEngine pattern:
        1. Get all community summaries
        2. Generate answer for each community (map)
        3. Aggregate answers into final response (reduce)
        
        Args:
            group_id: Tenant identifier
            query: User query
            top_k: Number of top communities to query (by relevance)
        
        Returns:
            Final aggregated answer
        """
        if not self.llm_service.llm:
            raise ValueError("LLM service not configured")
        
        summaries = self.get_community_summaries(group_id)
        
        if not summaries:
            logger.warning(f"No community summaries found for {group_id}")
            return "No community data available. Please run community detection first."
        
        logger.info(f"Global search across {len(summaries)} communities")
        
        # Map: Generate answer for each community
        community_answers = []
        
        for community_id, summary in list(summaries.items())[:top_k]:
            try:
                answer = await self._generate_answer_from_summary(summary, query)
                if answer and answer.lower() not in ['i don\'t know', 'not relevant', 'n/a']:
                    community_answers.append({
                        'community_id': community_id,
                        'answer': answer,
                    })
            except Exception as e:
                logger.error(f"Error querying community {community_id}: {e}")
        
        if not community_answers:
            return "Could not find relevant information in the knowledge graph communities."
        
        # Reduce: Aggregate answers
        final_answer = await self._aggregate_answers(community_answers, query)
        
        return final_answer
    
    async def _generate_answer_from_summary(self, summary: str, query: str) -> str:
        """Generate answer from a single community summary."""
        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
        
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are a helpful assistant analyzing community summaries from a knowledge graph. "
                    "Given a community summary and a question, provide a relevant answer if the summary "
                    "contains information related to the question. If the summary is not relevant, "
                    "respond with 'Not relevant'."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Community Summary:\n{summary}\n\nQuestion: {query}\n\nAnswer:"
            ),
        ]
        
        response = self.llm_service.llm.chat(messages)
        return re.sub(r"^assistant:\s*", "", str(response)).strip()
    
    async def _aggregate_answers(
        self, 
        community_answers: List[Dict[str, Any]], 
        query: str
    ) -> str:
        """Aggregate community answers into final response."""
        if self.llm_service.llm is None:
            raise RuntimeError("LLM not initialized")
        
        # Combine intermediate answers
        intermediate_text = "\n\n".join([
            f"Community {a['community_id']}: {a['answer']}" 
            for a in community_answers
        ])
        
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You are a helpful assistant synthesizing information from multiple sources. "
                    "Given a set of intermediate answers from different knowledge communities, "
                    "synthesize them into a single, coherent, and comprehensive answer. "
                    "Eliminate redundancy and highlight the most important insights."
                ),
            ),
            ChatMessage(
                role="user",
                content=f"Question: {query}\n\nIntermediate answers:\n{intermediate_text}\n\nFinal answer:"
            ),
        ]
        
        response = self.llm_service.llm.chat(messages)
        return re.sub(r"^assistant:\s*", "", str(response)).strip()
