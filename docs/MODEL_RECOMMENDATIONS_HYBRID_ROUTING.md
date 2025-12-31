# Model Recommendations: Hybrid Pipeline (3-Way & 4-Way Routing)

**Last Updated:** December 30, 2025  
**Architecture:** LazyGraphRAG + HippoRAG 2 Hybrid System  
**Profiles:** General Enterprise (4-way) | High Assurance (3-way)

---

## Executive Summary

This document provides Azure OpenAI model recommendations for the Hybrid Pipeline's intelligent routing system. The system supports two deployment profiles:

- **General Enterprise (4-way routing):** Routes 1, 2, 3, 4 enabled
- **High Assurance (3-way routing):** Routes 2, 3, 4 only (Route 1 disabled)

Model selection balances **cost**, **speed**, and **quality** across different query complexity levels.

---

## Available Azure OpenAI Models

Based on current deployment:

| Model Name | Type | Cost Tier | Speed | Best For |
|:-----------|:-----|:----------|:------|:---------|
| **gpt-4o-mini** | LLM | Low | Very Fast | Classification, simple tasks |
| **gpt-4o** | LLM | Medium | Fast | General reasoning, synthesis |
| **gpt-4.1** | LLM | High | Moderate | Complex reasoning, decomposition |
| **gpt-5.2** | LLM | Premium | Slower | Comprehensive reports, max quality |
| **text-embedding-3-large** | Embedding | Low | Fast | Vector search, community matching |

---

## Routing System Overview

```
┌──────────────────────────────────────────────────────┐
│           QUERY CLASSIFIER (Router)                  │
│           Model: gpt-4o-mini                         │
└──────────────────┬───────────────────────────────────┘
                   │
     ┌─────────────┼─────────────┬─────────────┐
     │             │             │             │
     ▼             ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
│ Route 1 │  │ Route 2 │  │ Route 3 │  │ Route 4 │
│ Vector  │  │ Local   │  │ Global  │  │ DRIFT   │
│ RAG     │  │ Search  │  │ Search  │  │ Multi-  │
│ (Fast)  │  │ (Graph) │  │(Graph+  │  │ Hop     │
│         │  │         │  │ PPR)    │  │ (PPR)   │
└─────────┘  └─────────┘  └─────────┘  └─────────┘
```

---

## Model Recommendations by Component

### 1. Router (Query Classifier)

**Component:** `app/hybrid/router/main.py` - `HybridRouter`  
**Task:** Classify query complexity and route to appropriate handler

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-4o-mini` | Fast, low-cost, sufficient for classification |
| **Environment Variable** | `HYBRID_ROUTER_MODEL` | Default: `gpt-4o-mini` |
| **Token Budget** | ~500 input / 100 output | Classification is simple |
| **Latency Target** | <500ms | Should not bottleneck routing |
| **Fallback** | Rule-based heuristics | If LLM unavailable |

**Why gpt-4o-mini?**
- Classification is a simple task (not reasoning-heavy)
- Fast response (<300ms typically)
- Cost-effective for high query volume
- Sufficient accuracy for 4-way routing decisions

---

### 2. Route 1: Vector RAG (Fast Lane)

**Profile:** General Enterprise only (disabled in High Assurance)  
**Use Case:** Simple fact lookups ("What is X's address?")

| Component | Model | Reasoning |
|:----------|:------|:----------|
| **Embeddings** | `text-embedding-3-large` | Standard for high-quality retrieval |
| **Synthesis** | `gpt-4o` | Fast, cost-effective for simple answers |

**Configuration:**
```python
AZURE_OPENAI_EMBEDDING_DEPLOYMENT = "text-embedding-3-large"
HYBRID_VECTOR_RAG_MODEL = "gpt-4o"  # Synthesis only
```

**Token Budget:** ~1,000 input / 200 output (single-chunk answers)

**Fallback Strategy:**
If Route 1 fails or is unavailable, automatically falls back to Route 2 (Local Search).

---

### 3. Route 2: Local Search (Entity-Focused)

**Profile:** Both General Enterprise and High Assurance  
**Use Case:** Entity-centric queries ("List all contracts with ABC Corp")

#### Stage 2.1: Entity Extraction

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Preferred** | NER model (deterministic) | Faster, no LLM cost |
| **Fallback Model** | `gpt-4o-mini` | If NER unavailable |
| **Environment Variable** | `HYBRID_NER_MODEL` | Default: `gpt-4o-mini` |

#### Stage 2.2: LazyGraphRAG Iterative Deepening

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-4o` | Good reasoning for relevance decisions |
| **Environment Variable** | `HYBRID_REASONING_MODEL` | Default: `gpt-4o` |
| **Token Budget** | ~3,000 input / 500 output | Multi-turn graph exploration |

