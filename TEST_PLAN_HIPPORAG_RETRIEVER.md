# Test Plan: LlamaIndex-Native HippoRAG Retriever

**Created:** December 29, 2025  
**Component:** `app/hybrid/retrievers/hipporag_retriever.py`  
**Status:** Implementation Complete, Testing In Progress

---

## 1. Overview

This document outlines the comprehensive test strategy for the LlamaIndex-native HippoRAG retriever implementation. The retriever uses Personalized PageRank (PPR) for deterministic multi-hop graph traversal and is designed for audit-grade accuracy in high-stakes industries.

### Key Testing Goals
1. **Correctness:** PPR algorithm produces mathematically correct rankings
2. **Determinism:** Same inputs always produce identical outputs
3. **Performance:** Graph loading and PPR execution within acceptable latency
4. **Integration:** Works seamlessly with Neo4j, LlamaIndex, and Azure services
5. **Multi-tenancy:** Proper isolation between tenant groups
6. **Edge Cases:** Handles empty graphs, disconnected components, malformed inputs

---

## 2. Test Categories

### 2.1. Unit Tests: PPR Algorithm

**File:** `tests/test_hipporag_retriever_ppr.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_ppr_simple_chain` | Linear graph A→B→C→D | Seed A: A gets highest score, decreasing along chain |
| `test_ppr_multiple_seeds` | Multiple seed nodes | Personalization distributed evenly across seeds |
| `test_ppr_convergence` | Iterative algorithm | Converges within max_iterations |
| `test_ppr_damping_factor` | Different damping values | Higher damping = more spread |
| `test_ppr_disconnected_graph` | Graph with isolated components | Only connected nodes get non-zero scores |
| `test_ppr_self_loops` | Nodes with self-edges | Algorithm handles without infinite loops |
| `test_ppr_bidirectional_edges` | A↔B relationships | Symmetric influence |
| `test_ppr_hub_nodes` | Star topology (hub with many spokes) | Hub gets high score from all directions |
| `test_ppr_determinism` | Run PPR twice with same inputs | Identical results every time |
| `test_ppr_empty_graph` | No nodes | Returns empty list gracefully |

### 2.2. Unit Tests: Seed Expansion

**File:** `tests/test_hipporag_retriever_seeds.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_exact_match` | Seed "Entity A" exists in graph | Returns exact node |
| `test_case_insensitive` | Seed "entity a" vs node "Entity A" | Matches despite case difference |
| `test_substring_match` | Seed "Risk" matches "Risk Management" | Returns substring matches |
| `test_token_overlap_jaccard` | Seed "Payment Terms" vs "Terms of Payment" | High Jaccard similarity → match |
| `test_no_match` | Seed doesn't exist | Returns empty list or fallback |
| `test_multiple_seeds` | List of 3 seeds | Expands all, deduplicates |
| `test_max_seeds_limit` | 20 seeds, max_seeds=10 | Only top 10 retained |
| `test_expand_seeds_per_entity` | 1 seed → 5 graph matches | Returns top `expand_seeds_per_entity` |
| `test_special_characters` | Seed with "ABC Corp." | Handles punctuation |
| `test_unicode` | Seed with non-ASCII chars | Handles UTF-8 correctly |

### 2.3. Unit Tests: Graph Loading

**File:** `tests/test_hipporag_retriever_graph.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_load_from_neo4j` | Load graph from live Neo4j | Adjacency lists populated |
| `test_multi_tenant_filtering` | Query with `group_id` filter | Only returns tenant's data |
| `test_node_properties` | Nodes have metadata | Properties cached for context retrieval |
| `test_large_graph_loading` | 10K nodes, 50K edges | Loads within 5 seconds |
| `test_graph_caching` | Load graph twice | Second load uses cache |
| `test_missing_driver` | No Neo4j driver provided | Graceful fallback |
| `test_connection_failure` | Neo4j unreachable | Error handling, doesn't crash |
| `test_empty_neo4j` | No data in Neo4j | Returns empty graph |
| `test_malformed_relationships` | Null source/target | Skips invalid edges |

### 2.4. Integration Tests: LlamaIndex Interface

**File:** `tests/test_hipporag_integration.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_retrieve_returns_nodeswithscore` | Call `retriever.retrieve()` | Returns list of `NodeWithScore` |
| `test_async_retrieve` | Call `retriever.aretrieve()` | Async interface works |
| `test_retrieve_with_seeds` | Pre-extracted seeds | Bypasses LLM entity extraction |
| `test_retrieve_uses_llm` | No seeds provided | LLM extracts entities from query |
| `test_empty_query` | Empty string query | Returns empty or uses fallback |
| `test_top_k_parameter` | top_k=5 | Returns exactly 5 results |
| `test_node_metadata` | Check result metadata | Contains `ppr_score`, `entity_name`, `group_id` |
| `test_node_text_field` | Node.text populated | Contains entity text or description |
| `test_callback_manager` | LlamaIndex callbacks | Callbacks invoked correctly |

