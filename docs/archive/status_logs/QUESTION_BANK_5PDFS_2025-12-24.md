# Question Bank — 5 PDF Grounded Tests
**Date:** 2025-12-24  
**Data Source:** Neo4j `TextChunk.text` extracted content (Document Intelligence pipeline output)  
**Group ID:** `phase1-5docs-1766595043`

## Routing Mapping (Hybrid 3-Route System)

These question groups are designed to exercise the Hybrid 3-route router:

- Section A (Q-V*): Expected to route to **Route 1 (Vector RAG)** under Profile A; forced to **Route 2** under Profile B.
- Sections B/C (Q-L*, Q-G*): Expected to route to **Route 2 (Local/Global equivalent)**.
- Section D (Q-D*): Expected to route to **Route 3 (DRIFT multi-hop)** under Profile A; forced to **Route 2** under Profile C.

Note: Profile constraints always override base routing.

## Documents
1. BUILDERS LIMITED WARRANTY.pdf
2. HOLDING TANK SERVICING CONTRACT.pdf
3. PROPERTY MANAGEMENT AGREEMENT.pdf
4. contoso_lifts_invoice.pdf
5. purchase_contract.pdf

---

## A) Vector / Exact-Retrieval Questions (10)
Use for `mode=vector` (or queries intended to route to `vector`).
**Expected Route:** Route 1 (Vector RAG)

1. **Q-V1:** What is the invoice **TOTAL** amount?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `29900.00`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

2. **Q-V2:** What is the invoice **DUE DATE**?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `12/17/2015`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

3. **Q-V3:** What are the invoice **TERMS**?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `Due on contract signing`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

4. **Q-V4:** In the purchase contract, list the **3 installment amounts** and their triggers.
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `$20,000.00 upon signing; $7,000.00 upon delivery; $2,900.00 upon completion`
   - **Source:** purchase_contract.pdf (chunk 0)

5. **Q-V5:** What is the **labor warranty** duration in the purchase contract?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `90 days`
   - **Source:** purchase_contract.pdf (chunk 0 or chunk 1)

6. **Q-V6:** In the property management agreement, what is the **approval threshold** requiring prior written approval for expenditures?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `in excess of Three Hundred Dollars ($300.00)`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

7. **Q-V7:** In the holding tank contract, what is the pumper’s **registration number**?   - **Expected Route:** Route 1 (Vector RAG)   - **Expected:** `REG-54321`
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 1)

8. **Q-V8:** What is the warranty’s builder address city/state/zip?   - **Expected Route:** Route 1 (Vector RAG)   - **Expected:** `Pocatello, ID 83201`
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3)

9. **Q-V9:** Who is the invoice **SALESPERSON**?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `Jim Contoso`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

10. **Q-V10:** What is the invoice **P.O. NUMBER**?
   - **Expected Route:** Route 1 (Vector RAG)
   - **Expected:** `30060204`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

---

## B) Local / Entity-Focused Questions (10)
Use for `mode=local` (or queries intended to route to GraphRAG local).
**Expected Route:** Route 2 (Local Search)

1. **Q-L1:** Who is the **Agent** in the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `Walt Flood Realty` (a Hawaii sole proprietorship)
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

2. **Q-L2:** Who is the **Owner** in the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `Contoso Ltd.`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

3. **Q-L3:** What is the managed property address in the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `456 Palm Tree Avenue, Honolulu, HI 96815`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

4. **Q-L4:** What is the initial term start date in the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `2010-06-15`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

5. **Q-L5:** What written notice period is required for termination of the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `sixty (60) days written notice`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

6. **Q-L6:** What is the Agent fee/commission for **short-term** rentals (<180 days)?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `twenty five percent (25%) of the gross revenues`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

7. **Q-L7:** What is the Agent fee/commission for **long-term** leases (>180 days)?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `ten percent (10%) of the gross revenues`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

8. **Q-L8:** What is the pro-ration advertising charge and minimum admin/accounting charge in the property management agreement?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `$75.00/month advertising; $50.00/month minimum admin/accounting`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

