# Prompt Improvement: DRIFT Synthesis Verbosity Issue

**Date:** February 5, 2026  
**Discovered During:** Route 4 LLM evaluation (GPT-5.1 judge)  
**Impact:** Minor - 1 question (Q-D5) scored 2/3 instead of 3/3 due to excessive verbosity  
**Status:** Documented for future refinement

---

## Issue Summary

Route 4 (DRIFT Multi-Hop) synthesis produces overly comprehensive answers that include tangentially-related information not requested in the original query. While factually correct, the verbosity reduces response quality for focused questions.

**Benchmark Results:**
- Overall Score: 32/33 (97.0%)
- Pass Rate: 100% (all ≥2/3)
- Affected Question: Q-D5 (scored 2/3 - "acceptable but verbose")

---

## Q-D5 Case Study: What Happened in Detail

### The Question
```
In the warranty, explain how the "coverage start" is defined and 
what must happen before coverage ends.
```

### Expected Answer
**Length:** ~150 characters  
**Content:**
> Coverage begins on date of final settlement or first occupancy (whichever first); 
> claims must be made in writing within the 1-year or 60-day period.

### Actual Answer
**Length:** 5,655 characters (37x expected)  
**Structure:**
- **Section 1:** "How 'coverage start' is defined" ✅ (in scope)
- **Section 2:** "What must happen before coverage ends" ✅ (in scope)
- **Section 3:** "Automatic termination upon sale/move-out" ❌ (not requested)
- **Section 4:** "Exclusions that function as practical limits" ❌ (not requested)
- **"Key Connections" section** - ties unrelated concepts together
- **"Conclusion" section** - comprehensive legal analysis

### What Was Included Beyond Scope
1. **Non-transferability clause:** Warranty terminates if first purchaser sells or moves out
2. **Exclusions:** Wear and tear, manufacturer warranties, acts of God, insect damage
3. **Emergency notification:** Failure to notify relieves builder of liability
4. **Legal formatting:** Multiple numbered sections with detailed citations【10†L2-L2】

### Judge's Assessment
> "The answer correctly explains that coverage starts on the earlier of final settlement 
> or first occupancy and that claims must be made in writing within the 1‑year or 60‑day 
> period, matching the core ground truth. **However, it adds extra termination conditions 
> (sale/move‑out, exclusions, emergencies) that go beyond what the user asked**. While not 
> directly contradictory, this additional material is **unnecessary and could be seen as 
> partially off‑scope**, so it is acceptable but not perfect."

**Score:** 2/3 (Acceptable / Minor Issues)

---

## Root Cause Analysis: How This Was Identified as a Prompt Issue

### Investigation Path

1. **Initial Discovery:** LLM evaluation flagged Q-D5 for verbosity (2/3 score)
2. **Answer Review:** Extracted actual answer - 5,655 chars with 4 sections + connections + conclusion
3. **Hypothesis:** Either retrieval over-fetched OR synthesis over-synthesized
4. **Code Review:** Examined Route 4 flow:
   - Query decomposition → Sub-questions
   - Entity discovery → Tracing
   - Evidence consolidation
   - **Synthesis** ← Identified as likely culprit

5. **Prompt Analysis:** Found `_get_drift_synthesis_prompt()` in `src/worker/hybrid_v2/pipeline/synthesis.py`

### Smoking Gun: The Synthesis Prompt

**File:** `src/worker/hybrid_v2/pipeline/synthesis.py` (lines 811-850)

```python
def _get_drift_synthesis_prompt(
    self, 
    query: str, 
    context: str,
    sub_questions: List[str]
) -> str:
    """Prompt for DRIFT-style multi-question synthesis."""
    sub_q_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(sub_questions))
    
    return f"""You are analyzing a complex query that was decomposed into multiple sub-questions.

Original Query: {query}

Sub-questions explored:
{sub_q_list}

Evidence Context (with citation markers):
{context}

Instructions:
1. Synthesize findings from ALL sub-questions into a coherent analysis
2. Show how the answers connect to address the original query
3. EVERY factual claim must include a citation [n] to the evidence
4. Structure your response to follow the logical flow of the sub-questions
5. Include a final synthesis section that ties everything together

Format:
## Analysis

[Your comprehensive analysis addressing each sub-question]

## Key Connections

[How the findings relate to each other]

## Conclusion

[Final answer to the original query]

Your response:"""
```

