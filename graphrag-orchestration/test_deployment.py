
import requests
import json
import time

# Configuration
BASE_URL = "https://graphrag-orchestration.ashypebble-48100d7f.swedencentral.azurecontainerapps.io"
GROUP_ID = "test-group-strict-fix"
API_KEY = "your-api-key-if-needed"  # Assuming no auth or handled by headers

def test_indexing():
    print(f"Testing indexing on {BASE_URL}...")
    
    # 1. Index a document
    endpoint = f"{BASE_URL}/graphrag/v3/index"
    headers = {
        "X-Group-ID": GROUP_ID,
        "Content-Type": "application/json"
    }
    
    # Long document to trigger chunking and Raptor (needs > 1 chunk)
    base_text = """
    Microsoft Corporation announced a new partnership with OpenAI today.
    Satya Nadella, the CEO of Microsoft, met with Sam Altman in San Francisco.
    The deal involves a $10 billion investment in artificial intelligence research.
    This partnership aims to accelerate breakthroughs in AI and ensure these benefits are broadly shared with the world.
    OpenAI and Microsoft will jointly build new Azure AI supercomputing systems.
    Microsoft will become OpenAI's exclusive cloud provider.
    """
    long_text = base_text * 50  # Repeat to ensure > 1024 tokens for chunking

    payload = {
        "documents": [
            {
                "content": long_text,
                "title": "Microsoft OpenAI Partnership (Long)",
                "source": "TechNews"
            }
        ],
        "run_raptor": True,  # Enable to test Raptor
        "run_community_detection": False, # Disable for speed
        "ingestion": "none"
    }
    
    try:
        print(f"Sending request to {endpoint}...")
        response = requests.post(endpoint, headers=headers, json=payload, timeout=300)
        
        if response.status_code == 200:
            print("✅ Indexing request successful!")
            result = response.json()
            print(json.dumps(result, indent=2))
            
            # Check stats
            entities = result.get("entities_created", 0)
            relations = result.get("relationships_created", 0)
            
            if entities > 0 and relations > 0:
                print(f"\n✅ SUCCESS: Extracted {entities} entities and {relations} relationships.")
                print("The strict=True fix is working correctly in production!")
            else:
                print(f"\n⚠️ WARNING: Extracted {entities} entities and {relations} relationships.")
                print("This might indicate the fix is NOT working or the model returned nothing.")
                
        else:
            print(f"❌ Request failed with status {response.status_code}")
            print(response.text)
            
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_indexing()
