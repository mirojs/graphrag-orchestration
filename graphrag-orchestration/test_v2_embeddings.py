"""Test V2 embeddings with Azure DI + Voyage contextualized_embed"""

import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

# Set Voyage API key
os.environ['VOYAGE_API_KEY'] = 'al-xRhrLGWWq3FdZFjC3Fn0Mqw68wYWlO1NvcrwujecQW2'

from app.services.cu_standard_ingestion_service_v2 import CUStandardIngestionServiceV2
from app.hybrid_v2.embeddings.voyage_embed import VoyageEmbedService

# 5 test PDFs - need SAS URLs for Azure DI
# For local testing, we'll simulate with sections from existing data

async def test_with_simulated_sections():
    """Test with simulated section data (skip Azure DI for now)"""
    
    # Simulated section chunks (like what Azure DI would return)
    documents_by_doc = {
        "BUILDERS LIMITED WARRANTY.pdf": [
            "## LIMITED WARRANTY\n\nThis limited warranty provides coverage for defects in materials and workmanship.",
            "## COVERAGE PERIOD\n\nThe warranty period begins on the closing date and extends for one year.",
            "## EXCLUSIONS\n\nThis warranty does not cover damage caused by Acts of God, owner negligence, or normal wear and tear.",
        ],
        "HOLDING TANK SERVICING CONTRACT.pdf": [
            "## SERVICE AGREEMENT\n\nThis contract covers quarterly inspection and pumping services for septic systems.",
            "## PAYMENT TERMS\n\nPayment is due within 30 days of service completion.",
        ],
        "PROPERTY MANAGEMENT AGREEMENT.pdf": [
            "## MANAGEMENT SERVICES\n\nThe manager agrees to collect rent, arrange repairs, and handle tenant relations.",
            "## COMPENSATION\n\nManager shall receive 8% of gross monthly rent as management fee.",
            "## TERM\n\nThis agreement shall remain in effect for one year from the date of execution.",
        ],
        "purchase_contract.pdf": [
            "## PURCHASE PRICE\n\nThe total purchase price shall be $450,000 payable at closing.",
            "## CONTINGENCIES\n\nThis agreement is contingent upon satisfactory home inspection and financing approval.",
            "## CLOSING DATE\n\nClosing shall occur within 45 days of contract acceptance.",
            "## EARNEST MONEY\n\nBuyer shall deposit $10,000 earnest money within 3 business days.",
        ],
        "contoso_lifts_invoice.pdf": [
            "## INVOICE\n\nContoso Lifts - Elevator Maintenance Services\nTotal Due: $2,500.00",
        ],
    }
    
    print(f"Documents: {len(documents_by_doc)}")
    total_chunks = sum(len(c) for c in documents_by_doc.values())
    print(f"Total chunks: {total_chunks}")
    
    # Initialize Voyage service
    svc = VoyageEmbedService()
    print(f"\nVoyage model: {svc.model_name}")
    print(f"Embedding dim: {svc.embed_dim}")
    
    # Format for contextualized_embed: List[List[str]]
    doc_names = list(documents_by_doc.keys())
    doc_chunks = list(documents_by_doc.values())
    
    print(f"\nGenerating V2 contextual embeddings...")
    embeddings = svc.embed_documents_contextualized(doc_chunks)
    
    print(f"\n✅ SUCCESS! Generated embeddings for {len(embeddings)} documents:")
    for i, name in enumerate(doc_names):
        print(f"  {name}: {len(embeddings[i])} embeddings, dim={len(embeddings[i][0])}")
    
    # Test query
    print(f"\nTesting query embedding...")
    query = "What is covered under the warranty?"
    query_emb = svc.embed_query(query)
    print(f"✅ Query embedded: {len(query_emb)} dims")
    
    print(f"\n🎉 V2 Voyage embeddings working!")

if __name__ == "__main__":
    asyncio.run(test_with_simulated_sections())