9. **Q-L9:** In the purchase contract Exhibit A, what is the job location?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** `811 Ocean Drive, Suite 405, Tampa, FL 33602`
   - **Source:** purchase_contract.pdf (chunk 1)

10. **Q-L10:** In the purchase contract Exhibit A, what is the contact’s name and email?   - **Expected Route:** Route 2 (Local Search)   - **Expected:** `Elizabeth Nolasco; enolasco@fabrikam.com`
   - **Source:** purchase_contract.pdf (chunk 1)

---

## C) Global / Cross-Section or “Policy” Questions (10)
Use for `mode=global` (or queries intended to route to GraphRAG global/community summaries).
**Expected Route:** Route 3 (Global Search)

1. **Q-G1:** Across the agreements, list the **termination/cancellation** rules you can find.
   - **Expected Route:** Route 3 (Global Search)
   - **Expected:**
     - Property management: either party may terminate with `60 days written notice`.
     - Purchase contract: customer may cancel within `3 business days` for full refund; afterward deposit is forfeited.
     - Holding tank contract: remains until owner or pumper terminates.
     - Warranty: not transferable; terminates if first purchaser sells/moves out.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0/1); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1); BUILDERS LIMITED WARRANTY.pdf (chunk 3)

2. **Q-G2:** Identify which documents reference **jurisdictions / governing law**.
   - **Expected Route:** Route 3 (Global Search)
   - **Expected:**
     - Warranty/arbitration: disputes governed by `State of Idaho` substantive law.
     - Purchase contract: governed by laws of `State of Florida`.
     - Property management agreement: governed by laws of `State of Hawaii`.
   - **Note:** "Pocatello" is the builder's mailing address (1820 Summit Ridge Dr., Pocatello, ID 83201), not a jurisdiction reference.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/6); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2)

3. **Q-G3:** Summarize "who pays what" across the set (fees/charges/taxes).
   - **Expected Route:** Route 3 (Global Search)
   - **Expected:**
     - Invoice: `TOTAL/AMOUNT DUE 29900.00`.
     - Purchase contract: $29,900 in 3 installments.
     - Property management: 25%/10% commissions + $75/month advertising + $50/month admin + 10% repair fee + $35/hour scheduling + Hawaii excise tax on fees.
     - Holding tank: owner pays pumper charges; owner files contract changes within 10 business days.
   - **Source:** contoso_lifts_invoice.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0/1)

4. **Q-G4:** What obligations are explicitly described as **reporting / record-keeping**?
   - **Expected Route:** Route 3 (Global Search)
   - **Expected:**
     - Holding tank: pumper submits reports to County including service dates, volumes pumped, and condition.
     - Property management: agent provides owner a monthly statement of income and expenses.
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0/1)

5. **Q-G5:** What remedies / dispute-resolution mechanisms are described?
   - **Expected Route:** Route 3 (Global Search)
   - **Expected:**
     - Warranty: binding arbitration (with small claims carveout) and confidentiality language.
     - Purchase contract: legal fees recoverable by contractor upon customer default.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/5/6); purchase_contract.pdf (chunk 0)

6. **Q-G6:** List all **named parties/organizations** across the documents and which document(s) they appear in.
    - **Expected Route:** Route 3 (Global Search)
    - **Expected:**
       - `Fabrikam Inc.`: builder (warranty), pumper (holding tank), customer (purchase contract)
       - `Contoso Ltd.`: owner (property management), holding tank owner (holding tank)
       - `Contoso Lifts LLC`: contractor (purchase contract)
       - `Walt Flood Realty`: agent (property management)
    - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0)

7. **Q-G7:** Summarize all explicit **notice / delivery** mechanisms (written notice, certified mail, phone, filings) mentioned.
    - **Expected Route:** Route 3 (Global Search)
    - **Expected:**
       - PMA: `60 days written notice` to terminate
       - Warranty: defect notice must be `in writing` and sent by `certified mail return receipt requested`; emergencies by phone
       - Holding tank: file contract changes with municipality/County within `10 business days`
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); BUILDERS LIMITED WARRANTY.pdf (chunk 2/3); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1)

