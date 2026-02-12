"""
Comprehensive Testing: 5 PDFs with Positive/Negative Questions per Route

Tests all 4 routes with:
- 10 positive questions (should find relevant answers)
- 10 negative questions (should return "no information found" or appropriate responses)

PDFs:
1. BUILDERS LIMITED WARRANTY.pdf
2. HOLDING TANK SERVICING CONTRACT.pdf
3. PROPERTY MANAGEMENT AGREEMENT.pdf
4. contoso_lifts_invoice.pdf
5. purchase_contract.pdf
"""

import asyncio
import httpx
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional


# ============================================================================
# Configuration
# ============================================================================

CLOUD_URL = os.getenv(
    "BASE_URL",
    "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io",
)
# The service uses the X-Group-ID header; allow overriding to reuse groups.
GROUP_ID = os.getenv("GROUP_ID") or f"test-5pdfs-{time.time_ns()}"
TIMEOUT = 180.0

TEST_PDFS = [
    "https://afhazstorage.blob.core.windows.net/source-docs/BUILDERS%20LIMITED%20WARRANTY.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/HOLDING%20TANK%20SERVICING%20CONTRACT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/PROPERTY%20MANAGEMENT%20AGREEMENT.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/contoso_lifts_invoice.pdf",
    "https://afhazstorage.blob.core.windows.net/source-docs/purchase_contract.pdf",
]


# ============================================================================
# Test Questions
# ============================================================================

@dataclass
class TestQuestion:
    qid: str
    text: str
    expected_type: str  # "positive" or "negative"
    expected_indicators: List[str]  # Keywords that should/shouldn't appear


# Route 1: Vector RAG (Fast Lane) - Specific factual questions
ROUTE1_QUESTIONS = [
    # POSITIVE: Should find answers
    TestQuestion("R1-P1", "What is the invoice number from Contoso Lifts?", "positive", ["INV", "invoice", "number"]),
    TestQuestion("R1-P2", "What is the total amount on the Contoso Lifts invoice?", "positive", ["$", "amount", "total"]),
    TestQuestion("R1-P3", "When does the property management agreement begin?", "positive", ["date", "2024", "2025"]),
    TestQuestion("R1-P4", "What is the warranty period in the builders warranty?", "positive", ["warranty", "year", "month", "period"]),
    TestQuestion("R1-P5", "Who is the vendor in the holding tank servicing contract?", "positive", ["vendor", "company", "contractor"]),
    TestQuestion("R1-P6", "What is the purchase price in the purchase contract?", "positive", ["$", "price", "amount"]),
    TestQuestion("R1-P7", "What services are covered under the holding tank contract?", "positive", ["service", "pump", "tank", "maintain"]),
    TestQuestion("R1-P8", "What is the payment term in the property management agreement?", "positive", ["payment", "net", "days", "term"]),
    TestQuestion("R1-P9", "Who issued the Contoso Lifts invoice?", "positive", ["Contoso", "Lifts", "elevator"]),
    TestQuestion("R1-P10", "What items are excluded from the builders warranty?", "positive", ["exclude", "not cover", "warranty"]),
    
    # NEGATIVE: Should NOT find answers (out of domain)
    TestQuestion("R1-N1", "What is the GDP of France in 2024?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N2", "Who won the Nobel Prize in Physics in 2023?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N3", "What is the capital of Australia?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N4", "How do you make chocolate chip cookies?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N5", "What is the speed of light?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N6", "Who is the current president of the United States?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N7", "What is the plot of Harry Potter?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N8", "How tall is Mount Everest?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N9", "What programming language was Python named after?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R1-N10", "When was the French Revolution?", "negative", ["no information", "not found", "no relevant"]),
]