### 2.5. Integration Tests: HippoRAGService

**File:** `tests/test_hipporag_service_llamaindex.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_service_auto_selects_llamaindex` | Service with graph_store | Uses LlamaIndex retriever |
| `test_service_fallback_to_upstream` | No graph_store, hipporag installed | Uses upstream package |
| `test_service_fallback_to_local_ppr` | Triples file exists | Uses local PPR |
| `test_service_retrieve_llamaindex_mode` | Service.retrieve() in LlamaIndex mode | Returns (entity, score) tuples |
| `test_service_health_check` | Call health_check() | Reports llamaindex_available |
| `test_service_is_llamaindex_mode` | Check mode property | Returns True when using LlamaIndex |
| `test_service_get_llamaindex_retriever` | Get raw retriever | Returns HippoRAGRetriever instance |
| `test_service_singleton_pattern` | Call get_hipporag_service() twice | Returns same instance |

### 2.6. Integration Tests: End-to-End

**File:** `tests/test_hipporag_e2e.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_route_3_global_search` | Full Route 3 pipeline | Community → Hubs → PPR → Synthesis |
| `test_route_4_drift` | Full Route 4 pipeline | Decompose → PPR → Consolidate |
| `test_multi_hop_retrieval` | Query requires 3-hop traversal | PPR finds relevant 3-hop entities |
| `test_thematic_query` | "What are the risks?" | Matches communities, expands via PPR |
| `test_audit_trail` | Query with audit_trail response | Citations traceable to graph paths |
| `test_citations_contain_ppr_scores` | Check citation metadata | PPR scores included for transparency |

### 2.7. Performance Tests

**File:** `tests/test_hipporag_performance.py`

| Test Case | Description | Target |
|:----------|:------------|:-------|
| `test_ppr_latency_small_graph` | 100 nodes, 500 edges | <100ms |
| `test_ppr_latency_medium_graph` | 10K nodes, 50K edges | <1s |
| `test_ppr_latency_large_graph` | 100K nodes, 500K edges | <5s |
| `test_graph_load_time` | Load 10K nodes from Neo4j | <3s |
| `test_memory_usage` | PPR on 100K node graph | <500MB |
| `test_concurrent_queries` | 10 parallel PPR runs | No deadlocks |

### 2.8. Edge Case Tests

**File:** `tests/test_hipporag_edge_cases.py`

| Test Case | Description | Expected Behavior |
|:----------|:------------|:------------------|
| `test_no_seeds_found` | Query extracts 0 entities | Falls back to high-degree nodes |
| `test_high_degree_fallback` | Fallback enabled, no seeds | Returns top-K degree nodes |
| `test_all_nodes_disconnected` | Graph with no edges | PPR uses only personalization vector |
| `test_single_node_graph` | Only 1 node | Returns that node |
| `test_very_long_query` | 1000-word query | Handles without error |
| `test_query_with_no_text` | Query is whitespace only | Returns empty gracefully |
| `test_unicode_entity_names` | Entities with emojis, Chinese chars | Handles correctly |
| `test_null_graph_store` | No graph_store provided | Doesn't crash, returns empty |

---

## 3. Test Data Requirements

### 3.1. Mock Graphs

Create synthetic graphs for testing:

```python
# tests/fixtures/mock_graphs.py

def create_simple_chain():
    """A → B → C → D → E"""
    return {
        'nodes': ['A', 'B', 'C', 'D', 'E'],
        'edges': [('A', 'B'), ('B', 'C'), ('C', 'D'), ('D', 'E')]
    }

def create_star_topology():
    """Hub with 10 spokes"""
    return {
        'nodes': ['Hub'] + [f'Spoke{i}' for i in range(10)],
        'edges': [('Hub', f'Spoke{i}') for i in range(10)]
    }

def create_disconnected_components():
    """Two separate subgraphs"""
    return {
        'nodes': ['A1', 'A2', 'A3', 'B1', 'B2', 'B3'],
        'edges': [('A1', 'A2'), ('A2', 'A3'), ('B1', 'B2'), ('B2', 'B3')]
    }
```

### 3.2. Neo4j Test Data

**Setup Script:** `tests/fixtures/setup_neo4j_test_data.py`

```cypher
-- Create test entities for tenant "test_group"
CREATE (e1:Entity {id: 'entity_1', name: 'Risk Management', group_id: 'test_group'})
CREATE (e2:Entity {id: 'entity_2', name: 'Compliance Policy', group_id: 'test_group'})
CREATE (e3:Entity {id: 'entity_3', name: 'Audit Trail', group_id: 'test_group'})
-- ... relationships ...
CREATE (e1)-[:RELATES_TO]->(e2)
CREATE (e2)-[:REQUIRES]->(e3)
```

