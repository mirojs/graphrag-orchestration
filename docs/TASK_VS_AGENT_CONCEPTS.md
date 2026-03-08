# Task vs Agent: Conceptual Guide

**Date:** 2026-02-17  
**Status:** Documentation  
**Purpose:** Clarify the distinction between "task" and "agent" concepts in the GraphRAG Orchestration codebase

---

## Quick Answer

| Concept | Definition | Role |
|---------|------------|------|
| **Agent** | Autonomous processing component that orchestrates work | Decision maker and coordinator |
| **Task** | Individual processing unit within a workflow | Work unit to be executed |

**In one sentence:** Agents decide what to do and orchestrate execution; tasks are the actual work units being executed.

---

## Detailed Explanation

### What is an Agent?

An **agent** is an autonomous component responsible for:
- Making decisions about how to process a query
- Orchestrating the execution of multiple tasks
- Coordinating different retrieval strategies
- Synthesizing results from multiple sources

#### Agent Examples in This Codebase

1. **Router Agent** (`src/worker/hybrid_v2/router/main.py`)
   - Classifies incoming queries
   - Decides which retrieval route to use (Local, Global, DRIFT, or Unified)
   - Uses LLM (gpt-4o-mini) to understand query intent

2. **Route-Specific Agents** (Orchestration Components)
   - **Local Search Agent** (`src/worker/hybrid_v2/routes/route_2_local.py`): Entity-focused retrieval with LazyGraphRAG iterative deepening
   - **Global Search Agent** (`src/worker/hybrid_v2/routes/route_3_global.py`): Thematic queries with HippoRAG PPR
   - **DRIFT Agent** (`src/worker/hybrid_v2/routes/route_4_drift.py`): Multi-hop iterative reasoning for complex queries
   - **Unified Agent** (`src/worker/hybrid_v2/routes/route_5_unified.py`): Combined HippoRAG search

3. **Synthesis Agent** (`src/worker/hybrid_v2/pipeline/synthesis.py`)
   - Combines evidence from multiple sources
   - Generates coherent final answers
   - Uses confidence scoring to validate outputs

### What is a Task?

A **task** is a discrete unit of work that:
- Represents a specific processing step
- Can often run in parallel with other tasks
- Produces a specific output or result
- Is coordinated by an agent

#### Task Examples in This Codebase

1. **Sub-Question Tasks** (Route 4 DRIFT - `src/worker/hybrid_v2/workflows/drift_workflow.py`)
   ```python
   # Complex query decomposed into parallel sub-question tasks
   Query: "What are the differences between vendor A and vendor B?"
   →
   Task 1: Answer "What are vendor A's key features?"
   Task 2: Answer "What are vendor B's key features?"
   Task 3: Compare results
   ```

2. **Entity Extraction Tasks** (Route 2 Local Search)
   - Each entity mentioned in a query spawns a retrieval task
   - Tasks run in parallel for efficiency
   - Results aggregated by the agent

3. **Evidence Retrieval Tasks** (All Routes)
   - Vector search task
   - Graph traversal task
   - Full-text search task
   - Re-ranking task

4. **Community Matching Tasks** (Route 3 Global Search)
   - Embedding similarity computation
   - Hub entity extraction
   - PPR (Personalized PageRank) calculation

---

## Task-Agent Relationship

### Hierarchical View

```
┌─────────────────────────────────────────────────┐
│                 User Query                       │
└───────────────────┬─────────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│          Router Agent (Orchestrator)             │
│  • Analyzes query intent                         │
│  • Selects appropriate route                     │
│  • Configures retrieval parameters               │
└───────────────────┬─────────────────────────────┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│  Agent 1   │ │  Agent 2   │ │  Agent 3   │
│  (Local)   │ │  (Global)  │ │  (DRIFT)   │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
      └──────────────┴──────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   Parallel Tasks      │
        │  ┌─────┐ ┌─────┐     │
        │  │Task1│ │Task2│ ... │
        │  └─────┘ └─────┘     │
        └───────────┬───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   Result Aggregation   │
        └───────────┬───────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │   Synthesis Agent      │
        │   (Final Answer)       │
        └───────────────────────┘
```

