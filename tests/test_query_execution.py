import sqlite3

import pytest
from sqlalchemy import text

from services.query_execution_service import execute_query, explain_query
from services.query_runner import run_query, validate_for
from services.sql_validation_service import validate_sql
from utils.exceptions import (
    ContextMismatchError, QueryExecutionError, QueryTimeoutError, SQLValidationError,
)


def _v(ctx, sql, limit=1000):
    return validate_sql(sql, ctx.dialect, ctx.schema, limit)


def test_valid_query_returns_real_data(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC"))
    assert res.row_count > 0 and list(res.dataframe.columns) == ["city", "n"]
    assert res.dataframe["n"].sum() == 60
    assert res.execution_time >= 0


def test_matches_direct_sqlite(ctx, manager):
    res = execute_query(ctx, _v(ctx, "SELECT COUNT(*) AS n FROM orders WHERE order_status = 'Delivered'"))
    con = sqlite3.connect(f"file:{manager._sample_path}?mode=ro", uri=True)
    expected = con.execute("SELECT COUNT(*) FROM orders WHERE order_status='Delivered'").fetchone()[0]
    assert int(res.dataframe.iloc[0, 0]) == expected


def test_empty_result(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT * FROM customers WHERE city = 'Atlantis'"))
    assert res.is_empty and res.row_count == 0 and "city" in res.dataframe.columns


def test_large_result_truncated_by_row_limit(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT * FROM order_items", 1000), row_limit=25)
    assert res.row_count == 25 and res.truncated


def test_row_limit_enforced_via_validation(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT * FROM order_items", 40), row_limit=40)
    assert res.row_count == 40


def test_duplicate_column_names_deduped(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT o.order_id, p.order_id FROM orders o JOIN payments p ON p.order_id=o.order_id"))
    assert len(set(res.dataframe.columns)) == 2


def test_percent_and_colon_in_sql_are_literal(ctx):
    res = execute_query(ctx, _v(ctx, "SELECT COUNT(*) FROM customers WHERE email LIKE '%@example.com' AND city <> 'a:b'"))
    assert int(res.dataframe.iloc[0, 0]) == 60


def test_refuses_invalid_validation(ctx):
    with pytest.raises(SQLValidationError):
        execute_query(ctx, _v(ctx, "DELETE FROM customers"))


def test_context_mismatch_blocked(ctx):
    with pytest.raises(ContextMismatchError):
        execute_query(ctx, _v(ctx, "SELECT 1"), expected_connection_id="db-42")


def test_timeout(ctx):
    slow = ("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM c WHERE x < 500000000) "
            "SELECT COUNT(*) FROM c")
    with pytest.raises(QueryTimeoutError):
        execute_query(ctx, _v(ctx, slow), timeout=1)


def test_database_level_read_only_second_layer(ctx):
    """Even if validation were bypassed, the execution connection cannot write."""
    with pytest.raises(Exception) as e:
        with ctx.engine.connect() as c:
            c.execute(text("DELETE FROM customers"))
    assert "readonly" in str(e.value).lower() or "read-only" in str(e.value).lower() or "query_only" in str(e.value).lower()
    with ctx.engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM customers")).scalar() == 60
    with pytest.raises(Exception):
        with ctx.engine.begin() as c:
            c.execute(text("DROP TABLE customers"))


def test_runner_records_history_for_all_outcomes(ctx, history, prefs):
    before = history.count(ctx.connection_id)
    ok = run_query(ctx, "SELECT COUNT(*) AS n FROM customers", prefs, history, "how many customers")
    assert ok.result is not None and ok.error is None
    rej = run_query(ctx, "DROP TABLE customers", prefs, history, "bad", source="playground")
    assert rej.result is None and "allowed" in rej.error.lower()
    assert history.count(ctx.connection_id) == before + 2
    rows = history.list(ctx.connection_id, limit=2)
    assert {r["execution_status"] for r in rows} == {"success", "rejected"}
    assert history.list(ctx.connection_id, status="success", limit=1)[0]["returned_row_count"] == 1


def test_runner_blocks_mismatched_connection(ctx, history, prefs):
    out = run_query(ctx, "SELECT 1", prefs, history, expected_connection_id="db-7")
    assert out.result is None and "different database" in out.error


def test_explain(ctx):
    plan = explain_query(ctx, _v(ctx, "SELECT * FROM customers WHERE city='Pune'"))
    assert len(plan) >= 1


def test_runtime_errors_are_friendly(ctx):
    from services.sql_validation_service import ValidationResult
    bad = ValidationResult(True, "SELECT nonexistent_fn_xyz(1)")
    with pytest.raises(QueryExecutionError) as e:
        execute_query(ctx, bad)
    assert "Traceback" not in str(e.value)
