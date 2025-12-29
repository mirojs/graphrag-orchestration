# Implementation Plan: Hybrid LazyGraphRAG + HippoRAG 2 System

This document details the step-by-step implementation plan for the architecture described in [ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md](ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md).

## Phase 1: Environment & Infrastructure Setup

### 1.1. Prerequisites
*   **Python Version:** 3.10+ (Recommended for compatibility with both libraries).
*   **Core Libraries:**
    *   `graphrag` (Microsoft's official package, v1.x+ for Lazy support).
    *   `hipporag` (HippoRAG 2 package).
    *   `networkx` (for graph manipulation).
    *   `neo4j` (Optional, if using a persistent graph store).
    *   `fastapi` (For the API layer).
    *   `langchain` / `llama-index` (For Vector RAG component).

### 1.2. Directory Structure
```bash
/graphrag-orchestration
├── /config                 # Configuration files (settings.yaml, env vars)
├── /data                   # Raw data and indexed artifacts
│   ├── /raw_documents      # Input PDFs/Text
│   ├── /graph_index        # Shared Graph artifacts (Parquet/Neo4j)
│   └── /vector_index       # Vector RAG embeddings
├── /src
│   ├── /indexing           # Scripts for Dual Indexing
│   ├── /pipeline           # Core logic for Hybrid Pipeline
│   │   ├── intent.py       # Stage 1: Disambiguation
│   │   ├── tracing.py      # Stage 2: HippoRAG Tracing
│   │   └── synthesis.py    # Stage 3: LazyGraphRAG Synthesis
│   ├── /router             # Routing logic (Profile A vs B)
│   └── /api                # FastAPI endpoints
└── /tests                  # Unit and Integration tests
```

---

## Phase 2: Data Preparation & Dual Indexing

### 2.1. Unified Graph Construction
*   **Goal:** Create a single "Source of Truth" graph that serves both engines.
*   **Action:**
    1.  Ingest documents using `graphrag`'s indexing pipeline to extract Entities and Relationships.
    2.  Output format: Parquet files (`create_final_nodes.parquet`, `create_final_relationships.parquet`).

### 2.2. Logical Dual Indexing
*   **HippoRAG View (Triples):**
    *   Write a script to convert `graphrag` relationship parquet files into HippoRAG's expected Triple format (Subject -> Predicate -> Object).
    *   Initialize `HippoRAG` indexer pointing to these triples.
*   **LazyGraphRAG View (Text Units):**
    *   Ensure `graphrag`'s `text_unit` parquet files are indexed and accessible.
    *   Configure `settings.yaml` to enable "Lazy" mode (disable community summarization if strictly following the cost-saving architecture, though keeping them can help with disambiguation).

---

## Phase 3: Core Component Implementation

### 3.1. Route A: Vector RAG (The Fast Lane)
*   **Implementation:**
    *   Use a standard Vector Store (ChromaDB/FAISS).
    *   Ingest the same `raw_documents`.
    *   Create a simple retrieval function `query_vector_rag(query: str) -> str`.

### 3.2. Route B: The Hybrid Pipeline (The Deep Dive)

#### Stage 1: Intent Disambiguation (LazyGraphRAG)
*   **File:** `src/pipeline/intent.py`
*   **Logic:**
    *   Load `graphrag`'s community reports or high-level entity list.
    *   Prompt LLM: "Given query '{query}', identify the top 3-5 specific Entity Names in our graph that this refers to. Return JSON."
    *   **Output:** `List[str]` (e.g., `["Project_Alpha", "Vendor_X"]`).

#### Stage 2: Deterministic Tracing (HippoRAG 2)
*   **File:** `src/pipeline/tracing.py`
*   **Logic:**
    *   Initialize `HippoRAG` instance.
    *   Function `trace_evidence(seed_entities: List[str]) -> List[str]`.
    *   Call `hipporag.retrieve(query, seeds=seed_entities)`.
    *   **Output:** A list of "Evidence Node Names" found via Personalized PageRank.

#### Stage 3: Synthesis & Validation (LazyGraphRAG)
*   **File:** `src/pipeline/synthesis.py`
*   **Logic:**
    *   Initialize `LocalSearch` engine from `graphrag`.
    *   Function `synthesize_report(query: str, evidence_nodes: List[str]) -> str`.
    *   Call `asearch` with `custom_args={"initial_entities": evidence_nodes, "relevance_budget": 0.9}`.
    *   **Prompt Engineering:** Modify the system prompt to strictly require citations based on the retrieved chunks.

---

## Phase 4: Orchestration & API

### 4.1. The Router
*   **File:** `src/router/main.py`
*   **Logic:**
    *   Implement `classify_query(query: str) -> RouteEnum`.
    *   **Profile A Logic:** If `is_simple_fact(query)` -> Route A, else Route B.
    *   **Profile B Logic:** Always Route B.

### 4.2. API Layer
*   **File:** `src/api/server.py`
*   **Endpoints:**
    *   `POST /query/fast`: Uses Profile A logic.
    *   `POST /query/audit`: Uses Profile B logic.
    *   `POST /admin/index`: Triggers the indexing pipeline.

---

## Phase 5: Testing & Validation

### 5.1. Unit Tests
*   Test Intent Disambiguation: Ensure "main vendor" maps to "Vendor X".
*   Test HippoRAG Tracing: Ensure known multi-hop paths are found deterministically.

### 5.2. End-to-End Audit Test
*   **Scenario:** "Find the connection between Invoice #902 and Company X."
*   **Success Criteria:**
    1.  Stage 1 identifies "Invoice #902" and "Company X".
    2.  Stage 2 finds the intermediate nodes (e.g., "Shell Company Y").
    3.  Stage 3 generates a report citing the specific documents linking them.
    4.  **Repeatability:** Running the query 5 times yields the exact same evidence path.

---

## Phase 6: Deployment Checklist
- [ ] Environment variables configured (API Keys, Neo4j URI).
- [ ] Graph Index built and validated.
- [ ] HippoRAG triples synced with GraphRAG entities.
- [ ] Router logic verified against test set.
- [ ] API endpoints secured.