# Route 2: Local Search (Entity-Focused) - Multi-entity questions
ROUTE2_QUESTIONS = [
    # POSITIVE: Should find answers
    TestQuestion("R2-P1", "List all contracts that mention Contoso and their key terms", "positive", ["contract", "term", "Contoso"]),
    TestQuestion("R2-P2", "What are the obligations of the property manager?", "positive", ["obligation", "property", "manager"]),
    TestQuestion("R2-P3", "What entities are related to payment terms across documents?", "positive", ["payment", "term", "entity"]),
    TestQuestion("R2-P4", "Find all warranty-related entities and their coverage", "positive", ["warranty", "cover", "entity"]),
    TestQuestion("R2-P5", "What companies are mentioned in the service contracts?", "positive", ["company", "service", "contract"]),
    TestQuestion("R2-P6", "List all financial amounts mentioned across documents", "positive", ["$", "amount", "financial"]),
    TestQuestion("R2-P7", "What locations are referenced in the property agreement?", "positive", ["location", "address", "property"]),
    TestQuestion("R2-P8", "Find all entities related to maintenance and servicing", "positive", ["maintenance", "service", "entity"]),
    TestQuestion("R2-P9", "What are the termination clauses for each contract?", "positive", ["termination", "clause", "contract"]),
    TestQuestion("R2-P10", "List all parties involved in the purchase contract", "positive", ["party", "buyer", "seller", "purchase"]),
    
    # NEGATIVE: Should NOT find answers
    TestQuestion("R2-N1", "List all NASA astronauts who walked on the moon", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N2", "What are the ingredients in a Big Mac?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N3", "Find all Oscar winners from the 1990s", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N4", "What are the symptoms of the common cold?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N5", "List all countries in the European Union", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N6", "What are the rules of chess?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N7", "Find all Shakespeare plays written after 1600", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N8", "What are the side effects of aspirin?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N9", "List all planets in the solar system", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R2-N10", "What are the Ten Commandments?", "negative", ["no information", "not found", "no relevant"]),
]

# Route 3: Global Search (Thematic) - Cross-document themes
ROUTE3_QUESTIONS = [
    # POSITIVE: Should find answers
    TestQuestion("R3-P1", "Summarize the payment terms across all agreements", "positive", ["payment", "term", "summarize"]),
    TestQuestion("R3-P2", "What are the common warranty provisions in the documents?", "positive", ["warranty", "provision", "common"]),
    TestQuestion("R3-P3", "Across all contracts, what are the main service obligations?", "positive", ["service", "obligation", "contract"]),
    TestQuestion("R3-P4", "Identify financial patterns across all documents", "positive", ["financial", "pattern", "amount"]),
    TestQuestion("R3-P5", "What are the recurring themes related to liability?", "positive", ["liability", "theme", "recurring"]),
    TestQuestion("R3-P6", "Summarize termination and cancellation provisions", "positive", ["termination", "cancellation", "provision"]),
    TestQuestion("R3-P7", "What governance patterns appear across agreements?", "positive", ["governance", "pattern", "agreement"]),
    TestQuestion("R3-P8", "Identify all time-based obligations across documents", "positive", ["time", "deadline", "date", "obligation"]),
    TestQuestion("R3-P9", "What are the main parties and their roles across contracts?", "positive", ["party", "role", "contract"]),
    TestQuestion("R3-P10", "Summarize dispute resolution mechanisms", "positive", ["dispute", "resolution", "mechanism"]),
    
    # NEGATIVE: Should NOT find answers
    TestQuestion("R3-N1", "Summarize global climate change trends", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N2", "What are the main themes in classical literature?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N3", "Identify patterns in stock market behavior", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N4", "Summarize recent advances in quantum computing", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N5", "What are common themes in Renaissance art?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N6", "Identify patterns in social media usage", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N7", "Summarize trends in artificial intelligence", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N8", "What are recurring themes in mythology?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N9", "Identify patterns in migration flows", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R3-N10", "Summarize developments in renewable energy", "negative", ["no information", "not found", "no relevant"]),
]

# Route 4: DRIFT (Multi-Hop Reasoning) - Complex relationships
ROUTE4_QUESTIONS = [
    # POSITIVE: Should find answers
    TestQuestion("R4-P1", "Trace the relationship between the invoice and the underlying service contract", "positive", ["relationship", "invoice", "contract"]),
    TestQuestion("R4-P2", "How do warranty provisions relate to service obligations?", "positive", ["warranty", "service", "relate"]),
    TestQuestion("R4-P3", "What is the connection between payment terms and delivery obligations?", "positive", ["payment", "delivery", "connection"]),
    TestQuestion("R4-P4", "Trace all entities connected to property management", "positive", ["entity", "property", "management", "connect"]),
    TestQuestion("R4-P5", "How do liability clauses interact across different agreements?", "positive", ["liability", "interact", "agreement"]),
    TestQuestion("R4-P6", "Find the chain of obligations from vendor to client", "positive", ["chain", "obligation", "vendor", "client"]),
    TestQuestion("R4-P7", "What indirect connections exist between warranty and insurance?", "positive", ["indirect", "warranty", "insurance"]),
    TestQuestion("R4-P8", "Trace the flow of financial obligations across contracts", "positive", ["flow", "financial", "obligation"]),
    TestQuestion("R4-P9", "How do termination clauses in one contract affect others?", "positive", ["termination", "affect", "contract"]),
    TestQuestion("R4-P10", "What multi-hop relationships exist between parties?", "positive", ["multi-hop", "relationship", "party"]),
    
    # NEGATIVE: Should NOT find answers
    TestQuestion("R4-N1", "Trace the evolution of democracy from ancient Greece to modern times", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N2", "How does photosynthesis relate to the carbon cycle?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N3", "What is the connection between supply and demand in economics?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N4", "Trace the influence of Roman law on modern legal systems", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N5", "How do plate tectonics relate to volcanic activity?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N6", "What is the relationship between DNA and protein synthesis?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N7", "Trace the development of the internet from ARPANET", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N8", "How does inflation relate to unemployment?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N9", "What is the connection between music theory and mathematics?", "negative", ["no information", "not found", "no relevant"]),
    TestQuestion("R4-N10", "Trace the evolution of human language", "negative", ["no information", "not found", "no relevant"]),
]


# ============================================================================
# Test Execution
# ============================================================================

class TestResults:
    def __init__(self):
        self.results = []
        self.summary = {
            "route1": {"positive": 0, "negative": 0, "total": 0},
            "route2": {"positive": 0, "negative": 0, "total": 0},
            "route3": {"positive": 0, "negative": 0, "total": 0},
            "route4": {"positive": 0, "negative": 0, "total": 0},
        }
    
    def add_result(self, route: str, question: TestQuestion, passed: bool, answer: str, latency: float, error: Optional[str] = None):
        result = {
            "route": route,
            "qid": question.qid,
            "question": question.text,
            "expected_type": question.expected_type,
            "passed": passed,
            "answer": answer[:200] if answer else "",
            "latency": latency,
            "error": error
        }
        self.results.append(result)
        
        # Update summary
        route_key = f"route{route[-1]}"
        if route_key in self.summary:
            if passed:
                self.summary[route_key][question.expected_type] += 1
            self.summary[route_key]["total"] += 1
    
    def print_summary(self):
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        for route, stats in self.summary.items():
            print(f"\n{route.upper()}:")
            print(f"  Positive: {stats['positive']}/10")
            print(f"  Negative: {stats['negative']}/10")
            print(f"  Total:    {stats['total']}/20")
            if stats['total'] > 0:
                print(f"  Success Rate: {(stats['positive'] + stats['negative']) / stats['total'] * 100:.1f}%")
            else:
                print(f"  Success Rate: N/A (no tests ran)")
        
        total_passed = sum(s["positive"] + s["negative"] for s in self.summary.values())
        total_tests = sum(s["total"] for s in self.summary.values())
        if total_tests > 0:
            print(f"\nOVERALL: {total_passed}/{total_tests} ({total_passed/total_tests*100:.1f}%)")
        else:
            print(f"\nOVERALL: No tests ran")
    
    def save_to_file(self, filename: str):
        with open(filename, 'w') as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "group_id": GROUP_ID,
                "pdfs": TEST_PDFS,
                "results": self.results,
                "summary": self.summary
            }, f, indent=2)
        print(f"\n✅ Results saved to {filename}")


