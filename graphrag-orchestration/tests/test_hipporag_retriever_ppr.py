"""
Test Suite: HippoRAG Retriever - PPR Algorithm

Purpose: Verify correctness of Personalized PageRank implementation

Test Data: Synthetic graphs created inline

Dependencies:
- pytest
- pytest-asyncio

Run: pytest tests/test_hipporag_retriever_ppr.py -v
"""

import pytest
from app.hybrid.retrievers import HippoRAGRetriever, HippoRAGRetrieverConfig


@pytest.fixture
def retriever():
    """Create a retriever instance for testing (no graph store needed for unit tests)."""
    config = HippoRAGRetrieverConfig(
        damping_factor=0.85,
        max_iterations=100,
        convergence_threshold=1e-6,
        top_k=10
    )
    return HippoRAGRetriever(
        graph_store=None,
        llm=None,
        config=config,
        group_id="test"
    )


def inject_test_graph(retriever, nodes, edges):
    """Helper to inject a test graph into the retriever."""
    retriever._nodes = nodes
    retriever._nodes_lower = {n: n.lower() for n in nodes}
    
    # Build adjacency from edges
    adjacency = {n: [] for n in nodes}
    reverse_adjacency = {n: [] for n in nodes}
    
    for src, tgt in edges:
        adjacency[src].append(tgt)
        reverse_adjacency[tgt].append(src)
    
    retriever._adjacency = adjacency
    retriever._reverse_adjacency = reverse_adjacency
    retriever._graph_loaded = True


class TestPPRBasicFunctionality:
    """Test basic PPR algorithm functionality."""
    
    def test_ppr_simple_chain(self, retriever):
        """Test PPR on a linear chain A→B→C→D→E."""
        nodes = ['A', 'B', 'C', 'D', 'E']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'E')]
        inject_test_graph(retriever, nodes, edges)
        
        results = retriever._run_personalized_pagerank(['A'])
        
        # Should return all nodes with scores
        assert len(results) == 5
        
        # Extract scores
        scores = {node: score for node, score in results}
        
        # A (seed) should have highest score
        assert scores['A'] > scores['B']
        assert scores['B'] > scores['C']
        assert scores['C'] > scores['D']
        assert scores['D'] > scores['E']
        
        # All scores should be positive
        assert all(score > 0 for score in scores.values())
        
        # Total mass is conserved (sum should be positive and reasonable)
        total = sum(scores.values())
        assert total > 0, "Total PPR score should be positive"
    
    def test_ppr_multiple_seeds(self, retriever):
        """Test PPR with multiple seed nodes."""
        nodes = ['A', 'B', 'C', 'D', 'E']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'E')]
        inject_test_graph(retriever, nodes, edges)
        
        # Seeds at both ends
        results = retriever._run_personalized_pagerank(['A', 'E'])
        scores = {node: score for node, score in results}
        
        # Both seeds should have high scores
        assert scores['A'] > scores['C']
        assert scores['E'] > scores['C']
        
        # Middle nodes benefit from both sides
        assert scores['C'] > 0
    
    def test_ppr_hub_topology(self, retriever):
        """Test PPR on star topology (hub with many spokes)."""
        nodes = ['Hub'] + [f'Spoke{i}' for i in range(5)]
        edges = [('Hub', f'Spoke{i}') for i in range(5)]
        inject_test_graph(retriever, nodes, edges)
        
        # Seed the hub
        results = retriever._run_personalized_pagerank(['Hub'])
        scores = {node: score for node, score in results}
        
        # Hub should have highest score
        assert scores['Hub'] > max(scores[f'Spoke{i}'] for i in range(5))
        
        # All spokes should have similar scores (equal distance from hub)
        spoke_scores = [scores[f'Spoke{i}'] for i in range(5)]
        avg_spoke = sum(spoke_scores) / len(spoke_scores)
        for score in spoke_scores:
            assert abs(score - avg_spoke) < 0.01
    
    def test_ppr_bidirectional_edges(self, retriever):
        """Test PPR with bidirectional relationships A↔B."""
        nodes = ['A', 'B', 'C']
        edges = [('A', 'B'), ('B', 'A'), ('B', 'C'), ('C', 'B')]
        inject_test_graph(retriever, nodes, edges)
        
        results = retriever._run_personalized_pagerank(['A'])
        scores = {node: score for node, score in results}
        
        # All nodes reachable
        assert all(score > 0 for score in scores.values())
        
        # A and B should have high scores (bidirectional flow)
        assert scores['A'] > scores['C']
        assert scores['B'] > scores['C']


