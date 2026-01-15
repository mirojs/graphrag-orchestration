# Question Bank: Route 4 Deep Reasoning & Inference (2026 Edition)

**Target Route:** Route 4 (DRIFT Multi-Hop)
**Core Competency:** Ambiguity Resolution, Implicit Discovery, Inference, Conflict Resolution
**Reference Documents:** Warranty (Fabrikam), Property Mgmt (Walt Flood), Invoice (Contoso), Purchase Contract (Contoso), Holding Tank Contract.

---

## Category 1: Implicit Entity Discovery (The "Chain" Test)

*Questions that require finding an entity mid-stream without it being named in the prompt.*

**Q-DR1:** "Identify the vendor responsible for the vertical platform lift maintenance. Does their invoice's payment schedule match the terms in the original Purchase Agreement?"
*   **Reasoning Chain:**
    1.  Search "vertical platform lift" -> Find Invoice #1256003.
    2.  Identify Vendor: "Contoso Lifts LLC".
    3.  Retrieve "Purchase Agreement" between Fabrikam and Contoso.
    4.  Extract Payment Terms from Invoice (Installments).
    5.  Extract Payment Terms from Contract.
    6.  Compare and conclude.
*   **Expected Answer:** Yes/No with specific comparison of the installments ($20k/$7k/$2.9k).

**Q-DR2:** "Who provides the insurance coverage for the property located at the detailed address found in the Property Management Agreement? Does this coverage explicitly exclude 'emergency defects' defined in the Builder's Warranty?"
*   **Reasoning Chain:**
    1.  Find Property Mgmt Agreement -> Extract Address (456 Palm Tree Ave).
    2.  Identify Insurer/Owner responsibilities.
    3.  Find Builder's Warranty -> Define "Emergency Defects".
    4.  Cross-reference exclusions.

## Category 2: logical Inference (The "Rule Application" Test)

*Questions that require applying abstract rules to concrete scenarios.*

**Q-DR3:** "A pipe burst in the kitchen (emergency) on a Sunday. If the homeowner notifies the Builder via certified mail the next day, is this considered valid notice under the Warranty terms?"
*   **Reasoning Chain:**
    1.  Classify "pipe burst" as Emergency (based on Warranty definition).
    2.  Find Warranty Notification Rule for Emergencies (Startling/Phone requirement).
    3.  Compare "Certified Mail" vs "Phone".
    4.  Infer: Invalid/Delayed notice (Mail takes time, emergency requires immediate phone contact).

**Q-DR4:** "If the property 456 Palm Tree Avenue is sold today, what happens to a guest reservation confirmed for next month?"
*   **Reasoning Chain:**
    1.  Find Property Mgmt Agreement for this address.
    2.  Locate "Termination" or "Sale of Property" clause.
    3.  Apply rule: Reservations confirms prior to termination must be honored (or similar).

## Category 3: Ambiguity Resolution & Decomposition

*Questions that require defining terms before searching.*

**Q-DR5:** "Compare the strictness of the 'financial penalties' for early termination in the Property Management Agreement versus the Holding Tank Servicing Contract."
*   **Reasoning Chain:**
    1.  Decompose: "What are the financial penalties in Prop Mgmt?" vs "What are the financial penalties in Holding Tank?"
    2.  Search Prop Mgmt -> Find Termination Fee (e.g., all commissions due).
    3.  Search Holding Tank -> Find Cancellation Fee.
    4.  Compare strictness (monetary value or conditions).

**Q-DR6:** "Which document has the longest 'governing duration' or valid term?"
*   **Reasoning Chain:**
    1.  Identify all documents with terms (Warranty, Contracts).
    2.  Extract "Term" from each (1 year, 10 years, indefinite?).
    3.  Compare and rank.

## Category 4: Conflict Resolution

*Questions that require identifying conflicting truth.*

**Q-DR7:** "The Purchase Contract lists specific payment milestones. Do these match the line items or total on the Invoice #1256003?"
*   **Reasoning Chain:**
    1.  Extract milestones from Contract ($20k, $7k, $2.9k).
    2.  Extract lines/total from Invoice.
    3.  Verify if they align or if there is a discrepancy.

**Q-DR8:** "Does the Pumper address in the Holding Tank Contract match the Builder address in the Warranty?"
*   **Reasoning Chain:**
    1.  Extract Pumper Address (Fabrikam).
    2.  Extract Builder Address (Fabrikam).
    3.  Compare (Detection of potential entity aliasing or moving).

---

## Metric Adjustments for Route 4

For these questions, standard RAG metrics (Precision/Recall) are insufficient. We introduce:

1.  **Reasoning path Containment:** Does the answer cite *both* end-point documents?
2.  **Logical Validity:** Does the conclusion follow from the premises?
3.  **Conflict Acknowledgment:** (For Q-DR7/8) Does the answer explicitly state "The documents agree/disagree"?
