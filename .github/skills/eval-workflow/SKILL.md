---
name: eval-workflow
description: >
  Domain knowledge for the agentic-text2sql evaluation workflow. Use when working on
  eval_examples.jsonl, eval_results.jsonl, run_eval.py, adding eval cases, interpreting
  scores, running the eval harness, diagnosing regressions, or expanding the test dataset.
  Trigger phrases: eval, evaluation, run_eval, eval_examples, eval_results, judge score,
  LLM judge, benchmark, regression, complexity tier, add test case.
argument-hint: "Eval task (e.g. 'add cases for CTEs', 'analyse failures', 'run eval')"
---

# Eval Workflow

## Files

| File | Purpose |
|---|---|
| `eval/eval_examples.jsonl` | Ground-truth NL→SQL pairs |
| `eval/eval_results.jsonl` | LLM-judge scores from last run |
| `eval/run_eval.py` | Eval harness script |

---

## `eval_examples.jsonl` Schema

One JSON object per line:

```jsonc
{
  "id": 1,                         // integer, sequential
  "complexity": "simple_filter",   // tier label (see below)
  "question": "...",               // natural-language question
  "expected_sql": "SELECT ..."     // canonical correct SQL
}
```

### Complexity Tiers

| Tier | Description |
|---|---|
| `simple_filter` | Single table, WHERE clause |
| `simple_aggregation` | GROUP BY / COUNT on one table |
| `sort_limit` | ORDER BY + LIMIT |
| `two_table_join_aggregation` | JOIN between two tables + aggregate |
| `left_join_anti_join` | LEFT JOIN with NULL check |
| `multi_table_join_groupby` | 3+ tables, GROUP BY |
| `multi_condition_filter` | Multiple AND/OR conditions |
| `groupby_having` | GROUP BY + HAVING |
| `three_table_join_aggregate` | 3-way JOIN + SUM/COUNT |
| `cte_multi_level_aggregation` | CTE + nested aggregation |

---

## `eval_results.jsonl` Schema

One JSON object per line, produced by `run_eval.py`:

```jsonc
{
  "id": 1,
  "complexity": "simple_filter",
  "question": "...",
  "expected_sql": "...",
  "generated_sql": "...",
  "score": 95,            // integer 0–100 from LLM judge
  "explanation": "...",   // 1–3 sentence judge explanation
  "latency_s": 8.2,       // pipeline wall-clock time in seconds
  "timestamp": "2026-03-29T..."
}
```

---

## Running the Eval

```bash
# Full eval against eval_examples.jsonl → writes eval_results.jsonl
uv run python eval/run_eval.py

# Custom paths
uv run python eval/run_eval.py \
  --examples eval/eval_examples.jsonl \
  --output eval/eval_results.jsonl
```

**Requires**: `.env` with Azure OpenAI credentials (`AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`).  
**Judge model**: `EVAL_MODEL` env var (default `gpt-5.3-chat`).

---

## Scoring Rubric (LLM Judge)

The judge (`JudgeResult`) scores 0–100:
- **90–100**: Functionally equivalent; only minor alias/whitespace differences
- **70–89**: Correct tables/joins but minor missing columns or ordering
- **40–69**: Partially correct (right tables, wrong aggregation or filter)
- **0–39**: Wrong tables or fundamentally incorrect

Minor syntactic differences (column aliases, equivalent expressions) do **not** penalise.

---

## Adding New Eval Examples

When writing new entries:
1. Assign the next sequential `id`
2. Pick the most specific `complexity` tier from the table above
3. Write `expected_sql` that runs correctly against the seeded e-commerce data (`seed_data.py`)
4. Test the SQL manually: `uv run text2sql ask "<question>"` or via SQLite CLI
5. Append to `eval/eval_examples.jsonl` (one JSON object per line, no trailing comma)

### Quick validation
```bash
# Check your new SQL runs
uv run text2sql ask "your new question here"
```

---

## Analysing Results

Quick summary from the terminal:
```bash
# Average score
python -c "
import json; rows = [json.loads(l) for l in open('eval/eval_results.jsonl')]
scores = [r['score'] for r in rows]
print(f'Mean: {sum(scores)/len(scores):.1f}  Min: {min(scores)}  Max: {max(scores)}')
"

# Failures by complexity tier (score < 70)
python -c "
import json; rows = [json.loads(l) for l in open('eval/eval_results.jsonl')]
fails = [r for r in rows if r['score'] < 70]
from collections import Counter
print(Counter(r['complexity'] for r in fails))
"
```
