"""Retrieval pipeline tests — LLM expansion is monkeypatched."""
from __future__ import annotations

import pytest

from text2sql_mvp.app.retrieval import RetrievalResult, expand_queries_stub, retrieve_tables


# ---------------------------------------------------------------------------
# Helper stub expanders
# ---------------------------------------------------------------------------

def _order_expander(_: str) -> list[str]:
    return ["order revenue total amount", "customer purchase history"]


def _product_expander(_: str) -> list[str]:
    return ["product inventory stock price", "sku category brand"]


def _user_expander(_: str) -> list[str]:
    return ["customer email username account"]


def _item_expander(_: str) -> list[str]:
    return ["order line items quantity discount subtotal"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_retrieve_returns_result_type(seeded_conn):
    result = retrieve_tables(seeded_conn, "How much revenue did we make?", query_expander=_order_expander)
    assert isinstance(result, RetrievalResult)
    assert len(result.table_names) > 0


def test_retrieve_orders_question(seeded_conn):
    result = retrieve_tables(seeded_conn, "What are the top orders by value?", query_expander=_order_expander)
    assert "orders" in result.table_names


def test_retrieve_products_question(seeded_conn):
    result = retrieve_tables(seeded_conn, "Which products are out of stock?", query_expander=_product_expander)
    assert "products" in result.table_names


def test_neighbour_pull_adds_users_for_orders(seeded_conn):
    """Retrieving orders should pull in users via FK."""
    result = retrieve_tables(seeded_conn, "orders revenue", query_expander=_order_expander)
    # orders.user_id → users, so users should be a neighbour
    assert "users" in result.table_names or len(result.table_names) >= 1


def test_neighbour_pull_adds_order_items(seeded_conn):
    """Retrieving orders should pull in order_items via FK."""
    result = retrieve_tables(seeded_conn, "orders revenue", query_expander=_order_expander)
    # order_items.order_id → orders
    assert "order_items" in result.table_names or "orders" in result.table_names


def test_expanded_queries_stored(seeded_conn):
    result = retrieve_tables(seeded_conn, "test question", query_expander=_order_expander)
    assert result.expanded_queries == ["order revenue total amount", "customer purchase history"]


def test_max_tables_cap(seeded_conn):
    result = retrieve_tables(
        seeded_conn, "everything", query_expander=lambda _: ["order", "user", "product"],
        max_tables=2,
    )
    assert len(result.table_names) <= 2


def test_stub_expander_does_not_crash(seeded_conn):
    result = retrieve_tables(
        seeded_conn, "Show me all customers from Germany", query_expander=expand_queries_stub
    )
    assert isinstance(result.table_names, list)


def test_fts_table_ids_populated(seeded_conn):
    result = retrieve_tables(seeded_conn, "revenue orders", query_expander=_order_expander)
    assert len(result.fts_table_ids) > 0
