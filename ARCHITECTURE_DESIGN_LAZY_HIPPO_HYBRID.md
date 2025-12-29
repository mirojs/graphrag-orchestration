# Architecture Design: Hybrid LazyGraphRAG + HippoRAG 2 System

## 1. Executive Summary

This document outlines the architectural transformation from a complex 6-way routing system (Local, Global, DRIFT, RAPTOR, HippoRAG 2, Vector RAG) to a streamlined **Hybrid Intelligence Pipeline**. 

Designed specifically for high-stakes industries such as **auditing, finance, and insurance**, this architecture prioritizes **determinism, auditability, and high precision** over raw speed. It leverages the complementary strengths of **LazyGraphRAG** (for semantic understanding and synthesis) and **HippoRAG 2** (for mathematical, deterministic pathfinding).

## 2. Architecture Overview

The new architecture simplifies the decision-making process into a primary **2-Way Split**, with a sophisticated **3-Stage Pipeline** for complex queries.

### The Routing Logic
Instead of a complex multi-way router, the system uses a simple binary classifier based on query complexity and intent:

1.  **Route A: Vector RAG (The Fast Lane)**
    *   **Trigger:** Simple, fact-based queries (e.g., "What is the invoice amount for transaction X?").
    *   **Goal:** Ultra-low latency, low cost.
2.  **Route B: The Hybrid Pipeline (The Deep Dive)**
    *   **Trigger:** Complex, ambiguous, multi-hop, or thematic queries (e.g., "Analyze the risk exposure to our main tech partner via subsidiary connections").
    *   **Goal:** Maximum precision, determinism, and comprehensive evidence.

### 2.1. Design Rationale: Replacing Global Search
A critical consideration in this design is the removal of the original **Global Search** mode.

*   **The Problem (Detail Loss):** The original Global Search used a "Map-Reduce" approach over pre-summarized community reports. While excellent for broad themes (acting like a "Satellite Photo"), it often smoothed over specific, low-level details due to the summarization bottleneck.
*   **The LazyGraphRAG Solution:** LazyGraphRAG replaces pre-summarization with **Iterative Deepening**. It acts like a drone that starts high but "zooms in" to fetch raw text chunks during the query. This preserves details that the original Global Search lost.
*   **Why Hybrid is Superior:** While LazyGraphRAG is better than the original Global Search, it is still "agentic" (stochastic). By pairing it with **HippoRAG 2** (mathematical/deterministic), we ensure that we don't just find *more* details, but we find the *exact* structural connections that an LLM might overlook.

---

## 3. Component Breakdown & Implementation

### Route A: Vector RAG (The Fast Lane)

*   **What:** Standard embedding-based retrieval.
*   **Why:** Not every query requires a graph traversal. For simple lookups, Vector RAG is orders of magnitude faster (ms vs. seconds) and cheaper.
*   **How to Implement:**
    *   Keep the existing Vector RAG implementation.
    *   **Router Prompt:** "Is this query a simple factual lookup that can be answered by a single document? If yes -> Vector RAG."

### Route B: The Hybrid Pipeline (LazyGraphRAG + HippoRAG 2)

This is the core innovation. It treats the LLM as a "writer/translator" and the Graph as a "map," ensuring the "finding" process is grounded in math rather than stochastic agent behavior.

#### Stage 1: Intent Disambiguation (The "Interpreter")
*   **Engine:** **LazyGraphRAG** (Query Refinement Module)
*   **What:** Decomposes ambiguous user queries into specific, graph-grounded entities.
*   **Why:** Financial queries are often vague (e.g., "main vendor"). HippoRAG 2 needs specific starting points ("seeds") to work effectively. An LLM agent is needed to map "main vendor" to specific Entity IDs like `[Entity: AWS, Entity: Azure]`.
*   **How to Implement:**
    *   Use LazyGraphRAG's `query_refinement` or a custom prompt against the graph's community summaries.
    *   **Output:** A JSON list of specific `Seed Entities` and `Relationship Constraints`.

#### Stage 2: Deterministic Tracing (The "Detective")
*   **Engine:** **HippoRAG 2**
*   **What:** Executes **Personalized PageRank (PPR)** starting from the seeds identified in Stage 1.
*   **Why:** 
    *   **Determinism:** Unlike "agentic" search (where an LLM decides where to look next and might miss a link), PPR is a mathematical algorithm. If a path exists in the graph, PPR *will* find it.
    *   **Multi-Hop:** It excels at finding non-obvious connections (3+ hops) that semantic similarity would miss.
*   **How to Implement:**
    *   Initialize `HippoRAG` with the shared knowledge graph.
    *   Call `hipporag.retrieve(query, seeds=seed_entities)`.
    *   **Output:** A ranked subgraph of nodes (entities) and edges (relationships) representing the "Chain of Evidence."

