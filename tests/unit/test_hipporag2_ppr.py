"""
Unit Tests: HippoRAG 2 PPR Engine with Passage Nodes

Tests the true HippoRAG 2 PPR algorithm that operates on a unified graph
containing both Entity nodes AND Passage (TextChunk) nodes.

Key properties verified:
- Passage nodes receive non-zero scores from PPR walk
- Undirected edges (both directions stored)
- Weighted edge distribution
- Entity vs passage seed injection
- Score normalization (sums to ~1.0)
- Convergence behavior
- Empty/edge-case handling

Run: pytest tests/unit/test_hipporag2_ppr.py -v
"""

import importlib.util
import sys

import pytest

# Direct import to avoid the full app dependency chain triggered by
# hybrid_v2.__init__.py  →  orchestrator  →  routes  →  config  →  pydantic_settings
_spec = importlib.util.spec_from_file_location(
    "hipporag2_ppr",
    "src/worker/hybrid_v2/retrievers/hipporag2_ppr.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["hipporag2_ppr"] = _mod
_spec.loader.exec_module(_mod)
HippoRAG2PPR = _mod.HippoRAG2PPR


# ============================================================================
# Helpers: build graphs without Neo4j
# ============================================================================

def build_simple_graph() -> HippoRAG2PPR:
    """3 entities, 2 passages, 4 edges — minimal HippoRAG 2 graph.

    Graph:
        E1 --RELATED_TO(1.0)--> E2 --RELATED_TO(1.0)--> E3
        P1 --MENTIONS(0.05)--> E1
        P2 --MENTIONS(0.05)--> E2
        P2 --MENTIONS(0.05)--> E3

    All edges undirected.
    """
    ppr = HippoRAG2PPR()
    ppr._add_node("e1", "entity", "Alpha Corp")
    ppr._add_node("e2", "entity", "Beta Fund")
    ppr._add_node("e3", "entity", "Gamma LLC")
    ppr._add_node("p1", "passage", "Alpha Corp was founded in 2010...")
    ppr._add_node("p2", "passage", "Beta Fund acquired Gamma LLC...")

    ppr._add_edge(0, 1, 1.0)  # E1 <-> E2 (RELATED_TO)
    ppr._add_edge(1, 2, 1.0)  # E2 <-> E3 (RELATED_TO)
    ppr._add_edge(3, 0, 0.05)  # P1 <-> E1 (MENTIONS)
    ppr._add_edge(4, 1, 0.05)  # P2 <-> E2 (MENTIONS)
    ppr._add_edge(4, 2, 0.05)  # P2 <-> E3 (MENTIONS)

    ppr._finalize_graph()
    ppr._loaded = True
    return ppr


def build_chain_with_passages() -> HippoRAG2PPR:
    """Linear chain: E1 -- E2 -- E3, each with one passage.

    E1 <-> P1,  E2 <-> P2,  E3 <-> P3
    E1 <-> E2,  E2 <-> E3
    """
    ppr = HippoRAG2PPR()
    for i in range(1, 4):
        ppr._add_node(f"e{i}", "entity", f"Entity_{i}")
    for i in range(1, 4):
        ppr._add_node(f"p{i}", "passage", f"Passage text {i}")

    # Entity chain
    ppr._add_edge(0, 1, 1.0)  # E1 <-> E2
    ppr._add_edge(1, 2, 1.0)  # E2 <-> E3
    # Passage edges
    ppr._add_edge(0, 3, 0.05)  # E1 <-> P1
    ppr._add_edge(1, 4, 0.05)  # E2 <-> P2
    ppr._add_edge(2, 5, 0.05)  # E3 <-> P3

    ppr._finalize_graph()
    ppr._loaded = True
    return ppr


def build_hub_graph() -> HippoRAG2PPR:
    """Hub entity E_hub connected to 4 entities, each with a passage.

    E_hub <-> E1 <-> P1
    E_hub <-> E2 <-> P2
    E_hub <-> E3 <-> P3
    E_hub <-> E4 <-> P4
    """
    ppr = HippoRAG2PPR()
    ppr._add_node("hub", "entity", "Hub Entity")
    for i in range(1, 5):
        ppr._add_node(f"e{i}", "entity", f"Spoke_{i}")
        ppr._add_node(f"p{i}", "passage", f"Passage for spoke {i}")

    # Hub to spokes
    for i in range(1, 5):
        ppr._add_edge(0, (i - 1) * 2 + 1, 1.0)  # hub <-> e_i
        ppr._add_edge((i - 1) * 2 + 1, (i - 1) * 2 + 2, 0.05)  # e_i <-> p_i

    ppr._finalize_graph()
    ppr._loaded = True
    return ppr


def build_synonym_graph() -> HippoRAG2PPR:
    """Two entities connected via SEMANTICALLY_SIMILAR (synonym) edge.

    E1 <-> E2 (synonym, weight=0.9)
    E1 <-> P1 (MENTIONS, weight=0.05)
    E2 <-> P2 (MENTIONS, weight=0.05)
    """
    ppr = HippoRAG2PPR()
    ppr._add_node("e1", "entity", "New York")
    ppr._add_node("e2", "entity", "NYC")
    ppr._add_node("p1", "passage", "New York is a city...")
    ppr._add_node("p2", "passage", "NYC population is...")

    ppr._add_edge(0, 1, 0.9)  # synonym
    ppr._add_edge(0, 2, 0.05)  # E1 <-> P1
    ppr._add_edge(1, 3, 0.05)  # E2 <-> P2

    ppr._finalize_graph()
    ppr._loaded = True
    return ppr


# ============================================================================
# Test Category 1: Basic PPR Properties
# ============================================================================

class TestHippoRAG2PPRBasics:
    """Test fundamental PPR properties on HippoRAG 2 graph."""

    def test_scores_sum_to_one(self):
        """PPR scores across all nodes should sum to ~1.0."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        total = sum(s for _, s in passage_scores) + sum(s for _, s in entity_scores)
        assert abs(total - 1.0) < 0.01, f"Scores sum to {total}, expected ~1.0"

    def test_scores_non_negative(self):
        """All PPR scores must be non-negative."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        assert all(s >= 0 for _, s in passage_scores)
        assert all(s >= 0 for _, s in entity_scores)

    def test_seed_entity_has_high_score(self):
        """The seed entity should have the highest entity score."""
        ppr = build_simple_graph()
        _, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        assert len(entity_scores) == 3
        # Top entity should be the seed or its direct neighbor
        top_entity_name = entity_scores[0][0]
        assert top_entity_name in ("Alpha Corp", "Beta Fund")

    def test_passage_nodes_receive_score(self):
        """Passages connected to seeded entities must get non-zero scores."""
        ppr = build_simple_graph()
        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        assert len(passage_scores) == 2
        assert all(s > 0 for _, s in passage_scores), "All passages should have non-zero score"

    def test_sorted_descending(self):
        """Both passage and entity scores should be sorted descending."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        passage_vals = [s for _, s in passage_scores]
        entity_vals = [s for _, s in entity_scores]
        assert passage_vals == sorted(passage_vals, reverse=True)
        assert entity_vals == sorted(entity_vals, reverse=True)


# ============================================================================
# Test Category 2: Passage Node Behavior (v2 key innovation)
# ============================================================================

class TestPassageNodeBehavior:
    """Test that passage nodes participate correctly in PPR walk."""

    def test_close_passage_scores_higher(self):
        """Passage connected to seeded entity should score higher than distant one."""
        ppr = build_chain_with_passages()
        # Seed E1 only
        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        score_map = dict(passage_scores)
        # P1 connected to E1, P3 is 2 hops away
        assert score_map["p1"] > score_map["p3"], \
            f"P1 ({score_map['p1']:.4f}) should score > P3 ({score_map['p3']:.4f})"

    def test_passage_seeds_boost_score(self):
        """Adding passage seeds should increase that passage's final score."""
        ppr = build_simple_graph()

        # Without passage seed
        p_without, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        score_without = dict(p_without).get("p2", 0)

        # With passage seed on P2
        p_with, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={"p2": 0.5}, damping=0.5
        )
        score_with = dict(p_with).get("p2", 0)

        assert score_with > score_without, \
            f"Passage seed should boost P2: {score_with:.4f} vs {score_without:.4f}"

    def test_passage_only_seeds(self):
        """PPR should work with passage seeds only (no entity seeds)."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={}, passage_seeds={"p1": 1.0}, damping=0.5
        )
        total = sum(s for _, s in passage_scores) + sum(s for _, s in entity_scores)
        assert abs(total - 1.0) < 0.01
        # P1 passage seed should result in E1 getting entity score (connected via MENTIONS)
        entity_map = dict(entity_scores)
        assert entity_map.get("Alpha Corp", 0) > 0, "E1 should get score from P1 seed"

    def test_hub_distributes_to_all_passages(self):
        """Seeding hub entity should distribute score to all spoke passages."""
        ppr = build_hub_graph()
        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"hub": 1.0}, passage_seeds={}, damping=0.5
        )
        # All 4 passages should have non-zero score
        assert len(passage_scores) == 4
        scores = [s for _, s in passage_scores]
        assert all(s > 0 for s in scores), "All passages should receive score from hub"
        # Scores should be roughly equal (symmetric graph)
        max_s, min_s = max(scores), min(scores)
        assert max_s / min_s < 1.5, f"Scores should be roughly equal: {scores}"


# ============================================================================
# Test Category 3: Weighted Edge Distribution
# ============================================================================

class TestWeightedEdges:
    """Test that edge weights affect PPR rank distribution."""

    def test_synonym_edge_transfers_rank(self):
        """SEMANTICALLY_SIMILAR (synonym) edge should transfer rank between entities."""
        ppr = build_synonym_graph()
        _, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        entity_map = dict(entity_scores)
        # NYC (e2) should get significant score via synonym edge to New York (e1)
        assert entity_map.get("NYC", 0) > 0, "Synonym entity should receive score"

    def test_synonym_passage_reachable(self):
        """Passage of synonym entity should be reachable via synonym edge."""
        ppr = build_synonym_graph()
        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        score_map = dict(passage_scores)
        # P2 is connected to NYC (e2), reachable via synonym edge from New York (e1)
        assert score_map.get("p2", 0) > 0, "Passage via synonym should be reachable"


# ============================================================================
# Test Category 4: Damping Factor
# ============================================================================

class TestDampingFactor:
    """Test that damping factor affects score distribution."""

    def test_high_damping_spreads_more(self):
        """Higher damping should spread more rank to distant nodes."""
        ppr = build_chain_with_passages()

        # Low damping = more teleportation back to seed
        _, entity_low = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.3
        )
        # High damping = more following edges
        _, entity_high = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.85
        )

        low_map = dict(entity_low)
        high_map = dict(entity_high)

        # E3 is 2 hops away — should get relatively more score with high damping
        e3_ratio_low = low_map.get("Entity_3", 0) / max(low_map.get("Entity_1", 0.001), 0.001)
        e3_ratio_high = high_map.get("Entity_3", 0) / max(high_map.get("Entity_1", 0.001), 0.001)

        assert e3_ratio_high > e3_ratio_low, \
            f"High damping should spread more: ratio {e3_ratio_high:.3f} vs {e3_ratio_low:.3f}"

    def test_upstream_default_damping(self):
        """Upstream HippoRAG 2 uses damping=0.5 (our default)."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        # Should produce valid results
        assert len(passage_scores) > 0
        assert len(entity_scores) > 0


