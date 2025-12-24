# Question Bank — 5 PDF Grounded Tests
**Date:** 2025-12-24  
**Data Source:** Neo4j `TextChunk.text` extracted content (Document Intelligence pipeline output)  
**Group ID:** `phase1-5docs-1766595043`

## Documents
1. BUILDERS LIMITED WARRANTY.pdf
2. HOLDING TANK SERVICING CONTRACT.pdf
3. PROPERTY MANAGEMENT AGREEMENT.pdf
4. contoso_lifts_invoice.pdf
5. purchase_contract.pdf

---

## A) Vector / Exact-Retrieval Questions (8)
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

## C) Global / Cross-Section or “Policy” Questions (5)
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

---

## D) Drift / Multi-Hop Reasoning Questions (5)
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

---

## E) RAPTOR / High-Level Theme Questions (2)
Use for `mode=raptor` (or queries intended to route to hierarchical summaries).

1. **Q-R1:** Summarize the major themes across the 5 documents.
   - **Expected:** Contractual obligations and payments (invoice + purchase contract), service/reporting obligations (holding tank), property management duties/fees/termination (PMA), and warranty coverage/exclusions + arbitration (warranty).
   - **Source:** All docs (see chunks listed above)

2. **Q-R2:** Summarize risk allocation across the set (risk of loss, liability/hold harmless, non-transferability).
   - **Expected:** Purchase contract risk shifts after delivery; PMA has hold harmless/indemnity for agent (except gross negligence/willful misconduct); warranty is not transferable and has exclusions; arbitration clauses define dispute handling.
   - **Source:** purchase_contract.pdf (chunk 0); PROPERTY MANAGEMENT AGREEMENT.pdf (chunk 2); BUILDERS LIMITED WARRANTY.pdf (chunks 1–6)
