#!/usr/bin/env python3
"""
GraphRAG v3 - PDF Test with Schema-Based Extraction
Tests 5 PDFs with timing for each process step
"""
import os
import requests
import json
import sys
import time
import base64
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Tuple

# Configuration
BASE_URL = "https://graphrag-orchestration.purplefield-1719ccc0.swedencentral.azurecontainerapps.io"
TEST_GROUP_ID = f"pdf-schema-test-{int(time.time())}"

# Prefer repo-local copies of the five production PDFs; fall back to the older shared path if present.
_default_pdf_dir = Path(__file__).parent / "graphrag-orchestration" / "data" / "input_docs"
_legacy_pdf_dir = Path("/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/input_docs")
PDF_DIR = Path(os.getenv("PDF_DIR", _default_pdf_dir if _default_pdf_dir.exists() else _legacy_pdf_dir))

# Schema file path can be overridden; if missing we continue but log a warning.
_default_schema_path = Path(__file__).parent / "graphrag-orchestration" / "data" / "CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json"
_legacy_schema_path = Path("/afh/projects/vs-code-development-project-3-6f0bbb9a-4fab-4d99-9cdb-2fe63103e939/data/CLEAN_SCHEMA_INVOICE_CONTRACT_VERIFICATION_OPTIMIZED.json")
SCHEMA_PATH = Path(os.getenv("SCHEMA_PATH", _default_schema_path if _default_schema_path.exists() else _legacy_schema_path))
SCHEMA_URL = os.getenv("SCHEMA_URL")
RESOLVED_SCHEMA_PATH: Path | None = None

# PDF files to test
PDF_FILES = [
    "contoso_lifts_invoice.pdf",
    "purchase_contract.pdf",
    "PROPERTY MANAGEMENT AGREEMENT.pdf",
    "BUILDERS LIMITED WARRANTY.pdf",
    "HOLDING TANK SERVICING CONTRACT.pdf"
]

TEST_QUERIES = [
    "What are the total amounts and payment terms mentioned?",
    "What companies or parties are involved?",
    "What services or equipment are being provided?",
    "What are the contract dates and durations?",
]