### Problematic Phrases

| Phrase | Effect | Example from Q-D5 |
|--------|--------|-------------------|
| **"ALL sub-questions"** | Forces inclusion of tangential sub-questions | Included "termination conditions" even though user only asked about "coverage start/end" |
| **"comprehensive analysis"** | Explicitly requests thoroughness over conciseness | 5,655 chars instead of ~150 chars |
| **"Show how the answers connect"** | Encourages synthesis of unrelated information | Created "Key Connections" section linking exclusions to coverage periods |
| **"ties everything together"** | Asks for holistic view even when unnecessary | Added "Conclusion" section with full legal analysis |
| **3-section structure** | Fixed format adds overhead | "Analysis" + "Key Connections" + "Conclusion" = 3x baseline |

### What Likely Happened with Q-D5

**Hypothesized Sub-Question Decomposition:**
1. ✅ "How is 'coverage start' defined in the warranty?" (in scope)
2. ✅ "What are the time limits for making claims?" (in scope)
3. ❌ "What conditions cause the warranty to terminate early?" (related but NOT asked)
4. ❌ "What exclusions apply to warranty coverage?" (related but NOT asked)

**Synthesis Flow:**
1. Sub-question 1 → Answer: "Coverage starts on earlier of final settlement or first occupancy"
2. Sub-question 2 → Answer: "Claims must be made in writing within 1-year or 60-day period"
3. Sub-question 3 → Answer: "Warranty terminates if property sold or owner moves out" ❌
4. Sub-question 4 → Answer: "Exclusions include wear/tear, acts of God, emergencies" ❌
5. Synthesis: **"Synthesize findings from ALL sub-questions"** → LLM includes 3 & 4
6. Formatting: **"comprehensive analysis"** → LLM adds 4 sections + detailed citations

**Result:** Correct answer buried in 5,655 characters of related but unrequested information.

---

## Comparison with Other Response Types

The issue is specific to the **DRIFT synthesis prompt**. Other prompts have better scoping:

### Summary Prompt (`_get_summary_prompt`)
```python
Instructions:
1. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence
2. ONLY if the EXACT requested information IS present: provide a brief summary (2-3 paragraphs)
3. **RESPECT ALL QUALIFIERS** in the question
4. Include citations [N] for factual claims
```
✅ Includes "brief summary (2-3 paragraphs)" constraint  
✅ Emphasizes "EXACT requested information"  
✅ No fixed multi-section structure

### Detailed Report Prompt (`_get_detailed_report_prompt`)
```python
Instructions:
1. First, carefully evaluate if the Evidence Context contains the SPECIFIC information requested
2. **REFUSE TO ANSWER** if the EXACT requested information is NOT in the evidence
3. Do NOT be "helpful" by providing alternative/related information when the specific item is missing
4. ONLY if the EXACT requested information IS present: cite sources [N] for EVERY claim
```
✅ Has anti-hallucination guidance  
✅ Warns against being "helpful" with alternative information  
❌ But still allows comprehensive answers (intended for detailed mode)

### DRIFT Synthesis Prompt (Current Issue)
```python
Instructions:
1. Synthesize findings from ALL sub-questions into a coherent analysis
2. Show how the answers connect to address the original query
3. EVERY factual claim must include a citation [n] to the evidence
4. Structure your response to follow the logical flow of the sub-questions
5. Include a final synthesis section that ties everything together
```
❌ No brevity constraint  
❌ No scoping guidance ("answer ONLY what was asked")  
❌ Encourages comprehensive coverage of ALL sub-questions  
❌ Fixed 3-section structure adds bulk

