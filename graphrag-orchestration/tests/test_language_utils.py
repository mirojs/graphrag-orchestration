"""Unit tests for language utilities.

Tests multilingual support for entity canonicalization and text processing.
"""

import pytest
from app.hybrid.utils.language import (
    is_cjk,
    is_rtl,
    detect_cjk_from_text,
    normalize_text,
    canonical_key_for_entity,
    get_sentence_delimiters,
    estimate_tokens_cjk,
    get_dominant_language,
)


class TestIsCJK:
    """Tests for is_cjk() function."""
    
    def test_chinese_simplified(self):
        assert is_cjk("zh-Hans") is True
        assert is_cjk("zh-CN") is True
        assert is_cjk("zh") is True
    
    def test_chinese_traditional(self):
        assert is_cjk("zh-Hant") is True
        assert is_cjk("zh-TW") is True
    
    def test_japanese(self):
        assert is_cjk("ja") is True
        assert is_cjk("ja-JP") is True
    
    def test_korean(self):
        assert is_cjk("ko") is True
        assert is_cjk("ko-KR") is True
    
    def test_non_cjk(self):
        assert is_cjk("en") is False
        assert is_cjk("de") is False
        assert is_cjk("fr") is False
        assert is_cjk("es") is False
    
    def test_edge_cases(self):
        assert is_cjk(None) is False
        assert is_cjk("") is False
        assert is_cjk("ZH-HANS") is True  # Case insensitive
        assert is_cjk("JA") is True


class TestIsRTL:
    """Tests for is_rtl() function."""
    
    def test_rtl_languages(self):
        assert is_rtl("ar") is True
        assert is_rtl("he") is True
        assert is_rtl("fa") is True
        assert is_rtl("ur") is True
    
    def test_non_rtl(self):
        assert is_rtl("en") is False
        assert is_rtl("zh") is False
        assert is_rtl(None) is False


class TestDetectCJKFromText:
    """Tests for detect_cjk_from_text() function."""
    
    def test_pure_chinese(self):
        assert detect_cjk_from_text("华为技术有限公司") is True
    
    def test_pure_japanese(self):
        assert detect_cjk_from_text("株式会社トヨタ自動車") is True
    
    def test_pure_korean(self):
        assert detect_cjk_from_text("삼성전자주식회사") is True
    
    def test_mixed_cjk_english(self):
        # Chinese with English contract number
        assert detect_cjk_from_text("合同编号 CONTRACT-2024-001 签署日期") is True
    
    def test_pure_english(self):
        assert detect_cjk_from_text("Microsoft Corporation") is False
    
    def test_low_cjk_ratio(self):
        # Less than 20% CJK
        long_english = "This is a very long English sentence with just 中 one character"
        assert detect_cjk_from_text(long_english) is False
    
    def test_empty_text(self):
        assert detect_cjk_from_text("") is False
        assert detect_cjk_from_text("   ") is False


class TestNormalizeText:
    """Tests for normalize_text() function."""
    
    def test_fullwidth_to_halfwidth(self):
        # Full-width ASCII should convert to half-width
        assert normalize_text("Ｈｅｌｌｏ") == "Hello"
        assert normalize_text("１２３４５") == "12345"
    
    def test_cjk_preserved(self):
        # CJK characters should be preserved
        assert normalize_text("华为技术有限公司") == "华为技术有限公司"
    
    def test_mixed_content(self):
        # Mixed CJK + full-width ASCII
        result = normalize_text("合同编号：ＣＯＮＴ-001")
        assert "合同编号" in result
        assert "CONT" in result
    
    def test_nbsp_to_space(self):
        assert normalize_text("hello\u00a0world") == "hello world"
    
    def test_multiple_spaces(self):
        assert normalize_text("hello    world") == "hello world"
    
    def test_empty(self):
        assert normalize_text("") == ""
        assert normalize_text(None) == ""


