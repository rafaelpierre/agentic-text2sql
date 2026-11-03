"""SQLAlchemy engine factory — supports SQLite and PostgreSQL.

SQLite schema support:
  SQLite doesn't have built-in named schemas.  We use SQLite's ATTACH DATABASE
  feature to create two extra databases named 'meta' and 'ecommerce'.

  * File-based (default):  text2sql_meta.db  /  text2sql_ecommerce.db
  * In-memory (tests):  ATTACH ':memory:' AS meta / ecommerce
    Uses StaticPool so all engine.connect() calls share the same underlying
    DBAPI connection — the ATTACHed in-memory databases therefore persist for
    the engine's lifetime.
"""
from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


def _db_url() -> str:
    return os.environ.get("DB_URL", "sqlite:///./text2sql.db")


def _make_sqlite_engine(url: str) -> Engine:
    is_memory = ":memory:" in url
    if is_memory:
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _attach_schemas(dbapi_conn, _conn_record):
        if is_memory:
            dbapi_conn.execute("ATTACH DATABASE ':memory:' AS meta")
            dbapi_conn.execute("ATTACH DATABASE ':memory:' AS ecommerce")
        else:
            raw_path = url.replace("sqlite:///", "").replace("sqlite://", "")
            base = os.path.splitext(raw_path)[0]
            dbapi_conn.execute(f"ATTACH DATABASE '{base}_meta.db' AS meta")
            dbapi_conn.execute(f"ATTACH DATABASE '{base}_ecommerce.db' AS ecommerce")

    return engine


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = _db_url()
    if url.startswith("sqlite"):
        return _make_sqlite_engine(url)
    return create_engine(url, pool_pre_ping=True)


def make_engine(url: str) -> Engine:
    """Create a fresh (uncached) engine — used by tests and the CLI."""
    if url.startswith("sqlite"):
        return _make_sqlite_engine(url)
    return create_engine(url, pool_pre_ping=True)


def dialect(engine: Engine | None = None) -> str:
    """Return 'sqlite' or 'postgresql'."""
    e = engine or get_engine()
    return e.dialect.name


def create_schemas(engine: Engine | None = None) -> None:
    """Create PostgreSQL schemas (meta, ecommerce). No-op for SQLite."""
    e = engine or get_engine()
    if dialect(e) == "postgresql":
        with e.begin() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS meta"))
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS ecommerce"))