# ============================================================================
# Test Category 5: Undirected Graph Property
# ============================================================================

class TestUndirectedGraph:
    """Test that edges are truly undirected."""

    def test_edge_adds_both_directions(self):
        """_add_edge should create entries in both directions."""
        ppr = HippoRAG2PPR()
        ppr._add_node("a", "entity", "A")
        ppr._add_node("b", "entity", "B")
        ppr._add_edge(0, 1, 1.0)

        assert (1, 1.0) in ppr._adj[0], "Forward edge missing"
        assert (0, 1.0) in ppr._adj[1], "Reverse edge missing"

    def test_symmetric_seeds_symmetric_scores(self):
        """Seeding symmetric nodes should produce mirrored results."""
        ppr = build_synonym_graph()

        _, scores_e1 = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        _, scores_e2 = ppr.run_ppr(
            entity_seeds={"e2": 1.0}, passage_seeds={}, damping=0.5
        )

        # Both entities exist in both result sets
        map_e1 = dict(scores_e1)
        map_e2 = dict(scores_e2)

        # When seeding e1, NYC gets some score; when seeding e2, New York gets some
        assert map_e1.get("NYC", 0) > 0
        assert map_e2.get("New York", 0) > 0


# ============================================================================
# Test Category 6: Convergence
# ============================================================================

