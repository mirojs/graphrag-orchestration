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
        neo4j_driver: Optional[Any] = None,
        group_id: str = "default",
    ):
        """
        Args:
            graph_store: LlamaIndex graph store.
            neo4j_driver: Neo4j driver for direct queries.
        """
        self.graph_store = graph_store
        self.neo4j_driver = neo4j_driver
        self.group_id = group_id
        
        logger.info("hub_extractor_created",
                   has_graph_store=graph_store is not None,
                   has_neo4j=neo4j_driver is not None,
                   group_id=group_id)
    
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
        """Get hub entities for a single community.
        
        For dynamically generated communities (LazyGraphRAG), we try to
        diversify hub selection across multiple source documents to ensure
        cross-document coverage in global queries.
        """
        
        # Try to get pre-computed hubs from community data
        if "hub_entities" in community:
            return community["hub_entities"][:top_k]
        
        if "entities" in community and community["entities"]:
            entities = community["entities"]
            
            # Debug: Log entity format and diversification eligibility
            logger.info("hub_entity_selection_debug",
                       entities_count=len(entities),
                       entities_format=type(entities[0]).__name__ if entities else None,
                       is_dict=isinstance(entities[0], dict) if entities else False,
                       has_neo4j_driver=self.neo4j_driver is not None,
                       top_k=top_k,
                       will_diversify=(not isinstance(entities[0], dict) and self.neo4j_driver is not None and len(entities) >= top_k) if entities else False)
            
            # If we have degree info, sort by it
            if entities and isinstance(entities[0], dict):
                sorted_entities = sorted(
                    entities,
                    key=lambda e: e.get("degree", 0),
                    reverse=True
                )
                return [e.get("name", e.get("id", "")) for e in sorted_entities[:top_k]]
            else:
                # For string entities from LazyGraphRAG dynamic communities:
                # Try to diversify across documents by querying Neo4j for document sources
                if self.neo4j_driver and len(entities) >= top_k:
                    diversified = await self._diversify_entities_by_document(entities, top_k)
                    if diversified:
                        logger.info("hub_entities_diversified_by_document",
                                   original_count=len(entities),
                                   diversified_count=len(diversified))
                        return diversified
                
                # Fallback: Just return first k entities
                return entities[:top_k]
        
        # LazyGraphRAG: Dynamically generated community - query Neo4j for hub entities
        if "keywords" in community:
            logger.info("lazygraphrag_dynamic_hub_extraction", keywords=community["keywords"][:3])
            return await self._query_neo4j_hubs_by_keywords(community["keywords"], top_k)
        
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
            MATCH (e:Entity {group_id: $group_id})-[r]-()
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
                    top_k=top_k,
                    group_id=self.group_id,
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
    
    async def _query_neo4j_hubs_by_keywords(
        self,
        keywords: List[str],
        top_k: int
    ) -> List[str]:
        """
        LazyGraphRAG: Query Neo4j for hub entities matching keywords.
        
        This enables on-the-fly hub extraction without pre-computed communities.
        """
        if self.neo4j_driver is None:
            logger.warning("no_neo4j_driver_for_dynamic_hub_extraction")
            return []
            
        try:
            keyword_list = [kw.strip().lower() for kw in (keywords or []) if kw and kw.strip()]
            keyword_list = keyword_list[:5]

            query = """
            MATCH (e)
            WHERE (e:`__Entity__` OR e:Entity)
              AND e.group_id = $group_id
              AND any(kw IN $keywords WHERE toLower(e.name) CONTAINS kw)
            WITH e
            MATCH (e)-[r]-()
            WITH e, count(r) as degree
            ORDER BY degree DESC
            LIMIT $top_k
            RETURN e.name as name, degree
            """
            
            # Use sync driver with run_in_executor for async compatibility
            import asyncio
            loop = asyncio.get_event_loop()
            
            def _sync_query():
                with self.neo4j_driver.session() as session:
                    result = session.run(
                        query,
                        top_k=top_k,
                        group_id=self.group_id,
                        keywords=keyword_list,
                    )
                    return [r["name"] for r in result if r.get("name")]
            
            hubs = await loop.run_in_executor(None, _sync_query)
            
            logger.info("lazygraphrag_keyword_hub_extraction_success",
                       keywords=keywords[:3],
                       num_hubs=len(hubs))
            
            return hubs
            
        except Exception as e:
            logger.error("neo4j_keyword_hub_query_failed", error=str(e))
            return []
    
    async def _diversify_entities_by_document(
        self,
        entity_names: List[str],
        top_k: int
    ) -> List[str]:
        """
        Select entities that maximize document coverage.
        
        For global queries, we want hub entities from multiple source documents,
        not just the largest/most-connected document.
        """
        if not self.neo4j_driver or not entity_names:
            return []
        
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Query Neo4j to get document source for each entity
            def _sync_query():
                with self.neo4j_driver.session() as session:
                    result = session.run("""
                        UNWIND $entity_names AS entity_name
                        CALL (entity_name) {
                            WITH entity_name
                            MATCH (c:TextChunk)-[:MENTIONS]->(e:Entity)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (c:TextChunk)-[:MENTIONS]->(e:`__Entity__`)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (e:Entity)-[:MENTIONS]->(c:TextChunk)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (e:`__Entity__`)-[:MENTIONS]->(c:TextChunk)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (c:Chunk)-[:MENTIONS]->(e:`__Entity__`)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (e:Entity)-[:MENTIONS]->(c:Chunk)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                            UNION
                            WITH entity_name
                            MATCH (e:`__Entity__`)-[:MENTIONS]->(c:Chunk)
                                                        WHERE c.group_id = $group_id AND e.group_id = $group_id
                                                            AND toLower(e.name) = toLower(entity_name)
                            RETURN c
                        }
                        WITH entity_name, c, apoc.convert.fromJsonMap(c.metadata) AS meta
                        RETURN entity_name, meta.url AS doc_url
                        LIMIT 100
                                        """, entity_names=entity_names, group_id=self.group_id)
                    return [(r["entity_name"], r["doc_url"]) for r in result if r.get("doc_url")]
            
            entity_docs = await loop.run_in_executor(None, _sync_query)
            
            # Group entities by document
            doc_to_entities = {}
            for entity_name, doc_url in entity_docs:
                doc_key = doc_url.split("/")[-1] if doc_url else "unknown"
                if doc_key not in doc_to_entities:
                    doc_to_entities[doc_key] = []
                if entity_name not in doc_to_entities[doc_key]:
                    doc_to_entities[doc_key].append(entity_name)
            
            if not doc_to_entities:
                return []
            
            # Round-robin select entities from different documents
            diversified = []
            doc_keys = list(doc_to_entities.keys())
            doc_indices = {doc: 0 for doc in doc_keys}
            
            while len(diversified) < top_k:
                made_progress = False
                for doc in doc_keys:
                    if len(diversified) >= top_k:
                        break
                    idx = doc_indices[doc]
                    entities = doc_to_entities[doc]
                    if idx < len(entities):
                        entity = entities[idx]
                        if entity not in diversified:
                            diversified.append(entity)
                        doc_indices[doc] = idx + 1
                        made_progress = True
                
                if not made_progress:
                    break
            
            logger.info("entity_diversification_result",
                       num_documents=len(doc_to_entities),
                       documents=list(doc_to_entities.keys()),
                       selected_count=len(diversified))
            
            return diversified
            
        except Exception as e:
            logger.warning("entity_diversification_failed", error=str(e))
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
            CALL () {
                MATCH (e:Entity)-[r]-()
                WHERE e.group_id = $group_id
                RETURN e.name as name, e.id as id, count(r) as degree
                UNION
                MATCH (e:`__Entity__`)-[r]-()
                WHERE e.group_id = $group_id
                RETURN e.name as name, e.id as id, count(r) as degree
            }
            RETURN name, id, degree
            ORDER BY degree DESC
            LIMIT $top_k
            """
            
            async with self.neo4j_driver.session() as session:
                result = await session.run(query, top_k=top_k, group_id=self.group_id)
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
