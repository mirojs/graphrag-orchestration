# LlamaIndex Workflows Migration Plan for Routes 3 & 4

**Date:** January 24, 2026  
**Status:** Planned (pending router accuracy testing)  
**Priority:** Medium — execute after top-level router validation

---

## Executive Summary

Refactor Route 4 (DRIFT) and Route 3 (Global Search) to use LlamaIndex Workflows for:
- **Parallel execution** of independent stages (3x faster Route 4, 2.5x faster Route 3)
- **Structured fallback handling** via events instead of nested try/except
- **Automatic observability** via LlamaIndex instrumentation (removes 15+ manual timing calls)
- **Agentic confidence loops** with clean event-driven re-decomposition

**Key Finding:** The top-level classification router is already well-designed (hybrid heuristic + LLM) and does NOT need Workflow migration. Only the internal stage orchestration benefits.

---

## Background: Current Architecture Analysis

### Top-Level Router (Keep As-Is) ✅

**Location:** `graphrag-orchestration/app/hybrid/router/main.py`

The current router uses a **hybrid heuristic + LLM approach** that matches industry best practices:

| Feature | Current Implementation | Industry Standard |
|---------|------------------------|-------------------|
| Primary routing | Heuristic scoring (complexity × 0.6 + ambiguity × 0.4) | Semantic/Keyword routing |
| Borderline handling | LLM refinement for scores 0.3-0.7 | LLM classifier fallback |
| Thresholds | vector=0.25, global=0.5, drift=0.75 | Tunable per deployment |
| Profile constraints | High Assurance disables Route 1 | Same pattern |

**Verdict:** LlamaIndex `RouterQueryEngine` would NOT add value — it's a simpler abstraction than what we already have.

### Route 3 Global Search (Needs Workflow) ⚠️

**Location:** `graphrag-orchestration/app/hybrid/search_pipeline_stages.py` (lines 2400-3400)

**Current Stages (Sequential Execution):**

| Stage | Name | Latency | Dependencies |
|-------|------|---------|--------------|
| 3.1 | Community Matching | ~50ms | None |
| 3.2 | Hub Entity Extraction | ~100ms | 3.1 |
| 3.3 | Enhanced Graph Context | ~50ms | 3.2 |
| 3.3.5 | Hybrid RRF (BM25 + Vector) | ~100ms | 3.2 (can parallel with 3.3) |
| Section | Semantic Section Discovery | ~100ms | 3.2 (can parallel) |
| SHARES_ENTITY | Cross-Document Expansion | ~50ms | 3.2 (can parallel) |
| Keyword | Domain-Specific Keywords | ~50ms | 3.2 (can parallel) |
| 3.4 | HippoRAG PPR Tracing | ~150ms | All retrieval stages |
| 3.4.1 | Coverage Gap Fill | ~100ms | 3.4 |
| 3.5 | Synthesis | ~500ms | All above |

**Problem:** Stages 3.3.5, Section, SHARES_ENTITY, and Keyword are **independent after hub extraction** but run sequentially (~300ms wasted).

### Route 4 DRIFT (Needs Workflow) ⚠️

**Location:** `graphrag-orchestration/app/hybrid/search_pipeline_stages.py` (lines 3800-4200)

**Current Stages:**

| Stage | Name | Latency | Notes |
|-------|------|---------|-------|
| 4.0 | Date Metadata Fast-Path | ~10ms | Optional shortcut |
| 4.1 | Query Decomposition | ~200ms | LLM call |
| 4.2 | Iterative Entity Discovery | ~700ms × N | **Sequential loop** |
| 4.3 | Consolidated PPR Tracing | ~200ms | After all sub-questions |
| 4.3.5 | Confidence Check | ~50ms | May trigger re-decomposition |
| 4.3.6 | Coverage Gap Fill | ~100ms | If confidence low |
| 4.4 | Multi-Source Synthesis | ~500ms | Final answer |

**Problem:** Stage 4.2 processes 2-5 sub-questions **sequentially** (2.1s for 3 questions). Could be parallel (~700ms total).

---

## Pain Points Identified

### 1. Sequential Stages That Could Parallelize

