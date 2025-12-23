#!/usr/bin/env python3
"""
Test script for GraphRAG V3 Search Endpoints (Local, Global, DRIFT)
Uses existing indexed data from group: phase1-5docs-1766248188
"""
import requests
import json
import sys
import time

# Configuration
BASE_URL = "https://graphrag-orchestration.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
GROUP_ID = "phase1-5docs-1766248188"

HEADERS = {
    "Content-Type": "application/json",
    "X-Group-ID": GROUP_ID
}

def log(msg):
    print(msg, flush=True)

def print_response(response):
    try:
        data = response.json()
        print(json.dumps(data, indent=2))
    except:
        print(response.text)

def check_stats():
    log(f"\n{'='*50}")
    log(f"Checking Stats for Group: {GROUP_ID}")
    log(f"{'='*50}")
    
    url = f"{BASE_URL}/graphrag/v3/stats/{GROUP_ID}"
    try:
        response = requests.get(url, headers=HEADERS)
        log(f"Status: {response.status_code}")
        print_response(response)
        return response.status_code == 200
    except Exception as e:
        log(f"Error: {e}")
        return False

def test_local_search():
    log(f"\n{'='*50}")
    log("Testing Local Search (Entity-focused)")
    log(f"{'='*50}")
    
    query = "What companies or parties are involved?"
    url = f"{BASE_URL}/graphrag/v3/query/local"
    payload = {
        "query": query,
        "top_k": 10,
        "include_sources": True
    }
    
    log(f"Query: {query}")
    try:
        start = time.time()
        response = requests.post(url, headers=HEADERS, json=payload)
        elapsed = time.time() - start
        log(f"Status: {response.status_code} (Time: {elapsed:.2f}s)")
        print_response(response)
    except Exception as e:
        log(f"Error: {e}")

def test_global_search():
    log(f"\n{'='*50}")
    log("Testing Global Search (Community summaries)")
    log(f"{'='*50}")
    
    query = "What are the main themes and risks in these documents?"
    url = f"{BASE_URL}/graphrag/v3/query/global"
    payload = {
        "query": query,
        "top_k": 10,
        "include_sources": True
    }
    
    log(f"Query: {query}")
    try:
        start = time.time()
        response = requests.post(url, headers=HEADERS, json=payload)
        elapsed = time.time() - start
        log(f"Status: {response.status_code} (Time: {elapsed:.2f}s)")
        print_response(response)
    except Exception as e:
        log(f"Error: {e}")

def test_drift_search():
    log(f"\n{'='*50}")
    log("Testing DRIFT Search (Multi-step reasoning)")
    log(f"{'='*50}")
    
    query = "Compare invoice amount with contract amount. Is there a discrepancy?"
    url = f"{BASE_URL}/graphrag/v3/query/drift"
    payload = {
        "query": query,
        "max_iterations": 5,
        "convergence_threshold": 0.8,
        "include_reasoning_path": True
    }
    
    log(f"Query: {query}")
    try:
        start = time.time()
        response = requests.post(url, headers=HEADERS, json=payload)
        elapsed = time.time() - start
        log(f"Status: {response.status_code} (Time: {elapsed:.2f}s)")
        print_response(response)
    except Exception as e:
        log(f"Error: {e}")

if __name__ == "__main__":
    if check_stats():
        test_local_search()
        test_global_search()
        test_drift_search()
    else:
        log("Stats check failed. Data might not be indexed or group ID is incorrect.")