class TestCanonicalKeyForEntity:
    """Tests for canonical_key_for_entity() function - CRITICAL for CJK support."""
    
    # --- Latin script tests (existing behavior preserved) ---
    
    def test_english_company(self):
        assert canonical_key_for_entity("Microsoft Corp.") == "microsoft corp"
        assert canonical_key_for_entity("Apple Inc.") == "apple inc"
    
    def test_english_with_punctuation(self):
        assert canonical_key_for_entity("AT&T") == "at&t"
        assert canonical_key_for_entity("Johnson & Johnson") == "johnson & johnson"
    
    def test_english_preserves_numbers(self):
        assert canonical_key_for_entity("Room 101") == "room 101"
    
    # --- CJK tests (NEW behavior) ---
    
    def test_chinese_company_with_locale(self):
        # With explicit locale hint
        result = canonical_key_for_entity("华为技术有限公司", locale="zh-Hans")
        assert "华为" in result
        assert "技术" in result
        assert "公司" in result
    
    def test_chinese_company_auto_detect(self):
        # Without locale hint - auto-detects CJK
        result = canonical_key_for_entity("华为技术有限公司")
        assert "华为" in result
        assert "技术" in result
    
    def test_japanese_company(self):
        result = canonical_key_for_entity("株式会社トヨタ自動車", locale="ja")
        assert "株式会社" in result
        assert "トヨタ" in result
    
    def test_korean_company(self):
        result = canonical_key_for_entity("삼성전자주식회사", locale="ko")
        assert "삼성" in result
    
    def test_mixed_cjk_english(self):
        # Contract with mixed languages - more CJK than English
        result = canonical_key_for_entity("合同编号 CONTRACT", locale="zh-Hans")
        assert "合同" in result
        assert "contract" in result.lower()
    
    def test_mixed_below_threshold_without_locale(self):
        # When CJK is below 20% threshold AND no locale hint, uses Latin rules
        # This is expected behavior - pass locale for accurate detection
        result = canonical_key_for_entity("合同 CONTRACT-2024-001")
        # Without locale hint, might not detect as CJK
        assert result != ""  # At minimum, not empty
    
    def test_cjk_not_emptied(self):
        # The OLD bug: CJK entities would become empty strings!
        # This test ensures that NEVER happens again
        chinese = canonical_key_for_entity("北京")
        japanese = canonical_key_for_entity("東京")
        korean = canonical_key_for_entity("서울")
        
        assert chinese != "", "Chinese entity should NOT become empty!"
        assert japanese != "", "Japanese entity should NOT become empty!"
        assert korean != "", "Korean entity should NOT become empty!"
    
    # --- Edge cases ---
    
    def test_empty_string(self):
        assert canonical_key_for_entity("") == ""
        assert canonical_key_for_entity("   ") == ""
    
    def test_none(self):
        assert canonical_key_for_entity(None) == ""


class TestGetSentenceDelimiters:
    """Tests for get_sentence_delimiters() function."""
    
    def test_english(self):
        delimiters = get_sentence_delimiters("en")
        assert "." in delimiters
        assert "!" in delimiters
        assert "?" in delimiters
        assert "。" not in delimiters
    
    def test_chinese(self):
        delimiters = get_sentence_delimiters("zh-Hans")
        assert "。" in delimiters  # Chinese period
        assert "！" in delimiters  # Chinese exclamation
        assert "？" in delimiters  # Chinese question
        assert "." in delimiters   # Also include ASCII for mixed text
    
    def test_japanese(self):
        delimiters = get_sentence_delimiters("ja")
        assert "。" in delimiters


class TestEstimateTokensCJK:
    """Tests for estimate_tokens_cjk() function."""
    
    def test_chinese_text(self):
        text = "华为技术有限公司"  # 8 characters
        tokens = estimate_tokens_cjk(text)
        # ~1.5 tokens per CJK char = ~12 tokens
        assert 8 <= tokens <= 16
    
    def test_empty_text(self):
        assert estimate_tokens_cjk("") == 0
        assert estimate_tokens_cjk("   ") == 0
    
    def test_mixed_content(self):
        text = "合同 CONTRACT-2024"  # 2 CJK + ~14 ASCII chars
        tokens = estimate_tokens_cjk(text)
        assert tokens > 0


class TestGetDominantLanguage:
    """Tests for get_dominant_language() function."""
    
    def test_single_language(self):
        languages = [
            {"locale": "zh-Hans", "confidence": 0.95, "spans": [{"offset": 0, "length": 100}]}
        ]
        assert get_dominant_language(languages, 100) == "zh-Hans"
    
    def test_multiple_languages(self):
        languages = [
            {"locale": "zh-Hans", "confidence": 0.95, "spans": [{"offset": 0, "length": 80}]},
            {"locale": "en", "confidence": 0.98, "spans": [{"offset": 80, "length": 20}]}
        ]
        # Chinese has more coverage (80 vs 20)
        assert get_dominant_language(languages, 100) == "zh-Hans"
    
    def test_empty_languages(self):
        assert get_dominant_language([], 100) is None
        assert get_dominant_language(None, 100) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
