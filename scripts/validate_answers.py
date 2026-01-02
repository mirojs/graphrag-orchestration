#!/usr/bin/env python3
"""
Answer Validation Script

Compares benchmark responses against ground truth answers from the question bank.
Calculates accuracy, F1 scores, and provides detailed per-question analysis.

Usage:
    python scripts/validate_answers.py \
        --benchmark benchmarks/route2_repeatability_20260102T183752Z.json \
        --question-bank docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md \
        --output validation_report.md

Metrics:
    - Exact Match: Response text exactly matches expected (after normalization)
    - Fuzzy Match: String similarity score (0-1)
    - Containment: Expected answer found within response
    - Precision/Recall: Token-level overlap
"""

import argparse
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class GroundTruth:
    """Ground truth answer from question bank."""
    qid: str
    question: str
    expected: str
    source: str


@dataclass
class ValidationResult:
    """Validation result for a single question."""
    qid: str
    question: str
    expected: str
    actual: str
    exact_match: bool
    fuzzy_score: float  # 0-1
    containment: bool  # Expected text found in actual
    precision: float  # Token overlap: relevant retrieved / retrieved
    recall: float  # Token overlap: relevant retrieved / relevant
    f1: float
    source: str


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    # Lowercase
    text = text.lower()
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove punctuation for comparison (keep alphanumeric and spaces)
    text = re.sub(r'[^\w\s$.,/()-]', '', text)
    return text.strip()


def extract_ground_truth(question_bank_path: Path) -> Dict[str, GroundTruth]:
    """Parse question bank markdown to extract ground truth answers."""
    content = question_bank_path.read_text(encoding='utf-8')
    ground_truth: Dict[str, GroundTruth] = {}
    
    # Split by question entries (numbered list items with Q-X# format)
    lines = content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for pattern: #. **Q-X#:** Question
        match = re.match(r'^(\d+)\.\s+\*\*(Q-[A-Z]\d+):\*\*\s+(.+)', line)
        if match:
            qid = match.group(2).strip()
            question = match.group(3).strip()
            expected = ""
            source = "Unknown"
            
            # Look ahead for Expected and Source fields
            j = i + 1
            while j < len(lines) and not re.match(r'^\d+\.\s+\*\*Q-', lines[j]):
                line_content = lines[j].strip()
                
                # Extract Expected field
                exp_match = re.match(r'-\s+\*\*Expected:\*\*\s*(.*)$', line_content)
                if exp_match:
                    # Start with first line (might be empty if just "- **Expected:**")
                    expected = exp_match.group(1).strip() if exp_match.group(1) else ""
                    
                    # Look ahead for continuation lines (bullet lists or regular continuation)
                    k = j + 1
                    while k < len(lines):
                        next_line = lines[k].strip()
                        
                        # Stop at next major field
                        if re.match(r'-\s+\*\*(?:Source|Expected):', next_line):
                            break
                        
                        # Stop at next question or section header
                        if re.match(r'^\d+\.\s+\*\*Q-', next_line) or next_line.startswith('##') or next_line.startswith('---'):
                            break
                        
                        # Empty line might end the expected field, but check next line first
                        if not next_line:
                            # Look ahead one more to see if there's more content
                            if k + 1 < len(lines):
                                peek = lines[k + 1].strip()
                                if peek and not re.match(r'-\s+\*\*(?:Source|Expected):', peek) and not re.match(r'^\d+\.\s+\*\*Q-', peek):
                                    # Continue through empty line
                                    k += 1
                                    continue
                            break
                        
                        # Add bullet list items or continuation
                        if next_line.startswith('-'):
                            # Bullet item in expected field
                            expected += ' ' + next_line[1:].strip()
                        else:
                            # Regular continuation
                            expected += ' ' + next_line
                        
                        k += 1
                
                # Extract Source field
                src_match = re.match(r'-\s+\*\*Source:\*\*\s+(.+)', line_content)
                if src_match:
                    source = src_match.group(1).strip()
                
                # Stop if we hit next section or question
                if line_content.startswith('##') or line_content.startswith('---'):
                    break
                    
                j += 1
            
            # Clean up expected answer
            expected = re.sub(r'`', '', expected)  # Remove backticks
            expected = re.sub(r'\*\*', '', expected)  # Remove bold
            expected = re.sub(r'\s+', ' ', expected).strip()  # Normalize whitespace
            
            if expected:  # Only add if we found an expected answer
                ground_truth[qid] = GroundTruth(
                    qid=qid,
                    question=question,
                    expected=expected,
                    source=source
                )
        
        i += 1
    
    return ground_truth


def calculate_token_metrics(expected: str, actual: str) -> Tuple[float, float, float]:
    """Calculate precision, recall, F1 based on token overlap."""
    expected_tokens = set(normalize_text(expected).split())
    actual_tokens = set(normalize_text(actual).split())
    
    if not expected_tokens:
        return 0.0, 0.0, 0.0
    
    if not actual_tokens:
        return 0.0, 0.0, 0.0
    
    overlap = expected_tokens.intersection(actual_tokens)
    
    precision = len(overlap) / len(actual_tokens) if actual_tokens else 0.0
    recall = len(overlap) / len(expected_tokens) if expected_tokens else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    
    return precision, recall, f1


