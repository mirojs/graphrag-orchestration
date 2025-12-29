# Routing Strategy Analysis: 3-Way vs. 4-Way

## The Question
Should the system use a **3-Way Router** (Vector, Graph, RAPTOR) or a **4-Way Router** (Vector, Graph, RAPTOR, DRIFT)?

## Recommendation: Keep the 4-Way Router

### Reason 1: Performance & Latency (Critical for <2min SLA)
The "Low Latency" architecture relies on doing the *minimum amount of work* necessary to answer a query.
- **RAPTOR (Summarization):** Relatively cheap. It just needs to fetch high-level summary nodes.
- **DRIFT (Multi-Hop Reasoning):** Expensive. It involves traversing from summaries down to entities and back up to other summaries ("teleporting").

**If you merge them (3-Way):**
- You risk running expensive DRIFT logic for simple "Give me a summary of the risks" questions.
- Or, you risk failing to answer complex "How does X affect Y?" questions because the generic "RAPTOR" route is too simple.

### Reason 2: Distinct User Intents
The four routes map to four distinct types of user questions:
1.  **Vector:** "What is the value of X?" (Specific Fact)
2.  **Graph:** "Who works with X?" (Direct Relationship)
3.  **RAPTOR:** "What is this document about?" (High-level Theme)
4.  **DRIFT:** "How does the delay in X impact the budget in Y?" (Complex, multi-step reasoning)

### Reason 3: LLM Clarity
The routing LLM (`o4-mini` or `gpt-5-2`) performs better when the definitions are distinct.
- Separating `drift` tells the LLM: "Only pick this if the user is asking for a complex connection between distant topics."
- This prevents "over-routing" to complex strategies.

## Conclusion
Retain the **4-Way Routing** architecture. It provides the granularity needed to optimize for both **speed** (by using cheaper routes when possible) and **quality** (by having a dedicated route for complex reasoning).
