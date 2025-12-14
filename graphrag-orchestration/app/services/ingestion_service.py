"""
Ingestion Service

Normalizes various document inputs and extracts text when needed.

Supports:
- Raw text strings
- Dicts with {"text": str, "metadata": {...}}
- URLs (http/https) pointing to text or PDF content

For PDFs, uses a lightweight local parser (pypdf).
"""

from typing import Any, Dict, List, Union
import logging
import io

import requests

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self) -> None:
        try:
            import pypdf  # noqa: F401
            self._pdf_available = True
        except Exception:
            self._pdf_available = False

    def _extract_pdf_text(self, content: bytes) -> str:
        if not self._pdf_available:
            raise RuntimeError("PDF parser not available (pypdf not installed)")
        from pypdf import PdfReader
        text_parts: List[str] = []
        with io.BytesIO(content) as bio:
            reader = PdfReader(bio)
            for page in reader.pages:
                try:
                    text_parts.append(page.extract_text() or "")
                except Exception:
                    # best effort per page
                    continue
        return "\n".join([t for t in text_parts if t])

    def _fetch_url_text(self, url: str) -> str:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()

        # If PDF
        if ("application/pdf" in ctype) or url.lower().endswith(".pdf"):
            logger.info("ingestion_pdf_detected", url=url)
            return self._extract_pdf_text(resp.content)

        # Textual content types
        if ctype.startswith("text/") or "application/json" in ctype or "application/xml" in ctype:
            return resp.text

        # Fallback: try decode as UTF-8
        try:
            return resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return resp.text  # let requests guess

    def preprocess(self, input_items: List[Union[str, Dict[str, Any]]]):
        """Return LlamaIndex Document objects from mixed inputs."""
        from llama_index.core import Document

        docs: List[Document] = []
        for item in input_items:
            if isinstance(item, dict):
                if "text" in item:
                    docs.append(Document(text=item["text"], metadata=item.get("metadata") or {}))
                    continue
                if "url" in item and isinstance(item["url"], str):
                    url = item["url"]
                    text = self._fetch_url_text(url)
                    meta = item.get("metadata") or {}
                    if "source_url" not in meta:
                        meta = {**meta, "source_url": url}
                    docs.append(Document(text=text, metadata=meta))
                    continue
                raise ValueError("Document dict must include 'text' or 'url'.")

            if isinstance(item, str):
                s = item.strip()
                if s.startswith("http://") or s.startswith("https://"):
                    text = self._fetch_url_text(s)
                    docs.append(Document(text=text, metadata={"source_url": s}))
                else:
                    docs.append(Document(text=s))
                continue

            raise ValueError("Unsupported document item type. Use string or {text|url}.")

        return docs