8. **Q-G8:** Summarize all explicit **insurance / indemnity / hold harmless** clauses.
    - **Expected Route:** Route 3 (Global Search)
    - **Expected:**
       - PMA: requires liability insurance with minimum limits `$300,000` BI and `$25,000` PD; hold harmless/indemnify agent (except gross negligence/willful misconduct)
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)

9. **Q-G9:** Identify all explicit **non-refundable / forfeiture** terms across the documents.
    - **Expected Route:** Route 3 (Global Search)
    - **Expected:**
       - PMA: `non-refundable start-up fee` of `$250.00`
       - Purchase contract: after 3 business days, `deposit is forfeited`
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2); purchase_contract.pdf (chunk 0/1)

10. **Q-G10:** Summarize each document's main purpose in one sentence.
    - **Expected Route:** Route 3 (Global Search)
    - **Expected:**
       - Warranty: limited warranty + arbitration process and exclusions
       - Holding tank: servicing/reporting obligations between owner and pumper
       - PMA: agent manages/rents property, fees, responsibilities, and termination
       - Invoice: amount due for lift purchase
       - Purchase contract: scope of work + payments + delivery + cancellation
    - **Source:** All docs (see chunks referenced throughout)

---

## D) Drift / Multi-Hop Reasoning Questions (10)
Use for `mode=drift` (or queries intended to route to multi-hop reasoning).
**Expected Route:** Route 4 (DRIFT)

1. **Q-D1:** If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Must telephone builder immediately for emergencies; failure to promptly notify relieves builder of liability for replacement/repair/damages.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3)

2. **Q-D2:** In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Owner shall honor all confirmed reservations.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

3. **Q-D3:** Compare "time windows" across the set: list all explicit day-based timeframes.
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** **Warranty:** 1 year warranty period (floors, walls, structural, plumbing, heating, electric, roof); 60-day warranty period (doors, windows, switches, fixtures, caulking, cabinets); 60 days repair window after defect report; 60 days after service of complaint for arbitration demand; 180 days arbitration completion target. **Holding Tank:** 10 business days to file contract changes. **Property Management:** 12 months initial term; 60 days written notice for termination; 5 business days to notify agent if property listed for sale; 180 days threshold for short-term vs long-term rentals. **Purchase Contract:** 90 days labor warranty; 3 business days cancel window with full refund.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0/1); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1); BUILDERS LIMITED WARRANTY.pdf (chunk 0/3)

4. **Q-D4:** Which documents mention **insurance** and what limits are specified?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Property management requires liability insurance with minimum limits `$300,000` bodily injury and `$25,000` property damage; agent named additional insured.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

5. **Q-D5:** In the warranty, explain how the "coverage start" is defined and what must happen before coverage ends.
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Coverage begins on date of final settlement or first occupancy whichever comes first; claims must be made in writing within the 1-year or 60-day period before coverage ends.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0)

6. **Q-D6:** Do the purchase contract total price and the invoice total match? If so, what is that amount?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Yes — both state a total of `29,900.00` / `$29,900.00`.
   - **Source:** purchase_contract.pdf (chunk 0); contoso_lifts_invoice.pdf (chunk 0)

7. **Q-D7:** Which document has the latest explicit date, and what is it?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** purchase contract latest date 2025-04-30 holding tank 2024-06-15 contoso_lifts_invoice 2015-12-17 warranty 2010-06-15 property management agreement 2010-06-15
   - **Source:** purchase_contract.pdf (chunk 1)

8. **Q-D8:** Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Both `Fabrikam Inc.` and `Contoso Ltd.` appear in the same number of documents (4 each - they are tied). Fabrikam appears in: warranty (as Builder), holding tank (as Pumper), property management (referenced), and purchase contract (as Customer). Contoso appears in: warranty (as Buyer/Owner), holding tank (as Owner), property management (as Owner), and purchase contract (as Contractor). Note: The invoice lists "Contoso Lifts LLC" which is a different entity.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

9. **Q-D9:** Compare the "fees" concepts: which doc has a percentage-based fee structure and which has fixed installment payments?
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Property management agreement percentage-based commissions 25% 10% gross revenues short term long term; purchase contract fixed installment payments $20,000 $7,000 $2,900 totaling $29,900.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2); purchase_contract.pdf (chunk 0)

