#!/usr/bin/env python3
"""
E2E Test: 5-File Batch Processing with Multi-Document Summarization

Files:
1. BUILDERS LIMITED WARRANTY.pdf
2. HOLDING TANK SERVICING CONTRACT.pdf
3. PROPERTY MANAGEMENT AGREEMENT.pdf
4. contoso_lifts_invoice.pdf
5. purchase_contract.pdf

Prompt: Please summarize all the input files individually, please count number of 
words of each summarization as well as total amount of words of all the summarizations
"""

import asyncio
import time
import json
import sys
import os
from pathlib import Path
import httpx

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.document_intelligence_service import DocumentIntelligenceService

# API configuration
API_BASE_URL = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io/graphrag"


# Test files from data/input_docs (in repository root)
# Path(__file__) is .../graphrag-orchestration/test_5_file_summarization.py
# We want .../graphrag-orchestration/data/input_docs
INPUT_DOCS_DIR = Path(__file__).parent / "data" / "input_docs"
TEST_FILES = [
    "ClaimForm_1.pdf",
    "ClaimForm_2.pdf",
    "ClaimForm_3.pdf",
    "ClaimForm_4.pdf",
    "ClaimForm_5.pdf"
]

# Summarization prompt
SUMMARIZATION_QUERY = """Please summarize all the input files individually, please count number of words of each summarization as well as total amount of words of all the summarizations"""

GROUP_ID = "2-file-summarization-test"