def fuzzy_match_score(expected: str, actual: str) -> float:
    """Calculate fuzzy string similarity score (0-1)."""
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    
    if not expected_norm or not actual_norm:
        return 0.0
    
    return difflib.SequenceMatcher(None, expected_norm, actual_norm).ratio()


def check_containment(expected: str, actual: str) -> bool:
    """Check if expected answer is contained within actual response."""
    expected_norm = normalize_text(expected)
    actual_norm = normalize_text(actual)
    
    if not expected_norm:
        return False
    
    # Check direct containment
    if expected_norm in actual_norm:
        return True
    
    # Check if most key tokens from expected appear in actual
    expected_tokens = set(expected_norm.split())
    actual_tokens = set(actual_norm.split())
    
    # Consider it contained if >80% of expected tokens are in actual
    overlap_ratio = len(expected_tokens.intersection(actual_tokens)) / len(expected_tokens) if expected_tokens else 0
    return overlap_ratio >= 0.8


def validate_benchmark(
    benchmark_path: Path,
    ground_truth: Dict[str, GroundTruth]
) -> List[ValidationResult]:
    """Validate benchmark results against ground truth."""
    with open(benchmark_path, 'r', encoding='utf-8') as f:
        benchmark_data = json.load(f)
    
    results: List[ValidationResult] = []
    
    # Handle different benchmark formats
    # Format 1: {scenarios: [{questions: [...]}]} - Route 2 style
    # Format 2: {results: {scenario_name: {Q-X#: {...}}}} - Route 3/4 style
    
    if 'scenarios' in benchmark_data:
        # Route 2 style format
        scenarios = benchmark_data.get('scenarios', [])
        
        for scenario in scenarios:
            questions = scenario.get('questions', [])
            
            for q_data in questions:
                qid = q_data.get('qid', '')
                
                if qid not in ground_truth:
                    print(f"Warning: Question {qid} not found in ground truth, skipping")
                    continue
                
                gt = ground_truth[qid]
                
                # Get first run's response (or aggregate if multiple runs)
                runs = q_data.get('runs', [])
                if not runs:
                    print(f"Warning: No runs for {qid}, skipping")
                    continue
                
                # Use first run's text as the actual response
                actual_response = runs[0].get('text', '') if runs else ''
                
                # Calculate metrics
                expected_norm = normalize_text(gt.expected)
                actual_norm = normalize_text(actual_response)
                
                exact = expected_norm == actual_norm
                fuzzy = fuzzy_match_score(gt.expected, actual_response)
                contained = check_containment(gt.expected, actual_response)
                precision, recall, f1 = calculate_token_metrics(gt.expected, actual_response)
                
                result = ValidationResult(
                    qid=qid,
                    question=gt.question,
                    expected=gt.expected,
                    actual=actual_response[:500],  # Truncate long responses
                    exact_match=exact,
                    fuzzy_score=fuzzy,
                    containment=contained,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                    source=gt.source
                )
                
                results.append(result)
    
    elif 'results' in benchmark_data:
        # Route 3/4 style format
        scenario_results = benchmark_data.get('results', {})
        
        for scenario_name, scenario_data in scenario_results.items():
            for qid, q_data in scenario_data.items():
                if qid not in ground_truth:
                    print(f"Warning: Question {qid} not found in ground truth, skipping")
                    continue
                
                gt = ground_truth[qid]
                
                # Get responses from runs
                runs = q_data.get('runs', [])
                if not runs:
                    print(f"Warning: No runs for {qid}, skipping")
                    continue
                
                # Use first run's response_text
                actual_response = runs[0].get('response_text', '') if runs else ''
                
                # Calculate metrics
                expected_norm = normalize_text(gt.expected)
                actual_norm = normalize_text(actual_response)
                
                exact = expected_norm == actual_norm
                fuzzy = fuzzy_match_score(gt.expected, actual_response)
                contained = check_containment(gt.expected, actual_response)
                precision, recall, f1 = calculate_token_metrics(gt.expected, actual_response)
                
                result = ValidationResult(
                    qid=qid,
                    question=gt.question,
                    expected=gt.expected,
                    actual=actual_response[:500],  # Truncate long responses
                    exact_match=exact,
                    fuzzy_score=fuzzy,
                    containment=contained,
                    precision=precision,
                    recall=recall,
                    f1=f1,
                    source=gt.source
                )
                
                results.append(result)
    
    return results


