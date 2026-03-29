"""Insert dummy e-commerce rows into the data schema."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy.engine import Connection

from .data_schema import create_ecommerce_tables, order_items, orders, products, users

CATEGORIES = ["Electronics", "Clothing", "Home & Garden", "Sports", "Books", "Toys", "Beauty"]
BRANDS = ["TechCo", "StyleHub", "HomePro", "ActiveGear", "ReadMore", "FunZone", "GlowUp"]
STATUSES = ["pending", "confirmed", "shipped", "delivered", "cancelled"]
PAYMENT_METHODS = ["credit_card", "paypal", "bank_transfer", "crypto"]
COUNTRIES = ["US", "UK", "DE", "FR", "CA", "AU", "JP", "BR"]
CITIES = ["New York", "London", "Berlin", "Paris", "Toronto", "Sydney", "Tokyo", "São Paulo"]

FIRST_NAMES = ["Alice", "Bob", "Carol", "David", "Eva", "Frank", "Grace", "Henry",
               "Iris", "Jack", "Karen", "Leo", "Mia", "Nick", "Olivia", "Paul",
               "Quinn", "Rachel", "Sam", "Tina", "Uma", "Victor", "Wendy", "Xander"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
              "Davis", "Wilson", "Taylor", "Anderson", "Thomas", "Jackson", "White"]


def _rand_date(days_back: int = 365) -> datetime:
    return datetime.utcnow() - timedelta(days=random.randint(0, days_back))


def seed_data(conn: Connection, n_users: int = 50, n_products: int = 80) -> None:
    create_ecommerce_tables(conn)

    # Users
    user_ids = []
    for i in range(1, n_users + 1):
        fn = random.choice(FIRST_NAMES)
        ln = random.choice(LAST_NAMES)
        city = random.choice(CITIES)
        country = random.choice(COUNTRIES)
        result = conn.execute(
            users.insert().values(
                email=f"{fn.lower()}.{ln.lower()}{i}@example.com",
                username=f"{fn.lower()}{i}",
                first_name=fn,
                last_name=ln,
                phone=f"+1-555-{random.randint(1000,9999)}",
                address=f"{random.randint(1,999)} Main St",
                city=city,
                country=country,
                created_at=_rand_date(730),
            )
        )
        user_ids.append(result.inserted_primary_key[0])

    # Products
    product_ids = []
    for i in range(1, n_products + 1):
        cat = random.choice(CATEGORIES)
        brand = random.choice(BRANDS)
        price = round(random.uniform(5.0, 999.99), 2)
        result = conn.execute(
            products.insert().values(
                sku=f"SKU-{i:04d}",
                name=f"{brand} {cat} Item {i}",
                description=f"High-quality {cat.lower()} product from {brand}. Model {i}.",
                price=price,
                stock_qty=random.randint(0, 500),
                category=cat,
                brand=brand,
                weight_kg=round(random.uniform(0.1, 10.0), 3),
                created_at=_rand_date(365),
            )
        )
        product_ids.append(result.inserted_primary_key[0])

    # Orders + order items
    for _ in range(120):
        uid = random.choice(user_ids)
        order_date = _rand_date(180)
        status = random.choice(STATUSES)
        city = random.choice(CITIES)
        country = random.choice(COUNTRIES)

        # Insert order with placeholder total
        result = conn.execute(
            orders.insert().values(
                user_id=uid,
                status=status,
                total_amount=0,
                shipping_addr=f"{random.randint(1,999)} Ship Lane",
                shipping_city=city,
                shipping_country=country,
                payment_method=random.choice(PAYMENT_METHODS),
                notes=None,
                created_at=order_date,
            )
        )
        order_id = result.inserted_primary_key[0]

        n_items = random.randint(1, 5)
        chosen_products = random.sample(product_ids, min(n_items, len(product_ids)))
        order_total = 0.0
        for pid in chosen_products:
            qty = random.randint(1, 4)
            unit_price = round(random.uniform(5.0, 499.99), 2)
            discount = round(random.uniform(0, min(5.0, unit_price * 0.1)), 2)
            subtotal = round(unit_price * qty - discount, 2)
            order_total += subtotal
            conn.execute(
                order_items.insert().values(
                    order_id=order_id,
                    product_id=pid,
                    quantity=qty,
                    unit_price=unit_price,
                    discount=discount,
                    subtotal=subtotal,
                    notes=None,
                    created_at=order_date,
                )
            )

        # Update order total
        conn.execute(
            orders.update().where(orders.c.id == order_id).values(
                total_amount=round(order_total, 2)
            )
        )
