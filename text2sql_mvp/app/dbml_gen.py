"""DBML generator from meta-schema rows.

Produces clean DBML text compatible with dbdiagram.io.
No external packages required.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.engine import Connection

from .meta_schema import column_registry, table_registry


def generate_dbml(
    conn: Connection,
    table_names: list[str],
    include_notes: bool = True,
) -> str:
    """Generate DBML for the given list of table names.

    Args:
        conn: SQLAlchemy connection to the meta-schema database.
        table_names: Only generate Table blocks for these tables.
        include_notes: If True, emit ``note:`` fields for column/table descriptions.

    Returns:
        A DBML string ready to paste into dbdiagram.io.
    """
    blocks: list[str] = []
    ref_lines: list[str] = []

    for tname in table_names:
        trow = conn.execute(
            select(table_registry).where(table_registry.c.table_name == tname)
        ).mappings().first()
        if trow is None:
            continue

        cols = conn.execute(
            select(column_registry)
            .where(column_registry.c.table_id == trow["id"])
            .order_by(column_registry.c.id)
        ).mappings().all()

        lines: list[str] = [f"Table {tname} {{"]

        for col in cols:
            parts: list[str] = [col["column_name"], col["data_type"]]
            constraints: list[str] = []

            if col["is_pk"]:
                constraints.append("primary key")
                constraints.append("increment")
            if col["is_fk"] and col["fk_references"]:
                constraints.append(f"ref: > {col['fk_references']}")
            if not col["is_pk"] and col["data_type"].startswith("varchar"):
                pass  # no default constraint for varchar unless specified
            if include_notes and col["description"]:
                safe_desc = col["description"].replace("'", "\\'")
                constraints.append(f"note: '{safe_desc}'")

            if constraints:
                parts.append(f"[{', '.join(constraints)}]")

            # Pad for readability
            lines.append("  " + "  ".join(parts))

        if include_notes and trow["description"]:
            safe_tdesc = trow["description"].replace("'", "\\'")
            lines.append("")
            lines.append(f"  note: '{safe_tdesc}'")

        lines.append("}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def generate_full_dbml(conn: Connection, include_notes: bool = True) -> str:
    """Generate DBML for all tables registered in the meta-schema."""
    rows = conn.execute(select(table_registry.c.table_name)).all()
    all_names = [r[0] for r in rows]
    return generate_dbml(conn, all_names, include_notes=include_notes)
