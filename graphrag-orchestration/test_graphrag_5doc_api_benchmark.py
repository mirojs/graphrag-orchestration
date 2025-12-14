#!/usr/bin/env python3
"""
GraphRAG V2 API Benchmark - Uses deployed Container App endpoints.

This benchmark tests the V2 GraphRAG implementation via HTTP API calls
to the deployed Azure Container App service.
"""

import asyncio
import time
import httpx
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any

# Configuration
API_BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
GROUP_ID = "graphrag-5doc-v2-benchmark"


@dataclass
class TimingResult:
    stage: str
    duration: float
    details: str


# 5 diverse test documents
TEST_DOCUMENTS = [
    {
        "id": "doc-1-purchase-agreement",
        "title": "Real Estate Purchase Agreement",
        "content": """
REAL ESTATE PURCHASE AGREEMENT

This Agreement is made on November 15, 2024, between:

SELLER: John Smith, residing at 456 Oak Avenue, Seattle, WA 98101
BUYER: ABC Corporation, a Delaware corporation with principal offices at 
       500 Tech Plaza, Austin, TX 78701

PROPERTY: 123 Main Street, Seattle, WA 98101
         Legal Description: Lot 7, Block 3, Downtown Seattle Subdivision

PURCHASE PRICE: $500,000.00 (Five Hundred Thousand Dollars)

TERMS:
1. Earnest Money: Buyer shall deposit $50,000 with First National Bank 
   within 5 business days.
2. Financing: Buyer to obtain conventional mortgage within 45 days.
3. Inspection: 14-day inspection period from acceptance.
4. Closing Date: On or before December 31, 2024.

The property is sold AS-IS with all fixtures and improvements including:
- Central HVAC system (installed 2020)
- Kitchen appliances (refrigerator, stove, dishwasher)
- Window treatments throughout

CONTINGENCIES:
- Subject to buyer obtaining financing
- Subject to satisfactory property inspection
- Subject to clear title report

SIGNATURES:
_________________________          _________________________
John Smith, Seller                 ABC Corporation, Buyer
                                   By: Sarah Williams, CFO
"""
    },
    {
        "id": "doc-2-invoice",
        "title": "Elevator Maintenance Invoice",
        "content": """
CONTOSO LIFTS INC.
INVOICE

Invoice Number: INV-2024-1847
Invoice Date: November 22, 2024

BILL TO:
ABC Corporation
500 Tech Plaza
Austin, TX 78701
Attn: Facilities Department

DATE: November 20, 2024
DUE DATE: December 20, 2024
TERMS: Net 30

SERVICES PROVIDED:

1. Quarterly Elevator Maintenance - Building A (2 elevators)
   - Safety system inspection and testing
   - Lubrication of all moving components  
   - Door alignment and adjustment
   - Emergency phone system test
   Unit Price: $500.00 each x 2 = $1,000.00

2. Parts Replacement
   - Control panel circuit board (Elevator #1): $450.00
   - Door sensor replacement (Elevator #2): $200.00
   Parts Subtotal: $650.00

3. Emergency Call-Out (November 5, 2024)
   - After-hours response to stuck elevator
   - Labor: 3 hours @ $150/hour = $450.00

SUBTOTAL: $2,100.00
TAX (8.25%): $173.25
TOTAL DUE: $2,273.25

Please remit payment to: Contoso Lifts Inc., Account #44521
Annual service contract renewal available - 10% discount on labor rates.
"""
    },
    {
        "id": "doc-3-board-minutes",
        "title": "Board Meeting Minutes",
        "content": """
ABC CORPORATION
BOARD OF DIRECTORS MEETING MINUTES

Date: November 18, 2024
Time: 2:00 PM - 4:30 PM
Location: Corporate Headquarters, Conference Room A
Recording Secretary: Lisa Park, Executive Assistant

ATTENDEES:
- John Smith, CEO and Chairman
- Sarah Williams, CFO
- Robert Chen, COO  
- Dr. Emily Watson, Independent Director
- Michael Torres, Independent Director

ABSENT: None

AGENDA ITEMS:

1. CALL TO ORDER
   Meeting called to order at 2:05 PM by Chairman John Smith.

2. APPROVAL OF PREVIOUS MINUTES
   Motion to approve October 2024 minutes by Sarah Williams, seconded by Robert Chen.
   APPROVED unanimously.

3. FINANCIAL REPORT (Sarah Williams)
   - Q3 2024 revenue: $12.5 million (up 15% YoY)
   - Operating expenses: $9.2 million
   - Net profit margin: 26.4%
   - Cash reserves: $8.3 million
   Motion to accept financial report: APPROVED unanimously.

4. REAL ESTATE ACQUISITION UPDATE (John Smith)
   - 123 Main Street property purchase on track
   - Due diligence 80% complete
   - First National Bank financing confirmed
   - Expected closing: December 31, 2024
   - Total investment: $500,000 purchase + $200,000 renovations
   Board reaffirms approval of acquisition.

5. OPERATIONS UPDATE (Robert Chen)
   - New Seattle distribution center operational
   - Contoso Lifts service contract renewed for 2025
   - Employee headcount: 156 (up from 142 in Q2)
   - Customer satisfaction score: 94%

6. STRATEGIC INITIATIVES
   - Partnership with Fabrikam Industries for Q1 2025 product launch
   - Expansion into Portland market approved
   - Technology upgrade budget: $500,000 for 2025

7. EXECUTIVE COMPENSATION
   - Annual bonus pool approved: $1.2 million
   - CEO salary adjustment: 5% increase effective January 2025

8. NEXT MEETING
   Scheduled for December 16, 2024, 2:00 PM

Meeting adjourned at 4:25 PM.
"""
    },
    {
        "id": "doc-4-service-contract",
        "title": "Annual Service Agreement",
        "content": """
ANNUAL SERVICE AGREEMENT

Agreement Number: SA-2025-0042
Effective Date: January 1, 2025
Expiration Date: December 31, 2025

PARTIES:

SERVICE PROVIDER:
Contoso Lifts Inc.
456 Industrial Blvd, Seattle, WA 98101
Tax ID: 91-1234567
Representative: David Park, Director of Operations
Email: dpark@contosolifts.com

CLIENT:
ABC Corporation
500 Tech Plaza, Austin, TX 78701
Tax ID: 84-7654321
Representative: Robert Chen, Chief Operating Officer
Email: rchen@abccorp.com

SCOPE OF SERVICES:

1. PREVENTIVE MAINTENANCE
   - Monthly inspection of all elevator systems
   - Quarterly comprehensive maintenance
   - Annual safety certification
   - 24/7 emergency response hotline

2. COVERED EQUIPMENT
   Location: 500 Tech Plaza, Austin, TX
   - Passenger Elevator #1 (Capacity: 2,500 lbs)
   - Passenger Elevator #2 (Capacity: 2,500 lbs)
   - Freight Elevator #3 (Capacity: 5,000 lbs)

3. RESPONSE TIMES
   - Emergency calls: 2-hour response
   - Standard service requests: 24-hour response
   - Parts replacement: 48-hour maximum

4. PRICING
   Annual Service Fee: $18,000 ($1,500/month)
   Parts and Materials: Cost + 15% markup
   After-hours labor: $175/hour (vs. standard $150/hour)
   
5. PAYMENT TERMS
   - Quarterly invoicing in advance
   - Payment due within 30 days
   - 2% discount for annual prepayment

6. TERM AND TERMINATION
   - Auto-renewal unless 60-day written notice
   - Early termination fee: 3 months service charge

APPROVED AND ACCEPTED:

_________________________          _________________________
David Park                         Robert Chen
Contoso Lifts Inc.                ABC Corporation
Date: December 1, 2024            Date: December 1, 2024
"""
    },
    {
        "id": "doc-5-partnership-proposal",
        "title": "Strategic Partnership Proposal",
        "content": """
STRATEGIC PARTNERSHIP PROPOSAL

CONFIDENTIAL

FROM: Fabrikam Industries
TO: ABC Corporation
DATE: November 25, 2024
PREPARED BY: Jennifer Lee, VP of Business Development

EXECUTIVE SUMMARY:

Fabrikam Industries proposes a strategic partnership with ABC Corporation to jointly 
develop and market next-generation smart building solutions. This partnership leverages 
Fabrikam's IoT expertise and ABC Corporation's market presence.

COMPANY OVERVIEW - FABRIKAM INDUSTRIES:
- Founded: 2010
- Headquarters: 789 Innovation Drive, Portland, OR 97201
- CEO: Thomas Anderson
- Annual Revenue: $45 million (2023)
- Employees: 280
- Specialization: IoT sensors, building automation, energy management

PARTNERSHIP OBJECTIVES:

1. PRODUCT DEVELOPMENT
   - Joint development of SmartBuilding 3.0 platform
   - Integration of Fabrikam sensors with ABC building systems
   - Target launch: Q2 2025
   - Combined R&D investment: $2 million

2. MARKET EXPANSION
   - Co-branded product line
   - Shared distribution network
   - Target markets: Pacific Northwest, Texas, California
   - Revenue target: $10 million in Year 1

3. TECHNOLOGY SHARING
   - Fabrikam provides: IoT platform, sensor technology, data analytics
   - ABC provides: Customer relationships, installation expertise, support infrastructure

FINANCIAL TERMS:

- Revenue sharing: 60% ABC / 40% Fabrikam
- Initial investment: $500,000 each party
- Milestone payments tied to product development
- Exclusivity period: 24 months

KEY MILESTONES:

Phase 1 (Jan-Mar 2025): Platform integration and beta testing
Phase 2 (Apr-Jun 2025): Pilot deployments with 5 customers
Phase 3 (Jul-Dec 2025): Full market launch and scaling

CONTACT:

Jennifer Lee
VP Business Development, Fabrikam Industries
Email: jlee@fabrikam.com
Phone: (503) 555-0456

We look forward to discussing this opportunity further.
"""
    }
]

