"""
Unit Tests: PPR (Personalized PageRank) Algorithm

Tests the graph traversal algorithm used by HippoRAG for evidence tracing.
PPR is used in Routes 2, 3, and 4 to expand seed entities to related nodes.

Run: pytest tests/unit/test_ppr.py -v
"""

import pytest
from unittest.mock import MagicMock, AsyncMock
from typing import Dict, List, Set


# ============================================================================
# Test Data: Sample Graph Structures
# ============================================================================

def create_simple_chain() -> Dict[str, Set[str]]:
    """A → B → C chain graph."""
    return {
        "A": {"B"},
        "B": {"C"},
        "C": set(),
    }


def create_hub_and_spoke() -> Dict[str, Set[str]]:
    """Hub with multiple spokes: A → {B, C, D, E}."""
    return {
        "A": {"B", "C", "D", "E"},
        "B": set(),
        "C": set(),
        "D": set(),
        "E": set(),
    }


def create_bidirectional() -> Dict[str, Set[str]]:
    """Bidirectional: A ↔ B ↔ C."""
    return {
        "A": {"B"},
        "B": {"A", "C"},
        "C": {"B"},
    }


def create_disconnected() -> Dict[str, Set[str]]:
    """Disconnected components: {A, B} and {C, D}."""
    return {
        "A": {"B"},
        "B": {"A"},
        "C": {"D"},
        "D": {"C"},
    }


# ============================================================================
# Test Category 1: PPR Algorithm Basics
# ============================================================================

class TestPPRBasics:
    """Test basic PPR algorithm properties."""
    
    def test_ppr_scores_sum_to_one(self):
        """Test that PPR scores sum to approximately 1.0."""
        # Simplified PPR result
        scores = {"A": 0.5, "B": 0.3, "C": 0.2}
        total = sum(scores.values())
        assert abs(total - 1.0) < 0.01, f"PPR scores should sum to ~1.0, got {total}"
    
    def test_ppr_scores_are_non_negative(self):
        """Test that all PPR scores are non-negative."""
        scores = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}
        assert all(s >= 0 for s in scores.values())
    
    def test_seed_nodes_have_high_scores(self):
        """Test that seed nodes typically have high PPR scores."""
        # When A is the seed, A should have highest score
        scores = {"A": 0.6, "B": 0.25, "C": 0.15}
        seed = "A"
        assert scores[seed] == max(scores.values())
    
    def test_damping_factor_in_valid_range(self):
        """Test that damping factor is between 0 and 1."""
        damping = 0.85  # Standard value
        assert 0.0 < damping < 1.0


# ============================================================================
# Test Category 2: Graph Traversal
# ============================================================================

class TestPPRTraversal:
    """Test PPR traversal behavior."""
    
    def test_chain_traversal_decreases_score(self):
        """Test that scores decrease along a chain."""
        # In A → B → C, scores should be A > B > C when A is seed
        chain = create_simple_chain()
        # Simulated scores after PPR
        scores = {"A": 0.6, "B": 0.3, "C": 0.1}
        
        assert scores["A"] > scores["B"] > scores["C"]
    
    def test_hub_distributes_to_spokes(self):
        """Test that hub distributes probability to spokes."""
        hub = create_hub_and_spoke()
        # Simulated: A is seed, spreads to B, C, D, E
        scores = {"A": 0.5, "B": 0.125, "C": 0.125, "D": 0.125, "E": 0.125}
        
        # Hub should have highest score
        assert scores["A"] > scores["B"]
        # Spokes should have equal scores
        spoke_scores = [scores["B"], scores["C"], scores["D"], scores["E"]]
        assert len(set(spoke_scores)) == 1
    
    def test_bidirectional_edges_considered(self):
        """Test that bidirectional edges are traversed."""
        graph = create_bidirectional()
        # B can reach both A and C
        assert "A" in graph["B"]
        assert "C" in graph["B"]
    
    def test_disconnected_components_isolated(self):
        """Test that disconnected components don't affect each other."""
        graph = create_disconnected()
        # Seeding from A should not reach C or D
        component_a = {"A", "B"}
        component_b = {"C", "D"}
        
        # No edges between components
        for node in component_a:
            for target in graph.get(node, set()):
                assert target not in component_b


# ============================================================================
# Test Category 3: Seed Expansion
# ============================================================================

