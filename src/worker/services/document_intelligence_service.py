"""
Azure Document Intelligence Ingestion Service

Uses Azure Document Intelligence (formerly Form Recognizer) SDK to extract 
structured layout from documents for GraphRAG PropertyGraphIndex.

Advantages over Azure Content Understanding:
- More mature and stable API
- Better table structure extraction
- Rich bounding box information
- Native SDK support (no manual REST polling)
- Managed identity support out-of-the-box

Features:
- **Batch Processing**: Analyze multiple documents in parallel
- **Concurrent Uploads**: Configurable concurrency limit (default: 5)
- **Error Resilience**: Individual failures don't stop the batch

Returns LlamaIndex Documents with:
- Clean markdown text with proper section hierarchy
- Table structure metadata (headers, rows, cells)
- Bounding box coordinates for spatial context
- Page numbers and reading order

API: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/
Model: prebuilt-layout (2024-11-30 API version)
"""

import asyncio
import logging
import base64
import io
import re
from bisect import bisect_left, bisect_right
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentAnalysisFeature,
    DocumentContentFormat,
    DocumentTable,
    DocumentParagraph,
    DocumentBarcode,
    DocumentLanguage,
)
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobClient
from llama_index.core import Document

from src.core.config import settings

logger = logging.getLogger(__name__)


# ========================================================================
# Geometry Data Structures for Pixel-Accurate Highlighting
# ========================================================================

@dataclass
class WordGeometry:
    """Word-level geometry extracted from Azure Document Intelligence.
    
    Coordinates are normalized to [0, 1] relative to page dimensions.
    """
    content: str
    offset: int  # Character offset in document content
    length: int
    page: int  # 1-indexed
    confidence: float
    polygon: List[float]  # [x1,y1,x2,y2,x3,y3,x4,y4] normalized to [0,1]
    
    @property
    def end_offset(self) -> int:
        return self.offset + self.length


@dataclass
class PageDimensions:
    """Page size and orientation from Azure Document Intelligence.
    
    Used by frontend to convert normalized coordinates to pixels.
    """
    page_number: int  # 1-indexed
    width: float  # Points (1/72 inch) or pixels depending on source
    height: float
    rotation: int = 0  # Degrees clockwise: 0, 90, 180, 270
    unit: str = "inch"  # "inch", "pixel", or "point"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page_number,
            "width": self.width,
            "height": self.height,
            "rotation": self.rotation,
            "unit": self.unit,
        }


class WordOffsetIndex:
    """Interval tree for efficient offset-to-word lookups.
    
    Given a character offset range, find all words that overlap.
    Uses sorted lists with binary search for O(log n) lookup.
    """
    
    def __init__(self, words: List[WordGeometry]):
        """Build index from word geometries.
        
        Args:
            words: List of WordGeometry, must be sorted by offset
        """
        self._words = sorted(words, key=lambda w: w.offset)
        # Build arrays for binary search
        self._starts = [w.offset for w in self._words]
        self._ends = [w.end_offset for w in self._words]
    
    def find_overlapping(self, start: int, end: int) -> List[WordGeometry]:
        """Find all words that overlap with [start, end).
        
        A word overlaps if: word.offset < end AND word.end_offset > start
        
        Args:
            start: Start offset (inclusive)
            end: End offset (exclusive)
            
        Returns:
            List of overlapping WordGeometry objects
        """
        if not self._words:
            return []
        
        # Find candidate range using binary search
        # Words starting before 'end' could overlap
        right_bound = bisect_left(self._starts, end)
        
        result = []
        for i in range(right_bound):
            word = self._words[i]
            # Check if this word's end is past our start (overlaps)
            if word.end_offset > start:
                result.append(word)
        
        return result
    
    def find_words_in_range(self, start: int, length: int) -> List[WordGeometry]:
        """Convenience wrapper for find_overlapping."""
        return self.find_overlapping(start, start + length)


