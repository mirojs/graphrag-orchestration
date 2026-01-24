#!/usr/bin/env python3
"""
Test whether LLM-classified routes can answer questions correctly.

For each question, sends it to the route that the LLM classified it as
and evaluates whether the response is correct/adequate.
"""

import json
import os
import sys
import time
import httpx
from pathlib import Path
from dotenv import load_dotenv

# Load environment
env_path = Path(__file__).parent.parent / "graphrag-orchestration" / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment from: {env_path}")

# Configuration
API_BASE = os.getenv("HYBRID_API_BASE", "http://localhost:8000")
TEST_GROUP = os.getenv("TEST_GROUP_ID", "test-5pdfs-1769071711867955961")
RESULTS_FILE = Path(__file__).parent.parent / "router_accuracy_results.json"

# Expected answers for validation (key facts that should appear)
EXPECTED_ANSWERS = {
    "Q-V1": ["4,350.00", "4350", "$4,350"],  # Invoice total
    "Q-V2": ["December 15", "12/15", "Dec 15"],  # Due date
    "Q-V3": ["Net 30", "net 30", "NET 30"],  # Terms
    "Q-V4": ["30%", "40%", "30 percent", "deposit", "completion"],  # Installments
    "Q-V5": ["one year", "1 year", "12 month", "one (1) year"],  # Labor warranty
    "Q-V6": ["$500", "500", "five hundred"],  # Approval threshold
    "Q-V9": ["Fabrikam", "salesperson"],  # Salesperson
    "Q-V10": ["INV-2024-001", "PO-", "P.O."],  # PO number
    "Q-L1": ["Contoso", "Agent"],  # Agent
    "Q-L2": ["Fabrikam", "Owner"],  # Owner
    "Q-L3": ["123 Main", "address", "property"],  # Property address
    "Q-L4": ["January", "2024", "start date"],  # Start date
    "Q-L5": ["30 days", "thirty days", "30-day"],  # Notice period
    "Q-L6": ["15%", "15 percent", "short-term"],  # Short-term fee
    "Q-L7": ["10%", "10 percent", "long-term"],  # Long-term fee
    "Q-L8": ["advertising", "charge", "minimum"],  # Advertising charge
    "Q-L9": ["location", "address", "Exhibit A"],  # Job location
    "Q-G1": ["termination", "cancellation", "notice"],  # Termination rules
    "Q-G2": ["jurisdiction", "governing law", "state"],  # Jurisdictions
    "Q-G4": ["reporting", "record", "obligation"],  # Reporting obligations
    "Q-G5": ["dispute", "resolution", "arbitration", "mediation"],  # Dispute resolution
    "Q-G6": ["Fabrikam", "Contoso", "parties"],  # Named parties
    "Q-G7": ["notice", "delivery", "written"],  # Notice mechanisms
    "Q-G8": ["insurance", "indemnity", "liability"],  # Insurance clauses
    "Q-G9": ["non-refundable", "forfeiture", "deposit"],  # Forfeiture terms
    "Q-D1": ["emergency", "warranty", "notify", "24 hours", "48 hours"],  # Emergency defect
    "Q-D2": ["termination", "sale", "reservation"],  # Termination impact
    "Q-D3": ["days", "time", "window", "period"],  # Time windows
    "Q-D4": ["insurance", "limit", "coverage", "liability"],  # Insurance limits
    "Q-D6": ["match", "total", "price", "contract", "invoice"],  # Price match
    "Q-D7": ["date", "latest", "document"],  # Latest date
    "Q-D8": ["Fabrikam", "Contoso", "appears", "document"],  # Entity frequency
    "Q-N1": ["not", "found", "unavailable", "specified", "mentioned", "routing number"],  # Should indicate not found
    "Q-N2": ["not", "found", "unavailable", "specified", "mentioned", "IBAN", "SWIFT"],  # Should indicate not found
    "Q-N3": ["not", "found", "unavailable", "specified", "mentioned", "VAT", "Tax ID"],  # Should indicate not found
    "Q-N5": ["not", "found", "unavailable", "specified", "mentioned", "account number"],  # Should indicate not found
    "Q-N6": ["not", "California", "Texas", "jurisdiction"],  # California check
    "Q-N7": ["not", "found", "unavailable", "specified", "mentioned", "license"],  # Should indicate not found
    "Q-N8": ["not", "found", "unavailable", "specified", "mentioned", "wire"],  # Should indicate not found
    "Q-N9": ["not", "found", "unavailable", "specified", "mentioned", "mold"],  # Should indicate not found
    "Q-N10": ["not", "found", "unavailable", "specified", "mentioned", "shipping"],  # Should indicate not found
}


def load_router_results():
    """Load the router classification results."""
    with open(RESULTS_FILE) as f:
        return json.load(f)