**Route 3 — After hub extraction:**
```python
# Current: Sequential (~300ms)
await self._apply_hybrid_rrf_stage(query, graph_context)     # 100ms
await self._apply_section_boost(query, graph_context)        # 100ms
await self._apply_shares_entity_boost(...)                   # 50ms
await self._apply_keyword_boost(...)                         # 50ms

# With Workflows: Parallel (~100ms)
return [HybridRRFEvent(...), SectionBoostEvent(...), KeywordBoostEvent(...)]
```

**Route 4 — Sub-question processing:**
```python
# Current: Sequential (~2.1s for 3 questions)
for sub_q in sub_questions:
    entities = await disambiguator.disambiguate(sub_q)  # 200ms
    evidence = await tracer.trace(sub_q, entities)      # 500ms

# With Workflows: Parallel (~700ms)
@step
async def process_sub_question(self, ev: SubQuestionEvent) -> ResultEvent:
    # All sub-questions run in parallel
```

### 2. Manual Timing Code (11+ Instances)

```python
# Current: Repeated 11+ times in Route 3
t0 = time.perf_counter()
matched_communities = await self.pipeline.community_matcher.match_communities(query)
timings_ms["stage_3.1_ms"] = int((time.perf_counter() - t0) * 1000)

# With Workflows: Automatic via instrumentation
from llama_index.core.instrumentation import get_dispatcher
# All @step executions auto-traced
```

### 3. Scattered Fallback Logic

```python
# Current: Nested try/except in 5+ places
try:
    query_embedding = llm_service.embed_model.get_text_embedding(query)
    chunks = await self._search_chunks_cypher25_hybrid_rrf(...)
except Exception as e:
    logger.warning("hybrid_rrf_embedding_failed", error=str(e))
    chunks = await self._search_chunks_graph_native_bm25(query)

# With Workflows: Structured fallback via events
@step
async def hybrid_rrf(self, ev: HybridRRFEvent) -> Union[ChunksRetrievedEvent, FallbackEvent]:
    try:
        return ChunksRetrievedEvent(chunks=...)
    except EmbeddingUnavailableError:
        return FallbackEvent(strategy="bm25_only")

@step
async def bm25_fallback(self, ev: FallbackEvent) -> ChunksRetrievedEvent:
    return ChunksRetrievedEvent(chunks=await self._bm25_search(...))
```

### 4. Ad-Hoc Confidence Loop (Route 4)

```python
# Current: Complex conditional logic
should_trigger = (
    (confidence < 0.5 and len(sub_questions) > 1) or
    (confidence_metrics["entity_diversity"] < 0.3 and len(sub_questions) > 2) or
    (len(confidence_metrics["concentrated_entities"]) > 0 and confidence < 0.7)
)

# With Workflows: Clean event-driven cycle
@step
async def check_confidence(self, ev: ConfidenceCheckEvent) -> Union[ReDecomposeEvent, SynthesizeEvent]:
    if ev.confidence < 0.5:
        return ReDecomposeEvent(refinement_prompt=...)
    return SynthesizeEvent(results=ev.results)
```

---

## Implementation Plan

### Phase 1: Route 4 DRIFT Workflow (1 week)

**New Files:**
- `app/hybrid/workflows/__init__.py`
- `app/hybrid/workflows/events.py` — Event definitions
- `app/hybrid/workflows/drift_workflow.py` — DRIFT Workflow class

**Events:**
```python
from llama_index.core.workflow import Event

class DecomposeEvent(Event):
    query: str

class SubQuestionEvent(Event):
    sub_question: str
    index: int

class SubQuestionResultEvent(Event):
    question: str
    entities: List[str]
    evidence: List[dict]
    index: int

class ConfidenceCheckEvent(Event):
    results: List[SubQuestionResultEvent]
    confidence: float

class ReDecomposeEvent(Event):
    refinement_prompt: str
    previous_results: List[SubQuestionResultEvent]

class SynthesizeEvent(Event):
    results: List[SubQuestionResultEvent]
```

