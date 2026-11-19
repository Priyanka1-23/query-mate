import pytest

from services.sql_validation_service import validate_sql

D = "sqlite"

UNSAFE = [
    "DELETE FROM customers",
    "DELETE FROM customers WHERE 1=1",
    "UPDATE customers SET city='X'",
    "INSERT INTO customers (customer_name) VALUES ('x')",
    "DROP TABLE customers",
    "ALTER TABLE customers ADD COLUMN x INT",
    "TRUNCATE TABLE customers",
    "CREATE TABLE t (id INT)",
    "SELECT 1; DROP TABLE customers",
    "SELECT * FROM customers; DELETE FROM customers",
    "SELECT * FROM customers;;DROP TABLE x",
    "WITH d AS (DELETE FROM customers RETURNING *) SELECT * FROM d",
    "SELECT * FROM customers FOR UPDATE",
    "SELECT SLEEP(5)",
    "SELECT BENCHMARK(100000000, MD5('x'))",
    "SELECT LOAD_FILE('/etc/passwd')",
    "SELECT * FROM customers INTO OUTFILE '/tmp/x'",
    "SET @a = 1",
    "SHOW TABLES",
    "PRAGMA table_info(customers)",
    "ATTACH DATABASE 'x.db' AS x",
    "GRANT ALL ON *.* TO 'a'@'b'",
    "CALL some_proc()",
    "REPLACE INTO customers VALUES (1)",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM other_db.customers",
    "",
    "   ",
    "not sql at all ((",
]


@pytest.mark.parametrize("sql", UNSAFE)
@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
def test_unsafe_rejected(sql, dialect, ctx):
    r = validate_sql(sql, dialect, ctx.schema)
    assert not r.is_valid and r.errors, f"should reject: {sql!r}"
    assert r.normalized_sql == ""


VALID = [
    "SELECT * FROM customers",
    "SELECT city, COUNT(*) AS n FROM customers GROUP BY city HAVING COUNT(*) > 2 ORDER BY n DESC",
    "SELECT c.customer_name, SUM(oi.quantity*oi.unit_price) AS spent FROM customers c JOIN orders o ON o.customer_id=c.customer_id "
    "JOIN order_items oi ON oi.order_id=o.order_id GROUP BY c.customer_name ORDER BY spent DESC LIMIT 5",
    "WITH t AS (SELECT city, COUNT(*) n FROM customers GROUP BY city) SELECT * FROM t WHERE n > 1",
    "SELECT product_name FROM products WHERE price > (SELECT AVG(price) FROM products)",
    "SELECT city FROM customers UNION SELECT 'x'",
    "SELECT 1",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_accepted(sql, ctx):
    r = validate_sql(sql, "sqlite", ctx.schema)
    assert r.is_valid, r.errors
    assert r.normalized_sql


def test_schema_grounding_errors(ctx):
    assert "does not exist" in validate_sql("SELECT * FROM nope", D, ctx.schema).errors[0]
    assert not validate_sql("SELECT bogus FROM customers", D, ctx.schema).is_valid
    assert not validate_sql("SELECT c.bogus FROM customers c", D, ctx.schema).is_valid
    assert not validate_sql("SELECT x.city FROM customers c", D, ctx.schema).is_valid
    # incorrect join column
    assert not validate_sql("SELECT * FROM orders o JOIN customers c ON o.cust = c.customer_id", D, ctx.schema).is_valid


def test_select_alias_in_order_by_ok(ctx):
    assert validate_sql("SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n", D, ctx.schema).is_valid


def test_limit_injected_and_capped(ctx):
    r = validate_sql("SELECT * FROM customers", D, ctx.schema, row_limit=50)
    assert r.limit_applied == 50 and "LIMIT 50" in r.normalized_sql.upper()
    r = validate_sql("SELECT * FROM customers LIMIT 9999", D, ctx.schema, row_limit=50)
    assert "LIMIT 50" in r.normalized_sql.upper()
    r = validate_sql("SELECT * FROM customers LIMIT 10", D, ctx.schema, row_limit=50)
    assert "LIMIT 10" in r.normalized_sql.upper() and r.limit_applied is None
    r = validate_sql("SELECT city FROM customers UNION SELECT city FROM customers", D, ctx.schema, row_limit=7)
    assert "LIMIT 7" in r.normalized_sql.upper()


def test_comment_payload_not_forwarded(ctx):
    r = validate_sql("SELECT 1 /* ; DROP TABLE customers */ -- trailing", "mysql", ctx.schema)
    assert r.is_valid and "DROP" not in r.normalized_sql.upper()


def test_keyword_in_string_literal_is_fine(ctx):
    r = validate_sql("SELECT * FROM customers WHERE city = 'DELETE'", D, ctx.schema)
    assert r.is_valid


def test_not_fooled_by_leading_select_text(ctx):
    # a naive startswith('SELECT') check would accept these
    assert not validate_sql("SELECT 1; UPDATE customers SET city='x'", D, ctx.schema).is_valid
    assert not validate_sql("SELECT * FROM customers WHERE 1=1; DROP TABLE customers --", D, ctx.schema).is_valid


def test_cartesian_warning(ctx):
    r = validate_sql("SELECT * FROM customers, orders", D, ctx.schema)
    assert r.is_valid and any("Cartesian" in w for w in r.warnings)


def test_without_schema_still_blocks_writes():
    assert not validate_sql("DROP TABLE x", "mysql").is_valid
    assert validate_sql("SELECT 1", "mysql").is_valid
