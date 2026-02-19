"""Stage 3.1: Community Matching for Global Search.

Matches thematic queries to relevant graph communities using embedding
similarity.  Communities are pre-computed by the Louvain pipeline
(Step 9) and stored as `:Community` nodes in Neo4j with embeddings.

When embeddings are missing or have a dimension mismatch against the
current Voyage model, this module transparently re-embeds the
community summaries at first load — ensuring cosine similarity scores
are always meaningful.

Used in: Route 3 (Global Search), Route 5 (Unified Search — Tier 3 seeds)
"""

from typing import List, Dict, Any, Optional, Tuple
import hashlib
import structlog
import json
from pathlib import Path
import asyncio

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
        self._summary_hashes: Dict[str, str] = {}  # community_id -> hash of text that was embedded
        self._loaded = False
        
        logger.info("community_matcher_created",
                   group_id=group_id,
                   folder_id=folder_id,
                   has_embedding_client=embedding_client is not None,
                   has_neo4j_service=neo4j_service is not None)
    
    async def load_communities(self) -> bool:
        """Load community data, embeddings, and ensure dimension parity.

        Priority order:
        1. Neo4j Community nodes (materialized by Step 9 Louvain pipeline)
        2. JSON file (legacy pre-computed communities)

        After loading, ``_ensure_embeddings()`` re-embeds any communities
        whose stored embedding is missing or has a dimension mismatch with
        the current Voyage model.
        """
        if self._loaded:
            return True

        # Try Neo4j first — materialized Louvain communities with embeddings
        if self.neo4j_service:
            neo4j_loaded = await self._load_from_neo4j()
            if neo4j_loaded:
                await self._ensure_embeddings()
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
                await self._ensure_embeddings()
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
                   c.embedding_text_hash AS embedding_text_hash,
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
            summary_hashes = {}
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
                if rec.get("embedding_text_hash"):
                    summary_hashes[rec["id"]] = rec["embedding_text_hash"]

            self._communities = communities
            self._community_embeddings = embeddings
            self._summary_hashes = summary_hashes
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
        """Find communities most relevant to the query via embedding similarity.

        Args:
            query: The user's thematic query.
            top_k: Number of communities to return.

        Returns:
            List of (community_data, similarity_score) tuples, ordered by
            descending similarity.  Empty list when no communities exist or
            none exceed the minimum similarity threshold.
        """
        if not self._loaded:
            await self.load_communities()

        if not self._communities:
            logger.warning("community_matching_no_communities_loaded")
            return []

        if not self.embedding_client:
            logger.warning("community_matching_no_embedding_client")
            return []

        if not self._community_embeddings:
            logger.warning(
                "community_matching_no_embeddings",
                num_communities=len(self._communities),
                hint="_ensure_embeddings may not have been called or failed",
            )
            return []

        results = await self._semantic_match(query, top_k)
        if not results:
            logger.info(
                "community_matching_no_results_above_threshold",
                query=query[:80],
                num_communities=len(self._communities),
            )
        return results
    
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
        """Get embedding for text using the configured embedding client."""
        if not self.embedding_client:
            return None

        try:
            # Handle different embedding client interfaces
            if hasattr(self.embedding_client, 'aget_text_embedding'):
                # LlamaIndex style (async)
                return await self.embedding_client.aget_text_embedding(text)
            elif hasattr(self.embedding_client, 'embed_query'):
                # VoyageEmbedService / LangChain style (sync)
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None, self.embedding_client.embed_query, text
                )
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

    async def _get_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Batch-embed a list of texts.

        Prefers the client's batch API when available (``embed_query_batch``)
        to save round-trips and reduce Voyage API calls.
        """
        if not self.embedding_client:
            return [None] * len(texts)

        # VoyageEmbedService has embed_query_batch
        if hasattr(self.embedding_client, 'embed_query_batch'):
            try:
                loop = asyncio.get_event_loop()
                results = await loop.run_in_executor(
                    None, self.embedding_client.embed_query_batch, texts
                )
                return results  # type: ignore[return-value]
            except Exception as e:
                logger.warning("batch_embedding_failed_falling_back", error=str(e))

        # Fallback: embed one by one
        embeddings: List[Optional[List[float]]] = []
        for text in texts:
            emb = await self._get_embedding(text)
            embeddings.append(emb)
        return embeddings
    


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
    
    # ==================================================================
    # Embedding Repair
    # ==================================================================

    def _compute_text_hash(self, community: Dict[str, Any]) -> str:
        """Compute hash of the text that would be embedded for a community.

        Used to detect when a community's summary has changed but the stored
        embedding is stale (e.g., generated from fallback entity-name text
        before an LLM summary was added).

        Returns:
            First 16 chars of SHA256 hex digest of the embedding source text.
        """
        text = community.get("summary", "").strip()
        if not text:
            title = community.get("title", "")
            enames = community.get("entity_names", [])
            text = f"{title}. Entities: {', '.join(enames[:15])}" if enames else title
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    async def _ensure_embeddings(self) -> None:
        """Re-embed community summaries whose stored embedding is missing, dimension-mismatched, or stale.

        After this method completes, every community in ``self._communities``
        has a corresponding entry in ``self._community_embeddings`` whose
        dimension matches the current embedding model.  Communities that
        cannot be embedded (empty summary) are skipped.

        Staleness detection: each embedding is paired with a hash of the text
        that was embedded.  If the current text hash differs from the stored
        hash (e.g., summary was updated from empty to an LLM summary), the
        community is re-embedded even if the dimension is correct.

        Optionally writes the fresh embeddings back to Neo4j so future
        loads don't need another round-trip to the Voyage API.  Controlled
        by the ``COMMUNITY_WRITEBACK_EMBEDDINGS`` env var (default: ``1``).
        """
        if not self.embedding_client:
            logger.warning("ensure_embeddings_no_client")
            return

        # Determine the expected dimension from the embedding client
        expected_dim: Optional[int] = None
        if hasattr(self.embedding_client, 'embed_dim'):
            expected_dim = self.embedding_client.embed_dim

        # Identify communities needing (re-)embedding
        needs_embedding: List[int] = []  # indices into self._communities
        stale_count = 0
        for idx, community in enumerate(self._communities):
            cid = community.get("id", community.get("title", ""))
            existing = self._community_embeddings.get(cid)
            if existing is None:
                needs_embedding.append(idx)
            elif expected_dim and len(existing) != expected_dim:
                needs_embedding.append(idx)
            else:
                # Check if the source text has changed since last embedding
                current_hash = self._compute_text_hash(community)
                stored_hash = self._summary_hashes.get(cid, "")
                if current_hash != stored_hash:
                    needs_embedding.append(idx)
                    stale_count += 1
                    logger.info(
                        "community_embedding_stale_content_changed",
                        community_id=cid,
                        stored_hash=stored_hash[:8] if stored_hash else "(none)",
                        current_hash=current_hash[:8],
                    )

        if not needs_embedding:
            logger.info("ensure_embeddings_all_ok",
                       total=len(self._communities),
                       expected_dim=expected_dim)
            return

        logger.info(
            "ensure_embeddings_re_embedding",
            communities_to_embed=len(needs_embedding),
            stale_content=stale_count,
            total_communities=len(self._communities),
            expected_dim=expected_dim,
        )

        # Build texts to embed: prefer summary, fall back to title + entity names
        texts: List[str] = []
        valid_indices: List[int] = []
        for idx in needs_embedding:
            c = self._communities[idx]
            text = c.get("summary", "").strip()
            if not text:
                # Fallback: construct synthetic summary from title + entities.
                # This produces a lower-quality embedding than a real summary.
                title = c.get("title", "")
                enames = c.get("entity_names", [])
                if title or enames:
                    text = f"{title}. Entities: {', '.join(enames[:15])}" if enames else title
                    logger.warning(
                        "community_embedding_fallback_no_summary",
                        community_id=c.get("id", ""),
                        community_title=title,
                        entity_count=len(enames),
                    )
            if not text:
                continue  # Skip communities with no content to embed
            texts.append(text)
            valid_indices.append(idx)

        if not texts:
            logger.warning("ensure_embeddings_no_text_to_embed")
            return

        embeddings = await self._get_embeddings_batch(texts)

        refreshed = 0
        cids_refreshed: List[str] = []
        for i, idx in enumerate(valid_indices):
            emb = embeddings[i]
            if emb is not None:
                cid = self._communities[idx].get("id", self._communities[idx].get("title", ""))
                self._community_embeddings[cid] = emb
                refreshed += 1
                cids_refreshed.append(cid)

        logger.info(
            "ensure_embeddings_complete",
            refreshed=refreshed,
            failed=len(valid_indices) - refreshed,
            new_dim=len(embeddings[0]) if embeddings and embeddings[0] else None,
        )

        # Optional: write embeddings back to Neo4j for persistence
        import os
        writeback = os.getenv("COMMUNITY_WRITEBACK_EMBEDDINGS", "1").strip().lower() in {"1", "true", "yes"}
        if writeback and self.neo4j_service and cids_refreshed:
            await self._writeback_embeddings(cids_refreshed)

    async def _writeback_embeddings(self, community_ids: List[str]) -> None:
        """Persist refreshed community embeddings and text hashes back to Neo4j.

        This avoids the need to re-embed on subsequent application restarts.
        The text hash enables stale-embedding detection when summaries are
        updated after the embedding was generated.
        """
        try:
            cypher = """
            UNWIND $rows AS row
            MATCH (c:Community {group_id: $group_id})
            WHERE c.id = row.id
            SET c.embedding = row.embedding,
                c.embedding_text_hash = row.text_hash
            """
            rows = []
            for cid in community_ids:
                if cid not in self._community_embeddings:
                    continue
                # Find the community dict to compute the hash
                community = next(
                    (c for c in self._communities
                     if c.get("id", c.get("title", "")) == cid),
                    None,
                )
                text_hash = self._compute_text_hash(community) if community else ""
                rows.append({
                    "id": cid,
                    "embedding": self._community_embeddings[cid],
                    "text_hash": text_hash,
                })
            if not rows:
                return

            async with self.neo4j_service._get_session() as session:
                await session.run(cypher, rows=rows, group_id=self.group_id)

            # Update in-memory hashes
            for row in rows:
                self._summary_hashes[row["id"]] = row["text_hash"]

            logger.info("community_embeddings_written_back", count=len(rows))
        except Exception as e:
            logger.warning("community_embeddings_writeback_failed", error=str(e))

    # ==================================================================
    # Accessors
    # ==================================================================

    def get_community_summaries(self) -> List[Dict[str, str]]:
        """Get summaries of all loaded communities for synthesis context."""
        return [
            {
                "title": c.get("title", f"Community {i}"),
                "summary": c.get("summary", "No summary available")[:500]
            }
            for i, c in enumerate(self._communities)
        ]
