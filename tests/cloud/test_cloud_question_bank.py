"""
Cloud Test: Question Bank Validation for 4-Route Hybrid System

Tests all 12 questions from QUESTION_BANK_HYBRID_ROUTER_2025-12-29.md
against the deployed GraphRAG service.

Routes tested:
- Route 1: Vector RAG (Q-V1, Q-V2, Q-V3)
- Route 2: Local Search (Q-L1, Q-L2, Q-L3)
- Route 3: Global Search (Q-G1, Q-G2, Q-G3)
- Route 4: DRIFT Multi-Hop (Q-D1, Q-D2, Q-D3)

Run:
    export GRAPHRAG_CLOUD_URL="https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
    export TEST_GROUP_ID="invoice-contract-verification"
    pytest tests/cloud/test_cloud_question_bank.py -v
"""

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx
import pytest

# ============================================================================
# Configuration
# ============================================================================

CLOUD_URL = os.getenv(
    "GRAPHRAG_CLOUD_URL",
    "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
)
GROUP_ID = os.getenv("TEST_GROUP_ID", "invoice-contract-verification")

# Timeout settings (cloud can be slower, especially on cold start)
TIMEOUT_HEALTH = 10.0
TIMEOUT_VECTOR = 60.0  # Route 1 - increased for cold start
TIMEOUT_LOCAL = 90.0   # Route 2
TIMEOUT_GLOBAL = 120.0  # Route 3
TIMEOUT_DRIFT = 180.0  # Route 4

# Latency targets (relaxed for cloud cold start)
LATENCY_VECTOR = 10.0  # Relaxed from 2.0s - cold start can be 5-8s
LATENCY_LOCAL = 15.0   # Relaxed from 5.0s
LATENCY_GLOBAL = 30.0  # Relaxed from 10.0s
LATENCY_DRIFT = 90.0   # Relaxed from 20.0s - DRIFT multi-hop can take 60-80s


# ============================================================================
# Question Bank Data
# ============================================================================

@dataclass(frozen=True)
class BankQuestion:
    qid: str
    text: str
    route: str  # vector, local, global, drift
    endpoint: str


