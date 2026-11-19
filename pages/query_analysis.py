import html
import re

import pandas as pd
import streamlit as st

from components.sql_editor import sql_editor
from components.status_components import badge, error_box, page_header, require_connection, validation_panel
from services.analysis_service import analyze_plan, complexity, describe_query_structure
from services.explanation_service import ai_explain_plan
from services.query_execution_service import execute_query, explain_query
from services.query_runner import validate_for
from utils.exceptions import QueryMateError
from utils.state import get_active_context, get_ai, get_history, get_prefs, reset_if_context_changed


def render() -> None:
    ctx = get_active_context()
    if not require_connection(ctx, "Query Analysis", "Understand how a query behaves and performs"):
        return
    reset_if_context_changed("analysis_", ctx)
    page_header("Query Analysis", "Findings come from real EXPLAIN output, not guesses", ctx)
    prefs = get_prefs()

    seed = st.session_state.pop("analysis_sql_seed", None)
    if seed is not None:
        st.session_state["analysis_sql"] = seed
        st.session_state.pop("analysis_out", None)
    elif "analysis_sql" not in st.session_state:
        st.session_state["analysis_sql"] = st.session_state.get("last_sql", "")

    sql = sql_editor("analysis_sql", 160, placeholder="Paste a SELECT query to analyse")
    v = validate_for(ctx, sql, prefs) if sql.strip() else None
    if v is not None:
        validation_panel(v)
    if st.button("📈 Analyze Query", type="primary", disabled=v is None or not v.is_valid):
        out = {"sql": v.normalized_sql, "conn": ctx.connection_id}
        try:
            with st.spinner("Running the query and reading its execution plan…"):
                out["result"] = execute_query(ctx, v, prefs.result_limit, prefs.query_timeout, ctx.connection_id)
                out["plan"] = explain_query(ctx, v)
        except QueryMateError as e:
            out["error"] = str(e)
        st.session_state["analysis_out"] = out

    out = st.session_state.get("analysis_out")
    if not out or out["conn"] != ctx.connection_id:
        st.caption("Enter or paste a query, then press Analyze. Tip: use **Analyze** in the SQL Playground to send a query here.")
        return
    if out.get("error"):
        error_box(out["error"])
        return

    res, plan = out["result"], out["plan"]
    struct = describe_query_structure(out["sql"], ctx.dialect)
    score, label = complexity(struct)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Execution time", f"{res.execution_time * 1000:,.0f} ms")
    c2.metric("Rows returned", f"{res.row_count:,}")
    c3.metric("Tables / joins", f"{len(struct.tables)} / {len(struct.joins)}")
    c4.metric("Complexity", f"{label} ({score})")

    t_struct, t_plan = st.tabs(["Query structure", "Performance (EXPLAIN)"])
    with t_struct:
        st.markdown("**Tables:** " + (", ".join(f"`{t}`" for t in struct.tables) or "none"))
        st.markdown("**Joins:** " + ("; ".join(f"`{j}`" for j in struct.joins) or "none"))
        st.markdown("**Filters:** " + (f"`{struct.filters}`" if struct.filters else "none"))
        st.markdown("**Aggregations:** " + (", ".join(f"`{a}`" for a in struct.aggregations) or "none"))
        st.markdown("**Group by:** " + (", ".join(f"`{g}`" for g in struct.group_by) or "none") + " &nbsp;|&nbsp; **Order by:** " +
                    (", ".join(f"`{o}`" for o in struct.order_by) or "none") + " &nbsp;|&nbsp; **Limit:** " + (struct.limit or "none"))
        st.caption("Complexity is a simple heuristic: joins, aggregations, grouping, subqueries, CTEs and window functions add points.")
    with t_plan:
        st.markdown("**Raw execution plan** (from the database)")
        st.dataframe(plan, use_container_width=True, hide_index=True)
        findings, recs = analyze_plan(plan, ctx.dialect, out["sql"], ctx.schema)
        if not findings:
            st.success("No performance concerns were detected in the execution plan.", icon="✅")
        for f in findings:
            (st.warning if f.severity == "warning" else st.info)(f.message, icon="⚠️" if f.severity == "warning" else "ℹ️")
        for r in recs:
            st.markdown(f'<div class="qm-note">{re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(r))}</div>', unsafe_allow_html=True)
        ai = get_ai()
        if ai is not None and st.button("✨ Explain this plan with AI", help="Sends the SQL and plan (no row data) to the AI provider."):
            try:
                with st.spinner("Explaining…"):
                    st.session_state["analysis_ai"] = ai_explain_plan(ai, ctx.dialect, out["sql"], plan, findings)
            except QueryMateError as e:
                st.error(str(e))
        if st.session_state.get("analysis_ai"):
            st.markdown(st.session_state["analysis_ai"])
            st.caption("AI explanation of the plan above. QueryMate never creates indexes or changes your schema.")