10. **Q-D10:** List the three different "risk allocation" statements across the set (risk of loss, liability limitations, non-transferability).
   - **Expected Route:** Route 4 (DRIFT)
   - **Expected:** Purchase contract shifts risk of loss after delivery; property management agreement limits agent liability except gross negligence willful misconduct; warranty is not transferable terminates if first purchaser sells or moves out.
   - **Source:** purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2); BUILDERS LIMITED WARRANTY.pdf (chunk 3)

---

## E) RAPTOR / High-Level Theme Questions (10)
Use for `mode=raptor` (or queries intended to route to hierarchical summaries).

1. **Q-R1:** Summarize the major themes across the 5 documents.
   - **Expected:** Contractual obligations and payments (invoice + purchase contract), service/reporting obligations (holding tank), property management duties/fees/termination (PMA), and warranty coverage/exclusions + arbitration (warranty).
   - **Source:** All docs (see chunks listed above)

2. **Q-R2:** Summarize risk allocation across the set (risk of loss, liability/hold harmless, non-transferability).
   - **Expected:** Purchase contract risk shifts after delivery; PMA has hold harmless/indemnity for agent (except gross negligence/willful misconduct); warranty is not transferable and has exclusions; arbitration clauses define dispute handling.
   - **Source:** purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2); BUILDERS LIMITED WARRANTY.pdf (chunks 1–6)

3. **Q-R3:** Summarize the payment structures (invoice vs contract vs ongoing management fees).
   - **Expected:** Invoice total/amount due 29,900; purchase contract $29,900 in 3 installments; PMA commissions (25%/10%) plus monthly/percentage/hourly add-ons.
   - **Source:** contoso_lifts_invoice.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)

4. **Q-R4:** Summarize all “timeline” concepts (effective dates, term starts, cancellation windows, notice periods).
   - **Expected:** PMA term begins 2010-06-15 with 60-day termination notice; purchase contract effective on signature+payment and signed 04/30/2025 with 3-business-day cancel window; holding tank contract date 2024-06-15; invoice due date 12/17/2015.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0/3); purchase_contract.pdf (chunk 0/1); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); contoso_lifts_invoice.pdf (chunk 0)

5. **Q-R5:** Summarize the warranty’s coverage durations and claim process at a high level.
   - **Expected:** 1-year and 60-day coverage buckets; written notice (certified mail) before the period ends; emergencies by phone; builder repairs within 60 days if covered.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0/2/3)

6. **Q-R6:** Summarize the holding tank contract’s core obligations and reporting contents.
   - **Expected:** Owner provides access; pumper services tank and submits County reports including service dates, gallons pumped, and tank/component condition.
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 0)

7. **Q-R7:** Summarize the PMA responsibilities split between Agent and Owner.
   - **Expected:** Agent advertises, collects rents into trust account, provides monthly statements, contracts for services/maintenance; Owner furnishes/maintains unit, provides tax IDs/license, provides insurance.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0/1)

8. **Q-R8:** Summarize the purchase contract’s scope of work and delivery expectations.
   - **Expected:** Furnish/install a vertical platform lift with listed components; delivery expected 8–10 weeks after drawing approval; delays may include factory and permits.
   - **Source:** purchase_contract.pdf (chunk 0)

9. **Q-R9:** Summarize dispute resolution mechanisms mentioned and where they apply.
   - **Expected:** Warranty disputes go to binding arbitration (with small claims carveout); purchase contract mentions legal fees recoverable if customer defaults.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/5/6); purchase_contract.pdf (chunk 0)

10. **Q-R10:** Summarize all explicit fees and rates in the PMA.
   - **Expected:** 25% short-term commission; 10% long-term; $75/month advertising; $50/month admin; 10% repairs; $35/hour scheduling; 4.712% Hawaii excise tax on fees; $250 non-refundable start-up fee.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)

---

## F) Negative Tests (9)
These should return **“not found / not specified in the provided documents”** (or equivalent).
**Expected Route:** Route 2 (Local Search) - with negative detection

