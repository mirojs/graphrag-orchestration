"""True Personalized PageRank with Passage Nodes for HippoRAG 2.

Implements the core HippoRAG 2 graph architecture where PPR operates on
a unified graph containing BOTH entity nodes AND passage (TextChunk) nodes.

Key differences from the existing hipporag_retriever.py PPR:

1. **Passage nodes in graph**: TextChunk nodes are first-class graph nodes,
   connected to entities via MENTIONS edges. PPR probability mass flows
   Entity <-> Passage, so passage scores come directly from the random walk.

2. **Weighted edges**: Edge weights are used in rank distribution. MENTIONS
   edges get a configurable passage_node_weight (default 0.05) to balance
   entity vs. passage influence. SEMANTICALLY_SIMILAR edges use their
   stored cosine similarity score.

3. **Undirected graph**: All edges are bidirectional (matching upstream
   HippoRAG 2 which uses igraph with directed=False).

4. **Damping = 0.5**: Upstream default (vs our existing 0.85).

5. **Dual output**: Returns both passage scores (document rankings) and
   entity scores (for synthesis evidence_nodes).

Reference: HippoRAG 2 (ICML '25) — https://arxiv.org/abs/2502.14802
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


class HippoRAG2PPR:
    """True in-memory PPR with passage nodes.

    Graph structure:
        Nodes: Entity nodes + TextChunk (passage) nodes
        Edges (undirected, weighted):
            - Entity <-> Entity via RELATED_TO (weight = r.weight, default 1.0)
            - Entity <-> Passage via MENTIONS (weight = passage_node_weight)
            - Entity <-> Entity via SEMANTICALLY_SIMILAR (weight = similarity)

    Seed vector:
        - Entity seeds: from triple linking (query-to-triple matching)
        - Passage seeds: from DPR retrieval (score * passage_node_weight)

    Output:
        - passage_scores: ranked TextChunk IDs (= document/chunk rankings)
        - entity_scores: ranked entity names (for synthesis evidence_nodes)
    """

    def __init__(self) -> None:
        self._node_to_idx: Dict[str, int] = {}  # node_id -> index
        self._idx_to_node: Dict[int, str] = {}  # index -> node_id
        self._node_types: Dict[int, str] = {}  # index -> "entity"|"passage"
        self._node_names: Dict[int, str] = {}  # index -> display name
        # Weighted adjacency: source_idx -> [(target_idx, weight)]
        self._adj: Dict[int, List[Tuple[int, float]]] = {}
        # Precomputed sum of outgoing weights per node (for rank distribution)
        self._out_weight_sum: Dict[int, float] = {}
        self._loaded = False
        self._node_count = 0

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def node_count(self) -> int:
        return self._node_count

    def _add_node(self, node_id: str, node_type: str, name: str) -> int:
        """Add a node to the graph, return its index."""
        if node_id in self._node_to_idx:
            return self._node_to_idx[node_id]
        idx = self._node_count
        self._node_to_idx[node_id] = idx
        self._idx_to_node[idx] = node_id
        self._node_types[idx] = node_type
        self._node_names[idx] = name
        self._adj[idx] = []
        self._node_count += 1
        return idx

    def _add_edge(self, src_idx: int, tgt_idx: int, weight: float) -> None:
        """Add a weighted undirected edge (both directions)."""
        self._adj[src_idx].append((tgt_idx, weight))
        self._adj[tgt_idx].append((src_idx, weight))

    def _finalize_graph(self) -> None:
        """Precompute outgoing weight sums for efficient PPR iteration."""
        for idx in range(self._node_count):
            edges = self._adj.get(idx, [])
            self._out_weight_sum[idx] = sum(w for _, w in edges) if edges else 0.0

    async def load_graph(
        self,
        neo4j_driver: Any,
        group_id: str,
        passage_node_weight: float = 0.05,
        synonym_threshold: float = 0.8,
        include_section_graph: bool = False,
        section_edge_weight: float = 0.1,
        section_sim_threshold: float = 0.5,
    ) -> None:
        """Load Entity + TextChunk nodes and edges from Neo4j.

        Args:
            neo4j_driver: Sync Neo4j driver instance.
            group_id: Multi-tenant group ID.
            passage_node_weight: Weight for MENTIONS edges (default 0.05).
            synonym_threshold: Min similarity for SEMANTICALLY_SIMILAR entity
                edges (default 0.8, matching upstream HippoRAG 2).
            include_section_graph: Phase 2 — also load Section nodes and edges.
            section_edge_weight: Weight for IN_SECTION edges (default 0.1).
            section_sim_threshold: Min similarity for section SEMANTICALLY_SIMILAR
                edges (default 0.5).
        """
        t0 = time.perf_counter()

        await asyncio.to_thread(
            self._load_graph_sync,
            neo4j_driver,
            group_id,
            passage_node_weight,
            synonym_threshold,
            include_section_graph,
            section_edge_weight,
            section_sim_threshold,
        )

        self._finalize_graph()
        self._loaded = True

        entity_count = sum(
            1 for t in self._node_types.values() if t == "entity"
        )
        passage_count = sum(
            1 for t in self._node_types.values() if t == "passage"
        )
        section_count = sum(
            1 for t in self._node_types.values() if t == "section"
        )
        edge_count = sum(len(edges) for edges in self._adj.values()) // 2

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "hipporag2_ppr_graph_loaded",
            group_id=group_id,
            total_nodes=self._node_count,
            entity_nodes=entity_count,
            passage_nodes=passage_count,
            section_nodes=section_count,
            edges=edge_count,
            elapsed_ms=elapsed_ms,
        )

    def _load_graph_sync(
        self,
        neo4j_driver: Any,
        group_id: str,
        passage_node_weight: float,
        synonym_threshold: float,
        include_section_graph: bool,
        section_edge_weight: float,
        section_sim_threshold: float,
    ) -> None:
        """Synchronous graph loading from Neo4j."""
        entity_edge_count = 0
        mentions_edge_count = 0
        synonym_edge_count = 0
        # Bug 11 fix: deduplicate undirected edges.
        # _add_edge adds both A→B and B→A. If Neo4j stores both directions of a
        # RELATED_TO/SEMANTICALLY_SIMILAR edge (common with MERGE-based ingestion),
        # calling _add_edge twice creates 4 adjacency entries instead of 2 and
        # doubles edge weight in PPR. Track canonical (min_idx, max_idx) pairs.
        seen_entity_edges: set = set()
        seen_synonym_edges: set = set()

        with neo4j_driver.session() as session:
            # ----------------------------------------------------------
            # 1. Load Entity nodes
            # ----------------------------------------------------------
            result = session.run(
                "MATCH (e:Entity {group_id: $group_id}) "
                "RETURN e.id AS id, e.name AS name",
                group_id=group_id,
            )
            for record in result:
                self._add_node(record["id"], "entity", record["name"] or "")

            # ----------------------------------------------------------
            # 2. Load TextChunk (passage) nodes
            # ----------------------------------------------------------
            result = session.run(
                "MATCH (c:TextChunk {group_id: $group_id}) "
                "RETURN c.id AS id, c.text AS text",
                group_id=group_id,
            )
            for record in result:
                # Use first 80 chars of text as display name
                text = (record["text"] or "")[:80]
                self._add_node(record["id"], "passage", text)

            # ----------------------------------------------------------
            # 3. Entity-Entity edges via RELATED_TO
            # ----------------------------------------------------------
            result = session.run(
                "MATCH (e1:Entity {group_id: $group_id})"
                "-[r:RELATED_TO]->"
                "(e2:Entity {group_id: $group_id}) "
                "RETURN e1.id AS src, e2.id AS tgt, "
                "coalesce(r.weight, 1.0) AS weight",
                group_id=group_id,
            )
            for record in result:
                src_idx = self._node_to_idx.get(record["src"])
                tgt_idx = self._node_to_idx.get(record["tgt"])
                if src_idx is not None and tgt_idx is not None:
                    edge_key = (min(src_idx, tgt_idx), max(src_idx, tgt_idx))
                    if edge_key not in seen_entity_edges:
                        seen_entity_edges.add(edge_key)
                        self._add_edge(src_idx, tgt_idx, float(record["weight"]))
                        entity_edge_count += 1

            # ----------------------------------------------------------
            # 4. Passage-Entity edges via MENTIONS
            # ----------------------------------------------------------
            result = session.run(
                "MATCH (c:TextChunk {group_id: $group_id})"
                "-[:MENTIONS]->"
                "(e:Entity {group_id: $group_id}) "
                "RETURN c.id AS chunk_id, e.id AS entity_id",
                group_id=group_id,
            )
            for record in result:
                src_idx = self._node_to_idx.get(record["chunk_id"])
                tgt_idx = self._node_to_idx.get(record["entity_id"])
                if src_idx is not None and tgt_idx is not None:
                    self._add_edge(src_idx, tgt_idx, passage_node_weight)
                    mentions_edge_count += 1

            # ----------------------------------------------------------
            # 5. Entity-Entity synonym edges via SEMANTICALLY_SIMILAR
            # ----------------------------------------------------------
            result = session.run(
                "MATCH (e1:Entity {group_id: $group_id})"
                "-[s:SEMANTICALLY_SIMILAR]->"
                "(e2:Entity {group_id: $group_id}) "
                "WHERE s.similarity >= $threshold "
                "RETURN e1.id AS src, e2.id AS tgt, "
                "s.similarity AS weight",
                group_id=group_id,
                threshold=synonym_threshold,
            )
            for record in result:
                src_idx = self._node_to_idx.get(record["src"])
                tgt_idx = self._node_to_idx.get(record["tgt"])
                if src_idx is not None and tgt_idx is not None:
                    edge_key = (min(src_idx, tgt_idx), max(src_idx, tgt_idx))
                    if edge_key not in seen_synonym_edges:
                        seen_synonym_edges.add(edge_key)
                        self._add_edge(src_idx, tgt_idx, float(record["weight"]))
                        synonym_edge_count += 1

            # ----------------------------------------------------------
            # 6. Phase 2: Section graph (optional)
            # ----------------------------------------------------------
            if include_section_graph:
                self._load_section_graph_sync(
                    session, group_id, section_edge_weight, section_sim_threshold
                )

        logger.debug(
            "hipporag2_ppr_edges_loaded",
            entity_edges=entity_edge_count,
            mentions_edges=mentions_edge_count,
            synonym_edges=synonym_edge_count,
        )

    def _load_section_graph_sync(
        self,
        session: Any,
        group_id: str,
        section_edge_weight: float,
        section_sim_threshold: float,
    ) -> None:
        """Load Section nodes and edges for Phase 2 augmentation."""
        # Section nodes
        result = session.run(
            "MATCH (s:Section {group_id: $group_id}) "
            "RETURN s.id AS id, s.title AS title",
            group_id=group_id,
        )
        for record in result:
            self._add_node(record["id"], "section", record["title"] or "")

        # Passage <-> Section via IN_SECTION
        result = session.run(
            "MATCH (c:TextChunk {group_id: $group_id})"
            "-[:IN_SECTION]->"
            "(s:Section {group_id: $group_id}) "
            "RETURN c.id AS chunk_id, s.id AS section_id",
            group_id=group_id,
        )
        for record in result:
            src_idx = self._node_to_idx.get(record["chunk_id"])
            tgt_idx = self._node_to_idx.get(record["section_id"])
            if src_idx is not None and tgt_idx is not None:
                self._add_edge(src_idx, tgt_idx, section_edge_weight)

        # Section <-> Section via SEMANTICALLY_SIMILAR
        result = session.run(
            "MATCH (s1:Section {group_id: $group_id})"
            "-[sim:SEMANTICALLY_SIMILAR]->"
            "(s2:Section {group_id: $group_id}) "
            "WHERE sim.similarity >= $threshold "
            "RETURN s1.id AS src, s2.id AS tgt, "
            "sim.similarity AS weight",
            group_id=group_id,
            threshold=section_sim_threshold,
        )
        for record in result:
            src_idx = self._node_to_idx.get(record["src"])
            tgt_idx = self._node_to_idx.get(record["tgt"])
            if src_idx is not None and tgt_idx is not None:
                self._add_edge(src_idx, tgt_idx, float(record["weight"]))

    def run_ppr(
        self,
        entity_seeds: Dict[str, float],
        passage_seeds: Dict[str, float],
        damping: float = 0.5,
        max_iterations: int = 50,
        convergence_threshold: float = 1e-6,
    ) -> Tuple[List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Run Personalized PageRank with weighted seeds.

        Power iteration on the weighted undirected graph. Both entity and
        passage nodes can be seeds. After convergence, passage node scores
        become document/chunk rankings and entity node scores become
        synthesis evidence.

        Args:
            entity_seeds: {entity_id: weight} — from triple linking.
            passage_seeds: {chunk_id: weight} — from DPR (score * passage_node_weight).
            damping: Damping factor (default 0.5, upstream HippoRAG 2).
            max_iterations: Max power iteration steps.
            convergence_threshold: L1 convergence threshold.

        Returns:
            Tuple of:
                - passage_scores: [(chunk_id, score)] sorted desc
                - entity_scores: [(entity_name, score)] sorted desc
        """
        if self._node_count == 0:
            return [], []

        # Build personalization vector
        personalization = [0.0] * self._node_count

        for node_id, weight in entity_seeds.items():
            idx = self._node_to_idx.get(node_id)
            if idx is not None:
                personalization[idx] += weight

        for node_id, weight in passage_seeds.items():
            idx = self._node_to_idx.get(node_id)
            if idx is not None:
                personalization[idx] += weight

        # Normalize personalization to sum to 1
        total_p = sum(personalization)
        if total_p <= 0:
            logger.warning("ppr_no_valid_seeds")
            return [], []
        personalization = [p / total_p for p in personalization]

        # Initialize rank to personalization vector
        rank = list(personalization)

        # Power iteration with weighted edges
        for iteration in range(max_iterations):
            new_rank = [
                (1.0 - damping) * personalization[i]
                for i in range(self._node_count)
            ]

            for src in range(self._node_count):
                if rank[src] == 0.0:
                    continue
                out_sum = self._out_weight_sum.get(src, 0.0)
                if out_sum == 0.0:
                    continue
                for tgt, edge_weight in self._adj[src]:
                    # Weighted random walk: probability proportional to edge weight
                    share = damping * rank[src] * edge_weight / out_sum
                    new_rank[tgt] += share

            # Check convergence (L1 norm)
            diff = sum(abs(new_rank[i] - rank[i]) for i in range(self._node_count))
            rank = new_rank

            if diff < convergence_threshold:
                logger.debug(
                    "hipporag2_ppr_converged",
                    iteration=iteration,
                    diff=diff,
                )
                break

        # Extract passage scores and entity scores
        passage_scores: List[Tuple[str, float]] = []
        entity_scores: List[Tuple[str, float]] = []

        for idx in range(self._node_count):
            node_id = self._idx_to_node[idx]
            node_type = self._node_types[idx]
            score = rank[idx]

            if node_type == "passage":
                passage_scores.append((node_id, score))
            elif node_type == "entity":
                name = self._node_names[idx]
                entity_scores.append((name, score))

        # Sort descending by score
        passage_scores.sort(key=lambda x: x[1], reverse=True)
        entity_scores.sort(key=lambda x: x[1], reverse=True)

        logger.info(
            "hipporag2_ppr_complete",
            iterations=min(iteration + 1, max_iterations) if self._node_count > 0 else 0,
            entity_seeds=len(entity_seeds),
            passage_seeds=len(passage_seeds),
            top_passage_score=passage_scores[0][1] if passage_scores else 0.0,
            top_entity_score=entity_scores[0][1] if entity_scores else 0.0,
        )

        return passage_scores, entity_scores
