"""
Deterministic extraction service for audit/compliance use cases.

Provides simple regex-based sentence extraction and optional rephrasing
with temperature=0 LLM for fully repeatable audit summaries.
"""

from typing import Optional, Any, Dict, List
import logging
import re

logger = logging.getLogger(__name__)


class ExtractionService:
    """
    Deterministic sentence extraction and rephrasing for audit compliance.
    
    Two modes:
    - audit: Extract sentences with citations (no LLM)
    - client: Extract + rephrase with deterministic LLM
    """

    def __init__(self, llm: Optional[Any] = None):
        """
        Initialize extraction service.
        
        Args:
            llm: Optional LLM for rephrasing (must support temperature parameter)
        """
        self.llm = llm

    def extract_sentences(
        self,
        text: str,
        top_k: int = 5,
        min_length: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Extract top-K sentences from text using simple regex-based ranking.
        Fully deterministic (no randomness, no external dependencies).
        
        Algorithm:
        1. Split on sentence boundaries (., !, ?)
        2. Filter by minimum length
        3. Score by: position (prefer first) + length (penalize very long)
        4. Return top-K deterministically
        
        Args:
            text: Input text to extract from
            top_k: Number of top sentences to extract
            min_length: Minimum sentence length (chars)
            
        Returns:
            List of dicts with keys:
            - text: Extracted sentence
            - rank_score: Relevance score (0.0-1.0)
            - sentence_idx: Position in original text
        """
        if not text or not text.strip():
            return []

        # Split on sentence boundaries
        # Regex: match . ! ? followed by whitespace or end of string
        raw_sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        
        sentences = []
        for i, sent in enumerate(raw_sentences):
            sent = sent.strip()
            
            # Filter by min length
            if len(sent) < min_length:
                continue
            
            # Calculate rank score (deterministic, order-based)
            # Prefer sentences that:
            # 1. Appear earlier (position decay)
            # 2. Are moderate length (not too long, not too short)
            position_score = 1.0 / (i + 1)  # Decay by position
            length_penalty = min(1.0, len(sent) / 100.0)  # Reward up to 100 chars, then cap
            rank = position_score * length_penalty
            
            sentences.append({
                "text": sent,
                "rank_score": float(rank),
                "sentence_idx": i,
            })
        
        # Sort by rank score descending, then by position (stable sort)
        sentences.sort(key=lambda x: (-x["rank_score"], x["sentence_idx"]))
        
        return sentences[:top_k]

    def extract_from_communities(
        self,
        communities: List[Dict[str, Any]],
        top_k: int = 5,
        min_length: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        Extract top sentences from a list of community summaries.
        
        Args:
            communities: List of dicts with 'summary' and 'id' keys
            top_k: Number of sentences to extract total
            min_length: Minimum sentence length
            
        Returns:
            List of extracted sentences with source attribution
        """
        all_sentences = []

        for community in communities:
            summary = community.get("summary", "").strip()
            community_id = community.get("id")

            if not summary:
                continue

            # Extract from this community
            sentences = self.extract_sentences(summary, top_k=top_k, min_length=min_length)

            for sent in sentences:
                sent["source_community_id"] = community_id
                sent["source_community_title"] = community.get("title", "")
                all_sentences.append(sent)

        # Sort by rank_score and return top_k
        all_sentences.sort(key=lambda x: x["rank_score"], reverse=True)
        return all_sentences[:top_k]

    def rephrase_sentences(
        self,
        sentences: List[str],
        query: str,
        temperature: float = 0.0,
        top_p: float = 1.0,
    ) -> str:
        """
        Rephrase extracted sentences into a coherent paragraph.
        Uses temperature=0 for deterministic output.
        
        Args:
            sentences: List of extracted sentences
            query: Original query (for context)
            temperature: LLM temperature (0.0 for determinism)
            top_p: LLM top_p (1.0 for no filtering)
            
        Returns:
            Rephrased paragraph (deterministic)
        """
        if not self.llm:
            # Fallback: just join with spaces
            return " ".join(sentences)

        if not sentences:
            return ""

        combined = " ".join(sentences)

        prompt = f"""Rephrase the following extracted sentences into a single, coherent paragraph.
- Do NOT add new information
- Only improve readability, grammar, and flow
- Preserve all facts and figures exactly as written

Extracted sentences:
{combined}

Question: {query}

Rephrased paragraph:"""

        try:
            response = self.llm.complete(
                prompt,
                temperature=temperature,
                top_p=top_p,
            )
            return (response.text or "").strip()
        except Exception as e:
            logger.warning(f"Rephrasing failed: {e}, returning joined sentences")
            return combined

    def audit_summary(
        self,
        communities: List[Dict[str, Any]],
        query: str,
        top_k: int = 5,
        include_rephrased: bool = False,
    ) -> Dict[str, Any]:
        """
        Generate audit-grade summary with deterministic extraction.
        
        Args:
            communities: List of community summaries
            query: Original query
            top_k: Number of sentences to extract
            include_rephrased: If True, also generate rephrased narrative
            
        Returns:
            Dict with:
            - extracted_sentences: List of sentence dicts
            - audit_summary: Plain text of extracted sentences
            - rephrased_narrative: (Optional) Rephrased version
            - processing_deterministic: Always True
        """
        # Extract sentences
        extracted = self.extract_from_communities(communities, top_k=top_k)

        # Build plain text summary
        audit_text = " ".join([s["text"] for s in extracted])

        result = {
            "extracted_sentences": extracted,
            "audit_summary": audit_text,
            "processing_deterministic": True,
        }

        # Optional: rephrase for readability
        if include_rephrased and self.llm:
            sentences = [s["text"] for s in extracted]
            rephrased = self.rephrase_sentences(sentences, query)
            result["rephrased_narrative"] = rephrased

        return result
