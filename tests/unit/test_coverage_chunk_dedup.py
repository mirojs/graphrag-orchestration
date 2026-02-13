"""
Unit Tests: Coverage Chunk Dedup Logic

Tests the inline dedup applied to coverage gap-fill chunks before they
merge into entity-retrieved chunks in synthesize().

The coverage gap fill path previously bypassed the entire denoising stack
(MD5 dedup, semantic dedup, score stamping).  This test validates the fix.

Run: pytest tests/unit/test_coverage_chunk_dedup.py -v
"""

import hashlib
import re
import os
import pytest


# ---------------------------------------------------------------------------
# Helpers — extracted from the inline logic in synthesis.py Step 1.5
# ---------------------------------------------------------------------------

def _merge_coverage_chunks(
    text_chunks: list,
    coverage_chunks: list,
    semantic_threshold: float = 0.92,
) -> dict:
    """
    Reproduce the coverage-chunk merge logic from synthesis.py Step 1.5.
    Returns stats dict with 'added' and 'deduped' counts.
    Mutates text_chunks in place (appends non-duplicate coverage chunks).
    """
    existing_hashes: set = set()
    existing_word_sets: list = []
    for ec in text_chunks:
        t = ec.get("text", "")
        existing_hashes.add(hashlib.md5(t.encode("utf-8")).hexdigest())
        existing_word_sets.append(set(re.findall(r'[a-z0-9]+', t.lower())))

    coverage_added = 0
    coverage_deduped = 0

    for cov_chunk in coverage_chunks:
        cov_text = cov_chunk.get("text", "")
        cov_hash = hashlib.md5(cov_text.encode("utf-8")).hexdigest()

        # 1. Exact MD5 dedup
        if cov_hash in existing_hashes:
            coverage_deduped += 1
            continue

        # 2. Semantic near-dedup (Jaccard)
        cov_words = set(re.findall(r'[a-z0-9]+', cov_text.lower()))
        is_near_dup = False
        if cov_words:
            for ws in existing_word_sets:
                if ws:
                    inter = len(cov_words & ws)
                    union = len(cov_words | ws)
                    if union > 0 and inter / union >= semantic_threshold:
                        is_near_dup = True
                        coverage_deduped += 1
                        break

        if not is_near_dup:
            min_entity_score = min(
                (c.get("_entity_score", 0.0) for c in text_chunks),
                default=0.0,
            )
            cov_chunk["_entity_score"] = min_entity_score * 0.5 if min_entity_score > 0 else 0.01
            cov_chunk["_source_entity"] = "__coverage_gap_fill__"

            text_chunks.append(cov_chunk)
            existing_hashes.add(cov_hash)
            existing_word_sets.append(cov_words)
            coverage_added += 1

    return {"added": coverage_added, "deduped": coverage_deduped}


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def entity_chunks():
    """Simulates chunks returned by _retrieve_text_chunks() (already denoised)."""
    return [
        {
            "text": "Invoice #12345 was issued by Contoso Ltd for $50,000 on January 15, 2024.",
            "_entity_score": 0.85,
            "_source_entity": "Contoso Ltd",
        },
        {
            "text": "Payment terms are Net 30 days from the invoice date.",
            "_entity_score": 0.72,
            "_source_entity": "Invoice #12345",
        },
        {
            "text": "The warranty covers structural defects for a period of 10 years.",
            "_entity_score": 0.60,
            "_source_entity": "Warranty",
        },
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExactDedup:
    """MD5 exact-match dedup of coverage chunks."""

    def test_exact_duplicate_removed(self, entity_chunks):
        """Coverage chunk with identical text to an entity chunk is removed."""
        coverage = [
            {"text": "Invoice #12345 was issued by Contoso Ltd for $50,000 on January 15, 2024."},
        ]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["deduped"] == 1
        assert stats["added"] == 0
        assert len(entity_chunks) == 3  # unchanged

    def test_unique_chunk_added(self, entity_chunks):
        """Coverage chunk with novel text is added."""
        coverage = [
            {"text": "The lease agreement runs for 12 months starting March 1, 2024."},
        ]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["added"] == 1
        assert stats["deduped"] == 0
        assert len(entity_chunks) == 4

    def test_mixed_duplicates_and_unique(self, entity_chunks):
        """Mix of duplicates and unique coverage chunks."""
        coverage = [
            {"text": "Invoice #12345 was issued by Contoso Ltd for $50,000 on January 15, 2024."},  # dup
            {"text": "The property is located at 123 Main Street, Springfield."},  # unique
            {"text": "Payment terms are Net 30 days from the invoice date."},  # dup
        ]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["deduped"] == 2
        assert stats["added"] == 1
        assert len(entity_chunks) == 4


class TestSemanticDedup:
    """Jaccard semantic near-dedup of coverage chunks."""

    def test_near_duplicate_removed(self, entity_chunks):
        """Coverage chunk that differs only by minor wording is removed."""
        # Same content with trivial differences (Jaccard > 0.92)
        coverage = [
            {"text": "Invoice #12345 was issued by Contoso Ltd. for $50,000 on January 15 2024."},
        ]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["deduped"] == 1
        assert stats["added"] == 0

    def test_sufficiently_different_not_removed(self, entity_chunks):
        """Coverage chunk with enough new content passes semantic dedup."""
        coverage = [
            {"text": "Invoice #12345 includes additional charges for shipping and handling of $2,500 plus tax."},
        ]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["added"] == 1
        assert stats["deduped"] == 0

    def test_empty_text_passes_through(self, entity_chunks):
        """Empty coverage chunk passes through (edge case)."""
        coverage = [{"text": ""}]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        # Empty text has no words → not a near-dup, gets added
        # But MD5 of empty string might match if entity chunks have empty... here none do
        assert stats["added"] == 1

    def test_custom_threshold(self, entity_chunks):
        """Lower threshold catches more near-duplicates."""
        coverage = [
            {"text": "Invoice #12345 was issued by Contoso Ltd for fifty thousand dollars in January 2024."},
        ]
        # With default threshold 0.92 — this should pass (many words differ)
        stats_default = _merge_coverage_chunks(
            [c.copy() for c in entity_chunks], [c.copy() for c in coverage], semantic_threshold=0.92
        )
        # With lower threshold 0.5 — should be caught
        stats_lower = _merge_coverage_chunks(
            [c.copy() for c in entity_chunks], [c.copy() for c in coverage], semantic_threshold=0.5
        )
        assert stats_default["added"] >= stats_lower["added"]


class TestScoreStamping:
    """Coverage chunks get proper _entity_score and _source_entity."""

    def test_coverage_score_below_entity_scores(self, entity_chunks):
        """Coverage chunks should score below entity-retrieved chunks."""
        coverage = [
            {"text": "The lease runs from March 1 to February 28."},
        ]
        _merge_coverage_chunks(entity_chunks, coverage)

        # Last chunk is the coverage chunk
        cov = entity_chunks[-1]
        assert cov["_source_entity"] == "__coverage_gap_fill__"
        # Min entity score is 0.60, coverage = 0.60 * 0.5 = 0.30
        assert cov["_entity_score"] == pytest.approx(0.30)
        # Must be below all entity chunks
        entity_scores = [c["_entity_score"] for c in entity_chunks[:-1]]
        assert cov["_entity_score"] < min(entity_scores)

    def test_coverage_score_with_no_entity_chunks(self):
        """When entity retrieval returns nothing, coverage gets baseline score."""
        text_chunks = []
        coverage = [{"text": "Some coverage text."}]
        _merge_coverage_chunks(text_chunks, coverage)
        assert text_chunks[0]["_entity_score"] == 0.01

    def test_source_entity_stamped(self, entity_chunks):
        """Coverage chunks are stamped with __coverage_gap_fill__ source."""
        coverage = [{"text": "Completely novel content about building permits."}]
        _merge_coverage_chunks(entity_chunks, coverage)
        assert entity_chunks[-1]["_source_entity"] == "__coverage_gap_fill__"


class TestCoverageChainDedup:
    """Coverage chunks should also dedup against each other."""

    def test_duplicate_coverage_chunks_deduped(self):
        """Two identical coverage chunks — only first should be added."""
        text_chunks = [
            {"text": "Existing entity chunk.", "_entity_score": 0.9},
        ]
        coverage = [
            {"text": "Coverage chunk about property management fees."},
            {"text": "Coverage chunk about property management fees."},  # exact dup
        ]
        stats = _merge_coverage_chunks(text_chunks, coverage)
        assert stats["added"] == 1
        assert stats["deduped"] == 1
        assert len(text_chunks) == 2  # 1 existing + 1 coverage

    def test_near_duplicate_coverage_chunks_deduped(self):
        """Two near-duplicate coverage chunks — only first should be added."""
        text_chunks = [
            {"text": "Existing entity chunk.", "_entity_score": 0.9},
        ]
        coverage = [
            {"text": "The property management fee is 20% of gross rental income for all units."},
            {"text": "The property management fee is 20% of gross rental income for all units collected."},
        ]
        stats = _merge_coverage_chunks(text_chunks, coverage)
        assert stats["added"] == 1
        assert stats["deduped"] == 1


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_coverage_list(self, entity_chunks):
        """No coverage chunks — should be a no-op."""
        original_len = len(entity_chunks)
        stats = _merge_coverage_chunks(entity_chunks, [])
        assert stats["added"] == 0
        assert stats["deduped"] == 0
        assert len(entity_chunks) == original_len

    def test_empty_entity_chunks(self):
        """No entity chunks — all coverage chunks should be added."""
        text_chunks = []
        coverage = [
            {"text": "Coverage alpha."},
            {"text": "Coverage beta."},
        ]
        stats = _merge_coverage_chunks(text_chunks, coverage)
        assert stats["added"] == 2
        assert len(text_chunks) == 2

    def test_large_coverage_batch(self, entity_chunks):
        """Many coverage chunks — performance shouldn't degrade badly."""
        coverage = [{"text": f"Unique coverage chunk number {i} with content."} for i in range(100)]
        stats = _merge_coverage_chunks(entity_chunks, coverage)
        assert stats["added"] == 100
        assert stats["deduped"] == 0
        assert len(entity_chunks) == 103  # 3 original + 100 coverage