### Workflow View (LlamaIndex Workflows)

The codebase uses **LlamaIndex Workflows** for task orchestration:

```python
# From src/worker/hybrid_v2/workflows/drift_workflow.py

class DRIFTWorkflow(Workflow):
    """
    Agent: DRIFT multi-hop reasoning orchestrator
    
    Tasks executed by this agent:
    1. Query decomposition → sub-questions
    2. Parallel sub-question retrieval (one task per sub-question)
    3. Entity resolution for discovered entities
    4. Evidence consolidation
    5. Final synthesis
    """
    
    @step
    async def decompose_query(self, ev: StartEvent) -> DecomposeEvent:
        # Agent decides how to break down the query
        # Returns: Multiple tasks (sub-questions)
        pass
    
    @step  
    async def answer_subquestion(self, ev: SubQuestionEvent) -> EvidenceEvent:
        # Task: Answer a single sub-question
        # Runs in parallel with other sub-question tasks
        pass
    
    @step
    async def synthesize_answer(self, ev: CollectEvent) -> StopEvent:
        # Agent: Combine all task results into final answer
        pass
```

---

## Real-World Analogy

Think of it like a construction project:

- **Agent = Project Manager**
  - Decides what needs to be built
  - Creates the plan
  - Assigns work to workers
  - Coordinates different teams
  - Ensures quality of final result

- **Task = Construction Work Item**
  - Pour foundation (Task 1)
  - Frame walls (Task 2)
  - Install electrical (Task 3)
  - Each task can be done by different workers
  - Some tasks can run in parallel
  - Each task produces a specific output

---

## Code References

### Agent Implementations

| File | Agent Type | Responsibility |
|------|------------|----------------|
| `src/worker/hybrid_v2/router/main.py` | Query Router | Route selection and intent classification |
| `src/worker/hybrid_v2/routes/route_2_local.py` | Local Search | Entity-focused retrieval orchestration |
| `src/worker/hybrid_v2/routes/route_3_global.py` | Global Search | Thematic query orchestration |
| `src/worker/hybrid_v2/routes/route_4_drift.py` | DRIFT Multi-hop | Complex reasoning orchestration |
| `src/worker/hybrid_v2/routes/route_5_unified.py` | Unified HippoRAG | Combined search orchestration |
| `src/worker/hybrid_v2/pipeline/synthesis.py` | Synthesis | Answer generation and validation |
| `src/worker/hybrid_v2/orchestrator.py` | Main Orchestrator | Top-level agent coordination |

### Task Event Definitions

| File | Task Events | Description |
|------|-------------|-------------|
| `src/worker/hybrid_v2/workflows/events.py` | `SubQuestionEvent`, `EvidenceEvent`, `CollectEvent` | Event-based task communication |
| `src/worker/hybrid_v2/workflows/drift_workflow.py` | Workflow steps | Task execution flow for DRIFT route |

### Configuration

| File | Purpose |
|------|---------|
| `src/core/config.py` | Model selection for different agents (router, synthesis, decomposition) |

---

## Agent Decision-Making Flow

### Example: Complex Query Processing

**Query:** "What are the key differences between vendor proposals, and which is better?"

```
1. Router Agent Analysis
   ├─ Detects: Comparison query with multiple entities
   ├─ Determines: Ambiguous, requires multi-hop reasoning
   └─ Routes to: DRIFT Agent (Route 4)

2. DRIFT Agent Orchestration
   ├─ Decomposes into tasks:
   │  ├─ Task A: "What are vendor A's key features?"
   │  ├─ Task B: "What are vendor B's key features?"
   │  └─ Task C: "What are vendor C's key features?"
   │
   ├─ Executes tasks in parallel
   │  ├─ Each task spawns sub-tasks:
   │  │  ├─ Entity extraction
   │  │  ├─ Graph traversal
   │  │  └─ Evidence retrieval
   │  │
   │  └─ Aggregates results per vendor
   │
   └─ Synthesizes final comparison answer

3. Synthesis Agent
   ├─ Combines evidence from all tasks
   ├─ Structures comparison
   ├─ Validates confidence scores
   └─ Generates final answer with citations
```

