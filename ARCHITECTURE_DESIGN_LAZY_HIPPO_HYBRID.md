# Architecture Design: Hybrid LazyGraphRAG + HippoRAG 2 System

## 1. Executive Summary

This document outlines the architectural transformation from a complex 6-way routing system (Local, Global, DRIFT, RAPTOR, HippoRAG 2, Vector RAG) to a streamlined **3-Way Intelligent Routing System**. 

Designed specifically for high-stakes industries such as **auditing, finance, and insurance**, this architecture prioritizes **determinism, auditability, and high precision** over raw speed. It leverages the complementary strengths of **LazyGraphRAG** (for semantic understanding and synthesis) and **HippoRAG 2** (for mathematical, deterministic pathfinding).

## 2. Architecture Overview

The new architecture provides **3 distinct routes**, each optimized for a specific query pattern:

### The 3-Way Routing Logic

```
                              ┌─────────────────────────────────────┐
                              │          QUERY CLASSIFIER           │
                              │   (LLM + Heuristics Assessment)     │
                              └─────────────────────────────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    │                         │                         │
                    ▼                         ▼                         ▼
        ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
        │   ROUTE 1         │   │   ROUTE 2         │   │   ROUTE 3         │
        │   Vector RAG      │   │   Local/Global    │   │   DRIFT Multi-Hop │
        │   (Fast Lane)     │   │   Equivalent      │   │   Equivalent      │
        └───────────────────┘   └───────────────────┘   └───────────────────┘
                │                         │                         │
                │                         │                         │
                ▼                         ▼                         ▼
        ┌───────────────────┐   ┌───────────────────┐   ┌───────────────────┐
        │ Embedding Search  │   │ LazyGraphRAG +    │   │ Iterative DRIFT   │
        │ Top-K retrieval   │   │ HippoRAG 2 PPR    │   │ with LazyGraphRAG │
        │ Direct answer     │   │ Entity-focused    │   │ Multi-step reason │
        └───────────────────┘   └───────────────────┘   └───────────────────┘
```

### Route 1: Vector RAG (The Fast Lane)
*   **Trigger:** Simple, fact-based queries with clear single-entity focus
*   **Example:** "What is the invoice amount for transaction TX-12345?"
*   **Goal:** Ultra-low latency (<500ms), minimal cost
*   **When to Use:** Query can be answered from a single document chunk

### Route 2: Local/Global Search Equivalent (Entity-Focused Hybrid)
*   **Trigger:** Entity-focused queries requiring graph context, clear subject
*   **Example:** "What are all the contracts with Vendor ABC and their payment terms?"
*   **Goal:** Comprehensive entity-centric retrieval with structural precision
*   **Engines:** LazyGraphRAG (synthesis) + HippoRAG 2 (PPR pathfinding)
*   **Solves:** Original Global Search's **detail loss problem** (summaries lost fine print)

### Route 3: DRIFT Search Equivalent (Multi-Hop Reasoning)
*   **Trigger:** Ambiguous, multi-hop queries requiring iterative decomposition
*   **Example:** "Analyze our risk exposure to tech vendors through subsidiary connections"
*   **Goal:** Handle vague queries through step-by-step reasoning
*   **Engines:** DRIFT-style iteration + LazyGraphRAG + HippoRAG 2
*   **Solves:** HippoRAG 2's **ambiguous query problem** (needs clear seeds to start PPR)

### 2.1. Why 3 Routes Instead of 2?

The original 2-way design (Vector RAG vs Hybrid) had a critical flaw:

| Query Type | Problem with 2-Way Design |
|:-----------|:--------------------------|
| "What is vendor ABC's address?" | ✅ Vector RAG handles well |
| "List all ABC contracts" | ⚠️ Hybrid works, but overkill for entity-focused |
| "Analyze tech vendor risk exposure" | ❌ HippoRAG 2 fails - no clear seed entities! |

**The Solution:** Route 3 adds DRIFT-style iterative disambiguation **before** HippoRAG 2:
1. DRIFT decomposes "tech vendor risk" → sub-questions
2. Each sub-question identifies specific entities
3. HippoRAG 2 traces connections from those entities
4. LazyGraphRAG synthesizes the final answer

---

## 3. Component Breakdown & Implementation

### Route 1: Vector RAG (The Fast Lane)

