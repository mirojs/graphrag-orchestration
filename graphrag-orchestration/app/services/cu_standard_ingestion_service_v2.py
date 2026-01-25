"""
CU Standard Ingestion Service V2 - Section-Aware Chunking

V2 Changes from V1:
1. Buffer text by Azure DI sections (not pages)
2. Apply min/max token rules for chunking
3. Store parent_doc_title separately from section_title
4. Detect summary sections for coverage retrieval
5. Support Voyage embeddings (2048 dim) via hybrid_v2

Ref: VOYAGE_V2_IMPLEMENTATION_PLAN_2026-01-25.md Phase 2
"""

import os
import re
from typing import Any, Dict, List, Optional, Union
import logging

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from llama_index.core import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


# ============================================================================
# Section-Aware Chunking Constants
# ============================================================================
MIN_SECTION_TOKENS = 100    # Merge sections below this threshold
MAX_SECTION_TOKENS = 1500   # Split sections above this threshold  
OVERLAP_TOKENS = 50         # Overlap between split chunks

# Summary section detection patterns
SUMMARY_PATTERNS = [
    "purpose", "summary", "executive summary",
    "introduction", "overview", "scope",
    "background", "abstract", "objectives",
    "recitals", "whereas",
]


class CUStandardIngestionServiceV2:
    """
    V2 Ingestion Service with section-aware chunking.
    
    Key differences from V1:
    - Returns Documents chunked by semantic sections (not pages)
    - Each Document has parent_doc_title and section_title metadata
    - Supports min/max token rules for optimal chunk sizes
    - Detects summary sections for coverage retrieval
    """
    
    API_SCOPE = "https://cognitiveservices.azure.com/.default"

    def __init__(self) -> None:
        self.endpoint = settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT or os.environ.get("AZURE_CONTENT_UNDERSTANDING_ENDPOINT")
        self.api_key = settings.AZURE_CONTENT_UNDERSTANDING_API_KEY or os.environ.get("AZURE_CONTENT_UNDERSTANDING_API_KEY")
        self.api_version = getattr(settings, "AZURE_CU_API_VERSION", "2025-05-01-preview")
        
        logger.info(f"CU Service Init - Endpoint: {self.endpoint}")
        logger.info(f"CU Service Init - API Key set: {bool(self.api_key)}, length: {len(self.api_key) if self.api_key else 0}")
        logger.info(f"CU Service Init - settings.API_KEY: {bool(settings.AZURE_CONTENT_UNDERSTANDING_API_KEY)}")
        logger.info(f"CU Service Init - os.environ API_KEY: {bool(os.environ.get('AZURE_CONTENT_UNDERSTANDING_API_KEY'))}")
        
        if not self.endpoint:
            raise RuntimeError("AZURE_CONTENT_UNDERSTANDING_ENDPOINT not configured")
        
        # Use API key if available, otherwise managed identity
        if self.api_key:
            logger.info("CU Service: Using API key authentication")
            self.credential = None
            self.token_provider = None
        else:
            logger.info("CU Service: Using managed identity authentication")
            self.credential = DefaultAzureCredential()
            self.token_provider = get_bearer_token_provider(self.credential, self.API_SCOPE)

    def _build_section_path(self, paragraphs: List[Dict]) -> List[str]:
        """Extract section hierarchy from paragraph roles."""
        path = []
        for para in paragraphs:
            role = para.get("role", "")
            content = para.get("content", "").strip()
            if role == "title":
                path = [content]  # Reset to top level
            elif role == "sectionHeading":
                if len(path) > 1:
                    path[-1] = content  # Replace last subsection
                else:
                    path.append(content)
        return path

    def _extract_table_metadata(self, table: Dict) -> Dict[str, Any]:
        """Extract structured table metadata for PropertyGraphIndex."""
        cells = table.get("cells", [])
        row_count = table.get("rowCount", 0)
        col_count = table.get("columnCount", 0)
        
        # Build header row (row 0)
        headers = []
        for cell in cells:
            if cell.get("rowIndex") == 0:
                headers.append(cell.get("content", ""))
        
        # Build data rows
        rows = []
        for row_idx in range(1, row_count):
            row_data = {}
            for cell in cells:
                if cell.get("rowIndex") == row_idx:
                    col_idx = cell.get("columnIndex", 0)
                    if col_idx < len(headers):
                        row_data[headers[col_idx]] = cell.get("content", "")
            if row_data:
                rows.append(row_data)
        
        return {
            "row_count": row_count,
            "column_count": col_count,
            "headers": headers,
            "rows": rows
        }

    def _build_markdown_from_page(self, page: Dict) -> str:
        """Convert CU page structure to clean markdown."""
        lines = []
        
        # Check if we have paragraphs (newer API) or lines (prebuilt-layout)
        paragraphs = page.get("paragraphs", [])
        if paragraphs:
            for para in paragraphs:
                role = para.get("role", "")
                content = para.get("content", "").strip()
                
                if role == "title":
                    lines.append(f"# {content}")
                elif role == "sectionHeading":
                    lines.append(f"## {content}")
                elif role == "pageHeader" or role == "pageFooter":
                    # Skip headers/footers (noise for extraction)
                    continue
                else:
                    lines.append(content)
        else:
            # Use lines field for prebuilt-layout
            page_lines = page.get("lines", [])
            for line in page_lines:
                content = line.get("content", "").strip()
                if content:
                    lines.append(content)
        
        # Add tables (CU already provides markdown)
        for table in page.get("tables", []):
            table_md = table.get("content", "")
            if table_md:
                lines.append(table_md)
        
        return "\n\n".join(lines)

    # ========================================================================
    # V2 Section-Aware Chunking Methods
    # ========================================================================
    
    def _count_tokens(self, text: str) -> int:
        """Simple whitespace tokenization for token counting."""
        return len(text.split())
    
    def _is_summary_section(self, title: str) -> bool:
        """Detect summary sections by title pattern."""
        if not title:
            return False
        title_lower = title.lower()
        return any(p in title_lower for p in SUMMARY_PATTERNS)
    
    def _extract_doc_title(self, pages: List[Dict]) -> str:
        """Extract document title from first page."""
        if not pages:
            return "Untitled Document"
        
        first_page = pages[0]
        for para in first_page.get("paragraphs", []):
            if para.get("role") == "title":
                return para.get("content", "").strip()
        
        return "Untitled Document"
    
    def _buffer_by_sections(self, pages: List[Dict]) -> List[Dict]:
        """
        Buffer text by Azure DI section boundaries.
        
        Returns list of section dicts with:
        - text: Complete section text
        - section_title: Section heading
        - section_level: Heading level (1, 2, 3)
        - section_path: Full path ["Doc", "Section", "Subsection"]
        - is_summary_section: True if title matches summary patterns
        - tables: List of tables in this section
        """
        sections: List[Dict] = []
        current_section: Optional[Dict] = None
        section_path: List[str] = []
        
        for page in pages:
            paragraphs = page.get("paragraphs", [])
            tables = page.get("tables", [])
            table_idx = 0
            
            for para in paragraphs:
                role = para.get("role", "")
                content = para.get("content", "").strip()
                
                if not content:
                    continue
                
                if role == "title":
                    # Save previous section
                    if current_section and current_section["text"].strip():
                        sections.append(current_section)
                    
                    # Reset to document title (level 1)
                    section_path = [content]
                    current_section = {
                        "text": f"# {content}\n\n",
                        "section_title": content,
                        "section_level": 1,
                        "section_path": section_path.copy(),
                        "is_summary_section": self._is_summary_section(content),
                        "tables": [],
                    }
                    
                elif role == "sectionHeading":
                    # Save previous section
                    if current_section and current_section["text"].strip():
                        sections.append(current_section)
                    
                    # Determine level based on heading style (heuristic)
                    # DI doesn't always give us explicit levels, so we track path
                    if len(section_path) == 0:
                        section_path = [content]
                        level = 1
                    elif len(section_path) == 1:
                        section_path.append(content)
                        level = 2
                    else:
                        # Replace last item (same level) or add (deeper level)
                        # Heuristic: treat all sectionHeadings as level 2+
                        section_path = [section_path[0], content]
                        level = 2
                    
                    current_section = {
                        "text": f"## {content}\n\n",
                        "section_title": content,
                        "section_level": level,
                        "section_path": section_path.copy(),
                        "is_summary_section": self._is_summary_section(content),
                        "tables": [],
                    }
                    
                elif role in ("pageHeader", "pageFooter"):
                    # Skip headers/footers (noise for extraction)
                    continue
                    
                else:
                    # Regular paragraph - add to current section
                    if current_section is None:
                        # No section yet, create implicit one
                        current_section = {
                            "text": "",
                            "section_title": "Introduction",
                            "section_level": 1,
                            "section_path": ["Introduction"],
                            "is_summary_section": True,  # Treat intro as summary
                            "tables": [],
                        }
                    current_section["text"] += content + "\n\n"
            
            # Add tables from this page to current section
            for table in tables:
                table_md = table.get("content", "")
                if table_md and current_section:
                    current_section["text"] += table_md + "\n\n"
                    current_section["tables"].append(self._extract_table_metadata(table))
        
        # Don't forget last section
        if current_section and current_section["text"].strip():
            sections.append(current_section)
        
        return sections
    
    def _apply_chunking_rules(
        self,
        sections: List[Dict],
        min_tokens: int = MIN_SECTION_TOKENS,
        max_tokens: int = MAX_SECTION_TOKENS,
        overlap_tokens: int = OVERLAP_TOKENS,
    ) -> List[Dict]:
        """
        Apply split/merge rules to sections.
        
        - Merge sections < min_tokens with previous sibling
        - Split sections > max_tokens at paragraph boundaries
        """
        if not sections:
            return []
        
        processed: List[Dict] = []
        
        for section in sections:
            token_count = self._count_tokens(section["text"])
            
            if token_count < min_tokens and processed:
                # Merge with previous section
                prev = processed[-1]
                prev["text"] += "\n\n" + section["text"]
                # Keep the more specific section path
                if len(section["section_path"]) > len(prev["section_path"]):
                    prev["section_path"] = section["section_path"]
                # Preserve summary flag if either is summary
                prev["is_summary_section"] = prev["is_summary_section"] or section["is_summary_section"]
                prev["tables"].extend(section["tables"])
                
            elif token_count > max_tokens:
                # Split at paragraph boundaries
                chunks = self._split_section(section, max_tokens, overlap_tokens)
                processed.extend(chunks)
                
            else:
                # Section is within bounds
                processed.append(section)
        
        return processed
    
    def _split_section(
        self,
        section: Dict,
        max_tokens: int,
        overlap_tokens: int,
    ) -> List[Dict]:
        """Split a large section at paragraph boundaries."""
        text = section["text"]
        paragraphs = text.split("\n\n")
        
        chunks: List[Dict] = []
        current_chunk = ""
        chunk_idx = 0
        
        for para in paragraphs:
            para_tokens = self._count_tokens(para)
            current_tokens = self._count_tokens(current_chunk)
            
            if current_tokens + para_tokens <= max_tokens:
                current_chunk += para + "\n\n"
            else:
                # Save current chunk
                if current_chunk.strip():
                    chunks.append({
                        "text": current_chunk.strip(),
                        "section_title": f"{section['section_title']} (part {chunk_idx + 1})",
                        "section_level": section["section_level"],
                        "section_path": section["section_path"],
                        "is_summary_section": section["is_summary_section"],
                        "tables": section["tables"] if chunk_idx == 0 else [],
                        "chunk_part": chunk_idx + 1,
                    })
                    chunk_idx += 1
                
                # Start new chunk with overlap
                if overlap_tokens > 0 and current_chunk:
                    # Get last N tokens for overlap
                    words = current_chunk.split()
                    overlap_text = " ".join(words[-overlap_tokens:]) if len(words) > overlap_tokens else ""
                    current_chunk = overlap_text + "\n\n" + para + "\n\n"
                else:
                    current_chunk = para + "\n\n"
        
        # Don't forget last chunk
        if current_chunk.strip():
            chunks.append({
                "text": current_chunk.strip(),
                "section_title": f"{section['section_title']} (part {chunk_idx + 1})" if chunk_idx > 0 else section["section_title"],
                "section_level": section["section_level"],
                "section_path": section["section_path"],
                "is_summary_section": section["is_summary_section"],
                "tables": [],
                "chunk_part": chunk_idx + 1 if chunk_idx > 0 else None,
            })
        
        return chunks if chunks else [section]

    async def extract_documents(self, group_id: str, input_items: List[Union[str, Dict[str, Any]]]) -> List[Document]:
        """
        Extract structured Documents from files using Azure Content Understanding.
        
        Args:
            group_id: Tenant ID for multi-tenancy
            input_items: List of URLs, dicts with {url}, or raw text strings
            
        Returns:
            List of LlamaIndex Documents with layout-aware metadata:
            - text: Markdown with proper headings
            - metadata: {page_number, section_path, tables, group_id}
        """
        # Separate URLs from raw text
        urls: List[str] = []
        passthrough_texts: List[str] = []
        
        for item in input_items:
            if isinstance(item, dict):
                if "text" in item:
                    passthrough_texts.append(item["text"])
                elif "url" in item:
                    urls.append(item["url"])
                else:
                    raise ValueError("Dict must have 'text' or 'url'")
            elif isinstance(item, str):
                if item.startswith(("http://", "https://")):
                    urls.append(item)
                else:
                    passthrough_texts.append(item)
            else:
                raise ValueError("Unsupported item type")
        
        documents: List[Document] = []
        
        # Add passthrough texts as simple Documents
        for text in passthrough_texts:
            documents.append(Document(
                text=text,
                metadata={"group_id": group_id, "source": "passthrough"}
            ))
        
        # Process URLs via CU API
        if urls:
            # Azure Content Understanding: /contentunderstanding/analyzers/prebuilt-layout:analyze
            analyze_url = f"{self.endpoint.rstrip('/')}/contentunderstanding/analyzers/prebuilt-layout:analyze?api-version=2025-05-01-preview"
            
            # For prebuilt analyzers, process each URL separately (no batch support in API)
            for url in urls:
                payload = {"url": url}
                headers = {
                    "Content-Type": "application/json",
                }
                if self.api_key:
                    headers["Ocp-Apim-Subscription-Key"] = self.api_key
                else:
                    # Token provider returns a callable; invoke to get token string
                    headers["Authorization"] = f"Bearer {self.token_provider()}"

                logger.info(f"CU Standard analyzing: {url[:80]}...")
                logger.debug(f"Request URL: {analyze_url}")
                logger.debug(f"Payload: {payload}")
                logger.debug(f"Headers: {dict((k, v[:20] + '...' if k in ('Authorization', 'Ocp-Apim-Subscription-Key') and len(v) > 20 else v) for k, v in headers.items())}")
                
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(analyze_url, json=payload, headers=headers)
                    if resp.status_code >= 400:
                        logger.error(f"CU API Error - Status: {resp.status_code}, Response: {resp.text}, Request payload: {payload}")
                        raise RuntimeError(f"CU analyze failed: {resp.status_code} {resp.text}")
                    
                    data = resp.json()
                    operation_id = data.get("id")
                    status = data.get("status", "unknown")
                    
                    # Poll for completion if async
                    if status.lower() in ("running", "notstarted"):
                        # Azure Content Understanding poll path
                        poll_url = f"{self.endpoint.rstrip('/')}/contentunderstanding/analyzerResults/{operation_id}?api-version=2025-05-01-preview"
                        max_attempts = 60
                        for attempt in range(max_attempts):
                            await __import__("asyncio").sleep(2)
                            poll_resp = await client.get(poll_url, headers=headers)
                            if poll_resp.status_code >= 400:
                                raise RuntimeError(f"Poll failed: {poll_resp.status_code} {poll_resp.text}")
                            
                            poll_data = poll_resp.json()
                            poll_status = poll_data.get("status", "unknown")
                            
                            if poll_status.lower() == "succeeded":
                                data = poll_data
                                break
                            elif poll_status.lower() in ("failed", "cancelled"):
                                raise RuntimeError(f"Analysis failed: {poll_status}")
                        else:
                            raise RuntimeError(f"Analysis timed out after {max_attempts * 2}s")
                    
                    result = data.get("result", {})
                    contents = result.get("contents", [])
                    
                    if not contents:
                        logger.warning(f"No contents in response for {url}")
                        continue
                    
                    # Process the first content item (single URL = single content)
                    content_item = contents[0]
                    pages = content_item.get("pages", [])
                    
                    if not pages:
                        # Fallback: no page structure, use raw content
                        raw_text = content_item.get("content") or content_item.get("text") or ""
                        documents.append(Document(
                            text=raw_text,
                            metadata={"group_id": group_id, "source": "cu-standard-v2", "url": url}
                        ))
                        continue
                    
                    # ================================================================
                    # V2: Section-aware chunking (instead of page-based)
                    # ================================================================
                    
                    # Extract document title from first page
                    parent_doc_title = self._extract_doc_title(pages)
                    
                    # Step 1: Buffer text by section boundaries
                    sections = self._buffer_by_sections(pages)
                    
                    if not sections:
                        # Fallback: No sections found, create single document
                        all_text = "\n\n".join(
                            self._build_markdown_from_page(p) for p in pages
                        )
                        documents.append(Document(
                            text=all_text,
                            metadata={
                                "group_id": group_id,
                                "source": "cu-standard-v2",
                                "url": url,
                                "parent_doc_title": parent_doc_title,
                                "section_title": parent_doc_title,
                                "is_summary_section": True,
                            }
                        ))
                        continue
                    
                    # Step 2: Apply chunking rules (merge small, split large)
                    chunks = self._apply_chunking_rules(sections)
                    
                    logger.info(
                        f"V2 Section chunking: {url[:50]}... -> "
                        f"{len(sections)} sections -> {len(chunks)} chunks"
                    )
                    
                    # Step 3: Create Documents from chunks
                    for chunk_idx, chunk in enumerate(chunks):
                        doc = Document(
                            text=chunk["text"],
                            metadata={
                                "group_id": group_id,
                                "source": "cu-standard-v2",
                                "url": url,
                                # V2 metadata: separate parent/section titles
                                "parent_doc_title": parent_doc_title,
                                "section_title": chunk["section_title"],
                                "section_level": chunk["section_level"],
                                "section_path": chunk["section_path"],
                                "is_summary_section": chunk["is_summary_section"],
                                "tables": chunk.get("tables", []),
                                "chunk_index": chunk_idx,
                                "chunk_part": chunk.get("chunk_part"),
                            }
                        )
                        documents.append(doc)
        
        logger.info(f"V2 Extracted {len(documents)} section-aware chunks for group {group_id}")
        return documents
