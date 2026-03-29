---
name: pipeline-architecture
description: >
  Domain knowledge for the agentic-text2sql 4-stage pipeline. Use when working on
  run_pipeline, PipelineDeps, text2sql.py, stage integration, model routing,
  query expansion, ModelRetry, SQL agent, answer narration, or any env-var tuning
  (FAST_MODEL, SQL_MODEL, REASONING_EFFORT, MAX_TOKENS_SQL, MAX_TOKENS_ANSWER).
  Trigger phrases: pipeline, run_pipeline, PipelineDeps, SQL agent, query expansion,
  model routing, ModelRetry, narration, FAST_MODEL, SQL_MODEL.
argument-hint: "Stage or component to work on (e.g. 'SQL agent', 'query expansion')"
---

# Pipeline Architecture

## Overview

Four sequential async stages in `text2sql_mvp/app/text2sql.py`. Entry point: `run_pipeline(question, conn)`.

```
Stage 1 – Query Expansion       ~1s    FAST_MODEL    LLM
Stage 2 – Schema Lookup         <50ms  no LLM        pure-Python FTS
Stage 3 – SQL Agent             ~6-8s  SQL_MODEL     Pydantic AI agent
Stage 4 – Answer Narration      ~1s    ANSWER_MODEL  LLM  (optional)
```

---

## Stage 1 — Query Expansion

**Module**: inline in `text2sql.py` via `_get_expansion_agent()`  
**Model**: `FAST_MODEL` (default `gpt-5.4-nano`)  
**Output type**: `_QueryExpansion(queries: list[str])`  
**Token cap**: `max_tokens=150`

Extracts 2–3 short noun-phrase FTS queries from the user question.  
Fallback: NLTK stopword removal if the LLM call fails.

---

## Stage 2 — Fast Schema Lookup (no LLM)

**Modules**: `fts.py`, `meta_schema.py`, `dbml_gen.py`  
**Steps**:
1. `asyncio.gather` — parallel `search_tables` + `search_columns` per expansion term
2. BM25 score merge → top-3 tables
3. FK-neighbour expansion via `get_fk_neighbour_table_ids()`
4. `generate_dbml(conn, table_names)` → DBML string stored in `PipelineDeps.dbml_context`

Retrieved table names stored in `PipelineDeps.retrieved_tables`.

---

## Stage 3 — SQL Agent

**Module**: inline in `text2sql.py`  
**Model**: `SQL_MODEL` (default `gpt-5.3-chat`)  
**Output type**: `SQLResult(sql: str)`  
**Tools**:
- `research_schema` — calls `schema_agent` as a tool (agent-as-tool pattern); returns `SchemaContext(table_names, dbml)`
- `execute_sql` — runs SQL via `conn.execute(text(sql))`; on `OperationalError` raises `ModelRetry` with the error message so the agent self-corrects

**Retry**: `ModelRetry` on `sqlalchemy.exc.OperationalError` — error message injected back as context.  
**Result rows**: stored in `PipelineDeps.rows`, NOT in the LLM output (bypasses output token limit).

---

## Stage 4 — Answer Narration

**Model**: `ANSWER_MODEL` (default: `FAST_MODEL`)  
**Output type**: `NarratedAnswer(answer: str)`  
**Token cap**: `MAX_TOKENS_ANSWER` (default `300`)  
**Input**: SQL + serialised rows from `PipelineDeps.rows`

Skipped if `narrate=False` is passed to `run_pipeline()`.

---

## PipelineDeps Dataclass

```python
@dataclass
class PipelineDeps:
    conn: Connection          # SQLAlchemy connection (sync)
    db_dialect: str           # "sqlite" | "postgresql"
    rows: list[dict]          # written by execute_sql tool
    retrieved_tables: list[str]
    dbml_context: str
```

Passed as `deps=` to all agent `.run()` calls. Tools receive it via `RunContext[PipelineDeps]`.

---

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `FAST_MODEL` | `gpt-5.4-nano` | Expansion + narration model |
| `SQL_MODEL` | `gpt-5.3-chat` | SQL generation model |
| `ANSWER_MODEL` | `FAST_MODEL` | Narration model override |
| `SCHEMA_MODEL` | `FAST_MODEL` | Reserved for future LLM schema fallback |
| `REASONING_EFFORT` | `low` | `openai_reasoning_effort` for SQL agent |
| `MAX_TOKENS_SQL` | `1024` | Token cap for SQL agent |
| `MAX_TOKENS_ANSWER` | `300` | Token cap for narration |
| `DB_URL` | `sqlite:///./text2sql.db` | SQLAlchemy database URL |

All models are prefixed with `azure:` when passed to Pydantic AI: `f"azure:{SQL_MODEL}"`.

---

## Key Patterns

### Model settings helper
```python
def _model_settings(max_tokens: int) -> dict:
    s = {"max_tokens": max_tokens}
    if _REASONING_EFFORT:
        s["openai_reasoning_effort"] = _REASONING_EFFORT
    return s
```

### ModelRetry on SQL error
```python
try:
    rows = conn.execute(text(sql)).mappings().all()
except OperationalError as e:
    raise ModelRetry(f"SQL error: {e}") from e
```

### Decimal serialisation
`_json_default(obj)` handles `Decimal` → `float`, other → `str` for row serialisation to JSON.

---

## CLI Entry Points

```bash
uv run text2sql ask "Which products are in Electronics?"
uv run text2sql seed-meta
uv run text2sql seed-data
uv run text2sql build-fts
uv run text2sql dbml show
```