1. **Q-N1:** What is the invoice's **bank routing number** for payment?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

2. **Q-N2:** What is the invoice’s **IBAN / SWIFT (BIC)** for international payments?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

3. **Q-N3:** What is the vendor's **VAT / Tax ID number** on the invoice?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

4. **Q-N5:** What is the invoice’s **bank account number** for ACH/wire payments?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

5. **Q-N6:** Which documents are governed by the laws of **California**?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** None (California not referenced).

6. **Q-N7:** What is the property management Agent's **license number**?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

7. **Q-N8:** What is the purchase contract’s required **wire transfer / ACH instructions**?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

8. **Q-N9:** What is the exact clause about **mold damage** coverage in the warranty?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified.

9. **Q-N10:** What is the invoice **shipping method** (value in "SHIPPED VIA")?
   - **Expected Route:** Route 2 (Local Search)
   - **Expected:** Not specified / blank.

---

## G) Synthesis Gap Questions — Frontier Categories (20)

These questions target four categories of **synthesis/reasoning limitations** that persist even when retrieval is perfect. They benchmark LLM reasoning quality independently of retrieval architecture. Any route that retrieves complete evidence will face these challenges.

See: `ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md` Section 33.17 for full gap analysis.

**Expected Route:** Route 7 (HippoRAG 2) or Route 6 (Global Search) — retrieval is not the bottleneck for these questions; the synthesis step is.

---

### G.1) Numerical Aggregation (Q-A)

1. **Q-A1:** How many distinct dollar amounts (not percentages) are explicitly stated across all 5 documents? List each one with its source document.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Invoice:** $29,900.00 (total/amount due). **Purchase contract:** $20,000 (1st installment), $7,000 (2nd installment), $2,900 (3rd installment), $29,900 (total). **PMA:** $250.00 (non-refundable start-up fee), $75/month (advertising), $50/month (admin fee), $35/hour (scheduling fee). **PMA insurance minimums:** $300,000 (bodily injury), $25,000 (property damage). Total distinct dollar amounts: **11** (note: invoice $29,900 and purchase contract total $29,900 are the same value but from different documents).
   - **Source:** contoso_lifts_invoice.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)
   - **Note:** Tests numerical enumeration + cross-document counting. Common failure: omitting insurance minimums or double-counting the $29,900.

2. **Q-A2:** What is the total fixed monthly cost (not percentage-based) that the property owner pays the agent under the PMA?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** $75 (advertising) + $50 (admin) = **$125/month** in fixed costs. The commissions (25%/10%) and repair markup (10%) are variable, not fixed monthly amounts. The $35/hour scheduling fee is per-use, not monthly. The $250 start-up fee is one-time, not monthly.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)
   - **Note:** Tests filtering by criteria (fixed vs variable vs one-time) + arithmetic. Common failure: including percentage-based fees or the one-time start-up fee.

3. **Q-A3:** Sum all percentage-based rates mentioned in the PMA. What is the total, and is it meaningful to sum them?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** 25% (short-term commission) + 10% (long-term commission) + 10% (repair markup) + 4.712% (Hawaii excise tax) = **49.712%**. However, this sum is **not meaningful** — these percentages apply to different bases (gross rental revenue for commissions, repair costs for markup, fees for tax). They cannot be meaningfully aggregated into a single rate.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)
   - **Note:** Tests arithmetic + meta-reasoning about whether aggregation is valid. Common failure: computing the sum without noting it's meaningless.

4. **Q-A4:** How many distinct time periods (in days, months, weeks, or years) are explicitly stated across all documents? List each one.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Warranty:** 1 year (major systems), 60 days (minor items), 60 days (repair window), 60 days (arbitration demand deadline), 180 days (arbitration completion target). **Holding tank:** 10 business days (file changes). **PMA:** 12 months (initial term), 60 days (termination notice), 5 business days (notify agent of sale listing), 180 days (short-term vs long-term threshold). **Purchase contract:** 90 days (labor warranty), 3 business days (cancellation window), 8-10 weeks (delivery estimate). Total: **13-14** distinct timeframes.
   - **Source:** All docs
   - **Note:** Tests enumeration + deduplication (60 days appears in multiple contexts with different meanings). Common failure: conflating the multiple 60-day periods or missing the 8-10 week delivery estimate.

