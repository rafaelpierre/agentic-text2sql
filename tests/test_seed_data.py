"""Demo seeding must preserve existing data when rerun."""
from sqlalchemy import select

from text2sql_mvp.app.data_schema import create_ecommerce_tables, users, products, orders, order_items
from text2sql_mvp.app.seed_data import seed_data


def snapshot(conn):
    return {
        table.name: conn.execute(select(table).order_by(table.c.id)).all()
        for table in (users, products, orders, order_items)
    }


def test_seed_data_is_repeatable(engine):
    with engine.begin() as conn:
        assert seed_data(conn) is True
        before = snapshot(conn)
        assert len(before['users']) == 50
        assert len(before['products']) == 80
        assert len(before['orders']) == 120
        assert len(before['order_items']) >= 120

    with engine.begin() as conn:
        assert seed_data(conn) is False
        assert snapshot(conn) == before


def test_seed_data_preserves_partial_database(engine):
    with engine.begin() as conn:
        create_ecommerce_tables(conn)
        conn.execute(products.insert().values(
            sku='SKU-0001', name='Existing product', price=10, stock_qty=1,
        ))
        before = snapshot(conn)
        assert seed_data(conn) is False
        assert snapshot(conn) == before