#### Stage 3: Synthesis & Evidence Validation (The "Analyst")
*   **Engine:** **LazyGraphRAG** (Iterative Deepening / Local Search)
*   **What:** Uses the "Chain of Evidence" from Stage 2 as anchors to fetch raw text and generate the final report.
*   **Why:** 
    *   **Detail Retention:** HippoRAG finds the *nodes*, but LazyGraphRAG retrieves the *content* (raw text chunks).
    *   **Context:** It understands the "why" behind the connections.
    *   **Auditability:** It can cite specific document chunks for every claim.
*   **How to Implement:**
    *   Pass the HippoRAG result nodes as `focal_entities` or `context_anchors` to LazyGraphRAG.
    *   Set `relevance_budget` to High (e.g., 0.8+) to ensure thorough coverage.
    *   **Prompting:** Enforce a "Factual Guardrail" requiring citations for every sentence.

---

## 4. Deployment Profiles

Depending on the specific use case, this architecture can be deployed in two distinct configurations:

### Profile A: General Enterprise Search (Speed-Optimized)
*   **Structure:** Includes **Route A (Vector RAG)** + **Route B (Hybrid Pipeline)**.
*   **Logic:** The router aggressively offloads simple queries to Vector RAG.
*   **Best For:** Customer support, internal wikis, and general Q&A where sub-second latency is critical and 90% accuracy is acceptable for simple facts.

### Profile B: High-Assurance Audit (Precision-Optimized)
*   **Structure:** **Route B (Hybrid Pipeline) ONLY**.
*   **Logic:** Vector RAG is disabled. Every query, no matter how simple, is forced through the LazyGraphRAG + HippoRAG pipeline.
*   **Why Remove Vector RAG?** Vector RAG relies on semantic similarity. In auditing, a critical piece of evidence (e.g., a transaction ID) might not be "semantically similar" to the query but is structurally vital. Removing the "Fast Lane" eliminates the risk of shallow retrieval.
*   **Best For:** Forensic accounting, compliance auditing, and legal discovery where "missing a link" is a failure and 5-10 second latency is acceptable.

---

## 5. Strategic Benefits for High-Stakes Industries

| Feature | Original 6-Way Router | New Hybrid Architecture | Benefit |
| :--- | :--- | :--- | :--- |
| **Ambiguity Handling** | Poor (often routed incorrectly) | **Excellent** (Refined by LazyGraphRAG) | Prevents "garbage in, garbage out" for vague audit questions. |
| **Multi-Hop Precision** | Stochastic (Hit or Miss) | **Deterministic** (Mathematical Guarantee) | Ensures repeatable results for audits. Same question = Same evidence path. |
| **Detail Retention** | Low (Global Search used summaries) | **High** (Fetches raw text) | No "small print" is lost in summarization. |
| **Indexing Cost** | Very High ($$$$) | **Minimal ($)** | LazyGraphRAG removes the need for expensive pre-computed community summaries. |
| **Auditability** | Low (Black Box Agent) | **High** (Visualizable PPR Path) | You can trace exactly *why* a connection was made. |

## 6. Implementation Strategy (Technical)

### Shared Infrastructure
*   **Graph Database:** A unified storage layer (e.g., Neo4j, NetworkX, or Parquet files) that both LazyGraphRAG and HippoRAG 2 can access.
*   **Dual Indexing (Logical):**
    *   **HippoRAG View:** Focuses on Triples (Subject-Predicate-Object) for PageRank.
    *   **LazyGraphRAG View:** Focuses on Text Units and Community hierarchies for synthesis.

### Python Pipeline Pseudocode

```python
import asyncio
from hipporag import HippoRAG
from graphrag.query.structured_search.local_search.search import LocalSearch

async def run_audit_pipeline(user_query: str):
    # --- STAGE 1: INTENT DISAMBIGUATION (LazyGraphRAG Logic) ---
    # (Conceptual) Use LLM to map query to specific graph entities
    # refined_query, seed_entities = lazy_graph_disambiguate(user_query)
    
    # --- STAGE 2: DETERMINISTIC TRACING (HippoRAG 2) ---
    # Initialize HippoRAG to find the exact evidence path
    hrag = HippoRAG(save_dir='audit_data', llm_model_name='gpt-4o')
    
    # Retrieve top nodes based on PageRank math
    # This guarantees we find the structural path, not just semantic matches
    ranked_nodes = hrag.retrieve(user_query, top_k=15) # In practice, pass seed_entities if supported
    
    # Extract entity names to use as "Anchors"
    evidence_anchors = [node_name for node_name, score in ranked_nodes]

    # --- STAGE 3: SYNTHESIS & VALIDATION (LazyGraphRAG) ---
    # Initialize LazyGraphRAG
    lgrag = LocalSearch(...) 
    
    # Execute search using the HippoRAG anchors
    final_report = await lgrag.asearch(
        query=user_query,
        custom_args={
            "initial_entities": evidence_anchors, # Force start at evidence nodes
            "relevance_budget": 0.9,              # Max precision
            "response_type": "detailed_audit_report" 
        }
    )
    
    return final_report
```
