"""
CU Standard Ingestion Service

Calls Azure Content Understanding to extract structured Documents with layout metadata
optimized for PropertyGraphIndex entity extraction.

Returns LlamaIndex Documents with:
- Clean markdown text (proper headings from paragraph roles)
- Section hierarchy (from title/sectionHeading roles)
- Table structure metadata (critical for entity-relationship extraction)
- Page numbers (for context)

Uses managed identity (DefaultAzureCredential) and API version 2025-11-01.
"""

import os

from typing import Any, Dict, List, Union
import logging

import httpx
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from llama_index.core import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class CUStandardIngestionService:
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
                            metadata={"group_id": group_id, "source": "cu-standard", "url": url}
                        ))
                        continue
                    
                    # Process each page as a Document
                    for page in pages:
                        page_num = page.get("pageNumber", 1)
                        
                        # Build markdown text
                        markdown = self._build_markdown_from_page(page)
                        
                        # Debug first page
                        if len(documents) == 0:
                            print(f"[DEBUG] First page keys: {list(page.keys())}")
                            print(f"[DEBUG] Paragraphs count: {len(page.get('paragraphs', []))}")
                            print(f"[DEBUG] Tables count: {len(page.get('tables', []))}")
                            print(f"[DEBUG] Markdown length: {len(markdown)}")
                            print(f"[DEBUG] Markdown preview: {markdown[:200]}")
                        
                        # Extract metadata
                        section_path = self._build_section_path(page.get("paragraphs", []))
                        
                        tables_metadata = [
                            self._extract_table_metadata(t)
                            for t in page.get("tables", [])
                        ]
                        
                        # Create Document with rich metadata
                        doc = Document(
                            text=markdown,
                            metadata={
                                "page_number": page_num,
                                "section_path": section_path,
                                "tables": tables_metadata,
                                "group_id": group_id,
                                "source": "cu-standard",
                                "url": url
                            }
                        )
                        documents.append(doc)
        
        logger.info(f"Extracted {len(documents)} documents for group {group_id}")
        return documents
