"""
Language utilities for multilingual document processing.

This module provides functions for:
- Language detection and classification (CJK, RTL, etc.)
- Language-specific text normalization
- Sentence boundary detection for different languages
- Token estimation for non-whitespace languages

Azure DI provides per-span language detection with locale codes like:
- "zh-Hans" (Simplified Chinese), "zh-Hant" (Traditional Chinese)
- "ja" (Japanese), "ko" (Korean)
- "en" (English), "de" (German), "fr" (French)
- etc.
"""

import re
import unicodedata
from typing import Optional

# CJK locale prefixes (Chinese, Japanese, Korean)
CJK_PREFIXES = ("zh", "ja", "ko")

# RTL (Right-to-Left) locale prefixes
RTL_PREFIXES = ("ar", "he", "fa", "ur", "yi")

# Non-Latin script locale prefixes (need character preservation in canonicalization)
# This includes CJK, RTL, Indic, Thai, and other scripts that would be destroyed by ASCII-only regex
NON_LATIN_PREFIXES = (
    "zh", "ja", "ko",           # CJK
    "ar", "he", "fa", "ur",    # RTL/Arabic
    "hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa",  # Indic
    "th",                        # Thai
    "el",                        # Greek
    "ru", "uk", "bg", "sr",    # Cyrillic
    "ka", "hy",                  # Georgian, Armenian
    "am", "ti",                  # Ethiopic
)

# Sentence delimiters by language category
CJK_SENTENCE_DELIMITERS = ["。", "！", "？", "．", "!", "?", "."]
DEFAULT_SENTENCE_DELIMITERS = [".", "!", "?"]


def is_cjk(locale: Optional[str]) -> bool:
    """
    Check if locale is CJK (Chinese, Japanese, Korean).
    
    Args:
        locale: ISO 639-1/BCP 47 locale code (e.g., "zh-Hans", "ja", "ko")
    
    Returns:
        True if the locale is CJK, False otherwise
    
    Examples:
        >>> is_cjk("zh-Hans")
        True
        >>> is_cjk("ja")
        True
        >>> is_cjk("en")
        False
        >>> is_cjk(None)
        False
    """
    if not locale:
        return False
    locale_lower = locale.lower()
    return any(locale_lower.startswith(prefix) for prefix in CJK_PREFIXES)


def is_rtl(locale: Optional[str]) -> bool:
    """
    Check if locale is RTL (Right-to-Left) script.
    
    Args:
        locale: ISO 639-1/BCP 47 locale code (e.g., "ar", "he", "fa")
    
    Returns:
        True if the locale uses RTL script, False otherwise
    """
    if not locale:
        return False
    locale_lower = locale.lower()
    return any(locale_lower.startswith(prefix) for prefix in RTL_PREFIXES)


def detect_cjk_from_text(text: str) -> bool:
    """
    Heuristic fallback: detect if text contains significant CJK characters.
    
    Use this when locale metadata is unavailable.
    
    Args:
        text: Text to analyze
    
    Returns:
        True if >20% of characters are CJK
    """
    if not text:
        return False
    
    cjk_count = 0
    total_count = 0
    
    for char in text:
        if char.isspace():
            continue
        total_count += 1
        # Unicode ranges for CJK:
        # CJK Unified Ideographs: U+4E00 - U+9FFF
        # CJK Extension A: U+3400 - U+4DBF
        # Hiragana: U+3040 - U+309F
        # Katakana: U+30A0 - U+30FF
        # Hangul Syllables: U+AC00 - U+D7AF
        code = ord(char)
        if (0x4E00 <= code <= 0x9FFF or      # CJK Unified Ideographs
            0x3400 <= code <= 0x4DBF or      # CJK Extension A
            0x3040 <= code <= 0x309F or      # Hiragana
            0x30A0 <= code <= 0x30FF or      # Katakana
            0xAC00 <= code <= 0xD7AF):       # Hangul
            cjk_count += 1
    
    if total_count == 0:
        return False
    
    return (cjk_count / total_count) > 0.2


def detect_non_latin_from_text(text: str) -> bool:
    """
    Detect if text contains significant non-Latin characters.
    
    This is more inclusive than detect_cjk_from_text - it catches:
    - CJK (Chinese, Japanese, Korean)
    - Arabic, Hebrew, Persian
    - Indic scripts (Hindi, Bengali, Tamil, etc.)
    - Thai, Cyrillic, Greek, etc.
    
    Args:
        text: Text to analyze
    
    Returns:
        True if >20% of characters are non-Latin
    """
    if not text:
        return False
    
    non_latin_count = 0
    total_count = 0
    
    for char in text:
        if char.isspace():
            continue
        total_count += 1
        # Check if character is outside basic Latin + digits
        # Basic Latin: U+0000 - U+007F (ASCII)
        # We consider anything with letters outside A-Za-z as non-Latin
        if char.isalpha() and not char.isascii():
            non_latin_count += 1
    
    if total_count == 0:
        return False
    
    return (non_latin_count / total_count) > 0.2


def is_non_latin_locale(locale: Optional[str]) -> bool:
    """
    Check if locale uses a non-Latin script.
    
    Args:
        locale: ISO 639-1/BCP 47 locale code
    
    Returns:
        True if the locale uses non-Latin script
    """
    if not locale:
        return False
    locale_lower = locale.lower()
    return any(locale_lower.startswith(prefix) for prefix in NON_LATIN_PREFIXES)