def generate_report(results: List[ValidationResult], output_path: Path):
    """Generate markdown validation report."""
    if not results:
        output_path.write_text("# Validation Report\n\nNo results to validate.\n")
        return
    
    # Calculate aggregate metrics
    total = len(results)
    exact_matches = sum(1 for r in results if r.exact_match)
    high_fuzzy = sum(1 for r in results if r.fuzzy_score >= 0.8)
    contained = sum(1 for r in results if r.containment)
    
    avg_fuzzy = sum(r.fuzzy_score for r in results) / total if total else 0
    avg_precision = sum(r.precision for r in results) / total if total else 0
    avg_recall = sum(r.recall for r in results) / total if total else 0
    avg_f1 = sum(r.f1 for r in results) / total if total else 0
    
    with output_path.open('w', encoding='utf-8') as f:
        f.write("# Answer Validation Report\n\n")
        
        f.write("## Summary Metrics\n\n")
        f.write(f"**Total Questions Validated:** {total}\n\n")
        
        f.write("| Metric | Value | Percentage |\n")
        f.write("|--------|-------|------------|\n")
        f.write(f"| Exact Matches | {exact_matches} | {exact_matches/total*100:.1f}% |\n")
        f.write(f"| High Fuzzy Match (≥0.8) | {high_fuzzy} | {high_fuzzy/total*100:.1f}% |\n")
        f.write(f"| Containment (Answer Found) | {contained} | {contained/total*100:.1f}% |\n")
        f.write(f"| Average Fuzzy Score | {avg_fuzzy:.3f} | - |\n")
        f.write(f"| Average Precision | {avg_precision:.3f} | - |\n")
        f.write(f"| Average Recall | {avg_recall:.3f} | - |\n")
        f.write(f"| Average F1 Score | {avg_f1:.3f} | - |\n\n")
        
        f.write("---\n\n")
        
        f.write("## Per-Question Results\n\n")
        
        for result in sorted(results, key=lambda x: x.qid):
            # Status emoji
            if result.exact_match:
                status = "✅ EXACT"
            elif result.containment:
                status = "✓ CONTAINED"
            elif result.fuzzy_score >= 0.8:
                status = "≈ HIGH SIMILARITY"
            elif result.fuzzy_score >= 0.5:
                status = "~ PARTIAL"
            else:
                status = "❌ MISS"
            
            f.write(f"### {result.qid}: {result.question}\n\n")
            f.write(f"**Status:** {status}\n\n")
            
            f.write("| Metric | Value |\n")
            f.write("|--------|-------|\n")
            f.write(f"| Exact Match | {'Yes' if result.exact_match else 'No'} |\n")
            f.write(f"| Fuzzy Score | {result.fuzzy_score:.3f} |\n")
            f.write(f"| Containment | {'Yes' if result.containment else 'No'} |\n")
            f.write(f"| Precision | {result.precision:.3f} |\n")
            f.write(f"| Recall | {result.recall:.3f} |\n")
            f.write(f"| F1 Score | {result.f1:.3f} |\n\n")
            
            f.write(f"**Expected Answer:**\n```\n{result.expected}\n```\n\n")
            
            # Show first 500 chars of actual response
            actual_display = result.actual if len(result.actual) <= 500 else result.actual[:500] + "..."
            f.write(f"**Actual Response (truncated):**\n```\n{actual_display}\n```\n\n")
            
            f.write(f"**Source:** {result.source}\n\n")
            f.write("---\n\n")
    
    print(f"✅ Validation report written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Validate benchmark answers against ground truth"
    )
    parser.add_argument(
        '--benchmark',
        type=Path,
        required=True,
        help='Path to benchmark JSON results file'
    )
    parser.add_argument(
        '--question-bank',
        type=Path,
        default=Path('docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md'),
        help='Path to question bank markdown file'
    )
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('validation_report.md'),
        help='Output path for validation report'
    )
    
    args = parser.parse_args()
    
    if not args.benchmark.exists():
        print(f"❌ Benchmark file not found: {args.benchmark}")
        return 1
    
    if not args.question_bank.exists():
        print(f"❌ Question bank not found: {args.question_bank}")
        return 1
    
    print(f"📖 Loading ground truth from {args.question_bank}...")
    ground_truth = extract_ground_truth(args.question_bank)
    print(f"✅ Loaded {len(ground_truth)} ground truth answers")
    
    print(f"\n🔍 Validating benchmark results from {args.benchmark}...")
    results = validate_benchmark(args.benchmark, ground_truth)
    print(f"✅ Validated {len(results)} questions")
    
    print(f"\n📝 Generating validation report...")
    generate_report(results, args.output)
    
    # Print quick summary
    if results:
        exact = sum(1 for r in results if r.exact_match)
        contained = sum(1 for r in results if r.containment)
        print(f"\n📊 Quick Summary:")
        print(f"   Exact matches: {exact}/{len(results)} ({exact/len(results)*100:.1f}%)")
        print(f"   Answer found: {contained}/{len(results)} ({contained/len(results)*100:.1f}%)")
        print(f"   Avg F1 score: {sum(r.f1 for r in results)/len(results):.3f}")
    
    return 0


if __name__ == '__main__':
    exit(main())
