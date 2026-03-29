# agentic-text2sql

A fast, self-correcting Natural Language → SQL pipeline built with **[Pydantic AI](https://ai.pydantic.dev/)** as the agent orchestration framework and **Azure OpenAI** as the model backend.

- **~8 seconds** end-to-end latency on a 10-table e-commerce schema
- **Self-correcting SQL** via `ModelRetry` on `OperationalError`
- **Zero LLM cost** for schema lookup — pure-Python FTS replaces the schema agent
- **Two-model routing**: a nano model for cheap tasks, a full model only for SQL generation

---

## Architecture

```mermaid
flowchart TD
    Q(["User question"]) --> S1

    subgraph S1 ["Stage 1 — LLM Query Expansion  ~1s"]
        direction TB
        E1["gpt-5.4-nano · max_tokens=150"]
        E2["Extract noun phrases"]
        E3["Fallback: NLTK stopword removal"]
        E1 --> E2 --> E3
    end

    S1 -->|"noun terms"| S2

    subgraph S2 ["Stage 2 — Fast Schema Lookup  <50ms  ·  no LLM"]
        direction TB
        F1["asyncio.gather → parallel FTS per term"]
        F2["BM25 score merge · top-3 tables"]
        F3["FK neighbour expansion"]
        F4["DBML generation"]
        F1 --> F2 --> F3 --> F4
    end

    S2 -->|"DBML schema snippet"| S3

    subgraph S3 ["Stage 3 — SQL Agent  ~6-8s  ·  Pydantic AI"]
        direction TB
        A1["gpt-5.3-chat · REASONING_EFFORT=low"]
        A2["Tool: execute_sql"]
        A3["ModelRetry on OperationalError"]
        A1 --> A2 --> A3
        A3 -->|"retry with error context"| A1
    end

    S3 -->|"SQL + result rows"| S4

    subgraph S4 ["Stage 4 — Answer Narration  ~1s  optional"]
        direction TB
        N1["gpt-5.4-nano · max_tokens=300"]
        N2["Plain-English answer"]
        N1 --> N2
    end

    S4 --> R(["Answer + SQL + rows"])
```

---

## Quick Start

### Prerequisites

- Python ≥ 3.11
- [uv](https://github.com/astral-sh/uv)
- Azure OpenAI access with `gpt-5.4-nano` and `gpt-5.3-chat` deployed

### Install

```bash
git clone https://github.com/your-org/agentic-text2sql
cd agentic-text2sql
uv sync
```

### Configure

```bash
cp .env.example .env
```

Edit `.env` with your Azure credentials:

```env
AZURE_OPENAI_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_OPENAI_API_KEY=<your-key>
OPENAI_API_VERSION=2024-12-01-preview
```

### Seed and Index

```bash
# Populate meta-schema (table + column descriptions)
uv run python cli.py seed-meta

# Insert dummy e-commerce rows
uv run python cli.py seed-data

# Build FTS5 search index
uv run python cli.py build-fts
```

### Ask a Question

```bash
uv run python cli.py ask "Which products are in the Electronics category?"

# With verbose pipeline output
uv run python cli.py ask "Top 5 customers by lifetime spend" --verbose

# SQL only, no narration
uv run python cli.py ask "How many orders were placed last month?" --no-narrate
```

---

## CLI Reference

| Command | Description |
|---|---|
| `seed-meta` | Populate meta-schema with e-commerce table/column descriptions |
| `seed-data` | Insert dummy e-commerce rows into the data schema |
| `build-fts` | Create / refresh FTS5 virtual tables |
| `search <query>` | Run BM25 FTS and print matching tables/columns with scores |
| `ask <question>` | Run the full Text2SQL pipeline |
| `dbml export` | Print DBML schema to stdout |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | — | API key |
| `OPENAI_API_VERSION` | — | API version (e.g. `2024-12-01-preview`) |
| `FAST_MODEL` | `gpt-5.4-nano` | Model for query expansion and narration |
| `SQL_MODEL` | `gpt-5.3-chat` | Model for SQL generation |
| `ANSWER_MODEL` | `$FAST_MODEL` | Model for answer narration (defaults to FAST_MODEL) |
| `REASONING_EFFORT` | `low` | `low` / `medium` / `high` — controls chain-of-thought |
| `MAX_TOKENS_SQL` | `1024` | Token cap for SQL agent output |
| `MAX_TOKENS_ANSWER` | `300` | Token cap for narration output |
| `DB_URL` | `sqlite:///./text2sql.db` | SQLAlchemy database URL |

---

## Model Routing

| Task | Model | Why |
|---|---|---|
| Query expansion (noun extraction) | `gpt-5.4-nano` | Simple extraction, ~150 tokens |
| Answer narration | `gpt-5.4-nano` | Templated prose, low stakes |
| SQL generation + execution | `gpt-5.3-chat` | Needs full reasoning, self-correction |

The schema lookup stage uses **no LLM** — it runs pure-Python BM25 FTS via SQLite FTS5.

---

## Eval Results

Tested on 10 Natural Language → SQL examples covering:
`simple_filter`, `aggregation`, `multi-table join`, `subquery`, `window function`, `CTE`

| Metric | Value |
|---|---|
| Average score | 83.6 / 100 |
| Average latency | ~8s |
| Self-correcting retries | ModelRetry on OperationalError |

Run the eval yourself:

```bash
uv run python eval/run_eval.py
# Results written to eval/eval_results.jsonl
```

---

## Project Structure

```
agentic-text2sql/
├── cli.py                          # Typer CLI entry point
├── pyproject.toml
├── .env                            # Azure credentials (not committed)
├── eval/
│   ├── eval_examples.jsonl         # 10 NL→SQL test cases
│   └── run_eval.py                 # LLM-as-judge eval runner
├── tests/
│   ├── conftest.py
│   ├── test_dbml_gen.py
│   ├── test_fts.py
│   └── test_retrieval.py
└── text2sql_mvp/app/
    ├── text2sql.py                 # Pipeline — main entry point
    ├── fts.py                      # FTS5 index build + BM25 search
    ├── dbml_gen.py                 # DBML schema generation
    ├── meta_schema.py              # FK neighbour expansion, table registry
    ├── retrieval.py                # Legacy LLM retrieval (unused in pipeline)
    ├── seed_meta.py                # E-commerce schema definitions
    ├── seed_data.py                # Dummy data rows
    ├── db.py                       # SQLAlchemy engine factory
    ├── data_schema.py              # SQLAlchemy table models
    └── log.py                      # ANSI colour logging
```

---

## Running Tests

```bash
uv run pytest
```

All 29 tests run against an in-memory SQLite database and do not require Azure credentials.

---

## How Self-Correction Works

The SQL agent is given an `execute_sql` tool. When the generated SQL raises a `sqlalchemy.exc.OperationalError` (e.g. wrong column name, bad syntax), the tool raises `ModelRetry` with the error message. pydantic-ai automatically re-prompts the model with the full error context, allowing it to fix the SQL without any manual retry logic.

```python
@sql_agent.tool
async def execute_sql(ctx: RunContext[PipelineDeps], sql: str) -> str:
    try:
        result = conn.execute(text(sql))
        ctx.deps.rows = [dict(row) for row in result]
        return json.dumps(ctx.deps.rows[:5], default=str)
    except OperationalError as e:
        raise ModelRetry(f"SQL error: {e}\nSchema:\n{ctx.deps.dbml}") from e
```