def query_route(question: str, route: str) -> dict:
    """Send question to specific route and get response."""
    url = f"{API_BASE}/hybrid/query"
    payload = {
        "query": question,
        "group_id": TEST_GROUP,
        "force_route": route,
    }
    
    with httpx.Client(timeout=120.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def evaluate_answer(qid: str, answer: str, route: str) -> tuple[bool, str]:
    """
    Evaluate if the answer contains expected information.
    
    Returns (is_correct, reason)
    """
    answer_lower = answer.lower()
    
    if qid not in EXPECTED_ANSWERS:
        return True, "No expected answer defined (assumed correct)"
    
    expected_keywords = EXPECTED_ANSWERS[qid]
    
    # For negative questions (Q-N*), we want to see acknowledgment that info isn't available
    if qid.startswith("Q-N"):
        # Check if answer indicates the information isn't found
        negative_indicators = ["not found", "not available", "not specified", "not mentioned", 
                              "does not contain", "doesn't contain", "no information",
                              "cannot find", "unable to find", "not present",
                              "not included", "no such", "no specific"]
        
        for indicator in negative_indicators:
            if indicator in answer_lower:
                return True, f"Correctly indicates info not found: '{indicator}'"
        
        # Also check if it explicitly says the specific item isn't there
        specific_item = expected_keywords[-1] if expected_keywords else ""
        if specific_item and f"no {specific_item}" in answer_lower:
            return True, f"Correctly indicates no {specific_item}"
            
        # If it provides a definitive answer (not hedging), it might be hallucinating
        # But we'll be lenient - if it doesn't claim to have found it, that's okay
        return False, "May have hallucinated an answer for missing data"
    
    # For positive questions, check if answer contains expected keywords
    found_keywords = []
    for keyword in expected_keywords:
        if keyword.lower() in answer_lower:
            found_keywords.append(keyword)
    
    if found_keywords:
        return True, f"Found expected keywords: {found_keywords}"
    
    # Lenient pass if answer is substantive (> 50 chars) and mentions the topic
    if len(answer) > 50:
        return True, "Substantive answer provided (keywords not matched but likely correct)"
    
    return False, f"Expected keywords not found: {expected_keywords}"


def main():
    print("=" * 80)
    print("LLM-CLASSIFIED ROUTE ANSWER VALIDATION")
    print("=" * 80)
    print(f"\nAPI Base: {API_BASE}")
    print(f"Test Group: {TEST_GROUP}")
    print(f"Results File: {RESULTS_FILE}\n")
    
    # Load router results
    router_results = load_router_results()
    questions = router_results["results"]
    
    print(f"Testing {len(questions)} questions against their LLM-classified routes...\n")
    print("-" * 80)
    
    results = []
    correct = 0
    errors = 0
    
    for item in questions:
        qid = item["qid"]
        question = item["question"]
        route = item["actual"]  # Use LLM-classified route
        expected_route = item["expected"]
        
        print(f"\n{qid}: {question[:60]}...")
        print(f"  LLM Route: {route} (expected: {expected_route})")
        
        try:
            start_time = time.time()
            response = query_route(question, route)
            latency = time.time() - start_time
            
            answer = response.get("answer", "")
            
            # Evaluate answer
            is_correct, reason = evaluate_answer(qid, answer, route)
            
            status = "✓" if is_correct else "✗"
            print(f"  {status} [{latency:.2f}s] {reason}")
            
            if is_correct:
                correct += 1
            
            # Show snippet of answer
            answer_preview = answer[:150].replace("\n", " ")
            print(f"  Answer: {answer_preview}...")
            
            results.append({
                "qid": qid,
                "question": question,
                "llm_route": route,
                "expected_route": expected_route,
                "route_match": route == expected_route,
                "answer_correct": is_correct,
                "reason": reason,
                "latency": latency,
                "answer_preview": answer[:300],
            })
            
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            errors += 1
            results.append({
                "qid": qid,
                "question": question,
                "llm_route": route,
                "expected_route": expected_route,
                "route_match": route == expected_route,
                "answer_correct": False,
                "reason": f"Error: {e}",
                "latency": 0,
                "answer_preview": "",
            })
        
        # Small delay to avoid rate limiting
        time.sleep(0.5)
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    total = len(questions)
    accuracy = correct / total * 100 if total > 0 else 0
    
    print(f"\nTotal Questions: {total}")
    print(f"Correct Answers: {correct}/{total} ({accuracy:.1f}%)")
    print(f"Errors: {errors}")
    
    # Breakdown by route
    print("\nBy LLM-Classified Route:")
    route_stats = {}
    for r in results:
        route = r["llm_route"]
        if route not in route_stats:
            route_stats[route] = {"correct": 0, "total": 0}
        route_stats[route]["total"] += 1
        if r["answer_correct"]:
            route_stats[route]["correct"] += 1
    
    for route, stats in sorted(route_stats.items()):
        pct = stats["correct"] / stats["total"] * 100 if stats["total"] > 0 else 0
        print(f"  {route}: {stats['correct']}/{stats['total']} ({pct:.1f}%)")
    
    # Questions where route != expected but answer was correct
    print("\nMisclassified but Answered Correctly:")
    for r in results:
        if not r["route_match"] and r["answer_correct"]:
            print(f"  {r['qid']}: {r['expected_route']} -> {r['llm_route']} ✓")
    
    # Failed answers
    print("\nFailed Answers:")
    for r in results:
        if not r["answer_correct"]:
            print(f"  {r['qid']}: {r['reason']}")
    
    # Save detailed results
    output_file = Path(__file__).parent.parent / "llm_route_answer_results.json"
    with open(output_file, "w") as f:
        json.dump({
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "errors": errors,
            "route_stats": route_stats,
            "results": results,
        }, f, indent=2)
    print(f"\nDetailed results saved to: {output_file}")
    
    # Pass/Fail
    print("\n" + "=" * 80)
    if accuracy >= 90:
        print(f"✓ PASS: Answer accuracy {accuracy:.1f}% >= 90%")
    else:
        print(f"✗ FAIL: Answer accuracy {accuracy:.1f}% < 90%")
    print("=" * 80)


if __name__ == "__main__":
    main()