def normalize_text(text: str, locale: Optional[str] = None) -> str:
    """
    Apply language-specific text normalization.
    
    Normalization includes:
    - NFKC Unicode normalization (合成 compatibility characters)
    - Full-width to half-width conversion for ASCII in CJK text
    - Whitespace normalization
    - Non-breaking space handling
    
    Args:
        text: Text to normalize
        locale: Optional locale hint for language-specific processing
    
    Returns:
        Normalized text
    
    Examples:
        >>> normalize_text("Ｈｅｌｌｏ　Ｗｏｒｌｄ")  # Full-width ASCII
        'Hello World'
        >>> normalize_text("合同编号：CONTRACT-001")  # Mixed CJK+ASCII
        '合同编号:CONTRACT-001'
    """
    if not text:
        return ""
    
    # Step 1: Unicode NFKC normalization
    # This handles:
    # - Full-width ASCII → half-width (Ａ → A)
    # - Compatibility characters (㈱ → (株))
    # - Composed forms (ﬁ → fi)
    normalized = unicodedata.normalize("NFKC", text)
    
    # Step 2: Replace non-breaking spaces with regular spaces
    normalized = normalized.replace("\u00a0", " ")
    
    # Step 3: Normalize whitespace (collapse multiple spaces)
    normalized = re.sub(r"\s+", " ", normalized)
    
    return normalized.strip()


def canonical_key_for_entity(name: str, locale: Optional[str] = None) -> str:
    """
    Generate a canonical key for entity matching.
    
    This function handles the critical difference between Latin and CJK scripts:
    - Latin: Lowercase, strip punctuation, normalize whitespace
    - CJK: Preserve characters, apply NFKC normalization, lowercase
    
    Args:
        name: Entity name to canonicalize
        locale: Optional locale hint (if None, auto-detect from text)
    
    Returns:
        Canonical key for entity matching
    
    Examples:
        >>> canonical_key_for_entity("Microsoft Corp.")
        'microsoft corp'
        >>> canonical_key_for_entity("株式会社トヨタ")
        '株式会社トヨタ'
        >>> canonical_key_for_entity("华为技术有限公司")
        '华为技术有限公司'
    """
    s = (name or "").strip()
    if not s:
        return ""
    
    # Apply Unicode normalization first
    s = normalize_text(s, locale)
    
    # Determine if this is non-Latin content (CJK, Arabic, Indic, Cyrillic, etc.)
    # Use locale if provided, otherwise auto-detect from text
    is_non_latin = is_non_latin_locale(locale) if locale else detect_non_latin_from_text(s)
    
    if is_non_latin:
        # For non-Latin scripts: Preserve native characters
        # Apply lowercase (for scripts that have case), normalize whitespace
        s = s.lower()
        # Keep all word characters (\w includes Unicode letters/digits)
        # Remove only punctuation while preserving native script characters
        s = re.sub(r"[^\w&\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    else:
        # For Latin scripts: Original ASCII-only approach
        s = s.lower()
        s = re.sub(r"[^a-z0-9_&\s]", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    
    return s


def get_sentence_delimiters(locale: Optional[str] = None) -> list[str]:
    """
    Return sentence boundary markers appropriate for the language.
    
    Args:
        locale: ISO 639-1/BCP 47 locale code
    
    Returns:
        List of sentence-ending punctuation marks
    
    Examples:
        >>> get_sentence_delimiters("zh-Hans")
        ['。', '！', '？', '．', '!', '?', '.']
        >>> get_sentence_delimiters("en")
        ['.', '!', '?']
    """
    if is_cjk(locale):
        return CJK_SENTENCE_DELIMITERS.copy()
    return DEFAULT_SENTENCE_DELIMITERS.copy()


def estimate_tokens_cjk(text: str) -> int:
    """
    Estimate token count for CJK text.
    
    CJK languages don't use whitespace tokenization. Rough estimates:
    - Chinese: ~1.5 tokens per character
    - Japanese: ~1.3 tokens per character (Kanji + Kana mix)
    - Korean: ~1.2 tokens per character
    
    This is a rough approximation for chunking purposes.
    
    Args:
        text: CJK text to estimate
    
    Returns:
        Estimated token count
    """
    if not text:
        return 0
    
    # Count CJK characters vs non-CJK
    cjk_chars = 0
    non_cjk_chars = 0
    
    for char in text:
        if char.isspace():
            continue
        code = ord(char)
        if (0x4E00 <= code <= 0x9FFF or
            0x3400 <= code <= 0x4DBF or
            0x3040 <= code <= 0x309F or
            0x30A0 <= code <= 0x30FF or
            0xAC00 <= code <= 0xD7AF):
            cjk_chars += 1
        else:
            non_cjk_chars += 1
    
    # CJK: ~1.5 tokens per char on average
    # Non-CJK: ~4 chars per token on average
    estimated = int(cjk_chars * 1.5) + int(non_cjk_chars / 4)
    return max(estimated, 1) if text.strip() else 0


def get_dominant_language(
    languages: list[dict],
    text_length: int
) -> Optional[str]:
    """
    Determine the dominant language from Azure DI language spans.
    
    Azure DI returns:
    ```
    [{"locale": "zh-Hans", "confidence": 0.95, "spans": [{"offset": 0, "length": 120}]}]
    ```
    
    Args:
        languages: List of language detection results from Azure DI
        text_length: Total text length for coverage calculation
    
    Returns:
        Dominant locale code, or None if no languages detected
    """
    if not languages:
        return None
    
    # Calculate total span coverage per language
    coverage: dict[str, int] = {}
    
    for lang in languages:
        locale = lang.get("locale", "")
        spans = lang.get("spans", [])
        
        total_length = sum(span.get("length", 0) for span in spans)
        coverage[locale] = coverage.get(locale, 0) + total_length
    
    if not coverage:
        return None
    
    # Return language with highest coverage
    dominant = max(coverage.items(), key=lambda x: x[1])
    return dominant[0] if dominant[1] > 0 else None
