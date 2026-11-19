"""Natural language -> SQL, grounded in the ACTIVE connection's schema."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from database.metadata_models import SchemaSnapshot, TableInfo
from prompts.sql_generation_prompt import SQL_FIX_PROMPT, SQL_USER_PROMPT, system_prompt
from services.ai_service import AIService
from utils.exceptions import AIServiceError


@dataclass
class GenerationResult:
    status: str  # sql | clarification_needed | unsupported
    connection_id: str
    question: str
    sql: str | None = None
    explanation: str | None = None
    clarifying_question: str | None = None
    options: list[str] = field(default_factory=list)
    reason: str | None = None
    suggestions: list[str] = field(default_factory=list)
    latency: float = 0.0


# ------------------------------------------------------------------ schema -> prompt text
def schema_to_prompt(tables: list[TableInfo], schema: SchemaSnapshot) -> str:
    lines = []
    for t in tables:
        cols = []
        for c in t.columns:
            tag = " PK" if c.is_primary_key else ""
            cols.append(f"{c.name} {c.data_type}{tag}")
        lines.append(f"TABLE {t.name}{' (view)' if t.is_view else ''}: " + ", ".join(cols))
    names = {t.name for t in tables}
    rel = [fk.describe() for t in tables for fk in t.foreign_keys if fk.ref_table in names]
    if rel:
        lines.append("RELATIONSHIPS (foreign keys):")
        lines += [f"  {r}" for r in rel]
    return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        out.add(w)
        if w.endswith("ies"):
            out.add(w[:-3] + "y")
        elif w.endswith("s"):
            out.add(w[:-1])
    return out


def select_relevant_tables(schema: SchemaSnapshot, question: str, limit: int = 25) -> list[TableInfo]:
    """Small schemas are sent whole. Large ones: keyword-score tables, then add FK neighbours."""
    if len(schema.tables) <= limit:
        return list(schema.tables)
    q = _tokens(question)
    scored = []
    for t in schema.tables:
        s = 3 * len(q & _tokens(t.name.replace("_", " ")))
        s += sum(1 for c in t.columns if q & _tokens(c.name.replace("_", " ")))
        scored.append((s, t))
    scored.sort(key=lambda x: (-x[0], x[1].name))
    chosen = {t.name: t for s, t in scored[: max(3, limit // 2)] if s > 0} or {t.name: t for _, t in scored[:5]}
    for t in list(chosen.values()):
        for fk in t.foreign_keys:
            if len(chosen) < limit and (rt := schema.table(fk.ref_table)):
                chosen.setdefault(rt.name, rt)
    for t in schema.tables:  # reverse neighbours
        if len(chosen) >= limit:
            break
        if any(fk.ref_table in chosen for fk in t.foreign_keys):
            chosen.setdefault(t.name, t)
    return list(chosen.values())


# ------------------------------------------------------------------ generation
def _parse(obj: dict, connection_id: str, question: str, latency: float) -> GenerationResult:
    status = str(obj.get("status", "")).strip().lower()
    aliases = {"clarification": "clarification_needed", "needs_clarification": "clarification_needed"}
    status = aliases.get(status, status)
    lst = lambda k: [str(x) for x in (obj.get(k) or []) if str(x).strip()][:6]
    if status == "sql":
        sql = (obj.get("sql") or "").strip()
        if not sql:
            raise AIServiceError("The AI did not return any SQL. Please rephrase and try again.")
        return GenerationResult("sql", connection_id, question, sql=sql, explanation=obj.get("explanation"), latency=latency)
    if status == "clarification_needed":
        return GenerationResult("clarification_needed", connection_id, question,
                                clarifying_question=obj.get("clarifying_question") or "Could you clarify what you mean?",
                                options=lst("options"), latency=latency)
    if status == "unsupported":
        return GenerationResult("unsupported", connection_id, question,
                                reason=obj.get("reason") or "The database does not contain the information needed.",
                                suggestions=lst("suggestions"), latency=latency)
    raise AIServiceError("The AI returned an unexpected status. Please try again.")


def generate_sql(ai: AIService, ctx, question: str, max_tables: int = 25) -> GenerationResult:
    question = (question or "").strip()
    if not question:
        raise AIServiceError("Please enter a question.")
    if len(question) > 1500:
        raise AIServiceError("The question is too long (max 1500 characters).")
    tables = select_relevant_tables(ctx.schema, question, max_tables)
    user = SQL_USER_PROMPT.format(database=ctx.schema.database_name,
                                  schema_text=schema_to_prompt(tables, ctx.schema), question=question)
    t0 = time.perf_counter()
    obj = ai.complete_json(system_prompt(ctx.dialect), user)
    return _parse(obj, ctx.connection_id, question, time.perf_counter() - t0)


def correct_sql(ai: AIService, ctx, question: str, bad_sql: str, error: str, max_tables: int = 25) -> GenerationResult:
    tables = select_relevant_tables(ctx.schema, question or bad_sql, max_tables)
    user = SQL_FIX_PROMPT.format(database=ctx.schema.database_name, schema_text=schema_to_prompt(tables, ctx.schema),
                                 question=question or "(written manually)", bad_sql=bad_sql, error=error)
    t0 = time.perf_counter()
    obj = ai.complete_json(system_prompt(ctx.dialect), user)
    return _parse(obj, ctx.connection_id, question, time.perf_counter() - t0)


# ------------------------------------------------------------------ suggestions (schema-grounded, no AI needed)
_NUMERIC = ("INT", "DEC", "NUM", "FLOAT", "DOUBLE", "REAL")
_DATE = ("DATE", "TIME")
_CATEGORICAL = ("city", "status", "type", "category", "method", "country", "state", "region", "gender", "role")
_STOCK = ("stock", "inventory", "quantity_on_hand")


def _h(name: str) -> str:
    return name.replace("_", " ")


def suggest_questions(schema: SchemaSnapshot, n: int = 8) -> list[str]:
    """Only references tables/columns that exist in the schema."""
    tables = [t for t in schema.tables if not t.is_view]
    tables.sort(key=lambda t: (-len(t.foreign_keys), t.name))
    buckets: list[list[str]] = [[], [], [], [], []]
    for t in tables:
        nm = _h(t.name)
        buckets[0].append(f"How many rows are in {nm}?")
        for c in t.columns:
            if c.is_primary_key or c.is_foreign_key:
                continue
            ty, cn = c.data_type.upper(), c.name.lower()
            if any(k in ty for k in _DATE):
                buckets[1].append(f"Show the 10 most recent {nm} by {_h(c.name)}.")
                buckets[1].append(f"What is the monthly count of {nm} by {_h(c.name)}?")
            elif any(k in ty for k in _NUMERIC):
                if any(s in cn for s in _STOCK):
                    buckets[2].append(f"Which {nm} have low {_h(c.name)}?")
                buckets[2].append(f"What is the average {_h(c.name)} in {nm}?")
                buckets[2].append(f"Show the top 5 {nm} by {_h(c.name)}.")
            elif any(k in cn for k in _CATEGORICAL):
                buckets[3].append(f"Show the number of {nm} for each {_h(c.name)}.")
        for fk in t.foreign_keys:
            buckets[4].append(f"How many {nm} does each {_h(fk.ref_table)} have? Show the top 10.")
    out: list[str] = []
    order = [4, 2, 3, 1, 0]  # relationships first, bare row counts last
    i = 0
    while len(out) < n and any(buckets):
        b = buckets[order[i % len(order)]]
        if b:
            q = b.pop(0)
            if q not in out:
                out.append(q)
        i += 1
    return out