5. **Q-A5:** Across all documents, how many unique named individuals (not organizations) are mentioned? List each with their role.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Invoice:** John Doe (recipient/ship-to contact), Jim Contoso (salesperson). **Purchase contract / Exhibit A:** Elizabeth Nolasco (contact for Bayfront Animal Clinic job). Total: **3** named individuals. Note: Signature blocks may contain names but these are typically role-holders signing on behalf of organizations, not independently named parties.
   - **Source:** contoso_lifts_invoice.pdf (chunk 0); purchase_contract.pdf (Exhibit A)
   - **Note:** Tests entity type filtering (individuals vs organizations) + exhaustive enumeration. Common failure: including organization names or missing individuals in secondary document sections.

---

### G.2) Temporal / Sequential Reasoning (Q-T)

1. **Q-T1:** Arrange all 5 documents by their stated or effective date from oldest to newest. Which two documents share the same date?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** (1) PMA: 2010-06-15, (2) Warranty: 2010-06-15, (3) Invoice: 2015-12-17, (4) Holding Tank: 2024-06-15, (5) Purchase Contract: 2025-04-30. The **PMA and Warranty** share the same date (June 15, 2010).
   - **Source:** All docs (date fields in each document)
   - **Note:** Tests date extraction from 5 different document formats + comparison. Common failure: missing one document's date or getting the ordering wrong.

2. **Q-T2:** If the purchase contract was signed on its stated date, by what calendar date would the 3-business-day cancellation window expire?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** Contract signed 2025-04-30 (Wednesday). 3 business days: Thu May 1, Fri May 2, Mon May 5 = cancellation window expires **May 5, 2025** (Monday). Weekends (Sat May 3, Sun May 4) are excluded from business days.
   - **Source:** purchase_contract.pdf (chunk 0/1)
   - **Note:** Tests date arithmetic with business day calculation. Common failure: counting calendar days instead of business days, or miscounting the start day.

3. **Q-T3:** Based on the warranty's stated date and coverage period, is the 1-year warranty still active as of today? When did/will it expire?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** Warranty date is 2010-06-15. Coverage begins on "date of final settlement or first occupancy, whichever comes first." Assuming that date aligns with the document date, the 1-year warranty expired **2011-06-15** and the 60-day warranty expired **2010-08-14**. Both are long expired (over 15 years ago).
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0)
   - **Note:** Tests temporal reasoning + conditional date computation. Common failure: not recognizing the coverage start date condition.

4. **Q-T4:** How many years and months elapsed between the oldest and newest document dates in the set?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** Oldest: PMA/Warranty at 2010-06-15. Newest: Purchase Contract at 2025-04-30. Elapsed: **14 years, 10 months, and 15 days** (approximately 14 years 10 months).
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf; purchase_contract.pdf
   - **Note:** Tests date interval computation. Common failure: miscalculating months or confusing which documents are oldest/newest.

5. **Q-T5:** If the PMA started on its effective date and auto-renews every 12 months, how many times has it renewed as of February 2026?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** PMA effective 2010-06-15. Initial 12-month term expires 2011-06-15. Then auto-renews annually. From June 2011 to February 2026 = ~14 years 8 months = **14 completed renewals** (currently in the 15th renewal year, which started June 2025).
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)
   - **Note:** Tests combining contract terms with date arithmetic. Common failure: off-by-one in renewal count or not accounting for the initial term.

---

### G.3) Implicit Role / Risk Inference (Q-I)

1. **Q-I1:** Across all documents, which named party bears the most financial risk? Justify by listing their specific obligations and exposures.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Contoso Ltd. / the Owner** bears the most financial risk: (a) under PMA: pays commissions (25%/10%), monthly fees ($75+$50), repair markup (10%), $250 start-up, insurance premiums, excise tax, and must indemnify agent; (b) under Holding Tank: pays pumper charges; (c) under Warranty (as Buyer/Owner): warranty has extensive exclusions and is non-transferable — once expired, all repair costs fall to owner; (d) under Purchase Contract: Fabrikam (as Customer) risks $20,000 deposit forfeiture after 3 days + risk of loss shifts on delivery.
   - **Source:** All docs
   - **Note:** Tests multi-document synthesis + comparative risk assessment. Common failure: listing obligations without concluding who bears MORE risk, or confusing which entity is the "owner" in each document.

