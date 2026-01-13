"""
Test script for section-aware chunking module.

Run with:
    cd graphrag-orchestration
    python -m app.hybrid.indexing.section_chunking.test_chunker
"""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# Mock LlamaDocument for testing without full dependencies
@dataclass
class MockLlamaDocument:
    text: str
    metadata: Dict[str, Any]


def create_test_di_units() -> List[MockLlamaDocument]:
    """Create mock DI output simulating a legal contract."""
    return [
        MockLlamaDocument(
            text="This Property Management Agreement is entered into between Owner and Manager.",
            metadata={
                "section_path": ["Introduction"],
                "di_section_path": [0],
                "chunk_type": "section",
                "paragraph_count": 1,
            },
        ),
        MockLlamaDocument(
            text="The purpose of this Agreement is to establish the terms under which Manager "
                 "will manage the Property on behalf of Owner. Manager shall perform all duties "
                 "in a professional manner consistent with industry standards.",
            metadata={
                "section_path": ["Purpose and Scope"],
                "di_section_path": [1],
                "chunk_type": "section",
                "paragraph_count": 2,
            },
        ),
        MockLlamaDocument(
            text="Manager agrees to collect all rents and deposits. Manager shall maintain "
                 "accurate records of all transactions. Manager shall provide monthly statements "
                 "to Owner detailing income and expenses. Manager shall respond to tenant "
                 "maintenance requests within 24 hours. Manager shall conduct regular property "
                 "inspections at least quarterly. Manager shall ensure compliance with all "
                 "applicable local, state, and federal laws. Manager shall maintain appropriate "
                 "insurance coverage as specified in Exhibit A. Manager shall handle all tenant "
                 "screening and background checks. Manager shall coordinate all repairs and "
                 "maintenance with pre-approved vendors. This is a very long section that "
                 "should be split into multiple chunks because it exceeds the maximum token "
                 "threshold. Additional text here to make it longer. More responsibilities "
                 "include lease negotiations, eviction proceedings if necessary, and annual "
                 "budget preparation.",
            metadata={
                "section_path": ["Terms and Conditions", "Manager Duties"],
                "di_section_path": [2, 0],
                "chunk_type": "section",
                "paragraph_count": 15,
            },
        ),
        MockLlamaDocument(
            text="Tiny section.",  # Below min_tokens, should be merged
            metadata={
                "section_path": ["Terms and Conditions", "Minor Clause"],
                "di_section_path": [2, 1],
                "chunk_type": "section",
                "paragraph_count": 1,
            },
        ),
        MockLlamaDocument(
            text="Manager shall receive 10% of gross monthly rents collected as compensation. "
                 "Payment shall be made on the first business day of each month.",
            metadata={
                "section_path": ["Compensation"],
                "di_section_path": [3],
                "chunk_type": "section",
                "paragraph_count": 2,
            },
        ),
    ]


async def test_section_chunking():
    """Test the section-aware chunker."""
    from .chunker import SectionAwareChunker, SectionChunkConfig
    
    print("=" * 60)
    print("Testing Section-Aware Chunker")
    print("=" * 60)
    
    # Configure with lower thresholds for testing
    config = SectionChunkConfig(
        min_tokens=10,     # Lower for testing (normally 100)
        max_tokens=100,    # Lower for testing (normally 1500)
        overlap_tokens=5,
        merge_tiny_sections=True,
        preserve_hierarchy=True,
    )
    
    chunker = SectionAwareChunker(config)
    di_units = create_test_di_units()
    
    chunks = await chunker.chunk_document(
        di_units=di_units,
        doc_id="test_doc_001",
        doc_source="test.pdf",
        doc_title="Property Management Agreement",
    )
    
    print(f"\nInput: {len(di_units)} DI units")
    print(f"Output: {len(chunks)} chunks")
    print()
    
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1}:")
        print(f"  ID: {chunk.id}")
        print(f"  Section: {chunk.section_title} (level {chunk.section_level})")
        print(f"  Path: {' > '.join(chunk.section_path)}")
        print(f"  Tokens: {chunk.tokens}")
        print(f"  Is Summary Section: {chunk.is_summary_section}")
        print(f"  Is Section Start: {chunk.is_section_start}")
        print(f"  Section Position: {chunk.section_chunk_index + 1}/{chunk.section_chunk_total}")
        print(f"  Text Preview: {chunk.text[:80]}...")
        print()
    
    # Verify summary sections detected
    summary_chunks = [c for c in chunks if c.is_summary_section]
    print(f"Summary sections detected: {len(summary_chunks)}")
    for sc in summary_chunks:
        print(f"  - {sc.section_title}")
    
    print("\n" + "=" * 60)
    print("Test Complete")
    print("=" * 60)


async def test_integration():
    """Test integration helpers."""
    from .chunker import SectionAwareChunker, SectionChunkConfig
    from .integration import (
        section_chunks_to_text_chunks,
        get_summary_chunks,
        get_chunks_by_section_title,
    )
    
    print("\n" + "=" * 60)
    print("Testing Integration Helpers")
    print("=" * 60)
    
    config = SectionChunkConfig(min_tokens=10, max_tokens=100)
    chunker = SectionAwareChunker(config)
    di_units = create_test_di_units()
    
    section_chunks = await chunker.chunk_document(
        di_units=di_units,
        doc_id="test_doc_001",
        doc_source="test.pdf",
        doc_title="Test Document",
    )
    
    # Test conversion to TextChunk
    text_chunks = section_chunks_to_text_chunks(section_chunks)
    print(f"\nConverted to {len(text_chunks)} TextChunks")
    
    # Test summary chunk extraction
    summary_chunks = get_summary_chunks(text_chunks)
    print(f"Summary chunks: {len(summary_chunks)}")
    
    # Test section title matching
    payment_chunks = get_chunks_by_section_title(
        text_chunks,
        ["compensation", "payment", "fees"],
    )
    print(f"Payment-related chunks: {len(payment_chunks)}")
    
    print("\n" + "=" * 60)
    print("Integration Test Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_section_chunking())
    asyncio.run(test_integration())
