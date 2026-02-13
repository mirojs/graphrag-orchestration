"""
Stage 3.1: Community Matching for Global Search

Matches thematic queries to relevant graph communities using embedding similarity.
This is the LazyGraphRAG component that identifies "which shelf to look at"
before HippoRAG PPR finds "every relevant page on that shelf."

Used in: Route 3 (Global Search Equivalent)
"""

from typing import List, Dict, Any, Optional, Tuple
import structlog
import json
from pathlib import Path

logger = structlog.get_logger(__name__)


class CommunityMatcher:
    """
    Matches queries to graph communities using embedding similarity.
    
    Communities are pre-computed clusters of related entities with summaries.
    This module finds which communities are most relevant to a thematic query.
    
    Example:
        Query: "What are the main compliance risks?"
        Output: [("Compliance", 0.92), ("Risk Management", 0.87)]
    """
    
    def __init__(
        self,
        embedding_client: Optional[Any] = None,
        communities_path: Optional[str] = None,
        group_id: str = "default",
        neo4j_service: Optional[Any] = None,
        folder_id: Optional[str] = None,
    ):
        """
        Args:
            embedding_client: LlamaIndex or OpenAI embedding client.
            communities_path: Path to pre-computed community data.
            group_id: Tenant identifier.
            neo4j_service: Neo4j service for validating dynamic communities.
            folder_id: Optional folder ID for scoped search (None = all folders).
        """
        self.embedding_client = embedding_client
        self.group_id = group_id
        self.folder_id = folder_id
        self.communities_path = Path(communities_path) if communities_path else None
        self.neo4j_service = neo4j_service
        
        self._communities: List[Dict[str, Any]] = []
        self._community_embeddings: Dict[str, List[float]] = {}
        self._loaded = False
        
        logger.info("community_matcher_created",
                   group_id=group_id,
                   folder_id=folder_id,
                   has_embedding_client=embedding_client is not None,
                   has_neo4j_service=neo4j_service is not None)
    
    async def load_communities(self) -> bool:
        """Load community data and embeddings.

        Priority order:
        1. Neo4j Community nodes (materialized by Step 9 Louvain pipeline)
        2. JSON file (legacy pre-computed communities)
        """
        if self._loaded:
            return True

        # Try Neo4j first — materialized Louvain communities with embeddings
        if self.neo4j_service:
            neo4j_loaded = await self._load_from_neo4j()
            if neo4j_loaded:
                return True

        # Fall back to JSON file
        if self.communities_path and self.communities_path.exists():
            try:
                with open(self.communities_path) as f:
                    data = json.load(f)
                
                self._communities = data.get("communities", [])
                self._community_embeddings = data.get("embeddings", {})
                self._loaded = True
                
                logger.info("communities_loaded_from_json",
                           num_communities=len(self._communities))
                return True
                
            except Exception as e:
                logger.error("community_load_failed", error=str(e))
                return False
        
        logger.warning("no_community_data_found",
                      path=str(self.communities_path))
        return False

    async def _load_from_neo4j(self) -> bool:
        """Load materialized Louvain communities from Neo4j.

        Reads Community nodes created by the indexing pipeline Step 9.
        Communities have title, summary, and (optionally) embedding vectors.

        Returns:
            True if communities were loaded successfully (at least 1 found).
        """
        try:
            query = """
            MATCH (c:Community {group_id: $group_id})
            WHERE c.title IS NOT NULL AND c.title <> ''
            OPTIONAL MATCH (c)<-[:BELONGS_TO]-(e:Entity)
            WITH c, collect(e.name) AS entity_names
            RETURN c.id AS id,
                   c.title AS title,
                   coalesce(c.summary, '') AS summary,
                   coalesce(c.rank, 0.0) AS rank,
                   coalesce(c.level, 0) AS level,
                   c.embedding AS embedding,
                   entity_names
            ORDER BY c.rank DESC
            """
            async with self.neo4j_service._get_session() as session:
                result = await session.run(query, group_id=self.group_id)
                records = await result.data()

            if not records:
                logger.info("no_neo4j_communities_found", group_id=self.group_id)
                return False

            communities = []
            embeddings = {}
            for rec in records:
                community = {
                    "id": rec["id"],
                    "title": rec["title"],
                    "summary": rec["summary"],
                    "rank": rec["rank"],
                    "level": rec["level"],
                    "entity_names": rec["entity_names"],
                }
                communities.append(community)
                if rec["embedding"]:
                    embeddings[rec["id"]] = list(rec["embedding"])

            self._communities = communities
            self._community_embeddings = embeddings
            self._loaded = True

            logger.info(
                "communities_loaded_from_neo4j",
                num_communities=len(communities),
                num_with_embeddings=len(embeddings),
                group_id=self.group_id,
            )
            return True

        except Exception as e:
            logger.warning("neo4j_community_load_failed", error=str(e))
            return False
    
    async def match_communities(
        self,
        query: str,
        top_k: int = 3
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        Find communities most relevant to the query.
        
        LazyGraphRAG approach: Generate communities on-the-fly from Neo4j graph.
        If pre-computed communities exist, use them. Otherwise, dynamically cluster entities.
        
        Args:
            query: The user's thematic query.
            top_k: Number of communities to return.
            
        Returns:
            List of (community_data, similarity_score) tuples.
            
        Raises:
            RuntimeError: If no valid communities can be found or generated.
        """
        # Try to load pre-computed communities first (for compatibility)
        if not self._loaded:
            await self.load_communities()
        
        # If we have pre-computed communities, use semantic matching
        if self._communities and len(self._communities) > 0:
            if self.embedding_client and self._community_embeddings:
                results = await self._semantic_match(query, top_k)
            else:
                logger.warning(
                    "community_matching_no_embeddings",
                    has_embedding_client=self.embedding_client is not None,
                    num_community_embeddings=len(self._community_embeddings),
                    num_communities=len(self._communities),
                )
                results = []
            
            # Validate that we got meaningful results
            if results and len(results) > 0:
                return results
            
            logger.warning("community_matching_found_no_results",
                          num_communities=len(self._communities))
        
        # LazyGraphRAG: Generate communities on-the-fly from Neo4j
        logger.info("lazygraphrag_on_the_fly_community_generation", query=query[:50])
        dynamic_communities = await self._generate_communities_from_query(query, top_k)
        
        # If no valid communities could be generated, return empty list
        # Let the orchestrator handle it via graph-based negative detection
        if not dynamic_communities or len(dynamic_communities) == 0:
            logger.warning(
                "lazygraphrag_no_communities_generated",
                query=query[:100],
                reason="Query keywords don't match any entities in the graph"
            )
            return []
        
        return dynamic_communities
    
    async def _semantic_match(
        self,
        query: str,
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Match using embedding similarity."""
        try:
            # Embed the query
            query_embedding = await self._get_embedding(query)
            if not query_embedding:
                logger.warning("semantic_match_no_query_embedding", query=query[:50])
                return []
            
            # Calculate similarities
            scored: List[Tuple[Dict[str, Any], float]] = []
            dimension_mismatches = 0
            for community in self._communities:
                community_id = community.get("id", community.get("title", ""))
                community_emb = self._community_embeddings.get(community_id)
                
                if community_emb:
                    if len(query_embedding) != len(community_emb):
                        dimension_mismatches += 1
                        continue
                    similarity = self._cosine_similarity(query_embedding, community_emb)
                    scored.append((community, similarity))
            
            if dimension_mismatches > 0:
                logger.error(
                    "semantic_match_dimension_mismatch",
                    query_dim=len(query_embedding),
                    community_dim=len(community_emb) if community_emb else 0,
                    mismatches=dimension_mismatches,
                    total_communities=len(self._communities),
                    hint="Query embedding model may differ from community embedding model",
                )
            
            # Sort by similarity
            scored.sort(key=lambda x: x[1], reverse=True)
            
            # Filter out near-zero scores (indicates broken matching)
            min_threshold = 0.05
            meaningful = [(c, s) for c, s in scored if s >= min_threshold]
            
            if scored and not meaningful:
                logger.warning(
                    "semantic_match_all_below_threshold",
                    threshold=min_threshold,
                    max_score=scored[0][1] if scored else 0,
                    num_communities=len(scored),
                    hint="All community scores near zero — likely embedding mismatch",
                )
                return []  # Fall through to dynamic generation
            
            logger.info("semantic_community_match",
                       query=query[:50],
                       top_scores=[round(s, 4) for _, s in meaningful[:5]],
                       top_matches=[c.get("title", c.get("id", "?"))[:30] for c, _ in meaningful[:top_k]])
            
            return meaningful[:top_k]
            
        except Exception as e:
            logger.error("semantic_match_failed", error=str(e))
            return []
    
    async def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Get embedding for text."""
        if not self.embedding_client:
            return None
        
        try:
            # Handle different embedding client interfaces
            if hasattr(self.embedding_client, 'aget_text_embedding'):
                # LlamaIndex style
                return await self.embedding_client.aget_text_embedding(text)
            elif hasattr(self.embedding_client, 'embed_query'):
                # LangChain style
                return self.embedding_client.embed_query(text)
            elif hasattr(self.embedding_client, 'create'):
                # OpenAI style
                response = await self.embedding_client.create(input=text)
                return response.data[0].embedding
            else:
                logger.warning("unknown_embedding_client_interface")
                return None
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            return None
    
    async def _generate_communities_from_query(
        self,
        query: str,
        top_k: int
    ) -> List[Tuple[Dict[str, Any], float]]:
        """
        LazyGraphRAG: Generate communities on-the-fly from Neo4j graph.
        
        Strategy:
        1. Extract query keywords
        2. Find entities matching keywords in Neo4j
        3. Group entities by their connected components (1-hop neighborhood)
        4. Return top-k clusters as "communities"
        """
        import re
        
        # Extract keywords from query
        stopwords = {"the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "should", "could", "may", "might", "must", "can", "what", "which", "who", "when", "where", "why", "how", "this", "that", "these", "those", "all", "any"}
        
        query_keywords = [
            token.lower() for token in re.findall(r"[A-Za-z0-9]+", query.lower())
            if len(token) >= 3 and token.lower() not in stopwords
        ]
        
        if not query_keywords:
            # Keyword matching will be skipped, but embedding search is the primary path.
            logger.warning("no_keywords_extracted_from_query", query=query[:50])
        
        logger.info("extracted_query_keywords", keywords=query_keywords[:5])
        
        # STRATEGY: Combine EMBEDDING search + keyword supplement + multi-document sampling
        # Priority order:
        # 1. Embedding similarity (most semantically relevant)
        # 2. Keyword supplement (fills gaps when <5 embedding matches)
        # 3. Multi-document sampling (ensures coverage)
        
        embedding_matched_entities = []
        keyword_matched_entities = []
        multi_doc_entities = []
        
        # Step 1: EMBEDDING-BASED entity search (PRIMARY - most consistent & semantic)
        if self.neo4j_service and self.embedding_client:
            try:
                # Get query embedding
                query_embedding = await self._get_embedding(query)
                
                if query_embedding:
                    # Vector similarity search with cross-document diversity
                    # Query entities directly by embedding, then join to chunks for doc diversity
                    embedding_query = """
                    MATCH (e)
                    WHERE (e:Entity OR e:`__Entity__`)
                      AND e.group_id = $group_id 
                      AND (e.embedding_v2 IS NOT NULL OR e.embedding IS NOT NULL)
                    WITH e, vector.similarity.cosine(
                        COALESCE(e.embedding_v2, e.embedding), $query_embedding
                    ) AS similarity
                    WHERE similarity > 0.35
                    OPTIONAL MATCH (src)-[:MENTIONS]->(e)
                    WHERE src.group_id = $group_id
                    OPTIONAL MATCH (src)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                    WITH coalesce(src.url, d.source, d.title, src.document_id, '') AS doc_url, e.name AS name, similarity
                    ORDER BY similarity DESC
                    // Get top entities per document for diversity
                    WITH doc_url, collect({name: name, sim: similarity})[..4] AS entities_per_doc
                    UNWIND entities_per_doc AS entity
                    RETURN DISTINCT entity.name AS name, entity.sim AS similarity
                    ORDER BY similarity DESC
                    LIMIT 15
                    """
                    
                    async with self.neo4j_service._get_session() as session:
                        result = await session.run(
                            embedding_query,
                            group_id=self.group_id,
                            query_embedding=query_embedding
                        )
                        records = await result.data()
                        embedding_matched_entities = [r["name"] for r in records]
                        
                    logger.info("embedding_entity_search",
                              entities_found=len(embedding_matched_entities),
                              top_similarity=records[0].get("similarity") if records else None)
                
            except Exception as e:
                logger.warning("embedding_entity_search_failed", error=str(e))
        
        # Step 2: Keyword-based entity search (SUPPLEMENT when embedding matches < 5)
        if self.neo4j_service and query_keywords and len(embedding_matched_entities) < 5:
            try:
                # Search entities by keyword, diversify across documents
                # Support both Entity and __Entity__ labels for compatibility
                search_query = """
                MATCH (src)-[:MENTIONS]->(e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND src.group_id = $group_id AND e.group_id = $group_id
                WITH src, e
                WHERE (any(keyword IN $keywords WHERE toLower(e.name) CONTAINS keyword)
                       OR any(keyword IN $keywords WHERE toLower(coalesce(e.description, '')) CONTAINS keyword))
                OPTIONAL MATCH (src)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                WITH coalesce(src.url, d.source, d.title, src.document_id, '') AS doc_url, e.name AS name
                // Get first matching entity from each document, round-robin
                WITH doc_url, collect(DISTINCT name)[..3] AS entities_per_doc
                UNWIND entities_per_doc AS name
                RETURN DISTINCT name
                LIMIT 15
                """
                
                async with self.neo4j_service._get_session() as session:
                    result = await session.run(
                        search_query,
                        group_id=self.group_id,
                        keywords=query_keywords
                    )
                    records = await result.data()
                    keyword_matched_entities = [r["name"] for r in records]
                    
                logger.info("keyword_entity_search",
                          keywords_searched=len(query_keywords),
                          entities_found=len(keyword_matched_entities))
                
            except Exception as e:
                logger.error("neo4j_entity_search_failed", error=str(e))

        # Step 3: Multi-document sampling (ALWAYS run for cross-doc coverage)
        if self.neo4j_service:
            try:
                # Get top entities from EACH document to ensure coverage
                # Support both Entity and __Entity__ labels for compatibility
                multi_doc_query = """
                MATCH (src)-[:MENTIONS]->(e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND src.group_id = $group_id AND e.group_id = $group_id
                OPTIONAL MATCH (src)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                WITH coalesce(src.url, d.source, d.title, src.document_id, '') AS doc_url,
                     e.name AS name,
                     coalesce(e.degree, 0) AS deg
                ORDER BY doc_url, deg DESC
                With doc_url, collect({name: name, degree: deg})[..2] AS top_entities
                UNWIND top_entities AS entity
                RETURN entity.name AS name, doc_url
                LIMIT 10
                """

                async with self.neo4j_service._get_session() as session:
                    result = await session.run(multi_doc_query, group_id=self.group_id)
                    records = await result.data()
                    multi_doc_entities = [r["name"] for r in records]

                    doc_sources = list(set(r.get("doc_url", "").split("/")[-1] for r in records if r.get("doc_url")))
                    logger.info(
                        "multi_document_sampling",
                        entities_from_multi_doc=len(multi_doc_entities),
                        documents_covered=len(doc_sources),
                        doc_sources=doc_sources,
                    )

            except Exception as e:
                logger.warning("multi_doc_sampling_failed", error=str(e))
        
        # Combine: embedding matches first (most semantic), then keyword, then multi-doc (coverage)
        # Deduplicate while preserving order
        seen = set()
        matching_entities = []
        for name in embedding_matched_entities + keyword_matched_entities + multi_doc_entities:
            if name not in seen:
                seen.add(name)
                matching_entities.append(name)
        
        logger.info("combined_entity_selection",
                   embedding_matched=len(embedding_matched_entities),
                   keyword_matched=len(keyword_matched_entities),
                   multi_doc=len(multi_doc_entities),
                   final_count=len(matching_entities))
        
        # If still no entities found, try broader embedding search (lower threshold)
        if not matching_entities and self.neo4j_service and self.embedding_client:
            try:
                logger.info("keyword_search_empty_trying_embedding_search",
                           group_id_used=self.group_id)
                
                # Get query embedding
                query_embedding = await self._get_embedding(query)
                
                if query_embedding:
                    # Use vector similarity search to find relevant entities
                    # This is more semantic than keyword matching
                    # Support both Entity and __Entity__ labels for compatibility
                    embedding_query = """
                    MATCH (e)
                    WHERE (e:Entity OR e:`__Entity__`)
                      AND e.group_id = $group_id 
                      AND (e.embedding_v2 IS NOT NULL OR e.embedding IS NOT NULL)
                    WITH e, vector.similarity.cosine(
                        COALESCE(e.embedding_v2, e.embedding), $query_embedding
                    ) AS similarity
                    WHERE similarity > 0.3
                    RETURN e.name AS name, e.description AS description, similarity
                    ORDER BY similarity DESC
                    LIMIT 20
                    """
                    
                    async with self.neo4j_service._get_session() as session:
                        result = await session.run(
                            embedding_query,
                            group_id=self.group_id,
                            query_embedding=query_embedding
                        )
                        records = await result.data()
                        matching_entities = [r["name"] for r in records]
                        
                    logger.info("embedding_search_found_entities",
                              entities_found=len(matching_entities),
                              top_similarity=records[0].get("similarity") if records else None)
                
            except Exception as e:
                logger.warning("embedding_search_failed_trying_fallback", 
                              error=str(e), error_type=type(e).__name__)
        
        # If embedding search failed or unavailable, use MULTI-DOCUMENT SAMPLING fallback
        # This ensures we get entities from ALL documents, not just highest-degree overall
        if not matching_entities and self.neo4j_service:
            try:
                logger.info("trying_multi_document_sampling_fallback",
                           group_id_used=self.group_id)
                
                # Get top entities from EACH document to ensure cross-document coverage
                # This prevents the largest document from dominating results
                # Support both Entity and __Entity__ labels for compatibility
                multi_doc_query = """
                MATCH (src)-[:MENTIONS]->(e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND src.group_id = $group_id AND e.group_id = $group_id
                OPTIONAL MATCH (src)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
                With coalesce(src.url, d.source, d.title, src.document_id, '') AS doc_url, e, coalesce(e.degree, 0) AS deg
                ORDER BY deg DESC
                WITH doc_url, collect({name: e.name, description: e.description, degree: deg})[..3] AS top_entities
                UNWIND top_entities AS entity
                RETURN entity.name AS name, entity.description AS description, doc_url
                LIMIT 15
                """
                
                async with self.neo4j_service._get_session() as session:
                    result = await session.run(multi_doc_query, group_id=self.group_id)
                    records = await result.data()
                    matching_entities = [r["name"] for r in records]
                    
                    # Log which documents we got entities from
                    doc_sources = list(set(r.get("doc_url", "").split("/")[-1] for r in records if r.get("doc_url")))
                    logger.info("multi_document_sampling_result",
                              entities_found=len(matching_entities),
                              documents_covered=len(doc_sources),
                              doc_sources=doc_sources[:5])
                
            except Exception as e:
                logger.warning("multi_doc_sampling_failed_trying_degree_fallback",
                              error=str(e), error_type=type(e).__name__)
        
        # Final fallback: simple degree-based (least preferred, may bias toward largest doc)
        if not matching_entities and self.neo4j_service:
            try:
                logger.info("using_final_degree_fallback",
                           group_id_used=self.group_id,
                           service_connected=self.neo4j_service._driver is not None)
                # Get most important entities as fallback
                # Support both Entity and __Entity__ labels for compatibility
                fallback_query = """
                MATCH (e)
                WHERE (e:Entity OR e:`__Entity__`)
                  AND e.group_id = $group_id
                RETURN e.name AS name, e.description AS description
                ORDER BY coalesce(e.degree, 0) DESC
                LIMIT 10
                """
                
                async with self.neo4j_service._get_session() as session:
                    result = await session.run(fallback_query, group_id=self.group_id)
                    records = await result.data()
                    matching_entities = [r["name"] for r in records]
                    logger.info("fallback_query_raw_result",
                               records_count=len(records),
                               first_record=records[0] if records else None,
                               group_id_param=self.group_id)
                    
                logger.info("fallback_top_entities_found",
                          entities_found=len(matching_entities))
                
            except Exception as e:
                logger.error("fallback_entity_search_failed", error=str(e), error_type=type(e).__name__)
        
        # If still no entities found, return empty (will cause fail-fast)
        if not matching_entities:
            logger.warning("no_entities_found_for_keywords",
                          keywords=query_keywords[:5])
            return []
        
        # Build real community summaries from entity descriptions + source text
        entity_summaries = await self._build_dynamic_community_summaries(
            matching_entities[:15], top_k
        )
        
        return entity_summaries
    
    async def _build_dynamic_community_summaries(
        self,
        entity_names: List[str],
        top_k: int,
    ) -> List[Tuple[Dict[str, Any], float]]:
        """Build real community summaries from entity descriptions and source text.

        Groups entities by document, fetches their descriptions and the sentence/chunk
        text that mentions them, then assembles a substantive summary string that
        Route 3 MAP can extract claims from.

        Returns:
            List of (community_dict, score) tuples — one per document cluster.
        """
        if not self.neo4j_service:
            return []

        try:
            # Fetch entity descriptions + source text grouped by document
            query = """
            UNWIND $entity_names AS ename
            MATCH (e)
            WHERE (e:Entity OR e:`__Entity__`)
              AND e.group_id = $group_id
              AND toLower(e.name) = toLower(ename)
            // Get source sentences/chunks that mention this entity
            OPTIONAL MATCH (src)-[:MENTIONS]->(e)
            WHERE src.group_id = $group_id
            // Resolve document
            OPTIONAL MATCH (src)-[:IN_DOCUMENT]->(d:Document {group_id: $group_id})
            OPTIONAL MATCH (src)-[:PART_OF]->(chunk:TextChunk)-[:IN_DOCUMENT]->(d2:Document {group_id: $group_id})
            WITH e,
                 coalesce(d.title, d2.title, 'Unknown') AS doc_title,
                 coalesce(d.id, d2.id, 'unknown') AS doc_id,
                 CASE WHEN src:Sentence THEN src.text ELSE null END AS sentence_text,
                 CASE WHEN src:TextChunk THEN src.text ELSE null END AS chunk_text
            WITH doc_id, doc_title,
                 collect(DISTINCT {
                     name: e.name,
                     description: coalesce(e.description, ''),
                     type: coalesce(e.type, '')
                 }) AS entities,
                 collect(DISTINCT sentence_text)[..8] AS sentences,
                 collect(DISTINCT chunk_text)[..3] AS chunks
            RETURN doc_id, doc_title, entities, sentences, chunks
            ORDER BY size(entities) DESC
            """

            async with self.neo4j_service._get_session() as session:
                result = await session.run(
                    query, group_id=self.group_id, entity_names=entity_names
                )
                records = await result.data()

            if not records:
                logger.warning("dynamic_community_no_records", entity_count=len(entity_names))
                return []

            communities: List[Tuple[Dict[str, Any], float]] = []
            for i, rec in enumerate(records[:top_k]):
                doc_title = rec["doc_title"]
                entities = rec["entities"]
                sentences = [s for s in rec.get("sentences", []) if s]
                chunks = [c for c in rec.get("chunks", []) if c]

                # Build a substantive summary from entity descriptions + source text
                parts = []

                # Entity descriptions
                entity_descs = []
                entity_name_list = []
                for ent in entities:
                    entity_name_list.append(ent["name"])
                    if ent.get("description"):
                        entity_descs.append(f"- {ent['name']}: {ent['description']}")
                if entity_descs:
                    parts.append("Key entities and descriptions:\n" + "\n".join(entity_descs[:10]))

                # Source text (prefer sentences — more precise)
                source_texts = sentences[:6] or chunks[:3]
                if source_texts:
                    parts.append("Relevant excerpts:\n" + "\n".join(
                        f"- {t.strip()}" for t in source_texts if t.strip()
                    ))

                summary = "\n\n".join(parts) if parts else f"Document contains entities: {', '.join(entity_name_list[:10])}"

                community = {
                    "id": f"dynamic_{self.group_id}_{doc_title}_{i}",
                    "title": doc_title,
                    "summary": summary,
                    "entity_names": entity_name_list[:20],
                }
                # Score decreases for lower-ranked documents
                score = 1.0 - (i * 0.1)
                communities.append((community, max(score, 0.5)))

            logger.info(
                "dynamic_communities_built",
                count=len(communities),
                titles=[c.get("title", "?") for c, _ in communities],
                total_summary_chars=sum(len(c.get("summary", "")) for c, _ in communities),
            )
            return communities

        except Exception as e:
            logger.error("build_dynamic_community_summaries_failed", error=str(e))
            return []

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def get_community_summaries(self) -> List[Dict[str, str]]:
        """Get summaries of all communities for context."""
        return [
            {
                "title": c.get("title", f"Community {i}"),
                "summary": c.get("summary", "No summary available")[:500]
            }
            for i, c in enumerate(self._communities)
        ]