**Workflow Structure:**
```python
from llama_index.core.workflow import Workflow, step, Context, StartEvent, StopEvent

class DRIFTWorkflow(Workflow):
    def __init__(self, pipeline, llm, **kwargs):
        super().__init__(**kwargs)
        self.pipeline = pipeline
        self.llm = llm

    @step
    async def decompose(self, ctx: Context, ev: StartEvent) -> List[SubQuestionEvent]:
        """Stage 4.1: Decompose query into sub-questions."""
        sub_questions = await self._drift_decompose(ev.query)
        ctx.set("original_query", ev.query)
        ctx.set("num_sub_questions", len(sub_questions))
        return [SubQuestionEvent(sub_question=q, index=i) for i, q in enumerate(sub_questions)]

    @step
    async def process_sub_question(self, ctx: Context, ev: SubQuestionEvent) -> SubQuestionResultEvent:
        """Stage 4.2: Process each sub-question in PARALLEL."""
        entities = await self.pipeline.disambiguator.disambiguate(ev.sub_question)
        evidence = await self.pipeline.tracer.trace(ev.sub_question, entities)
        return SubQuestionResultEvent(
            question=ev.sub_question,
            entities=entities,
            evidence=evidence,
            index=ev.index
        )

    @step
    async def check_confidence(self, ctx: Context, ev: SubQuestionResultEvent) -> Union[ConfidenceCheckEvent, None]:
        """Stage 4.3.5: Collect results and check confidence."""
        results = ctx.collect_events(SubQuestionResultEvent, expected_count=ctx.get("num_sub_questions"))
        if results is None:
            return None  # Wait for more results
        
        confidence = self._compute_confidence(results)
        
        if confidence < 0.5 and not ctx.get("already_redecomposed"):
            ctx.set("already_redecomposed", True)
            return ReDecomposeEvent(refinement_prompt=self._build_refinement_prompt(results))
        
        return SynthesizeEvent(results=results)

    @step
    async def redecompose(self, ctx: Context, ev: ReDecomposeEvent) -> List[SubQuestionEvent]:
        """Stage 4.3.5 (retry): Generate refined sub-questions."""
        refined_questions = await self._drift_decompose(ev.refinement_prompt)
        ctx.set("num_sub_questions", len(refined_questions))
        return [SubQuestionEvent(sub_question=q, index=i) for i, q in enumerate(refined_questions)]

    @step
    async def synthesize(self, ctx: Context, ev: SynthesizeEvent) -> StopEvent:
        """Stage 4.4: Multi-source synthesis."""
        original_query = ctx.get("original_query")
        response = await self._synthesize(original_query, ev.results)
        return StopEvent(result=response)
```

**Integration Point:**
```python
# In search_pipeline_stages.py, replace _execute_route4_drift() body:
async def _execute_route4_drift(self, query: str, response_type: str) -> RouteResult:
    workflow = DRIFTWorkflow(pipeline=self.pipeline, llm=self.llm, timeout=60)
    result = await workflow.run(query=query)
    return RouteResult(route=4, answer=result, ...)
```

---

### Phase 2: Route 3 Global Search Workflow (2 weeks)

**New File:**
- `app/hybrid/workflows/global_workflow.py`

**Additional Events:**
```python
class CommunityMatchedEvent(Event):
    communities: List[dict]
    query: str

class HubsExtractedEvent(Event):
    hub_entities: List[str]
    query: str

class HybridRRFEvent(Event):
    query: str
    hub_entities: List[str]

class SectionBoostEvent(Event):
    query: str
    hub_entities: List[str]

class KeywordBoostEvent(Event):
    query: str
    hub_entities: List[str]

class SharesEntityEvent(Event):
    query: str
    hub_entities: List[str]

class ChunksRetrievedEvent(Event):
    chunks: List[dict]
    source: str  # "hybrid_rrf", "section_boost", etc.

class FallbackEvent(Event):
    strategy: str
    query: str

class MergeChunksEvent(Event):
    all_chunks: List[ChunksRetrievedEvent]

class PPRTraceEvent(Event):
    query: str
    merged_chunks: List[dict]

class CoverageGapEvent(Event):
    query: str
    current_chunks: List[dict]
    coverage_score: float
```

