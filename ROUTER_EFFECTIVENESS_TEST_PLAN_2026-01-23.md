# Router Effectiveness Testing Plan

**Date:** January 23, 2026

## Overview

Validate the query router's accuracy against ground truth and identify tuning opportunities. The router uses a hybrid heuristic+LLM approach with complexity/ambiguity scoring, but has never been validated end-to-end against real-world queries.

## Background

### Current State

The GraphRAG orchestration system uses an automatic router to classify queries into one of four routes:

| Route | Purpose | Use Case |
|-------|---------|----------|
| Route 1 (Vector) | Simple factual lookup | Single document can answer |
| Route 2 (Local) | Entity-focused search | Needs graph traversal for specific entities |
| Route 3 (Global) | Dataset-wide analysis | Requires understanding corpus as a whole |
| Route 4 (DRIFT) | Complex multi-hop reasoning | Needs query decomposition and iterative search |

### Routing Decision Logic

**File:** `app/hybrid/router/main.py`

The router uses a **hybrid heuristic + optional LLM** approach:

1. **Complexity Assessment** (0.0-1.0):
   - Heuristic-based keyword scoring
   - Optional LLM refinement for borderline cases (0.3-0.7)

2. **Ambiguity Assessment** (0.0-1.0):
   - Keyword-based: vague references increase score
   - Entity detection: proper nouns, quotes, IDs decrease score

3. **Combined Score**:
   ```python
   combined_score = (complexity * 0.6) + (ambiguity * 0.4)
   ```

4. **Route Selection**:
   - `< 0.25` (vector_threshold) → Route 1 (Vector)
   - `> 0.75` (drift_threshold) → Route 4 (DRIFT)
   - `< 0.5` → Route 2 (Local)
   - Otherwise → Route 3 (Global)

5. **Profile Constraints**:
   - High Assurance Profile: Route 1 → Route 2 (disables vector)
   - General Enterprise: All routes enabled

### Testing Gaps Identified

| Gap | Impact |
|-----|--------|
| No ground truth route assignments | Can't measure accuracy |
| Unit tests don't invoke `Router.classify()` | Only test keyword patterns, not actual routing |
| No threshold boundary tests | Behavior at 0.24 vs 0.25 vs 0.26 undefined |
| Route 2 vs Route 3 distinction unclear | Question bank treats them as equivalent |
| LLM-assisted path never tested | Can't compare heuristic-only vs LLM accuracy |
| No accuracy metrics | Don't know if router is reliable |

### Microsoft GraphRAG Approach

**Key Finding:** Microsoft GraphRAG **does NOT have automatic routing**. Users explicitly choose `local`, `global`, `drift`, or `basic` via CLI or separate API functions.

**Their guidance:**
- Local Search: For questions about **specific entities**
- Global Search: For questions requiring **dataset-wide understanding**

They leave the choice to the user — no automatic classification.

## Implementation Steps

### Step 1: Define Route Ground Truth

**File:** `docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md`

Add explicit expected route assignment to each question:

```markdown
## Section A: Vector RAG Questions (Q-V*)
**Expected Route:** Route 1 (Vector RAG)

### Q-V1: [Question text]
**Expected Answer:** ...
**Expected Route:** Route 1 (Vector RAG)

## Section B: Local Search Questions (Q-L*)
**Expected Route:** Route 2 (Local Search)

### Q-L1: [Question text]
**Expected Answer:** ...
**Expected Route:** Route 2 (Local Search)

## Section C: Global Search Questions (Q-G*)
**Expected Route:** Route 3 (Global Search)

### Q-G1: [Question text]
**Expected Answer:** ...
**Expected Route:** Route 3 (Global Search)

## Section D: DRIFT Multi-Hop Questions (Q-D*)
**Expected Route:** Route 4 (DRIFT)

### Q-D1: [Question text]
**Expected Answer:** ...
**Expected Route:** Route 4 (DRIFT)

## Section N: Negative Test Cases (Q-N*)
**Expected Route:** Route 2 (Local Search)
**Expected Behavior:** Should trigger negative detection
```

**Deliverable:** Every question has explicit expected route

---

### Step 2: Create Router Accuracy Script

**File:** `scripts/evaluate_router_accuracy.py` (new)

Build evaluation script that:

