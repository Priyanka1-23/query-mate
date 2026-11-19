"""One shared validate -> execute -> record pipeline used by BOTH Ask QueryMate and the SQL Playground,
so the Playground can never become a validation bypass."""
from __future__ import annotations

from dataclasses import dataclass

from services.history_service import HistoryService
from services.query_execution_service import QueryResult, execute_query
from services.sql_validation_service import ValidationResult, validate_sql
from utils.config import Preferences
from utils.exceptions import QueryMateError


@dataclass
class RunOutcome:
    validation: ValidationResult
    result: QueryResult | None = None
    error: str | None = None
    history_id: int | None = None


def validate_for(ctx, sql: str, prefs: Preferences) -> ValidationResult:
    return validate_sql(sql, ctx.dialect, ctx.schema, prefs.result_limit)


def run_query(ctx, sql: str, prefs: Preferences, history: HistoryService | None, question: str | None = None,
              source: str = "ask", expected_connection_id: str | None = None) -> RunOutcome:
    validation = validate_for(ctx, sql, prefs)
    if not validation.is_valid:
        hid = history.record(ctx.connection_id, sql, "rejected", question, error="; ".join(validation.errors), source=source) if history else None
        return RunOutcome(validation, None, "; ".join(validation.errors), hid)
    try:
        result = execute_query(ctx, validation, prefs.result_limit, prefs.query_timeout, expected_connection_id)
    except QueryMateError as e:
        hid = history.record(ctx.connection_id, validation.normalized_sql, "failed", question, error=str(e), source=source) if history else None
        return RunOutcome(validation, None, str(e), hid)
    hid = history.record(ctx.connection_id, validation.normalized_sql, "success", question,
                         result.execution_time, result.row_count, source=source) if history else None
    return RunOutcome(validation, result, None, hid)
