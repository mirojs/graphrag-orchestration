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

1. **Q-V1:** What is the invoice **TOTAL** amount?
   - **Expected:** `TOTAL 29900.00` (also shown as SUBTOTAL and AMOUNT DUE)
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

2. **Q-V2:** What is the invoice **DUE DATE**?
   - **Expected:** `12/17/2015`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

3. **Q-V3:** What are the invoice **TERMS**?
   - **Expected:** `Due on contract`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

4. **Q-V4:** In the purchase contract, list the **3 installment amounts** and their triggers.
   - **Expected:** `$20,000.00 upon signing; $7,000.00 upon delivery; $2,900.00 upon completion`
   - **Source:** purchase_contract.pdf (chunk 0)

5. **Q-V5:** What is the **labor warranty** duration in the purchase contract?
   - **Expected:** `Contractor warrants labor for 90 days.`
   - **Source:** purchase_contract.pdf (chunk 0 or chunk 1)

6. **Q-V6:** In the property management agreement, what is the **approval threshold** requiring prior written approval for expenditures?
   - **Expected:** `in excess of Three Hundred Dollars ($300.00)`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

7. **Q-V7:** In the holding tank contract, what is the pumper’s **registration number**?
   - **Expected:** `REG-54321`
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 1)

8. **Q-V8:** What is the warranty’s builder address city/state/zip?
   - **Expected:** `Pocatello, ID 83201`
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3)

9. **Q-V9:** Who is the invoice **SALESPERSON**?
   - **Expected:** `Jim Contoso`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

10. **Q-V10:** What is the invoice **P.O. NUMBER**?
   - **Expected:** `30060204`
   - **Source:** contoso_lifts_invoice.pdf (chunk 0)

---

## B) Local / Entity-Focused Questions (10)
Use for `mode=local` (or queries intended to route to GraphRAG local).

1. **Q-L1:** Who is the **Agent** in the property management agreement?
   - **Expected:** `Walt Flood Realty` (a Hawaii sole proprietorship)
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

2. **Q-L2:** Who is the **Owner** in the property management agreement?
   - **Expected:** `Contoso Ltd.`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

3. **Q-L3:** What is the managed property address in the property management agreement?
   - **Expected:** `456 Palm Tree Avenue, Honolulu, HI 96815`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

4. **Q-L4:** What is the initial term start date in the property management agreement?
   - **Expected:** `2010-06-15`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

5. **Q-L5:** What written notice period is required for termination of the property management agreement?
   - **Expected:** `sixty (60) days written notice`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

6. **Q-L6:** What is the Agent fee/commission for **short-term** rentals (<180 days)?
   - **Expected:** `twenty five percent (25%) of the gross revenues`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

7. **Q-L7:** What is the Agent fee/commission for **long-term** leases (>180 days)?
   - **Expected:** `ten percent (10%) of the gross revenues`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

8. **Q-L8:** What is the pro-ration advertising charge and minimum admin/accounting charge in the property management agreement?
   - **Expected:** `$75.00/month advertising; $50.00/month minimum admin/accounting`
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

9. **Q-L9:** In the purchase contract Exhibit A, what is the job location?
   - **Expected:** `811 Ocean Drive, Suite 405, Tampa, FL 33602`
   - **Source:** purchase_contract.pdf (chunk 1)

10. **Q-L10:** In the purchase contract Exhibit A, what is the contact’s name and email?
   - **Expected:** `Elizabeth Nolasco; enolasco@fabrikam.com`
   - **Source:** purchase_contract.pdf (chunk 1)

---

## C) Global / Cross-Section or “Policy” Questions (10)
Use for `mode=global` (or queries intended to route to GraphRAG global/community summaries).

1. **Q-G1:** Across the agreements, list the **termination/cancellation** rules you can find.
   - **Expected:**
     - Property management: either party may terminate with `60 days written notice`.
     - Purchase contract: customer may cancel within `3 business days` for full refund; afterward deposit is forfeited.
     - Holding tank contract: remains until owner or pumper terminates.
     - Warranty: not transferable; terminates if first purchaser sells/moves out.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0/1); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1); BUILDERS LIMITED WARRANTY.pdf (chunk 3)

2. **Q-G2:** Identify which documents reference **jurisdictions / governing law**.
   - **Expected:**
     - Warranty/arbitration: disputes reference `State of Idaho` and arbitration in `Pocatello, Idaho`.
     - Purchase contract: governed by laws of `State of Florida`.
     - Property management agreement: governed by laws of `State of Hawaii`.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/6); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2)

3. **Q-G3:** Summarize “who pays what” across the set (fees/charges/taxes).
   - **Expected:**
     - Invoice: `TOTAL/AMOUNT DUE 29900.00`.
     - Purchase contract: $29,900 in 3 installments.
     - Property management: 25%/10% commissions + $75/month advertising + $50/month admin + 10% repair fee + $35/hour scheduling + Hawaii excise tax on fees.
     - Holding tank: owner pays pumper charges; owner files contract changes within 10 business days.
   - **Source:** contoso_lifts_invoice.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0/1)

4. **Q-G4:** What obligations are explicitly described as **reporting / record-keeping**?
   - **Expected:**
     - Holding tank: pumper submits reports to County including service dates, volumes pumped, and condition.
     - Property management: agent provides owner a monthly statement of income and expenses.
   - **Source:** HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0/1)

5. **Q-G5:** What remedies / dispute-resolution mechanisms are described?
   - **Expected:**
     - Warranty: binding arbitration (with small claims carveout) and confidentiality language.
     - Purchase contract: legal fees recoverable by contractor upon customer default.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3/4/5/6); purchase_contract.pdf (chunk 0)