**Workflow Structure:**
```python
class GlobalSearchWorkflow(Workflow):
    @step
    async def match_communities(self, ctx: Context, ev: StartEvent) -> CommunityMatchedEvent:
        """Stage 3.1: Community matching."""
        communities = await self.pipeline.community_matcher.match_communities(ev.query)
        return CommunityMatchedEvent(communities=communities, query=ev.query)

    @step
    async def extract_hubs(self, ctx: Context, ev: CommunityMatchedEvent) -> List[Event]:
        """Stage 3.2: Extract hub entities, then fan-out to parallel retrieval."""
        hubs = await self.pipeline.hub_extractor.extract_hub_entities(ev.communities)
        ctx.set("hub_entities", hubs)
        ctx.set("query", ev.query)
        
        # Fan-out: 4 parallel retrieval stages
        return [
            HybridRRFEvent(query=ev.query, hub_entities=hubs),
            SectionBoostEvent(query=ev.query, hub_entities=hubs),
            KeywordBoostEvent(query=ev.query, hub_entities=hubs),
            SharesEntityEvent(query=ev.query, hub_entities=hubs),
        ]

    @step
    async def hybrid_rrf(self, ctx: Context, ev: HybridRRFEvent) -> Union[ChunksRetrievedEvent, FallbackEvent]:
        """Stage 3.3.5: Hybrid RRF retrieval with fallback."""
        try:
            chunks = await self.pipeline._search_chunks_cypher25_hybrid_rrf(ev.query, ev.hub_entities)
            return ChunksRetrievedEvent(chunks=chunks, source="hybrid_rrf")
        except Exception:
            return FallbackEvent(strategy="bm25_only", query=ev.query)

    @step
    async def section_boost(self, ctx: Context, ev: SectionBoostEvent) -> ChunksRetrievedEvent:
        """Section semantic boost (parallel with hybrid_rrf)."""
        chunks = await self.pipeline._apply_section_boost(ev.query, ev.hub_entities)
        return ChunksRetrievedEvent(chunks=chunks, source="section_boost")

    @step
    async def keyword_boost(self, ctx: Context, ev: KeywordBoostEvent) -> ChunksRetrievedEvent:
        """Keyword boost (parallel)."""
        chunks = await self.pipeline._apply_keyword_boost(ev.query, ev.hub_entities)
        return ChunksRetrievedEvent(chunks=chunks, source="keyword_boost")

    @step
    async def shares_entity_boost(self, ctx: Context, ev: SharesEntityEvent) -> ChunksRetrievedEvent:
        """Cross-document entity expansion (parallel)."""
        chunks = await self.pipeline._apply_shares_entity_boost(ev.query, ev.hub_entities)
        return ChunksRetrievedEvent(chunks=chunks, source="shares_entity")

    @step
    async def bm25_fallback(self, ctx: Context, ev: FallbackEvent) -> ChunksRetrievedEvent:
        """Fallback handler for embedding failures."""
        chunks = await self.pipeline._search_chunks_graph_native_bm25(ev.query)
        return ChunksRetrievedEvent(chunks=chunks, source="bm25_fallback")

    @step
    async def merge_chunks(self, ctx: Context, ev: ChunksRetrievedEvent) -> Union[PPRTraceEvent, None]:
        """Collect all retrieval results and merge."""
        all_results = ctx.collect_events(ChunksRetrievedEvent, expected_count=4)
        if all_results is None:
            return None
        
        merged = self._deduplicate_and_rank(all_results)
        return PPRTraceEvent(query=ctx.get("query"), merged_chunks=merged)

    @step
    async def ppr_trace(self, ctx: Context, ev: PPRTraceEvent) -> CoverageGapEvent:
        """Stage 3.4: HippoRAG PPR tracing."""
        enhanced = await self.pipeline.ppr_tracer.trace(ev.query, ev.merged_chunks)
        coverage = self._compute_coverage(enhanced)
        return CoverageGapEvent(query=ev.query, current_chunks=enhanced, coverage_score=coverage)

    @step
    async def coverage_gap_fill(self, ctx: Context, ev: CoverageGapEvent) -> SynthesizeEvent:
        """Stage 3.4.1: Fill coverage gaps if needed."""
        if ev.coverage_score < 0.7:
            additional = await self.pipeline._fill_coverage_gaps(ev.query, ev.current_chunks)
            final_chunks = ev.current_chunks + additional
        else:
            final_chunks = ev.current_chunks
        return SynthesizeEvent(chunks=final_chunks)

    @step
    async def synthesize(self, ctx: Context, ev: SynthesizeEvent) -> StopEvent:
        """Stage 3.5: Final synthesis with citations."""
        response = await self.pipeline.synthesizer.synthesize(ctx.get("query"), ev.chunks)
        return StopEvent(result=response)
```

