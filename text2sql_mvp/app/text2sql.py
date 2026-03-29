"""End-to-end Text2SQL pipeline — two-agent async architecture using pydantic-ai.

Architecture
------------
schema_agent  — researches the database schema.
                Tools: fts_search, get_dbml_context
                Output: SchemaContext(table_names, dbml)

sql_agent     — orchestrates the full pipeline.
                Tools:
                  • research_schema  — calls schema_agent (agent-as-tool pattern)
                  • execute_sql      — runs SQL; raises ModelRetry on OperationalError
                Output: SQLResult(sql)   (rows stored in PipelineDeps, not in LLM output)

answer_agent  — narrates plain-English answer. No tools.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import OperationalError

from .db import dialect, get_engine
from .dbml_gen import generate_dbml
from .fts import lemmatize, search_columns, search_tables
from .log import configure_logging, get_logger
from .meta_schema import get_fk_neighbour_table_ids, table_registry

# asyncio.to_thread needs a callable — we defer heavy sync calls to the thread pool
# so that parallel tool invocations by the model actually run concurrently.

log = get_logger("text2sql.pipeline")

# FAST_MODEL  — lightweight tasks: query expansion, answer narration  (nano/mini class)
# SQL_MODEL   — SQL generation + execution  (full reasoning model)
FAST_MODEL = os.environ.get("FAST_MODEL", "gpt-5.4-nano")
SQL_MODEL = os.environ.get("SQL_MODEL", "gpt-5.3-chat")
ANSWER_MODEL = os.environ.get("ANSWER_MODEL", FAST_MODEL)   # default to fast model
SCHEMA_MODEL = os.environ.get("SCHEMA_MODEL", FAST_MODEL)   # reserved for future LLM fallback

# Latency knobs — tune via env vars
# REASONING_EFFORT: 'low'|'medium'|'high'  (default: 'low')
# MAX_TOKENS_SQL / MAX_TOKENS_ANSWER: integer token caps
_REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "low").strip() or None
_MAX_TOKENS_SQL = int(os.environ.get("MAX_TOKENS_SQL", "1024"))
_MAX_TOKENS_ANSWER = int(os.environ.get("MAX_TOKENS_ANSWER", "300"))


def _model_settings(max_tokens: int) -> dict:
    """Build a model_settings dict with optional reasoning effort + token cap."""
    s: dict = {"max_tokens": max_tokens}
    if _REASONING_EFFORT:
        s["openai_reasoning_effort"] = _REASONING_EFFORT
    return s


# ---------------------------------------------------------------------------
# Shared deps — passed to both agents; mutable so tools can write back results
# ---------------------------------------------------------------------------

@dataclass
class PipelineDeps:
    conn: Connection
    db_dialect: str
    # Written by execute_sql tool so full rows bypass LLM output token limit
    rows: list[dict[str, Any]] = field(default_factory=list)
    retrieved_tables: list[str] = field(default_factory=list)
    dbml_context: str = ""


def _json_default(obj: Any) -> Any:
    """JSON serialiser for SQLAlchemy row values (Decimal, date, etc.)."""
    if isinstance(obj, Decimal):
        return float(obj)
    return str(obj)


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------

class SQLResult(BaseModel):
    sql: str


class NarratedAnswer(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# Fast-path schema lookup: parallel FTS → score-rank → FK expand → DBML
# ---------------------------------------------------------------------------

class _QueryExpansion(BaseModel):
    queries: list[str]


_expansion_agent: Agent[None, _QueryExpansion] | None = None


def _get_expansion_agent() -> Agent[None, _QueryExpansion]:
    global _expansion_agent
    if _expansion_agent is None:
        _expansion_agent = Agent(
            model=f"azure:{FAST_MODEL}",
            output_type=_QueryExpansion,
            model_settings={"max_tokens": 150},
            system_prompt=(
                "Output 2-3 short FTS search queries (2-4 words each) for finding "
                "relevant database tables. Use nouns and domain terms only — no verbs, "
                "no stopwords, no articles. Return JSON: {\"queries\": [\"...\", ...]}"
            ),
        )
    return _expansion_agent


async def _llm_expand_queries(question: str) -> list[str]:
    """Use a tiny LLM call (~60 tokens) to extract noun-phrase FTS queries."""
    t0 = time.perf_counter()
    try:
        result = await _get_expansion_agent().run(question)
        queries = [q.strip() for q in result.output.queries if q.strip()][:3]
        log.info(
            "   [expand] %r -> %s (%.2fs, %d tokens)",
            question, queries, time.perf_counter() - t0, result.usage().total_tokens,
        )
        return queries or [question]
    except Exception as exc:
        log.warning("   [expand] LLM failed (%s), using fallback", exc)
        return _noun_fallback(question)


def _noun_fallback(question: str) -> list[str]:
    """Deterministic fallback: strip stopwords, lemmatize, return content words."""
    try:
        from nltk.corpus import stopwords as _sw
        stop = set(_sw.words("english"))
    except Exception:
        stop = set()
    tokens = re.findall(r"[a-zA-Z0-9_]+", question.lower())
    content = list(dict.fromkeys(
        lemmatize(t) for t in tokens if t not in stop and len(t) > 2
    ))
    return [" ".join(content)] if content else [question]

async def _fast_schema_lookup(question: str, conn: Connection) -> tuple[list[str], str]:
    """Run FTS in parallel on LLM-expanded noun queries, merge BM25 scores,
    pick top tables, FK-expand, return (table_names, dbml)."""
    queries = await _llm_expand_queries(question)

    async def _fts_one(query: str) -> dict[int, float]:
        """Run FTS for one query in a thread. Returns {table_id: best_score}."""
        def _sync() -> dict[int, float]:
            scores: dict[int, float] = {}
            with get_engine().connect() as c:
                for m in search_tables(c, query, top_k=5):
                    if m.table_id not in scores or m.score < scores[m.table_id]:
                        scores[m.table_id] = m.score
                for m in search_columns(c, query, top_k=5):
                    if m.table_id not in scores or m.score < scores[m.table_id]:
                        scores[m.table_id] = m.score
            return scores
        return await asyncio.to_thread(_sync)

    # Run all FTS queries in parallel
    all_score_dicts = await asyncio.gather(*[_fts_one(q) for q in queries])

    # Merge: keep best (lowest BM25) score per table across all queries
    merged: dict[int, float] = {}
    for d in all_score_dicts:
        for tid, score in d.items():
            if tid not in merged or score < merged[tid]:
                merged[tid] = score

    if not merged:
        log.warning("[schema_lookup] FTS returned no results for %r", question)
        return [], ""

    # Sort by score ascending (most negative = strongest match), take top 3
    top_ids = [tid for tid, _ in sorted(merged.items(), key=lambda x: x[1])[:3]]

    def _build_dbml() -> tuple[list[str], list[str], str]:
        with get_engine().connect() as c:
            # FK neighbour expansion from the top tables only
            all_ids = set(top_ids) | get_fk_neighbour_table_ids(c, top_ids)
            rows = c.execute(
                select(table_registry.c.id, table_registry.c.table_name).where(
                    table_registry.c.id.in_(all_ids)
                )
            ).all()
            id_to_name = {r[0]: r[1] for r in rows}
            top_names = [id_to_name[tid] for tid in top_ids if tid in id_to_name]
            all_names = [id_to_name[tid] for tid in all_ids if tid in id_to_name]
            dbml = generate_dbml(c, all_names, include_notes=True)
        return top_names, all_names, dbml

    top_names, all_names, dbml = await asyncio.to_thread(_build_dbml)
    log.info(
        "   [schema_lookup] queries: %s | top tables: %s | with FK neighbours: %s | %d chars",
        queries, top_names, all_names, len(dbml),
    )
    return all_names, dbml


# ---------------------------------------------------------------------------
# Agent 2 — SQL Generation + Execution Agent (lazy singleton)
# ---------------------------------------------------------------------------

_sql_agent: Agent[PipelineDeps, SQLResult] | None = None


def _get_sql_agent() -> Agent[PipelineDeps, SQLResult]:
    global _sql_agent
    if _sql_agent is None:
        _sql_agent = Agent(
            model=f"azure:{SQL_MODEL}",
            deps_type=PipelineDeps,
            output_type=SQLResult,
            retries=3,
            model_settings=_model_settings(_MAX_TOKENS_SQL),
            system_prompt=(
                "You are a SQL generation and execution expert. "
                "You will be given the DBML schema for relevant tables as context.\n\n"
                "COLUMN SELECTION RULES:\n"
                "- Never use SELECT *. Always list explicit columns.\n"
                "- For users/customers: prefer first_name, last_name, email over username.\n"
                "- Include all relevant identifying columns (id, name/sku/brand/category) "
                "plus any metrics the question asks about.\n\n"
                "ORDERING RULES:\n"
                "- Always add ORDER BY when results have a natural ranking: "
                "totals/sums/counts/prices sorted DESC, unless the question implies otherwise.\n\n"
                "EXECUTION RULES:\n"
                "- Use ONLY exact table and column names from the schema.\n"
                "- Call execute_sql to run the query.\n"
                "- If it errors, fix column/table names from the schema and retry immediately.\n"
                "- Return the final SQL string in the 'sql' field."
            ),
        )
        _sql_agent.tool(execute_sql)
    return _sql_agent


async def research_schema(ctx: RunContext[PipelineDeps], question: str) -> str:
    # kept for backward compat but no longer registered as a tool
    raise NotImplementedError


async def execute_sql(ctx: RunContext[PipelineDeps], sql: str) -> str:
    """Execute a SQL SELECT query against the database.
    Returns row count and up to 20 sample rows as JSON.
    Raises an error message if SQL is invalid — read it and fix column/table names."""
    log.info("   [execute_sql] Running: %s", sql)
    t0 = time.perf_counter()
    try:
        result = ctx.deps.conn.execute(text(sql))
        keys = list(result.keys())
        rows = [dict(zip(keys, row)) for row in result.fetchall()]
        # Store full rows in deps — bypasses LLM output token limit
        ctx.deps.rows = rows
        elapsed = time.perf_counter() - t0
        log.info("   [execute_sql] done in %.2fs | %d row(s)", elapsed, len(rows))
        sample = json.loads(json.dumps(rows[:20], default=_json_default))
        return json.dumps({"success": True, "row_count": len(rows), "sample_rows": sample})
    except OperationalError as exc:
        elapsed = time.perf_counter() - t0
        msg = str(exc).split("\n")[0]
        log.warning("   [execute_sql] error (%.2fs) — retrying: %s", elapsed, msg)
        raise ModelRetry(
            f"SQL execution failed: {msg}. "
            "Check the DBML schema from research_schema and use only exact table "
            "and column names that appear there. Do not invent column names."
        )


# ---------------------------------------------------------------------------
# Answer agent — simple narration, no tools, no deps
# ---------------------------------------------------------------------------

_answer_agent: Agent[None, NarratedAnswer] | None = None


def _get_answer_agent() -> Agent[None, NarratedAnswer]:
    global _answer_agent
    if _answer_agent is None:
        _answer_agent = Agent(
            model=f"azure:{ANSWER_MODEL}",
            output_type=NarratedAnswer,            model_settings=_model_settings(_MAX_TOKENS_ANSWER),            system_prompt=(
                "You are a helpful data analyst. Given a SQL query result, "
                "write a concise plain-English answer to the user's original question. "
                "Return a JSON object with an 'answer' key."
            ),
        )
    return _answer_agent


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------

@dataclass
class PipelineResult:
    question: str
    expanded_queries: list[str]
    retrieved_tables: list[str]
    dbml_context: str
    generated_sql: str
    rows: list[dict[str, Any]]
    answer: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Async pipeline core
# ---------------------------------------------------------------------------

async def _run_async(
    question: str,
    conn: Connection,
    db_dialect: str,
    narrate: bool,
) -> PipelineResult:
    pipeline_start = time.perf_counter()
    deps = PipelineDeps(conn=conn, db_dialect=db_dialect)

    # Step 1 — Fast schema lookup (pure Python, no LLM)
    log.info("📐 Step 1 — Schema lookup (parallel FTS + FK expand)...")
    t0 = time.perf_counter()
    table_names, dbml = await _fast_schema_lookup(question, conn)
    deps.retrieved_tables = table_names
    deps.dbml_context = dbml
    log.info("   -> done in %.2fs | tables: %s", time.perf_counter() - t0, table_names)

    if not dbml:
        return PipelineResult(
            question=question, expanded_queries=[], retrieved_tables=[],
            dbml_context="", generated_sql="", rows=[],
            error="Schema lookup returned no tables. FTS index may need rebuilding.",
        )

    # Step 2 — SQL generation + execution (one LLM agent)
    log.info("🤖 Step 2 — SQL generation + execution...")
    t0 = time.perf_counter()
    error = ""
    generated_sql = ""
    sql_usage = None

    try:
        sql_run = await _get_sql_agent().run(
            f"Question: {question}\n"
            f"Database dialect: {db_dialect}\n\n"
            f"Schema (DBML):\n{dbml}",
            deps=deps,
        )
        sql_usage = sql_run.usage()
        generated_sql = sql_run.output.sql.strip()
        log.info(
            "   -> done in %.2fs | tokens: %d in / %d out / %d total",
            time.perf_counter() - t0,
            sql_usage.input_tokens,
            sql_usage.output_tokens,
            sql_usage.total_tokens,
        )
        log.info("📝 Generated SQL: %s", generated_sql)
        log.info("✅ %d row(s) in result", len(deps.rows))
    except Exception as exc:
        error = str(exc)
        log.error("❌ Agent failed: %s", error)

    # Narrate
    answer = ""
    narration_usage = None
    if narrate and not error:
        log.info("💬 Narrating answer with LLM (%s)...", ANSWER_MODEL)
        t0 = time.perf_counter()
        sample = json.loads(json.dumps(deps.rows[:20], default=_json_default))
        narration_prompt = (
            f"Question: {question}\n\n"
            f"SQL: {generated_sql}\n\n"
            f"Result ({len(deps.rows)} rows): {sample}"
        )
        narration = await _get_answer_agent().run(narration_prompt)
        narration_usage = narration.usage()
        answer = narration.output.answer
        log.info(
            "   -> done in %.2fs | tokens: %d in / %d out",
            time.perf_counter() - t0,
            narration_usage.input_tokens,
            narration_usage.output_tokens,
        )

    total_in = (sql_usage.input_tokens if sql_usage else 0) + (narration_usage.input_tokens if narration_usage else 0)
    total_out = (sql_usage.output_tokens if sql_usage else 0) + (narration_usage.output_tokens if narration_usage else 0)
    log.info(
        "🏁 Pipeline complete in %.2fs | total tokens: %d in / %d out",
        time.perf_counter() - pipeline_start,
        total_in,
        total_out,
    )

    return PipelineResult(
        question=question,
        expanded_queries=[],
        retrieved_tables=deps.retrieved_tables,
        dbml_context=deps.dbml_context,
        generated_sql=generated_sql,
        rows=deps.rows,
        answer=answer,
        error=error,
    )


# ---------------------------------------------------------------------------
# Public sync entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    question: str,
    conn: Connection | None = None,
    narrate: bool = True,
    verbose: bool = False,
) -> PipelineResult:
    """Run the full Text2SQL pipeline (sync entry point)."""
    import logging
    configure_logging(logging.DEBUG if verbose else logging.INFO)
    log.info("🚀 Starting Text2SQL pipeline for: %r", question)

    engine = get_engine()
    db_dialect = dialect(engine)
    log.debug("Database dialect: %s", db_dialect)

    async def _run(c: Connection) -> PipelineResult:
        return await _run_async(question, c, db_dialect, narrate)

    if conn is None:
        with engine.connect() as _conn:
            return asyncio.run(_run(_conn))
    return asyncio.run(_run(conn))