class Timer:
    """Simple timer for measuring execution time"""
    def __init__(self, name: str):
        self.name = name
        self.start_time = None
        self.end_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        print(f"\n⏱️  Starting: {self.name}...")
        return self
    
    def __exit__(self, *args):
        self.end_time = time.time()
        elapsed = self.end_time - self.start_time
        print(f"✅ Completed: {self.name}")
        print(f"   ⏱️  Time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
    
    @property
    def elapsed(self) -> float:
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return 0


def print_header(text: str):
    """Print a formatted header"""
    print(f"\n{'=' * 80}")
    print(f"  {text}")
    print(f"{'=' * 80}\n")


def print_result(success: bool, message: str):
    """Print a formatted result"""
    symbol = "✅" if success else "❌"
    print(f"{symbol} {message}")


def load_pdf_files() -> Tuple[List[Dict[str, str]], float]:
    """Load PDF files and encode them as base64"""
    with Timer("PDF File Loading") as timer:
        files_data = []
        
        for pdf_file in PDF_FILES:
            pdf_path = PDF_DIR / pdf_file
            
            if not pdf_path.exists():
                print(f"  ⚠️  File not found: {pdf_file}")
                continue
            
            with open(pdf_path, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
                files_data.append({
                    "filename": pdf_file,
                    "content": content,
                    "content_type": "application/pdf"
                })
            
            size_mb = len(content) / 1024 / 1024
            print(f"  ✅ Loaded: {pdf_file} ({size_mb:.2f} MB encoded)")
        
        total_size = sum(len(f['content']) for f in files_data) / 1024 / 1024
        print(f"\n  📊 Total: {len(files_data)} files, {total_size:.2f} MB")
    
    return files_data, timer.elapsed


def download_schema_from_url(url: str) -> Path | None:
    """Download schema from URL to a temp path; return path on success"""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        target_name = Path(url.split("?")[0]).name or "schema.json"
        target_path = Path(tempfile.gettempdir()) / target_name
        target_path.write_bytes(response.content)
        print(f"  ✅ Downloaded schema from URL to {target_path}")
        return target_path
    except Exception as exc:  # pragma: no cover - depends on infra
        print(f"  ❌ Failed to download schema from {url}: {exc}")
        return None


def load_schema() -> Tuple[Dict[str, Any], float]:
    """Load the extraction schema if available"""
    global RESOLVED_SCHEMA_PATH

    with Timer("Schema Loading") as timer:
        schema_path = SCHEMA_PATH

        if SCHEMA_URL:
            downloaded = download_schema_from_url(SCHEMA_URL)
            if downloaded:
                schema_path = downloaded

        if not schema_path.exists():
            print(f"  ⚠️ Schema not found: {schema_path}")
            RESOLVED_SCHEMA_PATH = None
            return None, timer.elapsed

        with open(schema_path, 'r') as f:
            schema = json.load(f)

        RESOLVED_SCHEMA_PATH = schema_path
        print(f"  ✅ Loaded: {schema_path.name}")
        print(f"  📋 Schema fields: {len(schema.get('properties', {}))}")

    return schema, timer.elapsed


def test_indexing_with_schema(files_data: List[Dict], schema: Dict) -> Tuple[Dict[str, Any], float]:
    """Test document indexing with PDF files using batch processing"""
    print_header("PDF INDEXING WITH DOCUMENT INTELLIGENCE (BATCHED)")
    
    print(f"Group ID: {TEST_GROUP_ID}")
    print(f"Total PDFs: {len(files_data)}")
    print(f"Batch Size: 2 PDFs per request (to avoid gateway timeout)")
    schema_path = RESOLVED_SCHEMA_PATH or SCHEMA_PATH
    schema_status = schema_path.name if schema else f"{schema_path.name} (missing)"
    print(f"Schema loaded: {schema_status}")
    print("NOTE: /v3/index uses LlamaIndex entity extraction, not JSON schema")
    print("      For schema-based extraction, use /index-from-schema endpoint\n")
    
    # Aggregate stats across all batches
    total_stats = {
        "documents_processed": 0,
        "entities_created": 0,
        "relationships_created": 0,
        "communities_created": 0,
        "raptor_nodes_created": 0
    }
    
    batch_size = 2
    num_batches = (len(files_data) + batch_size - 1) // batch_size
    
    with Timer("PDF Indexing (All Batches)") as timer:
        for batch_num in range(num_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(files_data))
            batch = files_data[start_idx:end_idx]
            
            print(f"\n{'─' * 80}")
            print(f"📦 Batch {batch_num + 1}/{num_batches}: Processing {len(batch)} PDFs")
            for pdf in batch:
                print(f"   • {pdf['filename']}")
            print(f"{'─' * 80}\n")
            
            batch_start = time.time()
            
            try:
                # Prepare documents for this batch
                documents = []
                for pdf in batch:
                    documents.append({
                        "text": pdf["content"],  # Full base64 content
                        "metadata": {
                            "filename": pdf["filename"],
                            "content_type": pdf["content_type"]
                        }
                    })
                
                response = requests.post(
                    f"{BASE_URL}/graphrag/v3/index",
                    headers={
                        'Content-Type': 'application/json',
                        'X-Group-ID': TEST_GROUP_ID
                    },
                    json={
                        "documents": documents,
                        "ingestion": "document-intelligence",  # Use Azure DI for PDF extraction
                        "run_raptor": True,
                        "run_community_detection": True
                    },
                    timeout=240  # Match gateway timeout (4 minutes)
                )
                
                batch_time = time.time() - batch_start
                
                # Try to parse response
                try:
                    result = response.json()
                except Exception as json_error:
                    print_result(False, f"Batch {batch_num + 1} failed to parse JSON")
                    print(f"  Status Code: {response.status_code}")
                    print(f"  Response Text: {response.text[:500]}")
                    print(f"  Batch Time: {batch_time:.2f}s")
                    continue
                
                if response.status_code == 200:
                    print_result(True, f"Batch {batch_num + 1} completed in {batch_time:.2f}s")
                    print(f"  📄 Documents: {result.get('documents_processed', 0)}")
                    print(f"  🏷️  Entities: {result.get('entities_created', 0)}")
                    print(f"  🔗 Relationships: {result.get('relationships_created', 0)}")
                    print(f"  👥 Communities: {result.get('communities_created', 0)}")
                    print(f"  🌳 RAPTOR nodes: {result.get('raptor_nodes_created', 0)}")
                    
                    # Aggregate stats
                    for key in total_stats.keys():
                        total_stats[key] += result.get(key, 0)
                else:
                    print_result(False, f"Batch {batch_num + 1} failed: Status {response.status_code}")
                    print(f"  Error: {json.dumps(result, indent=2)[:200]}")
                    print(f"  Batch Time: {batch_time:.2f}s")
                    
            except Exception as e:
                batch_time = time.time() - batch_start
                print_result(False, f"Batch {batch_num + 1} exception: {str(e)}")
                print(f"  Batch Time: {batch_time:.2f}s")
        
        # Print totals
        print(f"\n{'═' * 80}")
        print(f"📊 TOTAL RESULTS ACROSS ALL BATCHES:")
        print(f"{'═' * 80}")
        print(f"  📄 Total Documents: {total_stats['documents_processed']}")
        print(f"  🏷️  Total Entities: {total_stats['entities_created']}")
        print(f"  🔗 Total Relationships: {total_stats['relationships_created']}")
        print(f"  👥 Total Communities: {total_stats['communities_created']}")
        print(f"  🌳 Total RAPTOR nodes: {total_stats['raptor_nodes_created']}")
        print(f"{'═' * 80}\n")
    
    return total_stats if total_stats['documents_processed'] > 0 else None, timer.elapsed


def test_queries(query_type: str) -> Tuple[List[Dict], float]:
    """Test queries with timing"""
    print_header(f"{query_type.upper()} QUERIES")
    
    results = []
    start_time = time.time()
    
    for i, query in enumerate(TEST_QUERIES, 1):
        print(f"\n{'─' * 80}")
        print(f"Query {i}/{len(TEST_QUERIES)}: {query}")
        print(f"{'─' * 80}")
        
        query_start = time.time()
        
        try:
            endpoint_map = {
                "drift": "drift",
                "local": "local",
                "global": "global"
            }
            
            # Increase timeout for DRIFT queries (they use embeddings and can be slow)
            timeout = 120 if query_type == "drift" else 60
            
            response = requests.post(
                f"{BASE_URL}/graphrag/v3/query/{endpoint_map[query_type]}",
                headers={
                    'Content-Type': 'application/json',
                    'X-Group-ID': TEST_GROUP_ID
                },
                json={"query": query},
                timeout=timeout
            )
            
            result = response.json()
            query_time = time.time() - query_start
            
            if response.status_code == 200:
                answer = result.get('answer', '')
                confidence = result.get('confidence', 0)
                sources = len(result.get('sources', []))
                
                print_result(True, f"Query succeeded in {query_time:.2f}s")
                print(f"  📊 Confidence: {confidence:.2f}")
                print(f"  📚 Sources: {sources}")
                print(f"  💬 Answer: {answer[:200]}{'...' if len(answer) > 200 else ''}")
                
                results.append({
                    "query": query,
                    "success": True,
                    "time": query_time,
                    "confidence": confidence,
                    "sources": sources
                })
            else:
                print_result(False, f"Status: {response.status_code}")
                results.append({
                    "query": query,
                    "success": False,
                    "time": query_time,
                    "error": result
                })
                
        except Exception as e:
            query_time = time.time() - query_start
            print_result(False, f"Exception: {str(e)}")
            results.append({
                "query": query,
                "success": False,
                "time": query_time,
                "error": str(e)
            })
    
    total_time = time.time() - start_time
    
    print(f"\n{'─' * 80}")
    print(f"⏱️  Total query time: {total_time:.2f} seconds")
    print(f"⏱️  Average per query: {total_time/len(TEST_QUERIES):.2f} seconds")
    
    return results, total_time


def print_timing_summary(timings: Dict[str, float]):
    """Print comprehensive timing summary"""
    print_header("TIMING SUMMARY")
    
    print("📊 Process Breakdown:\n")
    
    total = 0
    for process, duration in timings.items():
        minutes = duration / 60
        print(f"  {process:.<50} {duration:>6.2f}s ({minutes:.2f}m)")
        total += duration
    
    print(f"  {'─' * 50}")
    print(f"  {'TOTAL':.<50} {total:>6.2f}s ({total/60:.2f}m)")
    
    print(f"\n{'=' * 80}")


def print_final_summary(results: Dict[str, Any]):
    """Print final test summary"""
    print_header("FINAL SUMMARY")
    
    print("📋 Test Results:\n")
    
    for test_name, result in results.items():
        if isinstance(result, dict) and 'success' in result:
            print_result(result['success'], test_name)
        elif isinstance(result, bool):
            print_result(result, test_name)
        elif result is not None:
            print_result(True, test_name)
        else:
            print_result(False, test_name)
    
    print(f"\n{'=' * 80}")


def main():
    """Run all tests with comprehensive timing"""
    print("\n" + "=" * 80)
    print("  GraphRAG v3 - PDF Test Suite with Schema & Timing")
    print("  Testing: 5 PDFs with managed identity authentication")
    print("=" * 80)
    
    timings = {}
    results = {}
    
    # Step 1: Load PDFs
    files_data, load_time = load_pdf_files()
    timings["1. PDF Loading"] = load_time
    results["PDF Loading"] = len(files_data) == len(PDF_FILES)
    
    if not files_data:
        print("\n❌ No PDF files loaded. Exiting.")
        sys.exit(1)
    
    # Step 2: Load Schema
    schema, schema_time = load_schema()
    timings["2. Schema Loading"] = schema_time
    results["Schema Loading"] = schema is not None
    if schema is None:
        print("\n⚠️ Schema file is missing; continuing without schema context.")
    
    # Step 3: Index with Schema
    indexing_result, indexing_time = test_indexing_with_schema(files_data, schema)
    timings["3. PDF Indexing"] = indexing_time
    results["PDF Indexing"] = indexing_result is not None
    
    if not indexing_result:
        print("\n❌ Indexing failed. Skipping queries.")
        print_timing_summary(timings)
        sys.exit(1)
    
    # Wait for data propagation
    print("\n⏳ Waiting 5 seconds for data propagation...")
    time.sleep(5)
    
    # Step 4: DRIFT Queries
    drift_results, drift_time = test_queries("drift")
    timings["4. DRIFT Queries (Embeddings)"] = drift_time
    results["DRIFT Queries"] = all(r['success'] for r in drift_results)
    
    # Step 5: Local Queries
    local_results, local_time = test_queries("local")
    timings["5. Local Queries"] = local_time
    results["Local Queries"] = all(r['success'] for r in local_results)
    
    # Step 6: Global Queries
    global_results, global_time = test_queries("global")
    timings["6. Global Queries"] = global_time
    results["Global Queries"] = all(r['success'] for r in global_results)
    
    # Print summaries
    print_timing_summary(timings)
    print_final_summary(results)
    
    # Print query performance
    print_header("QUERY PERFORMANCE ANALYSIS")
    
    all_query_results = drift_results + local_results + global_results
    successful_queries = [r for r in all_query_results if r['success']]
    
    if successful_queries:
        avg_time = sum(r['time'] for r in successful_queries) / len(successful_queries)
        avg_confidence = sum(r.get('confidence', 0) for r in successful_queries) / len(successful_queries)
        
        print(f"  Total Queries: {len(all_query_results)}")
        print(f"  Successful: {len(successful_queries)}")
        print(f"  Average Query Time: {avg_time:.2f} seconds")
        print(f"  Average Confidence: {avg_confidence:.2f}")
    
    print(f"\n{'=' * 80}\n")
    
    # Exit with appropriate code
    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