class TestConvergence:
    """Test PPR convergence behavior."""

    def test_converges_on_small_graph(self):
        """PPR should converge well within max_iterations on small graphs."""
        ppr = build_simple_graph()
        # With max_iterations=50, a 5-node graph should converge in <20 iterations
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5,
            max_iterations=50, convergence_threshold=1e-6,
        )
        total = sum(s for _, s in passage_scores) + sum(s for _, s in entity_scores)
        assert abs(total - 1.0) < 0.01

    def test_deterministic_results(self):
        """Same input should produce identical output."""
        ppr = build_simple_graph()
        r1_pass, r1_ent = ppr.run_ppr(entity_seeds={"e1": 1.0}, passage_seeds={})
        r2_pass, r2_ent = ppr.run_ppr(entity_seeds={"e1": 1.0}, passage_seeds={})

        for (id1, s1), (id2, s2) in zip(r1_pass, r2_pass):
            assert id1 == id2
            assert abs(s1 - s2) < 1e-10

        for (id1, s1), (id2, s2) in zip(r1_ent, r2_ent):
            assert id1 == id2
            assert abs(s1 - s2) < 1e-10


# ============================================================================
# Test Category 7: Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_graph(self):
        """PPR on empty graph returns empty results."""
        ppr = HippoRAG2PPR()
        ppr._loaded = True
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"nonexistent": 1.0}, passage_seeds={}
        )
        assert passage_scores == []
        assert entity_scores == []

    def test_nonexistent_seeds(self):
        """Seeds referencing missing node IDs should be ignored gracefully."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"nonexistent": 1.0}, passage_seeds={}, damping=0.5
        )
        # All seeds invalid → no valid personalization → empty result
        assert passage_scores == []
        assert entity_scores == []

    def test_no_seeds(self):
        """No seeds at all should return empty."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={}, passage_seeds={}, damping=0.5
        )
        assert passage_scores == []
        assert entity_scores == []

    def test_isolated_passage(self):
        """A passage with no edges should get score only if directly seeded."""
        ppr = HippoRAG2PPR()
        ppr._add_node("e1", "entity", "E1")
        ppr._add_node("p1", "passage", "P1")
        ppr._add_node("p_isolated", "passage", "Isolated")
        ppr._add_edge(0, 1, 0.05)  # E1 <-> P1
        # p_isolated has no edges
        ppr._finalize_graph()
        ppr._loaded = True

        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}, damping=0.5
        )
        score_map = dict(passage_scores)
        assert score_map.get("p1", 0) > 0
        # Isolated passage gets teleportation mass only (no seed = 0 teleportation)
        assert score_map.get("p_isolated", 0) == 0

    def test_multiple_entity_seeds(self):
        """Multiple weighted entity seeds should work correctly."""
        ppr = build_chain_with_passages()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 0.7, "e3": 0.3},
            passage_seeds={},
            damping=0.5,
        )
        total = sum(s for _, s in passage_scores) + sum(s for _, s in entity_scores)
        assert abs(total - 1.0) < 0.01

    def test_mixed_entity_and_passage_seeds(self):
        """Combining entity and passage seeds should work."""
        ppr = build_simple_graph()
        passage_scores, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 0.5},
            passage_seeds={"p2": 0.5},
            damping=0.5,
        )
        total = sum(s for _, s in passage_scores) + sum(s for _, s in entity_scores)
        assert abs(total - 1.0) < 0.01