2. **Q-I2:** If Fabrikam Inc. ceased operations, which agreements would be directly affected and what would each counterparty lose?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** (a) **Warranty** — Contoso Ltd. (Buyer/Owner) loses warranty coverage; Fabrikam is the Builder obligated to repair defects. (b) **Holding Tank** — Contoso Ltd. (Owner) loses their pumper; must find a replacement and file contract changes within 10 business days. (c) **Purchase Contract** — Contoso Lifts LLC (Contractor) loses their customer; Fabrikam is the Customer who ordered the lift. The **PMA is unaffected** — its parties are Contoso Ltd. and Walt Flood Realty; Fabrikam is not a party to it.
   - **Source:** All docs
   - **Note:** Tests entity-document role mapping + counterfactual reasoning. Common failure: incorrectly including the PMA as affected, or confusing Fabrikam Inc. with Fabrikam Construction (invoice entity).

3. **Q-I3:** Which document provides the weakest consumer/buyer protection? Explain what makes it weaker than the others.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** The **Builders Limited Warranty** provides the weakest buyer protection: (a) extensive exclusions (settling, cracking, exterior stains, septic systems, landscaping, etc.); (b) non-transferable — terminates on resale; (c) strict notice requirements (certified mail, return receipt requested); (d) mandatory binding arbitration with confidentiality clause — removes court access; (e) short 60-day window for minor items. By comparison, the PMA at least allows 60-day termination by either party, and the Purchase Contract offers a 3-day full-refund cancellation window.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunks 0-6); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)
   - **Note:** Tests comparative legal analysis + reasoning about protection strength. Common failure: stating facts without comparative judgment, or selecting the wrong document.

4. **Q-I4:** If a dispute arose about the quality of the vertical platform lift installation, which documents would be relevant and what remedies are available?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Purchase Contract:** 90-day labor warranty; contractor recovers legal fees on customer default; risk of loss shifts to customer on delivery. **Invoice:** documents the $29,900 payment but contains no warranty or dispute terms. The **Builders Limited Warranty is NOT relevant** — it covers a residential property (480 Willow Glen Drive, Chubbuck, ID) and its builder is Fabrikam Inc., while the lift installation involves Contoso Lifts LLC at a different location (Bayfront Animal Clinic). The warranty and purchase contract are separate agreements between different parties about different properties.
   - **Source:** purchase_contract.pdf (chunk 0); contoso_lifts_invoice.pdf (chunk 0); BUILDERS LIMITED WARRANTY.pdf (chunk 0)
   - **Note:** Tests cross-document reasoning about applicability. Common failure: incorrectly applying the Builders Limited Warranty to the lift installation because both involve "warranty" concepts.

5. **Q-I5:** Which party has the most contractual obligations (not rights) across all documents? List the obligations per document.
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Fabrikam Inc.** has obligations in 3 documents: (a) Warranty — repair/replace defects within 60 days, respond to emergency calls; (b) Holding Tank — pump tank, submit County reports with dates/volumes/condition, provide licensed equipment; (c) Purchase Contract (as Customer) — make installment payments ($20,000/$7,000/$2,900). **Contoso Ltd.** also has obligations in 3 documents: (a) PMA — furnish property, provide insurance, pay fees/commissions; (b) Holding Tank — provide access to tank, pay pumper charges, file contract with County; (c) Warranty — provide written notice of defects by certified mail. Both have obligations in 3 documents, but Fabrikam's obligations are more operationally demanding (physical servicing, construction repair) while Contoso's are primarily financial.
   - **Source:** All docs
   - **Note:** Tests obligation enumeration + comparative analysis. Common failure: confusing rights with obligations, or missing obligations in secondary clauses.

---

### G.4) Clause-Level Legal Interpretation (Q-C)