@dataclass
class SentenceGeometry:
    """Sentence-level geometry synthesized from word geometries.
    
    Used for pixel-accurate sentence highlighting in the frontend.
    """
    text: str
    offset: int
    length: int
    page: int  # Primary page (first word's page)
    confidence: float  # Length-weighted mean of word confidences
    polygons: List[List[float]]  # Multi-polygon for line-wrapping
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to API response format."""
        return {
            "text": self.text,
            "offset": self.offset,
            "length": self.length,
            "page": self.page,
            "confidence": round(self.confidence, 3),
            "polygons": [[round(x, 4) for x in poly] for poly in self.polygons],
        }


def synthesize_sentence_geometry(
    sentence_text: str,
    sentence_offset: int,
    sentence_length: int,
    word_index: WordOffsetIndex,
    *,
    line_gap_threshold: float = 0.015,  # 1.5% of page height = new line
) -> Optional[SentenceGeometry]:
    """Synthesize sentence geometry from word geometries.
    
    Given a sentence's character span, finds overlapping words and creates
    multi-polygon highlights that handle line-wrapping.
    
    Args:
        sentence_text: The sentence text
        sentence_offset: Character offset in document content
        sentence_length: Length of sentence in characters
        word_index: WordOffsetIndex for efficient lookups
        line_gap_threshold: Y-distance threshold for detecting new lines
        
    Returns:
        SentenceGeometry or None if no words found
    """
    # Find words overlapping with the sentence span
    words = word_index.find_overlapping(sentence_offset, sentence_offset + sentence_length)
    
    if not words:
        return None
    
    # Group words by text line (detect line breaks via Y-coordinate gaps)
    lines: List[List[WordGeometry]] = []
    current_line: List[WordGeometry] = []
    prev_y: Optional[float] = None
    
    # Sort words by page, then by Y, then by X
    sorted_words = sorted(words, key=lambda w: (w.page, _get_word_y(w), _get_word_x(w)))
    
    for word in sorted_words:
        word_y = _get_word_y(word)
        
        if prev_y is None:
            current_line.append(word)
        elif abs(word_y - prev_y) > line_gap_threshold or (current_line and word.page != current_line[-1].page):
            # New line detected (Y gap or page change)
            if current_line:
                lines.append(current_line)
            current_line = [word]
        else:
            current_line.append(word)
        
        prev_y = word_y
    
    if current_line:
        lines.append(current_line)
    
    # Create multi-polygon (one polygon per line)
    polygons: List[List[float]] = []
    for line_words in lines:
        if not line_words:
            continue
        polygon = _merge_line_polygons([w.polygon for w in line_words])
        if polygon:
            polygons.append(polygon)
    
    if not polygons:
        return None
    
    # Compute length-weighted confidence
    total_weight = 0
    weighted_conf = 0.0
    for word in words:
        weight = word.length
        weighted_conf += word.confidence * weight
        total_weight += weight
    
    confidence = weighted_conf / total_weight if total_weight > 0 else 0.0
    
    # Primary page is the first word's page
    page = sorted_words[0].page
    
    return SentenceGeometry(
        text=sentence_text,
        offset=sentence_offset,
        length=sentence_length,
        page=page,
        confidence=confidence,
        polygons=polygons,
    )


def _get_word_y(word: WordGeometry) -> float:
    """Get the Y-coordinate of a word (top edge, normalized)."""
    if len(word.polygon) >= 2:
        # Average of top-left and top-right Y
        return (word.polygon[1] + word.polygon[3]) / 2
    return 0.0


def _get_word_x(word: WordGeometry) -> float:
    """Get the X-coordinate of a word (left edge, normalized)."""
    if word.polygon:
        return word.polygon[0]
    return 0.0


def _merge_line_polygons(polygons: List[List[float]]) -> Optional[List[float]]:
    """Merge word polygons on the same line into a single bounding quad.
    
    Each polygon is [x1,y1,x2,y2,x3,y3,x4,y4] where:
    - (x1,y1) = top-left
    - (x2,y2) = top-right
    - (x3,y3) = bottom-right
    - (x4,y4) = bottom-left
    
    Returns:
        Merged polygon [x1,y1,x2,y2,x3,y3,x4,y4] or None
    """
    if not polygons:
        return None
    
    # Filter out invalid polygons
    valid_polys = [p for p in polygons if len(p) >= 8]
    if not valid_polys:
        return None
    
    # Find bounding box
    min_x = min(min(p[0], p[6]) for p in valid_polys)  # Left edge (x1, x4)
    max_x = max(max(p[2], p[4]) for p in valid_polys)  # Right edge (x2, x3)
    min_y = min(min(p[1], p[3]) for p in valid_polys)  # Top edge (y1, y2)
    max_y = max(max(p[5], p[7]) for p in valid_polys)  # Bottom edge (y3, y4)
    
    # Return as quad: top-left, top-right, bottom-right, bottom-left
    return [min_x, min_y, max_x, min_y, max_x, max_y, min_x, max_y]


class DocumentIntelligenceService:
    """Extract layout-aware documents using Azure Document Intelligence SDK.
    
    Uses prebuilt-layout model which includes OCR capabilities for both
    text-based and image-based PDFs.
    
    Reference: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout
    """

    # Maximum concurrent document analyses (avoid rate limiting)
    DEFAULT_CONCURRENCY = 5

    def __init__(self, max_concurrency: int = DEFAULT_CONCURRENCY) -> None:
        # Backwards-compatible aliasing:
        # Some deployments historically set Azure Content Understanding env vars
        # while using the Document Intelligence SDK. Prefer DI-specific vars, but
        # fall back to CU vars to avoid production breakage.
        self.endpoint: str = (
            settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
            or settings.AZURE_CONTENT_UNDERSTANDING_ENDPOINT
            or ""
        )
        self.api_key = settings.AZURE_DOCUMENT_INTELLIGENCE_KEY or settings.AZURE_CONTENT_UNDERSTANDING_API_KEY
        self.api_version = settings.AZURE_DOC_INTELLIGENCE_API_VERSION
        self.max_concurrency = max_concurrency
        self._semaphore: Optional[asyncio.Semaphore] = None

        if not self.endpoint:
            raise RuntimeError(
                "Document Intelligence endpoint not configured (set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT "
                "or AZURE_CONTENT_UNDERSTANDING_ENDPOINT)"
            )

        # Token authentication (Managed Identity / DefaultAzureCredential) requires the
        # resource-specific custom subdomain endpoint. If the endpoint is the generic
        # regional host (e.g., https://swedencentral.api.cognitive.microsoft.com/),
        # Azure DI will reject token auth unless an API key is used.
        if not self.api_key and ".api.cognitive.microsoft.com" in self.endpoint:
            raise RuntimeError(
                "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT must be the resource custom subdomain "
                "(https://<resource-name>.cognitiveservices.azure.com/) when using Managed Identity. "
                "Either set the correct endpoint or configure AZURE_DOCUMENT_INTELLIGENCE_KEY."
            )

        logger.info(f"Document Intelligence Service Init - Endpoint: {self.endpoint}")
        logger.info(f"Document Intelligence Service Init - Using API key: {bool(self.api_key)}")
        logger.info(f"Document Intelligence Service Init - Max concurrency: {self.max_concurrency}")

    @asynccontextmanager
    async def _create_client(self) -> AsyncIterator[DocumentIntelligenceClient]:
        """Create an async Document Intelligence client and ensure resources are closed.

        Azure async credentials and clients use aiohttp under the hood. If they aren't
        closed, the process can emit warnings like "Unclosed client session/connector".
        """
        if self.api_key:
            logger.info("Document Intelligence: Using API key authentication")
            credential = AzureKeyCredential(self.api_key)
            async with DocumentIntelligenceClient(
                endpoint=self.endpoint,
                credential=credential,
                api_version=self.api_version,
            ) as client:
                yield client
        else:
            logger.info("Document Intelligence: Using managed identity authentication")
            async with DefaultAzureCredential() as credential:
                async with DocumentIntelligenceClient(
                    endpoint=self.endpoint,
                    credential=credential,
                    api_version=self.api_version,
                ) as client:
                    yield client

    def _build_section_hierarchy(self, paragraphs: List[DocumentParagraph]) -> List[str]:
        """Extract section hierarchy from paragraph roles."""
        path = []
        for para in paragraphs:
            if not para.role:
                continue
            
            content = para.content.strip() if para.content else ""
            
            if para.role == "title":
                path = [content]  # Reset to document title
            elif para.role == "sectionHeading":
                # Handle subsections
                if len(path) > 1:
                    path[-1] = content
                else:
                    path.append(content)
        
        return path

    def _extract_table_metadata(self, table: DocumentTable) -> Dict[str, Any]:
        """
        Extract structured table metadata for PropertyGraphIndex.
        
        Returns:
            {
                "row_count": int,
                "column_count": int,
                "headers": List[str],
                "rows": List[Dict[str, str]]
            }
        """
        if not table.cells:
            return {
                "row_count": table.row_count or 0,
                "column_count": table.column_count or 0,
                "headers": [],
                "rows": [],
            }

        # Extract headers (row 0)
        headers = [""] * (table.column_count or 0)
        for cell in table.cells:
            if cell.row_index == 0 and cell.column_index is not None:
                headers[cell.column_index] = cell.content or ""

        # Extract data rows
        rows = []
        for row_idx in range(1, table.row_count or 0):
            row_data = {}
            for cell in table.cells:
                if cell.row_index == row_idx and cell.column_index is not None:
                    col_idx = cell.column_index
                    if col_idx < len(headers):
                        row_data[headers[col_idx]] = cell.content or ""
            
            if row_data:
                rows.append(row_data)

        return {
            "row_count": table.row_count or 0,
            "column_count": table.column_count or 0,
            "headers": headers,
            "rows": rows,
        }

    # ========================================================================
    # Word Geometry Extraction for Pixel-Accurate Highlighting
    # ========================================================================

    def _extract_page_dimensions(self, result: AnalyzeResult) -> List[PageDimensions]:
        """Extract page dimensions from Azure DI result.
        
        Returns normalized page dimensions for coordinate transformation.
        
        Args:
            result: AnalyzeResult from Document Intelligence
            
        Returns:
            List of PageDimensions, one per page
        """
        dimensions: List[PageDimensions] = []
        
        for page in (getattr(result, "pages", None) or []):
            page_num = getattr(page, "page_number", 1) or 1
            width = getattr(page, "width", 0) or 0
            height = getattr(page, "height", 0) or 0
            angle = getattr(page, "angle", 0) or 0
            unit = getattr(page, "unit", "inch") or "inch"
            
            # Normalize angle to standard rotation values
            rotation = 0
            if angle:
                # Round to nearest 90 degrees
                rotation = round(angle / 90) * 90 % 360
            
            dimensions.append(PageDimensions(
                page_number=page_num,
                width=width,
                height=height,
                rotation=rotation,
                unit=unit,
            ))
        
        if dimensions:
            logger.debug(
                f"📐 Extracted page dimensions for {len(dimensions)} pages",
                extra={"page_count": len(dimensions)}
            )
        
        return dimensions

    def _extract_word_geometries(
        self, 
        result: AnalyzeResult,
        page_dimensions: Optional[List[PageDimensions]] = None,
    ) -> Tuple[List[WordGeometry], WordOffsetIndex]:
        """Extract word-level geometry from Azure DI result.
        
        Words are accessed via page.words in the Azure DI response.
        Coordinates are normalized to [0, 1] relative to page dimensions.
        
        Args:
            result: AnalyzeResult from Document Intelligence
            page_dimensions: Pre-extracted page dimensions for normalization
            
        Returns:
            Tuple of (list of WordGeometry, WordOffsetIndex for lookups)
        """
        words: List[WordGeometry] = []
        
        # Build page dimension lookup
        dim_by_page: Dict[int, PageDimensions] = {}
        if page_dimensions:
            dim_by_page = {d.page_number: d for d in page_dimensions}
        
        for page in (getattr(result, "pages", None) or []):
            page_num = getattr(page, "page_number", 1) or 1
            page_words = getattr(page, "words", None) or []
            
            # Get page dimensions for normalization
            page_dim = dim_by_page.get(page_num)
            page_width = page_dim.width if page_dim else (getattr(page, "width", 1) or 1)
            page_height = page_dim.height if page_dim else (getattr(page, "height", 1) or 1)
            
            # Avoid division by zero
            if page_width <= 0:
                page_width = 1
            if page_height <= 0:
                page_height = 1
            
            for word in page_words:
                content = getattr(word, "content", "") or ""
                confidence = getattr(word, "confidence", 0.0) or 0.0
                polygon = getattr(word, "polygon", None) or []
                span = getattr(word, "span", None)
                
                # Extract offset and length from span
                offset = 0
                length = len(content)
                if span:
                    offset = getattr(span, "offset", 0) or 0
                    length = getattr(span, "length", len(content)) or len(content)
                
                # Normalize polygon coordinates to [0, 1]
                # Azure DI polygon format: [x1, y1, x2, y2, x3, y3, x4, y4]
                normalized_polygon: List[float] = []
                if polygon and len(polygon) >= 8:
                    for i, coord in enumerate(polygon[:8]):
                        if i % 2 == 0:  # x coordinate
                            normalized_polygon.append(coord / page_width)
                        else:  # y coordinate
                            normalized_polygon.append(coord / page_height)
                
                if content and normalized_polygon:
                    words.append(WordGeometry(
                        content=content,
                        offset=offset,
                        length=length,
                        page=page_num,
                        confidence=confidence,
                        polygon=normalized_polygon,
                    ))
        
        # Build interval index for efficient lookups
        word_index = WordOffsetIndex(words)
        
        if words:
            avg_confidence = sum(w.confidence for w in words) / len(words)
            logger.info(
                f"📐 Extracted {len(words)} word geometries",
                extra={
                    "word_count": len(words),
                    "avg_confidence": round(avg_confidence, 3),
                    "pages": len(set(w.page for w in words)),
                }
            )
        
        return words, word_index

    def _words_to_serializable(self, words: List[WordGeometry]) -> List[Dict[str, Any]]:
        """Convert WordGeometry list to JSON-serializable format.
        
        For storage efficiency, only include essential fields.
        The full geometry can be reconstructed from offset + polygon.
        
        Args:
            words: List of WordGeometry objects
            
        Returns:
            List of dicts with compact representation
        """
        return [
            {
                "o": w.offset,  # offset
                "l": w.length,  # length
                "p": w.page,    # page
                "c": round(w.confidence, 3),  # confidence
                "g": [round(x, 4) for x in w.polygon],  # geometry (polygon)
            }
            for w in words
        ]

    def _extract_sentences_with_geometry(
        self,
        result: AnalyzeResult,
        word_index: WordOffsetIndex,
        content: str,
    ) -> List[Dict[str, Any]]:
        """Extract sentence-level text with synthesized polygon geometry.
        
        Uses paragraph spans from Azure DI as sentence boundaries and
        synthesizes multi-polygon geometry for each sentence.
        
        Args:
            result: AnalyzeResult from Document Intelligence
            word_index: Pre-built WordOffsetIndex for word lookups
            content: Full document content string
            
        Returns:
            List of sentence dicts with text, offset, length, page, confidence, polygons
        """
        sentences: List[Dict[str, Any]] = []
        
        paragraphs = getattr(result, "paragraphs", None) or []
        
        for para in paragraphs:
            # Skip headers/footers
            role = getattr(para, "role", "") or ""
            if role in ("pageHeader", "pageFooter", "pageNumber"):
                continue
            
            para_content = getattr(para, "content", "") or ""
            if len(para_content.strip()) < 5:
                continue
            
            # Get span information
            spans = getattr(para, "spans", None) or []
            if not spans:
                continue
            
            # Use first span for offset/length
            first_span = spans[0]
            offset = getattr(first_span, "offset", 0) or 0
            length = getattr(first_span, "length", len(para_content)) or len(para_content)
            
            # For long paragraphs, split into sentences
            # Simple sentence detection: split on ". ", "? ", "! "
            import re
            sentence_pattern = r'(?<=[.!?])\s+'
            sentence_texts = re.split(sentence_pattern, para_content)
            
            current_offset = offset
            for sent_text in sentence_texts:
                sent_text = sent_text.strip()
                if len(sent_text) < 5:
                    current_offset += len(sent_text) + 1  # +1 for space
                    continue
                
                # Calculate this sentence's offset within the paragraph
                sent_offset = current_offset
                sent_length = len(sent_text)
                
                # Synthesize geometry for this sentence
                geometry = synthesize_sentence_geometry(
                    sentence_text=sent_text,
                    sentence_offset=sent_offset,
                    sentence_length=sent_length,
                    word_index=word_index,
                )
                
                if geometry:
                    sentences.append(geometry.to_dict())
                else:
                    # Fallback: store sentence without geometry
                    sentences.append({
                        "text": sent_text,
                        "offset": sent_offset,
                        "length": sent_length,
                        "page": 1,  # Unknown
                        "confidence": 0.9,  # Default
                        "polygons": [],
                    })
                
                current_offset += sent_length + 2  # +2 for ". " or "? " or "! "
        
        if sentences:
            with_geom = sum(1 for s in sentences if s.get("polygons"))
            logger.info(
                f"📝 Extracted {len(sentences)} sentences ({with_geom} with geometry)",
                extra={"sentence_count": len(sentences), "with_geometry": with_geom}
            )
        
        return sentences

    def _extract_table_row_sentences(
        self,
        result: AnalyzeResult,
    ) -> List[Dict[str, Any]]:
        """Extract sentence-like structures from table rows.
        
        Tables often contain important line-item data (invoices, price lists, etc.)
        that should be searchable as sentences. Each table row is converted to a
        sentence with format: "HEADER1: value1 | HEADER2: value2 | ..."
        
        Args:
            result: AnalyzeResult from Document Intelligence
            
        Returns:
            List of sentence dicts with text, page, confidence, and polygons from cells
        """
        sentences: List[Dict[str, Any]] = []
        tables = getattr(result, "tables", None) or []
        
        for table_idx, table in enumerate(tables):
            if not table.cells:
                continue
            
            # Extract headers (row 0)
            num_cols = table.column_count or 0
            headers = [""] * num_cols
            for cell in table.cells:
                if cell.row_index == 0 and cell.column_index is not None and cell.column_index < num_cols:
                    headers[cell.column_index] = (cell.content or "").strip()
            
            # Process each data row (starting from row 1)
            for row_idx in range(1, table.row_count or 0):
                row_cells = [c for c in table.cells if c.row_index == row_idx]
                if not row_cells:
                    continue
                
                # Build sentence text from row data
                text_parts = []
                polygons = []
                page_number = 1
                confidences = []
                
                for cell in sorted(row_cells, key=lambda c: c.column_index or 0):
                    col_idx = cell.column_index or 0
                    content = (cell.content or "").strip()
                    if not content:
                        continue
                    
                    # Format: "HEADER: value"
                    header = headers[col_idx] if col_idx < len(headers) else ""
                    if header:
                        text_parts.append(f"{header}: {content}")
                    else:
                        text_parts.append(content)
                    
                    # Extract polygon geometry from cell's bounding_regions
                    cell_regions = getattr(cell, "bounding_regions", None) or []
                    for region in cell_regions:
                        region_page = getattr(region, "page_number", 1) or 1
                        page_number = region_page  # Use last cell's page
                        
                        # Get polygon as list of floats
                        region_polygon = getattr(region, "polygon", None)
                        if region_polygon:
                            # Convert to list if needed
                            poly_list = list(region_polygon) if hasattr(region_polygon, "__iter__") else []
                            if poly_list:
                                polygons.append({
                                    "page": region_page,
                                    "polygon": poly_list,
                                })
                    
                    # Track confidence if available
                    cell_conf = getattr(cell, "confidence", None)
                    if cell_conf is not None:
                        confidences.append(cell_conf)
                
                if not text_parts:
                    continue
                
                # Join cell values with " | " separator
                row_text = " | ".join(text_parts)
                
                # Calculate average confidence
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0.9
                
                sentences.append({
                    "text": row_text,
                    "offset": -1,  # Table rows don't have content offsets
                    "length": len(row_text),
                    "page": page_number,
                    "confidence": avg_confidence,
                    "polygons": polygons,
                    "source": "table",  # Mark as table-derived for debugging
                    "table_index": table_idx,
                    "row_index": row_idx,
                })
        
        if sentences:
            logger.info(
                f"📊 Extracted {len(sentences)} table row sentences from {len(tables)} tables",
                extra={"table_sentence_count": len(sentences), "table_count": len(tables)}
            )
        
        return sentences

    def _page_dimensions_to_serializable(self, dims: List[PageDimensions]) -> List[Dict[str, Any]]:
        """Convert PageDimensions to JSON-serializable format."""
        return [d.to_dict() for d in dims]

    def _extract_barcodes(self, result: AnalyzeResult) -> List[Dict[str, Any]]:
        """Extract barcodes/QR codes from document pages (FREE add-on).
        
        Barcode kinds: QRCode, Code39, Code128, UPC-A, UPC-E, EAN-8, EAN-13,
                      ITF, Codabar, DataBar, PDF417, Aztec, DataMatrix
        
        Returns:
            List of barcode dicts with kind, value, confidence, page_number
        """
        barcodes: List[Dict[str, Any]] = []
        
        for page in (getattr(result, "pages", None) or []):
            page_num = getattr(page, "page_number", 1) or 1
            page_barcodes = getattr(page, "barcodes", None) or []
            
            for bc in page_barcodes:
                kind = getattr(bc, "kind", "") or ""
                value = getattr(bc, "value", "") or ""
                confidence = getattr(bc, "confidence", 0.0) or 0.0
                
                if value:  # Only include barcodes with decoded values
                    # Infer entity type from barcode kind
                    entity_type = self._infer_barcode_entity_type(kind, value)
                    
                    barcodes.append({
                        "kind": kind,
                        "value": value,
                        "confidence": confidence,
                        "page_number": page_num,
                        "entity_type": entity_type,
                    })
        
        if barcodes:
            logger.info(
                f"📊 Extracted {len(barcodes)} barcodes",
                extra={"barcode_count": len(barcodes), "kinds": list(set(b["kind"] for b in barcodes))}
            )
        
        return barcodes

    def _infer_barcode_entity_type(self, kind: str, value: str) -> str:
        """Infer entity type from barcode kind and value pattern."""
        kind_lower = kind.lower()
        
        # UPC/EAN are product codes
        if any(k in kind_lower for k in ["upc", "ean"]):
            return "PRODUCT_CODE"
        
        # QR codes often contain URLs
        if "qr" in kind_lower:
            if value.startswith(("http://", "https://")):
                return "URL"
            return "QR_DATA"
        
        # Code128 with specific patterns
        if "code128" in kind_lower or "code39" in kind_lower:
            # UPS tracking: 1Z...
            if value.startswith("1Z") and len(value) == 18:
                return "TRACKING_NUMBER"
            # FedEx tracking: 12-34 digits
            if value.isdigit() and 12 <= len(value) <= 34:
                return "TRACKING_NUMBER"
        
        # PDF417 often used for IDs
        if "pdf417" in kind_lower:
            return "DOCUMENT_ID"
        
        return "BARCODE"

    def _extract_languages(self, result: AnalyzeResult) -> List[Dict[str, Any]]:
        """Extract detected languages from document (FREE add-on).
        
        Returns:
            List of language dicts with locale, confidence, span_count, and spans
            (spans contain offset/length for sentence-level boundaries)
        """
        languages: List[Dict[str, Any]] = []
        
        for lang in (getattr(result, "languages", None) or []):
            locale = getattr(lang, "locale", "") or ""
            confidence = getattr(lang, "confidence", 0.0) or 0.0
            raw_spans = getattr(lang, "spans", None) or []
            
            # Preserve span offsets for sentence-level context extraction
            # Each span represents a text segment (often sentence/block level)
            spans_data = []
            for span in raw_spans:
                offset = getattr(span, "offset", 0) or 0
                length = getattr(span, "length", 0) or 0
                if length > 0:
                    spans_data.append({"offset": offset, "length": length})
            
            if locale:
                languages.append({
                    "locale": locale,
                    "confidence": confidence,
                    "span_count": len(spans_data),
                    "spans": spans_data,  # Preserved for sentence-level extraction
                })
        
        if languages:
            primary_lang = max(languages, key=lambda x: x.get("span_count", 0))
            total_spans = sum(l.get("span_count", 0) for l in languages)
            logger.info(
                f"🌐 Detected {len(languages)} languages, primary: {primary_lang.get('locale')}, total spans: {total_spans}",
                extra={"languages": [l["locale"] for l in languages], "total_spans": total_spans}
            )
        
        return languages

    def _extract_figures(self, result: AnalyzeResult) -> List[Dict[str, Any]]:
        """Extract figures with cross-section element references.
        
        Figures can reference paragraphs/tables from different sections,
        creating cross-section graph edges without LLM extraction.
        
        Returns:
            List of figure dicts with id, caption, element_refs, footnotes
        """
        figures: List[Dict[str, Any]] = []
        
        for fig in (getattr(result, "figures", None) or []):
            fig_id = getattr(fig, "id", "") or ""
            elements = getattr(fig, "elements", None) or []
            
            # Extract caption
            caption_obj = getattr(fig, "caption", None)
            caption_text = ""
            if caption_obj:
                caption_text = getattr(caption_obj, "content", "") or ""
            
            # Extract footnotes
            footnotes: List[str] = []
            for fn in (getattr(fig, "footnotes", None) or []):
                fn_content = getattr(fn, "content", "") or ""
                if fn_content:
                    footnotes.append(fn_content)
            
            # Parse element references (e.g., "/paragraphs/42", "/tables/5")
            element_refs: List[Dict[str, Any]] = []
            for el in elements:
                parsed = self._parse_di_element_ref(el)
                if parsed:
                    kind, idx = parsed
                    element_refs.append({"kind": kind, "index": idx, "ref": el})
            
            figures.append({
                "id": fig_id,
                "caption": caption_text,
                "element_refs": element_refs,
                "footnotes": footnotes,
                "element_count": len(elements),
            })
        
        if figures:
            logger.info(
                f"📈 Extracted {len(figures)} figures with {sum(len(f['element_refs']) for f in figures)} element references",
                extra={"figure_count": len(figures)}
            )
        
        return figures

    def _extract_selection_marks(self, result: AnalyzeResult) -> List[Dict[str, Any]]:
        """Extract selection marks (checkboxes) from document.
        
        Returns:
            List of selection mark dicts with state, confidence, page_number
        """
        marks: List[Dict[str, Any]] = []
        
        for page in (getattr(result, "pages", None) or []):
            page_num = getattr(page, "page_number", 1) or 1
            page_marks = getattr(page, "selection_marks", None) or []
            
            for mark in page_marks:
                state = getattr(mark, "state", "") or ""
                confidence = getattr(mark, "confidence", 0.0) or 0.0
                
                marks.append({
                    "state": state,  # "selected" or "unselected"
                    "confidence": confidence,
                    "page_number": page_num,
                })
        
        if marks:
            selected_count = sum(1 for m in marks if m["state"] == "selected")
            logger.info(
                f"☑️ Extracted {len(marks)} selection marks ({selected_count} selected)",
                extra={"total": len(marks), "selected": selected_count}
            )
        
        return marks

    def _extract_key_value_pairs(
        self,
        result: AnalyzeResult,
        sections: List[Any],
        content: str,
    ) -> List[Dict[str, Any]]:
        """Extract key-value pairs from DI result with section association.
        
        Associates each KVP to a section based on span offset overlap.
        This enables section-scoped queries for deterministic field lookups.
        
        Args:
            result: Document Intelligence AnalyzeResult
            sections: List of section objects from result.sections
            content: Full document content for span slicing
            
        Returns:
            List of KVP dicts with section association:
            {
                "key": str,
                "value": str,
                "confidence": float,
                "page_number": int,
                "section_id": Optional[str],
                "section_path": List[str],
                "key_span": {"offset": int, "length": int},
                "value_span": {"offset": int, "length": int},
            }
        """
        kvps = getattr(result, "key_value_pairs", None) or []
        if not kvps:
            return []

        extracted: List[Dict[str, Any]] = []
        
        # Build section span index for efficient lookup
        section_spans: List[Tuple[int, int, int, str]] = []  # (start, end, section_idx, title)
        for sec_idx, sec in enumerate(sections):
            sec_spans = getattr(sec, "spans", None) or []
            sec_title = self._infer_section_title_from_section(sec, result.paragraphs or [])
            for span in sec_spans:
                offset = getattr(span, "offset", None)
                length = getattr(span, "length", None)
                if offset is not None and length is not None:
                    section_spans.append((offset, offset + length, sec_idx, sec_title))
        
        for kvp_idx, kvp in enumerate(kvps):
            key_elem = getattr(kvp, "key", None)
            value_elem = getattr(kvp, "value", None)
            confidence = getattr(kvp, "confidence", None) or 0.0
            
            if not key_elem:
                continue
            
            key_content = getattr(key_elem, "content", "") or ""
            value_content = getattr(value_elem, "content", "") if value_elem else ""
            
            # Extract span info
            key_spans = getattr(key_elem, "spans", None) or []
            value_spans = getattr(value_elem, "spans", None) if value_elem else []
            
            key_span = None
            value_span = None
            if key_spans:
                ks = key_spans[0]
                key_span = {"offset": getattr(ks, "offset", 0), "length": getattr(ks, "length", 0)}
            if value_spans:
                vs = value_spans[0]
                value_span = {"offset": getattr(vs, "offset", 0), "length": getattr(vs, "length", 0)}
            
            # Extract page number from bounding regions
            page_number = 1
            key_regions = getattr(key_elem, "bounding_regions", None) or []
            if key_regions:
                page_number = getattr(key_regions[0], "page_number", 1) or 1
            
            # Find section association based on key span offset
            section_id = None
            section_path: List[str] = []
            if key_span:
                kvp_offset = key_span["offset"]
                for start, end, sec_idx, sec_title in section_spans:
                    if start <= kvp_offset < end:
                        section_id = f"section_{sec_idx}"
                        section_path = [sec_title] if sec_title else []
                        break
            
            extracted.append({
                "key": key_content.strip(),
                "value": value_content.strip(),
                "confidence": confidence,
                "page_number": page_number,
                "section_id": section_id,
                "section_path": section_path,
                "key_span": key_span,
                "value_span": value_span,
            })
        
        logger.info(
            f"📋 Extracted {len(extracted)} key-value pairs",
            extra={"kvp_count": len(extracted), "with_section": sum(1 for k in extracted if k["section_id"])}
        )
        
        return extracted

    def _infer_section_title_from_section(
        self,
        section: Any,
        paragraphs: List[DocumentParagraph],
    ) -> str:
        """Infer section title from section elements."""
        elements = getattr(section, "elements", None) or []
        for el in elements:
            parsed = self._parse_di_element_ref(el)
            if not parsed:
                continue
            kind, idx = parsed
            if kind == "paragraphs" and 0 <= idx < len(paragraphs):
                para = paragraphs[idx]
                role = getattr(para, "role", None) or ""
                if role in ("title", "sectionHeading"):
                    return getattr(para, "content", "") or ""
        return ""

    def _build_markdown_from_result(self, result: AnalyzeResult) -> str:
        """
        Convert Document Intelligence result to clean markdown.
        
        Uses paragraph roles to create proper heading hierarchy.
        Includes tables as markdown tables.
        """
        lines = []

        if result.paragraphs:
            for para in result.paragraphs:
                if not para.content:
                    continue

                content = para.content.strip()
                role = para.role or ""

                # Skip headers/footers (noise)
                if role in ("pageHeader", "pageFooter", "pageNumber"):
                    continue

                # Convert to markdown based on role
                if role == "title":
                    lines.append(f"# {content}")
                elif role == "sectionHeading":
                    lines.append(f"## {content}")
                else:
                    lines.append(content)

        # Add tables as markdown
        if result.tables:
            for table in result.tables:
                if not table.cells:
                    continue

                # Build markdown table
                col_count = table.column_count or 0
                headers = [""] * col_count

                # Extract headers
                for cell in table.cells:
                    if cell.row_index == 0 and cell.column_index is not None:
                        headers[cell.column_index] = cell.content or ""

                # Table header
                table_lines = [
                    "| " + " | ".join(headers) + " |",
                    "| " + " | ".join(["---"] * col_count) + " |",
                ]

                # Table rows
                for row_idx in range(1, table.row_count or 0):
                    row_cells = [""] * col_count
                    for cell in table.cells:
                        if cell.row_index == row_idx and cell.column_index is not None:
                            row_cells[cell.column_index] = cell.content or ""
                    table_lines.append("| " + " | ".join(row_cells) + " |")

                lines.extend(table_lines)

        return "\n\n".join(lines)

    def _slice_content_by_spans(self, content: str, spans: Any) -> str:
        if not content or not spans:
            return ""

        start: Optional[int] = None
        end: Optional[int] = None

        for span in spans:
            if span is None:
                continue

            # DI span objects are typically {offset, length} with attributes.
            offset = getattr(span, "offset", None)
            length = getattr(span, "length", None)
            if offset is None and isinstance(span, dict):
                offset = span.get("offset")
                length = span.get("length")

            if offset is None or length is None:
                continue

            try:
                offset_i = int(offset)
                length_i = int(length)
            except Exception:
                continue

            if start is None or offset_i < start:
                start = offset_i
            span_end = offset_i + length_i
            if end is None or span_end > end:
                end = span_end

        if start is None or end is None or start >= end:
            return ""

        return content[start:end].strip()

    _DI_ELEMENT_REF_RE = re.compile(r"^/(paragraphs|sections|tables)/(\d+)$")

    def _parse_di_element_ref(self, ref: Any) -> Optional[Tuple[str, int]]:
        if not isinstance(ref, str):
            return None
        m = self._DI_ELEMENT_REF_RE.match(ref.strip())
        if not m:
            return None
        kind = m.group(1)
        try:
            idx = int(m.group(2))
        except Exception:
            return None
        return (kind, idx)

    def _collect_span_union(self, spans_list: List[Any]) -> List[Dict[str, int]]:
        """Return a conservative union span as a list of {offset,length}.

        We intentionally return a single merged span (min offset..max end)
        to keep slicing simple and stable.
        """
        start: Optional[int] = None
        end: Optional[int] = None

        for spans in spans_list:
            if not spans:
                continue
            for span in spans:
                if span is None:
                    continue
                offset = getattr(span, "offset", None)
                length = getattr(span, "length", None)
                if offset is None and isinstance(span, dict):
                    offset = span.get("offset")
                    length = span.get("length")
                if offset is None or length is None:
                    continue
                try:
                    o = int(offset)
                    l = int(length)
                except Exception:
                    continue
                if l <= 0:
                    continue
                if start is None or o < start:
                    start = o
                e = o + l
                if end is None or e > end:
                    end = e

        if start is None or end is None or start >= end:
            return []
        return [{"offset": start, "length": end - start}]

    def _infer_section_title(self, paragraph_indices: List[int], paragraphs: List[DocumentParagraph], fallback: str) -> str:
        for idx in paragraph_indices:
            if idx < 0 or idx >= len(paragraphs):
                continue
            p = paragraphs[idx]
            if not getattr(p, "content", None):
                continue
            role = getattr(p, "role", None) or ""
            if role in ("title", "sectionHeading"):
                return str(p.content).strip() or fallback
        # fallback to first non-empty paragraph
        for idx in paragraph_indices:
            if idx < 0 or idx >= len(paragraphs):
                continue
            p = paragraphs[idx]
            if getattr(p, "content", None):
                return str(p.content).strip()[:120] or fallback
        return fallback

    def _build_markdown_from_paragraphs_and_tables(
        self,
        paragraphs: List[DocumentParagraph],
        tables: List[DocumentTable],
    ) -> str:
        lines: List[str] = []
        for para in paragraphs:
            if not getattr(para, "content", None):
                continue
            role = getattr(para, "role", None) or ""
            content = str(para.content).strip()
            if role in ("pageHeader", "pageFooter", "pageNumber"):
                continue
            if role == "title":
                lines.append(f"# {content}")
            elif role == "sectionHeading":
                lines.append(f"## {content}")
            else:
                lines.append(content)

        for table in tables:
            if not getattr(table, "cells", None):
                continue
            col_count = int(getattr(table, "column_count", 0) or 0)
            if col_count <= 0:
                continue
            headers = [""] * col_count
            for cell in table.cells:
                if getattr(cell, "row_index", None) == 0 and getattr(cell, "column_index", None) is not None:
                    headers[int(cell.column_index)] = cell.content or ""

            table_md = [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join(["---"] * col_count) + " |",
            ]
            row_count = int(getattr(table, "row_count", 0) or 0)
            for row_idx in range(1, row_count):
                row_cells = [""] * col_count
                for cell in table.cells:
                    if getattr(cell, "row_index", None) == row_idx and getattr(cell, "column_index", None) is not None:
                        row_cells[int(cell.column_index)] = cell.content or ""
                table_md.append("| " + " | ".join(row_cells) + " |")
            lines.extend(table_md)

        return "\n\n".join(lines).strip()

    def _build_section_aware_documents(
        self,
        result: AnalyzeResult,
        group_id: str,
        url: str,
        *,
        word_index: Optional[WordOffsetIndex] = None,
        geometry_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Create section/subsection chunks using `result.sections`.

        This produces more semantically coherent chunks than per-page splitting and
        makes downstream retrieval more precise.
        
        Also extracts:
        - Key-value pairs associated with sections
        - Barcodes/QR codes (FREE add-on)
        - Language detection (FREE add-on)
        - Figure cross-references
        - Selection marks (checkboxes)
        - Word geometry for pixel-accurate highlighting (if word_index provided)
        
        Args:
            result: Azure DI AnalyzeResult
            group_id: Tenant isolation ID
            url: Source document URL
            word_index: Optional WordOffsetIndex for geometry lookups
            geometry_metadata: Optional pre-computed geometry metadata
        """
        sections = list(getattr(result, "sections", None) or [])
        if not sections:
            return []

        paragraphs: List[DocumentParagraph] = list(getattr(result, "paragraphs", None) or [])
        tables: List[DocumentTable] = list(getattr(result, "tables", None) or [])

        content = getattr(result, "content", None) or ""
        
        # Extract key-value pairs with section association
        key_value_pairs = self._extract_key_value_pairs(result, sections, content)
        
        # Extract FREE add-on features
        barcodes = self._extract_barcodes(result)
        languages = self._extract_languages(result)
        figures = self._extract_figures(result)
        selection_marks = self._extract_selection_marks(result)
        
        # Build section_idx -> KVPs mapping for efficient lookup
        kvps_by_section: Dict[int, List[Dict[str, Any]]] = {}
        orphan_kvps: List[Dict[str, Any]] = []  # KVPs not associated with any section
        for kvp in key_value_pairs:
            section_id = kvp.get("section_id")
            if section_id and section_id.startswith("section_"):
                try:
                    sec_idx = int(section_id.split("_")[1])
                    kvps_by_section.setdefault(sec_idx, []).append(kvp)
                except (ValueError, IndexError):
                    orphan_kvps.append(kvp)
            else:
                orphan_kvps.append(kvp)

        def _safe_get_paragraph(i: int) -> Optional[DocumentParagraph]:
            if i < 0 or i >= len(paragraphs):
                return None
            return paragraphs[i]

        def _safe_get_table(i: int) -> Optional[DocumentTable]:
            if i < 0 or i >= len(tables):
                return None
            return tables[i]

        # Build a conservative root set: if DI provides nested sections but doesn't
        # provide explicit roots, treat all indices as roots.
        # (We avoid attempting to infer parent pointers from elements to keep behavior stable.)
        root_indices = list(range(len(sections)))

        docs: List[Document] = []

        def walk(section_idx: int, parent_titles: List[str], parent_ids: List[int]) -> None:
            if section_idx < 0 or section_idx >= len(sections):
                return
            sec = sections[section_idx]
            elements = list(getattr(sec, "elements", None) or [])

            child_sections: List[int] = []
            para_indices: List[int] = []
            table_indices: List[int] = []

            for el in elements:
                parsed = self._parse_di_element_ref(el)
                if not parsed:
                    continue
                kind, idx = parsed
                if kind == "sections":
                    child_sections.append(idx)
                elif kind == "paragraphs":
                    para_indices.append(idx)
                elif kind == "tables":
                    table_indices.append(idx)

            title_fallback = f"section_{section_idx}"
            title = self._infer_section_title(para_indices, paragraphs, title_fallback)
            titles = [*parent_titles, title]
            ids = [*parent_ids, section_idx]

            # Prefer explicit spans on the section; otherwise aggregate paragraph spans.
            section_spans = list(getattr(sec, "spans", None) or [])
            direct_paras = [p for i in para_indices if (p := _safe_get_paragraph(i))]
            direct_tables = [t for i in table_indices if (t := _safe_get_table(i))]

            # If this section has children, we still may have direct content that isn't
            # captured by child sections (common for an intro paragraph).
            has_children = len(child_sections) > 0

            def emit_chunk(*, part: str, spans: Any, paras: List[DocumentParagraph], tbls: List[DocumentTable]) -> None:
                merged = self._collect_span_union([spans] if spans else [getattr(p, "spans", None) or [] for p in paras])
                text = ""
                if content and merged:
                    text = self._slice_content_by_spans(content, merged)
                if not text:
                    text = self._build_markdown_from_paragraphs_and_tables(paras, tbls)
                if not text:
                    return

                tables_metadata = [self._extract_table_metadata(t) for t in tbls]
                
                # Get KVPs associated with this section
                section_kvps = kvps_by_section.get(section_idx, [])
                # For first chunk of document, also include orphan KVPs
                if section_idx == 0 and part == "direct":
                    section_kvps = section_kvps + orphan_kvps

                # Extract page number from first paragraph's bounding regions
                page_number = None
                for para in paras:
                    bounding_regions = getattr(para, "bounding_regions", None) or []
                    if bounding_regions:
                        page_number = getattr(bounding_regions[0], "page_number", None)
                        if page_number:
                            break
                # Fallback: try tables if no paragraph has bounding region
                if page_number is None:
                    for tbl in tbls:
                        bounding_regions = getattr(tbl, "bounding_regions", None) or []
                        if bounding_regions:
                            page_number = getattr(bounding_regions[0], "page_number", None)
                            if page_number:
                                break
                
                # Extract character offsets from merged spans
                start_offset = None
                end_offset = None
                if merged:
                    first_span = merged[0]
                    start_offset = first_span.get("offset")
                    length = first_span.get("length")
                    if start_offset is not None and length is not None:
                        end_offset = start_offset + length
                
                # Build geometry metadata for this chunk
                # Note: We store sentences (with polygons) but NOT word_geometries
                # Word geometries are only used for synthesis; storing would bloat Neo4j
                chunk_geometry: Dict[str, Any] = {}
                if geometry_metadata and section_idx == 0 and part == "direct":
                    # First chunk gets page dimensions and all sentences
                    chunk_geometry["page_dimensions"] = geometry_metadata.get("page_dimensions", [])
                    chunk_geometry["sentences"] = geometry_metadata.get("sentences", [])
                elif word_index and start_offset is not None and end_offset is not None:
                    # Other chunks get their relevant sentences (filter by offset range)
                    if geometry_metadata and geometry_metadata.get("sentences"):
                        chunk_sentences = [
                            s for s in geometry_metadata["sentences"]
                            if s.get("offset", 0) >= start_offset and s.get("offset", 0) < end_offset
                        ]
                        if chunk_sentences:
                            chunk_geometry["sentences"] = chunk_sentences
                    # Store offset range for fallback geometry reconstruction
                    chunk_geometry["offset_range"] = [start_offset, end_offset]

                # Document-level metadata: attach to the FIRST emitted unit so
                # that _store_di_metadata_in_graph() can pick it up regardless
                # of which section/part combination happens to be first.
                is_first_unit = len(docs) == 0

                docs.append(
                    Document(
                        text=text,
                        metadata={
                            "group_id": group_id,
                            "source": "document-intelligence",
                            "url": url,
                            "chunk_type": "section",
                            "section_path": titles,
                            "di_section_path": ids,
                            "di_section_part": part,
                            "tables": tables_metadata,
                            "table_count": len(tbls),
                            "paragraph_count": len(paras),
                            "key_value_pairs": section_kvps,
                            "kvp_count": len(section_kvps),
                            # Location metadata for citation tracking
                            **({"page_number": page_number} if page_number is not None else {}),
                            **({"start_offset": start_offset} if start_offset is not None else {}),
                            **({"end_offset": end_offset} if end_offset is not None else {}),
                            # Word geometry for pixel-accurate highlighting
                            **(chunk_geometry if chunk_geometry else {}),
                            # Document-level metadata (included in first emitted unit)
                            **({"barcodes": barcodes} if is_first_unit and barcodes else {}),
                            **({"languages": languages} if is_first_unit and languages else {}),
                            **({"figures": figures} if is_first_unit and figures else {}),
                            **({"selection_marks": selection_marks} if is_first_unit and selection_marks else {}),
                        },
                    )
                )

            # Emit direct content chunk (intro/body) if present.
            if direct_paras or direct_tables:
                emit_chunk(part="direct", spans=section_spans, paras=direct_paras, tbls=direct_tables)

            # Recurse into child sections.
            for child_idx in child_sections:
                walk(child_idx, titles, ids)

            # Leaf section with no direct content but with explicit spans: emit anyway.
            if not has_children and not (direct_paras or direct_tables) and section_spans:
                emit_chunk(part="spans", spans=section_spans, paras=[], tbls=[])

        for idx in root_indices:
            walk(idx, [], [])

        # De-dup exact duplicates (can happen when roots include nested sections).
        seen: set[tuple[str, str]] = set()
        unique: List[Document] = []
        for d in docs:
            key = (str(d.metadata.get("url") or ""), str(d.metadata.get("di_section_path") or ""))
            if key in seen:
                continue
            seen.add(key)
            unique.append(d)
        return unique

    def _select_model(self, url: str, default_model: str = "prebuilt-layout", explicit: Optional[str] = None) -> str:
        """Select Document Intelligence model based on hints.

        Priority:
        1) explicit override (e.g., 'prebuilt-invoice')
        2) default model

        NOTE: URL-based heuristics were removed because they silently routed
        documents to specialised models (prebuilt-invoice, prebuilt-receipt) that
        do NOT support add-on features such as LANGUAGES.  Callers that need a
        non-layout model should pass ``explicit`` or set ``di_model`` on the
        input item dict.
        """
        if explicit:
            return explicit

        # No filename-based guessing — always honour the caller's default.
        return default_model

    async def _analyze_single_document(
        self,
        client: DocumentIntelligenceClient,
        url: str,
        group_id: str,
        *,
        default_model: str = "prebuilt-layout",
        explicit_model: Optional[str] = None,
    ) -> Tuple[str, List[Document], Optional[str]]:
        """
        Analyze a single document and return extracted Documents.
        
        Returns:
            Tuple of (url, documents, error_message)
            - If successful: (url, [Document, ...], None)
            - If failed: (url, [], "error message")
        """
        # Use semaphore to limit concurrency
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrency)
        
        async with self._semaphore:
            logger.info(f"Document Intelligence analyzing: {url[:80]}...")
            
            try:
                # Decide model
                selected_model = self._select_model(url, default_model=default_model, explicit=explicit_model)

                # DI can access Azure blob storage directly using its own Managed Identity
                # No need to download locally - just pass the URL (with SAS if present)
                logger.info(f"⏳ Starting Document Intelligence analysis (URL source, model={selected_model})...")
                # Enable add-on features for enhanced extraction (v4 API pricing)
                # KEY_VALUE_PAIRS: FREE in v4 API - deterministic field lookups
                # BARCODES: FREE - QR codes, UPC, tracking numbers
                # LANGUAGES: FREE - per-span language detection
                # Selection marks: Included in base prebuilt-layout (no add-on needed)
                poller = await client.begin_analyze_document(
                    selected_model,
                    AnalyzeDocumentRequest(url_source=url),
                    output_content_format=DocumentContentFormat.MARKDOWN,
                    features=[
                        DocumentAnalysisFeature.KEY_VALUE_PAIRS,  # FREE in v4!
                        DocumentAnalysisFeature.BARCODES,         # FREE!
                        DocumentAnalysisFeature.LANGUAGES,        # FREE!
                    ],
                )

                # Wait for completion with timeout (SDK handles polling automatically)
                # Azure DI typically takes 2-10 seconds per document, can be slower under load
                di_timeout = settings.AZURE_DI_TIMEOUT
                try:
                    result: AnalyzeResult = await asyncio.wait_for(
                        poller.result(), 
                        timeout=di_timeout
                    )
                    logger.info(f"✅ Document Intelligence analysis completed for {url[:80]}")
                except asyncio.TimeoutError:
                    logger.error(f"❌ Document Intelligence analysis timed out after {di_timeout}s for {url[:80]}")
                    raise TimeoutError(f"Document Intelligence analysis timed out for {url}")

                if not getattr(result, "pages", None):
                    logger.warning(f"No pages extracted from {url}")
                    return (url, [], None)

                # ========================================================
                # Extract word geometry for pixel-accurate highlighting
                # ========================================================
                page_dimensions = self._extract_page_dimensions(result)
                word_geometries, word_index = self._extract_word_geometries(result, page_dimensions)
                
                # Extract sentences with synthesized polygon geometry
                content = getattr(result, "content", None) or ""
                sentences_with_geometry = self._extract_sentences_with_geometry(result, word_index, content)
                
                # Extract sentence-like structures from table rows (invoices, price lists, etc.)
                table_row_sentences = self._extract_table_row_sentences(result)
                
                # Merge paragraph sentences and table row sentences
                all_sentences = sentences_with_geometry + table_row_sentences
                
                # Serialize for storage (compact format)
                geometry_metadata = {
                    "page_dimensions": self._page_dimensions_to_serializable(page_dimensions),
                    "word_geometries": self._words_to_serializable(word_geometries),
                    "sentences": all_sentences,  # Sentence-level polygons for highlighting
                }

                # Log Document Intelligence confidence scores
                if result.paragraphs:
                    confidences = [p.confidence for p in result.paragraphs if hasattr(p, 'confidence') and p.confidence is not None]
                    if confidences:
                        avg_confidence = sum(confidences) / len(confidences)
                        min_confidence = min(confidences)
                        logger.info(f"📊 DI Confidence: avg={avg_confidence:.3f}, min={min_confidence:.3f}, samples={len(confidences)}")

                documents: List[Document] = []

                # Prefer section-aware chunking when DI provides a sections tree.
                # This produces higher-precision chunks and improves downstream retrieval.
                if getattr(result, "sections", None) and getattr(result, "content", None):
                    section_docs = self._build_section_aware_documents(
                        result, group_id, url,
                        word_index=word_index,
                        geometry_metadata=geometry_metadata,
                    )
                    if not section_docs:
                        raise RuntimeError(
                            "Document Intelligence returned a sections tree, but section-aware chunking produced 0 chunks"
                        )
                    logger.info(
                        "✅ Extracted section-aware chunks",
                        extra={
                            "url": url,
                            "chunks": len(section_docs),
                            "sections": len(getattr(result, "sections", None) or []),
                        },
                    )
                    return (url, section_docs, None)
                
                # Create one document per page (better for large docs)
                # Extract document-level add-on features for propagation
                page_languages = self._extract_languages(result)
                page_barcodes = self._extract_barcodes(result)

                for page in result.pages:
                    page_num = page.page_number

                    # Prefer DI-native content (markdown) when available.
                    # We still compute structured metadata from paragraphs/tables.
                    page_markdown = ""
                    if getattr(result, "content", None):
                        page_markdown = self._slice_content_by_spans(result.content, getattr(page, "spans", None))

                    # Get paragraphs for this page
                    page_paragraphs = [
                        p for p in (result.paragraphs or [])
                        if any(
                            region.page_number == page_num 
                            for region in (p.bounding_regions or [])
                        )
                    ]

                    # Get tables for this page
                    page_tables = [
                        t for t in (result.tables or [])
                        if any(
                            region.page_number == page_num
                            for region in (t.bounding_regions or [])
                        )
                    ]

                    # Build markdown for this page
                    markdown = page_markdown
                    if not markdown:
                        # Fallback: build a basic markdown representation from paragraphs/tables.
                        page_lines = []
                        for para in page_paragraphs:
                            if not para.content:
                                continue
                            
                            role = para.role or ""
                            content = para.content.strip()

                            if role in ("pageHeader", "pageFooter", "pageNumber"):
                                continue
                            elif role == "title":
                                page_lines.append(f"# {content}")
                            elif role == "sectionHeading":
                                page_lines.append(f"## {content}")
                            else:
                                page_lines.append(content)

                        # Add tables
                        for table in page_tables:
                            if not table.cells:
                                continue

                            col_count = table.column_count or 0
                            headers = [""] * col_count

                            for cell in table.cells:
                                if cell.row_index == 0 and cell.column_index is not None:
                                    headers[cell.column_index] = cell.content or ""

                            table_md = [
                                "| " + " | ".join(headers) + " |",
                                "| " + " | ".join(["---"] * col_count) + " |",
                            ]

                            for row_idx in range(1, table.row_count or 0):
                                row_cells = [""] * col_count
                                for cell in table.cells:
                                    if cell.row_index == row_idx and cell.column_index is not None:
                                        row_cells[cell.column_index] = cell.content or ""
                                table_md.append("| " + " | ".join(row_cells) + " |")

                            page_lines.extend(table_md)

                        markdown = "\n\n".join(page_lines)

                    # Extract metadata
                    section_path = self._build_section_hierarchy(page_paragraphs)
                    tables_metadata = [
                        self._extract_table_metadata(t) for t in page_tables
                    ]

                    # Build geometry metadata for this page
                    # Note: Store only page_dimensions and sentences, NOT word_geometries
                    page_geometry: Dict[str, Any] = {}
                    if page_num == 1 and geometry_metadata:
                        # First page gets page dimensions and all sentences
                        page_geometry["page_dimensions"] = geometry_metadata.get("page_dimensions", [])
                        page_geometry["sentences"] = geometry_metadata.get("sentences", [])

                    # Create Document with structured table metadata for schema-aware extraction
                    # The 'tables' metadata enables direct field mapping without LLM parsing
                    logger.info(f"📄 Extracted page {page_num}: {len(markdown)} chars, {len(page_paragraphs)} paragraphs, {len(page_tables)} tables")
                    if markdown.strip():
                        # Attach document-level metadata to first emitted unit
                        is_first_page_unit = len(documents) == 0
                        doc = Document(
                            text=markdown,
                            metadata={
                                "page_number": page_num,
                                "group_id": group_id,
                                "source": "document-intelligence",
                                "url": url,
                                "section_path": section_path,  # Hierarchical section info
                                "tables": tables_metadata,  # Structured table data for direct extraction
                                "table_count": len(page_tables),
                                "paragraph_count": len(page_paragraphs),
                                # Word geometry for pixel-accurate highlighting
                                **page_geometry,
                                # Document-level metadata (first unit only)
                                **({"languages": page_languages} if is_first_page_unit and page_languages else {}),
                                **({"barcodes": page_barcodes} if is_first_page_unit and page_barcodes else {}),
                            },
                        )
                        documents.append(doc)

                logger.info(
                    f"✅ Extracted {len(result.pages)} pages from {url[:50]}... "
                    f"({len(result.paragraphs or [])} paragraphs, "
                    f"{len(result.tables or [])} tables)"
                )
                
                return (url, documents, None)

            except Exception as e:
                error_msg = f"Failed to analyze {url}: {e}"
                logger.error(error_msg)
                return (url, [], error_msg)

    async def extract_documents(
        self, 
        group_id: str, 
        input_items: List[Union[str, Dict[str, Any]]],
        fail_fast: bool = False,
        *,
        model_strategy: str = "auto",  # 'auto' | 'layout' | 'invoice' | 'receipt'
    ) -> List[Document]:
        """
        Extract structured Documents from files using Azure Document Intelligence.
        
        **Supports batch processing of multiple documents in parallel!**

        Args:
            group_id: Tenant ID for multi-tenancy
            input_items: List of URLs, dicts with {url}, or raw text strings
            fail_fast: If True, raise on first error. If False (default), continue and log errors.

        Returns:
            List of LlamaIndex Documents with layout-aware metadata:
            - text: Markdown with proper headings and tables
            - metadata: {
                page_number, 
                section_path, 
                tables, 
                bounding_regions,
                group_id
              }
        """
        logger.info(f"🔍 Document Intelligence extract_documents called with {len(input_items)} items for group '{group_id}'")
        logger.info(f"   Items: {[str(item)[:100] for item in input_items]}")
        
        # Separate URLs from raw text
        urls: List[str] = []
        passthrough_texts: List[str] = []
        # Optional per-item override: map URL->explicit model
        per_item_model: Dict[str, str] = {}

        for item in input_items:
            if isinstance(item, dict):
                if "text" in item:
                    passthrough_texts.append(item["text"])
                elif "url" in item:
                    url = item["url"]
                    urls.append(url)
                    # Allow per-item explicit override via 'di_model' or 'doc_type'
                    model = item.get("di_model") or None
                    doc_type = (item.get("doc_type") or "").lower()
                    if not model and doc_type:
                        if doc_type in ("invoice", "ap-invoice"):
                            model = "prebuilt-invoice"
                        elif doc_type in ("receipt", "sales-receipt"):
                            model = "prebuilt-receipt"
                    if model:
                        per_item_model[url] = model
                else:
                    raise ValueError("Dict must have 'text' or 'url'")
            elif isinstance(item, str):
                if item.startswith(("http://", "https://")):
                    urls.append(item)
                else:
                    passthrough_texts.append(item)
            else:
                raise ValueError("Unsupported item type")

        logger.info(f"   Parsed: {len(urls)} URLs, {len(passthrough_texts)} passthrough texts")
        
        documents: List[Document] = []

        # Add passthrough texts as simple Documents
        for text in passthrough_texts:
            documents.append(
                Document(
                    text=text, 
                    metadata={"group_id": group_id, "source": "passthrough"}
                )
            )

        # Process URLs via Document Intelligence Batch API
        if urls:
            logger.info(f"📦 Batch processing {len(urls)} documents with 600s timeout")
            
            async with self._create_client() as client:
                # Resolve default model from strategy
                if model_strategy == "layout":
                    default_model = "prebuilt-layout"
                elif model_strategy == "invoice":
                    default_model = "prebuilt-invoice"
                elif model_strategy == "receipt":
                    default_model = "prebuilt-receipt"
                else:
                    default_model = "prebuilt-layout"  # auto with layout fallback

                # Create parallel tasks for all documents
                tasks = []
                for url in urls:
                    tasks.append(
                        self._analyze_single_document(
                            client,
                            url,
                            group_id,
                            default_model=default_model,
                            explicit_model=per_item_model.get(url),
                        )
                    )
                
                # Run all in parallel with batch timeout
                # Each document has 60s timeout internally; batch timeout should be generous
                # for parallel processing (e.g., 5 docs @ 60s each = max 60s if truly parallel,
                # but allow much longer for queueing/throttling in production)
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=600  # 600s (10min) for entire batch to handle throttling
                    )
                except asyncio.TimeoutError:
                    logger.error("❌ Batch timeout after 600s")
                    if fail_fast:
                        raise RuntimeError("Batch processing timeout after 10 minutes")
                    return documents
                
                # Process results
                errors: List[str] = []
                for raw_result in results:
                    if isinstance(raw_result, Exception):
                        errors.append(str(raw_result))
                        if fail_fast:
                            raise RuntimeError(f"Batch processing failed: {raw_result}")
                        continue
                    
                    # Type narrowing: raw_result is now Tuple[str, List[Document], Optional[str]]
                    url, docs, error = raw_result  # type: ignore
                    if error:
                        errors.append(error)
                        if fail_fast:
                            raise RuntimeError(error)
                    else:
                        documents.extend(docs)
                
                # Log summary
                success_count = len(urls) - len(errors)
                if errors:
                    logger.warning(
                        f"⚠️ Batch completed with {len(errors)} errors: "
                        f"{success_count}/{len(urls)} documents processed successfully"
                    )
                    for err in errors[:5]:  # Log first 5 errors
                        logger.warning(f"   - {err[:100]}")
                else:
                    logger.info(f"✅ Batch completed: {success_count}/{len(urls)} documents processed")

        logger.info(f"📄 Total extracted: {len(documents)} document pages for group {group_id}")
        return documents