---

## Possible Improvements

### Option 1: Response-Type-Aware DRIFT Synthesis ⭐ Recommended

Adjust verbosity based on `response_type`:

```python
def _get_drift_synthesis_prompt(
    self, 
    query: str, 
    context: str,
    sub_questions: List[str],
    response_type: str = "summary"  # NEW PARAMETER
) -> str:
    """Prompt for DRIFT-style multi-question synthesis."""
    sub_q_list = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(sub_questions))
    
    # Adjust instructions based on response type
    if response_type == "summary":
        format_instruction = """Provide a concise response (2-3 paragraphs maximum) that:
- Directly answers the original query
- Focuses ONLY on information requested in the original query
- Omits tangentially-related information not explicitly asked for
- Includes citations [n] for key claims"""
        
    elif response_type == "detailed_report":
        format_instruction = """Generate a comprehensive analysis that:
- Addresses each sub-question in depth
- Shows connections between findings
- Includes citations [n] for every factual claim
- Uses clear section headings for organization"""
        
    else:  # audit_trail, comprehensive, etc.
        format_instruction = """Generate a thorough response with:
- Complete coverage of all sub-questions
- Logical connections between findings
- Citations [n] for all claims
- Structured format with sections"""
    
    return f"""You are analyzing a complex query that was decomposed into multiple sub-questions.

Original Query: {query}

Sub-questions explored:
{sub_q_list}

Evidence Context (with citation markers):
{context}

{format_instruction}

Your response:"""
```

**Benefits:**
- Preserves comprehensive mode for `detailed_report`
- Adds conciseness constraint for `summary`
- Maintains flexibility for other response types

**Tradeoffs:**
- Requires passing `response_type` through call chain
- Need to test all response types to ensure no regression

---

### Option 2: Sub-Question Relevance Filtering

Filter sub-questions before synthesis to only include directly relevant ones:

```python
async def _filter_relevant_subquestions(
    self, 
    original_query: str, 
    sub_questions: List[str]
) -> List[str]:
    """Filter sub-questions to only those directly addressing the original query."""
    if not self.llm or len(sub_questions) <= 2:
        return sub_questions  # Don't filter if already minimal
    
    prompt = f"""Original Query: "{original_query}"

Sub-questions:
{chr(10).join(f"{i+1}. {q}" for i, q in enumerate(sub_questions))}

Which sub-questions are DIRECTLY required to answer the original query?
Mark each as:
- REQUIRED: Directly answers part of the query
- OPTIONAL: Provides related context but not explicitly requested

Output format:
1. REQUIRED/OPTIONAL
2. REQUIRED/OPTIONAL
..."""
    
    response = await self.llm.acomplete(prompt)
    # Parse response and filter sub_questions
    # ...
    return filtered_sub_questions
```

**Benefits:**
- Prevents synthesis of tangential sub-questions
- No prompt changes needed

**Tradeoffs:**
- Additional LLM call (latency + cost)
- Risk of filtering useful context
- Adds complexity to Route 4 flow

---

### Option 3: Prompt Refinement (Simple Text Changes)

Minimal change to existing DRIFT synthesis prompt:

**Current:**
```python
Instructions:
1. Synthesize findings from ALL sub-questions into a coherent analysis
2. Show how the answers connect to address the original query
```

**Improved:**
```python
Instructions:
1. Answer the original query directly and concisely
2. Focus ONLY on information explicitly requested in the original query
3. Synthesize findings from relevant sub-questions
4. Omit tangentially-related information (exclusions, alternative scenarios, etc.) unless directly asked
```

**Benefits:**
- Minimal code change
- No API change (no new parameters)
- Explicit guidance against over-synthesis

**Tradeoffs:**
- May need multiple iterations to tune wording
- Less flexible than Option 1

---

### Option 4: Post-Processing Filter

Add LLM-based relevance filter AFTER synthesis:

