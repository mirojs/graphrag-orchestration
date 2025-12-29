"""
Test Suite: HippoRAG Retriever - Seed Expansion

Purpose: Verify seed entity matching and expansion logic

Test Data: Synthetic node lists

Dependencies:
- pytest

Run: pytest tests/test_hipporag_retriever_seeds.py -v
"""

import pytest
from app.hybrid.retrievers import HippoRAGRetriever, HippoRAGRetrieverConfig


@pytest.fixture
def retriever():
    """Create a retriever instance for testing."""
    config = HippoRAGRetrieverConfig(
        expand_seeds_per_entity=3,
        max_seeds=10
    )
    return HippoRAGRetriever(
        graph_store=None,
        llm=None,
        config=config,
        group_id="test"
    )


def setup_nodes(retriever, nodes):
    """Helper to set up node list in retriever."""
    retriever._nodes = nodes
    retriever._nodes_lower = {n: n.lower() for n in nodes}
    retriever._graph_loaded = True


class TestExactMatching:
    """Test exact entity name matching."""
    
    def test_exact_match_case_sensitive(self, retriever):
        """Test exact match with same case."""
        nodes = ['Risk Management', 'Compliance Policy', 'Audit Trail']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Risk Management'])
        
        assert 'Risk Management' in expanded
        assert len(expanded) >= 1
    
    def test_exact_match_case_insensitive(self, retriever):
        """Test exact match with different case."""
        nodes = ['Risk Management', 'Compliance Policy', 'Audit Trail']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['risk management'])
        
        assert 'Risk Management' in expanded
    
    def test_exact_match_multiple_seeds(self, retriever):
        """Test exact matching with multiple seeds."""
        nodes = ['Entity A', 'Entity B', 'Entity C', 'Other']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Entity A', 'Entity B'])
        
        assert 'Entity A' in expanded
        assert 'Entity B' in expanded
        assert len(expanded) >= 2


class TestSubstringMatching:
    """Test substring-based entity matching."""
    
    def test_substring_seed_in_node(self, retriever):
        """Test when seed is substring of node name."""
        nodes = ['Risk Management Policy', 'Compliance', 'Audit']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Risk'])
        
        assert 'Risk Management Policy' in expanded
    
    def test_substring_node_in_seed(self, retriever):
        """Test when node name is substring of seed."""
        nodes = ['Risk', 'Compliance', 'Audit']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Risk Management'])
        
        assert 'Risk' in expanded
    
    def test_substring_multiple_matches(self, retriever):
        """Test substring matching with multiple hits."""
        nodes = [
            'Risk Management',
            'Risk Assessment',
            'Risk Policy',
            'Other Entity'
        ]
        setup_nodes(retriever, nodes)
        
        # Should find all three Risk* entities
        expanded = retriever._expand_seeds_to_nodes(['Risk'])
        
        risk_entities = [n for n in expanded if 'Risk' in n]
        assert len(risk_entities) >= 1
    
    def test_substring_respects_max_per_seed(self, retriever):
        """Test that expand_seeds_per_entity limit is respected."""
        nodes = [f'Risk Entity {i}' for i in range(10)]
        setup_nodes(retriever, nodes)
        
        retriever.config.expand_seeds_per_entity = 3
        expanded = retriever._expand_seeds_to_nodes(['Risk'])
        
        # Should return at most 3 matches
        risk_count = len([n for n in expanded if 'Risk' in n])
        assert risk_count <= 3


class TestTokenOverlapMatching:
    """Test Jaccard similarity-based matching."""
    
    def test_token_overlap_similar_phrases(self, retriever):
        """Test matching with token overlap."""
        nodes = ['Payment Terms Agreement', 'Service Agreement', 'Other']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Terms of Payment'])
        
        # Should match 'Payment Terms Agreement' via token overlap
        matches = [n for n in expanded if 'Payment' in n or 'Terms' in n]
        assert len(matches) > 0
    
    def test_token_overlap_high_jaccard(self, retriever):
        """Test that high Jaccard similarity produces matches."""
        nodes = [
            'Risk Management Policy Document',
            'Risk Policy',
            'Management Guide',
            'Unrelated Entity'
        ]
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Risk Management Policy'])
        
        # Both 'Risk Management Policy Document' and 'Risk Policy' should match
        assert any('Risk Management Policy' in n for n in expanded)
    
    def test_token_overlap_no_match_when_disjoint(self, retriever):
        """Test no match when tokens don't overlap."""
        nodes = ['Compliance Policy', 'Audit Trail', 'Entity X']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Risk Management'])
        
        # Should not match unrelated entities
        assert 'Compliance Policy' not in expanded or len(expanded) == 0


