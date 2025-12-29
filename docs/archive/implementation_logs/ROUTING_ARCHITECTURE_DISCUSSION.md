# Routing Architecture Discussion: 4-Way vs. 5-Way

## Context
We are defining the routing logic for the "Low Latency Engine" (<2min SLA).
The user has proposed two models:
1.  **4-Way Routing:** Local / Global / DRIFT / RAPTOR
2.  **5-Way Routing:** Local / Global / DRIFT / RAPTOR / Vector RAG

## Analysis of Routes

| Route | Mechanism | Best For | Cost/Latency |
| :--- | :--- | :--- | :--- |
| **Vector RAG** | Embedding → Top-K Text Chunks | Exact quotes, specific facts present in a single chunk. | ⚡ **Lowest** |
| **Local Search** | Embedding → Entities → 1-Hop Neighbors | "Tell me about Entity X", specific entity details. | 🟢 Low/Medium |
| **Global Search** | Community Summaries (Map-Reduce) | "What are the main themes?", broad overview of the whole corpus. | 🟡 Medium |
| **RAPTOR** | Tree Traversal of Summaries | Hierarchical questions, "Summarize the risk section". | 🟡 Medium |
| **DRIFT** | Multi-Hop (Summary ↔ Entity ↔ Summary) | "How does X affect Y?", connecting distant concepts. | 🔴 High |

## Comparison

### Option A: 4-Way Routing (Local / Global / DRIFT / RAPTOR)
*Excludes "Vector RAG".*

*   **Pros:** Simplifies the router slightly.
*   **Cons:**
    *   **Inefficient for Simple Facts:** If a user asks "What is the date of the contract?", the system must use **Local Search** (finding entities, traversing to chunks) instead of a simple **Vector Search** (finding the chunk directly).
    *   **Latency Risk:** Local Search involves more DB hits than Vector Search.

### Option B: 5-Way Routing (+ Vector RAG)
*Includes "Vector RAG" as a distinct route.*

*   **Pros:**
    *   **The "Fast Lane":** Simple questions get the fastest possible response.
    *   **Cost Savings:** Vector search is cheaper than Graph traversal.
    *   **Precision:** For exact wording (e.g., "quote the liability clause"), Vector RAG often beats Graph methods which rely on synthesized descriptions.
*   **Cons:**
    *   **Router Complexity:** The LLM must distinguish between 5 options.

## Deep Dive: Global vs. RAPTOR
Do we need both?
*   **Global Search** (Standard GraphRAG) relies on **Community Summaries** (Leiden clusters). It is excellent for "breadth-first" understanding of the dataset.
*   **RAPTOR** relies on a **Recursive Tree** of summaries. It is excellent for "depth-first" or hierarchical understanding.
*   **Verdict:** They are distinct enough to keep. "Global" is for *broad* themes. "RAPTOR" is for *structured* deep-dives.

## Recommendation: Adopt 5-Way Routing

For a "Low Latency" engine, having the **Vector RAG** route is critical. It serves as the baseline for speed.

**Proposed Routing Logic:**
1.  **Vector:** "Find this specific text." (Fastest)
2.  **Local:** "Tell me about this person/company."
3.  **Global:** "Overview of the whole dataset."
4.  **RAPTOR:** "Summarize this specific topic/section."
5.  **DRIFT:** "Connect these two distant things." (Slowest)

## Codebase Reality Check
I analyzed `triple_engine_retriever.py` and found:
- The current `vector` route calls `self.store.search_entities_hybrid`.
- **This is actually "Local Search" (Entity-based).** It does not search raw text chunks.
- **Missing Route:** We currently lack a true "Vector RAG" route that searches `TextChunk` nodes directly.

## Recommendation: Adopt 5-Way Routing & Rename
To align terms with reality:

1.  **Rename** current `vector` route to `local` (since it searches Entities).
2.  **Create** a new `vector` route that searches `TextChunk` nodes (for exact text retrieval).
3.  **Keep** `graph`, `raptor`, `drift`.

**Final 5-Way Map:**
1.  **Vector:** Text Chunk Search (Fastest, best for quotes).
2.  **Local:** Entity Search (Best for "Who is X?").
3.  **Graph:** Community Search (Best for broad themes).
4.  **RAPTOR:** Tree Summary Search (Best for hierarchical topics).
5.  **DRIFT:** Multi-hop Reasoning (Best for complex connections).

## Next Steps
1.  Update `triple_engine_retriever.py` to support 5 routes.
2.  Update the prompt to clearly distinguish "Vector" (Text) from "Local" (Entity).
