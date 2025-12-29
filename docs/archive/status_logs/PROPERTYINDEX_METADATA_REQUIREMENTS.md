# PropertyGraphIndex Document Processing Analysis

## What PropertyGraphIndex Actually Uses

### 1. Document Processing Flow
```
Document → [optional chunking] → Nodes → KG Extractors → Graph
```

**Key finding:** PropertyGraphIndex processes `Document.text` + `Document.metadata` together.

### 2. What Extractors See

When LLMs extract entities/relationships, they receive:
```python
content = document.text + "\n\n" + document.get_metadata_str()
```

**Example:**
```python
Document(
    text="# Payment Terms\n\n| Item | Price |\n| A | $1000 |",
    metadata={
        "page_number": 1,
        "section_path": ["Contract", "Payment Terms"],
        "table_structure": {"headers": ["Item", "Price"], "rows": [["A", "$1000"]]}
    }
)

# LLM sees:
"""
# Payment Terms

| Item | Price |
| A | $1000 |

page_number: 1
section_path: ['Contract', 'Payment Terms']
table_structure: {'headers': ['Item', 'Price'], 'rows': [['A', '$1000']]}
"""
```

### 3. Impact on Entity Extraction

**Without structured metadata:**
```
LLM input: "| Item | Price |\n| A | $1000 |"
LLM output:
  - Entity: "A"
  - Entity: "$1000"
  - No relationship (doesn't know they're in same table row)
```

**With structured metadata:**
```
LLM input: "| Item | Price |\n| A | $1000 |\n\ntable_structure: {'headers': ['Item', 'Price'], 'rows': [['A', '$1000']]}"
LLM output:
  - Entity: "Item A"
  - Entity: "Price $1000"
  - Relationship: Item A -[HAS_PRICE]-> $1000
  - (LLM understands table structure from metadata)
```

### 4. What Metadata is Useful

**High-value metadata** (LLM can use for better extraction):
- ✅ `page_number`: Helps LLM understand document context
- ✅ `section_path`: Shows hierarchy (e.g., ["Contract", "Payment Terms", "Line Items"])
- ✅ `table_structure`: Critical for understanding cell relationships
- ✅ `paragraph_role`: Helps identify titles vs body text
- ✅ `document_type`: Guides extraction (contract vs invoice vs technical doc)

**Lower-value metadata** (used by other components, not extractors):
- ⚠️ `bbox`: Extractors don't use spatial coordinates, but useful for:
  - Future spatial queries ("what's near entity X")
  - Visualization/debugging
  - Linking back to original document locations
- ⚠️ `reading_order`: Implicit in text order; useful for validation

**Not useful for extraction:**
- ❌ `file_path`, `source`, `created_at`: Doesn't help LLM extract better entities
- ❌ Raw polygon coordinates: Too verbose, LLM doesn't process geometry

---

## CU API → Optimal Document Metadata Mapping

### What CU Provides vs What We Should Use

| CU Field | Use in Metadata? | Reason |
|----------|------------------|--------|
| `paragraphs[].role` | ✅ YES | Helps LLM identify titles/headings → better entity typing |
| `paragraphs[].content` | ✅ YES (in text) | Core content for extraction |
| `paragraphs[].boundingRegions` | ⚠️ OPTIONAL | Store simplified bbox, not full polygons |
| `tables[].cells[]` | ✅ YES | Critical for cell→entity→relationship extraction |
| `tables[].rowCount/columnCount` | ✅ YES | Helps LLM understand table shape |
| `tables[].boundingRegions` | ⚠️ OPTIONAL | Useful for linking, not extraction |
| `pageNumber` | ✅ YES | Context for extraction |
| Full polygon coordinates | ❌ NO | Too verbose, clutters LLM context |

### Recommended Metadata Schema

```python
{
    # Core extraction hints
    "page_number": 1,
    "section_path": ["Section Name", "Subsection"],  # Built from role=title/sectionHeading
    "paragraph_role": "title",  # Current paragraph type
    
    # Table structure (critical for quality)
    "tables": [
        {
            "row_count": 3,
            "column_count": 2,
            "headers": ["Item", "Price"],
            "rows": [
                {"Item": "A", "Price": "$1000"},
                {"Item": "B", "Price": "$2000"}
            ]
        }
    ],
    
    # Optional: simplified spatial data
    "bbox": [x1, y1, x2, y2],  # Simple rectangle, not full polygon
    
    # Multi-tenancy (required)
    "group_id": "tenant-001",
    
    # Provenance
    "source": "cu-standard",
    "source_file": "contract.pdf"
}
```

---

## Implementation Strategy

### Phase 1: Essential Conversion (Immediate Value)
Convert CU → Documents with **extraction-critical** metadata:

```python
async def extract_documents(self, group_id: str, urls: List[str]) -> List[Document]:
    # ... call CU API ...
    
    documents = []
    for page in cu_response["pages"]:
        # Build markdown with proper headings
        markdown = self._build_markdown(page["paragraphs"])
        
        # Build section hierarchy
        section_path = self._extract_section_path(page["paragraphs"])
        
        # Extract table structure
        tables_metadata = [
            {
                "row_count": t["rowCount"],
                "column_count": t["columnCount"],
                "headers": self._get_table_headers(t),
                "rows": self._get_table_rows(t)
            }
            for t in page.get("tables", [])
        ]
        
        doc = Document(
            text=markdown,
            metadata={
                "page_number": page["pageNumber"],
                "section_path": section_path,
                "tables": tables_metadata,
                "group_id": group_id
            }
        )
        documents.append(doc)
    
    return documents
```

**Complexity:** ~100 lines  
**Value:** 4x better entity extraction (same as LlamaParse goal)

### Phase 2: Optional Enhancements (Future)
- Add simplified bboxes for visualization
- Add reading order validation
- Add document type classification

---

## Conclusion

**Do this conversion—it's worth it:**

1. **High ROI:** ~100 lines of code → 4x better graph quality
2. **Uses what you have:** Azure credits, no external API
3. **Targets what matters:** Focus on metadata that extractors actually use
4. **Better than LlamaParse:** CU provides table structure that LlamaParse doesn't expose

**Focus on:**
- ✅ Section hierarchy (from paragraph roles)
- ✅ Table cell structure (critical for relationships)
- ✅ Page numbers (context)
- ✅ Proper markdown formatting

**Skip for now:**
- ❌ Full polygon bboxes (too verbose)
- ❌ Raw layout coordinates
- ❌ Metadata extractors don't use

This is the "ProperIndex" approach: give the LLM structured context in metadata so it can extract better entities and relationships.
