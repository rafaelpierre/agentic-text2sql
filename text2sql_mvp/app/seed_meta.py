"""Populate meta-schema with e-commerce table and column descriptions."""
from __future__ import annotations

from sqlalchemy.engine import Connection

from .meta_schema import column_registry, create_meta_tables, schema_registry, table_registry

# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------

SCHEMA_OVERVIEW = (
    "E-commerce transactional database covering customers, product catalogue, "
    "purchase orders, and order line items. Use for revenue analytics, inventory "
    "queries, customer behaviour analysis, and order fulfilment reporting."
)

TABLES: list[dict] = [
    {
        "table_name": "users",
        "description": (
            "Registered customers of the e-commerce platform. "
            "Contains contact details, shipping address defaults, and account metadata. "
            "Query for customer demographics, account age, and geographical distribution."
        ),
        "columns": [
            ("id", "integer", True, False, None, "Unique customer identifier, auto-incremented primary key."),
            ("email", "varchar(255)", False, False, None, "Customer email address, used for login and notifications."),
            ("username", "varchar(100)", False, False, None, "Unique display name chosen by the customer."),
            ("first_name", "varchar(100)", False, False, None, "Customer first name."),
            ("last_name", "varchar(100)", False, False, None, "Customer last name."),
            ("phone", "varchar(30)", False, False, None, "Optional contact phone number."),
            ("address", "text", False, False, None, "Street address for default shipping."),
            ("city", "varchar(100)", False, False, None, "City for default shipping address."),
            ("country", "varchar(100)", False, False, None, "Country code or name for default shipping."),
            ("created_at", "timestamp", False, False, None, "Account creation timestamp."),
        ],
    },
    {
        "table_name": "products",
        "description": (
            "Product catalogue for the e-commerce store. "
            "Contains pricing, inventory levels, category taxonomy, and brand information. "
            "Query for stock availability, price ranges, category performance, and brand listings."
        ),
        "columns": [
            ("id", "integer", True, False, None, "Unique product identifier."),
            ("sku", "varchar(100)", False, False, None, "Stock-keeping unit — unique product code used in warehouse and orders."),
            ("name", "varchar(255)", False, False, None, "Human-readable product name displayed on the storefront."),
            ("description", "text", False, False, None, "Long-form product description with features and specifications."),
            ("price", "numeric(10,2)", False, False, None, "List price in the store's base currency."),
            ("stock_qty", "integer", False, False, None, "Current available inventory count. Zero means out of stock."),
            ("category", "varchar(100)", False, False, None, "Top-level category (e.g. Electronics, Clothing, Home & Garden)."),
            ("brand", "varchar(100)", False, False, None, "Brand or manufacturer name."),
            ("weight_kg", "numeric(6,3)", False, False, None, "Physical weight in kilograms, used for shipping cost calculation."),
            ("created_at", "timestamp", False, False, None, "Timestamp when the product was added to the catalogue."),
        ],
    },
    {
        "table_name": "orders",
        "description": (
            "Purchase transaction header records. Each row is one customer order. "
            "Contains order status lifecycle, payment method, shipping destination, and total value. "
            "Query for revenue totals, order status breakdown, payment method analysis, and customer purchase history."
        ),
        "columns": [
            ("id", "integer", True, False, None, "Unique order identifier."),
            ("user_id", "integer", False, True, "users.id", "Foreign key to the customer who placed this order."),
            ("status", "varchar(50)", False, False, None, "Order lifecycle status: pending | confirmed | shipped | delivered | cancelled."),
            ("total_amount", "numeric(10,2)", False, False, None, "Sum of all order_items subtotals for this order."),
            ("shipping_addr", "text", False, False, None, "Delivery street address for this specific order."),
            ("shipping_city", "varchar(100)", False, False, None, "Delivery city for this order."),
            ("shipping_country", "varchar(100)", False, False, None, "Delivery country for this order."),
            ("payment_method", "varchar(50)", False, False, None, "Payment method used: credit_card | paypal | bank_transfer | crypto."),
            ("notes", "text", False, False, None, "Optional free-text notes from the customer or support team."),
            ("created_at", "timestamp", False, False, None, "Timestamp when the order was placed."),
        ],
    },
    {
        "table_name": "order_items",
        "description": (
            "Individual line items within a purchase order. Each row links one product to one order. "
            "Contains quantity, unit price at time of purchase, any discount applied, and computed subtotal. "
            "Query for product sales volumes, discount analysis, revenue per product, and basket analysis."
        ),
        "columns": [
            ("id", "integer", True, False, None, "Unique order item identifier."),
            ("order_id", "integer", False, True, "orders.id", "Foreign key to the parent order."),
            ("product_id", "integer", False, True, "products.id", "Foreign key to the product that was purchased."),
            ("quantity", "integer", False, False, None, "Number of units of the product in this line item."),
            ("unit_price", "numeric(10,2)", False, False, None, "Price per unit at the time of purchase (may differ from current product price)."),
            ("discount", "numeric(5,2)", False, False, None, "Discount amount applied to this line item (absolute value, not percentage)."),
            ("subtotal", "numeric(10,2)", False, False, None, "Final line item value: (unit_price * quantity) - discount."),
            ("notes", "text", False, False, None, "Optional notes specific to this line item, e.g. gift wrapping instructions."),
            ("created_at", "timestamp", False, False, None, "Timestamp when this line item was created."),
        ],
    },
]


def _build_search_doc(table_name: str, description: str, columns: list) -> str:
    col_names = " ".join(c[0] for c in columns)
    col_descs = " ".join(c[5] for c in columns)
    return f"{table_name} {description} {col_names} {col_descs}"


def _build_col_search_doc(col_name: str, col_desc: str, table_name: str) -> str:
    return f"{col_name} {col_desc} {table_name}"


def seed_meta(conn: Connection) -> None:
    create_meta_tables(conn)

    # Upsert schema
    existing = conn.execute(
        schema_registry.select().where(schema_registry.c.schema_name == "ecommerce")
    ).first()
    if existing is None:
        result = conn.execute(
            schema_registry.insert().values(schema_name="ecommerce", overview=SCHEMA_OVERVIEW)
        )
        schema_id = result.inserted_primary_key[0]
    else:
        schema_id = existing.id

    for tbl in TABLES:
        tname = tbl["table_name"]
        tdesc = tbl["description"]
        cols = tbl["columns"]
        search_doc = _build_search_doc(tname, tdesc, cols)

        existing_tbl = conn.execute(
            table_registry.select().where(table_registry.c.table_name == tname)
        ).first()
        if existing_tbl is None:
            result = conn.execute(
                table_registry.insert().values(
                    schema_id=schema_id,
                    table_name=tname,
                    description=tdesc,
                    search_doc=search_doc,
                )
            )
            table_id = result.inserted_primary_key[0]
        else:
            table_id = existing_tbl.id

        for col_name, data_type, is_pk, is_fk, fk_ref, col_desc in cols:
            existing_col = conn.execute(
                column_registry.select().where(
                    (column_registry.c.table_id == table_id)
                    & (column_registry.c.column_name == col_name)
                )
            ).first()
            if existing_col is None:
                conn.execute(
                    column_registry.insert().values(
                        table_id=table_id,
                        column_name=col_name,
                        data_type=data_type,
                        is_pk=is_pk,
                        is_fk=is_fk,
                        fk_references=fk_ref,
                        description=col_desc,
                        search_doc=_build_col_search_doc(col_name, col_desc, tname),
                    )
                )
