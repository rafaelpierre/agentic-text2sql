"""Meta-schema table definitions (schema_registry, table_registry, column_registry)."""
from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    select,
)
from sqlalchemy.engine import Connection

# SQLite ignores the schema= kwarg gracefully; Postgres uses it.
META = MetaData()

schema_registry = Table(
    "schema_registry",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("schema_name", Text, nullable=False, unique=True),
    Column("overview", Text, nullable=False),
    schema="meta",
)

table_registry = Table(
    "table_registry",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("schema_id", Integer, ForeignKey("meta.schema_registry.id"), nullable=False),
    Column("table_name", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("search_doc", Text, nullable=False),
    schema="meta",
)

column_registry = Table(
    "column_registry",
    META,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("table_id", Integer, ForeignKey("meta.table_registry.id"), nullable=False),
    Column("column_name", Text, nullable=False),
    Column("data_type", Text, nullable=False),
    Column("is_pk", Boolean, nullable=False, default=False),
    Column("is_fk", Boolean, nullable=False, default=False),
    Column("fk_references", Text, nullable=True),
    Column("description", Text, nullable=False),
    Column("search_doc", Text, nullable=False),
    schema="meta",
)


def create_meta_tables(conn: Connection) -> None:
    META.create_all(conn, checkfirst=True)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_table_by_name(conn: Connection, table_name: str) -> dict | None:
    row = conn.execute(
        select(table_registry).where(table_registry.c.table_name == table_name)
    ).mappings().first()
    return dict(row) if row else None


def get_columns_for_table(conn: Connection, table_id: int) -> list[dict]:
    rows = conn.execute(
        select(column_registry).where(column_registry.c.table_id == table_id)
    ).mappings().all()
    return [dict(r) for r in rows]


def get_all_table_names(conn: Connection) -> list[str]:
    rows = conn.execute(select(table_registry.c.table_name)).all()
    return [r[0] for r in rows]


def get_fk_neighbour_table_ids(conn: Connection, table_ids: list[int]) -> set[int]:
    """Return table_ids that are FK targets/sources of the given set."""
    if not table_ids:
        return set()
    rows = conn.execute(
        select(column_registry.c.table_id, column_registry.c.fk_references).where(
            column_registry.c.is_fk == True  # noqa: E712
        )
    ).all()

    name_to_id: dict[str, int] = {}
    all_rows = conn.execute(
        select(table_registry.c.id, table_registry.c.table_name)
    ).all()
    for tid, tname in all_rows:
        name_to_id[tname] = tid

    neighbours: set[int] = set()
    for row_table_id, fk_ref in rows:
        if fk_ref is None:
            continue
        ref_table = fk_ref.split(".")[0]
        ref_id = name_to_id.get(ref_table)
        if ref_id is None:
            continue
        # If this column's table is in our set → add the FK target
        if row_table_id in table_ids:
            neighbours.add(ref_id)
        # If the FK target is in our set → add the source table
        if ref_id in table_ids:
            neighbours.add(row_table_id)
    return neighbours
