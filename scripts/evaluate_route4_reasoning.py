#!/usr/bin/env python3

"""
LLM-as-a-Judge Evaluation for Route 4 (Drift/Reasoning).

Uses a strong LLM (configured via .env) to evaluate benchmark results
against the Question Bank ground truth.

Replaces simple string matching with reasoning-based grading.
"""

import argparse
import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import time

from dotenv import load_dotenv
from openai import AzureOpenAI

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load env from graphrag-orchestration/.env
ENV_PATH = Path(__file__).resolve().parents[1] / "graphrag-orchestration" / ".env"
load_dotenv(ENV_PATH)

DEFAULT_QBANK = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "archive"
    / "status_logs"
    / "QUESTION_BANK_5PDFS_2025-12-24.md"
)

# Grading Prompt Template
JUDGE_SYSTEM_PROMPT = """You are an expert AI Judge evaluating RAG system outputs.
Your goal is to determine if the Actual Answer correctly answers the User Query based on the Expected Ground Truth.

## Grading Rubric (Score 0-3):

**3 - Perfect / Correct:**
- The answer contains all key facts/numbers from the Expected Answer.
- For negative tests, it correctly refuses (says "not found" or similar).
- For reasoning questions, it shows valid logic path.
- Additional context is allowed (and encouraged), as long as it doesn't contradict the truth.

**2 - Acceptable / Minor Issues:**
- Correct answer but misses minor details (e.g., exact date format).
- Reasoning is slightly unclear but conclusion is correct.
- Very verbose but correct.

**1 - Incorrect / Weak:**
- Misses the main answer but finds related keywords.
- Hallucinates minor details.
- For negative tests, provides a wrong answer instead of refusing.

**0 - Failure:**
- Completely wrong answer.
- Hallucination of core facts.
- "I don't know" for a positive question (False Negative).
- Providing an answer for a negative question (False Positive / Hallucination).

## Output Format:**
You must output a JSON object:
{
  "score": <0, 1, 2, or 3>,
  "reasoning": "<Concise explanation of the grade>"
}
"""

JUDGE_USER_PROMPT_TEMPLATE = """
**User Query:** {query}

**Expected Ground Truth:**
{expected}

**Actual System Answer:**
{actual}
"""

def _get_aad_token() -> Optional[str]:
    """Get Azure AD access token for Azure OpenAI."""
    try:
        result = subprocess.run(
            [
                "az", "account", "get-access-token",
                "--resource", "https://cognitiveservices.azure.com",
                "--query", "accessToken", "-o", "tsv",
            ],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to get AAD token: {e}")
        return None


def _get_client() -> AzureOpenAI:
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://graphrag-openai-8476.openai.azure.com/")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    
    if not endpoint:
        raise ValueError(f"Missing AZURE_OPENAI_ENDPOINT in {ENV_PATH}")

    # Prefer API key if available, otherwise use Azure AD token
    if api_key:
        logger.info("Using API key authentication")
        return AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )

    # Try Azure AD token auth
    token = _get_aad_token()
    if token:
        logger.info("Using Azure AD token authentication")
        return AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token=token,
            api_version=api_version,
        )

    raise ValueError(
        f"No credentials found. Set AZURE_OPENAI_API_KEY in {ENV_PATH} "
        "or login with 'az login' for token auth."
    )

def evaluate_single_run(client: AzureOpenAI, deployment: str, query: str, expected: str, actual: str) -> Dict[str, Any]:
    """Call LLM to grade one answer."""
    
    prompt = JUDGE_USER_PROMPT_TEMPLATE.format(
        query=query,
        expected=expected,
        actual=actual[:8000]  # Truncate overly long answers
    )
    
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.0,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response content from judge model")
        return json.loads(content)
        
    except Exception as e:
        logger.error(f"Error evaluating query '{query}': {e}")
        return {"score": 0, "reasoning": f"Evaluation Failed: {str(e)}"}

def load_ground_truth(path: Path) -> Dict[str, str]:
    """Simple parser for Question Bank to get QID -> Expected mappings."""
    text = path.read_text(encoding="utf-8")
    gt = {}
    
    # Regex to find **Q-ID:** ... - **Expected:** ...
    # This is a simplified parser; assumes structure matches current file
    entries = text.split("\n\n")
    current_qid = None
    
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m_id = re.search(r"\*\*(Q-[DGNLS]\d+):\*\*", line)
        if m_id:
            current_qid = m_id.group(1)

        if current_qid and "- **Expected:**" in line:
            expected_text = line.split("- **Expected:**")[1].strip()
            # Collect multi-line expected answers (indented continuation lines)
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # Stop at blank line, next section header, next QID, or next top-level bullet
                if not next_line.strip():
                    break
                if re.match(r"\d+\.\s+\*\*Q-", next_line):
                    break
                if re.match(r"\s*- \*\*(Expected Route|Source|Note):", next_line):
                    break
                # Continuation line (indented bullet or text)
                expected_text += " " + next_line.strip().lstrip("- ")
                j += 1
            gt[current_qid] = expected_text.strip()
            current_qid = None  # Reset
            
        i += 1
            
    return gt

