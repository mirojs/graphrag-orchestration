#!/usr/bin/env python3
"""
Local test for comprehensive mode to verify _comprehensive_two_pass_extract works.
Tests the synthesis pipeline directly without the full API server.
"""
import asyncio
import os
import sys
import json

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set required environment variables if not already set
env_defaults = {
    "AZURE_OPENAI_ENDPOINT": "https://graphrag-openai.openai.azure.com/",
    "AZURE_OPENAI_DEPLOYMENT_NAME": "gpt-4o",  # Use gpt-4o which is widely deployed
    "AZURE_OPENAI_API_VERSION": "2024-10-21",
    "NEO4J_URI": "neo4j+s://a86dcf63.databases.neo4j.io",
    "NEO4J_USERNAME": "neo4j",
    "VOYAGE_V2_ENABLED": "true",
}

for key, val in env_defaults.items():
    if key not in os.environ:
        os.environ[key] = val

# Read secrets from .azure/default/.env if not set
def load_azure_env():
    env_file = os.path.join(os.path.dirname(__file__), ".azure", "default", ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            content = f.read()
            # Parse key=value pairs, handling multi-line values in quotes
            import re
            for match in re.finditer(r'^([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"', content, re.MULTILINE):
                key, val = match.groups()
                # Remove escaped newlines (\n literal) and actual newlines
                val = val.replace('\\n', '').replace('\n', '').strip()
                if key and val and key not in os.environ:
                    os.environ[key] = val
                # Handle lowercase keys
                if key == "azureOpenAiApiKey" and "AZURE_OPENAI_API_KEY" not in os.environ:
                    os.environ["AZURE_OPENAI_API_KEY"] = val
                if key == "neo4jPassword" and "NEO4J_PASSWORD" not in os.environ:
                    os.environ["NEO4J_PASSWORD"] = val
                if key == "voyageApiKey" and "VOYAGE_API_KEY" not in os.environ:
                    os.environ["VOYAGE_API_KEY"] = val

load_azure_env()

# Now import the modules
from src.worker.hybrid_v2.pipeline.synthesis import EvidenceSynthesizer
from src.worker.hybrid_v2.services.neo4j_store import Neo4jStoreV3 as Neo4jStore
from llama_index.llms.azure_openai import AzureOpenAI
import structlog

logger = structlog.get_logger()

TEST_QUERY = """List all areas of inconsistency identified in the invoice, organized by:
(1) all inconsistencies with corresponding evidence,
(2) inconsistencies in goods or services sold including detailed specifications for every line item, and
(3) inconsistencies regarding billing logistics and administrative or legal issues."""

TEST_GROUP_ID = "test-5pdfs-v2-enhanced-ex"


async def get_test_chunks_from_neo4j(group_id: str, limit: int = 50) -> list:
    """Fetch ALL text chunks from Neo4j for the test group (for comprehensive mode)."""
    from src.core.config import settings
    
    neo4j_store = Neo4jStore(
        uri=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
    )
    
    # Query for ALL text chunks (comprehensive mode needs all data)
    query = """
    MATCH (c:TextChunk)
    WHERE c.group_id = $group_id
    RETURN c.id AS id, 
           c.text AS text, 
           c.document_id AS document_id
    ORDER BY c.document_id, c.id
    LIMIT $limit
    """
    
    # Also get document metadata
    doc_query = """
    MATCH (d:Document)
    WHERE d.group_id = $group_id
    RETURN d.id AS id, d.title AS title
    """
    
    with neo4j_store.driver.session() as session:
        # Get chunks
        result = session.run(query, group_id=group_id, limit=limit)
        chunks = []
        for record in result:
            chunks.append({
                "id": record["id"],
                "text": record["text"],
                "document_id": record["document_id"],
            })
        
        # Get document titles
        doc_result = session.run(doc_query, group_id=group_id)
        doc_titles = {r["id"]: r["title"] for r in doc_result}
        
        # Enrich chunks with document titles
        for chunk in chunks:
            doc_id = chunk.get("document_id", "")
            chunk["document_title"] = doc_titles.get(doc_id, doc_id)
            chunk["document_source"] = ""
            chunk["metadata"] = {
                "document_id": doc_id,
                "document_title": chunk["document_title"],
                "section_path_key": "",
            }
        
        return chunks


async def test_comprehensive_mode():
    """Test the comprehensive two-pass extraction directly."""
    from src.core.config import settings
    
    print("\n" + "="*80)
    print("COMPREHENSIVE MODE LOCAL TEST")
    print("="*80)
    
    # Verify environment
    print(f"\nEnvironment:")
    print(f"  AZURE_OPENAI_ENDPOINT: {settings.AZURE_OPENAI_ENDPOINT}")
    print(f"  AZURE_OPENAI_DEPLOYMENT_NAME: {settings.AZURE_OPENAI_DEPLOYMENT_NAME}")
    print(f"  NEO4J_URI: {settings.NEO4J_URI}")
    print(f"  VOYAGE_V2_ENABLED: {settings.VOYAGE_V2_ENABLED}")
    
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("\n❌ ERROR: AZURE_OPENAI_API_KEY not set!")
        return
    print(f"  AZURE_OPENAI_API_KEY: {'*' * 10}...{api_key[-10:]}")
    
    neo4j_pass = os.environ.get("NEO4J_PASSWORD", "")
    if not neo4j_pass:
        print("\n❌ ERROR: NEO4J_PASSWORD not set!")
        return
    print(f"  NEO4J_PASSWORD: {'*' * 10}...{neo4j_pass[-5:]}")
    
    # Step 1: Get test chunks from Neo4j
    print(f"\n📚 Fetching chunks for group_id={TEST_GROUP_ID}...")
    try:
        chunks = await get_test_chunks_from_neo4j(TEST_GROUP_ID)
        print(f"   ✅ Fetched {len(chunks)} chunks")
        
        # Show document distribution
        docs = {}
        for c in chunks:
            doc = c.get("document_title", "Unknown")
            docs[doc] = docs.get(doc, 0) + 1
        print(f"   Documents: {docs}")
    except Exception as e:
        print(f"   ❌ Failed to fetch chunks: {e}")
        return
    
    if not chunks:
        print("   ❌ No chunks found!")
        return
    
    # Step 2: Initialize LLM
    print(f"\n🤖 Initializing LLM...")
    try:
        llm = AzureOpenAI(
            model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=api_key,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            temperature=0.0,
        )
        print(f"   ✅ LLM initialized: {settings.AZURE_OPENAI_DEPLOYMENT_NAME}")
    except Exception as e:
        print(f"   ❌ LLM init failed: {e}")
        return
    
    # Step 3: Create synthesizer and call comprehensive mode directly
    print(f"\n🔬 Testing _comprehensive_two_pass_extract...")
    print(f"   Query: {TEST_QUERY[:80]}...")
    
    synthesizer = EvidenceSynthesizer(llm_client=llm)
    
    evidence_nodes = [(c["document_id"], 1.0) for c in chunks[:5]]
    
    try:
        result = await synthesizer._comprehensive_two_pass_extract(
            query=TEST_QUERY,
            text_chunks=chunks,
            evidence_nodes=evidence_nodes
        )
        
        print(f"\n✅ COMPREHENSIVE MODE RESULT:")
        print(f"   response length: {len(result.get('response', ''))}")
        print(f"   raw_extractions: {len(result.get('raw_extractions', []))} documents")
        print(f"   citations: {len(result.get('citations', []))} items")
        print(f"   processing_mode: {result.get('processing_mode', 'N/A')}")
        print(f"   text_chunks_used: {result.get('text_chunks_used', 0)}")
        
        # Show raw_extractions summary
        if result.get("raw_extractions"):
            print(f"\n📋 RAW EXTRACTIONS:")
            for i, ext in enumerate(result["raw_extractions"][:3]):
                doc_id = ext.get("_document_id", ext.get("document_title", f"Doc {i+1}"))
                print(f"   [{i+1}] {doc_id[:50]}...")
                # Show some key fields
                if "amounts" in ext:
                    print(f"       amounts: {ext['amounts']}")
                if "parties" in ext:
                    print(f"       parties: {ext['parties']}")
        
        # Show response preview
        response_text = result.get("response", "")
        print(f"\n📝 RESPONSE PREVIEW:")
        print("-" * 60)
        print(response_text[:1500])
        if len(response_text) > 1500:
            print(f"... [{len(response_text) - 1500} more chars]")
        print("-" * 60)
        
        # Save full result
        output_file = f"test_comprehensive_local_result_{TEST_GROUP_ID}.json"
        with open(output_file, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\n💾 Full result saved to: {output_file}")
        
        return result
        
    except Exception as e:
        import traceback
        print(f"\n❌ COMPREHENSIVE MODE FAILED:")
        print(f"   Error: {e}")
        traceback.print_exc()
        return None


async def test_via_synthesis_pipeline():
    """Test comprehensive mode via the regular synthesize() method to verify routing."""
    from src.core.config import settings
    
    print("\n" + "="*80)
    print("TEST VIA SYNTHESIZE() WITH response_type='comprehensive'")
    print("="*80)
    
    api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
    if not api_key:
        print("\n❌ ERROR: AZURE_OPENAI_API_KEY not set!")
        return
    
    # Get chunks
    print(f"\n📚 Fetching chunks...")
    chunks = await get_test_chunks_from_neo4j(TEST_GROUP_ID)
    print(f"   Got {len(chunks)} chunks")
    
    # Initialize LLM
    llm = AzureOpenAI(
        model=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        deployment_name=settings.AZURE_OPENAI_DEPLOYMENT_NAME,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=api_key,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        temperature=0.0,
    )
    
    # Create synthesizer and call via synthesize() with response_type="comprehensive"
    synthesizer = EvidenceSynthesizer(llm_client=llm)
    evidence_nodes = [(c["document_id"], 1.0) for c in chunks[:5]]
    
    print(f"\n🔬 Calling synthesize(response_type='comprehensive')...")
    
    result = await synthesizer.synthesize(
        query=TEST_QUERY,
        text_chunks=chunks,
        evidence_nodes=evidence_nodes,
        response_type="comprehensive"
    )
    
    print(f"\n✅ RESULT:")
    print(f"   response length: {len(result.get('response', ''))}")
    print(f"   raw_extractions: {result.get('raw_extractions')}")
    print(f"   processing_mode: {result.get('processing_mode', 'N/A')}")
    
    # Save result
    output_file = "test_comprehensive_synthesize_result.json"
    with open(output_file, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n💾 Result saved to: {output_file}")
    
    return result


if __name__ == "__main__":
    print("Testing comprehensive mode locally...")
    
    # Test direct method call
    result1 = asyncio.run(test_comprehensive_mode())
    
    # Test via synthesize() routing
    if result1:
        result2 = asyncio.run(test_via_synthesis_pipeline())
