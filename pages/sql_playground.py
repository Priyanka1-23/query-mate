import streamlit as st

from components.result_table import render_result
from components.sql_editor import format_callback, sql_editor, sql_preview
from components.status_components import error_box, page_header, require_connection, validation_panel
from prompts.explanation_prompt import LEVELS
from services.explanation_service import explain_sql
from services.query_runner import run_query, validate_for
from utils.state import get_active_context, get_ai, get_history, get_prefs, go, reset_if_context_changed

DEFAULT_SQL = "SELECT * FROM {table} LIMIT 10"


def render() -> None:
    ctx = get_active_context()
    if not require_connection(ctx, "SQL Playground", "Write, understand and run read-only SQL"):
        return
    reset_if_context_changed("play_", ctx)
    page_header("SQL Playground", "Same validation and read-only rules as Ask QueryMate: no bypass", ctx)
    prefs, hist = get_prefs(), get_history()

    seed = st.session_state.pop("play_sql_seed", None)  # hand-off from Ask / History / Analysis
    if seed is not None:
        st.session_state["play_sql_editor"] = seed
        st.session_state.pop("play_run", None)
        st.session_state.pop("play_explain", None)
    elif "play_sql_editor" not in st.session_state:
        first = next((t.name for t in ctx.schema.tables if not t.is_view), None)
        st.session_state["play_sql_editor"] = DEFAULT_SQL.format(table=first) if first else "SELECT 1"

    sql = sql_editor("play_sql_editor", 240)
    v = validate_for(ctx, sql, prefs)
    validation_panel(v)
    sql_preview(sql)

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    run_clicked = c1.button("▶ Run Query", type="primary", disabled=not v.is_valid, use_container_width=True)
    c2.button("✨ Format SQL", use_container_width=True, on_click=format_callback, args=("play_sql_editor", ctx.dialect))
    if c3.button("📈 Analyze", use_container_width=True, disabled=not v.is_valid):
        st.session_state["analysis_sql_seed"] = sql
        go("analysis")
    c4.button("Clear", use_container_width=True, on_click=lambda: st.session_state.update(play_sql_editor="", play_run=None, play_explain=None))

    if run_clicked:
        with st.spinner("Running query…"):
            st.session_state["play_run"] = run_query(ctx, sql, prefs, hist, None, "playground")
        st.session_state["last_sql"] = sql

    t_run, t_explain = st.tabs(["Results", "Explain SQL"])
    with t_run:
        run = st.session_state.get("play_run")
        if run is None:
            st.caption("Run a query to see results here.")
        elif v.normalized_sql != run.validation.normalized_sql:
            st.info("The SQL changed since the last run. Press **Run Query** to execute the new version.", icon="✏️")
        elif run.error:
            error_box(run.error)
        else:
            render_result(run.result, "play")
    with t_explain:
        level = st.radio("Level", list(LEVELS), format_func=lambda k: LEVELS[k][0], horizontal=True, key="play_level")
        if st.button("🔍 Explain SQL", disabled=not v.is_valid):
            with st.spinner("Explaining…"):
                text, src = explain_sql(get_ai(), v.normalized_sql, ctx, level)
            st.session_state["play_explain"] = (level, text, src, v.normalized_sql)
        exp = st.session_state.get("play_explain")
        if exp:
            lvl, text, src, esql = exp
            st.markdown(text)
            st.caption(("Written by AI" if src == "ai" else "Generated from the parsed SQL (no AI key configured or AI unavailable)")
                       + f" · {LEVELS[lvl][0]} level" + ("" if esql == v.normalized_sql else " · ⚠️ SQL has changed since this explanation"))