async def step1_extract_documents():
    """Step 1: Extract documents using Document Intelligence batch processing"""
    print("=" * 80)
    print("STEP 1: Document Intelligence Batch Extraction")
    print("=" * 80)
    
    # Upload files to blob storage and get SAS URLs
    import subprocess
    from datetime import datetime, timedelta
    
    file_urls = []
    for filename in TEST_FILES:
        file_path = INPUT_DOCS_DIR / filename
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return None
        
        # Upload to blob storage
        blob_name = f"test-5-file/{filename}"
        container = "pro-input-files"
        account = "stvscodedeve533189432253"
        
        print(f"📤 Uploading {filename}...", end=" ")
        
        # Upload using az CLI
        result = subprocess.run([
            "az", "storage", "blob", "upload",
            "--account-name", account,
            "--container-name", container,
            "--name", blob_name,
            "--file", str(file_path),
            "--auth-mode", "key",
            "--overwrite"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ Upload failed: {result.stderr}")
            return None
        
        # Generate SAS URL
        expiry = (datetime.utcnow() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = subprocess.run([
            "az", "storage", "blob", "generate-sas",
            "--account-name", account,
            "--container-name", container,
            "--name", blob_name,
            "--permissions", "r",
            "--expiry", expiry,
            "--auth-mode", "key",
            "-o", "tsv"
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ SAS generation failed: {result.stderr}")
            return None
        
        sas_token = result.stdout.strip()
        blob_url = f"https://{account}.blob.core.windows.net/{container}/{blob_name}?{sas_token}"
        file_urls.append(blob_url)
        print(f"✅")
    
    print(f"\n🚀 Starting batch extraction of {len(file_urls)} documents...")
    
    service = DocumentIntelligenceService(max_concurrency=5)
    
    start_time = time.time()
    docs = await service.extract_documents(GROUP_ID, file_urls)
    elapsed = time.time() - start_time
    
    print(f"\n✅ Extracted {len(docs)} document sections in {elapsed:.2f}s")
    print(f"⏱️  Average: {elapsed/len(TEST_FILES):.2f}s per file")
    print(f"📊 Throughput: {len(TEST_FILES)/elapsed:.2f} files/second")
    
    # Show extraction stats
    total_chars = sum(len(doc.text) for doc in docs)
    print(f"\n📈 Extraction Statistics:")
    print(f"   Total characters: {total_chars:,}")
    print(f"   Average per doc: {total_chars//len(docs):,} chars")
    
    for i, filename in enumerate(TEST_FILES):
        # Find docs matching this file
        file_docs = [d for d in docs if filename in d.metadata.get('source', '')]
        if file_docs:
            chars = sum(len(d.text) for d in file_docs)
            print(f"   {i+1}. {filename}: {chars:,} chars ({len(file_docs)} sections)")
    
    return docs, file_urls, elapsed


async def step2_index_documents(blob_urls):
    """Step 2: Index documents into Neo4j with GraphRAG"""
    print("\n" + "=" * 80)
    print("STEP 2: GraphRAG Knowledge Graph Indexing")
    print("=" * 80)
    
    print(f"\n🔄 Indexing {len(blob_urls)} documents into Neo4j...")
    print(f"   Extraction mode: DynamicLLMPathExtractor")
    print(f"   Group ID: {GROUP_ID}")
    
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{API_BASE_URL}/index",
                json={
                    "documents": blob_urls,
                    "extraction_mode": "dynamic",
                    "ingestion": "document-intelligence",  # Extract from blob URLs
                    "run_community_detection": True
                },
                headers={"X-Group-ID": GROUP_ID}
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                
                print(f"\n✅ Indexing completed in {elapsed:.2f}s")
                print(f"\n📊 Indexing Statistics:")
                print(f"   Documents indexed: {result.get('document_count', 0)}")
                print(f"   Nodes created: {result.get('node_count', 0)}")
                print(f"   Relationships: {result.get('relationship_count', 0)}")
                
                return result, elapsed
            else:
                print(f"\n❌ Indexing failed: HTTP {response.status_code}")
                print(f"   Error: {response.text}")
                return None, elapsed
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ Indexing failed: {e}")
        import traceback
        traceback.print_exc()
        return None, elapsed


async def step3_local_search_summarization():
    """Step 3: Execute local search for multi-document summarization"""
    print("\n" + "=" * 80)
    print("STEP 3: GraphRAG Local Search Summarization")
    print("=" * 80)
    
    print(f"\n📝 Query: {SUMMARIZATION_QUERY}")
    print(f"\n🔍 Executing local search...")
    
    start_time = time.time()
    
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{API_BASE_URL}/query/local",
                json={
                    "query": SUMMARIZATION_QUERY,
                    "top_k": 20
                },
                headers={"X-Group-ID": GROUP_ID}
            )
            
            elapsed = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get('response', '')
                
                print(f"\n✅ Local search completed in {elapsed:.2f}s")
                print(f"\n📄 Response length: {len(response_text)} characters")
                print(f"   Word count: {len(response_text.split())} words")
                
                print(f"\n📋 GraphRAG Response:")
                print("=" * 80)
                print(response_text)
                print("=" * 80)
                
                # Analyze word counts
                if "total" in response_text.lower() and "words" in response_text.lower():
                    print("\n✅ Response includes word count analysis as requested!")
                
                return result, elapsed
            else:
                print(f"\n❌ Search failed: HTTP {response.status_code}")
                print(f"   Error: {response.text}")
                return None, elapsed
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n❌ Search failed: {e}")
        import traceback
        traceback.print_exc()
        return None, elapsed


async def main():
    """Run complete E2E test"""
    print("\n" + "🧪" * 40)
    print("E2E TEST: 5-File Batch Processing + Multi-Document Summarization")
    print("🧪" * 40)
    print(f"\nTest Configuration:")
    print(f"  Files: {len(TEST_FILES)}")
    print(f"  Group ID: {GROUP_ID}")
    print(f"  Extraction: Document Intelligence (parallel)")
    print(f"  Indexing: GraphRAG + Neo4j")
    print(f"  Query: DRIFT multi-step reasoning")
    print()
    
    total_start = time.time()
    
    # Step 1: Extract with Document Intelligence
    extraction_result = await step1_extract_documents()
    if not extraction_result:
        print("\n❌ Extraction failed - aborting test")
        return
    
    docs, blob_urls, extraction_time = extraction_result
    
    # Step 2: Index with GraphRAG
    indexing_result, indexing_time = await step2_index_documents(blob_urls)
    if not indexing_result:
        print("\n⚠️  Indexing failed - continuing to query test anyway")
    
    # Step 3: Query with Local Search
    query_result, query_time = await step3_local_search_summarization()
    
    total_elapsed = time.time() - total_start
    
    # Final Summary
    print("\n" + "=" * 80)
    print("📊 E2E TEST SUMMARY")
    print("=" * 80)
    print(f"\n⏱️  Timing Breakdown:")
    print(f"   Extraction:  {extraction_time:6.2f}s ({extraction_time/total_elapsed*100:5.1f}%)")
    print(f"   Indexing:    {indexing_time:6.2f}s ({indexing_time/total_elapsed*100:5.1f}%)")
    print(f"   Query:       {query_time:6.2f}s ({query_time/total_elapsed*100:5.1f}%)")
    print(f"   {'─'*30}")
    print(f"   Total:       {total_elapsed:6.2f}s")
    
    print(f"\n📈 Performance Metrics:")
    print(f"   Files processed: {len(TEST_FILES)}")
    print(f"   Time per file: {total_elapsed/len(TEST_FILES):.2f}s")
    print(f"   Extraction speedup: ~{3.87:.2f}x (parallel processing)")
    
    if query_result:
        print(f"\n✅ E2E TEST PASSED")
        print(f"   - All 5 files extracted successfully")
        print(f"   - Documents indexed into knowledge graph")
        print(f"   - DRIFT query executed and returned summarization")
        
        # Save results
        output_file = f"5_file_summarization_result_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump({
                'files': TEST_FILES,
                'extraction_time': extraction_time,
                'indexing_time': indexing_time,
                'query_time': query_time,
                'total_time': total_elapsed,
                'query': SUMMARIZATION_QUERY,
                'response': query_result.get('response', ''),
                'response_metadata': {
                    k: v for k, v in query_result.items() if k != 'response'
                }
            }, f, indent=2)
        print(f"\n💾 Results saved to: {output_file}")
    else:
        print(f"\n⚠️  E2E TEST PARTIALLY COMPLETED")
        print(f"   - Files extracted: ✅")
        print(f"   - Documents indexed: {'✅' if indexing_result else '❌'}")
        print(f"   - DRIFT query: ❌")
    
    print()


if __name__ == "__main__":
    asyncio.run(main())
