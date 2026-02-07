#!/usr/bin/env python3
"""
Router Accuracy Evaluation Script

Evaluates the hybrid router's classification accuracy against ground truth
from the question bank.

Usage:
    python scripts/evaluate_router_accuracy.py
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Any
from collections import defaultdict
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "graphrag-orchestration"))

# Load environment from nested .env file
env_path = project_root / "graphrag-orchestration" / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"Loaded environment from: {env_path}")

from src.worker.hybrid.router.main import HybridRouter, DeploymentProfile, QueryRoute


class QuestionBankParser:
    """Parse question bank markdown and extract questions with expected routes."""
    
    def __init__(self, question_bank_path: str):
        self.path = Path(question_bank_path)
        self.questions = []
    
    def parse(self) -> List[Dict[str, Any]]:
        """Parse the question bank and extract all questions with expected routes."""
        with open(self.path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to match questions: Q-X#: question text
        # Followed by Expected Route line
        pattern = r'\d+\.\s+\*\*([QR]-[A-Z]\d+):\*\*\s+([^\n]+)\n\s+-\s+\*\*Expected Route:\*\*\s+([^\n]+)'
        
        matches = re.finditer(pattern, content, re.MULTILINE)
        
        for match in matches:
            qid = match.group(1)
            question = match.group(2).strip()
            expected_route_text = match.group(3).strip()
            
            # Map text to QueryRoute enum
            expected_route = self._parse_route(expected_route_text)
            
            if expected_route:
                self.questions.append({
                    "id": qid,
                    "question": question,
                    "expected_route": expected_route,
                    "expected_route_text": expected_route_text
                })
        
        print(f"Parsed {len(self.questions)} questions from {self.path}")
        return self.questions
    
    def _parse_route(self, route_text: str) -> QueryRoute:
        """Convert route text to QueryRoute enum."""
        route_text_lower = route_text.lower()
        
        if "route 1" in route_text_lower or "vector rag" in route_text_lower:
            return QueryRoute.VECTOR_RAG
        elif "route 2" in route_text_lower or "local search" in route_text_lower:
            return QueryRoute.LOCAL_SEARCH
        elif "route 3" in route_text_lower or "global search" in route_text_lower:
            return QueryRoute.GLOBAL_SEARCH
        elif "route 4" in route_text_lower or "drift" in route_text_lower:
            return QueryRoute.DRIFT_MULTI_HOP
        else:
            print(f"Warning: Could not parse route: {route_text}")
            return None


class RouterAccuracyEvaluator:
    """Evaluate router accuracy against ground truth."""
    
    def __init__(self, router: HybridRouter, questions: List[Dict[str, Any]]):
        self.router = router
        self.questions = questions
        self.results = []
    
    async def evaluate(self) -> Dict[str, Any]:
        """Run evaluation on all questions."""
        print(f"\nEvaluating {len(self.questions)} questions...")
        print("=" * 80)
        
        for q in self.questions:
            # Use async route() method for full complexity assessment
            actual_route = await self.router.route(q["question"])
            expected_route = q["expected_route"]
            
            # Determine if correct (with soft error handling for Route 2 <-> Route 3)
            is_correct = (actual_route == expected_route)
            is_soft_error = (
                {actual_route, expected_route} == {QueryRoute.LOCAL_SEARCH, QueryRoute.GLOBAL_SEARCH}
            )
            
            result = {
                "qid": q["id"],
                "question": q["question"],
                "expected": expected_route.value,
                "actual": actual_route.value,
                "correct": is_correct,
                "soft_error": is_soft_error,
            }
            
            self.results.append(result)
            
            # Print result
            status = "✓" if is_correct else ("~" if is_soft_error else "✗")
            print(f"{status} {q['id']:8} | Expected: {expected_route.value:20} | "
                  f"Actual: {actual_route.value:20}")
        
        print("=" * 80)
        
        # Calculate metrics
        metrics = self._calculate_metrics()
        return metrics
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """Calculate accuracy metrics."""
        total = len(self.results)
        
        # Hard accuracy (exact match only)
        hard_correct = sum(1 for r in self.results if r["correct"])
        hard_accuracy = hard_correct / total if total > 0 else 0
        
        # Soft accuracy (Route 2 <-> Route 3 swaps count as 0.5)
        soft_correct = sum(
            1.0 if r["correct"] else (0.5 if r["soft_error"] else 0.0)
            for r in self.results
        )
        soft_accuracy = soft_correct / total if total > 0 else 0
        
        # Build confusion matrix
        confusion = defaultdict(lambda: defaultdict(int))
        for r in self.results:
            confusion[r["expected"]][r["actual"]] += 1
        
        # Per-route precision and recall
        per_route = {}
        all_routes = [QueryRoute.VECTOR_RAG, QueryRoute.LOCAL_SEARCH, 
                      QueryRoute.GLOBAL_SEARCH, QueryRoute.DRIFT_MULTI_HOP]
        
        for route in all_routes:
            route_val = route.value
            
            # True positives: expected and actual match
            tp = confusion[route_val][route_val]
            
            # False positives: predicted as this route but expected something else
            fp = sum(confusion[other][route_val] 
                    for other in confusion.keys() if other != route_val)
            
            # False negatives: expected this route but predicted something else
            fn = sum(confusion[route_val][other] 
                    for other in confusion[route_val].keys() if other != route_val)
            
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            
            per_route[route_val] = {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": sum(confusion[route_val].values())
            }
        
        return {
            "total_questions": total,
            "hard_accuracy": hard_accuracy,
            "soft_accuracy": soft_accuracy,
            "hard_correct": hard_correct,
            "soft_correct": soft_correct,
            "confusion_matrix": dict(confusion),
            "per_route_metrics": per_route,
            "results": self.results
        }


async def main():
    """Main evaluation function."""
    
    # Parse question bank
    question_bank_path = (
        "docs/archive/status_logs/QUESTION_BANK_5PDFS_2025-12-24.md"
    )
    
    parser = QuestionBankParser(question_bank_path)
    questions = parser.parse()
    
    if not questions:
        print("ERROR: No questions found in question bank")
        return
    
    # Initialize LLM client for routing
    print("\nInitializing LLM client...")
    try:
        from llama_index.llms.azure_openai import AzureOpenAI
        import os
        
        llm = AzureOpenAI(
            deployment_name=os.getenv("AZURE_OPENAI_ROUTING_DEPLOYMENT", "gpt-4o-mini"),
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            temperature=1.0,  # Required for gpt-5-mini/nano which don't support custom temperatures
        )
        print(f"  Using LLM: {os.getenv('AZURE_OPENAI_ROUTING_DEPLOYMENT', 'gpt-4o-mini')}")
    except Exception as e:
        print(f"WARNING: Could not initialize LLM client: {e}")
        print("  Falling back to heuristic-only routing")
        llm = None
    
    # Initialize router with LLM
    print("\nInitializing router (General Enterprise profile)...")
    router = HybridRouter(
        profile=DeploymentProfile.GENERAL_ENTERPRISE,
        llm_client=llm,
        vector_threshold=0.25,
        global_threshold=0.5,
        drift_threshold=0.75
    )
    
    # Run evaluation
    evaluator = RouterAccuracyEvaluator(router, questions)
    metrics = await evaluator.evaluate()
    
    # Print summary
    print("\n" + "=" * 80)
    print("EVALUATION SUMMARY")
    print("=" * 80)
    print(f"Total Questions:     {metrics['total_questions']}")
    print(f"Hard Accuracy:       {metrics['hard_accuracy']:.1%} ({metrics['hard_correct']}/{metrics['total_questions']})")
    print(f"Soft Accuracy:       {metrics['soft_accuracy']:.1%} ({metrics['soft_correct']:.1f}/{metrics['total_questions']})")
    print()
    
    print("Per-Route Metrics:")
    print("-" * 80)
    print(f"{'Route':<25} {'Precision':<12} {'Recall':<12} {'F1':<12} {'Support':<10}")
    print("-" * 80)
    for route, metrics_dict in metrics['per_route_metrics'].items():
        print(f"{route:<25} {metrics_dict['precision']:<12.1%} "
              f"{metrics_dict['recall']:<12.1%} {metrics_dict['f1']:<12.3f} "
              f"{metrics_dict['support']:<10}")
    print("-" * 80)
    
    # Print confusion matrix
    print("\nConfusion Matrix:")
    print("-" * 80)
    all_routes = ["vector_rag", "local_search", "global_search", "drift_multi_hop"]
    
    # Header
    header_label = "Expected \\ Actual"
    print(f"{header_label:<25}", end="")
    for route in all_routes:
        print(f"{route[:10]:<12}", end="")
    print()
    print("-" * 80)
    
    # Rows
    confusion = metrics['confusion_matrix']
    for expected in all_routes:
        print(f"{expected:<25}", end="")
        for actual in all_routes:
            count = confusion.get(expected, {}).get(actual, 0)
            print(f"{count:<12}", end="")
        print()
    print("-" * 80)
    
    # Save detailed results
    output_path = "router_accuracy_results.json"
    with open(output_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    print(f"\nDetailed results saved to: {output_path}")
    
    # Determine pass/fail
    target_hard_accuracy = 0.85
    target_soft_accuracy = 0.90
    
    print("\n" + "=" * 80)
    if metrics['soft_accuracy'] >= target_soft_accuracy:
        print(f"✓ PASS: Soft accuracy {metrics['soft_accuracy']:.1%} >= {target_soft_accuracy:.0%}")
    elif metrics['hard_accuracy'] >= target_hard_accuracy:
        print(f"~ MARGINAL: Hard accuracy {metrics['hard_accuracy']:.1%} >= {target_hard_accuracy:.0%}, "
              f"but soft accuracy {metrics['soft_accuracy']:.1%} < {target_soft_accuracy:.0%}")
    else:
        print(f"✗ FAIL: Hard accuracy {metrics['hard_accuracy']:.1%} < {target_hard_accuracy:.0%}")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
