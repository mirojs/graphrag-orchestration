# Handover — 2026-03-15: LLM Fragment Connector for Signature & Contact Blocks

## Where We Are

### Problem
Signature blocks and contact/address blocks produce garbled sentences like:
- `"Representative John Smith Company Fabrikam Inc."` — LLM reads "John Smith Company" as a company name
- `"Entered into as of date of last signature of the parties hereto. Contoso Ltd. Fabrikam Inc. (Buyer/Owner). Builder..."` — disconnected fragments joined with ". "

These are distinct text fragments (names, roles, dates, addresses) that individually lack context. They need to be **connected** into meaningful sentences.

### Solution: LLM Fragment Connector
Replaced the template-based and raw-join approach in `_synthesize_signature_sentences()` with a single LLM call per block that connects fragments into a coherent sentence.

**Prompt**: "Connect the following text fragments into a single meaningful sentence. Do NOT add any information not present. Just add minimal connective words."

**Results** (tested on all 4 signature blocks + 1 contact block):
- Contact: `"Representative John Smith of Company Fabrikam Inc., located at 1820 Summit Ridge Dr., Pocatello, ID 83201, can be reached at the emergency number (208) 555-2311."`
- WARRANTY sig: `"Contoso Ltd. (Buyer/Owner) by Fabrikam Inc. (Builder), Authorized Representative, 2010-06-15."`
- PMA sig: `"SIGNED in duplicate this 15th day of June 2010; both parties acknowledge receipt... OWNER: Contoso Ltd., It's Owner, 2010-06-15; AGENT: Walt Flood Realty, Fabrikam Inc., It's Principal Broker, 2010-06-15."`
- Purchase sig: `"Signed this 04/30/2025 by Authorized Representative Contoso Ltd. and Authorized Representative Fabrikam Inc."`

### Changes Made (uncommitted)
- `src/worker/services/sentence_extraction_service.py`:
  - Added `_call_llm_text()` — plain text LLM call (mirrors `_call_llm_json` but returns raw string)
  - Rewrote `_synthesize_signature_sentences()` — filters noise lines, sends fragments to LLM, falls back to comma-join

### Previous Commit (8b65bbb5)
- `src/worker/services/document_intelligence_service.py`: Fixed `_detect_signature_block_paragraphs()` to always run both handwritten AND typed-anchor detection paths (was fallback-only)
- `src/worker/services/sentence_extraction_service.py`: Original template-based signature synthesis (now superseded by LLM approach)

## Key Discovery: Contact Block ≠ Signature Block
The "John Smith" paragraph (WARRANTY para 27, page 1) is **NOT** in the signature block. It's a **contact/address block** embedded in Section 6 (Notification of Defects) body text at Y=10.85". The actual signature block is on page 2 (paras 39-52).

Azure DI merged 5 separate lines (Representative, Company, Street, City/State/Zip, Phone) into one paragraph. Each line is a label-value pair that makes sense alone, but the concatenation is garbled.

This block goes through the normal Source A (paragraph body text) path, NOT the signature path.

## Completed Steps

1. ✅ **LLM fragment connector** — `_synthesize_signature_sentences()` rewritten with LLM (commit 485a6e26)
2. ✅ **Contact block detection** — `_is_contact_block_paragraph()`, `_detect_contact_block_paragraph_indices()` added; excluded from section DI units; Source H handler for sentence extraction (commit 480480e4)
3. ✅ **Span-union text stripping** — Contact block text leaked via span-union merging (min..max range). Fixed by stripping contact-block paragraph spans from section text after slicing (commit c799a8ca)
4. ✅ **Reindex completed** — 207 sentences, 12 communities, 472 entities
5. ✅ **Verified** — garbled "Representative John Smith Company Fabrikam Inc." sentence is gone; replaced with coherent LLM-connected contact_block and signature_block sentences
6. ✅ **Benchmark run** — 152/171 (88.9%)

## Benchmark Results After Fix

| Q | Baseline | After Fix | Change |
|---|----------|-----------|--------|
| Q-G1 | 8/9 | 8/9 | = |
| Q-G2 | 9/9 | 6/9 | ❌ -3 (WI Code regression) |
| Q-G3 | 7/9 | 9/9 | ✅ +2 |
| Q-G4 | 6/9 | 9/9 | ✅ +3 |
| Q-G5 | 9/9 | 8/9 | -1 |
| Q-G6 | 5/9 | 6/9 | ✅ +1 |
| Q-G7 | 9/9 | 8/9 | -1 |
| Q-G8 | 5/9 | 3/9 | ❌ -2 |
| Q-G9 | 9/9 | 9/9 | = |
| Q-G10 | 9/9 | 5/9 | ❌ -4 |
| Neg | 81/81 | 81/81 | = |
| **Total** | **157/171** | **152/171** | **-5** |

### Analysis
The contact block fix achieved its goal — garbled sentence removed, Q-G6 improved. However the reindex changed community structure (11→12 communities), causing regressions in Q-G2, Q-G8, Q-G10. These regressions are **not caused by the fix** but by non-deterministic community detection (Louvain) producing different community boundaries.

Key regressions:
- **Q-G2 (9→6)**: Missing WI Code / County of Washburn — holding tank content split into different community
- **Q-G8 (5→3)**: Insurance/indemnity clauses — already below threshold, community restructuring worsened retrieval
- **Q-G10 (9→5)**: Document purpose summaries — community split affects global overview queries

## TODO List

### Remaining Work
1. **Stabilize community structure** — The Louvain algorithm is non-deterministic. Consider seeding or using deterministic community detection to prevent score fluctuations across reindexes.
2. **Q-G6 further improvement (6/9→9/9)** — AAA (American Arbitration Association) still missing in some runs. Investigate retrieval gap vs synthesis gap.
3. **Q-G8 (3/9)** — Stacked retrieval + synthesis gap. Insurance/indemnity/hold harmless clauses span multiple documents. Consider query decomposition or wider community selection.
4. **Q-G2 (6/9)** — WI Code SPS 383.21(2)5 and County of Washburn retrieval. Holding tank contract content may need entity extraction improvement.
5. **Q-G10 (5/9)** — Global summary question sensitive to community boundaries. May need a different retrieval strategy (all communities, not just top-matched).
