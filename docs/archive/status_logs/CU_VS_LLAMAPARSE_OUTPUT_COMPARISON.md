# CU vs LlamaParse Output Comparison

## Current CU Standard Output (What We Have)

**Returns:** `List[str]` - Plain text strings

**Example:**
```
--- Page 1 ---
PURCHASE AGREEMENT

This agreement is made between...

| Item | Price | Terms |
|------|-------|-------|
| A    | $1000 | Net 30|

--- Page 2 ---
...
```

**Problems:**
- ❌ No structured metadata (just text with markers)
- ❌ Tables as markdown strings (no cell-level access)
- ❌ No bounding boxes preserved
- ❌ No section hierarchy (just inline text)
- ❌ Returns `List[str]` not `List[Document]`

---

## CU API Actually Provides (What's Available)

**API Response Structure:**
```json
{
  "result": {
    "contents": [
      {
        "pages": [
          {
            "pageNumber": 1,
            "paragraphs": [
              {
                "content": "PURCHASE AGREEMENT",
                "role": "title",
                "boundingRegions": [{"polygon": [...]}]
              },
              {
                "content": "This agreement...",
                "role": "paragraph",
                "boundingRegions": [{"polygon": [...]}]
              }
            ],
            "tables": [
              {
                "rowCount": 2,
                "columnCount": 3,
                "cells": [
                  {
                    "rowIndex": 0,
                    "columnIndex": 0,
                    "content": "Item",
                    "boundingRegions": [{"polygon": [...]}]
                  },
                  {
                    "rowIndex": 1,
                    "columnIndex": 0,
                    "content": "A"
                  },
                  {
                    "rowIndex": 1,
                    "columnIndex": 1,
                    "content": "$1000"
                  }
                ],
                "boundingRegions": [{"polygon": [...]}]
              }
            ]
          }
        ]
      }
    ]
  }
}
```

**What's Available:**
- ✅ Page numbers
- ✅ Paragraph roles (title, sectionHeading, paragraph, pageHeader, etc.)
- ✅ Table structure (rows, columns, cells with positions)
- ✅ Bounding boxes (polygon coordinates)
- ✅ Reading order (implicit in array order)

---

## LlamaParse Output (What We'd Get)

**Returns:** `List[Document]` with markdown text + metadata

**Example:**
```python
Document(
    text="""# PURCHASE AGREEMENT

This agreement is made between...

## Payment Terms

| Item | Price | Terms |
|------|-------|-------|
| A    | $1000 | Net 30|
""",
    metadata={
        "page_number": 1,
        "file_path": "contract.pdf",
        # LlamaParse doesn't expose detailed table structure or bboxes in metadata
        # It focuses on clean markdown conversion
    }
)
```

**What LlamaParse Provides:**
- ✅ Clean markdown with proper heading hierarchy
- ✅ Table formatting (markdown)
- ✅ Page breaks
- ✅ Returns `List[Document]` directly
- ❌ Limited metadata (mostly just page numbers and file info)
- ❌ No bounding boxes in metadata
- ❌ No table cell structure in metadata

---

## The Gap Analysis

### Current CU Implementation
**What we lose by flattening to `List[str]`:**
- Table structure metadata (cells, rows, columns)
- Bounding boxes
- Paragraph roles (which are titles/headings vs body)
- Section hierarchy

### What CU Can Provide (If We Parse Properly)
**More than LlamaParse:**
- ✅ Bounding boxes (LlamaParse doesn't expose these)
- ✅ Table cell-level structure (LlamaParse only gives markdown)
- ✅ Paragraph roles for better heading detection

**Same as LlamaParse:**
- ✅ Page numbers
- ✅ Markdown text
- ✅ Table formatting

### What LlamaParse Gives Us
**Advantages:**
- ✅ Better markdown formatting quality (optimized for readability)
- ✅ Returns `Document` objects directly (no conversion needed)
- ✅ Handles complex layouts well (multi-column, headers/footers)

**Disadvantages:**
- ❌ Cloud API (external dependency, rate limits)
- ❌ Not open source (proprietary service)
- ❌ Less structured metadata than CU provides

---

## Recommendation: Fix CU to Match LlamaParse Output

**Why:** CU already has all the data we need—we're just not using it properly.

**Simple conversion (keeping it practical):**

```python
async def extract_documents(self, group_id: str, urls: List[str]) -> List[Document]:
    """Extract layout-aware Documents from CU API response."""
    documents = []
    
    # ... make CU API call ...
    
    for item in items:
        if "pages" in item:
            for page in item["pages"]:
                page_num = page.get("pageNumber", 1)
                
                # Build markdown
                markdown_lines = []
                section_path = []
                
                for para in page.get("paragraphs", []):
                    role = para.get("role", "")
                    content = para.get("content", "")
                    
                    if role == "title":
                        markdown_lines.append(f"# {content}")
                        section_path = [content]
                    elif role == "sectionHeading":
                        markdown_lines.append(f"## {content}")
                        if section_path:
                            section_path[-1] = content
                        else:
                            section_path.append(content)
                    else:
                        markdown_lines.append(content)
                
                # Add tables
                for table in page.get("tables", []):
                    # Convert to markdown (CU might already provide this)
                    table_md = self._table_to_markdown(table)
                    markdown_lines.append(table_md)
                
                # Create Document with metadata
                doc = Document(
                    text="\n\n".join(markdown_lines),
                    metadata={
                        "page_number": page_num,
                        "section_path": section_path,
                        "group_id": group_id,
                        "source": "cu-standard"
                    }
                )
                documents.append(doc)
    
    return documents
```

**Complexity:** Low
- ~50 lines of conversion logic
- No external dependencies
- Uses Azure credits we already have
- Provides same or better structure than LlamaParse

**Benefits:**
- ✅ Same `List[Document]` output as LlamaParse
- ✅ Works with PropertyGraphIndex directly
- ✅ No external API/rate limits
- ✅ Uses free Azure credits
- ✅ Can preserve more metadata (bboxes) if needed later

---

## Decision

**Convert CU to return `List[Document]` instead of `List[str]`**

This gives us:
1. Layout-aware parsing (same as LlamaParse goal)
2. No external dependencies
3. Uses Azure credits
4. Actually more metadata available than LlamaParse
5. Simple conversion (~50 lines)

We can keep LlamaParse as an optional alternative for users who prefer it, but CU becomes our primary, properly-implemented solution.
