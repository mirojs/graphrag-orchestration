# Route 3 Thematic Question Bank

## Purpose
This question bank is designed specifically for Route 3 (Global Search / LazyGraphRAG) evaluation.
Route 3 excels at **thematic synthesis** and **cross-document analysis**, not precise fact extraction.

## Evaluation Criteria
- **Entity Discovery**: Does it find relevant entities across documents?
- **Theme Coverage**: Does it identify the main themes?
- **Cross-Document Synthesis**: Does it connect information from multiple sources?
- **Coherence**: Is the response well-structured and logical?

---

## Thematic Questions (T-1 to T-10)

**T-1:** What are the common themes across all the contracts and agreements in these documents?
- **Expected Themes**: legal obligations, payment terms, termination clauses, liability provisions, dispute resolution
- **Expected Entity Types**: parties, dates, monetary values, legal terms

**T-2:** How do the different parties relate to each other across the documents?
- **Expected Themes**: contractual relationships, service providers, clients, third parties
- **Expected Entity Types**: organization names, person names, roles

**T-3:** What patterns emerge in the financial terms and payment structures?
- **Expected Themes**: payment schedules, amounts, penalties, invoicing
- **Expected Entity Types**: dollar amounts, percentages, dates, payment terms

**T-4:** Summarize the risk management and liability provisions across all documents.
- **Expected Themes**: indemnification, limitation of liability, insurance requirements, warranties
- **Expected Entity Types**: coverage amounts, conditions, exclusions

**T-5:** What dispute resolution mechanisms are mentioned across the agreements?
- **Expected Themes**: arbitration, mediation, litigation, jurisdiction, governing law
- **Expected Entity Types**: legal entities (AAA), locations, time limits

**T-6:** How do the documents address confidentiality and data protection?
- **Expected Themes**: NDA provisions, data handling, privacy, disclosure limitations
- **Expected Entity Types**: information types, time periods, exceptions

**T-7:** What are the key obligations and responsibilities outlined for each party?
- **Expected Themes**: deliverables, timelines, performance standards, compliance
- **Expected Entity Types**: party names, deadlines, quality metrics

**T-8:** Compare the termination and cancellation provisions across the documents.
- **Expected Themes**: notice periods, grounds for termination, effects of termination, survival clauses
- **Expected Entity Types**: time periods, conditions, procedures

**T-9:** What insurance and indemnification requirements appear in the documents?
- **Expected Themes**: coverage types, minimum amounts, certificate requirements, named insureds
- **Expected Entity Types**: insurance types, dollar limits, carriers

**T-10:** Identify the key dates, deadlines, and time-sensitive provisions across all documents.
- **Expected Themes**: effective dates, expiration, renewal, notice periods, response times
- **Expected Entity Types**: specific dates, durations, milestones

---

## Cross-Document Questions (X-1 to X-5)

**X-1:** Which entities or concepts appear in multiple documents?
- **Evaluation**: Count of entities found in 2+ documents

**X-2:** What are the most important entities mentioned across the entire document set?
- **Evaluation**: Entity frequency and centrality in evidence path

**X-3:** How do the documents collectively define the business relationship?
- **Evaluation**: Synthesis quality, coherence across sources

**X-4:** What regulatory or compliance requirements are referenced across documents?
- **Evaluation**: Coverage of legal/regulatory themes

**X-5:** Summarize the overall contractual framework represented by these documents.
- **Evaluation**: High-level synthesis quality

---

## Ground Truth Format

For each question, ground truth consists of:
1. **Expected Entities** (list): Entities that should appear in hub_entities or evidence_path
2. **Expected Themes** (list): Topics that should be covered in the response
3. **Minimum Evidence Nodes**: Expected num_evidence_nodes threshold
4. **Cross-Document Flag**: Whether response should synthesize multiple documents

## Scoring Rubric

| Metric | Weight | Description |
|--------|--------|-------------|
| Entity Recall | 30% | % of expected entities found in evidence_path |
| Theme Coverage | 30% | % of expected themes addressed (LLM-judge) |
| Evidence Quality | 20% | num_evidence_nodes >= threshold |
| Coherence | 20% | Response structure and logical flow (LLM-judge) |
