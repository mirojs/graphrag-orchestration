"""
Stage 3.2: Hub Entity Extraction

Extracts hub entities (most connected nodes) from matched communities.
These hub entities serve as deterministic "landing pads" for HippoRAG PPR.

Used in: Route 3 (Global Search Equivalent)
"""

from typing import List, Dict, Any, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)


class HubExtractor:
    """
    Extracts hub entities from graph communities.
    
    Hub entities are the most connected nodes in a community.
    They serve as optimal starting points for HippoRAG's PPR algorithm
    because:
    1. They have high structural importance
    2. They connect to many other entities
    3. PPR from hubs covers more ground
    
    Example:
        Community: "Compliance"
        Hub Entities: ["Compliance_Policy_2024", "Audit_Committee", "Risk_Officer"]
    """
    
    def __init__(
        self,
        graph_store: Optional[Any] = None,
        neo4j_driver: Optional[Any] = None
    ):
        """
        Args:
            graph_store: LlamaIndex graph store.
            neo4j_driver: Neo4j driver for direct queries.
        """
        self.graph_store = graph_store
        self.neo4j_driver = neo4j_driver
        
        logger.info("hub_extractor_created",
                   has_graph_store=graph_store is not None,
                   has_neo4j=neo4j_driver is not None)
    
    async def extract_hub_entities(
        self,
        communities: List[Dict[str, Any]],
        top_k_per_community: int = 3
    ) -> List[str]:
        """
        Extract hub entities from the given communities.
        
        Args:
            communities: List of community data from CommunityMatcher.
            top_k_per_community: Number of hubs to extract per community.
            
        Returns:
            List of hub entity names/IDs.
        """
        all_hubs: List[str] = []
        
        for community in communities:
            hubs = await self._get_community_hubs(community, top_k_per_community)
            all_hubs.extend(hubs)
        
        # Deduplicate while preserving order
        seen = set()
        unique_hubs = []
        for hub in all_hubs:
            if hub not in seen:
                seen.add(hub)
                unique_hubs.append(hub)
        
        logger.info("hub_extraction_complete",
                   num_communities=len(communities),
                   total_hubs=len(unique_hubs))
        
        return unique_hubs
    
    async def _get_community_hubs(
        self,
        community: Dict[str, Any],
        top_k: int
    ) -> List[str]:
        """Get hub entities for a single community."""
        
        # Try to get pre-computed hubs from community data
        if "hub_entities" in community:
            return community["hub_entities"][:top_k]
        
        if "entities" in community:
            entities = community["entities"]
            # If we have degree info, sort by it
            if entities and isinstance(entities[0], dict):
                sorted_entities = sorted(
                    entities,
                    key=lambda e: e.get("degree", 0),
                    reverse=True
                )
                return [e.get("name", e.get("id", "")) for e in sorted_entities[:top_k]]
            else:
                # Just return first k entities
                return entities[:top_k]
        
        # Try Neo4j query if we have a driver and community ID
        if self.neo4j_driver and "id" in community:
            return await self._query_neo4j_hubs(community["id"], top_k)
        
        # Fallback: use community title as a pseudo-entity
        if "title" in community:
            return [community["title"]]
        
        return []
    
    async def _query_neo4j_hubs(
        self,
        community_id: str,
        top_k: int
    ) -> List[str]:
        """Query Neo4j for hub entities in a community."""
        if self.neo4j_driver is None:
            return []
            
        try:
            # Query for most connected entities in the community
            query = """
            MATCH (e:Entity)-[r]-()
            WHERE e.community = $community_id OR e.community_id = $community_id
            WITH e, count(r) as degree
            ORDER BY degree DESC
            LIMIT $top_k
            RETURN e.name as name, e.id as id, degree
            """
            
            async with self.neo4j_driver.session() as session:
                result = await session.run(
                    query,
                    community_id=community_id,
                    top_k=top_k
                )
                records = await result.data()
            
            hubs = [r.get("name") or r.get("id") for r in records if r]
            
            logger.info("neo4j_hub_query_success",
                       community_id=community_id,
                       num_hubs=len(hubs))
            
            return hubs
            
        except Exception as e:
            logger.error("neo4j_hub_query_failed",
                        community_id=community_id,
                        error=str(e))
            return []
    
    async def get_high_degree_entities(
        self,
        top_k: int = 10
    ) -> List[Tuple[str, int]]:
        """
        Get globally highest-degree entities across the entire graph.
        
        Useful as fallback when no community matches are found.
        
        Returns:
            List of (entity_name, degree) tuples.
        """
        if not self.neo4j_driver:
            logger.warning("no_neo4j_driver_for_global_hubs")
            return []
        
        try:
            query = """
            MATCH (e:Entity)-[r]-()
            WITH e, count(r) as degree
            ORDER BY degree DESC
            LIMIT $top_k
            RETURN e.name as name, e.id as id, degree
            """
            
            async with self.neo4j_driver.session() as session:
                result = await session.run(query, top_k=top_k)
                records = await result.data()
            
            hubs = [
                (r.get("name") or r.get("id"), r.get("degree", 0))
                for r in records if r
            ]
            
            logger.info("global_hub_query_success", num_hubs=len(hubs))
            return hubs
            
        except Exception as e:
            logger.error("global_hub_query_failed", error=str(e))
            return []
