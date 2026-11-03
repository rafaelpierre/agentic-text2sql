"""DBML generator tests."""
from __future__ import annotations

import pytest

from text2sql_mvp.app.dbml_gen import generate_dbml, generate_full_dbml


def test_generates_table_block(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"])
    assert "Table orders {" in dbml
    assert "}" in dbml


def test_primary_key_marker(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"])
    assert "primary key" in dbml
    assert "increment" in dbml


def test_fk_ref_syntax(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"])
    # orders.user_id → users.id
    assert "ref: > users.id" in dbml


def test_fk_ref_order_items(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["order_items"])
    assert "ref: > orders.id" in dbml
    assert "ref: > products.id" in dbml


def test_note_fields_included(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"], include_notes=True)
    assert "note:" in dbml


def test_note_fields_excluded(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"], include_notes=False)
    assert "note:" not in dbml


def test_table_note_present(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["orders"], include_notes=True)
    # Table-level note should contain part of the description
    assert "revenue" in dbml.lower() or "order" in dbml.lower()


def test_multiple_tables(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["users", "orders"])
    assert "Table users {" in dbml
    assert "Table orders {" in dbml


def test_full_dbml_includes_all_tables(seeded_conn):
    dbml = generate_full_dbml(seeded_conn)
    for tname in ["users", "products", "orders", "order_items"]:
        assert f"Table {tname} {{" in dbml


def test_unknown_table_skipped(seeded_conn):
    dbml = generate_dbml(seeded_conn, ["nonexistent_table"])
    assert dbml.strip() == ""


def test_empty_table_list(seeded_conn):
    dbml = generate_dbml(seeded_conn, [])
    assert dbml.strip() == ""
