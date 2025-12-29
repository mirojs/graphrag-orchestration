# Question Bank — Hybrid Router (3-Route)
**Date:** 2025-12-29

Purpose: A lightweight question set used to validate the **3-way HybridRouter** behavior without requiring any external services.

Routing expectations:
- **Profile A (General Enterprise):** Route 1 + Route 2 + Route 3
- **Profile B (High Assurance):** Route 2 + Route 3 (Route 1 disabled)
- **Profile C (Speed Critical):** Route 1 + Route 2 (Route 3 disabled)

---

## A) Vector / Fast-Lane Questions
These are phrased as simple fact lookups. Under Profile A, they should be eligible for Route 1.

1. **Q-V1:** What is the invoice total amount?
2. **Q-V2:** What is the due date?
3. **Q-V3:** Who is the salesperson?

---

## B) Local / Entity-Focused Questions
These are entity-centric and typically benefit from Route 2.

1. **Q-L1:** List all contracts with Vendor ABC and their payment terms.
2. **Q-L2:** What are all obligations for Contoso Ltd. in the property management agreement?
3. **Q-L3:** What is the approval threshold requiring prior written approval for expenditures?

---

## C) Global / Cross-Document Questions
These are cross-section policy-style questions that should go through Route 2 (Local/Global equivalent).

1. **Q-G1:** Across the agreements, summarize termination and cancellation rules.
2. **Q-G2:** Identify which documents reference governing law or jurisdiction.
3. **Q-G3:** Summarize who pays what across the set (fees, charges, taxes).

---

## D) DRIFT / Multi-Hop Reasoning Questions
These are multi-hop or ambiguous prompts designed to make Route 3 relevant in Profile A.

1. **Q-D1:** Analyze our overall risk exposure through subsidiaries and trace the relationship between entities across all related parties in general.
2. **Q-D2:** Compare time windows across the set and list all explicit day-based timeframes.
3. **Q-D3:** Explain the implications of the dispute resolution mechanisms across the agreements.