#### Stage 2.3: Synthesis with Citations

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-4o` | Balanced speed/quality for reports |
| **Environment Variable** | `HYBRID_SYNTHESIS_MODEL` | Default: `gpt-4o` |
| **Token Budget** | ~8,000 input / 1,500 output | Comprehensive with citations |

**Total Route 2 Cost:** ~11,000 tokens/query (moderate)

---

### 4. Route 3: Global Search (Thematic + Detail Recovery)

**Profile:** Both General Enterprise and High Assurance  
**Use Case:** Thematic queries without explicit entities ("What are the main compliance risks?")

#### Stage 3.1: Community Matching

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `text-embedding-3-large` | Deterministic, no LLM needed |
| **Method** | Embedding cosine similarity | Fast, cacheable |

#### Stage 3.2: Hub Entity Extraction

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Method** | Graph topology (degree centrality) | Deterministic, algorithmic |
| **Model** | None | No LLM required |

#### Stage 3.3: HippoRAG PPR Tracing

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Method** | Personalized PageRank (algorithm) | Deterministic, no LLM |
| **Model** | None | Mathematical graph traversal |

#### Stage 3.4 & 3.5: Synthesis with Citations

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-5.2` | **Premium quality** for comprehensive reports |
| **Environment Variable** | `HYBRID_SYNTHESIS_MODEL` | Override: `gpt-5.2` for Route 3 |
| **Token Budget** | ~15,000 input / 3,000 output | Large context for detail preservation |
| **Cost Trade-off** | Higher cost, maximum quality | Worth it for thematic deep-dives |

**Why gpt-5.2 for Route 3?**
- Route 3 handles the most complex thematic queries
- Large context window needed (20+ evidence chunks)
- Detail preservation is critical (fine print must not be lost)
- These queries are typically infrequent but high-value

**Total Route 3 Cost:** ~18,000 tokens/query (high, but thorough)

---

### 5. Route 4: DRIFT Multi-Hop (Ambiguous Queries)

**Profile:** Both General Enterprise and High Assurance  
**Use Case:** Multi-hop, ambiguous queries ("Analyze risk exposure to tech vendors")

#### Stage 4.1: Query Decomposition

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-4.1` | **Strong reasoning** for ambiguity resolution |
| **Environment Variable** | `HYBRID_DECOMPOSITION_MODEL` | Default: `gpt-4.1` |
| **Token Budget** | ~1,500 input / 500 output | Decompose into 3-5 sub-questions |

**Why gpt-4.1?**
- Ambiguous queries require advanced reasoning
- Must identify implicit relationships and entities
- Critical first step (bad decomposition = bad results)

#### Stage 4.2: Iterative Entity Discovery

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-4o` | Per sub-question entity extraction |
| **Environment Variable** | `HYBRID_NER_MODEL` | Default: `gpt-4o` |
| **Token Budget** | ~2,000 input / 300 output × 3-5 sub-questions | Multi-turn |

#### Stage 4.3: Consolidated HippoRAG Tracing

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Method** | Personalized PageRank (algorithm) | Deterministic, no LLM |
| **Model** | None | Mathematical graph traversal |

#### Stage 4.4: Multi-Source Synthesis

| Aspect | Recommendation | Reasoning |
|:-------|:--------------|:----------|
| **Model** | `gpt-5.2` | **Maximum coherence** for complex answers |
| **Environment Variable** | `HYBRID_SYNTHESIS_MODEL` | Override: `gpt-5.2` for Route 4 |
| **Token Budget** | ~20,000 input / 4,000 output | Multi-source consolidation |

