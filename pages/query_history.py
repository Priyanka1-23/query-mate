import html

import pandas as pd
import streamlit as st

from components.result_table import render_result
from components.status_components import badge, error_box, page_header, require_connection
from services.query_runner import run_query
from utils.state import get_active_context, get_history, get_manager, get_prefs, go, request_activate


def render() -> None:
    ctx = get_active_context()
    if not require_connection(ctx, "Query History", "Revisit and re-run previous queries"):
        return
    page_header("Query History", "History is stored separately from the database you analyse", ctx)
    hist, mgr, prefs = get_history(), get_manager(), get_prefs()
    names = {i.id: i.name for i in mgr.list_connections()}

    t_hist, t_saved = st.tabs(["History", "Saved queries"])
    with t_hist:
        f1, f2, f3 = st.columns([2, 1, 1])
        search = f1.text_input("Search", placeholder="Search question or SQL…", key="hist_search")
        status = f2.selectbox("Status", ["all", "success", "failed", "rejected"], key="hist_status")
        scope = f3.selectbox("Scope", ["This database", "All databases"], key="hist_scope")
        rows = hist.list(ctx.connection_id if scope == "This database" else None, 200,
                         None if status == "all" else status, search or None)
        if not rows:
            st.info("No matching history yet.", icon="🕘")
        else:
            df = pd.DataFrame([{
                "ID": r["id"], "When": r["created_at"].strftime("%Y-%m-%d %H:%M"), "Database": names.get(r["connection_id"], r["connection_id"]),
                "Question": r["natural_language_question"] or "(manual SQL)", "Status": r["execution_status"],
                "Rows": r["returned_row_count"], "Time (ms)": None if r["execution_time"] is None else round(r["execution_time"] * 1000),
            } for r in rows])
            ev = st.dataframe(df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="hist_table")
            sel = ev.selection.rows if ev and ev.selection else []
            if sel:
                rec = rows[sel[0]]
                with st.container(border=True):
                    kind = {"success": "success", "failed": "error", "rejected": "warning"}.get(rec["execution_status"], "neutral")
                    st.markdown(f"{badge(rec['execution_status'], kind)} {badge(names.get(rec['connection_id'], rec['connection_id']), 'info')} "
                                f"{badge(rec['source'], 'neutral')}", unsafe_allow_html=True)
                    if rec["natural_language_question"]:
                        st.markdown(f"**Question:** {html.escape(rec['natural_language_question'])}", unsafe_allow_html=True)
                    st.code(rec["generated_sql"], language="sql")
                    if rec["error_message"]:
                        st.caption(f"Error: {rec['error_message']}")
                    same_db = rec["connection_id"] == ctx.connection_id
                    exists = rec["connection_id"] in names
                    if not same_db:
                        st.warning(f"This query was run on **{names.get(rec['connection_id'], 'a database that no longer exists')}**, "
                                   f"but the active database is **{ctx.name}**. It will not run against the wrong database.", icon="🔒")
                        if exists and st.button(f"Switch to {names[rec['connection_id']]}", key="hist_switch"):
                            request_activate(rec["connection_id"])
                            st.rerun()
                    b1, b2 = st.columns(2)
                    if b1.button("Open in Playground", key="hist_open", disabled=not same_db, use_container_width=True):
                        st.session_state["play_sql_seed"] = rec["generated_sql"]
                        go("playground")
                    if b2.button("↻ Rerun Query", key="hist_rerun", disabled=not same_db, type="primary", use_container_width=True):
                        with st.spinner("Re-validating against the current schema and running…"):
                            st.session_state["hist_run"] = (rec["id"], run_query(
                                ctx, rec["generated_sql"], prefs, hist, rec["natural_language_question"],
                                "rerun", expected_connection_id=rec["connection_id"]))
                held = st.session_state.get("hist_run")
                run = held[1] if held and held[0] == rec["id"] else None
                if run is not None:
                    if run.error:
                        error_box(run.error)
                    else:
                        render_result(run.result, "hist", rec["natural_language_question"], show_save=False)

    with t_saved:
        saved = hist.list_saved(ctx.connection_id)
        if not saved:
            st.info("No saved queries for this database. Save one from any result.", icon="💾")
        for s in saved:
            with st.container(border=True):
                st.markdown(f"**{html.escape(s['title'])}**  <span class='qm-muted'>{s['created_at']:%Y-%m-%d}</span>", unsafe_allow_html=True)
                st.code(s["sql"], language="sql")
                c1, c2 = st.columns(2)
                if c1.button("Open in Playground", key=f"sv_open_{s['id']}", use_container_width=True):
                    st.session_state["play_sql_seed"] = s["sql"]
                    go("playground")
                if c2.button("Delete", key=f"sv_del_{s['id']}", use_container_width=True):
                    hist.delete_saved(s["id"])
                    st.rerun()