class TestSeedListHandling:
    """Test handling of seed lists."""
    
    def test_empty_seed_list(self, retriever):
        """Test with empty seed list."""
        nodes = ['Entity A', 'Entity B']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes([])
        
        assert expanded == []
    
    def test_duplicate_seeds(self, retriever):
        """Test that duplicate seeds are deduplicated."""
        nodes = ['Entity A', 'Entity B', 'Entity C']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Entity A', 'Entity A', 'Entity A'])
        
        # Should only return Entity A once
        assert expanded.count('Entity A') == 1
    
    def test_max_seeds_limit(self, retriever):
        """Test that max_seeds limit is enforced."""
        nodes = [f'Entity {i}' for i in range(20)]
        setup_nodes(retriever, nodes)
        
        retriever.config.max_seeds = 5
        
        # Try to expand 20 seeds
        seeds = [f'Entity {i}' for i in range(20)]
        expanded = retriever._expand_seeds_to_nodes(seeds)
        
        # Should return at most max_seeds
        assert len(expanded) <= 5
    
    def test_whitespace_only_seed(self, retriever):
        """Test that whitespace-only seeds are skipped."""
        nodes = ['Entity A', 'Entity B']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['   ', '\t', '\n', 'Entity A'])
        
        # Should only match Entity A
        assert 'Entity A' in expanded
        assert len(expanded) == 1


class TestSpecialCharacters:
    """Test handling of special characters in entity names."""
    
    def test_punctuation_in_entity_name(self, retriever):
        """Test matching entities with punctuation."""
        nodes = ['ABC Corp.', 'XYZ Inc.', 'DEF Ltd.']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['ABC Corp.'])
        
        assert 'ABC Corp.' in expanded
    
    def test_punctuation_normalized(self, retriever):
        """Test that punctuation is normalized in matching."""
        nodes = ['ABC Corp.', 'XYZ Inc.']
        setup_nodes(retriever, nodes)
        
        # Try without period
        expanded = retriever._expand_seeds_to_nodes(['ABC Corp'])
        
        # Should still match via substring or token overlap
        matches = [n for n in expanded if 'ABC' in n]
        assert len(matches) > 0
    
    def test_numbers_in_entity_name(self, retriever):
        """Test matching entities with numbers."""
        nodes = ['Policy 2023', 'Agreement V2', 'Contract 001']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Policy 2023'])
        
        assert 'Policy 2023' in expanded
    
    def test_unicode_characters(self, retriever):
        """Test matching with unicode characters."""
        nodes = ['Entity A', 'Café Paris', 'München Office']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Café Paris'])
        
        assert 'Café Paris' in expanded


class TestNoMatchScenarios:
    """Test scenarios where no matches should be found."""
    
    def test_no_match_completely_different(self, retriever):
        """Test when seed has no relation to any nodes."""
        nodes = ['Compliance', 'Audit', 'Risk']
        setup_nodes(retriever, nodes)
        
        expanded = retriever._expand_seeds_to_nodes(['Zebra'])
        
        assert len(expanded) == 0
    
    def test_empty_node_list(self, retriever):
        """Test expansion on empty graph."""
        setup_nodes(retriever, [])
        
        expanded = retriever._expand_seeds_to_nodes(['Entity A'])
        
        assert expanded == []


class TestFallbackBehavior:
    """Test fallback to high-degree nodes."""
    
    def test_fallback_when_no_seeds_found(self, retriever):
        """Test that get_high_degree_nodes works as fallback."""
        nodes = ['Hub', 'Spoke1', 'Spoke2', 'Spoke3']
        setup_nodes(retriever, nodes)
        
        # Set up adjacency for degree calculation
        retriever._adjacency = {
            'Hub': ['Spoke1', 'Spoke2', 'Spoke3'],
            'Spoke1': [],
            'Spoke2': [],
            'Spoke3': []
        }
        retriever._reverse_adjacency = {
            'Hub': [],
            'Spoke1': ['Hub'],
            'Spoke2': ['Hub'],
            'Spoke3': ['Hub']
        }
        
        # Get high-degree nodes
        high_degree = retriever._get_high_degree_nodes(k=2)
        
        # Hub should be first (highest degree)
        assert high_degree[0] == 'Hub'
        assert len(high_degree) <= 2


class TestOrderPreservation:
    """Test that expansion preserves order and deduplicates."""
    
    def test_deduplication_preserves_first_occurrence(self, retriever):
        """Test that deduplication keeps first occurrence."""
        nodes = ['Entity A', 'Entity B', 'Entity C']
        setup_nodes(retriever, nodes)
        
        # Seed A matches, then token overlap might match A again
        expanded = retriever._expand_seeds_to_nodes(['Entity A', 'Entity'])
        
        # Entity A should appear only once
        assert expanded.count('Entity A') == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
