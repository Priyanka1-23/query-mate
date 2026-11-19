import pandas as pd
import streamlit as st

from components.status_components import page_header, require_connection
from services.schema_service import count_rows, preview_table
from utils.exceptions import QueryMateError
from utils.state import get_active_context, reset_if_context_changed


def _er_dot(schema) -> str:
    lines = ["digraph G { rankdir=LR; node [shape=box, style=\"rounded,filled\", fillcolor=\"#EFF6FF\", color=\"#2563EB\", fontname=\"Helvetica\"]; edge [color=\"#64748B\", fontname=\"Helvetica\", fontsize=9];"]
    for t in schema.tables:
        lines.append(f'"{t.name}";')
    for fk in schema.relationships:
        lines.append(f'"{fk.table}" -> "{fk.ref_table}" [label="{", ".join(fk.columns)}"];')
    lines.append("}")
    return "\n".join(lines)


def render() -> None:
    ctx = get_active_context()
    if not require_connection(ctx, "Database Explorer", "Understand your database structure"):
        return
    reset_if_context_changed("explore_", ctx)
    page_header("Database Explorer", "Tables, columns, keys and relationships", ctx)
    schema = ctx.schema
    n_tables = len([t for t in schema.tables if not t.is_view])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Database", schema.database_name)
    c2.metric("Type", "MySQL" if schema.dialect == "mysql" else schema.dialect.upper())
    c3.metric("Tables", n_tables)
    c4.metric("Relationships", len(schema.relationships))

    if not schema.tables:
        st.info("This database has no tables.", icon="🗂️")
        return

    t_tables, t_rel = st.tabs(["Tables", "Relationships"])
    with t_tables:
        left, right = st.columns([1, 3])
        with left:
            q = st.text_input("Search tables", placeholder="Filter…", key="explore_search")
            names = [t.name for t in schema.tables if q.lower() in t.name.lower()]
            if not names:
                st.caption("No tables match.")
                return
            sel = st.radio("Tables", names, key="explore_table", label_visibility="collapsed")
        info = schema.table(sel)
        with right:
            st.markdown(f"### {info.name}" + ("  `view`" if info.is_view else ""))
            rows = count_rows(ctx.engine, schema, info.name)
            fk_map = {c: f"{fk.ref_table}.{r}" for fk in info.foreign_keys for c, r in zip(fk.columns, fk.ref_columns)}
            df = pd.DataFrame([{
                "Column": c.name, "Type": c.data_type,
                "Key": "🔑 PK" if c.is_primary_key else ("🔗 FK" if c.is_foreign_key else ""),
                "References": fk_map.get(c.name, ""), "Nullable": "yes" if c.nullable else "no",
            } for c in info.columns])
            st.caption(f"{len(info.columns)} columns" + (f" · {rows:,} rows" if rows is not None else ""))
            st.dataframe(df, use_container_width=True, hide_index=True)
            if info.foreign_keys:
                st.markdown("**Foreign keys**")
                for fk in info.foreign_keys:
                    st.markdown(f"- `{fk.describe()}`")
            limit = st.slider("Preview rows", 5, 100, 10, step=5, key="explore_limit")
            try:
                st.dataframe(preview_table(ctx.engine, schema, info.name, limit), use_container_width=True, hide_index=True)
            except QueryMateError as e:
                st.error(str(e))
    with t_rel:
        if not schema.relationships:
            st.info("No foreign-key relationships were found in this database.", icon="🔗")
        else:
            st.graphviz_chart(_er_dot(schema), use_container_width=True)
            st.dataframe(pd.DataFrame([{"From": f"{f.table}({', '.join(f.columns)})", "To": f"{f.ref_table}({', '.join(f.ref_columns)})"}
                                       for f in schema.relationships]), use_container_width=True, hide_index=True)
