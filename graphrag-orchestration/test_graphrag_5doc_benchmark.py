"""
Microsoft GraphRAG 5-Document Benchmark Test with Detailed Timing.

Tests the full pipeline with 5 diverse documents and records:
- Per-document extraction time
- Embedding generation time
- Neo4j upsert time
- Community building time (Leiden clustering)
- Community summarization time
- Query response time
"""

import logging
import time
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass

from llama_index.core.schema import TextNode
from llama_index.core.graph_stores.types import EntityNode, Relation

from app.services.graphrag_store import GraphRAGStore
from app.services.graphrag_extractor import SimpleGraphRAGExtractor
from app.services.graphrag_query_engine import GraphRAGQueryEngine
from app.services.llm_service import LLMService
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test group ID for isolation
GROUP_ID = "graphrag-5doc-benchmark"


@dataclass
class TimingResult:
    """Stores timing for each operation."""
    stage: str
    duration: float
    details: str = ""


# 5 diverse test documents
TEST_DOCUMENTS = [
    {
        "id": "doc-1-purchase-agreement",
        "title": "Real Estate Purchase Agreement",
        "content": """
REAL ESTATE PURCHASE AGREEMENT

This Purchase Agreement is entered into on November 15, 2024, between:

BUYER: ABC Corporation, a Delaware corporation, represented by John Smith, CEO
Address: 500 Tech Plaza, Austin, TX 78701

SELLER: XYZ Properties LLC, a California limited liability company, represented by Jane Doe, Managing Partner
Address: 200 Market Street, San Francisco, CA 94102

PROPERTY: The commercial building located at 123 Main Street, San Francisco, CA 94102, 
including all fixtures, improvements, and appurtenances.

PURCHASE PRICE: Five Hundred Thousand Dollars ($500,000.00)

TERMS:
1. Earnest Money Deposit: $50,000 to be held in escrow by Golden State Title Company
2. Financing: Buyer has obtained mortgage pre-approval from First National Bank for $400,000
3. Due Diligence Period: 30 days from execution date
4. Inspection Period: 10 business days
5. Closing Date: December 31, 2024
6. Title Insurance: To be provided by seller

CONTINGENCIES:
- Satisfactory property inspection
- Clear title verification
- Environmental assessment approval
- Financing approval

Signed by the parties on the date first written above.
"""
    },
    {
        "id": "doc-2-invoice",
        "title": "Elevator Maintenance Invoice",
        "content": """
INVOICE #INV-2024-1001

FROM:
Contoso Lifts Inc.
456 Industrial Blvd
Seattle, WA 98101
Contact: Mike Johnson, Service Manager
Email: mjohnson@contosolifts.com
Phone: (206) 555-0123

TO:
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

# Test queries for evaluation
TEST_QUERIES = [
    "What is the relationship between ABC Corporation and Contoso Lifts?",
    "Who are the key executives at ABC Corporation and what are their roles?",
    "What financial information is mentioned across the documents?",
    "What are the details of the real estate purchase?",
    "Describe the partnership between ABC Corporation and Fabrikam Industries.",
    "What services does Contoso Lifts provide and at what cost?",
    "Summarize all the business relationships and contracts mentioned.",
]


def main():
    """Run the full GraphRAG benchmark with timing."""
    timings: List[TimingResult] = []
    total_start = time.time()
    
    print("=" * 80)
    print("MICROSOFT GRAPHRAG 5-DOCUMENT BENCHMARK")
    print("=" * 80)
    
    # Initialize services
    print("\n[INIT] Initializing services...")
    init_start = time.time()
    
    llm_service = LLMService()
    assert settings.NEO4J_USERNAME is not None, "NEO4J_USERNAME not set"
    assert settings.NEO4J_PASSWORD is not None, "NEO4J_PASSWORD not set"
    assert settings.NEO4J_URI is not None, "NEO4J_URI not set"
    store = GraphRAGStore(
        group_id=GROUP_ID,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
        url=settings.NEO4J_URI,
    )
    assert llm_service.llm is not None, "LLM not initialized"
    extractor = SimpleGraphRAGExtractor(
        llm=llm_service.llm,
        embed_model=llm_service.embed_model,
        group_id=GROUP_ID,
        generate_embeddings=True  # Enable embedding generation for vector search
    )
    
    init_time = time.time() - init_start
    timings.append(TimingResult("Initialization", init_time, "LLM + Neo4j connection"))
    print(f"    Initialization time: {init_time:.2f}s")
    
    # Clear existing test data
    print("\n[CLEANUP] Clearing existing test data...")
    cleanup_start = time.time()
    store.structured_query(
        "MATCH (n) WHERE n.group_id = $group_id DETACH DELETE n",
        param_map={"group_id": GROUP_ID}
    )
    store.structured_query(
        "MATCH (c:__Community__) WHERE c.group_id = $group_id DELETE c",
        param_map={"group_id": GROUP_ID}
    )
    cleanup_time = time.time() - cleanup_start
    timings.append(TimingResult("Cleanup", cleanup_time, "Delete existing data"))
    print(f"    Cleanup time: {cleanup_time:.2f}s")
    
    # =========================================================================
    # PHASE 1: ENTITY EXTRACTION
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 1: ENTITY EXTRACTION")
    print("=" * 80)
    
    extraction_start = time.time()
    all_entities: List[EntityNode] = []
    all_relations: List[Relation] = []
    doc_timings: List[Tuple[str, float, int, int]] = []
    
    for i, doc in enumerate(TEST_DOCUMENTS, 1):
        doc_start = time.time()
        print(f"\n[{i}/5] Processing: {doc['title']}")
        
        # Create text node
        text_node = TextNode(
            id_=doc["id"],
            text=doc["content"],
            metadata={"title": doc["title"], "group_id": GROUP_ID}
        )
        
        # Extract entities and relations
        entities, relations = extractor.extract(doc["content"], source_id=doc["id"])
        
        doc_time = time.time() - doc_start
        doc_timings.append((doc["title"], doc_time, len(entities), len(relations)))
        
        print(f"       Entities: {len(entities)}, Relations: {len(relations)}")
        print(f"       Time: {doc_time:.2f}s")
        
        all_entities.extend(entities)
        all_relations.extend(relations)
    
    extraction_time = time.time() - extraction_start
    timings.append(TimingResult(
        "Entity Extraction (Total)", 
        extraction_time, 
        f"{len(all_entities)} entities, {len(all_relations)} relations"
    ))
    
    print(f"\n    EXTRACTION SUMMARY:")
    print(f"    Total entities: {len(all_entities)}")
    print(f"    Total relations: {len(all_relations)}")
    print(f"    Total time: {extraction_time:.2f}s")
    print(f"    Average per doc: {extraction_time/5:.2f}s")
    
    # =========================================================================
    # PHASE 2: EMBEDDING GENERATION & NEO4J STORAGE
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 2: EMBEDDING GENERATION & NEO4J STORAGE")
    print("=" * 80)
    
    # Upsert entities (includes embedding generation)
    print("\n[2a] Generating embeddings and storing entities...")
    embed_start = time.time()
    from llama_index.core.graph_stores.types import LabelledNode
    store.upsert_nodes(list(all_entities))  # type: ignore
    embed_time = time.time() - embed_start
    timings.append(TimingResult(
        "Embedding + Entity Storage", 
        embed_time, 
        f"{len(all_entities)} entities with embeddings"
    ))
    print(f"       Time: {embed_time:.2f}s ({embed_time/len(all_entities):.3f}s per entity)")
    
    # Upsert relations
    print("\n[2b] Storing relationships...")
    rel_start = time.time()
    store.upsert_relations(all_relations)
    rel_time = time.time() - rel_start
    timings.append(TimingResult(
        "Relationship Storage", 
        rel_time, 
        f"{len(all_relations)} relationships"
    ))
    print(f"       Time: {rel_time:.2f}s ({rel_time/len(all_relations):.3f}s per relation)")
    
    # =========================================================================
    # PHASE 3: COMMUNITY BUILDING (LEIDEN CLUSTERING + LLM SUMMARIZATION)
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 3: COMMUNITY BUILDING")
    print("=" * 80)
    
    print("\n[3a] Building NetworkX graph...")
    nx_start = time.time()
    nx_graph = store._create_nx_graph()
    nx_time = time.time() - nx_start
    timings.append(TimingResult(
        "NetworkX Graph Creation", 
        nx_time, 
        f"{nx_graph.number_of_nodes()} nodes, {nx_graph.number_of_edges()} edges"
    ))
    print(f"       Nodes: {nx_graph.number_of_nodes()}, Edges: {nx_graph.number_of_edges()}")
    print(f"       Time: {nx_time:.2f}s")
    
    print("\n[3b] Running Leiden clustering...")
    leiden_start = time.time()
    from graspologic.partition import hierarchical_leiden
    clusters = hierarchical_leiden(nx_graph, max_cluster_size=store.max_cluster_size)
    num_communities = len(set(c.cluster for c in clusters))
    leiden_time = time.time() - leiden_start
    timings.append(TimingResult(
        "Leiden Clustering", 
        leiden_time, 
        f"{num_communities} communities found"
    ))
    print(f"       Communities found: {num_communities}")
    print(f"       Time: {leiden_time:.2f}s")
    
    print("\n[3c] Collecting community information...")
    collect_start = time.time()
    entity_info, community_info = store._collect_community_info(nx_graph, clusters)
    collect_time = time.time() - collect_start
    timings.append(TimingResult(
        "Community Info Collection", 
        collect_time, 
        f"{len(community_info)} communities with relationship data"
    ))
    print(f"       Time: {collect_time:.2f}s")
    
    print("\n[3d] Generating community summaries (LLM)...")
    summary_start = time.time()
    store.entity_info = entity_info
    store._summarize_communities(community_info)
    summary_time = time.time() - summary_start
    timings.append(TimingResult(
        "Community Summarization (LLM)", 
        summary_time, 
        f"{len(store.community_summary)} summaries generated"
    ))
    print(f"       Summaries generated: {len(store.community_summary)}")
    print(f"       Time: {summary_time:.2f}s ({summary_time/max(1,len(store.community_summary)):.2f}s per summary)")
    
    print("\n[3e] Persisting communities to Neo4j...")
    persist_start = time.time()
    store._persist_communities_to_neo4j()
    persist_time = time.time() - persist_start
    timings.append(TimingResult(
        "Community Persistence", 
        persist_time, 
        "Stored in Neo4j"
    ))
    print(f"       Time: {persist_time:.2f}s")
    
    community_total = nx_time + leiden_time + collect_time + summary_time + persist_time
    timings.append(TimingResult(
        "Community Building (Total)", 
        community_total, 
        "All community operations"
    ))
    
    # =========================================================================
    # PHASE 4: QUERY TESTING
    # =========================================================================
    print("\n" + "=" * 80)
    print("PHASE 4: QUERY TESTING")
    print("=" * 80)
    
    assert llm_service.llm is not None, "LLM not initialized"
    query_engine = GraphRAGQueryEngine(graph_store=store, llm=llm_service.llm)
    query_timings: List[Tuple[str, float]] = []
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n[Q{i}] {query}")
        print("-" * 60)
        
        query_start = time.time()
        response = query_engine.custom_query(query)
        query_time = time.time() - query_start
        query_timings.append((query[:50] + "...", query_time))
        
        # Truncate response for display
        response_preview = str(response)[:300] + "..." if len(str(response)) > 300 else str(response)
        print(f"    Response ({query_time:.2f}s):")
        print(f"    {response_preview}")
    
    avg_query_time = sum(t for _, t in query_timings) / len(query_timings)
    timings.append(TimingResult(
        "Query Response (Average)", 
        avg_query_time, 
        f"{len(TEST_QUERIES)} queries"
    ))
    
    # =========================================================================
    # FINAL SUMMARY
    # =========================================================================
    total_time = time.time() - total_start
    
    print("\n" + "=" * 80)
    print("BENCHMARK RESULTS SUMMARY")
    print("=" * 80)
    
    print("\n📊 DOCUMENT EXTRACTION BREAKDOWN:")
    print("-" * 60)
    for title, doc_time, entities, relations in doc_timings:
        print(f"  {title:40} {doc_time:6.2f}s  ({entities} E, {relations} R)")
    
    print("\n⏱️  STAGE TIMING SUMMARY:")
    print("-" * 60)
    for timing in timings:
        print(f"  {timing.stage:40} {timing.duration:8.2f}s  [{timing.details}]")
    
    print("\n🔍 QUERY TIMING BREAKDOWN:")
    print("-" * 60)
    for query, query_time in query_timings:
        print(f"  {query:50} {query_time:6.2f}s")
    
    print("\n" + "=" * 80)
    print(f"📈 TOTAL PIPELINE TIME: {total_time:.2f}s")
    print("=" * 80)
    
    # Key metrics
    print("\n📋 KEY METRICS:")
    print(f"  • Documents processed: {len(TEST_DOCUMENTS)}")
    print(f"  • Total entities: {len(all_entities)}")
    print(f"  • Total relationships: {len(all_relations)}")
    print(f"  • Communities built: {num_communities}")
    print(f"  • Avg extraction time per doc: {extraction_time/5:.2f}s")
    print(f"  • Avg query response time: {avg_query_time:.2f}s")
    print(f"  • Community summarization time: {summary_time:.2f}s")
    

if __name__ == "__main__":
    main()