# Test queries
TEST_QUERIES = [
    "What is the relationship between ABC Corporation and Contoso Lifts?",
    "Who are the key executives at ABC Corporation and what are their roles?",
    "What financial information is mentioned across the documents?",
    "What are the details of the real estate purchase?",
    "Describe the partnership between ABC Corporation and Fabrikam Industries.",
    "What services does Contoso Lifts provide and at what cost?",
    "Summarize all the business relationships and contracts mentioned.",
]


async def index_document(client: httpx.AsyncClient, doc: dict) -> dict:
    """Index a single document via V2 API."""
    response = await client.post(
        f"{API_BASE_URL}/graphrag/v2/index/text",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={
            "text": doc["content"],
            "document_name": doc["title"],
        },
        timeout=120.0,
    )
    return response.json()


async def query_local(client: httpx.AsyncClient, query: str) -> dict:
    """Execute local search query via API."""
    response = await client.post(
        f"{API_BASE_URL}/graphrag/v2/query/local",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"query": query, "top_k": 5},
        timeout=60.0,
    )
    return response.json()


async def query_hybrid(client: httpx.AsyncClient, query: str) -> dict:
    """Execute hybrid search query via API."""
    response = await client.post(
        f"{API_BASE_URL}/graphrag/v2/query/hybrid",
        headers={"X-Group-ID": GROUP_ID, "Content-Type": "application/json"},
        json={"query": query, "top_k": 5},
        timeout=60.0,
    )
    return response.json()