```python
# Pseudocode structure
def evaluate_router_accuracy():
    # Load question bank with expected routes
    questions = load_question_bank("QUESTION_BANK_5PDFS_2025-12-24.md")
    
    # Initialize router
    router = Router(profile=QueryProfile.GENERAL_ENTERPRISE)
    
    # Test each question
    results = []
    for q in questions:
        actual_route = router.classify(q.text)
        expected_route = q.expected_route
        correct = (actual_route == expected_route)
        results.append({
            "qid": q.id,
            "question": q.text,
            "expected": expected_route,
            "actual": actual_route,
            "correct": correct,
            "complexity_score": router.last_complexity,
            "ambiguity_score": router.last_ambiguity,
            "combined_score": router.last_combined_score
        })
    
    # Calculate metrics
    accuracy = sum(r["correct"] for r in results) / len(results)
    confusion_matrix = build_confusion_matrix(results)
    per_route_metrics = calculate_precision_recall(results)
    
    # Report
    print(f"Overall Accuracy: {accuracy:.2%}")
    print(f"Confusion Matrix:\n{confusion_matrix}")
    print(f"Per-Route Metrics:\n{per_route_metrics}")
    
    # Save detailed results
    save_json(results, "router_accuracy_results.json")
```

**Metrics to compute:**
- Overall accuracy (correct/total)
- Confusion matrix (expected vs actual routes)
- Per-route precision and recall
- Threshold sensitivity (questions near 0.25 and 0.75)

**Deliverable:** Comprehensive router accuracy report

---

### Step 3: Add Real Router Invocation Tests

**File:** `tests/test_router.py`

**Current Problem:**
Existing unit tests only check keyword patterns in example strings. They never call `Router.classify()`.

**Fix:**
```python
import pytest
from app.hybrid.router.main import Router, QueryProfile, RouteEnum

@pytest.mark.parametrize("query,expected_route", [
    ("What is the address of Acme Corp?", RouteEnum.VECTOR_RAG),
    ("List all contracts with Fabrikam", RouteEnum.LOCAL_SEARCH),
    ("What are the main themes across all documents?", RouteEnum.GLOBAL_SEARCH),
    ("Trace the relationship between Entity A and Entity B through intermediaries", RouteEnum.DRIFT),
])
def test_router_classify_real_invocation(query, expected_route):
    """Test router actually classifies queries correctly."""
    router = Router(profile=QueryProfile.GENERAL_ENTERPRISE)
    result = router.classify(query)
    assert result == expected_route, f"Expected {expected_route}, got {result}"

def test_router_question_bank_coverage():
    """Test router against full question bank."""
    questions = load_question_bank()  # Helper function
    router = Router(profile=QueryProfile.GENERAL_ENTERPRISE)
    
    correct = 0
    for q in questions:
        actual = router.classify(q.text)
        if actual == q.expected_route:
            correct += 1
    
    accuracy = correct / len(questions)
    assert accuracy >= 0.85, f"Router accuracy {accuracy:.2%} below 85% threshold"
```

**Deliverable:** Unit tests validate actual routing behavior

---

### Step 4: Test Threshold Boundaries

**File:** `tests/test_router.py`

Add tests for edge cases around routing thresholds:

```python
def test_vector_threshold_boundary():
    """Test routing behavior near vector_threshold (0.25)."""
    router = Router(profile=QueryProfile.GENERAL_ENTERPRISE)
    
    # Craft queries with known complexity scores
    just_below = "What is X?"  # Expect complexity ~0.20
    right_at = "What is the purpose of X?"  # Expect complexity ~0.25
    just_above = "What is the relationship of X?"  # Expect complexity ~0.30
    
    assert router.classify(just_below) == RouteEnum.VECTOR_RAG
    # Borderline cases may vary, document behavior
    route_at = router.classify(right_at)
    assert route_at in [RouteEnum.VECTOR_RAG, RouteEnum.LOCAL_SEARCH]
    assert router.classify(just_above) != RouteEnum.VECTOR_RAG

def test_drift_threshold_boundary():
    """Test routing behavior near drift_threshold (0.75)."""
    router = Router(profile=QueryProfile.GENERAL_ENTERPRISE)
    
    # Multi-hop keywords should push complexity high
    just_below = "How are A and B related?"  # Expect ~0.70
    just_above = "Trace the chain of relationships from A to B through intermediaries"  # Expect ~0.80
    
    assert router.classify(just_below) in [RouteEnum.LOCAL_SEARCH, RouteEnum.GLOBAL_SEARCH]
    assert router.classify(just_above) == RouteEnum.DRIFT
```

