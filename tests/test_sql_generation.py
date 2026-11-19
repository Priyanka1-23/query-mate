import json

import pytest

from services.ai_service import AIService, MockProvider, parse_json_object
from services.sql_generation_service import (
    correct_sql, generate_sql, schema_to_prompt, select_relevant_tables, suggest_questions,
)
from services.sql_validation_service import validate_sql
from utils.exceptions import AIServiceError


def _ai(payload):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return AIService(MockProvider([text])), None


def test_sql_status(ctx):
    ai, _ = _ai({"status": "sql", "sql": "SELECT city, COUNT(*) AS n FROM customers GROUP BY city",
                 "explanation": "Customers per city"})
    r = generate_sql(ai, ctx, "customers per city")
    assert r.status == "sql" and r.sql.startswith("SELECT") and r.connection_id == "sample"


def test_prompt_is_grounded_in_active_schema_and_has_no_secrets(ctx):
    prov = MockProvider([json.dumps({"status": "unsupported", "reason": "x"})])
    generate_sql(AIService(prov), ctx, "anything")
    system, user = prov.calls[0]
    assert "customers" in user and "order_items" in user
    assert "orders(customer_id) -> customers(customer_id)" in user  # relationships included
    assert "SQLite" in system and "Never invent" in system and "ONE read-only" in system
    assert "password" not in (system + user).lower()


def test_clarification_status(ctx):
    ai, _ = _ai({"status": "clarification_needed", "clarifying_question": "Top by what?",
                 "options": ["Total spending", "Order count", "Most recent"]})
    r = generate_sql(ai, ctx, "Show the top customers")
    assert r.status == "clarification_needed" and len(r.options) == 3 and r.sql is None


def test_unsupported_status(ctx):
    ai, _ = _ai({"status": "unsupported", "reason": "No employee salary data.", "suggestions": ["How many customers per city?"]})
    r = generate_sql(ai, ctx, "average employee salary")
    assert r.status == "unsupported" and r.suggestions and r.sql is None


def test_fenced_and_noisy_json_parsed():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Sure! {"a": 2} hope that helps') == {"a": 2}


def test_malformed_output_raises_safe_error(ctx):
    ai, _ = _ai("I cannot do that")
    with pytest.raises(AIServiceError):
        generate_sql(ai, ctx, "q")
    ai, _ = _ai({"status": "sql", "sql": ""})
    with pytest.raises(AIServiceError):
        generate_sql(ai, ctx, "q")
    ai, _ = _ai({"status": "banana"})
    with pytest.raises(AIServiceError):
        generate_sql(ai, ctx, "q")


def test_empty_question(ctx):
    with pytest.raises(AIServiceError):
        generate_sql(AIService(MockProvider([])), ctx, "   ")


def test_model_output_is_still_validated(ctx):
    """A prompt is not a security mechanism: malicious/hallucinated model output is caught by the validator."""
    for bad in ["DROP TABLE customers", "SELECT * FROM invented_table", "SELECT fake_col FROM customers",
                "SELECT 1; DELETE FROM orders"]:
        ai, _ = _ai({"status": "sql", "sql": bad})
        r = generate_sql(ai, ctx, "q")
        assert not validate_sql(r.sql, ctx.dialect, ctx.schema).is_valid


def test_correction_flow(ctx):
    ai, _ = _ai({"status": "sql", "sql": "SELECT customer_name FROM customers"})
    r = correct_sql(ai, ctx, "names", "SELECT name FROM customers", "no such column: name")
    assert r.sql == "SELECT customer_name FROM customers"


def test_relevant_table_selection_for_large_schema(ctx):
    from database.metadata_models import ColumnInfo, SchemaSnapshot, TableInfo
    tables = tuple(TableInfo(f"t{i}", (ColumnInfo("id", "INT", False, True),), ("id",)) for i in range(60))
    tables += (TableInfo("invoices", (ColumnInfo("amount", "INT"),)),)
    big = SchemaSnapshot("big", "mysql", tables)
    chosen = select_relevant_tables(big, "total invoice amount", limit=10)
    assert len(chosen) <= 10 and "invoices" in {t.name for t in chosen}
    assert len(select_relevant_tables(ctx.schema, "x", 25)) == 6  # small schema sent whole


def test_schema_prompt_text(ctx):
    txt = schema_to_prompt(list(ctx.schema.tables), ctx.schema)
    assert "TABLE customers" in txt and "customer_id" in txt and "PK" in txt


def test_suggestions_grounded_in_schema(ctx):
    qs = suggest_questions(ctx.schema, 8)
    assert len(qs) == 8 and len(set(qs)) == 8
    names = [t.name.replace("_", " ") for t in ctx.schema.tables]
    assert all(any(n in q for n in names) for q in qs)


def test_suggestions_empty_schema():
    from database.metadata_models import SchemaSnapshot
    assert suggest_questions(SchemaSnapshot("x", "mysql", ())) == []
