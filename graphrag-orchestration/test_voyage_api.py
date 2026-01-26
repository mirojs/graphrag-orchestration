"""
Quick test to verify Voyage AI voyage-context-3 API is working.

Run: python test_voyage_api.py
"""
import os
import sys

# Check if API key is set
api_key = os.environ.get("VOYAGE_API_KEY")
if not api_key:
    print("❌ VOYAGE_API_KEY not set in environment")
    print("   Set it with: export VOYAGE_API_KEY='your-key'")
    sys.exit(1)

print(f"✅ VOYAGE_API_KEY is set (length: {len(api_key)})")

# Try importing voyageai
try:
    import voyageai
    print(f"✅ voyageai package installed (version: {voyageai.__version__})")
except ImportError:
    print("❌ voyageai not installed. Install with: pip install voyageai")
    sys.exit(1)

# Initialize client
client = voyageai.Client(api_key=api_key)
print("✅ Voyage client initialized")

# Test 1: Simple embedding (non-contextual)
print("\n--- Test 1: Simple Embedding ---")
try:
    result = client.embed(
        texts=["Hello world"],
        model="voyage-context-3",
        input_type="document",
        output_dimension=2048,
    )
    emb = result.embeddings[0]
    print(f"✅ Simple embedding works!")
    print(f"   Dimension: {len(emb)}")
    print(f"   First 5 values: {emb[:5]}")
except Exception as e:
    print(f"❌ Simple embedding failed: {e}")

# Test 2: Contextual embedding (the key feature for V2)
print("\n--- Test 2: Contextual Embedding ---")
try:
    # Format: List of documents, where each document is a list of chunks
    documents = [
        # Document 1: Two chunks about a contract
        [
            "This agreement is made between Acme Corp and Contoso Ltd.",
            "The parties agree to the following terms and conditions.",
        ],
        # Document 2: Single chunk about another topic
        [
            "华为技术有限公司是一家全球领先的ICT解决方案提供商。",  # Chinese text test
        ]
    ]
    
    result = client.contextualized_embed(
        inputs=documents,
        model="voyage-context-3",
        input_type="document",
        output_dimension=2048,
    )
    
    print(f"✅ Contextual embedding works!")
    print(f"   Documents processed: {len(result.results)}")
    for doc_idx, doc_result in enumerate(result.results):
        print(f"   Doc {doc_idx}: {len(doc_result.embeddings)} chunks embedded")
        print(f"      Chunk 0 dim: {len(doc_result.embeddings[0])}")
        
except Exception as e:
    print(f"❌ Contextual embedding failed: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Query embedding
print("\n--- Test 3: Query Embedding ---")
try:
    queries = [
        ["What are the contract terms?"],
        ["Tell me about Huawei"]
    ]
    
    result = client.contextualized_embed(
        inputs=queries,
        model="voyage-context-3",
        input_type="query",
        output_dimension=2048,
    )
    
    print(f"✅ Query embedding works!")
    print(f"   Queries processed: {len(result.results)}")
    
except Exception as e:
    print(f"❌ Query embedding failed: {e}")

# Summary
print("\n" + "="*50)
print("SUMMARY: Voyage API is ready for V2!" if 'result' in dir() else "SUMMARY: Some tests failed")
print("="*50)