---

## Expected Benefits

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **Route 4 latency** (3 sub-questions) | ~2.1s | ~0.7s | **3x faster** |
| **Route 3 retrieval stages** | ~400ms | ~150ms | **2.7x faster** |
| **Manual timing code** | 15+ instances | 0 (auto) | Cleaner codebase |
| **Fallback logic** | 5 nested try/except | 5 event handlers | Testable, visible |
| **Observability** | structlog only | LlamaIndex traces | Full step visibility |

---

## Testing Strategy

### Unit Tests for Workflows

**File:** `tests/test_drift_workflow.py`
```python
import pytest
from unittest.mock import AsyncMock
from app.hybrid.workflows.drift_workflow import DRIFTWorkflow

@pytest.mark.asyncio
async def test_drift_workflow_parallel_sub_questions():
    """Verify sub-questions are processed in parallel."""
    mock_pipeline = AsyncMock()
    mock_pipeline.disambiguator.disambiguate.return_value = ["Entity1"]
    mock_pipeline.tracer.trace.return_value = [{"chunk": "evidence"}]
    
    workflow = DRIFTWorkflow(pipeline=mock_pipeline, llm=AsyncMock(), timeout=30)
    result = await workflow.run(query="How does A affect B through C?")
    
    # Verify parallel execution (all sub-questions should complete ~same time)
    assert result is not None

@pytest.mark.asyncio
async def test_drift_workflow_redecompose_on_low_confidence():
    """Verify re-decomposition triggers when confidence < 0.5."""
    # ... test confidence loop
```

**File:** `tests/test_global_workflow.py`
```python
@pytest.mark.asyncio
async def test_global_workflow_parallel_retrieval():
    """Verify 4 retrieval stages run in parallel."""
    # ... test fan-out behavior

@pytest.mark.asyncio
async def test_global_workflow_fallback_on_embedding_failure():
    """Verify BM25 fallback when embedding fails."""
    # ... test FallbackEvent handling
```

---

## Rollback Plan

1. **Feature flag:** `USE_WORKFLOW_ROUTES` in environment/config
   ```python
   if os.getenv("USE_WORKFLOW_ROUTES", "false").lower() == "true":
       result = await DRIFTWorkflow(...).run(query)
   else:
       result = await self._execute_route4_drift_legacy(query)
   ```

2. **Keep legacy methods** with `_legacy` suffix for 2 weeks post-migration

3. **Monitoring:** Compare latency metrics between workflow and legacy paths

---

## Dependencies

**Already installed** (no new packages needed):
```
llama-index-core==0.14.12  # Includes llama-index-workflows
```

**Imports needed:**
```python
from llama_index.core.workflow import Workflow, Event, StartEvent, StopEvent, step, Context
from llama_index.core.instrumentation import get_dispatcher
```

---

## Timeline

| Phase | Scope | Duration | Dependencies |
|-------|-------|----------|--------------|
| **Pre-req** | Complete router accuracy testing | 1-2 days | This plan |
| **Phase 1** | Route 4 DRIFT Workflow | 1 week | Pre-req complete |
| **Phase 2** | Route 3 Global Workflow | 2 weeks | Phase 1 validated |
| **Phase 3** | Remove legacy code | 1 week | 2 weeks stable operation |

---

## References

- [LlamaIndex Workflows Documentation](https://docs.llamaindex.ai/en/stable/module_guides/workflow/)
- Current router: `graphrag-orchestration/app/hybrid/router/main.py`
- Current orchestrator: `graphrag-orchestration/app/hybrid/search_pipeline_stages.py`
- Router test plan: `ROUTER_EFFECTIVENESS_TEST_PLAN_2026-01-23.md`
