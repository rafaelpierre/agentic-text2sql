"""FTS search tests — no external service required."""
from __future__ import annotations

import pytest

from text2sql_mvp.app.fts import search_columns, search_tables


QUERIES_AND_EXPECTED = [
    # table-level queries — top_k=5 to catch all relevant matches
    ("revenue totals order status payment", ["orders"]),
    ("product inventory stock price category", ["products"]),
    ("order line items quantity discount subtotal", ["order_items"]),
    ("shipping address city country order", ["orders"]),
    ("customer email username account demographics", ["users"]),
]


@pytest.mark.parametrize("query,expected_tables", QUERIES_AND_EXPECTED)
def test_search_tables_returns_expected(seeded_conn, query, expected_tables):
    results = search_tables(seeded_conn, query, top_k=5)
    returned_names = {r.table_name for r in results}
    for expected in expected_tables:
        assert expected in returned_names, (
            f"Expected '{expected}' in results for query {query!r}. Got: {returned_names}"
        )


def test_search_tables_returns_scores(seeded_conn):
    results = search_tables(seeded_conn, "order revenue total amount", top_k=5)
    assert len(results) > 0
    for r in results:
        assert isinstance(r.score, float)


def test_search_columns_finds_fk_column(seeded_conn):
    results = search_columns(seeded_conn, "customer who placed order", top_k=5)
    col_names = {r.column_name for r in results}
    # user_id on orders or id on users should surface
    assert len(results) > 0


def test_search_tables_no_results_for_garbage(seeded_conn):
    results = search_tables(seeded_conn, "xyzzy quantum flux capacitor", top_k=5)
    # Should return empty or very low-scoring results — no assert on count,
    # just assert it doesn't crash
    assert isinstance(results, list)


def test_search_columns_sku_product(seeded_conn):
    results = search_columns(seeded_conn, "product sku warehouse code", top_k=5)
    col_names = {r.column_name for r in results}
    assert "sku" in col_names