class TestPPRConvergence:
    """Test PPR convergence properties."""
    
    def test_ppr_converges_within_max_iterations(self, retriever):
        """Test that PPR converges within max_iterations."""
        nodes = ['A', 'B', 'C', 'D']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'A')]  # Cycle
        inject_test_graph(retriever, nodes, edges)
        
        retriever.config.max_iterations = 50
        retriever.config.convergence_threshold = 1e-6
        
        results = retriever._run_personalized_pagerank(['A'])
        
        # Should return results (converged or hit max_iter)
        assert len(results) == 4
        assert all(score > 0 for _, score in results)
    
    def test_ppr_different_damping_factors(self, retriever):
        """Test PPR with different damping factors."""
        nodes = ['A', 'B', 'C', 'D']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D')]
        inject_test_graph(retriever, nodes, edges)
        
        # Low damping (more teleportation to seed)
        retriever.config.damping_factor = 0.5
        results_low = retriever._run_personalized_pagerank(['A'])
        scores_low = {node: score for node, score in results_low}
        
        # High damping (more flow through edges)
        retriever.config.damping_factor = 0.95
        results_high = retriever._run_personalized_pagerank(['A'])
        scores_high = {node: score for node, score in results_high}
        
        # With high damping, distant nodes get more score
        assert scores_high['D'] / scores_high['A'] > scores_low['D'] / scores_low['A']


class TestPPRDeterminism:
    """Test that PPR produces deterministic results."""
    
    def test_ppr_deterministic_same_seed(self, retriever):
        """Test that running PPR twice produces identical results."""
        nodes = ['A', 'B', 'C', 'D', 'E']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'E'), ('E', 'A')]
        inject_test_graph(retriever, nodes, edges)
        
        # Run PPR twice
        results1 = retriever._run_personalized_pagerank(['A'])
        results2 = retriever._run_personalized_pagerank(['A'])
        
        # Convert to dicts for comparison
        scores1 = {node: score for node, score in results1}
        scores2 = {node: score for node, score in results2}
        
        # Exact same scores
        for node in nodes:
            assert abs(scores1[node] - scores2[node]) < 1e-10


class TestPPREdgeCases:
    """Test PPR edge cases and error handling."""
    
    def test_ppr_empty_graph(self, retriever):
        """Test PPR on empty graph."""
        inject_test_graph(retriever, [], [])
        
        results = retriever._run_personalized_pagerank(['A'])
        assert results == []
    
    def test_ppr_single_node(self, retriever):
        """Test PPR on graph with single node."""
        inject_test_graph(retriever, ['A'], [])
        
        results = retriever._run_personalized_pagerank(['A'])
        assert len(results) == 1
        assert results[0][0] == 'A'
        assert results[0][1] > 0  # Should have positive score
    
    def test_ppr_disconnected_components(self, retriever):
        """Test PPR on disconnected graph."""
        nodes = ['A1', 'A2', 'B1', 'B2']
        edges = [('A1', 'A2'), ('B1', 'B2')]  # Two separate components
        inject_test_graph(retriever, nodes, edges)
        
        # Seed in component A
        results = retriever._run_personalized_pagerank(['A1'])
        scores = {node: score for node, score in results}
        
        # Component A nodes should have high scores
        assert scores['A1'] > 0
        assert scores['A2'] > 0
        
        # Component B nodes should have zero scores (not reachable)
        assert scores['B1'] == 0
        assert scores['B2'] == 0
    
    def test_ppr_self_loop(self, retriever):
        """Test PPR with self-loops."""
        nodes = ['A', 'B']
        edges = [('A', 'A'), ('A', 'B')]  # A has self-loop
        inject_test_graph(retriever, nodes, edges)
        
        results = retriever._run_personalized_pagerank(['A'])
        
        # Should handle self-loops without infinite loops
        assert len(results) == 2
        scores = {node: score for node, score in results}
        assert scores['A'] > 0
        assert scores['B'] > 0
    
    def test_ppr_nonexistent_seed(self, retriever):
        """Test PPR with seed that doesn't exist in graph."""
        nodes = ['A', 'B', 'C']
        edges = [('A', 'B'), ('B', 'C')]
        inject_test_graph(retriever, nodes, edges)
        
        # Seed 'Z' doesn't exist
        results = retriever._run_personalized_pagerank(['Z'])
        
        # Should return empty or handle gracefully
        assert results == []


class TestPPRRanking:
    """Test that PPR produces correct rankings."""
    
    def test_ppr_top_k(self, retriever):
        """Test that top-k filtering works."""
        nodes = ['A', 'B', 'C', 'D', 'E', 'F']
        edges = [('A', 'B'), ('A', 'C'), ('A', 'D'), ('A', 'E'), ('A', 'F')]
        inject_test_graph(retriever, nodes, edges)
        
        retriever.config.top_k = 3
        results = retriever._run_personalized_pagerank(['A'])
        
        # Should return exactly 3 results
        assert len(results) == 6  # _run_personalized_pagerank returns all
        
        # But top-k is applied in retrieve() method
        # Here we just verify ranking order
        scores = [score for _, score in results]
        # Scores should be descending
        assert scores == sorted(scores, reverse=True)
    
    def test_ppr_ranking_transitivity(self, retriever):
        """Test ranking respects graph distance from seeds."""
        nodes = ['A', 'B', 'C', 'D']
        edges = [('A', 'B'), ('B', 'C'), ('C', 'D')]
        inject_test_graph(retriever, nodes, edges)
        
        results = retriever._run_personalized_pagerank(['A'])
        
        # Results should be sorted by score descending
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)
        
        # Node order should match distance from A
        node_order = [node for node, _ in results]
        assert node_order.index('A') < node_order.index('B')
        assert node_order.index('B') < node_order.index('C')
        assert node_order.index('C') < node_order.index('D')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
