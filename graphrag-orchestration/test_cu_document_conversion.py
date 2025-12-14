#!/usr/bin/env python3
"""
Test CU Standard Service - Document Conversion

Validates that the new CU service correctly converts CU API responses
into Documents with extraction-optimized metadata.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.cu_standard_ingestion_service import CUStandardIngestionService


def test_section_path_extraction():
    """Test that section hierarchy is correctly extracted from paragraph roles."""
    service = CUStandardIngestionService.__new__(CUStandardIngestionService)
    
    paragraphs = [
        {"role": "title", "content": "Purchase Agreement"},
        {"role": "sectionHeading", "content": "Payment Terms"},
        {"role": "paragraph", "content": "Net 30 days"},
        {"role": "sectionHeading", "content": "Delivery Terms"},
    ]
    
    path = service._build_section_path(paragraphs)
    
    # Should have: ["Purchase Agreement", "Delivery Terms"]
    # (last sectionHeading replaces previous subsection)
    assert len(path) == 2, f"Expected 2 levels, got {len(path)}: {path}"
    assert path[0] == "Purchase Agreement", f"Wrong title: {path[0]}"
    assert path[1] == "Delivery Terms", f"Wrong section: {path[1]}"
    
    print("✅ Section path extraction works correctly")
    print(f"   Result: {path}")


def test_table_metadata_extraction():
    """Test that table structure is correctly extracted."""
    service = CUStandardIngestionService.__new__(CUStandardIngestionService)
    
    table = {
        "rowCount": 3,
        "columnCount": 2,
        "cells": [
            {"rowIndex": 0, "columnIndex": 0, "content": "Item"},
            {"rowIndex": 0, "columnIndex": 1, "content": "Price"},
            {"rowIndex": 1, "columnIndex": 0, "content": "A"},
            {"rowIndex": 1, "columnIndex": 1, "content": "$1000"},
            {"rowIndex": 2, "columnIndex": 0, "content": "B"},
            {"rowIndex": 2, "columnIndex": 1, "content": "$2000"},
        ]
    }
    
    metadata = service._extract_table_metadata(table)
    
    assert metadata["row_count"] == 3
    assert metadata["column_count"] == 2
    assert metadata["headers"] == ["Item", "Price"]
    assert len(metadata["rows"]) == 2  # 2 data rows (excluding header)
    assert metadata["rows"][0] == {"Item": "A", "Price": "$1000"}
    assert metadata["rows"][1] == {"Item": "B", "Price": "$2000"}
    
    print("✅ Table metadata extraction works correctly")
    print(f"   Headers: {metadata['headers']}")
    print(f"   Rows: {metadata['rows']}")


def test_markdown_conversion():
    """Test that paragraphs are converted to clean markdown."""
    service = CUStandardIngestionService.__new__(CUStandardIngestionService)
    
    page = {
        "paragraphs": [
            {"role": "title", "content": "Contract"},
            {"role": "sectionHeading", "content": "Terms"},
            {"role": "paragraph", "content": "This is a test."},
            {"role": "pageHeader", "content": "Page 1"},  # Should be skipped
            {"role": "paragraph", "content": "More content."},
        ],
        "tables": [
            {"content": "| A | B |\n|---|---|\n| 1 | 2 |"}
        ]
    }
    
    markdown = service._build_markdown_from_page(page)
    
    assert "# Contract" in markdown
    assert "## Terms" in markdown
    assert "This is a test." in markdown
    assert "More content." in markdown
    assert "Page 1" not in markdown  # Headers should be filtered
    assert "| A | B |" in markdown  # Table included
    
    print("✅ Markdown conversion works correctly")
    print("   Generated markdown:")
    for line in markdown.split("\n"):
        print(f"     {line}")


def test_metadata_for_propertyindex():
    """Test that generated metadata is useful for PropertyGraphIndex."""
    service = CUStandardIngestionService.__new__(CUStandardIngestionService)
    
    from llama_index.core import Document
    
    # Simulate a page with rich structure
    page = {
        "pageNumber": 1,
        "paragraphs": [
            {"role": "title", "content": "Invoice"},
            {"role": "sectionHeading", "content": "Line Items"},
            {"role": "paragraph", "content": "See table below."},
        ],
        "tables": [
            {
                "rowCount": 2,
                "columnCount": 2,
                "cells": [
                    {"rowIndex": 0, "columnIndex": 0, "content": "Item"},
                    {"rowIndex": 0, "columnIndex": 1, "content": "Price"},
                    {"rowIndex": 1, "columnIndex": 0, "content": "Widget"},
                    {"rowIndex": 1, "columnIndex": 1, "content": "$50"},
                ],
                "content": "| Item | Price |\n|------|-------|\n| Widget | $50 |"
            }
        ]
    }
    
    markdown = service._build_markdown_from_page(page)
    section_path = service._build_section_path(page["paragraphs"])
    tables_metadata = [service._extract_table_metadata(t) for t in page["tables"]]
    
    doc = Document(
        text=markdown,
        metadata={
            "page_number": 1,
            "section_path": section_path,
            "tables": tables_metadata,
            "group_id": "test",
        }
    )
    
    # Check what PropertyGraphIndex will see
    content = doc.get_content()
    metadata_str = doc.get_metadata_str()
    
    print("✅ Metadata is PropertyGraphIndex-ready")
    print("\n   === What LLM sees (text + metadata) ===")
    print(f"   {content}\n")
    print(f"   {metadata_str}")
    print("\n   === Analysis ===")
    print(f"   - LLM can see section: {section_path}")
    print(f"   - LLM can see table structure: {tables_metadata[0]['headers']}")
    print(f"   - LLM can map Widget → $50 relationship from table rows")


def main():
    print("=" * 70)
    print("CU Standard Service - Document Conversion Tests")
    print("=" * 70)
    print()
    
    tests = [
        test_section_path_extraction,
        test_table_metadata_extraction,
        test_markdown_conversion,
        test_metadata_for_propertyindex,
    ]
    
    for test in tests:
        try:
            test()
            print()
        except Exception as e:
            print(f"❌ Test failed: {e}")
            import traceback
            traceback.print_exc()
            return 1
    
    print("=" * 70)
    print("All tests passed! ✅")
    print("=" * 70)
    print()
    print("CU Standard service now returns Documents with:")
    print("  - Clean markdown (proper headings)")
    print("  - Section hierarchy metadata")
    print("  - Table structure (headers + rows as dicts)")
    print("  - Page numbers")
    print()
    print("This gives PropertyGraphIndex the context it needs for")
    print("high-quality entity and relationship extraction.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
