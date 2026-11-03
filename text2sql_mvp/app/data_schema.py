"""Actual e-commerce table definitions (schema: ecommerce)."""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
)

ECOMMERCE = MetaData()

users = Table(
    "users",
    ECOMMERCE,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("username", String(100), nullable=False, unique=True),
    Column("first_name", String(100), nullable=False),
    Column("last_name", String(100), nullable=False),
    Column("phone", String(30)),
    Column("address", Text),
    Column("city", String(100)),
    Column("country", String(100)),
    Column("created_at", DateTime, server_default=func.now()),
    schema="ecommerce",
)

products = Table(
    "products",
    ECOMMERCE,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sku", String(100), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("description", Text),
    Column("price", Numeric(10, 2), nullable=False),
    Column("stock_qty", Integer, nullable=False, default=0),
    Column("category", String(100)),
    Column("brand", String(100)),
    Column("weight_kg", Numeric(6, 3)),
    Column("created_at", DateTime, server_default=func.now()),
    schema="ecommerce",
)

orders = Table(
    "orders",
    ECOMMERCE,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("ecommerce.users.id"), nullable=False),
    Column("status", String(50), nullable=False, default="pending"),
    Column("total_amount", Numeric(10, 2), nullable=False),
    Column("shipping_addr", Text),
    Column("shipping_city", String(100)),
    Column("shipping_country", String(100)),
    Column("payment_method", String(50)),
    Column("notes", Text),
    Column("created_at", DateTime, server_default=func.now()),
    schema="ecommerce",
)

order_items = Table(
    "order_items",
    ECOMMERCE,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("ecommerce.orders.id"), nullable=False),
    Column("product_id", Integer, ForeignKey("ecommerce.products.id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("discount", Numeric(5, 2), default=0),
    Column("subtotal", Numeric(10, 2), nullable=False),
    Column("notes", Text),
    Column("created_at", DateTime, server_default=func.now()),
    schema="ecommerce",
)


def create_ecommerce_tables(conn) -> None:
    ECOMMERCE.create_all(conn, checkfirst=True)
