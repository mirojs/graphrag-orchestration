# Session Continuation Plan

**Date**: 2025-11-10  
**Context**: Azure Content Understanding (2025-05-01-preview) GeneratedSchema returns only metadata (name, description) — no field definitions. Array-based pattern validated (5 fields). String-based historical pattern pending reproduction.

---
## 1. Current Ground Truth
- GeneratedSchema (`method: generate`) produces empty `fields` object across prompt-only, enhanced prompt, and document-driven tests.
- Document parsing works (content extracted) but schema field synthesis does not.
- Array-of-field-definitions pattern succeeds for both document + prompt-only modes (returns 5 objects).
- Historical string JSON pattern (CompleteEnhancedSchema) previously produced full field schema; unverified today.

## 2. Open Questions for Next Session
1. Can we still reproduce the string-based `CompleteEnhancedSchema` pattern in current API version?
2. Does the array pattern scale to nested structures (e.g., richer `line_items` details)?
3. Which pattern (array vs string) yields lower transformation overhead and higher reliability?
4. Any hidden analyzer configuration enabling direct population of `fields.valueObject`?
5. What canonical internal schema shape do we standardize on for downstream processing?

## 3. Planned Experiments (Priority Order)
1. Implement `tests/test_string_schema_generation_pattern.py` (prompt-only + document-driven variants).
2. Enrich array output: add nested `line_items` object with properties (quantity, description, unit_price, line_total); remove stray scalar `items` arrays.
3. Apply 7-dimension AI self-correction (OpenAI) to raw CU output; capture dimension scores before/after.
4. Build consolidated test harness to compare latency, field count, dimension quality across: GeneratedSchema, Array, String, OpenAI direct.
5. Draft Azure support inquiry summarizing empty `fields` behavior with timestamps & artifacts.

## 4. Decision Matrix (Preliminary)
| Criterion | Array Pattern | String Pattern | GeneratedSchema |
|-----------|---------------|----------------|-----------------|
| Field completeness | ✅ | ✅ (if JSON parse) | ❌ |
| Nested structure potential | Medium (needs enrichment) | Unknown (test) | N/A |
| Transformation complexity | Medium (normalize objects) | Medium (parse string) | High (needs alternate source) |
| Reliability (today) | Validated | Pending | Blocked |
| Prompt flexibility | High | High | Low |

## 5. Target Metrics
| Metric | Today | Target | Notes |
|--------|-------|--------|-------|
| Field count | 5 (array) / 0 (GeneratedSchema) | ≥6 (include line item subfields) | Add nested properties |
| Avg description length | ~150 | ≥200 | Post-refinement |
| Relationship annotations | 0 | ≥3 | vendor↔invoice, line_items→total, date context |
| Provenance tags | 0 | Present per field | Source segments (table/header) |
| Latency (array prompt-only) | ~37s | ≤60s | Maintain ≤300s cap |

## 6. Risks & Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| String pattern deprecated | Lose richer option | Test ASAP & document behavior |
| API latency >300s | Slow iteration | Cap + backoff + metrics logging |
| Inconsistent field object shapes | Parsing errors | Validator + normalization layer |
| Over-refined verbose descriptions | Reduced clarity | Length caps + scoring rubric |
| Dependency on undocumented behavior | Future breakage | Favor documented patterns; escalate to support |

## 7. Implementation Checklist (Kickoff Tomorrow)
- [ ] Create string pattern test script.
- [ ] Run prompt-only + document-driven variants; save artifacts.
- [ ] Implement array enrichment transformer (`backend/utils/schema_transformers.py`).
- [ ] Integrate transformer + feature flag in `backend/utils/query_schema_generator.py`.
- [ ] Add 7-dimension refinement pass; output before/after diff.
- [ ] Build consolidated harness (latency + quality metrics).
- [ ] Draft Azure support inquiry (attach sample empty fields outputs).

## 8. Quick Restart Commands
```bash
python3 tests/test_prompt_file_array_pattern.py
python3 tests/test_array_schema_generation_pattern.py
# After creation:
python3 tests/test_string_schema_generation_pattern.py
```

## 9. Parking Lot (Later Considerations)
- Multi-document grounding for schema confidence scores.
- Provenance visualization UI component.
- Schema version diff & migration assistant.
- Severity scoring & gap analysis across a document set.

## 10. End-of-Day Snapshot
Array pattern validated; string pattern reproduction pending; GeneratedSchema unsuitable for direct field generation. Canonical schema source decision and refinement pipeline queued.

---
**To be continued next session.**