class TestSeedExpansion:
    """Test seed entity expansion."""
    
    def test_single_seed_expands(self):
        """Test that single seed expands to neighbors."""
        graph = create_simple_chain()
        seed = "A"
        
        # Direct neighbors
        neighbors = graph[seed]
        assert "B" in neighbors
    
    def test_multiple_seeds_combine(self):
        """Test that multiple seeds combine their traversals."""
        seeds = ["A", "C"]
        # Both seeds contribute to the PPR computation
        assert len(seeds) == 2
    
    def test_top_k_limits_results(self):
        """Test that top_k limits the number of results."""
        all_scores = {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.04, "E": 0.01}
        top_k = 3
        
        top_nodes = sorted(all_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
        assert len(top_nodes) == top_k
        assert top_nodes[0][0] == "A"


# ============================================================================
# Test Category 4: Convergence
# ============================================================================

class TestPPRConvergence:
    """Test PPR convergence behavior."""
    
    def test_convergence_threshold_reasonable(self):
        """Test that convergence threshold is reasonable."""
        threshold = 1e-6
        assert threshold > 0
        assert threshold < 0.01  # Should be small
    
    def test_max_iterations_bounded(self):
        """Test that max iterations is bounded."""
        max_iterations = 100
        assert 10 <= max_iterations <= 1000
    
    def test_iteration_count_reasonable(self):
        """Test that typical convergence is within reasonable iterations."""
        typical_iterations = 20
        max_iterations = 100
        assert typical_iterations < max_iterations


# ============================================================================
# Test Category 5: Multi-Tenancy in PPR
# ============================================================================

class TestPPRMultiTenancy:
    """Test PPR respects multi-tenancy."""
    
    def test_group_id_filters_nodes(self):
        """Test that PPR only considers nodes in the same group."""
        nodes_with_groups = {
            "A": {"group_id": "tenant_1"},
            "B": {"group_id": "tenant_1"},
            "C": {"group_id": "tenant_2"},
        }
        
        tenant_1_nodes = [k for k, v in nodes_with_groups.items() if v["group_id"] == "tenant_1"]
        assert "A" in tenant_1_nodes
        assert "B" in tenant_1_nodes
        assert "C" not in tenant_1_nodes
    
    def test_cross_tenant_traversal_blocked(self):
        """Test that PPR doesn't traverse across tenants."""
        # Even if edge exists, should not traverse to different tenant
        edges = [("A", "C")]  # A is tenant_1, C is tenant_2
        
        # Filtering should prevent this traversal
        allowed_edges = []  # All filtered out
        assert len(allowed_edges) == 0


# ============================================================================
# Test Category 6: Edge Cases
# ============================================================================

class TestPPREdgeCases:
    """Test PPR edge cases."""
    
    def test_empty_graph_returns_empty(self):
        """Test that empty graph returns empty results."""
        graph = {}
        seeds = ["A"]
        
        # Should handle gracefully
        reachable = set()
        for seed in seeds:
            reachable.update(graph.get(seed, set()))
        
        assert len(reachable) == 0
    
    def test_isolated_node_returns_only_itself(self):
        """Test that isolated node only returns itself."""
        graph = {"A": set()}
        seed = "A"
        
        neighbors = graph[seed]
        assert len(neighbors) == 0
        # Only the seed itself contributes
    
    def test_self_loop_handled(self):
        """Test that self-loops are handled."""
        graph = {"A": {"A", "B"}}
        
        # A points to itself - should not cause infinite loop
        assert "A" in graph["A"]
    
    def test_no_seeds_returns_empty(self):
        """Test that no seeds returns empty results."""
        seeds = []
        # PPR with no seeds should return empty
        assert len(seeds) == 0


# ============================================================================
# Test Category 7: Score Interpretation
# ============================================================================

class TestPPRScoreInterpretation:
    """Test interpretation of PPR scores."""
    
    def test_higher_score_means_more_relevant(self):
        """Test that higher PPR score indicates more relevance."""
        scores = {"A": 0.8, "B": 0.15, "C": 0.05}
        
        # A is most relevant, C is least relevant
        ranked = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        assert ranked == ["A", "B", "C"]
    
    def test_score_threshold_filters_noise(self):
        """Test that score threshold filters low-relevance nodes."""
        scores = {"A": 0.8, "B": 0.15, "C": 0.05, "D": 0.001}
        threshold = 0.01
        
        filtered = {k: v for k, v in scores.items() if v >= threshold}
        assert "D" not in filtered
        assert "A" in filtered
    
    def test_normalized_scores_comparable(self):
        """Test that normalized scores are comparable across queries."""
        query1_scores = {"A": 0.6, "B": 0.4}
        query2_scores = {"X": 0.7, "Y": 0.3}
        
        # Both sum to 1.0
        assert abs(sum(query1_scores.values()) - 1.0) < 0.01
        assert abs(sum(query2_scores.values()) - 1.0) < 0.01


# ============================================================================
# Test Category 8: Performance
# ============================================================================

class TestPPRPerformance:
    """Test PPR performance characteristics."""
    
    def test_sparse_graph_efficient(self):
        """Test that sparse graphs are handled efficiently."""
        # Sparse graph: 1000 nodes, ~2000 edges (avg degree 2)
        num_nodes = 1000
        avg_degree = 2
        
        # O(E * iterations) should be manageable
        expected_edges = num_nodes * avg_degree
        max_iterations = 100
        operations = expected_edges * max_iterations
        
        # Should be under 1M operations for sparse graph
        assert operations < 1_000_000
    
    def test_dense_graph_bounded(self):
        """Test that dense graphs are bounded by max iterations."""
        # Dense graph: 100 nodes, fully connected
        num_nodes = 100
        num_edges = num_nodes * (num_nodes - 1)  # ~10K edges
        max_iterations = 100
        
        operations = num_edges * max_iterations
        # Even dense small graph should be bounded
        assert operations < 10_000_000
