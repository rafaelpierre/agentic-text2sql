"""BM25 / FTS index build and search functions.

Supports:
- SQLite FTS5 (default, zero config)
- PostgreSQL tsvector + GIN indexes
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .db import dialect


# ---------------------------------------------------------------------------
# Lemmatization helper
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _lemmatizer():
    from nltk.stem import WordNetLemmatizer
    return WordNetLemmatizer()


def lemmatize(text_: str) -> str:
    """Lowercase, tokenize, lemmatize each word, and rejoin."""
    lem = _lemmatizer()
    tokens = re.findall(r"[a-zA-Z0-9_]+", text_.lower())
    return " ".join(lem.lemmatize(t) for t in tokens)



@dataclass
class TableMatch:
    table_id: int
    table_name: str
    score: float


@dataclass
class ColumnMatch:
    column_id: int
    table_id: int
    column_name: str
    score: float


# ---------------------------------------------------------------------------
# FTS index creation
# ---------------------------------------------------------------------------

def build_fts_index(conn: Connection) -> None:
    d = dialect(conn.engine)
    if d == "sqlite":
        _build_fts_sqlite(conn)
    else:
        _build_fts_postgres(conn)


def _build_fts_sqlite(conn: Connection) -> None:
    conn.execute(text("DROP TABLE IF EXISTS fts_tables"))
    conn.execute(text("DROP TABLE IF EXISTS fts_columns"))

    conn.execute(text("""
        CREATE VIRTUAL TABLE fts_tables USING fts5(
            table_id UNINDEXED,
            table_name UNINDEXED,
            search_doc,
            tokenize='unicode61'
        )
    """))
    conn.execute(text("""
        CREATE VIRTUAL TABLE fts_columns USING fts5(
            column_id UNINDEXED,
            table_id UNINDEXED,
            column_name UNINDEXED,
            search_doc,
            tokenize='unicode61'
        )
    """))

    # SQLite views cannot reference ATTACHed databases, so we populate FTS
    # tables programmatically by reading directly from the meta schema.
    tbl_rows = conn.execute(
        text("SELECT id, table_name, search_doc FROM meta.table_registry")
    ).fetchall()
    for tid, tname, sdoc in tbl_rows:
        conn.execute(
            text("INSERT INTO fts_tables(table_id, table_name, search_doc) VALUES (:tid, :tn, :sd)"),
            {"tid": tid, "tn": tname, "sd": lemmatize(sdoc)},
        )

    col_rows = conn.execute(
        text("SELECT id, table_id, column_name, search_doc FROM meta.column_registry")
    ).fetchall()
    for cid, tid, cname, sdoc in col_rows:
        conn.execute(
            text("INSERT INTO fts_columns(column_id, table_id, column_name, search_doc) VALUES (:cid, :tid, :cn, :sd)"),
            {"cid": cid, "tid": tid, "cn": cname, "sd": lemmatize(sdoc)},
        )


def _build_fts_postgres(conn: Connection) -> None:
    # Add tsvector columns if they don't exist
    conn.execute(text("""
        ALTER TABLE meta.table_registry
        ADD COLUMN IF NOT EXISTS search_vec tsvector
        GENERATED ALWAYS AS (to_tsvector('english', search_doc)) STORED
    """))
    conn.execute(text("""
        ALTER TABLE meta.column_registry
        ADD COLUMN IF NOT EXISTS search_vec tsvector
        GENERATED ALWAYS AS (to_tsvector('english', search_doc)) STORED
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_table_registry_search_vec
        ON meta.table_registry USING GIN(search_vec)
    """))
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_column_registry_search_vec
        ON meta.column_registry USING GIN(search_vec)
    """))


# ---------------------------------------------------------------------------
# Search functions — same interface for both backends
# ---------------------------------------------------------------------------

def search_tables(conn: Connection, query: str, top_k: int = 5) -> list[TableMatch]:
    d = dialect(conn.engine)
    if d == "sqlite":
        return _search_tables_sqlite(conn, query, top_k)
    return _search_tables_postgres(conn, query, top_k)


def search_columns(conn: Connection, query: str, top_k: int = 5) -> list[ColumnMatch]:
    d = dialect(conn.engine)
    if d == "sqlite":
        return _search_columns_sqlite(conn, query, top_k)
    return _search_columns_postgres(conn, query, top_k)


# -- SQLite implementations --

def _search_tables_sqlite(conn: Connection, query: str, top_k: int) -> list[TableMatch]:
    safe_query = _escape_fts5(lemmatize(query))
    rows = conn.execute(
        text("""
            SELECT table_id, table_name, bm25(fts_tables) AS score
            FROM fts_tables
            WHERE fts_tables MATCH :q
            ORDER BY score
            LIMIT :k
        """),
        {"q": safe_query, "k": top_k},
    ).fetchall()
    return [TableMatch(table_id=r[0], table_name=r[1], score=r[2]) for r in rows]


def _search_columns_sqlite(conn: Connection, query: str, top_k: int) -> list[ColumnMatch]:
    safe_query = _escape_fts5(lemmatize(query))
    rows = conn.execute(
        text("""
            SELECT column_id, table_id, column_name, bm25(fts_columns) AS score
            FROM fts_columns
            WHERE fts_columns MATCH :q
            ORDER BY score
            LIMIT :k
        """),
        {"q": safe_query, "k": top_k},
    ).fetchall()
    return [ColumnMatch(column_id=r[0], table_id=r[1], column_name=r[2], score=r[3]) for r in rows]


def _escape_fts5(query: str) -> str:
    """Wrap each token in double quotes to avoid FTS5 syntax errors."""
    tokens = query.split()
    escaped = " ".join(f'"{t}"' for t in tokens if t)
    return escaped if escaped else '""'


# -- PostgreSQL implementations --

def _search_tables_postgres(conn: Connection, query: str, top_k: int) -> list[TableMatch]:
    rows = conn.execute(
        text("""
            SELECT id, table_name,
                   ts_rank_cd(search_vec, plainto_tsquery('english', :q)) AS score
            FROM meta.table_registry
            WHERE search_vec @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :k
        """),
        {"q": query, "k": top_k},
    ).fetchall()
    return [TableMatch(table_id=r[0], table_name=r[1], score=r[2]) for r in rows]


def _search_columns_postgres(conn: Connection, query: str, top_k: int) -> list[ColumnMatch]:
    rows = conn.execute(
        text("""
            SELECT id, table_id, column_name,
                   ts_rank_cd(search_vec, plainto_tsquery('english', :q)) AS score
            FROM meta.column_registry
            WHERE search_vec @@ plainto_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :k
        """),
        {"q": query, "k": top_k},
    ).fetchall()
    return [ColumnMatch(column_id=r[0], table_id=r[1], column_name=r[2], score=r[3]) for r in rows]


