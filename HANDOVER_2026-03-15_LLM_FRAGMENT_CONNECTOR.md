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

## TODO List

### Immediate
1. **Apply LLM fragment connector to contact/address blocks** — Currently only signature blocks get the LLM treatment. The contact block (WARRANTY para 27) still goes through Source A as garbled body text. Need to:
   - Detect contact/address block paragraphs (pattern: Street, City/State/Zip, phone number)
   - Exclude them from normal section DI units (like sig blocks)
   - Route them through `_synthesize_signature_sentences()` or a similar LLM connector
   
2. **Commit the LLM fragment connector changes** — Current changes to `sentence_extraction_service.py` are uncommitted

3. **Reindex** `test-5pdfs-v2-fix2` with the fixes (another session may already be reindexing)

4. **Run benchmark** to measure Q-G6 improvement from signature/contact fix
   - Baseline: 157/171 (91.8%), Q-G6: 5/9
   - Command: `python3 scripts/benchmark_route7_hipporag2.py --positive-prefix Q-G --query-mode community_search --repeats 3 --no-auth`

### Remaining Q-G6 Issues (after contact block fix)
5. **AAA missing** — American Arbitration Association not consistently retrieved. Investigate retrieval vs synthesis gap.
6. **Missing roles** — Ground truth expects roles (builder, pumper, etc.) but may need ground truth adjustment or synthesis prompt tuning.

### Other Below-Threshold Questions
7. **Q-G8 (5/9)** — Stacked retrieval + synthesis gap. Wider community selection proven harmful. Needs alternative approach (query decomposition, synthesis prompt tuning for "hold harmless" interpretation).
8. **Q-G4 (6/9)** — Synthesis over-inclusion (tax IDs, sale notification). Prompt tuning needed.
9. **Q-G3 (7/9)** — Minor omissions (compliance costs, credit card fees).

## Baseline Scores
| Q | Score | Status |
|---|-------|--------|
| Q-G1 | 8/9 | Minor |
| Q-G2 | 9/9 | ✅ |
| Q-G3 | 7/9 | Omissions |
| Q-G4 | 6/9 | Over-inclusion |
| Q-G5 | 9/9 | ✅ |
| Q-G6 | 5/9 | ❌ Signature/contact fix in progress |
| Q-G7 | 9/9 | ✅ |
| Q-G8 | 5/9 | ❌ Retrieval + synthesis gap |
| Q-G9 | 9/9 | ✅ |
| Q-G10 | 9/9 | ✅ |
| **Total** | **157/171** | **91.8%** |
