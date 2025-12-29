# Azure CU Standard vs LlamaParse Pricing Comparison

## Azure Content Understanding (Standard)

**Pricing Model:** Pay-per-page analyzed

### Current Pricing (December 2025)
- **Standard tier:** ~$0.01 - $0.015 per page
- **Volume discounts:** Available for 1M+ pages/month
- **Free tier:** First 500-1000 pages/month (Azure free credits)

### Cost Examples
| Volume | Cost per 1000 pages | Monthly cost (100K pages) |
|--------|---------------------|---------------------------|
| 0-10K pages | ~$10-15 | $1,000-1,500 |
| 10K-100K | ~$8-12 | $800-1,200 |
| 100K-1M | ~$5-8 | $500-800 |
| 1M+ | ~$3-5 | $300-500 |

**Notes:**
- Included in Azure consumption commitment
- No rate limits (enterprise SLA)
- Data stays in your Azure region
- Billed monthly on Azure invoice

---

## LlamaParse

**Pricing Model:** Tiered subscription + overage

### Current Pricing (December 2025)

**Free Tier:**
- 1,000 pages/day
- 7,000 pages/week
- Rate limited
- Community support

**Professional Tier:** $49/month
- 50,000 pages/month included
- $0.001 per page overage (1/10th of a cent)
- Higher rate limits
- Email support

**Enterprise Tier:** Custom pricing
- Volume discounts
- Dedicated support
- Custom SLA
- Private deployment options

### Cost Examples
| Volume | Tier | Monthly Cost |
|--------|------|--------------|
| 7K pages | Free | $0 |
| 30K pages | Pro | $49 |
| 50K pages | Pro | $49 |
| 100K pages | Pro | $49 + $50 overage = $99 |
| 500K pages | Pro | $49 + $450 overage = $499 |
| 1M pages | Enterprise | ~$500-800 (negotiated) |

---

## Side-by-Side Comparison

| Factor | Azure CU Standard | LlamaParse |
|--------|-------------------|------------|
| **Small volume (10K/month)** | ~$100-150 | $49 (Pro) |
| **Medium volume (100K/month)** | ~$500-800 | $99 (Pro + overage) |
| **Large volume (1M/month)** | ~$300-500 | ~$500-800 (Enterprise) |
| **Free tier** | 500-1K pages/month | 7K pages/week |
| **Rate limits** | None (enterprise SLA) | Yes (even on Pro) |
| **Data residency** | Your Azure region | LlamaCloud (US) |
| **Commitment** | Monthly Azure bill | Annual subscription recommended |
| **Integration** | Azure ecosystem | LlamaIndex ecosystem |
| **Support** | Azure support plans | Community/Email/Dedicated |

---

## Cost Optimization Strategies

### Use Azure CU if:
- ✅ You have Azure credits/commitment
- ✅ Need data to stay in your region (compliance)
- ✅ Processing > 50K pages/month consistently
- ✅ Need enterprise SLA and no rate limits
- ✅ Already using Azure ecosystem

**Cost advantage:** 30-50% cheaper at high volume + uses existing credits

### Use LlamaParse if:
- ✅ Processing < 50K pages/month
- ✅ Want fixed monthly cost (Pro tier)
- ✅ Don't have Azure credits
- ✅ Prefer external managed service
- ✅ Need best markdown quality (they optimize specifically for this)

**Cost advantage:** 50-70% cheaper for small/medium volumes

### Hybrid Strategy:
- Use free tier of both for development/testing
- LlamaParse for < 50K pages/month (cheaper)
- Azure CU for > 50K pages/month (better economics + uses credits)
- Switch based on monthly volume

---

## Your Situation (Azure Credits)

**Recommendation:** Azure CU Standard

**Why:**
1. **Free with credits:** You mentioned having free Azure credits
   - CU consumption counts toward commitment
   - Effective cost: $0 until credits exhausted
   
2. **Better integration:** Already using Azure ecosystem
   - Same authentication (Managed Identity)
   - Same monitoring (Application Insights)
   - Same networking (VNet/Private Link)
   
3. **No external dependency:** Data doesn't leave Azure
   - Compliance/security advantage
   - Lower latency (same region as your app)
   
4. **Scalability:** No rate limits
   - Can process large batches
   - No throttling during high load

**LlamaParse only makes sense if:**
- Credits run out and you need to minimize cash spend
- Processing < 30K pages/month (then Pro tier is cheaper)
- Need their specific markdown optimization (marginal)

---

## ROI Analysis

**Scenario:** 100K pages/month

| Option | Monthly Cost | Notes |
|--------|--------------|-------|
| Azure CU (with credits) | $0 | Until credits exhausted |
| Azure CU (no credits) | ~$600 | Volume pricing |
| LlamaParse Pro | $99 | $49 + $50 overage |

**Break-even:**
- LlamaParse cheaper if < 50K pages/month AND no Azure credits
- Azure CU cheaper if > 50K pages/month OR have credits

**Your case:** Azure credits available → Azure CU is $0 vs $99 for LlamaParse

---

## Bottom Line

**Use Azure CU Standard** for your implementation:
- Costs you nothing (Azure credits)
- Better data residency
- No rate limits
- Same quality output (after our conversion)
- Already provisioned

Keep LlamaParse code as backup option for users without Azure credits.