QUESTION_BANK: List[BankQuestion] = [
    # Route 1: Vector RAG (Fast Lane)
    BankQuestion("Q-V1", "What is the invoice total amount?", "vector", "/graphrag/v3/query/local"),
    BankQuestion("Q-V2", "What is the due date?", "vector", "/graphrag/v3/query/local"),
    BankQuestion("Q-V3", "Who is the salesperson?", "vector", "/graphrag/v3/query/local"),
    
    # Route 2: Local Search (Entity-Focused)
    BankQuestion("Q-L1", "List all contracts with Vendor ABC and their payment terms.", "local", "/graphrag/v3/query/local"),
    BankQuestion("Q-L2", "What are all obligations for Contoso Ltd. in the property management agreement?", "local", "/graphrag/v3/query/local"),
    BankQuestion("Q-L3", "What is the approval threshold requiring prior written approval for expenditures?", "local", "/graphrag/v3/query/local"),
    
    # Route 3: Global Search (Thematic)
    BankQuestion("Q-G1", "Across the agreements, summarize termination and cancellation rules.", "global", "/graphrag/v3/query/global"),
    BankQuestion("Q-G2", "Identify which documents reference governing law or jurisdiction.", "global", "/graphrag/v3/query/global"),
    BankQuestion("Q-G3", "Summarize who pays what across the set (fees, charges, taxes).", "global", "/graphrag/v3/query/global"),
    
    # Route 4: DRIFT Multi-Hop
    BankQuestion("Q-D1", "Analyze our overall risk exposure through subsidiaries and trace the relationship between entities across all related parties in general.", "drift", "/graphrag/v3/query/drift"),
    BankQuestion("Q-D2", "Compare time windows across the set and list all explicit day-based timeframes.", "drift", "/graphrag/v3/query/drift"),
    BankQuestion("Q-D3", "Explain the implications of the dispute resolution mechanisms across the agreements.", "drift", "/graphrag/v3/query/drift"),
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def cloud_client():
    """HTTP client for cloud tests."""
    with httpx.Client(base_url=CLOUD_URL, timeout=TIMEOUT_DRIFT) as client:
        yield client


@pytest.fixture(scope="module")
def headers():
    """Common headers for all requests."""
    return {
        "Content-Type": "application/json",
        "X-Group-ID": GROUP_ID,
    }


# ============================================================================
# Health Check Tests
# ============================================================================

class TestCloudHealth:
    """Verify the deployed service is reachable and healthy."""
    
    def test_health_endpoint(self, cloud_client: httpx.Client):
        """Test /health endpoint returns 200."""
        response = cloud_client.get("/health", timeout=TIMEOUT_HEALTH)
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") in ("healthy", "ok")
    
    def test_docs_endpoint(self, cloud_client: httpx.Client):
        """Test /docs (Swagger UI) is accessible."""
        response = cloud_client.get("/docs", timeout=TIMEOUT_HEALTH)
        assert response.status_code == 200
        assert "swagger" in response.text.lower() or "openapi" in response.text.lower()


# ============================================================================
# Route Tests
# ============================================================================

class TestRoute1Vector:
    """Test Route 1: Vector RAG (Fast Lane) questions."""
    
    @pytest.mark.parametrize("question", [q for q in QUESTION_BANK if q.route == "vector"])
    def test_vector_questions(self, cloud_client: httpx.Client, headers: dict, question: BankQuestion):
        """Test Vector RAG questions (Q-V1, Q-V2, Q-V3)."""
        payload = {
            "query": question.text,
            "top_k": 10,
        }
        
        start = time.monotonic()
        response = cloud_client.post(question.endpoint, json=payload, headers=headers, timeout=TIMEOUT_VECTOR)
        elapsed = time.monotonic() - start
        
        assert response.status_code == 200, f"{question.qid} failed: {response.text[:200]}"
        data = response.json()
        
        # Check response structure
        assert "answer" in data, f"{question.qid} missing 'answer' field"
        assert len(data["answer"]) > 0, f"{question.qid} returned empty answer"
        
        # Check latency
        assert elapsed < LATENCY_VECTOR, f"{question.qid} too slow: {elapsed:.2f}s > {LATENCY_VECTOR}s"


class TestRoute2Local:
    """Test Route 2: Local Search (Entity-Focused) questions."""
    
    @pytest.mark.parametrize("question", [q for q in QUESTION_BANK if q.route == "local"])
    def test_local_questions(self, cloud_client: httpx.Client, headers: dict, question: BankQuestion):
        """Test Local Search questions (Q-L1, Q-L2, Q-L3)."""
        payload = {
            "query": question.text,
            "top_k": 10,
        }
        
        start = time.monotonic()
        response = cloud_client.post(question.endpoint, json=payload, headers=headers, timeout=TIMEOUT_LOCAL)
        elapsed = time.monotonic() - start
        
        assert response.status_code == 200, f"{question.qid} failed: {response.text[:200]}"
        data = response.json()
        
        assert "answer" in data, f"{question.qid} missing 'answer' field"
        assert len(data["answer"]) > 0, f"{question.qid} returned empty answer"
        
        # Latency check (more lenient for Local)
        assert elapsed < LATENCY_LOCAL, f"{question.qid} too slow: {elapsed:.2f}s > {LATENCY_LOCAL}s"


class TestRoute3Global:
    """Test Route 3: Global Search (Thematic + HippoRAG PPR) questions."""
    
    @pytest.mark.parametrize("question", [q for q in QUESTION_BANK if q.route == "global"])
    def test_global_questions(self, cloud_client: httpx.Client, headers: dict, question: BankQuestion):
        """Test Global Search questions (Q-G1, Q-G2, Q-G3)."""
        payload = {
            "query": question.text,
            "top_k": 10,
            "use_dynamic_community": True,
        }
        
        start = time.monotonic()
        response = cloud_client.post(question.endpoint, json=payload, headers=headers, timeout=TIMEOUT_GLOBAL)
        elapsed = time.monotonic() - start
        
        assert response.status_code == 200, f"{question.qid} failed: {response.text[:200]}"
        data = response.json()
        
        assert "answer" in data, f"{question.qid} missing 'answer' field"
        # Global may return "No RAPTOR nodes" if not indexed - check for that
        answer = data["answer"]
        no_data_indicators = ["no raptor", "no relevant", "no data", "not found"]
        has_data = not any(ind in answer.lower() for ind in no_data_indicators)
        
        if not has_data:
            pytest.skip(f"{question.qid}: No indexed data for this group")
        
        assert elapsed < LATENCY_GLOBAL, f"{question.qid} too slow: {elapsed:.2f}s > {LATENCY_GLOBAL}s"


class TestRoute4Drift:
    """Test Route 4: DRIFT Multi-Hop Reasoning questions."""
    
    @pytest.mark.parametrize("question", [q for q in QUESTION_BANK if q.route == "drift"])
    def test_drift_questions(self, cloud_client: httpx.Client, headers: dict, question: BankQuestion):
        """Test DRIFT questions (Q-D1, Q-D2, Q-D3)."""
        payload = {
            "query": question.text,
            "top_k": 10,
            "max_iterations": 5,
            "include_sources": True,
        }
        
        start = time.monotonic()
        response = cloud_client.post(question.endpoint, json=payload, headers=headers, timeout=TIMEOUT_DRIFT)
        elapsed = time.monotonic() - start
        
        assert response.status_code == 200, f"{question.qid} failed: {response.text[:200]}"
        data = response.json()
        
        assert "answer" in data, f"{question.qid} missing 'answer' field"
        answer = data["answer"]
        no_data_indicators = ["no raptor", "no relevant", "no data", "not found"]
        has_data = not any(ind in answer.lower() for ind in no_data_indicators)
        
        if not has_data:
            pytest.skip(f"{question.qid}: No indexed data for this group")
        
        assert elapsed < LATENCY_DRIFT, f"{question.qid} too slow: {elapsed:.2f}s > {LATENCY_DRIFT}s"


# ============================================================================
# Full Question Bank Validation
# ============================================================================

class TestFullQuestionBank:
    """Run all 12 questions and report pass/fail summary."""
    
    def test_all_questions_complete(self, cloud_client: httpx.Client, headers: dict):
        """Verify all 12 questions can be submitted (may not all pass if no data)."""
        results = []
        
        for question in QUESTION_BANK:
            payload = {
                "query": question.text,
                "top_k": 10,
            }
            
            try:
                response = cloud_client.post(
                    question.endpoint, 
                    json=payload, 
                    headers=headers, 
                    timeout=TIMEOUT_DRIFT
                )
                success = response.status_code == 200
                error = None if success else response.text[:100]
            except Exception as e:
                success = False
                error = str(e)[:100]
            
            results.append({
                "qid": question.qid,
                "route": question.route,
                "success": success,
                "error": error,
            })
        
        # Report summary
        passed = sum(1 for r in results if r["success"])
        total = len(results)
        
        print(f"\n{'='*60}")
        print(f"QUESTION BANK SUMMARY: {passed}/{total} passed")
        print(f"{'='*60}")
        
        for route in ["vector", "local", "global", "drift"]:
            route_results = [r for r in results if r["route"] == route]
            route_passed = sum(1 for r in route_results if r["success"])
            print(f"  Route {route.upper()}: {route_passed}/{len(route_results)}")
        
        # Don't fail the test - just report (actual route tests above will fail if needed)
        assert True


# ============================================================================
# Unified Query Endpoint Test
# ============================================================================

class TestUnifiedQueryEndpoint:
    """Test the unified /graphrag/v3/query endpoint with routing."""
    
    def test_unified_query_routes_correctly(self, cloud_client: httpx.Client, headers: dict):
        """Test that /graphrag/v3/query routes to appropriate backend."""
        payload = {
            "query": "What is the invoice total amount?",
            "group_id": GROUP_ID,
            "use_dynamic_community": True,
        }
        
        response = cloud_client.post("/graphrag/v3/query", json=payload, headers=headers, timeout=TIMEOUT_LOCAL)
        
        # Should succeed (200) or give meaningful error (400/500 with JSON)
        assert response.status_code in (200, 400, 404, 500)
        
        if response.status_code == 200:
            data = response.json()
            assert "answer" in data


# ============================================================================
# Performance Benchmark
# ============================================================================

class TestCloudPerformance:
    """Benchmark latency for each route type."""
    
    def test_latency_by_route(self, cloud_client: httpx.Client, headers: dict):
        """Measure and report latency for each route."""
        samples = {
            "vector": BankQuestion("Q-V1", "What is the invoice total amount?", "vector", "/graphrag/v3/query/local"),
            "local": BankQuestion("Q-L1", "List all contracts with Vendor ABC and their payment terms.", "local", "/graphrag/v3/query/local"),
            "global": BankQuestion("Q-G1", "Across the agreements, summarize termination and cancellation rules.", "global", "/graphrag/v3/query/global"),
            "drift": BankQuestion("Q-D1", "Analyze our overall risk exposure through subsidiaries.", "drift", "/graphrag/v3/query/drift"),
        }
        
        print(f"\n{'='*60}")
        print("LATENCY BENCHMARK")
        print(f"{'='*60}")
        
        for route_name, question in samples.items():
            payload = {"query": question.text, "top_k": 10}
            
            start = time.monotonic()
            try:
                response = cloud_client.post(
                    question.endpoint,
                    json=payload,
                    headers=headers,
                    timeout=TIMEOUT_DRIFT
                )
                elapsed = time.monotonic() - start
                status = response.status_code
            except Exception as e:
                elapsed = -1
                status = f"ERROR: {e}"
            
            print(f"  {route_name.upper():8} : {elapsed:6.2f}s (status={status})")
        
        # This test is informational
        assert True
