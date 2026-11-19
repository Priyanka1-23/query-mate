import pytest

from services.schema_service import count_rows, preview_table
from utils.exceptions import QueryMateError


def test_tables_and_columns(ctx):
    names = set(ctx.schema.table_names())
    assert names == {"customers", "categories", "products", "orders", "order_items", "payments"}
    cust = ctx.schema.table("customers")
    assert cust.primary_key == ("customer_id",)
    assert {"customer_name", "email", "city", "registration_date"} <= set(cust.column_names())


def test_foreign_keys_extracted(ctx):
    rels = {(f.table, f.columns, f.ref_table) for f in ctx.schema.relationships}
    assert ("orders", ("customer_id",), "customers") in rels
    assert ("order_items", ("order_id",), "orders") in rels
    assert ("order_items", ("product_id",), "products") in rels
    assert ("products", ("category_id",), "categories") in rels
    assert ("payments", ("order_id",), "orders") in rels
    col = next(c for c in ctx.schema.table("orders").columns if c.name == "customer_id")
    assert col.is_foreign_key and not col.is_primary_key


def test_sample_data_is_real_and_sufficient(ctx):
    assert count_rows(ctx.engine, ctx.schema, "customers") == 60
    assert count_rows(ctx.engine, ctx.schema, "orders") == 300
    assert count_rows(ctx.engine, ctx.schema, "order_items") > 300


def test_preview_limit(ctx):
    df = preview_table(ctx.engine, ctx.schema, "customers", 5)
    assert len(df) == 5


def test_preview_rejects_unknown_or_injected_table(ctx):
    with pytest.raises(QueryMateError):
        preview_table(ctx.engine, ctx.schema, "customers; DROP TABLE customers")


def test_sample_data_consistent(ctx):
    from sqlalchemy import text
    with ctx.engine.connect() as c:
        orphan = c.execute(text("SELECT COUNT(*) FROM orders o LEFT JOIN customers c ON c.customer_id=o.customer_id WHERE c.customer_id IS NULL")).scalar()
        assert orphan == 0
        mism = c.execute(text("""SELECT COUNT(*) FROM payments p JOIN
            (SELECT order_id, ROUND(SUM(quantity*unit_price),2) t FROM order_items GROUP BY order_id) x ON x.order_id=p.order_id
            WHERE ABS(p.amount - x.t) > 0.01""")).scalar()
        assert mism == 0
