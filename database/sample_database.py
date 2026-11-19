"""Sample e-commerce database (real tables, real foreign keys, seeded data).

Works on SQLite (default, zero setup) and MySQL:
    python -m database.sample_database --mysql-url "mysql+pymysql://user:pass@localhost/shop"
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import (
    Column, Date, ForeignKey, Integer, MetaData, Numeric, String, Table, create_engine,
    insert, inspect,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

customers = Table(
    "customers", metadata,
    Column("customer_id", Integer, primary_key=True, autoincrement=True),
    Column("customer_name", String(100), nullable=False),
    Column("email", String(150), nullable=False, unique=True),
    Column("city", String(80)),
    Column("registration_date", Date),
)
categories = Table(
    "categories", metadata,
    Column("category_id", Integer, primary_key=True, autoincrement=True),
    Column("category_name", String(80), nullable=False, unique=True),
)
products = Table(
    "products", metadata,
    Column("product_id", Integer, primary_key=True, autoincrement=True),
    Column("product_name", String(120), nullable=False),
    Column("category_id", Integer, ForeignKey("categories.category_id"), nullable=False),
    Column("price", Numeric(10, 2), nullable=False),
    Column("stock_quantity", Integer, nullable=False),
)
orders = Table(
    "orders", metadata,
    Column("order_id", Integer, primary_key=True, autoincrement=True),
    Column("customer_id", Integer, ForeignKey("customers.customer_id"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("order_status", String(20), nullable=False),
)
order_items = Table(
    "order_items", metadata,
    Column("order_item_id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("orders.order_id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.product_id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
)
payments = Table(
    "payments", metadata,
    Column("payment_id", Integer, primary_key=True, autoincrement=True),
    Column("order_id", Integer, ForeignKey("orders.order_id"), nullable=False),
    Column("payment_method", String(30), nullable=False),
    Column("payment_status", String(20), nullable=False),
    Column("amount", Numeric(10, 2), nullable=False),
)

SAMPLE_TABLES = ["customers", "categories", "products", "orders", "order_items", "payments"]

_FIRST = ["Aarav", "Vivaan", "Aditya", "Diya", "Ananya", "Isha", "Rohan", "Kabir", "Meera", "Saanvi",
          "Arjun", "Neha", "Priya", "Rahul", "Sneha", "Karan", "Pooja", "Amit", "Riya", "Vikram",
          "Emma", "Liam", "Olivia", "Noah", "Sophia", "Lucas", "Mia", "Ethan", "Ava", "Mason"]
_LAST = ["Sharma", "Verma", "Gupta", "Mehta", "Singh", "Patel", "Reddy", "Nair", "Joshi", "Kapoor",
         "Rao", "Iyer", "Chauhan", "Bose", "Das", "Smith", "Johnson", "Brown", "Taylor", "Wilson"]
_CITIES = ["Mumbai", "Delhi", "Bengaluru", "Udaipur", "Jaipur", "Pune", "Chennai", "Kolkata",
           "Hyderabad", "Ahmedabad"]
_CATALOG = {
    "Electronics": [("Wireless Earbuds", 59.99), ("Bluetooth Speaker", 39.50), ("Smartwatch", 129.00),
                    ("Power Bank 20000mAh", 24.99), ("Mechanical Keyboard", 79.00), ("USB-C Hub", 34.90)],
    "Home & Kitchen": [("Air Fryer", 89.00), ("Electric Kettle", 29.99), ("Non-stick Pan Set", 49.50),
                       ("Mixer Grinder", 64.00), ("Vacuum Flask", 18.75), ("Knife Set", 42.00)],
    "Books": [("SQL for Beginners", 19.99), ("Python Crash Course", 29.99), ("Data Science Handbook", 39.99),
              ("Database Internals", 54.00), ("Clean Code", 34.50)],
    "Clothing": [("Cotton T-Shirt", 14.99), ("Denim Jeans", 44.99), ("Running Shoes", 69.00),
                 ("Hooded Sweatshirt", 38.00), ("Rain Jacket", 55.00)],
    "Sports": [("Yoga Mat", 22.00), ("Dumbbell Set 10kg", 47.50), ("Cricket Bat", 58.00),
               ("Football", 19.00), ("Badminton Racket", 31.00)],
    "Beauty": [("Face Wash", 8.99), ("Sunscreen SPF 50", 12.50), ("Hair Dryer", 36.00), ("Perfume 50ml", 45.00)],
}
_STATUSES = ["Delivered"] * 6 + ["Shipped"] * 2 + ["Processing"] + ["Cancelled"] + ["Returned"]
_METHODS = ["Credit Card", "UPI", "Debit Card", "Net Banking", "Cash on Delivery"]


def create_and_seed(engine: Engine, today: date | None = None, seed: int = 42) -> dict[str, int]:
    """Drop + recreate the sample tables and fill them with deterministic data."""
    rnd = random.Random(seed)
    today = today or date.today()
    metadata.drop_all(engine)
    metadata.create_all(engine)

    cust_rows = []
    for i in range(60):
        name = f"{rnd.choice(_FIRST)} {rnd.choice(_LAST)}"
        cust_rows.append({
            "customer_name": name,
            "email": f"{name.lower().replace(' ', '.')}{i}@example.com",
            "city": rnd.choice(_CITIES),
            "registration_date": today - timedelta(days=rnd.randint(30, 700)),
        })
    cat_rows = [{"category_name": c} for c in _CATALOG]
    prod_rows = []
    for cid, (cat, items) in enumerate(_CATALOG.items(), start=1):
        for pname, price in items:
            prod_rows.append({"product_name": pname, "category_id": cid, "price": price,
                              "stock_quantity": rnd.choice([0, 3, 5, 8, 12, 25, 40, 80, 150, 300])})

    with engine.begin() as conn:
        conn.execute(insert(customers), cust_rows)
        conn.execute(insert(categories), cat_rows)
        conn.execute(insert(products), prod_rows)

        n_prod = len(prod_rows)
        prices = {i + 1: float(p["price"]) for i, p in enumerate(prod_rows)}
        order_rows, item_rows, pay_rows = [], [], []
        item_id = 1
        for oid in range(1, 301):
            # Skew: a few customers order a lot.
            cust = min(60, int(rnd.paretovariate(1.3)))
            odate = today - timedelta(days=int(rnd.triangular(0, 365, 20)))
            status = rnd.choice(_STATUSES)
            order_rows.append({"customer_id": max(1, cust), "order_date": odate, "order_status": status})
            total = 0.0
            for pid in rnd.sample(range(1, n_prod + 1), rnd.randint(1, 4)):
                qty = rnd.randint(1, 3)
                item_rows.append({"order_id": oid, "product_id": pid, "quantity": qty, "unit_price": prices[pid]})
                total += qty * prices[pid]
                item_id += 1
            pstatus = {"Delivered": "Paid", "Shipped": "Paid", "Processing": "Pending",
                       "Cancelled": "Failed", "Returned": "Refunded"}[status]
            pay_rows.append({"order_id": oid, "payment_method": rnd.choice(_METHODS),
                             "payment_status": pstatus, "amount": round(total, 2)})
        conn.execute(insert(orders), order_rows)
        conn.execute(insert(order_items), item_rows)
        conn.execute(insert(payments), pay_rows)

    return {"customers": len(cust_rows), "categories": len(cat_rows), "products": len(prod_rows),
            "orders": len(order_rows), "order_items": len(item_rows), "payments": len(pay_rows)}


def ensure_sample_sqlite(path: Path) -> Path:
    """Create + seed the SQLite sample DB file if missing/incomplete. Uses a writable engine ONLY here."""
    path = Path(path)
    needs = True
    if path.exists():
        eng = create_engine(f"sqlite:///{path}")
        try:
            needs = not set(SAMPLE_TABLES).issubset(set(inspect(eng).get_table_names()))
        finally:
            eng.dispose()
    if needs:
        path.parent.mkdir(parents=True, exist_ok=True)
        eng = create_engine(f"sqlite:///{path}")
        try:
            create_and_seed(eng)
        finally:
            eng.dispose()
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Seed the QueryMate sample database.")
    ap.add_argument("--mysql-url", help="e.g. mysql+pymysql://user:pass@localhost:3306/shop (use an admin/writer account)")
    ap.add_argument("--sqlite-path", help="SQLite file to (re)create")
    args = ap.parse_args()
    if args.mysql_url:
        eng = create_engine(args.mysql_url)
    elif args.sqlite_path:
        eng = create_engine(f"sqlite:///{args.sqlite_path}")
    else:
        ap.error("provide --mysql-url or --sqlite-path")
    print("Seeded:", create_and_seed(eng))
