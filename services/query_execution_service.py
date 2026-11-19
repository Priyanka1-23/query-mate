"""Execute VALIDATED, read-only queries with timeout, row cap and timing."""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from database.connection_manager import ConnectionContext
from services.sql_validation_service import ValidationResult
from utils.exceptions import (
    ContextMismatchError, QueryExecutionError, QueryTimeoutError, SQLValidationError,
)
from utils.security import scrub


@dataclass
class QueryResult:
    sql: str
    dataframe: pd.DataFrame
    row_count: int
    execution_time: float  # seconds
    truncated: bool
    connection_id: str

    @property
    def is_empty(self) -> bool:
        return self.row_count == 0


def _dedupe(cols: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for c in cols:
        c = str(c)
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 1
            out.append(c)
    return out


def _to_frame(rows, columns) -> pd.DataFrame:
    df = pd.DataFrame([tuple(r) for r in rows], columns=_dedupe(list(columns)))
    for c in df.columns:
        if df[c].dtype == object:
            nonnull = df[c].dropna()
            if len(nonnull) and all(isinstance(v, Decimal) for v in nonnull):
                df[c] = df[c].astype(float)
    return df


def friendly_error(e: Exception) -> QueryExecutionError:
    orig = getattr(e, "orig", e)
    code = orig.args[0] if getattr(orig, "args", None) and isinstance(orig.args[0], int) else None
    raw = str(orig)
    if code in (3024, 1969) or "interrupted" in raw.lower() and "sqlite" in type(orig).__module__:
        return QueryTimeoutError("The query exceeded the time limit and was stopped. Add filters or a LIMIT, or raise the timeout in Settings.")
    if code == 2013 or "timed out" in raw.lower():
        return QueryTimeoutError("The query timed out or the connection was lost.")
    if code in (2003, 2002, 2006, 2055, 2013):
        return QueryExecutionError("The database connection was lost. Check that the server is reachable and try again.")
    if code in (1142, 1143, 1044, 1045, 1227):
        return QueryExecutionError("Permission denied: the database account is not allowed to run this query.")
    if code == 1146 or "no such table" in raw.lower():
        return QueryExecutionError("A table referenced by the query does not exist.")
    if code == 1054 or "no such column" in raw.lower():
        return QueryExecutionError("A column referenced by the query does not exist.")
    if "readonly" in raw.lower() or "read-only" in raw.lower() or code == 1792:
        return QueryExecutionError("The database rejected the statement because the session is read-only.")
    return QueryExecutionError(f"The database could not run this query: {scrub(raw)[:300]}")


def _arm_timeout(ctx: ConnectionContext, conn, timeout: int):
    """Return a callable that disarms the timeout."""
    if ctx.dialect == "sqlite":
        raw = conn.connection.driver_connection
        deadline = time.monotonic() + timeout
        raw.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        return lambda: raw.set_progress_handler(None, 0)
    # MySQL / MariaDB
    try:
        conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME={int(timeout * 1000)}")
    except Exception:
        try:
            conn.exec_driver_sql(f"SET SESSION max_statement_time={int(timeout)}")
        except Exception:
            pass  # driver read_timeout is still in force
    return lambda: None


def execute_query(ctx: ConnectionContext, validation: ValidationResult, row_limit: int = 1000,
                  timeout: int = 30, expected_connection_id: str | None = None) -> QueryResult:
    if not validation.is_valid or not validation.normalized_sql:
        raise SQLValidationError("Refusing to execute: the query did not pass validation.")
    if expected_connection_id is not None and expected_connection_id != ctx.connection_id:
        raise ContextMismatchError("This query was prepared for a different database. Re-run it from the correct connection.")

    sql = validation.normalized_sql
    row_limit = max(1, int(row_limit))
    start = time.perf_counter()
    try:
        with ctx.engine.connect().execution_options(no_parameters=True) as conn:
            disarm = _arm_timeout(ctx, conn, timeout)
            try:
                res = conn.exec_driver_sql(sql)
                rows = res.fetchmany(row_limit + 1)
                columns = list(res.keys())
                res.close()
            finally:
                try:
                    disarm()
                except Exception:
                    pass
            conn.rollback()
    except QueryExecutionError:
        raise
    except (SQLAlchemyError, DBAPIError, Exception) as e:
        raise friendly_error(e) from e
    elapsed = time.perf_counter() - start

    truncated = len(rows) > row_limit
    rows = rows[:row_limit]
    df = _to_frame(rows, columns)
    return QueryResult(sql, df, len(df), elapsed, truncated, ctx.connection_id)


def explain_query(ctx: ConnectionContext, validation: ValidationResult) -> pd.DataFrame:
    """Run EXPLAIN on an already-validated query. EXPLAIN never executes the statement itself."""
    if not validation.is_valid:
        raise SQLValidationError("Only validated queries can be analysed.")
    prefix = "EXPLAIN QUERY PLAN " if ctx.dialect == "sqlite" else "EXPLAIN "
    try:
        with ctx.engine.connect().execution_options(no_parameters=True) as conn:
            res = conn.exec_driver_sql(prefix + validation.normalized_sql)
            return _to_frame(res.fetchall(), list(res.keys()))
    except Exception as e:
        raise friendly_error(e) from e
