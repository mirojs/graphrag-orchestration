# Task vs Agent: Quick Reference

**TL;DR**: Agents orchestrate; tasks execute.

---

## The Difference

| | Agent | Task |
|---|-------|------|
| **What is it?** | Orchestrator / Decision Maker | Work Unit |
| **Role** | Decides what to do | Does the work |
| **Examples** | Router, Synthesis, DRIFT Orchestrator | Sub-question answering, Entity extraction, Evidence retrieval |
| **Runs** | Sequentially (makes decisions) | Often in parallel (executes work) |
| **Code Location** | `orchestrator.py`, `router/`, `routes/` | `workflows/events.py`, workflow steps |

---

## Simple Example

**Query:** "What are the differences between vendor A and B?"

```
Router Agent → "This needs DRIFT multi-hop reasoning"
               ↓
DRIFT Agent → Decomposes into 3 tasks:
              • Task 1: Get vendor A info (parallel)
              • Task 2: Get vendor B info (parallel)  
              • Task 3: Get vendor C info (parallel)
              ↓
Synthesis Agent → Combines task results → Final answer
```

---

## Code Pointers

- **Agents**: `src/worker/hybrid_v2/orchestrator.py`, `routes/route_*.py`
- **Tasks**: `workflows/drift_workflow.py`, `workflows/events.py`
- **Full Explanation**: `docs/TASK_VS_AGENT_CONCEPTS.md`

---

## Key Insight

Think of **Agents as project managers** who plan and coordinate, and **Tasks as construction workers** who do specific jobs. Multiple workers (tasks) can work in parallel, but the manager (agent) ensures everything comes together correctly.