6. **Q-G6:** List all **named parties/organizations** across the documents and which document(s) they appear in.
    - **Expected:**
       - `Fabrikam Inc.`: builder (warranty), pumper (holding tank), customer (purchase contract)
       - `Contoso Ltd.`: owner (property management), holding tank owner (holding tank)
       - `Contoso Lifts LLC`: contractor (purchase contract)
       - `Walt Flood Realty`: agent (property management)
    - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0)

7. **Q-G7:** Summarize all explicit **notice / delivery** mechanisms (written notice, certified mail, phone, filings) mentioned.
    - **Expected:**
       - PMA: `60 days written notice` to terminate
       - Warranty: defect notice must be `in writing` and sent by `certified mail return receipt requested`; emergencies by phone
       - Holding tank: file contract changes with municipality/County within `10 business days`
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); BUILDERS LIMITED WARRANTY.pdf (chunk 2/3); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1)

8. **Q-G8:** Summarize all explicit **insurance / indemnity / hold harmless** clauses.
    - **Expected:**
       - PMA: requires liability insurance with minimum limits `$300,000` BI and `$25,000` PD; hold harmless/indemnify agent (except gross negligence/willful misconduct)
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2)

9. **Q-G9:** Identify all explicit **non-refundable / forfeiture** terms across the documents.
    - **Expected:**
       - PMA: `non-refundable start-up fee` of `$250.00`
       - Purchase contract: after 3 business days, `deposit is forfeited`
    - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2); purchase_contract.pdf (chunk 0/1)

10. **Q-G10:** Summarize each document’s main purpose in one sentence.
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

1. **Q-D1:** If an emergency defect occurs under the warranty (e.g., burst pipe), what is the required notification channel and consequence of delay?
   - **Expected:** Must telephone builder immediately for emergencies; failure to promptly notify relieves builder of liability for replacement/repair/damages.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 3)

2. **Q-D2:** In the property management agreement, what happens to confirmed reservations if the agreement is terminated or the property is sold?
   - **Expected:** Owner shall honor all confirmed reservations.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

3. **Q-D3:** Compare “time windows” across the set: list all explicit day-based timeframes.
   - **Expected:** 60 days written notice (property management); 3 business days cancel window (purchase contract); 10 business days to file changes (holding tank); 60 days repair window after defect report (warranty repair timeline); 60-day warranty for certain items; demand for arbitration timing mentions 60 days after service of complaint.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0); purchase_contract.pdf (chunk 0/1); HOLDING TANK SERVICING CONTRACT.pdf (chunk 1); BUILDERS LIMITED WARRANTY.pdf (chunk 0/3)

4. **Q-D4:** Which documents mention **insurance** and what limits are specified?
   - **Expected:** Property management requires liability insurance with minimum limits `$300,000` bodily injury and `$25,000` property damage; agent named additional insured.
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1)

5. **Q-D5:** In the warranty, explain how the “coverage start” is defined and what must happen before coverage ends.
   - **Expected:** Coverage begins on date of final settlement or first occupancy (whichever first); claims must be made in writing within the 1-year or 60-day period.
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0)

6. **Q-D6:** Do the purchase contract total price and the invoice total match? If so, what is that amount?
   - **Expected:** Yes — both state a total of `29,900.00` / `$29,900.00`.
   - **Source:** purchase_contract.pdf (chunk 0); contoso_lifts_invoice.pdf (chunk 0)

7. **Q-D7:** Which document has the latest explicit date, and what is it?
   - **Expected:** `Signed this 04/30/2025` in the purchase contract Exhibit A.
   - **Source:** purchase_contract.pdf (chunk 1)

8. **Q-D8:** Across the set, which entity appears in the most different documents: `Fabrikam Inc.` or `Contoso Ltd.`?
   - **Expected:** `Fabrikam Inc.` appears in more documents (warranty, holding tank, purchase contract) than `Contoso Ltd.` (property management, holding tank).
   - **Source:** BUILDERS LIMITED WARRANTY.pdf (chunk 0); HOLDING TANK SERVICING CONTRACT.pdf (chunk 0); purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 0)

9. **Q-D9:** Compare the “fees” concepts: which doc has a percentage-based fee structure and which has fixed installment payments?
   - **Expected:** PMA has percentage-based commissions (25%/10% + add-ons); purchase contract has fixed installment payments ($20k/$7k/$2.9k).
   - **Source:** PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 1/2); purchase_contract.pdf (chunk 0)

10. **Q-D10:** List the three different “risk allocation” statements across the set (risk of loss, liability limitations, non-transferability).
   - **Expected:** Purchase contract shifts risk after delivery; PMA limits agent liability except gross negligence/willful misconduct; warranty is not transferable (terminates if first purchaser sells/moves out).
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

1. **Q-N1:** What is the invoice’s **bank routing number** for payment?
   - **Expected:** Not specified.

2. **Q-N2:** What is the invoice’s **IBAN / SWIFT (BIC)** for international payments?
   - **Expected:** Not specified.

3. **Q-N3:** What is the vendor’s **VAT / Tax ID number** on the invoice?
   - **Expected:** Not specified.

4. **Q-N5:** What is the invoice’s **bank account number** for ACH/wire payments?
   - **Expected:** Not specified.

5. **Q-N6:** Which documents are governed by the laws of **California**?
   - **Expected:** None (California not referenced).

6. **Q-N7:** What is the property management Agent’s **license number**?
   - **Expected:** Not specified.

7. **Q-N8:** What is the purchase contract’s required **wire transfer / ACH instructions**?
   - **Expected:** Not specified.

8. **Q-N9:** What is the exact clause about **mold damage** coverage in the warranty?
   - **Expected:** Not specified.

9. **Q-N10:** What is the invoice **shipping method** (value in “SHIPPED VIA”)?
   - **Expected:** Not specified / blank.
