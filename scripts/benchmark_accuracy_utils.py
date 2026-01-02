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
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Match question ID pattern: **Q-X#:**
        m = re.match(r'\*\*([QN][-A-Z]+\d+):\*\*\s*(.+)', line)
        if m:
            qid = m.group(1).strip()
            question = m.group(2).strip()
            
            # Check if this is a negative test
            is_negative = qid.startswith("Q-N")
            
            # Look for Expected: in subsequent lines
            expected_parts = []
            j = i + 1
            found_expected = False
            
            while j < len(lines):
                next_line = lines[j].strip()
                
                # Stop at next question
                if re.match(r'\*\*[QN][-A-Z]+\d+:\*\*', next_line):
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
                        if re.match(r'\*\*[QN][-A-Z]+\d+:\*\*', bullet_line):
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
            "not available", "cannot be determined", "information is not"
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
