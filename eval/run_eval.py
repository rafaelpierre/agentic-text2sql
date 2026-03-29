"""Evaluation script for the Text2SQL pipeline.

For each example in eval_examples.jsonl:
  1. Runs the full pipeline to get a generated SQL query.
  2. Uses the Azure OpenAI model as a judge to score the generated SQL
     against the expected SQL on a 0-100 scale, with an explanation.
  3. Saves results to eval_results.jsonl next to this script.

Usage:
    uv run python eval/run_eval.py
    uv run python eval/run_eval.py --examples eval/eval_examples.jsonl --output eval/eval_results.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel
from pydantic_ai import Agent

from text2sql_mvp.app.log import configure_logging, get_logger
from text2sql_mvp.app.text2sql import run_pipeline

import logging
configure_logging(logging.INFO)
log = get_logger("text2sql.eval")

EVAL_MODEL = os.environ.get("EVAL_MODEL", "gpt-5.3-chat")
EXAMPLES_FILE = Path(__file__).parent / "eval_examples.jsonl"
OUTPUT_FILE = Path(__file__).parent / "eval_results.jsonl"


# ---------------------------------------------------------------------------
# Judge model
# ---------------------------------------------------------------------------

class JudgeResult(BaseModel):
    score: int          # 0–100
    explanation: str


_judge_agent: Agent[None, JudgeResult] | None = None


def _get_judge_agent() -> Agent[None, JudgeResult]:
    global _judge_agent
    if _judge_agent is None:
        _judge_agent = Agent(
            model=f"azure:{EVAL_MODEL}",
            output_type=JudgeResult,
            system_prompt=(
                "You are an expert SQL evaluator. You will be given a natural-language "
                "question, an expected SQL query, and a generated SQL query. "
                "Score the generated query from 0 to 100 based on how correctly and "
                "completely it answers the question compared to the expected query. "
                "Consider: correct tables, correct columns, correct filters/joins/aggregations, "
                "correct ordering. Minor syntactic differences (aliases, whitespace, equivalent "
                "expressions) should NOT penalise the score. "
                "Return a JSON object with 'score' (integer 0-100) and 'explanation' (1-3 sentences)."
            ),
        )
    return _judge_agent


def judge(question: str, expected_sql: str, generated_sql: str) -> JudgeResult:
    agent = _get_judge_agent()
    prompt = (
        f"Question: {question}\n\n"
        f"Expected SQL:\n{expected_sql}\n\n"
        f"Generated SQL:\n{generated_sql}"
    )
    result = agent.run_sync(prompt)
    return result.output


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def load_examples(path: Path) -> list[dict[str, Any]]:
    examples = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def run_eval(examples_file: Path, output_file: Path) -> None:
    examples = load_examples(examples_file)
    log.info("📋 Loaded %d examples from %s", len(examples), examples_file)

    results = []
    total_score = 0

    for i, ex in enumerate(examples, start=1):
        ex_id = ex["id"]
        question = ex["question"]
        expected_sql = ex["expected_sql"]
        complexity = ex.get("complexity", "unknown")

        log.info("=" * 60)
        log.info("📝 [%d/%d] id=%s | %s", i, len(examples), ex_id, complexity)
        log.info("   Question: %s", question)

        # --- Run pipeline ---
        pipeline_start = time.perf_counter()
        pipeline_error = None
        generated_sql = ""
        try:
            result = run_pipeline(question, narrate=False)
            generated_sql = result.generated_sql
            if result.error:
                pipeline_error = result.error
                log.error("   Pipeline SQL error: %s", result.error)
        except Exception as exc:
            pipeline_error = str(exc)
            log.error("   Pipeline exception: %s", exc)
        pipeline_elapsed = time.perf_counter() - pipeline_start

        log.info("   Generated SQL: %s", generated_sql or "(none)")

        # --- Judge ---
        score = 0
        explanation = ""
        judge_error = None
        judge_elapsed = 0.0
        if generated_sql:
            try:
                t0 = time.perf_counter()
                judge_result = judge(question, expected_sql, generated_sql)
                judge_elapsed = time.perf_counter() - t0
                score = judge_result.score
                explanation = judge_result.explanation
                log.info(
                    "   🏅 Score: %d/100 (judged in %.2fs) — %s",
                    score, judge_elapsed, explanation,
                )
            except Exception as exc:
                judge_error = str(exc)
                log.error("   Judge error: %s", exc)
        else:
            explanation = "Pipeline did not produce a SQL query."
            log.warning("   ⚠️  No SQL generated, score=0")

        total_score += score
        results.append({
            "id": ex_id,
            "complexity": complexity,
            "question": question,
            "expected_sql": expected_sql,
            "generated_sql": generated_sql,
            "pipeline_error": pipeline_error,
            "score": score,
            "explanation": explanation,
            "judge_error": judge_error,
            "pipeline_elapsed_s": round(pipeline_elapsed, 3),
            "judge_elapsed_s": round(judge_elapsed, 3),
        })

    # --- Summary ---
    avg_score = total_score / len(examples) if examples else 0
    log.info("=" * 60)
    log.info("✅ Eval complete | avg score: %.1f/100 across %d examples", avg_score, len(examples))

    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "model": EVAL_MODEL,
        "examples_file": str(examples_file),
        "total_examples": len(examples),
        "average_score": round(avg_score, 2),
        "results": results,
    }

    with open(output_file, "w") as f:
        json.dump(summary, f, indent=2)

    log.info("💾 Results saved to %s", output_file)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Text2SQL eval")
    parser.add_argument("--examples", type=Path, default=EXAMPLES_FILE)
    parser.add_argument("--output", type=Path, default=OUTPUT_FILE)
    args = parser.parse_args()

    run_eval(args.examples, args.output)