async def index_pdfs():
    """Index the 5 PDFs into the cloud service."""
    print("="*80)
    print("INDEXING 5 PDFs")
    print("="*80)
    
    for i, pdf_url in enumerate(TEST_PDFS, 1):
        pdf_name = pdf_url.split('/')[-1].replace('%20', ' ')
        print(f"[{i}/5] {pdf_name}")
    # NOTE: group_id is taken from the X-Group-ID header (multi-tenancy).
    # Keep request body aligned with /hybrid/index/documents schema.
    payload = {
        "documents": [{"url": url} for url in TEST_PDFS],
        "ingestion": "document-intelligence",
        "run_raptor": False,
        "run_community_detection": True,
    }
    
    headers = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=600.0) as client:
        print("\n⏳ Running indexing (synchronous)...")
        
        start = time.monotonic()
        try:
            # Preferred indexing entrypoint for the LazyGraphRAG + HippoRAG2 + Vector system
            response = await client.post("/hybrid/index/documents", json=payload, headers=headers)
            elapsed = time.monotonic() - start
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Indexing completed in {elapsed:.1f}s")
                print(f"   Status: {data.get('status', 'unknown')}")
                print(f"   Message: {data.get('message', '')}")
                stats = data.get("stats") or {}
                if stats:
                    print(
                        "   Stats: "
                        f"documents={stats.get('documents')} chunks={stats.get('chunks')} "
                        f"entities={stats.get('entities')} relationships={stats.get('relationships')} "
                        f"communities={stats.get('communities')}"
                    )
                
                # Wait for Neo4j data, then sync + init HippoRAG (poll every 30s)
                print("\n⏳ Waiting for indexing to complete (checking /hybrid/index/sync dry_run every 30s)...")
                max_wait = 420  # 7 minutes max
                waited = 0

                while waited < max_wait:
                    await asyncio.sleep(30)
                    waited += 30

                    try:
                        dry = await client.post(
                            "/hybrid/index/sync",
                            json={"output_dir": "./hipporag_index", "dry_run": True},
                            headers=headers,
                        )
                        if dry.status_code == 200:
                            d = dry.json()
                            would = d.get("would_index") or {}
                            chunks = int(would.get("text_chunks", 0) or 0)
                            entities = int(would.get("entities", 0) or 0)
                            print(f"   ⏳ {waited}s: entities={entities} chunks={chunks}")

                            if chunks > 0:
                                print("   ✅ Neo4j data detected. Syncing HippoRAG artifacts...")
                                sync = await client.post(
                                    "/hybrid/index/sync",
                                    json={"output_dir": "./hipporag_index", "dry_run": False},
                                    headers=headers,
                                    timeout=600.0,
                                )
                                if sync.status_code != 200:
                                    print(f"   ❌ Sync failed: HTTP {sync.status_code} {sync.text[:200]}")
                                    return False

                                init = await client.post(
                                    "/hybrid/index/initialize-hipporag",
                                    headers=headers,
                                )
                                if init.status_code != 200:
                                    print(f"   ❌ HippoRAG init failed: HTTP {init.status_code} {init.text[:200]}")
                                    return False

                                print("   ✅ HippoRAG synced + initialized.")
                                return True
                    except Exception:
                        pass

                print(f"   ⚠️ Timed out after {max_wait}s. Indexing may still be in progress.")
                print("   Continuing with tests anyway...")
                return True
            else:
                print(f"❌ Indexing failed: {response.status_code}")
                print(f"   Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"❌ Indexing error: {str(e)}")
            return False


def validate_answer(question: TestQuestion, answer: str) -> bool:
    """Check if answer matches expected type (positive/negative)."""
    answer_lower = answer.lower()
    
    if question.expected_type == "positive":
        # For positive questions, check if answer contains expected indicators
        # and doesn't contain "no information" phrases
        no_info_phrases = ["no information", "not found", "no relevant", "no data", "no answer"]
        has_no_info = any(phrase in answer_lower for phrase in no_info_phrases)
        has_indicators = any(indicator.lower() in answer_lower for indicator in question.expected_indicators)
        
        # Pass if we have indicators and no "no information" phrases
        return has_indicators and not has_no_info
    else:  # negative
        # For negative questions, check if answer correctly says "no information"
        no_info_phrases = ["no information", "not found", "no relevant", "no data", "cannot find"]
        return any(phrase in answer_lower for phrase in no_info_phrases)


async def test_route(route_name: str, endpoint: str, questions: List[TestQuestion], results: TestResults):
    """Test a specific route with all questions."""
    print(f"\n{'='*80}")
    print(f"TESTING {route_name}")
    print(f"{'='*80}\n")
    
    headers = {"Content-Type": "application/json", "X-Group-ID": GROUP_ID}
    
    async with httpx.AsyncClient(base_url=CLOUD_URL, timeout=TIMEOUT) as client:
        for i, question in enumerate(questions, 1):
            print(f"[{i}/{len(questions)}] {question.qid} ({question.expected_type}): {question.text[:60]}...")
            
            # Hybrid query endpoint with forced route.
            route_map = {
                "Route 1 (Vector)": "vector_rag",
                "Route 2 (Local)": "local_search",
                "Route 3 (Global)": "global_search",
                "Route 4 (DRIFT)": "drift_multi_hop",
            }
            payload = {
                "query": question.text,
                "response_type": "detailed_report",
                "force_route": route_map.get(route_name),
            }
            
            start = time.monotonic()
            try:
                response = await client.post(endpoint, json=payload, headers=headers)
                elapsed = time.monotonic() - start
                
                if response.status_code == 200:
                    data = response.json()
                    answer = data.get("response", "")
                    passed = validate_answer(question, answer)
                    
                    status = "✅ PASS" if passed else "❌ FAIL"
                    print(f"   {status} ({elapsed:.2f}s)")
                    print(f"   Answer: {answer[:100]}...")
                    
                    results.add_result(route_name, question, passed, answer, elapsed)
                else:
                    print(f"   ❌ HTTP {response.status_code}")
                    results.add_result(route_name, question, False, "", elapsed, f"HTTP {response.status_code}")
            
            except Exception as e:
                elapsed = time.monotonic() - start
                print(f"   ❌ ERROR: {str(e)[:60]}")
                results.add_result(route_name, question, False, "", elapsed, str(e)[:100])
            
            # Small delay between requests
            await asyncio.sleep(0.5)


async def main():
    """Main test execution."""
    print("\n" + "="*80)
    print("COMPREHENSIVE 5-PDF TEST WITH POSITIVE/NEGATIVE QUESTIONS")
    print("="*80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Service: {CLOUD_URL}")
    print(f"Group ID: {GROUP_ID}")
    
    # Step 1: Index PDFs
    if not await index_pdfs():
        print("\n❌ Indexing failed. Aborting tests.")
        return
    
    # Step 2: Run tests
    results = TestResults()

    await test_route("Route 1 (Vector)", "/hybrid/query", ROUTE1_QUESTIONS, results)
    await test_route("Route 2 (Local)", "/hybrid/query", ROUTE2_QUESTIONS, results)
    await test_route("Route 3 (Global)", "/hybrid/query", ROUTE3_QUESTIONS, results)
    await test_route("Route 4 (DRIFT)", "/hybrid/query", ROUTE4_QUESTIONS, results)
    
    # Step 3: Print summary
    results.print_summary()
    
    # Step 4: Save results
    filename = f"test_5pdfs_results_{int(time.time())}.json"
    results.save_to_file(filename)
    
    print("\n" + "="*80)
    print("✅ TESTING COMPLETE")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
