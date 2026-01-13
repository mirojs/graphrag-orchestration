"""
Test Section-Aware Chunking with Real Azure DI Output

This script tests the section-aware chunker against actual Azure DI extraction
to validate it works with real document structure.

Usage:
    # Set Azure DI credentials
    export AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<resource>.cognitiveservices.azure.com/
    
    # Run test
    cd graphrag-orchestration
    python scripts/test_section_chunking_real.py --url <blob-url-to-pdf>
    
    # Or with local file (will use mock DI)
    python scripts/test_section_chunking_real.py --mock
"""
import asyncio
import argparse
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_with_azure_di(url: str, group_id: str = "test-section-chunking"):
    """Test section chunking with real Azure DI extraction."""
    from app.services.document_intelligence_service import DocumentIntelligenceService
    from app.hybrid.indexing.section_chunking import SectionAwareChunker, SectionChunkConfig
    from app.hybrid.indexing.section_chunking.integration import section_chunks_to_text_chunks
    
    print("=" * 70)
    print("Testing Section-Aware Chunking with Azure Document Intelligence")
    print("=" * 70)
    
    # Step 1: Extract with Azure DI
    print(f"\n[Step 1] Extracting document with Azure DI...")
    print(f"  URL: {url[:80]}...")
    
    di_service = DocumentIntelligenceService()
    extracted_docs = await di_service.extract_documents(
        group_id=group_id,
        input_items=[url],
        fail_fast=True,
        model_strategy="auto",
    )
    
    print(f"  Extracted {len(extracted_docs)} DI units")
    
    if not extracted_docs:
        print("  ERROR: No documents extracted!")
        return
    
    # Show DI metadata
    print(f"\n[Step 2] DI Unit Metadata:")
    for i, doc in enumerate(extracted_docs[:5]):  # First 5 units
        meta = getattr(doc, "metadata", {}) or {}
        text = (getattr(doc, "text", "") or "")[:100]
        print(f"  Unit {i}:")
        print(f"    section_path: {meta.get('section_path', 'N/A')}")
        print(f"    chunk_type: {meta.get('chunk_type', 'N/A')}")
        print(f"    paragraphs: {meta.get('paragraph_count', 'N/A')}")
        print(f"    text preview: {text}...")
    
    if len(extracted_docs) > 5:
        print(f"  ... and {len(extracted_docs) - 5} more units")
    
    # Step 3: Apply section-aware chunking
    print(f"\n[Step 3] Applying Section-Aware Chunking...")
    
    config = SectionChunkConfig(
        min_tokens=100,
        max_tokens=1500,
        overlap_tokens=50,
    )
    chunker = SectionAwareChunker(config)
    
    section_chunks = await chunker.chunk_document(
        di_units=extracted_docs,
        doc_id="test_doc_001",
        doc_source=url,
        doc_title=url.split("/")[-1].replace(".pdf", ""),
    )
    
    print(f"  Created {len(section_chunks)} section chunks")
    
    # Step 4: Analyze results
    print(f"\n[Step 4] Section Chunk Analysis:")
    
    summary_count = sum(1 for c in section_chunks if c.is_summary_section)
    section_titles = set(c.section_title for c in section_chunks)
    
    print(f"  Summary sections: {summary_count}")
    print(f"  Unique sections: {len(section_titles)}")
    print(f"  Section titles: {list(section_titles)[:10]}")
    
    # Step 5: Show sample chunks
    print(f"\n[Step 5] Sample Chunks:")
    for i, chunk in enumerate(section_chunks[:5]):
        print(f"\n  Chunk {i + 1}:")
        print(f"    ID: {chunk.id}")
        print(f"    Section: {chunk.section_title} (level {chunk.section_level})")
        print(f"    Path: {' > '.join(chunk.section_path)}")
        print(f"    Tokens: {chunk.tokens}")
        print(f"    Is Summary: {chunk.is_summary_section}")
        print(f"    Position: {chunk.section_chunk_index + 1}/{chunk.section_chunk_total}")
        print(f"    Text: {chunk.text[:150]}...")
    
    # Step 6: Convert to TextChunk for pipeline compatibility
    print(f"\n[Step 6] TextChunk Conversion:")
    text_chunks = section_chunks_to_text_chunks(section_chunks)
    print(f"  Converted to {len(text_chunks)} TextChunks")
    
    # Show metadata structure
    if text_chunks:
        sample_meta = text_chunks[0].metadata
        print(f"  Sample metadata keys: {list(sample_meta.keys())}")
    
    print("\n" + "=" * 70)
    print("Test Complete!")
    print("=" * 70)
    
    return section_chunks