**Why gpt-5.2 for Route 4?**
- Must synthesize findings from multiple sub-questions
- Needs to maintain coherence across decomposed reasoning
- Highest complexity queries = premium model justified

**Total Route 4 Cost:** ~30,000 tokens/query (highest, but most complex)

---

## Cost & Latency Comparison

| Route | Profile | Model(s) | Est. Tokens | Est. Cost* | Est. Latency |
|:------|:--------|:---------|:------------|:-----------|:-------------|
| **Route 1** | General | gpt-4o | ~1,200 | $0.01 | 500ms |
| **Route 2** | Both | gpt-4o | ~11,000 | $0.09 | 3-5s |
| **Route 3** | Both | gpt-5.2 | ~18,000 | $0.35 | 8-12s |
| **Route 4** | Both | gpt-4.1 + gpt-5.2 | ~30,000 | $0.55 | 15-30s |

*Cost estimates based on approximate Azure OpenAI pricing (subject to change)

---

## Environment Variable Configuration

### Recommended Settings

```bash
# Router
HYBRID_ROUTER_MODEL="gpt-4o-mini"

# Route 1 (Vector RAG)
AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large"
HYBRID_VECTOR_RAG_MODEL="gpt-4o"

# Route 2 (Local Search)
HYBRID_NER_MODEL="gpt-4o-mini"          # Entity extraction
HYBRID_REASONING_MODEL="gpt-4o"         # Iterative deepening
HYBRID_SYNTHESIS_MODEL="gpt-4o"         # Default synthesis

# Route 3 (Global Search) - Override synthesis
HYBRID_GLOBAL_SYNTHESIS_MODEL="gpt-5.2"  # Premium for thematic queries

# Route 4 (DRIFT Multi-Hop) - Advanced reasoning
HYBRID_DECOMPOSITION_MODEL="gpt-4.1"     # Query decomposition
HYBRID_DRIFT_SYNTHESIS_MODEL="gpt-5.2"   # Final consolidation
```

### Cost-Optimized Settings (Budget Mode)

If cost is a primary concern:

```bash
# Router
HYBRID_ROUTER_MODEL="gpt-4o-mini"

# All routes use gpt-4o (no premium models)
HYBRID_SYNTHESIS_MODEL="gpt-4o"
HYBRID_GLOBAL_SYNTHESIS_MODEL="gpt-4o"
HYBRID_DECOMPOSITION_MODEL="gpt-4o"
HYBRID_DRIFT_SYNTHESIS_MODEL="gpt-4o"
```

**Trade-off:** ~60% cost reduction, slight quality reduction for complex queries

---

## 3-Way vs 4-Way Routing Model Selection

### General Enterprise (4-Way Routing)

**Routes Enabled:** 1, 2, 3, 4  
**Query Distribution (typical):**
- Route 1: ~60% (simple queries)
- Route 2: ~25% (entity-focused)
- Route 3: ~10% (thematic)
- Route 4: ~5% (multi-hop)

**Average Cost per Query:** ~$0.05 (weighted average)

### High Assurance (3-Way Routing)

**Routes Enabled:** 2, 3, 4 (Route 1 disabled)  
**Query Distribution (typical):**
- Route 2: ~70% (entity-focused)
- Route 3: ~20% (thematic)
- Route 4: ~10% (multi-hop)

**Average Cost per Query:** ~$0.15 (higher due to no Route 1 shortcuts)

**Why Higher Cost?**
- Every query uses graph-based retrieval (no shortcuts)
- Full audit trail for compliance
- Worth the cost for high-stakes industries (audit, finance, insurance)

---

## Model Selection Decision Matrix

| Query Characteristic | Recommended Route | Primary Model | Reasoning |
|:---------------------|:------------------|:--------------|:----------|
| Simple fact lookup | Route 1 (General) | gpt-4o | Fast, cheap |
| Explicit entity | Route 2 | gpt-4o | Balanced |
| Thematic/summary | Route 3 | gpt-5.2 | Quality critical |
| Multi-hop/ambiguous | Route 4 | gpt-4.1 + gpt-5.2 | Complex reasoning |
| High Assurance (any) | Never Route 1 | gpt-4o or gpt-5.2 | Audit trail required |

---

## Performance Tuning Recommendations