1. **Q-C1:** The warranty states it is "not transferable" and "terminates if first purchaser sells or moves out." Are these the same thing, or do they mean something different legally?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** These are **related but distinct concepts.** "Not transferable" means the warranty cannot be assigned to another person — the new buyer cannot claim under it. "Terminates if first purchaser sells or moves out" goes further — the warranty **ceases to exist entirely**, not just for the new buyer but for everyone. Together they mean: (a) even if transfer were somehow attempted, it would be void; AND (b) the warranty itself ends as a matter of contract, regardless of any assignment attempt. The termination clause is the stronger provision — it makes the warranty disappear, not merely unenforceable by a third party.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3)
   - **Note:** Tests distinguishing between two related legal concepts. Common failure: treating them as synonymous ("both mean the new buyer gets nothing").

2. **Q-C2:** The PMA says the owner must "hold harmless and indemnify Agent...except for losses caused by Agent's gross negligence or willful misconduct." Does the agent have ANY liability under this agreement?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** **Yes, but only for gross negligence or willful misconduct.** The indemnification clause protects the agent from all ordinary liability (simple negligence, third-party claims, property damage, etc.) — the owner absorbs those costs. The exception carves out a narrow category: if the agent's actions rise to "gross negligence or willful misconduct," the owner is NOT required to indemnify. This means the agent IS liable for their own grossly negligent or willfully wrongful acts, but NOT for ordinary mistakes.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2)
   - **Note:** Tests understanding exception-to-indemnification clauses. Common failure: stating the agent has "no liability" (ignoring the exception) or overstating the exception as general liability.

3. **Q-C3:** The warranty's arbitration clause includes a "small claims carveout." What is the practical significance for a homeowner with a $500 repair claim?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** The small claims carveout means disputes below the jurisdictional small claims court limit **do not have to go through arbitration** — the homeowner can file directly in small claims court. This is practically significant because: (a) arbitration filing fees often exceed the claim value for small amounts; (b) small claims court is designed for self-representation (no attorney needed); (c) it provides a faster, cheaper path for minor warranty claims. Without this carveout, even a $500 claim would require binding arbitration with its associated costs.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/5)
   - **Note:** Tests understanding the practical effect of a procedural carveout. Common failure: explaining what arbitration is without addressing why the carveout matters for small claims specifically.

4. **Q-C4:** The purchase contract states the deposit is "forfeited" if the customer doesn't cancel within 3 business days. Is this a penalty or liquidated damages? Does the distinction matter?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** The contract uses "forfeited" without specifying whether it constitutes liquidated damages or a penalty. The distinction matters under Florida law (the governing jurisdiction): **liquidated damages** are enforceable if they represent a reasonable pre-estimate of actual loss; **penalties** designed to punish breach may be unenforceable. A $20,000 forfeiture on a $29,900 contract (67% of total) could be challenged as a penalty if the contractor's actual damages from cancellation would be substantially less. The contract does not include a liquidated damages clause or reasonableness justification.
   - **Source:** purchase_contract.pdf (chunk 0/1)
   - **Note:** Tests legal concept application to contract terms. Common failure: defining the terms without applying them to the specific facts (forfeiture amount vs contract value, governing law).

5. **Q-C5:** The holding tank contract references "WI Code SPS 383.21(2)5" as the basis for filing requirements. What does this reference tell us about the regulatory context, and what might happen if the owner fails to file?
   - **Expected Route:** Route 7 (HippoRAG 2)
   - **Expected:** The statutory reference indicates this contract operates under **Wisconsin administrative code** (SPS = Safety and Professional Services). This means: (a) the filing requirement is not merely contractual but **regulatory** — it exists because state law mandates it; (b) failure to file may expose the owner to **governmental enforcement** (fines, compliance orders), not just contractual breach by the pumper; (c) the pumper's reporting obligations to the County are also likely regulatory in origin. The regulatory context elevates this from a private contract term to a public health/environmental compliance obligation.
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 0/1)
   - **Note:** Tests inference from statutory references about regulatory implications. Common failure: noting the code reference exists without analyzing what it implies about enforcement and consequences.