### 3.3. LLM Mock Responses

For testing without calling real LLMs:

```python
# tests/fixtures/mock_llm.py

class MockAzureOpenAI:
    def complete(self, prompt):
        # Extract entities from prompt
        if "extract entities" in prompt.lower():
            return '["Risk Management", "Compliance"]'
        return "Mock response"
    
    async def acomplete(self, prompt):
        return self.complete(prompt)
```

---

## 4. Test Execution Strategy

### 4.1. CI/CD Integration

```yaml
# .github/workflows/test.yml
name: HippoRAG Retriever Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      neo4j:
        image: neo4j:5.15
        env:
          NEO4J_AUTH: neo4j/password
        ports:
          - 7687:7687
    
    steps:
      - uses: actions/checkout@v3
      - name: Install dependencies
        run: pip install -e ".[test]"
      - name: Run unit tests
        run: pytest tests/test_hipporag_retriever_*.py -v
      - name: Run integration tests
        run: pytest tests/test_hipporag_integration.py -v
      - name: Run performance tests
        run: pytest tests/test_hipporag_performance.py -v --benchmark
```

### 4.2. Local Testing

```bash
# Unit tests (fast, no external dependencies)
pytest tests/test_hipporag_retriever_ppr.py -v

# Integration tests (requires Neo4j)
docker-compose up -d neo4j
pytest tests/test_hipporag_integration.py -v

# E2E tests (requires full stack)
pytest tests/test_hipporag_e2e.py -v --slow

# Performance benchmarks
pytest tests/test_hipporag_performance.py -v --benchmark-only
```

### 4.3. Test Coverage Goals

| Module | Target Coverage |
|:-------|:----------------|
| `hipporag_retriever.py` | 90%+ |
| `hipporag_service.py` (LlamaIndex mode) | 85%+ |
| PPR algorithm (`_run_personalized_pagerank`) | 100% |
| Seed expansion (`_expand_seeds_to_nodes`) | 95%+ |

---

## 5. Success Criteria

### 5.1. Functional Requirements
- ✅ All unit tests pass (PPR, seeds, graph loading)
- ✅ All integration tests pass (LlamaIndex interface, service)
- ✅ E2E tests demonstrate full Route 3 & 4 pipelines
- ✅ Edge cases handled gracefully (no crashes)

### 5.2. Non-Functional Requirements
- ✅ PPR latency <1s for 10K node graphs
- ✅ Memory usage <500MB for 100K node graphs
- ✅ Deterministic results (100% reproducibility)
- ✅ Multi-tenant isolation (no data leakage)

### 5.3. Code Quality
- ✅ Type hints on all public methods
- ✅ Docstrings on all classes/methods
- ✅ No Pylance/mypy errors
- ✅ Code coverage >90%

---

## 6. Risk Mitigation

| Risk | Mitigation Strategy |
|:-----|:-------------------|
| PPR algorithm correctness | Compare against reference implementation (NetworkX) |
| Neo4j connection issues | Use docker-compose for consistent test environment |
| LLM API failures | Mock LLM responses in unit tests |
| Large graph performance | Add performance benchmarks, set timeouts |
| Multi-tenancy bugs | Dedicated tests for group_id filtering |
| Flaky tests | Use deterministic seeds, isolated test data |

---

## 7. Test Maintenance

### 7.1. When to Update Tests

- **Algorithm changes:** Re-run all PPR tests
- **Interface changes:** Update integration tests
- **New features:** Add corresponding test cases
- **Bug fixes:** Add regression test

### 7.2. Test Documentation

Each test file should have:
```python
"""
Test Suite: HippoRAG Retriever - PPR Algorithm

Purpose: Verify correctness of Personalized PageRank implementation

Test Data: Synthetic graphs defined in tests/fixtures/mock_graphs.py

Dependencies:
- pytest
- pytest-asyncio
- NetworkX (for reference comparison)

Run: pytest tests/test_hipporag_retriever_ppr.py -v
"""
```

---

## 8. Next Actions

**Priority 1: Core Functionality**
1. Create `tests/test_hipporag_retriever_ppr.py` (PPR algorithm tests)
2. Create `tests/test_hipporag_retriever_seeds.py` (seed expansion tests)
3. Create `tests/test_hipporag_integration.py` (LlamaIndex interface tests)

**Priority 2: Robustness**
4. Create `tests/test_hipporag_service_llamaindex.py` (service integration)
5. Create `tests/test_hipporag_edge_cases.py` (error handling)

**Priority 3: Performance & E2E**
6. Create `tests/test_hipporag_performance.py` (benchmarks)
7. Create `tests/test_hipporag_e2e.py` (full pipeline tests)

**Priority 4: CI/CD**
8. Update `.github/workflows/test.yml` with new test suites
9. Add test coverage reporting (codecov)
