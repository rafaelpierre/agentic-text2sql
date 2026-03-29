"""Typer CLI entrypoint for the Text2SQL MVP."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

import typer
from sqlalchemy import text

# Ensure the project root is on the path when running directly
sys.path.insert(0, str(Path(__file__).parent))

from text2sql_mvp.app.db import create_schemas, get_engine
from text2sql_mvp.app.dbml_gen import generate_dbml, generate_full_dbml
from text2sql_mvp.app.fts import build_fts_index
from text2sql_mvp.app.log import configure_logging
from text2sql_mvp.app.meta_schema import create_meta_tables
from text2sql_mvp.app.seed_data import seed_data
from text2sql_mvp.app.seed_meta import seed_meta
from text2sql_mvp.app.text2sql import run_pipeline

configure_logging()

app = typer.Typer(help="Agentic Text2SQL — Schema Retrieval MVP")
dbml_app = typer.Typer(help="DBML generation commands")
app.add_typer(dbml_app, name="dbml")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine():
    return get_engine()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command("seed-meta")
def cmd_seed_meta():
    """Populate meta-schema with e-commerce table/column descriptions."""
    engine = _engine()
    create_schemas(engine)
    with engine.begin() as conn:
        seed_meta(conn)
    typer.echo("Meta-schema seeded successfully.")


@app.command("seed-data")
def cmd_seed_data():
    """Insert dummy e-commerce rows into the data schema."""
    engine = _engine()
    create_schemas(engine)
    with engine.begin() as conn:
        seed_data(conn)
    typer.echo("Data schema seeded with dummy rows.")


@app.command("build-fts")
def cmd_build_fts():
    """Create / refresh FTS5 virtual tables (SQLite) or tsvector indexes (Postgres)."""
    engine = _engine()
    with engine.begin() as conn:
        build_fts_index(conn)
    typer.echo("FTS index built successfully.")


@app.command("search")
def cmd_search(
    query: str = typer.Argument(..., help="Natural-language search query"),
    top_k: int = typer.Option(5, help="Number of results per FTS search"),
):
    """Run BM25 FTS search and print matching tables/columns with scores."""
    from text2sql_mvp.app.fts import search_columns, search_tables

    engine = _engine()
    with engine.connect() as conn:
        typer.echo(f"\nSearching for: {query!r}\n")
        typer.echo("=== Tables ===")
        for m in search_tables(conn, query, top_k=top_k):
            typer.echo(f"  [{m.score:+.4f}]  {m.table_name}  (id={m.table_id})")
        typer.echo("\n=== Columns ===")
        for m in search_columns(conn, query, top_k=top_k):
            typer.echo(f"  [{m.score:+.4f}]  {m.column_name}  (table_id={m.table_id})")


@dbml_app.command("export")
def cmd_dbml_export(
    tables: Optional[str] = typer.Option(
        None, "--tables", help="Comma-separated list of table names (default: all)"
    ),
    no_notes: bool = typer.Option(False, "--no-notes", help="Omit column/table notes"),
):
    """Print DBML schema to stdout."""
    engine = _engine()
    with engine.connect() as conn:
        if tables:
            names = [t.strip() for t in tables.split(",")]
            dbml = generate_dbml(conn, names, include_notes=not no_notes)
        else:
            dbml = generate_full_dbml(conn, include_notes=not no_notes)
    typer.echo(dbml)


@app.command("ask")
def cmd_ask(
    question: str = typer.Argument(..., help="Natural-language question"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show pipeline details"),
    no_narrate: bool = typer.Option(False, "--no-narrate", help="Skip plain-English answer"),
):
    """Run the full Text2SQL pipeline and print results."""
    result = run_pipeline(question, narrate=not no_narrate, verbose=verbose)

    if verbose:
        typer.echo(f"\nExpanded queries: {result.expanded_queries}")
        typer.echo(f"Retrieved tables: {result.retrieved_tables}")
        typer.echo(f"\nDBML context:\n{result.dbml_context}")
        typer.echo(f"\nGenerated SQL:\n{result.generated_sql}\n")

    if result.error:
        typer.echo(f"[error] {result.error}", err=True)
        raise typer.Exit(1)

    typer.echo(f"\nSQL: {result.generated_sql}\n")
    typer.echo(f"Results ({len(result.rows)} rows):")
    for row in result.rows[:50]:
        typer.echo(f"  {json.dumps(row, default=str)}")

    if result.answer:
        typer.echo(f"\nAnswer: {result.answer}")


if __name__ == "__main__":
    app()
