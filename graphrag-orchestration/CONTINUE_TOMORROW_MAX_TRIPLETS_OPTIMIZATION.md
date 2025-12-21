# Continue Tomorrow: max_triplets_per_chunk Optimization

**Date:** December 21, 2024  
**Status:** Ready to test

---

## What We Accomplished Today

### 1. ✅ Verified Current Performance (EXCELLENT!)
- **Baseline (3 days ago, max_triplets=20):** 352 entities, 440 relationships
- **Current (max_triplets=80):** 664 entities, 786 relationships
- **Improvement:** +88% entities, +78% relationships
- **Finding:** DI page grouping + max_triplets increase = massive improvement

### 2. ✅ Established Quality Criteria
- **Target:** 95-99% precision (1-5% false entities acceptable)
- **Zero tolerance:** Hallucinations (completely fabricated entities)
- **Acceptable:** Boundary cases (debatable entities, over-extraction of minor details)
- **Rationale:** 
  - Human inter-annotator agreement: 85-92%
  - Industry standards: 90-95% precision
  - Precision-recall tradeoff: accepting 2% false entities can yield 2.5x more true entities

### 3. ✅ Industry Research
- **LlamaIndex default:** max_triplets_per_chunk=10
- **Neo4j recommendation:** 20-30 for quality
- **Microsoft approach:** Unlimited with multi-pass validation (4-5x slower/expensive)
- **Our choice:** Systematic testing to find sweet spot

### 4. ✅ Created Test Script
- **File:** `test_max_triplets_optimization.sh` (ready to run)
- **Tests:** 20, 40, 80
- **Time:** ~30 minutes total
- **Fixed:** API validation error (document-intelligence vs document_intelligence)

---

## What to Do Tomorrow

### Step 1: Run the Test
```bash
cd /afh/projects/graphrag-orchestration/graphrag-orchestration
chmod +x test_max_triplets_optimization.sh
bash test_max_triplets_optimization.sh
```

**Expected output:**
- Updates code to each value (20, 40, 80)
- Deploys each version
- Submits indexing for all three
- Waits 6 minutes for completion
- Collects entity/relationship/community counts
- Saves 15 entity samples per test to `/tmp/samples_*.json`
- Saves full results to `/tmp/max_triplets_results_*.txt`

### Step 2: Review Quality Samples
```bash
# Review entity samples for each test
cat /tmp/samples_20.json
cat /tmp/samples_40.json
cat /tmp/samples_80.json
```

**Quality checklist for each entity:**
- ✅ Real entity mentioned in source docs
- ✅ Description accurate
- ⚠️ Borderline (minor detail, debatable)
- ❌ False entity (not in docs)
- 🚫 HALLUCINATION (fabricated information)

**Calculate precision:**
```
Precision = (Real entities + Borderline entities) / Total entities
```

### Step 3: Analyze Results

**Look for patterns:**
1. **Entity count:** Does it plateau or keep increasing?
2. **Quality degradation:** Does precision drop at higher values?
3. **Sweet spot:** Where do we get max entities with 95-99% precision?

**Expected scenarios:**
- **If 80 is still high quality (>95%):** Test higher values (100, 120, 150)
- **If 80 shows degradation (<95%):** 40 or 60 might be optimal
- **If all three are good:** 80 is the winner (already deployed)

### Step 4: Set Final Value

**Once optimal value is found:**
```bash
# Update to optimal value (example: 60)
sed -i 's/max_triplets_per_chunk=[0-9]\+/max_triplets_per_chunk=60/' app/v3/services/indexing_pipeline.py
bash deploy.sh
```

---

## Current State

### Neo4j Database
- **URI:** neo4j+s://a86dcf63.databases.neo4j.io
- **Current data:** phase1-5docs-1766334973 (664 entities with max_triplets=80)
- **Test groups will be:** max-triplets-20-*, max-triplets-40-*, max-triplets-80-*

### Code
- **File:** `app/v3/services/indexing_pipeline.py` (line ~732)
- **Current value:** `max_triplets_per_chunk=80`
- **Change committed:** Yes (94940c3)

### Processing Performance
- **Time:** 2 minutes (improved from 6-7 minutes via batch embeddings)
- **Documents:** 5 (Azure DI pages grouped by source URL)
- **Embeddings:** 3072-dim stored directly in Neo4j

---

## Key Files

1. **Test script:** `test_max_triplets_optimization.sh` (ready to run)
2. **Main code:** `app/v3/services/indexing_pipeline.py` (line ~732)
3. **Results:** `/tmp/max_triplets_results_*.txt` (after test)
4. **Quality samples:** `/tmp/samples_{20,40,80}.json` (after test)

---

## Decision Framework

### If Quality Remains High (>95% precision at max_triplets=80)
- **Action:** Test higher values (100, 120, 150)
- **Goal:** Find where quality degrades or plateau occurs
- **Timeline:** Another 30-minute test tomorrow

### If Quality Degrades (80 drops below 95%)
- **Action:** Test intermediate values (30, 50, 60)
- **Goal:** Find the highest value that maintains quality
- **Timeline:** Another 30-minute test tomorrow

### If 40-60 is the Sweet Spot
- **Action:** Fine-tune (45, 50, 55) if needed
- **Goal:** Maximize within quality constraints
- **Timeline:** Optional, only if marginal gains matter

---

## Questions to Answer

1. **Does entity count plateau?** (diminishing returns after certain value)
2. **Where does quality degrade?** (precision drops below 95%)
3. **Are there hallucinations?** (fabricated entities not in source)
4. **What's the optimal value?** (max entities at 95-99% precision)
5. **Is 80 good enough?** (already 88% improvement over baseline)

---

## Notes

- **API format:** Use `document-intelligence` (hyphen), not `document_intelligence` (underscore)
- **Wait time:** 6 minutes for indexing (not 2 minutes - learned today)
- **Quality focus:** We prioritize quality over quantity (1-5% error tolerance)
- **Baseline:** Keep in mind we're already 88% above baseline with max_triplets=80

---

## Expected Timeline Tomorrow

- **9:00 AM:** Run test script (~30 min)
- **9:30 AM:** Review quality samples (~15 min)
- **9:45 AM:** Analyze patterns, calculate precision (~15 min)
- **10:00 AM:** Decision on optimal value
- **10:15 AM:** Deploy final configuration
- **DONE** ✅