def main():
    parser = argparse.ArgumentParser(description="Evaluate Route 4 results with LLM Judge")
    parser.add_argument("results_json", type=Path, help="Path to benchmark output JSON")
    parser.add_argument("--qbank", type=Path, default=DEFAULT_QBANK, help="Path to Question Bank")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of evals (for testing)")
    
    args = parser.parse_args()
    
    # 1. Load Data
    if not args.results_json.exists():
        logger.error(f"Results file not found: {args.results_json}")
        sys.exit(1)
        
    with args.results_json.open("r") as f:
        data = json.load(f)
        
    ground_truth = load_ground_truth(args.qbank)
    logger.info(f"Loaded {len(ground_truth)} ground truth entries")
    
    scenario_data = data.get("scenario", {})
    if not scenario_data:
        # Check if it is the other format
         scenario_data = data.get("questions", [])
    else:
         scenario_data = scenario_data.get("questions", [])

    if not scenario_data:
        logger.error("No question data found in JSON")
        sys.exit(1)
        
    # 2. Setup Client
    client = _get_client()
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5.1") # Match production deployment
    logger.info(f"Using Judge Model: {deployment_name}")
    
    # 3. Evaluate ALL runs (not just the first)
    question_scores = []  # Each entry: {qid, expected, run_scores: [{run, score, reasoning, actual}]}
    
    print(f"\n{'='*60}")
    print(f"Starting Evaluation for {args.results_json.name}")
    print(f"{'='*60}\n")
    
    count = 0
    for q_item in scenario_data:
        if args.limit and count >= args.limit:
            break
            
        qid = q_item.get("qid")
        query = q_item.get("query")
        runs = q_item.get("runs", [])
        
        if not runs:
            continue
            
        expected = ground_truth.get(qid, "UNKNOWN")
        
        if expected == "UNKNOWN":
            logger.warning(f"No ground truth for {qid}, skipping")
            continue
        
        run_scores = []
        for run_idx, run in enumerate(runs):
            actual_answer = run.get("text", "")
            run_num = run_idx + 1
            print(f"Evaluating {qid} run {run_num}/{len(runs)}...", end="", flush=True)
            
            result = evaluate_single_run(client, deployment_name, query, expected, actual_answer)
            score = result.get("score", 0)
            reasoning = result.get("reasoning", "")
            
            print(f" Score: {score}/3")
            
            run_scores.append({
                "run": run_num,
                "score": score,
                "reasoning": reasoning,
                "actual": actual_answer,
            })
        
        question_scores.append({
            "qid": qid,
            "expected": expected,
            "run_scores": run_scores,
        })
        count += 1
    
    # 4. Summary Report — scores summed across ALL runs
    num_questions = len(question_scores)
    all_run_scores = [rs for qs in question_scores for rs in qs["run_scores"]]
    total_evaluations = len(all_run_scores)
    num_runs = max((len(qs["run_scores"]) for qs in question_scores), default=1)
    
    total_score = sum(rs["score"] for rs in all_run_scores)
    max_score = total_evaluations * 3
    accuracy = (total_score / max_score) * 100 if max_score > 0 else 0
    
    # Pass Rate: fraction of individual evaluations scoring >= 2
    pass_count = sum(1 for rs in all_run_scores if rs["score"] >= 2)
    pass_rate = (pass_count / total_evaluations) * 100 if total_evaluations else 0
    
    report_path = args.results_json.with_suffix('.eval.md')
    
    with report_path.open("w") as f:
        f.write("# LLM Judge Evaluation Report\n\n")
        f.write(f"**Source:** `{args.results_json.name}`\n")
        f.write(f"**Judge Model:** `{deployment_name}`\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Summary Metrics\n\n")
        f.write(f"- **Total Score:** {total_score}/{max_score} ({accuracy:.1f}%)\n")
        f.write(f"- **Pass Rate (Score >= 2):** {pass_rate:.1f}%\n")
        f.write(f"- **Questions:** {num_questions}\n")
        f.write(f"- **Runs per question:** {num_runs}\n")
        f.write(f"- **Total evaluations:** {total_evaluations}\n\n")
        
        f.write("## Detailed Results\n\n")
        
        for qs in question_scores:
            qid = qs["qid"]
            run_scores = qs["run_scores"]
            q_total = sum(rs["score"] for rs in run_scores)
            q_max = len(run_scores) * 3
            all_pass = all(rs["score"] >= 2 for rs in run_scores)
            any_fail = any(rs["score"] < 2 for rs in run_scores)
            icon = "✅" if all_pass else "❌"
            
            run_summary = ", ".join(f"Run {rs['run']}: {rs['score']}/3" for rs in run_scores)
            f.write(f"### {qid} {icon} (Score: {q_total}/{q_max} — {run_summary})\n\n")
            
            for rs in run_scores:
                f.write(f"**Run {rs['run']} — Score: {rs['score']}/3:**\n")
                f.write(f"{rs['reasoning']}\n\n")
            
            f.write(f"**Expected:** {qs['expected']}\n\n")
            f.write("---\n")
            
    print(f"\nEvaluation Complete. Report written to:\n{report_path}")

if __name__ == "__main__":
    main()
