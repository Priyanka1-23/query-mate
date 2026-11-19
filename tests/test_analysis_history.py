import pandas as pd

from services.analysis_service import analyze_plan, complexity, describe_query_structure
from services.explanation_service import deterministic_explanation, explain_sql, summarize_result
from services.ai_service import AIService, MockProvider
from services.query_execution_service import explain_query
from services.sql_validation_service import validate_sql

SQL = ("SELECT c.city, COUNT(*) AS n FROM customers c JOIN orders o ON o.customer_id=c.customer_id "
       "WHERE o.order_status='Delivered' GROUP BY c.city HAVING COUNT(*)>1 ORDER BY n DESC LIMIT 3")


def test_structure(ctx):
    s = describe_query_structure(SQL, "sqlite")
    assert s.tables == ["customers", "orders"] and len(s.joins) == 1 and s.group_by == ["c.city"]
    assert s.limit == "3" and s.having and s.filters and any("COUNT" in a for a in s.aggregations)
    assert complexity(s)[1] in {"Low", "Medium", "High"}


def test_plan_findings_come_from_explain_evidence(ctx):
    v = validate_sql("SELECT * FROM customers WHERE city='Pune'", "sqlite", ctx.schema)
    plan = explain_query(ctx, v)
    findings, recs = analyze_plan(plan, "sqlite", v.normalized_sql, ctx.schema)
    assert any("Full table scan on `customers`" in f.message for f in findings)
    assert recs and "customers(city)" in recs[0] and "never creates" in recs[0]


def test_pk_lookup_has_no_scan_or_recommendation(ctx):
    v = validate_sql("SELECT * FROM customers WHERE customer_id = 5", "sqlite", ctx.schema)
    findings, recs = analyze_plan(explain_query(ctx, v), "sqlite", v.normalized_sql, ctx.schema)
    assert not any("Full table scan" in f.message for f in findings) and not recs


def test_mysql_plan_parsing():
    from database.metadata_models import ColumnInfo, SchemaSnapshot, TableInfo
    schema = SchemaSnapshot("d", "mysql", (TableInfo("orders", (ColumnInfo("status", "VARCHAR(20)"), ColumnInfo("id", "INT", False, True)), ("id",)),))
    plan = pd.DataFrame([{"id": 1, "select_type": "SIMPLE", "table": "orders", "type": "ALL", "possible_keys": None,
                          "key": None, "rows": 120000, "Extra": "Using where; Using filesort"}])
    f, r = analyze_plan(plan, "mysql", "SELECT * FROM orders WHERE status='x' ORDER BY id", schema)
    msgs = " ".join(x.message for x in f)
    assert "Full table scan on `orders`" in msgs and "120,000" in msgs and "filesort" in msgs
    assert r and "orders(status)" in r[0]


def test_static_explanations_reflect_actual_sql():
    simple = deterministic_explanation(SQL, "sqlite", "simple")
    assert "customers" in simple and "orders" in simple and "3 rows" in simple
    detailed = deterministic_explanation(SQL, "sqlite", "detailed")
    for clause in ["SELECT", "FROM", "JOIN", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "LIMIT"]:
        assert f"**{clause}**" in detailed
    assert "**HAVING**" not in deterministic_explanation("SELECT * FROM customers", "sqlite", "detailed")
    assert "performance" in deterministic_explanation("SELECT * FROM customers ORDER BY city", "sqlite", "technical").lower()


def test_explain_uses_ai_when_available_and_falls_back_on_failure(ctx):
    text, src = explain_sql(AIService(MockProvider(["It lists customers."])), "SELECT * FROM customers", ctx, "simple")
    assert (text, src) == ("It lists customers.", "ai")

    class Boom(MockProvider):
        def complete(self, *a, **k):
            raise RuntimeError("x")
    text, src = explain_sql(AIService(Boom([])), "SELECT * FROM customers", ctx, "simple")
    assert src == "static" and "customers" in text
    assert explain_sql(None, "SELECT * FROM customers", ctx, "simple")[1] == "static"


def test_result_summary_is_supported_by_data():
    df = pd.DataFrame({"city": ["Pune", "Delhi", "Jaipur"], "n": [10, 30, 5]})
    s = summarize_result(df)
    assert "3 rows" in s and "30" in s and "Delhi" in s and "5" in s
    assert "no rows" in summarize_result(pd.DataFrame({"a": []}))
    assert "single value" in summarize_result(pd.DataFrame({"n": [7]}))


def test_history_filters_and_saved_queries(history):
    cid = "db-histtest"
    history.record(cid, "SELECT 1", "success", "q one", 0.01, 1)
    history.record(cid, "SELECT bad", "failed", "q two", error="boom")
    history.record("db-other", "SELECT 2", "success", "other db")
    assert len(history.list(cid)) == 2 and len(history.list(cid, status="failed")) == 1
    assert history.list(cid, search="q one")[0]["generated_sql"] == "SELECT 1"
    assert history.recent_questions(cid, 5) == ["q two", "q one"]
    assert all(r["connection_id"] == cid for r in history.list(cid))  # no cross-connection leakage
    sid = history.save_query(cid, "My query", "SELECT 1", "desc")
    assert history.list_saved(cid)[0]["title"] == "My query" and history.list_saved("db-other") == []
    history.delete_saved(sid)
    assert history.list_saved(cid) == []
    history.clear(cid)
    assert history.list(cid) == [] and history.list("db-other")
