"""Unit tests for chunk noise filters."""

import pytest
from src.worker.hybrid_v2.pipeline.chunk_filters import (
    compute_noise_penalty,
    apply_noise_filters,
    _form_label_penalty,
    _bare_heading_penalty,
    _min_content_penalty,
    FORM_LABEL_PENALTY,
    BARE_HEADING_PENALTY,
    LOW_CONTENT_PENALTY,
)


# =====================================================================
# Form-label filter
# =====================================================================

class TestFormLabelFilter:
    """Test detection of form-label dominated chunks."""

    def test_pure_form_labels(self):
        """Chunks that are entirely form fields should be penalised."""
        text = (
            "Pumper's Name:____________________\n"
            "Date:____________________\n"
            "Signature:____________________\n"
            "Phone Number:____________________\n"
        )
        assert _form_label_penalty(text) == FORM_LABEL_PENALTY

    def test_mixed_content_below_threshold(self):
        """Chunks with some form labels but mostly content should pass."""
        text = (
            "The contractor agrees to perform maintenance services quarterly.\n"
            "Services include inspection, cleaning, and minor repairs.\n"
            "The fee for each visit is $250.00 payable within 30 days.\n"
            "Contractor Name:____________________\n"
        )
        assert _form_label_penalty(text) == 1.0

    def test_empty_value_labels(self):
        """Labels with empty values (no underscores) should match."""
        text = (
            "Name:\n"
            "Date:\n"
            "Address:\n"
            "Phone:\n"
        )
        assert _form_label_penalty(text) == FORM_LABEL_PENALTY

    def test_separator_lines(self):
        """Lines of underscores/dashes should match form-label pattern."""
        text = (
            "____________________________\n"
            "----------------------------\n"
            "............................\n"
        )
        assert _form_label_penalty(text) == FORM_LABEL_PENALTY

    def test_normal_content(self):
        """Normal text should not be penalised."""
        text = (
            "Section 4: Customer Default\n"
            "If the customer fails to make payment within 30 days of the due date,\n"
            "the contractor may suspend services and charge a late fee of 1.5% per month.\n"
            "The contractor reserves the right to terminate this agreement upon 60 days notice.\n"
        )
        assert _form_label_penalty(text) == 1.0

    def test_empty_text(self):
        """Empty text should trigger bare-heading level penalty."""
        assert _form_label_penalty("") == BARE_HEADING_PENALTY


# =====================================================================
# Bare heading filter
# =====================================================================

class TestBareHeadingFilter:
    """Test detection of heading-only chunks with no substantive content."""

    def test_section_heading_only(self):
        """A bare section heading should be penalised."""
        text = "4. Customer Default"
        assert _bare_heading_penalty(text) == BARE_HEADING_PENALTY

    def test_short_heading(self):
        """Very short headings should be penalised."""
        text = "## Overview"
        assert _bare_heading_penalty(text) == BARE_HEADING_PENALTY

    def test_heading_with_underscores(self):
        """Heading followed by separator should be penalised."""
        text = "Section Title\n_______________"
        assert _bare_heading_penalty(text) == BARE_HEADING_PENALTY

    def test_substantive_content(self):
        """Chunks with real content should not be penalised."""
        text = "The total invoice amount is $29,900.00 payable within 30 days."
        assert _bare_heading_penalty(text) == 1.0

    def test_borderline_length(self):
        """Text just above the threshold should pass."""
        # 20 chars of letters after stripping
        text = "abcdefghijklmnopqrstu"  # 21 chars
        assert _bare_heading_penalty(text) == 1.0

    def test_just_below_threshold(self):
        """Text just below the threshold should be penalised."""
        text = "abcdefghij"  # 10 chars
        assert _bare_heading_penalty(text) == BARE_HEADING_PENALTY


# =====================================================================
# Minimum content filter
# =====================================================================

class TestMinContentFilter:
    """Test minimum token threshold."""

    def test_short_chunk(self):
        """Chunks below 50 estimated tokens should be penalised."""
        # 50 tokens ≈ 200 chars. Use 100 chars → ~25 tokens
        text = "Short text that is not enough to be useful for analysis purposes."
        assert _min_content_penalty(text) == LOW_CONTENT_PENALTY

    def test_adequate_chunk(self):
        """Chunks above 50 estimated tokens should pass."""
        # ~300 chars → ~75 tokens
        text = (
            "The contractor agrees to provide quarterly maintenance services for the "
            "holding tank system installed at the property. Services include inspection, "
            "cleaning, pumping, and minor repairs as needed. The fee for each visit shall "
            "be two hundred and fifty dollars payable within thirty days of service."
        )
        assert _min_content_penalty(text) == 1.0

    def test_empty(self):
        """Empty text should be penalised."""
        assert _min_content_penalty("") == LOW_CONTENT_PENALTY