**Deliverable:** Threshold behavior documented and tested

---

### Step 5: Clarify Route 2 vs Route 3 Criteria

**Problem:** 
Current question bank treats sections B (Local) and C (Global) as "Local/Global equivalent". No clear distinction.

**Decision Required:**

| Criteria | Route 2 (Local) | Route 3 (Global) |
|----------|----------------|------------------|
| Entity specificity | Query mentions specific entities | Query is entity-agnostic |
| Scope | Single entity or small entity set | Cross-document themes/patterns |
| Example | "List all contracts with Acme Corp" | "What are the main risk factors across all contracts?" |

**Action:**
1. Review question bank sections B and C
2. Re-classify ambiguous questions
3. Document the distinction in `app/hybrid/router/README.md`

**Deliverable:** Clear criteria for Route 2 vs Route 3

---

### Step 6: Tune Thresholds (if needed)

**Current Thresholds:**
- `vector_threshold = 0.25`
- `drift_threshold = 0.75`

**Tuning Process:**
1. Run router accuracy script (Step 2)
2. Analyze misrouted questions
3. Identify patterns:
   - Are simple questions being over-routed to Local?
   - Are complex questions being under-routed to DRIFT?
4. Adjust thresholds incrementally (±0.05)
5. Re-run accuracy test
6. Target: ≥90% accuracy

**Example Adjustment:**
```python
# If too many simple queries go to Local instead of Vector
vector_threshold = 0.30  # Raised from 0.25

# If complex queries don't reach DRIFT
drift_threshold = 0.70  # Lowered from 0.75
```

**Deliverable:** Optimized routing thresholds

---

## Further Considerations

### 1. LLM-Assisted Routing

**Current State:**
- Heuristic-based routing is default
- LLM refinement only for borderline cases (0.3 < score < 0.7)
- Tests never exercise the LLM path

**Questions:**
- Should we benchmark heuristics-only vs LLM-assisted accuracy?
- Does LLM improve borderline cases enough to justify latency?
- Should LLM be enabled by default or opt-in?

**Recommendation:** 
Measure accuracy both ways. If LLM adds <5% accuracy but adds 500ms latency, keep heuristics-only as default.

---

### 2. Acceptable Accuracy Target

**Industry Standards:**
- Intent classification systems: 85-95% accuracy
- Search query routing: 80-90% accuracy

**Recommendation:**
- **Minimum threshold:** 85% overall accuracy
- **Target:** 90% overall accuracy
- **Per-route:** No route should have <80% precision

**Rationale:**
Misrouting degrades answer quality. A simple query routed to DRIFT wastes 25s of retrieval time. A complex query routed to Vector produces incomplete answers.

---

### 3. Route 2 ↔ Route 3 Tolerance

**Question:** 
If router picks Route 2 but ground truth is Route 3 (or vice versa), is this a "hard" error or "soft" error?

**Consideration:**
Both Route 2 and Route 3 use graph context and can produce quality answers. The difference is:
- Route 2: Focused on specific entity neighborhoods
- Route 3: Aggregates community-level summaries

**Recommendation:**
- Count Route 2 ↔ Route 3 swaps as **soft errors** (0.5 penalty instead of 1.0)
- Focus tuning on preventing Vector ↔ DRIFT misroutes (hard errors)

**Adjusted Accuracy Metric:**
```python
def calculate_accuracy_with_soft_errors(results):
    correct = 0
    for r in results:
        if r["expected"] == r["actual"]:
            correct += 1.0  # Perfect match
        elif {r["expected"], r["actual"]} <= {RouteEnum.LOCAL_SEARCH, RouteEnum.GLOBAL_SEARCH}:
            correct += 0.5  # Soft error (both use graph)
        # else: hard error, no credit
    return correct / len(results)
```

---

### 4. Profile-Specific Accuracy

**Question:**
Should we measure accuracy separately for High Assurance vs General Enterprise profiles?

**Consideration:**
High Assurance profile forces Route 1 → Route 2 (disables Vector RAG). This affects routing decisions.

