"""Shared accuracy validation utilities for benchmark scripts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


@dataclass(frozen=True)
class GroundTruth:
    """Ground truth answer for validation."""
    qid: str
    question: str
    expected: str
    is_negative: bool  # True for Q-N questions


def extract_ground_truth(question_bank_path: Path) -> Dict[str, GroundTruth]:
    """Extract ground truth answers from question bank."""
    content = question_bank_path.read_text(encoding="utf-8")
    lines = content.splitlines()
    
    ground_truth: Dict[str, GroundTruth] = {}

    def _expected_looks_negative(expected: str) -> bool:
        e = (expected or "").strip().lower()
        if not e:
            return True
        negative_markers = [
            "not specified",
            "not provided",
            "not mentioned",
            "not available",
            "cannot be determined",
            "no information",
            "information is not",
            "none",
            "blank",
            "n/a",
            "unknown",
        ]
        return any(m in e for m in negative_markers)
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Match question ID pattern: **Q-X#:** (with optional numbered list prefix)
        m = re.match(r'^\d*\.?\s*\*\*([QN][-A-Z]+\d+):\*\*\s*(.+)', line)
        if m:
            qid = m.group(1).strip()
            question = m.group(2).strip()
            
            # Look for Expected: in subsequent lines
            expected_parts = []
            j = i + 1
            found_expected = False
            
            while j < len(lines):
                next_line = lines[j].strip()
                
                # Stop at next question
                if re.match(r'^\d*\.?\s*\*\*[QN][-A-Z]+\d+:\*\*', next_line):
                    break
                
                # Look for Expected marker
                if next_line.startswith("- **Expected:**"):
                    found_expected = True
                    # Extract text after Expected:
                    exp_text = next_line.replace("- **Expected:**", "").strip()
                    if exp_text:
                        expected_parts.append(exp_text)
                    j += 1
                    
                    # Continue through bullet points and empty lines
                    while j < len(lines):
                        bullet_line = lines[j].strip()
                        # Stop at next question or next field
                        if re.match(r'^\d*\.?\s*\*\*[QN][-A-Z]+\d+:\*\*', bullet_line):
                            break
                        if bullet_line.startswith("- **") and not bullet_line.startswith("  -"):
                            break
                        # Include bullet points and text
                        if bullet_line.startswith("-") or bullet_line.startswith("•"):
                            expected_parts.append(bullet_line.lstrip("-•").strip())
                        elif bullet_line and not bullet_line.startswith("**"):
                            expected_parts.append(bullet_line)
                        j += 1
                    break
                j += 1
            
            if found_expected:
                expected = " ".join(expected_parts)

                # Determine whether this is a negative test.
                # Prefer the expected-answer content (so Q-N* can become positive if the
                # corpus actually contains the requested value).
                is_negative = qid.startswith("Q-N") and _expected_looks_negative(expected)
                ground_truth[qid] = GroundTruth(
                    qid=qid,
                    question=question,
                    expected=expected,
                    is_negative=is_negative
                )
        
        i += 1
    
    return ground_truth


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^a-z0-9 $%./:-]", "", t)
    return t


def similarity(a: str, b: str) -> float:
    """Calculate similarity between two strings using SequenceMatcher."""
    import difflib
    return float(difflib.SequenceMatcher(None, a or "", b or "").ratio())


def calculate_accuracy_metrics(expected: str, actual: str, is_negative: bool) -> Dict[str, Any]:
    """Calculate accuracy metrics comparing expected vs actual answer."""
    
    # For negative tests, check if response indicates "not found"
    if is_negative:
        actual_lower = actual.lower()
        not_found_phrases = [
            "not found", "not specified", "not mentioned", "not provided",
            "does not specify", "doesn't specify", "no information",
            "not available", "cannot be determined", "information is not",
            "not explicitly include", "not explicitly mention", "not explicitly provide",
            "not explicitly state", "no documents explicitly state", "does not explicitly",
            "not explicitly detailed", "no explicit mention",
            # Additional phrases for responses like "no VAT number is present"
            "is not present", "not present", "does not provide", "doesn't provide",
            "nowhere in", "no vat", "no tax id", "no routing", "no account",
            "no wire transfer", "no ach", "no bank", "not include", "does not include",
            "doesn't include", "no such", "none of the", "not contain",
            # Blank-field synonyms (Feb 13, 2026 — caught by Q-N10 false failure)
            "left blank", "is blank", "not filled in", "no shipping method",
            "not recorded", "no value", "is empty", "field is blank",
            "no data", "does not record", "doesn't record",
        ]
        negative_test_pass = any(phrase in actual_lower for phrase in not_found_phrases)
        return {
            "is_negative": True,
            "negative_test_pass": negative_test_pass,
            "exact_match": False,
            "fuzzy_score": 0.0,
            "containment": 0.0,
            "precision": 0.0,
            "recall": 0.0,
            "f1_score": 0.0,
        }
    
    # For positive tests, calculate various metrics
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    
    # Exact match
    exact_match = expected_norm == actual_norm
    
    # Fuzzy similarity
    fuzzy_score = similarity(expected_norm, actual_norm)
    
    # Containment: how much of expected is in actual
    expected_tokens = set(expected_norm.split())
    actual_tokens = set(actual_norm.split())
    
    if expected_tokens:
        containment = len(expected_tokens & actual_tokens) / len(expected_tokens)
    else:
        containment = 1.0 if not actual_tokens else 0.0
    
    # Precision, Recall, F1
    if actual_tokens:
        precision = len(expected_tokens & actual_tokens) / len(actual_tokens)
    else:
        precision = 0.0
    
    if expected_tokens:
        recall = len(expected_tokens & actual_tokens) / len(expected_tokens)
    else:
        recall = 1.0 if not actual_tokens else 0.0
    
    if precision + recall > 0:
        f1_score = 2 * (precision * recall) / (precision + recall)
    else:
        f1_score = 0.0
    
    return {
        "is_negative": False,
        "negative_test_pass": False,
        "exact_match": exact_match,
        "fuzzy_score": fuzzy_score,
        "containment": containment,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
    }


@dataclass
class BankQuestion:
    """A question from the question bank."""
    qid: str
    query: str


def read_question_bank(
    path: Path,
    *,
    positive_prefix: str = "Q-V",
    negative_prefix: str = "Q-N"
) -> list:
    """Read questions from question bank (positive + negative tests).
    
    Handles two question bank formats:
    1. Multi-line format with expected on separate line:
       **Q-D1:** Question text here?
          - **Expected:** Answer text
    2. Single-line format with expected on same line:
       **Q-D1:** Question text here?   - **Expected Route:** Route 4   - **Expected:** Answer text
    
    The regex stops at ' - **' or '  - **' markers to avoid including expected answers in the query.
    
    Args:
        path: Path to question bank markdown file
        positive_prefix: Prefix for positive test questions (e.g., "Q-V", "Q-D", "Q-G")
        negative_prefix: Prefix for negative test questions (e.g., "Q-N")
    
    Returns:
        List of BankQuestion objects
    """
    questions: list = []
    
    def extract_question(line: str, prefix: str) -> tuple:
        """Extract (qid, query_text) from a question bank line."""
        # Pattern stops at ' - **' (common metadata marker) or end of line
        pattern = re.compile(rf"\*\*({re.escape(prefix)}\d+):\*\*\s*(.+?)(?:\s+-\s+\*\*|\s*$)")
        m = pattern.search(line)
        if m:
            qid = m.group(1).strip()
            qtext = m.group(2).strip()
            # Additional cleanup: remove any trailing ' -' or '  -' 
            qtext = re.sub(r'\s+-\s*$', '', qtext).strip()
            return qid, qtext
        return None, None
    
    # Read positive questions
    for line in path.read_text(encoding="utf-8").splitlines():
        if f"**{positive_prefix}" in line:
            qid, qtext = extract_question(line, positive_prefix)
            if qid and qtext:
                questions.append(BankQuestion(qid=qid, query=qtext))
    
    # Read negative questions
    for line in path.read_text(encoding="utf-8").splitlines():
        if f"**{negative_prefix}" in line:
            qid, qtext = extract_question(line, negative_prefix)
            if qid and qtext:
                questions.append(BankQuestion(qid=qid, query=qtext))
    
    if not questions:
        raise RuntimeError(f"No {positive_prefix}* or {negative_prefix}* questions found in {path}")
    
    return questions