# =====================================================================
# Composite penalty
# =====================================================================

class TestCompositeNoisePenalty:
    """Test the combined penalty multiplier."""

    def test_clean_chunk_no_penalty(self):
        """A normal chunk should have penalty = 1.0."""
        text = (
            "The total invoice amount is $29,900.00. Payment is due within 30 days "
            "of the invoice date. Late payments will be subject to a 1.5% monthly "
            "interest charge. Please remit payment to the address listed above."
        )
        assert compute_noise_penalty(text) == 1.0

    def test_form_label_chunk(self):
        """A form-label chunk should have a very low penalty (multiple filters stack)."""
        text = (
            "Name:____\n"
            "Date:____\n"
            "Sign:____\n"
        )
        penalty = compute_noise_penalty(text)
        assert penalty < 0.1  # Multiple filters compound

    def test_bare_heading(self):
        """A bare heading has bare_heading + min_content penalties stacked."""
        text = "4. Default"
        penalty = compute_noise_penalty(text)
        # bare_heading = 0.10, min_content = 0.20 → 0.02
        assert penalty < 0.05

    def test_penalty_in_range(self):
        """Penalty should always be in (0, 1]."""
        test_cases = [
            "",
            "x",
            "Hello world",
            "Name:____\nDate:____\n",
            "A" * 500,
        ]
        for text in test_cases:
            p = compute_noise_penalty(text)
            assert 0 < p <= 1.0, f"Penalty {p} out of range for text: {text!r}"


# =====================================================================
# apply_noise_filters integration
# =====================================================================

class TestApplyNoiseFilters:
    """Test the in-place filter application on chunk lists."""

    def test_applies_penalty_to_noisy_chunks(self):
        """Noisy chunks should have their score reduced."""
        chunks = [
            {"text": "Name:____\nDate:____\nSign:____\n", "_entity_score": 1.0},
            {
                "text": (
                    "The total invoice amount is $29,900.00 and payment terms are 30 days net. "
                    "Late payments are subject to a 1.5% monthly interest charge on the outstanding "
                    "balance. Please remit payment to the address shown on this invoice."
                ),
                "_entity_score": 0.8,
            },
        ]
        penalised = apply_noise_filters(chunks)
        
        assert penalised["total_penalised"] >= 1  # At least the form-label chunk
        assert chunks[0]["_entity_score"] < 1.0  # Penalised
        assert chunks[0]["_noise_penalty"] < 1.0
        assert chunks[0]["_noise_filters_hit"]  # Should have filter names
        assert chunks[1]["_noise_penalty"] == 1.0  # Clean chunk
        assert chunks[1]["_noise_filters_hit"] == []  # No filters fired

    def test_preserves_clean_chunks(self):
        """Clean chunks should keep their original score."""
        chunks = [
            {
                "text": (
                    "The contractor shall provide maintenance services quarterly. "
                    "The fee for each visit is $250.00 payable within 30 days of service completion. "
                    "Services include inspection, cleaning, pumping, and minor repairs as needed."
                ),
                "_entity_score": 0.9,
            },
        ]
        apply_noise_filters(chunks)
        assert chunks[0]["_entity_score"] == 0.9
        assert chunks[0]["_noise_penalty"] == 1.0

    def test_empty_list(self):
        """Empty list should work without error."""
        result = apply_noise_filters([])
        assert result["total_penalised"] == 0
        assert result["form_label"] == 0

    def test_reranking_effect(self):
        """After filtering, a previously lower-scored clean chunk should
        outrank a previously higher-scored noisy chunk."""
        chunks = [
            {"text": "Name:____\nDate:____\nSign:____\n", "_entity_score": 1.0},
            {
                "text": (
                    "The total invoice amount is $29,900.00 payable within 30 days. "
                    "Late payments incur a 1.5% monthly interest charge on the outstanding balance."
                ),
                "_entity_score": 0.5,
            },
        ]
        apply_noise_filters(chunks)
        
        # Sort by penalised score (as synthesis.py does)
        ranked = sorted(chunks, key=lambda c: c["_entity_score"], reverse=True)
        assert "29,900.00" in ranked[0]["text"]  # Clean chunk should now rank first