**Recommendation:**
- Test both profiles separately
- High Assurance profile expected to have lower accuracy (forced fallback)
- Report accuracy per profile in evaluation script

**Expected Accuracy:**
- General Enterprise: ≥90%
- High Assurance: ≥85% (accepts Route 1 → Route 2 as correct)

---

### 5. Multi-Language Query Routing

**Question:**
How does the router handle non-English queries?

**Current State:**
Router uses English keywords (`"connected to"`, `"relationship between"`, `"analyze"`, etc.) for complexity/ambiguity scoring.

**Impact:**
- Chinese query: `"分析A和B的关系"` (Analyze relationship between A and B)
  - Complexity keywords won't match
  - May be incorrectly routed to Vector instead of Local/DRIFT

**Recommendation:**
- Defer to Multi-Language Support Plan (Phase 2)
- Consider language-agnostic signals (query length, punctuation patterns)
- Or use LLM for complexity assessment (language-agnostic)

---

## Success Metrics

### Router Accuracy
- **Overall accuracy:** ≥90% (with soft error tolerance for Route 2 ↔ Route 3)
- **Per-route precision:** ≥80% for each route
- **Threshold boundary behavior:** Documented and predictable

### Test Coverage
- **Unit tests:** Exercise real `Router.classify()` invocation
- **Integration tests:** Cover full question bank (19 queries)
- **Boundary tests:** Test edge cases at 0.24, 0.25, 0.26 and 0.74, 0.75, 0.76
- **Profile tests:** Validate High Assurance and General Enterprise separately

### Performance
- **Heuristic-based routing:** <50ms per query
- **LLM-assisted routing:** <500ms per query (borderline cases only)
- **No regressions:** Route quality maintained after threshold tuning

---

## Implementation Timeline

| Phase | Steps | Estimated Effort |
|-------|-------|-----------------|
| Phase 1: Ground Truth | Step 1 | 2 hours |
| Phase 2: Accuracy Testing | Steps 2-3 | 1 day |
| Phase 3: Boundary Testing | Step 4 | 4 hours |
| Phase 4: Criteria Refinement | Step 5 | 4 hours |
| Phase 5: Threshold Tuning | Step 6 | 4 hours |
| **Total** | | **2-3 days** |

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Ground truth assignments subjective | Review with domain expert; accept some ambiguity |
| Low initial accuracy (<85%) | Adjust thresholds; consider simplifying to 2-way routing |
| Route 2 vs Route 3 distinction unclear | Document as "soft error" in accuracy metric |
| LLM-assisted path adds latency | Keep heuristics-only as default; LLM opt-in only |
| Multi-language queries fail | Defer to Multi-Language Support Plan; document limitation |

---

## Appendix: Code Locations Reference

| Component | File | Lines |
|-----------|------|-------|
| Router Main Logic | `app/hybrid/router/main.py` | 1-500 |
| Route Classification | `app/hybrid/router/main.py` | 302-316 |
| Complexity Assessment | `app/hybrid/router/main.py` | 150-250 |
| Ambiguity Assessment | `app/hybrid/router/main.py` | 250-300 |
| Profile Constraints | `app/hybrid/router/main.py` | 316-330 |
| Unit Tests | `tests/test_router.py` | 1-311 |
| Question Bank Tests | `tests/test_router_question_bank.py` | 1-163 |
| Question Bank | `docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md` | Full file |

---

## Comparison: Microsoft GraphRAG vs Our Approach

| Aspect | Microsoft GraphRAG | Our Implementation |
|--------|-------------------|-------------------|
| Routing Strategy | **Manual** — User explicitly chooses local/global/drift/basic via CLI/API | **Automatic** — Router classifies queries using heuristics + optional LLM |
| User Experience | User must understand GraphRAG concepts | Single endpoint, transparent routing |
| Misroute Risk | Zero (user chooses) | Depends on router accuracy (target: 90%) |
| Implementation | Separate API functions per route | Unified `search_hybrid` endpoint with `force_route` override |
| Testing | No router to test | Requires comprehensive accuracy testing |

**Our Advantage:** Better UX — users don't need to understand routing internals.

**Our Challenge:** Must achieve ≥90% routing accuracy to avoid degrading answer quality.
