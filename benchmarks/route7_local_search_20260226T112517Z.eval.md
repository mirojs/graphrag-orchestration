# LLM Judge Evaluation Report

**Source:** `route7_local_search_20260226T112517Z.json`
**Judge Model:** `gpt-5.1`
**Date:** 2026-02-26 11:28:28

## Summary Metrics

- **Total Score:** 48/57 (84.2%)
- **Pass Rate (Score >= 2):** 84.2%
- **Evaluated Questions:** 19

## Detailed Results

### Q-L1 ✅ (Score: 3/3)

**Judge Reasoning:** The Actual System Answer correctly identifies the Agent as 'Walt Flood Realty, a Hawaii sole proprietorship,' matching the Expected Ground Truth exactly. Additional context about the agreement does not contradict the core fact.

**Expected:** `Walt Flood Realty` (a Hawaii sole proprietorship)

---
### Q-L2 ✅ (Score: 3/3)

**Judge Reasoning:** The actual answer correctly identifies 'Contoso Ltd.' as the Owner in the property management agreement and is consistent with the expected ground truth, with no contradictions or missing key facts.

**Expected:** `Contoso Ltd.`

---
### Q-L3 ✅ (Score: 3/3)

**Judge Reasoning:** The actual answer correctly identifies the managed property address exactly as in the expected ground truth: '456 Palm Tree Avenue, Honolulu, HI 96815'. Additional details about the property name and unit number do not contradict the required answer.

**Expected:** `456 Palm Tree Avenue, Honolulu, HI 96815`

---
### Q-L4 ❌ (Score: 0/3)

**Judge Reasoning:** The expected ground truth clearly specifies the initial term start date as 2010-06-15, but the system answer incorrectly claims that the exact start date is not provided. This is a direct contradiction of the ground truth, so the answer is a failure.

**Expected:** `2010-06-15`

---
### Q-L5 ❌ (Score: 0/3)

**Judge Reasoning:** The correct answer is that a sixty (60) days written notice is required, but the system answer incorrectly states that no written notice period is specified and that the information was not found. This is a clear false negative.

**Expected:** `sixty (60) days written notice`

---
### Q-L6 ✅ (Score: 3/3)

**Judge Reasoning:** The actual answer correctly states that the agent fee/commission for short-term rentals (<180 days) is twenty five percent (25%) of the gross revenues, matching the expected ground truth. Extra details do not contradict the core fact.

**Expected:** `twenty five percent (25%) of the gross revenues`

---
### Q-L7 ✅ (Score: 3/3)

**Judge Reasoning:** The Actual System Answer correctly states that the agent fee/commission for long-term leases (>180 days) is ten percent (10%) of the gross revenues, matching the Expected Ground Truth. Extra context about short-term rentals does not contradict the core fact.

**Expected:** `ten percent (10%) of the gross revenues`

---
### Q-L8 ❌ (Score: 0/3)

**Judge Reasoning:** The system answer says the information was not found, but the ground truth clearly provides the specific dollar amounts. This is a false negative and does not answer the user’s query.

**Expected:** `$75.00/month advertising; $50.00/month minimum admin/accounting`

---
### Q-L9 ✅ (Score: 3/3)

**Judge Reasoning:** The Actual System Answer exactly matches the Expected Ground Truth job location address and correctly identifies it as the job location in Exhibit A, with no contradictions or missing key details.

**Expected:** `811 Ocean Drive, Suite 405, Tampa, FL 33602`

---
### Q-L10 ✅ (Score: 3/3)

**Judge Reasoning:** The system answer exactly matches the expected ground truth, correctly identifying both the contact’s name (Elizabeth Nolasco) and email (enolasco@fabrikam.com) from the purchase contract Exhibit A, with no contradictions or missing details.

**Expected:** `Elizabeth Nolasco; enolasco@fabrikam.com`

---
### Q-N1 ✅ (Score: 3/3)

**Judge Reasoning:** The system correctly states that the bank routing number is not found in the provided documents, matching the expected ground truth that it is not specified.

**Expected:** Not specified.

---
### Q-N2 ✅ (Score: 3/3)

**Judge Reasoning:** The expected ground truth is that the IBAN/SWIFT is not specified, and the system answer correctly states it is not found in the provided documents. This matches perfectly with no contradictions.

**Expected:** Not specified.

---
### Q-N3 ✅ (Score: 3/3)

**Judge Reasoning:** The system correctly states that the VAT/Tax ID number is not found, which matches the expected ground truth of 'Not specified.'

**Expected:** Not specified.

---
### Q-N5 ✅ (Score: 3/3)

**Judge Reasoning:** The system correctly states that the bank account number for ACH/wire payments is not found in the provided documents, matching the expected ground truth of 'Not specified.'

**Expected:** Not specified.

---
### Q-N6 ✅ (Score: 3/3)

**Judge Reasoning:** The query is a negative test (California is not referenced). The system correctly responded that it was not found in the provided documents, matching the expected ground truth.

**Expected:** None (California not referenced).

---
### Q-N7 ✅ (Score: 3/3)

**Judge Reasoning:** The system answer correctly states that the property management Agent’s license number is not provided in the documents, matching the expected ground truth of 'Not specified,' and does not hallucinate any number.

**Expected:** Not specified.

---
### Q-N8 ✅ (Score: 3/3)

**Judge Reasoning:** The system answer correctly states that no wire transfer or ACH instructions are specified in the purchase contract and concludes that the requested information was not found, matching the expected ground truth of 'Not specified.'

**Expected:** Not specified.

---
### Q-N9 ✅ (Score: 3/3)

**Judge Reasoning:** The expected ground truth indicates that mold damage coverage is not specified, and the system answer correctly states that it is not found in the provided documents. This matches the negative expectation with no contradictions.

**Expected:** Not specified.

---
### Q-N10 ✅ (Score: 3/3)

**Judge Reasoning:** The system answer correctly states that the 'SHIPPED VIA' field is present but blank, matching the expected ground truth that the shipping method is not specified.

**Expected:** Not specified / blank.

---