async def test_with_mock_data():
    """Test section chunking with mock DI data."""
    from dataclasses import dataclass
    from typing import Any, Dict
    from app.hybrid.indexing.section_chunking import SectionAwareChunker, SectionChunkConfig
    
    @dataclass
    class MockLlamaDocument:
        text: str
        metadata: Dict[str, Any]
    
    print("=" * 70)
    print("Testing Section-Aware Chunking with Mock Data")
    print("=" * 70)
    
    # Create realistic mock DI output
    mock_units = [
        MockLlamaDocument(
            text="PROPERTY MANAGEMENT AGREEMENT\n\nThis Agreement is made between Owner and Manager.",
            metadata={
                "section_path": [],
                "chunk_type": "title",
                "paragraph_count": 2,
            },
        ),
        MockLlamaDocument(
            text="The purpose of this Agreement is to establish the terms and conditions under "
                 "which the Manager will manage the Property on behalf of the Owner. The Manager "
                 "shall perform all services in a professional manner consistent with industry "
                 "standards and applicable laws.",
            metadata={
                "section_path": ["Purpose and Scope"],
                "di_section_path": [0],
                "chunk_type": "section",
                "paragraph_count": 2,
            },
        ),
        MockLlamaDocument(
            text="The Manager agrees to perform the following duties:\n\n"
                 "1. Collect all rents and security deposits from tenants\n"
                 "2. Maintain accurate financial records of all transactions\n"
                 "3. Provide monthly statements to Owner detailing income and expenses\n"
                 "4. Respond to tenant maintenance requests within 24 business hours\n"
                 "5. Conduct quarterly property inspections\n"
                 "6. Ensure compliance with all applicable local, state, and federal laws\n"
                 "7. Handle tenant screening and background verification\n"
                 "8. Coordinate repairs with pre-approved vendors\n"
                 "9. Manage lease renewals and terminations\n"
                 "10. Represent Owner in legal proceedings if necessary",
            metadata={
                "section_path": ["Terms and Conditions", "Manager Duties"],
                "di_section_path": [1, 0],
                "chunk_type": "section",
                "paragraph_count": 11,
            },
        ),
        MockLlamaDocument(
            text="The Manager shall receive compensation equal to 10% of gross monthly rents "
                 "collected. Payment shall be made on the first business day of each month. "
                 "Additional fees may apply for services outside the scope of this Agreement.",
            metadata={
                "section_path": ["Compensation"],
                "di_section_path": [2],
                "chunk_type": "section",
                "paragraph_count": 3,
            },
        ),
        MockLlamaDocument(
            text="Term.",  # Tiny section - should be merged
            metadata={
                "section_path": ["Term"],
                "di_section_path": [3],
                "chunk_type": "section",
                "paragraph_count": 1,
            },
        ),
        MockLlamaDocument(
            text="This Agreement shall commence on the Effective Date and continue for a period "
                 "of one (1) year. Either party may terminate this Agreement with 30 days written "
                 "notice. Upon termination, Manager shall provide all records to Owner within 15 days.",
            metadata={
                "section_path": ["Term and Termination"],
                "di_section_path": [4],
                "chunk_type": "section",
                "paragraph_count": 3,
            },
        ),
    ]
    
    print(f"\nMock DI units created: {len(mock_units)}")
    
    # Apply chunker
    config = SectionChunkConfig(
        min_tokens=20,   # Lower for mock data
        max_tokens=200,  # Lower for mock data
        overlap_tokens=10,
    )
    chunker = SectionAwareChunker(config)
    
    chunks = await chunker.chunk_document(
        di_units=mock_units,
        doc_id="mock_doc_001",
        doc_source="mock://property_management.pdf",
        doc_title="Property Management Agreement",
    )
    
    print(f"Section chunks created: {len(chunks)}")
    
    print("\nChunk Details:")
    for i, chunk in enumerate(chunks):
        print(f"\n  [{i + 1}] {chunk.section_title}")
        print(f"      Tokens: {chunk.tokens}, Summary: {chunk.is_summary_section}")
        print(f"      Path: {' > '.join(chunk.section_path) if chunk.section_path else '(root)'}")
        print(f"      Text: {chunk.text[:100]}...")
    
    # Verify summary detection
    summary_chunks = [c for c in chunks if c.is_summary_section]
    print(f"\n✓ Summary sections detected: {len(summary_chunks)}")
    for sc in summary_chunks:
        print(f"    - {sc.section_title}")
    
    print("\n" + "=" * 70)
    print("Mock Test Complete!")
    print("=" * 70)


async def main():
    parser = argparse.ArgumentParser(description="Test section-aware chunking")
    parser.add_argument("--url", help="Azure Blob URL to PDF document")
    parser.add_argument("--mock", action="store_true", help="Use mock data instead of real DI")
    parser.add_argument("--group-id", default="test-section-chunking", help="Group ID for testing")
    
    args = parser.parse_args()
    
    if args.mock:
        await test_with_mock_data()
    elif args.url:
        await test_with_azure_di(args.url, args.group_id)
    else:
        print("Usage:")
        print("  --mock         Test with mock data")
        print("  --url <url>    Test with real Azure DI extraction")
        print()
        print("Running mock test by default...")
        await test_with_mock_data()


if __name__ == "__main__":
    asyncio.run(main())