*   **What:** Standard embedding-based retrieval with top-K ranking.
*   **Why:** Not every query requires graph traversal. For simple lookups, Vector RAG is 10-100x faster.
*   **Implementation:**
    *   Azure AI Search or similar vector store
    *   **Router Signal:** Single-entity query, no relationship keywords, simple question structure

### Route 2: Local/Global Equivalent (LazyGraphRAG + HippoRAG 2)

This is the replacement for Microsoft GraphRAG's Local and Global search modes.

#### Stage 2.1: Seed Identification
*   **Engine:** LazyGraphRAG community summaries + LLM
*   **What:** Extract specific entity names from the query
*   **Output:** `["Entity: ABC Corp", "Entity: Contract-2024-001"]`

#### Stage 2.2: Deterministic Tracing  
*   **Engine:** HippoRAG 2 (Personalized PageRank)
*   **What:** Mathematical graph traversal from seed entities
*   **Why:** Deterministic - same input = same output (critical for audits)
*   **Output:** Ranked evidence nodes with PPR scores

#### Stage 2.3: Synthesis with Citations
*   **Engine:** LazyGraphRAG Iterative Deepening
*   **What:** Fetch raw text chunks for evidence nodes, generate cited response
*   **Output:** Detailed report with `[Source: doc.pdf, page 5]` citations

### Route 3: DRIFT Equivalent (Multi-Hop Iterative Reasoning)

This handles queries that would confuse HippoRAG 2 due to ambiguity.

#### Stage 3.1: Query Decomposition (DRIFT-Style)
*   **Engine:** LLM with DRIFT prompting strategy
*   **What:** Break ambiguous query into concrete sub-questions
*   **Example:**
    ```
    Original: "Analyze tech vendor risk exposure"
    Decomposed:
    → Q1: "Who are our technology vendors?"
    → Q2: "What subsidiaries do these vendors have?"
    → Q3: "What contracts exist with these entities?"
    → Q4: "What are the financial terms and risk clauses?"
    ```

