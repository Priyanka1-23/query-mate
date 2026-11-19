"""Independent SQL validation using a real parser (SQLGlot). Never trusts the model.

Pipeline: parse -> exactly one statement -> root must be a query (SELECT / set-op / CTE)
-> no write/DDL/admin/locking nodes anywhere in the AST -> no dangerous functions
-> tables/columns exist in the schema snapshot -> inject/cap LIMIT -> regenerate SQL from the AST
(so hidden comment payloads never reach the database).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from database.metadata_models import SchemaSnapshot

logging.getLogger("sqlglot").setLevel(logging.ERROR)  # silence "falling back to Command" noise

MAX_SQL_CHARS = 20_000


def _classes(*names: str) -> tuple[type, ...]:
    return tuple(getattr(exp, n) for n in names if hasattr(exp, n))


_FORBIDDEN_NODES = _classes(
    "Insert", "Update", "Delete", "Drop", "Alter", "AlterTable", "Create", "TruncateTable", "Merge",
    "Command", "Into", "Lock", "Set", "Use", "LoadData", "Kill", "Grant", "Revoke", "Transaction",
    "Commit", "Rollback", "Copy", "Pragma", "Attach", "Detach", "Show", "Describe", "Analyze",
    "Declare", "Execute", "Refresh",
)
_FORBIDDEN_FUNCS = {
    "SLEEP", "BENCHMARK", "LOAD_FILE", "GET_LOCK", "RELEASE_LOCK", "RELEASE_ALL_LOCKS", "IS_FREE_LOCK",
    "IS_USED_LOCK", "SYS_EXEC", "SYS_EVAL", "PG_SLEEP", "LOAD_EXTENSION", "READFILE", "WRITEFILE",
    "RANDOMBLOB", "ZEROBLOB", "MASTER_POS_WAIT", "SOURCE_POS_WAIT",
}


@dataclass
class ValidationResult:
    is_valid: bool
    normalized_sql: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables: list[str] = field(default_factory=list)
    limit_applied: int | None = None
    notes: list[str] = field(default_factory=list)  # informational, not warnings

    @property
    def status(self) -> str:
        if not self.is_valid:
            return "invalid"
        return "warning" if self.warnings else "valid"


def _reject(msg: str) -> ValidationResult:
    return ValidationResult(False, errors=[msg])


def validate_sql(sql: str, dialect: str, schema: SchemaSnapshot | None = None, row_limit: int = 1000) -> ValidationResult:
    sql = (sql or "").strip()
    if not sql:
        return _reject("The query is empty.")
    if len(sql) > MAX_SQL_CHARS:
        return _reject("The query is too long.")

    # 1) parse (fail closed on anything the parser cannot understand)
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except SqlglotError as e:
        first = str(e).splitlines()[0][:200] if str(e) else "syntax error"
        return _reject(f"SQL could not be parsed as {dialect.upper()}: {first}")
    if not statements:
        return _reject("No SQL statement found.")

    # 2) single statement
    if len(statements) > 1:
        return _reject("Multiple statements are not allowed. Submit exactly one SELECT query.")
    tree = statements[0]

    # 3) must be a read query
    root = tree
    while isinstance(root, exp.Subquery):
        root = root.this
    if not isinstance(root, exp.Query):
        return _reject(f"Only read-only SELECT queries are allowed (found {type(tree).__name__.upper()}).")

    # 4) deny-list over the *entire* AST (catches writes nested in CTEs/subqueries, SELECT INTO, FOR UPDATE ...)
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            return _reject(f"Operation not allowed in read-only mode: {type(node).__name__.upper()}.")
    for fn in tree.find_all(exp.Func):
        name = (fn.name if isinstance(fn, exp.Anonymous) else fn.sql_name()).upper()
        if name in _FORBIDDEN_FUNCS:
            return _reject(f"Function not allowed: {name}().")
    if tree.args.get("locks") or any(tree.find_all(exp.Lock)):
        return _reject("Locking reads (FOR UPDATE / LOCK IN SHARE MODE) are not allowed.")

    errors: list[str] = []
    warnings: list[str] = []
    tables: list[str] = []

    # 5) schema grounding
    if schema is not None:
        _check_schema(tree, schema, errors, warnings, tables)
    else:
        tables = sorted({t.name for t in tree.find_all(exp.Table) if t.name})
    if errors:
        return ValidationResult(False, errors=errors, warnings=warnings, tables=tables)

    # 6) soft warnings
    if any(isinstance(s, exp.Star) for s in tree.find_all(exp.Star)) and not any(tree.find_all(exp.AggFunc)):
        warnings.append("SELECT * returns every column; consider selecting only what you need.")
    for j in tree.find_all(exp.Join):
        if not j.args.get("on") and not j.args.get("using") and j.args.get("method") is None:
            warnings.append("A JOIN without an ON condition produces a Cartesian product and can be very slow.")
            break

    # 7) enforce LIMIT, then regenerate SQL from the AST (drops comments)
    applied = None
    try:
        tree, applied = _enforce_limit(tree, root, row_limit)
        normalized = tree.sql(dialect=dialect, comments=False)
    except SqlglotError as e:
        return _reject(f"Could not normalise the query: {str(e)[:150]}")
    notes = [f"A row limit of {applied:,} was applied."] if applied is not None else []
    return ValidationResult(True, normalized, [], warnings, tables, applied, notes)


def _enforce_limit(tree: exp.Expression, root: exp.Query, row_limit: int):
    row_limit = max(1, int(row_limit))
    target = tree if isinstance(tree, exp.Query) and not isinstance(tree, exp.Subquery) else None
    if target is None:  # parenthesised query: wrap it
        wrapped = exp.select("*").from_(tree.subquery("_qm"))
        return wrapped.limit(row_limit), row_limit
    lim = target.args.get("limit")
    if target.args.get("fetch") is not None:
        return tree, None
    if lim is None:
        target.limit(row_limit, copy=False)
        return tree, row_limit
    count = lim.args.get("expression")
    if isinstance(count, exp.Literal) and count.is_int and int(count.name) <= row_limit:
        return tree, None
    lim.set("expression", exp.Literal.number(row_limit))
    return tree, row_limit


def _check_schema(tree, schema: SchemaSnapshot, errors, warnings, tables_out) -> None:
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    derived = {s.alias.lower() for s in tree.find_all(exp.Subquery) if s.alias}
    select_aliases = {a.alias.lower() for a in tree.find_all(exp.Alias) if a.alias}
    alias_map: dict[str, object] = {}
    base = []
    for t in tree.find_all(exp.Table):
        if not t.name:
            continue
        db = t.args.get("db")
        if db is not None and db.name.lower() not in {schema.database_name.lower(), "main"}:
            errors.append(f"Access to another database ('{db.name}') is not allowed.")
            continue
        if db is None and t.name.lower() in cte_names:
            continue
        info = schema.table(t.name)
        if info is None:
            hint = f" Available tables: {', '.join(schema.table_names()[:12])}." if schema.tables else ""
            errors.append(f"Table '{t.name}' does not exist in this database.{hint}")
            continue
        base.append(info)
        alias_map[(t.alias or t.name).lower()] = info
        alias_map.setdefault(t.name.lower(), info)
        if info.name not in tables_out:
            tables_out.append(info.name)

    has_derived = bool(cte_names or derived)
    for col in tree.find_all(exp.Column):
        if isinstance(col.this, exp.Star):
            continue
        name = col.name.lower()
        qual = col.table.lower()
        if qual:
            if qual in cte_names or qual in derived:
                continue
            info = alias_map.get(qual)
            if info is None:
                if not any("does not exist" in e and qual in e.lower() for e in errors):
                    errors.append(f"Unknown table or alias '{col.table}' referenced for column '{col.name}'.")
                continue
            if name not in {c.lower() for c in info.column_names()}:
                errors.append(f"Column '{col.name}' does not exist in table '{info.name}'. "
                              f"Columns: {', '.join(info.column_names())}.")
        else:
            if name in select_aliases:
                continue
            if any(name in {c.lower() for c in i.column_names()} for i in base):
                continue
            if has_derived:
                continue  # may come from a CTE / derived table; cannot verify statically
            if base:
                errors.append(f"Column '{col.name}' was not found in the referenced tables.")