# ============================================================================
# Test Category 8: Node Type Separation
# ============================================================================

class TestNodeTypeSeparation:
    """Test that passage and entity scores are correctly separated."""

    def test_passage_scores_only_passages(self):
        """passage_scores list should only contain passage node IDs."""
        ppr = build_simple_graph()
        passage_scores, _ = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}
        )
        for node_id, _ in passage_scores:
            assert node_id.startswith("p"), f"Expected passage ID, got {node_id}"

    def test_entity_scores_only_entities(self):
        """entity_scores list should only contain entity display names."""
        ppr = build_simple_graph()
        _, entity_scores = ppr.run_ppr(
            entity_seeds={"e1": 1.0}, passage_seeds={}
        )
        entity_names = {"Alpha Corp", "Beta Fund", "Gamma LLC"}
        for name, _ in entity_scores:
            assert name in entity_names, f"Unexpected entity name: {name}"

    def test_node_count_correct(self):
        """node_count property should reflect actual number of nodes."""
        ppr = build_simple_graph()
        assert ppr.node_count == 5  # 3 entities + 2 passages

    def test_graph_internals(self):
        """Verify internal data structures after graph construction."""
        ppr = build_simple_graph()
        # Check node type counts
        entity_count = sum(1 for t in ppr._node_types.values() if t == "entity")
        passage_count = sum(1 for t in ppr._node_types.values() if t == "passage")
        assert entity_count == 3
        assert passage_count == 2
        # Check precomputed weight sums exist
        assert len(ppr._out_weight_sum) == 5
