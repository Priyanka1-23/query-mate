"""SQL explanations (3 levels) and result summaries. AI-optional: a deterministic fallback
built from the parsed SQL / real data is always available."""
from __future__ import annotations

import pandas as pd

from prompts.explanation_prompt import (
    EXPLAIN_SYSTEM, EXPLAIN_USER, LEVELS, PLAN_SYSTEM, PLAN_USER, SUMMARY_SYSTEM, SUMMARY_USER,
)
from services.ai_service import AIService
from services.analysis_service import Finding, QueryStructure, describe_query_structure
from services.sql_generation_service import schema_to_prompt


def deterministic_explanation(sql: str, dialect: str, level: str, schema=None) -> str:
    s = describe_query_structure(sql, dialect)
    if s is None:
        return "The SQL could not be parsed, so it cannot be explained."
    tables = ", ".join(f"`{t}`" for t in s.tables) or "no tables"
    if level == "simple":
        parts = [f"This query reads data from {tables}"]
        if s.joins:
            parts.append(f"and combines them using {len(s.joins)} join(s)")
        if s.filters:
            parts.append("keeps only rows matching a filter")
        if s.group_by:
            parts.append(f"groups the rows by {', '.join(s.group_by)}")
        if s.aggregations:
            parts.append(f"and calculates {', '.join(s.aggregations)}")
        txt = ", ".join(parts) + "."
        if s.order_by:
            txt += f" Results are sorted by {', '.join(s.order_by)}."
        if s.limit:
            txt += f" At most {s.limit} rows are returned."
        return txt
    lines = []
    sel = ", ".join(s.select_items) if s.select_items else "(see query)"
    lines.append(f"- **SELECT**: returns {sel}{' (distinct rows only)' if s.distinct else ''}.")
    if s.tables:
        lines.append(f"- **FROM**: reads from {tables}.")
    for j in s.joins:
        lines.append(f"- **JOIN**: `{j}`.")
    if s.filters:
        lines.append(f"- **WHERE**: keeps rows where `{s.filters}`.")
    if s.group_by:
        lines.append(f"- **GROUP BY**: groups rows by `{', '.join(s.group_by)}`.")
    if s.having:
        lines.append(f"- **HAVING**: keeps groups where `{s.having}`.")
    if s.order_by:
        lines.append(f"- **ORDER BY**: sorts by `{', '.join(s.order_by)}`.")
    if s.limit:
        lines.append(f"- **LIMIT**: returns at most {s.limit} rows.")
    if s.ctes:
        lines.append(f"- **CTEs**: {', '.join(s.ctes)} are computed first and reused below.")
    if level == "technical":
        notes = []
        if s.select_star:
            notes.append("`SELECT *` reads every column; selecting only needed columns reduces I/O.")
        if s.joins:
            notes.append("Join columns should be indexed (primary/foreign keys usually are).")
        if s.order_by and not s.limit:
            notes.append("Sorting without a LIMIT sorts the whole result set.")
        if s.filters and schema is not None:
            notes.append("Columns in WHERE that are not indexed cause full scans; check the Query Analysis page for the real plan.")
        if s.aggregations and s.group_by:
            notes.append("GROUP BY aggregation may need a temporary table or sort on large inputs.")
        if notes:
            lines.append("\n**Potential performance concerns** (static analysis, not an execution plan):")
            lines += [f"- {n}" for n in notes]
    return "\n".join(lines)


def explain_sql(ai: AIService | None, sql: str, ctx, level: str) -> tuple[str, str]:
    """Return (text, source) where source is 'ai' or 'static'."""
    if level not in LEVELS:
        level = "simple"
    if ai is not None:
        try:
            s = describe_query_structure(sql, ctx.dialect)
            names = set(s.tables) if s else set()
            tables = [t for t in ctx.schema.tables if t.name in names] or list(ctx.schema.tables)[:10]
            user = EXPLAIN_USER.format(dialect=ctx.dialect.upper(), schema_text=schema_to_prompt(tables, ctx.schema),
                                       sql=sql, task=LEVELS[level][1])
            text = ai.complete_text(EXPLAIN_SYSTEM, user)
            if text:
                return text, "ai"
        except Exception:
            pass  # fall back to static explanation
    return deterministic_explanation(sql, ctx.dialect, level, ctx.schema), "static"


# ------------------------------------------------------------------ result summaries
def summarize_result(df: pd.DataFrame) -> str:
    """Deterministic, claims limited to what is literally in the DataFrame."""
    n = len(df)
    if n == 0:
        return "The query ran successfully but returned no rows. Check your filters or the date range."
    if n == 1 and len(df.columns) == 1:
        return f"The result is a single value: **{df.iloc[0, 0]}** ({df.columns[0]})."
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]
    cat = [c for c in df.columns if c not in num]
    parts = [f"The query returned **{n:,} row{'s' if n != 1 else ''}** across {len(df.columns)} column{'s' if len(df.columns) != 1 else ''}."]
    if num and cat and n > 1:
        m = num[-1]
        top = df.loc[df[m].idxmax()]
        low = df.loc[df[m].idxmin()]
        parts.append(f"The highest `{m}` is **{_fmt(top[m])}** for **{top[cat[0]]}**; the lowest is {_fmt(low[m])} for {low[cat[0]]}.")
        if n > 2 and (df[m] >= 0).all() and df[m].sum() > 0:
            parts.append(f"The values sum to {_fmt(df[m].sum())} (average {_fmt(df[m].mean())}).")
    elif num and n > 1:
        m = num[0]
        parts.append(f"`{m}` ranges from {_fmt(df[m].min())} to {_fmt(df[m].max())}.")
    return " ".join(parts)


def _fmt(v) -> str:
    try:
        f = float(v)
        return f"{f:,.0f}" if f == int(f) else f"{f:,.2f}"
    except Exception:
        return str(v)


def ai_summarize_result(ai: AIService, question: str | None, sql: str, df: pd.DataFrame, sample_rows: int = 20) -> str:
    """Sends up to `sample_rows` result rows to the AI provider. Call only on explicit user action."""
    shown = df.head(sample_rows)
    user = SUMMARY_USER.format(question=question or "(manual query)", sql=sql, total_rows=len(df),
                               shown=len(shown), table_text=shown.to_csv(index=False))
    return ai.complete_text(SUMMARY_SYSTEM, user, max_tokens=500)


def ai_explain_plan(ai: AIService, dialect: str, sql: str, plan: pd.DataFrame, findings: list[Finding]) -> str:
    user = PLAN_USER.format(dialect=dialect.upper(), sql=sql, plan_text=plan.to_csv(index=False),
                            findings_text="\n".join(f"- [{f.severity}] {f.message}" for f in findings) or "(none)")
    return ai.complete_text(PLAN_SYSTEM, user, max_tokens=500)