```python
async def _trim_verbose_response(
    self, 
    query: str, 
    response: str, 
    max_length: int = 1000
) -> str:
    """Trim verbose responses to focus on query-relevant content."""
    if len(response) < max_length:
        return response
    
    prompt = f"""Original Query: "{query}"

Response (verbose):
{response}

Extract ONLY the content that directly answers the original query.
Omit:
- Related but unrequested information
- Tangential context
- Detailed legal analysis beyond what was asked

Concise Answer:"""
    
    trimmed = await self.llm.acomplete(prompt)
    return trimmed.text.strip()
```

**Benefits:**
- Non-invasive (doesn't change synthesis prompt)
- Can be enabled/disabled via feature flag

**Tradeoffs:**
- Additional LLM call (doubles synthesis cost)
- Risk of removing useful information
- Adds latency

---

## Recommendation

**Primary:** **Option 1 - Response-Type-Aware DRIFT Synthesis** ⭐

**Rationale:**
1. **Surgical fix:** Only affects `summary` mode, preserves `detailed_report` behavior
2. **No extra LLM calls:** Single prompt adjustment, no latency overhead
3. **Explicit control:** Clear distinction between concise vs comprehensive modes
4. **Testable:** Can A/B test summary vs detailed_report on same questions

**Secondary:** **Option 3 - Prompt Refinement** (if Option 1 is too invasive)

**Avoid:**
- Option 2 (extra LLM call for filtering)
- Option 4 (extra LLM call for trimming)

---

## Implementation Checklist

When implementing Option 1:

- [ ] Add `response_type` parameter to `_get_drift_synthesis_prompt()`
- [ ] Update call sites in `route_4_drift.py` to pass `response_type`
- [ ] Add mode-specific prompt instructions
- [ ] Test on Q-D5 specifically to verify improvement
- [ ] Run full benchmark suite (all 19 questions, 3 repeats)
- [ ] Compare LLM eval scores: before vs after
- [ ] Check latency impact (should be neutral)
- [ ] Verify `detailed_report` mode still works as expected

---

## Related Files

- **Synthesis Module:** `src/worker/hybrid_v2/pipeline/synthesis.py` (lines 811-850)
- **Route 4 Handler:** `src/worker/hybrid_v2/routes/route_4_drift.py`
- **Benchmark Script:** `scripts/benchmark_route4_drift_multi_hop.py`
- **Evaluation Script:** `scripts/evaluate_route4_reasoning.py`
- **Test Question Bank:** `docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md`

---

## Current Benchmark Results (Baseline)

**File:** `benchmarks/route4_drift_multi_hop_20260205T115442Z.json`  
**Evaluation:** `benchmarks/route4_drift_multi_hop_20260205T115442Z.eval.md`  
**Judge:** GPT-5.1

| Metric | Value |
|--------|-------|
| Total Score | 32/33 (97.0%) |
| Pass Rate (≥2/3) | 100% |
| Perfect Scores (3/3) | 10/11 (91%) |
| Q-D5 Score | 2/3 (acceptable but verbose) |
| Questions Evaluated | 11 |

**Distribution:**
- 3/3: Q-D1, Q-D2, Q-D3, Q-D4, Q-D6, Q-D7, Q-D9, Q-N1, Q-N2, Q-N3
- 2/3: Q-D5
- 1/3: None
- 0/3: None

---

## Next Steps

1. **Defer implementation:** Prompt tuning requires careful testing and validation
2. **Keep this as baseline:** Use current 97% (32/33) as benchmark floor
3. **When implementing:**
   - Run 3x repeats on all 19 questions
   - Compare LLM eval scores
   - Target: Q-D5 → 3/3 while maintaining 10/11 existing perfect scores
   - Acceptance criteria: Overall score ≥97% (no regression)

---

## Notes

- This is a **quality improvement**, not a bug fix (current behavior is acceptable)
- Impact is minor: affects only ~9% of questions (1/11 in evaluation)
- All answers are factually correct; issue is purely about conciseness
- User experience: may prefer verbose answers for exploratory queries
- Consider making verbosity configurable via API parameter
