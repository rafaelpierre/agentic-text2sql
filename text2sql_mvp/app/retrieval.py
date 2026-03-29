"""Query expansion + FTS search + FK-neighbour pull.

Uses pydantic-ai-slim for the LLM query expansion step.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel
from pydantic_ai import Agent
from sqlalchemy import select
from sqlalchemy.engine import Connection

from .fts import search_columns, search_tables
from .log import get_logger
from .meta_schema import column_registry, get_fk_neighbour_table_ids, table_registry

log = get_logger("text2sql.retrieval")

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------
DEFAULT_TOP_K = 5       # FTS results per query
MAX_TABLES = 8          # Hard cap after neighbour expansion
MODEL = os.environ.get("EXPANSION_MODEL", "gpt-5.3-chat")


# ---------------------------------------------------------------------------
# Pydantic model for structured query expansion output
# ---------------------------------------------------------------------------

class QueryExpansion(BaseModel):
    queries: list[str]


# ---------------------------------------------------------------------------
# LLM-based query expansion
# ---------------------------------------------------------------------------

_expansion_agent: Agent[None, QueryExpansion] | None = None


def _get_expansion_agent() -> Agent[None, QueryExpansion]:
    global _expansion_agent
    if _expansion_agent is None:
        _expansion_agent = Agent(
            model=f"azure:{MODEL}",
            output_type=QueryExpansion,
            system_prompt=(
                "You are a database search assistant. Given a user question about "
                "an e-commerce database, output 2-3 short search queries (3-6 words each) "
                "that would find the relevant tables and columns. "
                "Return ONLY a JSON object with a 'queries' key containing an array of strings."
            ),
        )
    return _expansion_agent


def expand_queries(question: str) -> list[str]:
    """Use LLM to expand a natural-language question into 2–3 FTS search queries."""
    log.info("🔍 Expanding question into search queries...")
    t0 = time.perf_counter()
    agent = _get_expansion_agent()
    result = agent.run_sync(question)
    usage = result.usage()
    queries = result.output.queries[:3]  # cap at 3
    log.info(
        "   ↳ done in %.2fs | tokens: %d in / %d out / %d total | queries: %s",
        time.perf_counter() - t0,
        usage.input_tokens,
        usage.output_tokens,
        usage.total_tokens,
        queries,
    )
    return queries


def expand_queries_stub(question: str) -> list[str]:
    """Deterministic stub for testing — no LLM call."""
    words = question.lower().split()
    return [question, " ".join(words[:4]), " ".join(words[-4:])]


# ---------------------------------------------------------------------------
# Core retrieval pipeline
# ---------------------------------------------------------------------------

@dataclass
class RetrievalResult:
    table_names: list[str]
    table_ids: list[int]
    expanded_queries: list[str]
    fts_table_ids: set[int] = field(default_factory=set)
    neighbour_table_ids: set[int] = field(default_factory=set)


def retrieve_tables(
    conn: Connection,
    question: str,
    top_k: int = DEFAULT_TOP_K,
    max_tables: int = MAX_TABLES,
    query_expander: Callable[[str], list[str]] | None = None,
) -> RetrievalResult:
    """Full retrieval: expand → search → neighbour pull → resolve names.

    Args:
        conn: SQLAlchemy connection (meta-schema must be seeded + FTS built).
        question: Natural-language user question.
        top_k: FTS results per expanded query.
        max_tables: Hard cap on total tables after neighbour expansion.
        query_expander: Override for query expansion (default: LLM via pydantic-ai).

    Returns:
        RetrievalResult with resolved table names and ids.
    """
    expander = query_expander or expand_queries
    expanded = expander(question)
    log.debug("Expanded queries: %s", expanded)

    # --- FTS search across all expanded queries ---
    log.info("📚 Running FTS search across %d expanded queries...", len(expanded))
    t0 = time.perf_counter()
    fts_table_ids: set[int] = set()
    for q in expanded:
        for match in search_tables(conn, q, top_k=top_k):
            log.debug("  table hit [%.4f] %s (id=%d)", match.score, match.table_name, match.table_id)
            fts_table_ids.add(match.table_id)
        for col_match in search_columns(conn, q, top_k=top_k):
            log.debug("  column hit [%.4f] %s (table_id=%d)", col_match.score, col_match.column_name, col_match.table_id)
            fts_table_ids.add(col_match.table_id)
    log.info("   ↳ done in %.2fs | %d table(s) matched", time.perf_counter() - t0, len(fts_table_ids))
    log.debug("FTS matched table ids: %s", fts_table_ids)

    # Trim to top max_tables by taking first seen (already score-ordered per query)
    if len(fts_table_ids) > max_tables:
        fts_table_ids = set(list(fts_table_ids)[:max_tables])

    # --- FK neighbour expansion ---
    log.info("🔗 Expanding via FK neighbours...")
    t0 = time.perf_counter()
    neighbours = get_fk_neighbour_table_ids(conn, list(fts_table_ids))
    log.info("   ↳ done in %.2fs | %d neighbour(s) added", time.perf_counter() - t0, len(neighbours - fts_table_ids))
    log.debug("FK neighbour table ids: %s", neighbours)
    combined = fts_table_ids | neighbours

    if len(combined) > max_tables:
        # Prioritise original FTS hits; add neighbours until cap reached
        ordered = list(fts_table_ids) + [n for n in neighbours if n not in fts_table_ids]
        combined = set(ordered[:max_tables])

    # --- Resolve table IDs to names ---
    rows = conn.execute(
        select(table_registry.c.id, table_registry.c.table_name).where(
            table_registry.c.id.in_(combined)
        )
    ).all()
    id_to_name = {r[0]: r[1] for r in rows}
    table_ids = list(combined)
    table_names = [id_to_name[tid] for tid in table_ids if tid in id_to_name]

    log.info("✅ Retrieved tables: %s", table_names)

    return RetrievalResult(
        table_names=table_names,
        table_ids=table_ids,
        expanded_queries=expanded,
        fts_table_ids=fts_table_ids,
        neighbour_table_ids=neighbours,
    )
