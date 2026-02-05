#!/usr/bin/env python3
"""
Quick test script to run Q-G10 standalone and compare with full benchmark results.
"""
import asyncio
import httpx
import json
from datetime import datetime

async def test_qg10():
    """Test Q-G10 question standalone."""
    
    url = "https://graphrag-api.salmonhill-df6033f3.swedencentral.azurecontainerapps.io"
    endpoint = f"{url}/hybrid/query"
    
    # Q-G10 from QUESTION_BANK_5PDFS_2025-12-24.md
    query = "Summarize each document's main purpose in one sentence."
    
    # Use the same group_id as the full benchmark
    group_id = "test-5pdfs-1768557493369886422"
    
    print(f"Testing Q-G10 standalone at {datetime.utcnow().isoformat()}Z")
    print(f"URL: {endpoint}")
    print(f"Group ID: {group_id}")
    print(f"Query: {query}")
    print("-" * 80)
    
    payload = {
        "query": query,
        "force_route": "global_search",
        "response_type": "summary"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Group-ID": group_id
    }
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            
            # Extract the answer text
            answer = result.get("response", "") or result.get("answer", "")
            
            print("\n=== RESPONSE ===")
            print(answer)
            print("\n" + "=" * 80)
            
            # Check for thematic terms
            expected_terms = ["warranty", "arbitration", "servicing", "management", "invoice", "scope of work", "payment"]
            answer_lower = answer.lower()
            
            print("\n=== THEMATIC TERM CHECK ===")
            found_terms = []
            missing_terms = []
            
            for term in expected_terms:
                if term in answer_lower:
                    found_terms.append(term)
                    print(f"✓ Found: {term}")
                else:
                    missing_terms.append(term)
                    print(f"✗ MISSING: {term}")
            
            print(f"\nCoverage: {len(found_terms)}/{len(expected_terms)} ({len(found_terms)/len(expected_terms)*100:.1f}%)")
            
            if missing_terms:
                print(f"\n⚠️  Missing terms: {', '.join(missing_terms)}")
            else:
                print("\n✅ All thematic terms present!")
            
            # Count document summaries
            lines = [line.strip() for line in answer.split('\n') if line.strip()]
            numbered_lines = [line for line in lines if line and line[0].isdigit() and '. ' in line[:5]]
            
            print(f"\n=== DOCUMENT COUNT ===")
            print(f"Number of document summaries: {len(numbered_lines)}")
            if len(numbered_lines) != 5:
                print(f"⚠️  Expected 5 documents, got {len(numbered_lines)}")
                for i, line in enumerate(numbered_lines, 1):
                    # Show first 100 chars of each summary
                    print(f"  {i}. {line[:100]}...")
            
            # Save result to file
            timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            output_file = f"test_qg10_standalone_{timestamp}.json"
            
            with open(output_file, 'w') as f:
                json.dump({
                    "timestamp": timestamp,
                    "query": query,
                    "group_id": group_id,
                    "answer": answer,
                    "thematic_check": {
                        "expected": expected_terms,
                        "found": found_terms,
                        "missing": missing_terms,
                        "coverage": len(found_terms) / len(expected_terms)
                    },
                    "document_count": len(numbered_lines),
                    "full_result": result
                }, f, indent=2)
            
            print(f"\n📄 Full result saved to: {output_file}")
            
        except httpx.HTTPError as e:
            print(f"❌ HTTP Error: {e}")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_qg10())