async def main():
    """Run the V2 API benchmark."""
    timings: List[TimingResult] = []
    total_start = time.time()
    
    print("=" * 80)
    print("NEO4J GRAPHRAG V2 API BENCHMARK")
    print(f"Endpoint: {API_BASE_URL}")
    print(f"Group ID: {GROUP_ID}")
    print("=" * 80)
    
    async with httpx.AsyncClient() as client:
        # Check health
        print("\n[HEALTH] Checking API health...")
        try:
            health = await client.get(f"{API_BASE_URL}/health", timeout=10.0)
            print(f"    Status: {health.status_code}")
        except Exception as e:
            print(f"    Error: {e}")
            return
        
        # =====================================================================
        # PHASE 1: DOCUMENT INDEXING
        # =====================================================================
        print("\n" + "=" * 80)
        print("PHASE 1: DOCUMENT INDEXING")
        print("=" * 80)
        
        indexing_start = time.time()
        doc_timings: List[Tuple[str, float, str]] = []
        
        for i, doc in enumerate(TEST_DOCUMENTS, 1):
            doc_start = time.time()
            print(f"\n[{i}/5] Indexing: {doc['title']}")
            
            try:
                result = await index_document(client, doc)
                doc_time = time.time() - doc_start
                status = result.get("status", "unknown")
                doc_timings.append((doc["title"], doc_time, status))
                print(f"       Status: {status}")
                print(f"       Time: {doc_time:.2f}s")
            except Exception as e:
                doc_time = time.time() - doc_start
                doc_timings.append((doc["title"], doc_time, f"error: {e}"))
                print(f"       Error: {e}")
        
        indexing_time = time.time() - indexing_start
        timings.append(TimingResult("Document Indexing (Total)", indexing_time, f"{len(TEST_DOCUMENTS)} documents"))
        
        print(f"\n    INDEXING SUMMARY:")
        print(f"    Total time: {indexing_time:.2f}s")
        print(f"    Average per doc: {indexing_time/5:.2f}s")
        
        # =====================================================================
        # PHASE 2: LOCAL SEARCH QUERIES
        # =====================================================================
        print("\n" + "=" * 80)
        print("PHASE 2: LOCAL SEARCH QUERIES")
        print("=" * 80)
        
        query_timings: List[Tuple[str, float, str]] = []
        
        for i, query in enumerate(TEST_QUERIES, 1):
            print(f"\n[Q{i}] {query}")
            print("-" * 60)
            
            query_start = time.time()
            try:
                response = await query_local(client, query)
                query_time = time.time() - query_start
                
                answer = response.get("answer", "No answer")
                sources_count = len(response.get("sources", []))
                answer_preview = answer[:250] + "..." if len(answer) > 250 else answer
                
                query_timings.append((query[:50] + "...", query_time, "local"))
                
                print(f"    Time: {query_time:.2f}s")
                print(f"    Sources: {sources_count}")
                print(f"    Answer: {answer_preview}")
                
            except Exception as e:
                query_time = time.time() - query_start
                query_timings.append((query[:50] + "...", query_time, f"error: {e}"))
                print(f"    Error: {e}")
        
        avg_query_time = sum(t for _, t, _ in query_timings) / len(query_timings) if query_timings else 0
        timings.append(TimingResult("Local Query (Average)", avg_query_time, f"{len(TEST_QUERIES)} queries"))
        
        # =====================================================================
        # PHASE 3: HYBRID SEARCH
        # =====================================================================
        print("\n" + "=" * 80)
        print("PHASE 3: HYBRID SEARCH")
        print("=" * 80)
        
        hybrid_query = "What is the total value of all contracts and agreements?"
        print(f"\n[HYBRID] {hybrid_query}")
        print("-" * 60)
        
        hybrid_start = time.time()
        try:
            response = await query_hybrid(client, hybrid_query)
            hybrid_time = time.time() - hybrid_start
            
            answer = response.get("answer", "No answer")
            sources_count = len(response.get("sources", []))
            
            timings.append(TimingResult("Hybrid Query", hybrid_time, "Vector + Fulltext"))
            
            print(f"    Time: {hybrid_time:.2f}s")
            print(f"    Sources: {sources_count}")
            print(f"    Answer: {answer[:400]}..." if len(answer) > 400 else f"    Answer: {answer}")
            
        except Exception as e:
            hybrid_time = time.time() - hybrid_start
            print(f"    Error: {e}")
    
    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    total_time = time.time() - total_start
    
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 80)
    
    print("\n📊 DOCUMENT INDEXING BREAKDOWN:")
    print("-" * 60)
    for title, doc_time, status in doc_timings:
        print(f"  {title:40} {doc_time:6.2f}s  [{status}]")
    
    print("\n⏱️  STAGE TIMING SUMMARY:")
    print("-" * 60)
    for timing in timings:
        print(f"  {timing.stage:40} {timing.duration:8.2f}s  [{timing.details}]")
    
    print("\n🔍 QUERY TIMING BREAKDOWN:")
    print("-" * 60)
    for query, query_time, mode in query_timings:
        print(f"  {query:50} {query_time:6.2f}s  [{mode}]")
    
    print("\n" + "=" * 80)
    print(f"📈 TOTAL BENCHMARK TIME: {total_time:.2f}s")
    print("=" * 80)
    
    print("\n📋 KEY METRICS:")
    print(f"  • Documents indexed: {len(TEST_DOCUMENTS)}")
    print(f"  • Queries executed: {len(TEST_QUERIES) + 1}")
    print(f"  • Avg indexing time: {indexing_time/5:.2f}s")
    print(f"  • Avg query time: {avg_query_time:.2f}s")
    print(f"  • API Base: {API_BASE_URL}")


if __name__ == "__main__":
    asyncio.run(main())
