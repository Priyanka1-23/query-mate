"""Query structure analysis + EXPLAIN-based performance findings (evidence only)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
import sqlglot
from sqlglot import exp

from database.metadata_models import SchemaSnapshot


@dataclass
class QueryStructure:
    tables: list[str] = field(default_factory=list)
    ctes: list[str] = field(default_factory=list)
    joins: list[str] = field(default_factory=list)       # "INNER JOIN orders ON ..."
    filters: str | None = None
    group_by: list[str] = field(default_factory=list)
    having: str | None = None
    order_by: list[str] = field(default_factory=list)
    limit: str | None = None
    aggregations: list[str] = field(default_factory=list)
    select_items: list[str] = field(default_factory=list)
    distinct: bool = False
    subqueries: int = 0
    has_window: bool = False
    select_star: bool = False


def describe_query_structure(sql: str, dialect: str) -> QueryStructure | None:
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None
    s = QueryStructure()
    s.ctes = [c.alias_or_name for c in tree.find_all(exp.CTE)]
    cte_l = {c.lower() for c in s.ctes}
    s.tables = list(dict.fromkeys(t.name for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in cte_l))
    for j in tree.find_all(exp.Join):
        kind = " ".join(x for x in [j.side, j.kind] if x).upper() or "INNER"
        cond = j.args.get("on")
        s.joins.append(f"{kind} JOIN {j.this.sql(dialect=dialect)}" + (f" ON {cond.sql(dialect=dialect)}" if cond else ""))
    top = tree
    if isinstance(top, exp.Query):
        w, h = top.args.get("where"), top.args.get("having")
        s.filters = w.this.sql(dialect=dialect) if w else None
        s.having = h.this.sql(dialect=dialect) if h else None
        g = top.args.get("group")
        s.group_by = [e.sql(dialect=dialect) for e in g.expressions] if g else []
        o = top.args.get("order")
        s.order_by = [e.sql(dialect=dialect) for e in o.expressions] if o else []
        lim = top.args.get("limit")
        s.limit = lim.expression.sql(dialect=dialect) if lim and lim.expression is not None else None
        s.distinct = bool(top.args.get("distinct"))
        if isinstance(top, exp.Select):
            s.select_items = [e.sql(dialect=dialect) for e in top.expressions]
            s.select_star = any(isinstance(e, exp.Star) or (isinstance(e, exp.Column) and isinstance(e.this, exp.Star)) for e in top.expressions)
    s.aggregations = list(dict.fromkeys(a.sql(dialect=dialect) for a in tree.find_all(exp.AggFunc)))
    s.subqueries = len(list(tree.find_all(exp.Subquery))) - (1 if isinstance(tree, exp.Subquery) else 0)
    s.has_window = any(tree.find_all(exp.Window))
    return s


def complexity(s: QueryStructure) -> tuple[int, str]:
    score = len(s.joins) * 2 + len(s.aggregations) + (2 if s.group_by else 0) + (1 if s.having else 0) \
        + s.subqueries * 2 + len(s.ctes) * 2 + (2 if s.has_window else 0) + (1 if s.filters else 0)
    label = "Low" if score <= 4 else "Medium" if score <= 9 else "High"
    return score, label


@dataclass
class Finding:
    severity: str  # info | warning
    message: str
    table: str | None = None


def _filter_columns(sql: str, dialect: str, schema: SchemaSnapshot) -> dict[str, set[str]]:
    """Columns used in WHERE / JOIN ON / GROUP BY / ORDER BY, resolved to real tables."""
    out: dict[str, set[str]] = {}
    try:
        tree = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return out
    alias = {}
    base = []
    for t in tree.find_all(exp.Table):
        info = schema.table(t.name) if t.name else None
        if info:
            alias[(t.alias or t.name).lower()] = info
            base.append(info)
    nodes = [w for w in tree.find_all(exp.Where)] + [j.args["on"] for j in tree.find_all(exp.Join) if j.args.get("on")]
    for n in nodes:
        for c in n.find_all(exp.Column):
            info = alias.get(c.table.lower()) if c.table else None
            if info is None and not c.table:
                owners = [i for i in base if c.name.lower() in {x.lower() for x in i.column_names()}]
                info = owners[0] if len(owners) == 1 else None
            if info:
                out.setdefault(info.name, set()).add(c.name)
    return out


def analyze_plan(plan: pd.DataFrame, dialect: str, sql: str, schema: SchemaSnapshot) -> tuple[list[Finding], list[str]]:
    """Return (findings, recommendations). Everything is derived from actual EXPLAIN rows."""
    findings: list[Finding] = []
    full_scan_tables: set[str] = set()
    cols = {c.lower(): c for c in plan.columns}

    if dialect == "sqlite":
        for detail in plan[cols.get("detail", plan.columns[-1])].astype(str):
            m = re.match(r"SCAN (?:TABLE )?(\w+)", detail)
            if m and "USING COVERING INDEX" not in detail:
                full_scan_tables.add(m.group(1))
                findings.append(Finding("warning", f"Full table scan on `{m.group(1)}` ({detail}).", m.group(1)))
            elif m:
                findings.append(Finding("info", f"Full scan of a covering index on `{m.group(1)}` ({detail}).", m.group(1)))
            elif detail.startswith("SEARCH"):
                findings.append(Finding("info", f"Index/key lookup: {detail}."))
            if "USE TEMP B-TREE" in detail:
                findings.append(Finding("warning", f"Temporary sort structure needed ({detail})."))
            if "AUTOMATIC" in detail and "INDEX" in detail:
                findings.append(Finding("warning", f"SQLite built a temporary automatic index ({detail}), which suggests a missing index."))
    else:
        for _, r in plan.iterrows():
            tbl = r.get(cols.get("table")) if "table" in cols else None
            typ = str(r.get(cols["type"])) if "type" in cols and r.get(cols["type"]) is not None else ""
            key = r.get(cols["key"]) if "key" in cols else None
            rows = r.get(cols["rows"]) if "rows" in cols else None
            extra = str(r.get(cols["extra"]) or "") if "extra" in cols else ""
            rows_txt = f" (~{int(rows):,} rows estimated)" if rows is not None and pd.notna(rows) else ""
            if typ.upper() == "ALL" and tbl:
                full_scan_tables.add(str(tbl))
                findings.append(Finding("warning", f"Full table scan on `{tbl}`{rows_txt}.", str(tbl)))
            elif typ.lower() == "index" and tbl:
                findings.append(Finding("info", f"Full index scan on `{tbl}` using `{key}`{rows_txt}.", str(tbl)))
            elif key and pd.notna(key) and tbl:
                findings.append(Finding("info", f"`{tbl}` uses index `{key}` (access type {typ}){rows_txt}.", str(tbl)))
            for flag, msg in (("Using filesort", "needs an extra sorting pass (filesort)"),
                              ("Using temporary", "creates a temporary table"),
                              ("Using join buffer", "uses a join buffer (no usable index for the join)")):
                if flag in extra:
                    findings.append(Finding("warning", f"`{tbl}` {msg}."))

    recs: list[str] = []
    if full_scan_tables:
        used = _filter_columns(sql, dialect, schema)
        for t in sorted(full_scan_tables):
            info = schema.table(t)
            candidates = [c for c in sorted(used.get(t, set()))
                          if info and not any(col.name == c and col.is_primary_key for col in info.columns)]
            if candidates:
                recs.append(f"Recommendation (review before applying): `{t}` is fully scanned and column(s) "
                            f"{', '.join('`'+c+'`' for c in candidates)} appear in WHERE/JOIN conditions, so an index on "
                            f"`{t}({', '.join(candidates[:2])})` may help. Indexes speed reads but add write overhead and "
                            f"storage; QueryMate never creates them for you.")
    return findings, recs
