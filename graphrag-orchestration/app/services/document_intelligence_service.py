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
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple, Union
from urllib.parse import unquote

from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import (
    AnalyzeDocumentRequest,
    AnalyzeResult,
    DocumentContentFormat,
    DocumentTable,
    DocumentParagraph,
)
from azure.core.credentials import AzureKeyCredential
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobClient
from llama_index.core import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class DocumentIntelligenceService:
    """Extract layout-aware documents using Azure Document Intelligence SDK.
    
    Uses prebuilt-layout model which includes OCR capabilities for both
    text-based and image-based PDFs.
    
    Reference: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/layout
    """

    # Maximum concurrent document analyses (avoid rate limiting)
    DEFAULT_CONCURRENCY = 5

    def __init__(self, max_concurrency: int = DEFAULT_CONCURRENCY) -> None:
        self.endpoint: str = settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT or ""
        self.api_key = settings.AZURE_DOCUMENT_INTELLIGENCE_KEY
        self.api_version = settings.AZURE_DOC_INTELLIGENCE_API_VERSION
        self.max_concurrency = max_concurrency
        self._semaphore: Optional[asyncio.Semaphore] = None

        if not self.endpoint:
            raise RuntimeError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT not configured")

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

    def _select_model(self, url: str, default_model: str = "prebuilt-layout", explicit: Optional[str] = None) -> str:
        """Select Document Intelligence model based on hints.

        Priority:
        1) explicit override (e.g., 'prebuilt-invoice')
        2) filename/url heuristics
        3) default model
        """
        if explicit:
            return explicit

        lower = url.lower()
        # Simple heuristics: prefer invoice/receipt when filename hints exist
        if any(k in lower for k in ["invoice", "inv_"]):
            return "prebuilt-invoice"
        if any(k in lower for k in ["receipt", "rcpt_"]):
            return "prebuilt-receipt"
        # Fallback
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
                # Check if URL is a blob URL and try to download content if possible
                # This handles private blobs by downloading with Managed Identity
                document_bytes = None
                
                if ".blob.core.windows.net" in url:
                    try:
                        logger.info(f"Attempting to download blob content from: {url}")
                        
                        # Use DefaultAzureCredential for blob access (Managed Identity)
                        # This requires the Container App to have 'Storage Blob Data Reader' role.
                        # Ensure credential is properly closed to avoid aiohttp unclosed-session warnings.
                        async with DefaultAzureCredential() as credential:
                            # Extract blob URL without query params (SAS tokens not needed with MI)
                            clean_url = url.split('?')[0]
                            logger.info(f"Using clean blob URL (no SAS): {clean_url}")

                            async with BlobClient.from_blob_url(clean_url, credential=credential) as blob_client:
                                content = await blob_client.download_blob()
                                document_bytes = await content.readall()

                                logger.info(f"✅ Successfully downloaded blob content ({len(document_bytes)} bytes)")
                    except Exception as e:
                        logger.error(f"❌ Failed to download blob content: {str(e)}")
                        logger.error(f"   This likely means the Container App doesn't have 'Storage Blob Data Reader' role")
                        logger.error(f"   or the blob doesn't exist. Cannot proceed without blob content.")
                        # Re-raise the exception instead of silently falling back
                        raise RuntimeError(f"Failed to download blob {url}: {str(e)}")

                # Decide model
                selected_model = self._select_model(url, default_model=default_model, explicit=explicit_model)

                # Start analysis with automatic polling
                # For bytes, pass directly as second parameter; for URL, use AnalyzeDocumentRequest
                if document_bytes:
                    # Pass bytes directly to the SDK (v1/v2 pattern)
                    logger.info(f"⏳ Starting Document Intelligence analysis ({len(document_bytes)} bytes)...")
                    poller = await client.begin_analyze_document(
                        selected_model,
                        io.BytesIO(document_bytes),
                        output_content_format=DocumentContentFormat.MARKDOWN,
                    )
                else:
                    # Fallback to URL source (for public URLs or URLs with SAS tokens)
                    logger.info(f"⏳ Starting Document Intelligence analysis (URL source, model={selected_model})...")
                    poller = await client.begin_analyze_document(
                        selected_model,
                        AnalyzeDocumentRequest(url_source=url),
                        output_content_format=DocumentContentFormat.MARKDOWN,
                    )

                # Wait for completion with timeout (SDK handles polling automatically)
                # Azure DI typically takes 2-10 seconds per document
                try:
                    result: AnalyzeResult = await asyncio.wait_for(
                        poller.result(), 
                        timeout=60  # 60 seconds max per document
                    )
                    logger.info(f"✅ Document Intelligence analysis completed for {url[:80]}")
                except asyncio.TimeoutError:
                    logger.error(f"❌ Document Intelligence analysis timed out after 60s for {url[:80]}")
                    raise TimeoutError(f"Document Intelligence analysis timed out for {url}")

                if not result.pages:
                    logger.warning(f"No pages extracted from {url}")
                    return (url, [], None)

                # Log Document Intelligence confidence scores
                if result.paragraphs:
                    confidences = [p.confidence for p in result.paragraphs if hasattr(p, 'confidence') and p.confidence is not None]
                    if confidences:
                        avg_confidence = sum(confidences) / len(confidences)
                        min_confidence = min(confidences)
                        logger.info(f"📊 DI Confidence: avg={avg_confidence:.3f}, min={min_confidence:.3f}, samples={len(confidences)}")

                documents: List[Document] = []
                
                # Create one document per page (better for large docs)
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

                    # Create Document with structured table metadata for schema-aware extraction
                    # The 'tables' metadata enables direct field mapping without LLM parsing
                    logger.info(f"📄 Extracted page {page_num}: {len(markdown)} chars, {len(page_paragraphs)} paragraphs, {len(page_tables)} tables")
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
            logger.info(f"📦 Batch processing {len(urls)} documents with 60s timeout")
            
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
                try:
                    results = await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=60  # 60s for entire batch
                    )
                except asyncio.TimeoutError:
                    logger.error("❌ Batch timeout after 60s")
                    if fail_fast:
                        raise RuntimeError("Batch processing timeout")
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