### 1. Token Budget Optimization

**Synthesis Stage (All Routes):**
- **Input context limit:** Cap at 20,000 tokens to avoid latency spikes
- **Output token limit:** Set max_tokens=3000 for detailed reports
- **Truncation strategy:** Prioritize high-PPR-score chunks when capping

### 2. Model Fallback Strategy

```python
# Primary: gpt-5.2 for Route 3/4 synthesis
# Fallback: gpt-4o if gpt-5.2 unavailable or times out
# Emergency: gpt-4o-mini with quality warning
```

### 3. Caching Opportunities

| Component | Cacheable? | Cache Key | TTL |
|:----------|:-----------|:----------|:----|
| Router classification | ✅ Yes | Query hash | 5 min |
| Community embeddings | ✅ Yes | Query embedding | 1 hour |
| PPR results | ✅ Yes | (seeds, group_id) | 24 hours |
| Entity extractions | ❌ No | Query-specific | N/A |
| LLM syntheses | ❌ No | Non-deterministic | N/A |

**Caching PPR Results:**
Since HippoRAG PPR is deterministic (same seeds = same results), cache results for 24 hours to save computation.

---

## Monitoring & Metrics

### Key Metrics to Track

1. **Route Distribution:** Which routes are used most often?
2. **Model Usage:** Token consumption per route
3. **Latency:** p50, p95, p99 per route
4. **Cost:** Daily/weekly spend per route
5. **Fallback Rate:** How often Route 1 falls back to Route 2?

### Recommended Logging

```python
logger.info("model_usage",
           route=route_name,
           model=model_name,
           input_tokens=input_tokens,
           output_tokens=output_tokens,
           latency_ms=latency_ms,
           cost_usd=cost_estimate)
```

---

## Deployment Profile Recommendations by Industry

| Industry | Recommended Profile | Primary Routes | Model Budget |
|:---------|:-------------------|:---------------|:-------------|
| Customer Support | General Enterprise | 1, 2 | Low (gpt-4o) |
| Internal Wiki | General Enterprise | 1, 2, 3 | Low-Medium |
| Financial Audit | High Assurance | 2, 3, 4 | High (gpt-5.2) |
| Legal Discovery | High Assurance | 2, 3, 4 | High (gpt-5.2) |
| Compliance | High Assurance | 2, 3 | Medium-High |
| Insurance Claims | High Assurance | 2, 4 | High (gpt-4.1/5.2) |

---

## Summary & Quick Reference

### Recommended Model Assignments

| Component | Default Model | Override (Premium) | Use Case |
|:----------|:--------------|:------------------|:---------|
| Router | gpt-4o-mini | N/A | All queries |
| Route 1 Synthesis | gpt-4o | N/A | Fast lane |
| Route 2 Synthesis | gpt-4o | N/A | Standard reports |
| Route 3 Synthesis | gpt-4o | **gpt-5.2** | Thematic deep-dives |
| Route 4 Decomposition | gpt-4o | **gpt-4.1** | Ambiguity resolution |
| Route 4 Synthesis | gpt-4o | **gpt-5.2** | Multi-source consolidation |

### Cost Optimization Tips

1. **Use Route 1 aggressively** (General Enterprise): ~60% of queries can be simple lookups
2. **Cache PPR results:** Deterministic = cacheable
3. **Budget mode:** Use gpt-4o everywhere if cost-constrained
4. **Premium mode:** Use gpt-5.2 for Routes 3 & 4 if quality is paramount

### Quality Optimization Tips

1. **Always use gpt-5.2 for Route 3/4 synthesis** (High Assurance)
2. **Always use gpt-4.1 for Route 4 decomposition** (ambiguous queries)
3. **Set response_type="audit_trail"** for maximum detail
4. **Increase PPR top_k** (20-30) for thorough evidence collection

---

**Next Steps:**
1. Configure environment variables per deployment profile
2. Monitor query distribution to optimize route thresholds
3. A/B test gpt-4o vs gpt-5.2 for Route 3/4 synthesis to validate quality improvement
4. Set up cost alerts per route for budget tracking

**Questions?** See [ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md](../ARCHITECTURE_DESIGN_LAZY_HIPPO_HYBRID.md) for architectural context.