#### Stage 3.2: Iterative Entity Discovery
*   **Engine:** LazyGraphRAG per sub-question
*   **What:** Each sub-question identifies new entities to explore
*   **Why:** Builds up the seed set iteratively (solves HippoRAG's cold-start problem)

#### Stage 3.3: Consolidated Tracing
*   **Engine:** HippoRAG 2 with accumulated seeds
*   **What:** Run PPR with all discovered entities as seeds
*   **Output:** Complete evidence subgraph spanning all relevant connections

#### Stage 3.4: Multi-Source Synthesis
*   **Engine:** LazyGraphRAG with DRIFT-style aggregation
*   **What:** Synthesize findings from all sub-questions into coherent report
*   **Output:** Executive summary + detailed evidence trail

---

## 4. Deployment Profiles

### Profile A: General Enterprise (All 3 Routes)
*   **Routes Enabled:** 1 (Vector RAG) + 2 (Local/Global) + 3 (DRIFT)
*   **Logic:** Router classifies and dispatches to optimal route
*   **Best For:** Customer support, internal wikis, mixed query patterns
*   **Latency:** 100ms - 15s depending on route

### Profile B: High-Assurance Audit (Routes 2 + 3 Only)
*   **Routes Enabled:** 2 (Local/Global) + 3 (DRIFT) only
*   **Logic:** Vector RAG disabled to prevent shallow retrieval
*   **Best For:** Forensic accounting, compliance audits, legal discovery
*   **Latency:** 3s - 30s (thoroughness over speed)

### Profile C: Speed-Critical (Route 1 + 2 Only)
*   **Routes Enabled:** 1 (Vector RAG) + 2 (Local/Global) only
*   **Logic:** DRIFT disabled to cap latency
*   **Best For:** Real-time applications, chatbots with latency SLAs
*   **Latency:** 100ms - 5s max

---

## 5. Strategic Benefits Summary

| Feature | Original 6-Way Router | New 3-Way Architecture | Benefit |
| :--- | :--- | :--- | :--- |
| **Route Selection** | Complex, error-prone | Clear 3 patterns | Predictable behavior |
| **Ambiguity Handling** | Poor | **Route 3 (DRIFT)** handles it | No "confused" responses |
| **Detail Retention** | Low (summaries) | **High** (raw text via LazyGraphRAG) | Fine print preserved |
| **Multi-Hop Precision** | Stochastic | **Deterministic** (HippoRAG PPR) | Repeatable audits |
| **Indexing Cost** | Very High | **Minimal** | LazyGraphRAG = lazy indexing |
| **Auditability** | Black box | **Full trace** | Evidence path visible | |

## 6. Implementation Strategy (Technical)

### Shared Infrastructure
*   **Graph Database:** Neo4j for unified storage (both LazyGraphRAG and HippoRAG 2 access)
*   **Triple Indexing:**
    *   **HippoRAG View:** Subject-Predicate-Object triples for PageRank
    *   **LazyGraphRAG View:** Text Units linked to entities for synthesis
    *   **Vector Index:** Embeddings for Route 1 fast retrieval

### Python Pipeline Pseudocode

```python
import asyncio
from enum import Enum
from hipporag import HippoRAG
from graphrag.query.structured_search.local_search.search import LocalSearch

class QueryRoute(Enum):
    VECTOR_RAG = "vector_rag"           # Route 1: Simple fact lookup
    LOCAL_GLOBAL = "local_global"        # Route 2: Entity-focused hybrid
    DRIFT_MULTI_HOP = "drift_multi_hop"  # Route 3: Ambiguous multi-step

async def classify_query(query: str) -> QueryRoute:
    """
    Classify query into one of 3 routes based on:
    - Entity clarity (are specific entities mentioned?)
    - Relationship complexity (single-hop vs multi-hop?)
    - Query ambiguity (clear intent vs needs decomposition?)
    """
    # Use LLM + heuristics to classify
    ...

async def route_1_vector_rag(query: str):
    """Route 1: Fast vector similarity search."""
    results = vector_store.search(query, top_k=5)
    return synthesize_response(query, results)

async def route_2_local_global(query: str):
    """Route 2: LazyGraphRAG + HippoRAG 2 for entity-focused queries."""
    # Stage 2.1: Identify seed entities from query
    seed_entities = await identify_entities(query)
    
    # Stage 2.2: HippoRAG PPR tracing
    hrag = HippoRAG(save_dir='audit_data', llm_model_name='gpt-4o')
    evidence_nodes = hrag.retrieve(query, seeds=seed_entities, top_k=15)
    
    # Stage 2.3: LazyGraphRAG synthesis with citations
    lgrag = LocalSearch(...)
    return await lgrag.asearch(
        query=query,
        initial_entities=[n[0] for n in evidence_nodes],
        relevance_budget=0.9
    )

async def route_3_drift_multi_hop(query: str):
    """Route 3: DRIFT-style iteration for ambiguous queries."""
    # Stage 3.1: Decompose into sub-questions
    sub_questions = await drift_decompose(query)
    
    # Stage 3.2: Iteratively discover entities
    all_seeds = []
    intermediate_results = []
    for sub_q in sub_questions:
        entities = await identify_entities(sub_q)
        all_seeds.extend(entities)
        # Optional: run partial search for context
        partial = await route_2_local_global(sub_q)
        intermediate_results.append(partial)
    
    # Stage 3.3: Consolidated HippoRAG tracing with all seeds
    hrag = HippoRAG(save_dir='audit_data', llm_model_name='gpt-4o')
    complete_evidence = hrag.retrieve(query, seeds=all_seeds, top_k=30)
    
    # Stage 3.4: DRIFT-style aggregation
    return await drift_synthesize(
        original_query=query,
        sub_questions=sub_questions,
        intermediate_results=intermediate_results,
        evidence_graph=complete_evidence
    )

async def run_query(query: str):
    """Main entry point - routes to appropriate handler."""
    route = await classify_query(query)
    
    if route == QueryRoute.VECTOR_RAG:
        return await route_1_vector_rag(query)
    elif route == QueryRoute.LOCAL_GLOBAL:
        return await route_2_local_global(query)
    else:  # DRIFT_MULTI_HOP
        return await route_3_drift_multi_hop(query)
```

---

## 7. Route Selection Examples

| Query | Route | Why |
|:------|:------|:----|
| "What is ABC Corp's address?" | **Route 1** | Single entity, simple fact |
| "List all contracts with ABC Corp" | **Route 2** | Clear entity, needs graph traversal |
| "What are ABC Corp's payment terms across all contracts?" | **Route 2** | Entity-focused, relationship exploration |
| "Analyze our vendor risk exposure" | **Route 3** | Ambiguous "vendor", needs decomposition |
| "How are we connected to Company X through subsidiaries?" | **Route 3** | Multi-hop, unclear path |
| "Compare compliance status of our top 3 partners" | **Route 3** | Multi-entity, comparative analysis |