---

## Key Architectural Patterns

### 1. Event-Driven Task Communication

Tasks communicate through events (`SubQuestionEvent`, `EvidenceEvent`), enabling:
- Parallel execution
- Loose coupling
- Fault tolerance
- Progress tracking

### 2. Agentic Confidence Loops

Agents can:
- Execute tasks
- Check confidence scores
- Re-decompose queries if confidence is low
- Trigger additional retrieval tasks

From `LLAMAINDEX_WORKFLOW_MIGRATION_PLAN_2026-01-24.md`:
> "LlamaIndex Workflows enable agentic confidence loops — agents execute tasks, check confidence, and can trigger re-decomposition for low-confidence responses."

### 3. Parallel Task Execution

Multiple tasks run concurrently for efficiency:
```python
# Pseudo-code representation
async def process_query(query: str):
    # Agent: Decompose query
    sub_questions = decompose(query)
    
    # Tasks: Process in parallel
    results = await asyncio.gather(*[
        answer_question(q) for q in sub_questions
    ])
    
    # Agent: Synthesize
    return synthesize(results)
```

---

## Model Allocation by Agent/Task

From `src/worker/hybrid_v2/orchestrator.py`:

| Component | Model | Purpose |
|-----------|-------|---------|
| Router Agent | gpt-4o-mini | Fast, cost-effective classification |
| Decomposition Task | gpt-4.1 | High-quality query decomposition |
| Entity Extraction | gpt-4o or NER | Deterministic extraction |
| Synthesis Agent | gpt-5.2 or gpt-4o | High-quality answer generation |

---

## Frontend Representation

The UI reflects the agent/task distinction:

- **AgentPlan Component** (`frontend/src/components/AgentPlan.tsx`)
  - Shows agent's thinking process
  - Displays planned tasks
  - Tracks task execution status

- **Task Progress Indicators**
  - Show parallel task execution
  - Display completion status per task
  - Aggregate results visualization

---

## Best Practices

### When Designing Agents

1. **Single Responsibility**: Each agent should have a clear purpose
2. **Decision Authority**: Agents should make autonomous decisions
3. **Coordination**: Agents orchestrate tasks but don't execute low-level work
4. **Confidence Scoring**: Agents should validate their outputs

### When Designing Tasks

1. **Atomicity**: Tasks should be discrete, complete units of work
2. **Parallelizability**: Design tasks to run independently when possible
3. **Clear Outputs**: Each task should produce a well-defined result
4. **Idempotency**: Tasks should be safely re-runnable

---

## Related Documentation

- [`LLAMAINDEX_WORKFLOW_MIGRATION_PLAN_2026-01-24.md`](../LLAMAINDEX_WORKFLOW_MIGRATION_PLAN_2026-01-24.md) - Workflow architecture planning
- [`ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md`](../ARCHITECTURE_HYBRID_SKELETON_2026-02-11.md) - Overall system architecture
- [`src/worker/hybrid_v2/orchestrator.py`](../src/worker/hybrid_v2/orchestrator.py) - Main agent orchestration code
- [`src/worker/hybrid_v2/workflows/`](../src/worker/hybrid_v2/workflows/) - Task workflow implementations

---

## Summary

- **Agents** are orchestrators that make decisions and coordinate work
- **Tasks** are discrete work units that agents execute
- This codebase uses LlamaIndex Workflows for event-driven task execution
- The Router Agent selects the appropriate route (agent) for each query
- Route-specific agents decompose work into parallel tasks
- The Synthesis Agent combines task results into final answers
- This separation enables:
  - Parallel execution for efficiency
  - Modular, maintainable code
  - Clear responsibility boundaries
  - Sophisticated multi-hop reasoning

Understanding this distinction is crucial for extending the system with new retrieval strategies or reasoning patterns.
