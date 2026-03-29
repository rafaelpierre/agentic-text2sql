"""Shared pytest fixtures — in-memory SQLite database via StaticPool + ATTACH."""
from __future__ import annotations

import pytest
from sqlalchemy.engine import Engine

from text2sql_mvp.app.db import make_engine
from text2sql_mvp.app.fts import build_fts_index
from text2sql_mvp.app.seed_meta import seed_meta


@pytest.fixture(scope="function")
def engine() -> Engine:
    """Fresh in-memory SQLite engine per test (StaticPool — ATTACHed schemas persist)."""
    return make_engine("sqlite:///:memory:")


@pytest.fixture(scope="function")
def seeded_conn(engine):
    """Single connection with meta-schema seeded and FTS index built.

    We use ONE connection for the entire fixture because StaticPool reuses the
    same underlying DBAPI connection — the ATTACHed in-memory databases live
    as long as that connection stays open.
    """
    with engine.begin() as conn:
        seed_meta(conn)
        build_fts_index(conn)

    # Re-open a read connection (StaticPool = same underlying DBAPI conn)
    with engine.connect() as conn:
        yield conn
