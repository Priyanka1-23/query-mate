import html

import streamlit as st

from components.connection_selector import add_connection_dialog
from components.status_components import badge, page_header
from utils.state import get_active_context, get_history, get_manager, go, request_activate


def _onboarding() -> None:
    st.markdown(
        '<div class="qm-hero"><h2>Your Database. Your Questions. Real Answers.</h2>'
        '<p>QueryMate turns plain-English questions into safe, read-only SQL grounded in your real schema, '
        'then helps you understand and visualise the results.</p></div>', unsafe_allow_html=True)
    err = st.session_state.get("conn_error")
    if err:
        st.error(f"Could not open the selected database. {err}", icon="🚫")
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.markdown("#### 🔌 Connect MySQL Database")
        st.caption("Bring your own database. Use a read-only account; credentials are encrypted and never sent to the AI.")
        if st.button("Connect MySQL Database", type="primary", use_container_width=True, key="ov_connect"):
            add_connection_dialog()
    with c2, st.container(border=True):
        st.markdown("#### 🛍️ Explore Sample Database")
        st.caption("A real e-commerce database (customers, orders, products, payments) so you can try everything instantly.")
        if st.button("Explore Sample Database", use_container_width=True, key="ov_sample"):
            request_activate("sample")
            st.rerun()
    st.markdown("**Connect → Explore → Ask → Understand → Analyze**")


def render() -> None:
    ctx = get_active_context()
    if ctx is None:
        page_header("Overview", "Your database workspace at a glance")
        _onboarding()
        return

    mgr, hist = get_manager(), get_history()
    infos = mgr.list_connections()
    names = {i.id: i.name for i in infos}
    page_header("Overview", "Your database workspace at a glance", ctx)

    st.markdown(
        f'<div class="qm-hero compact"><div><h2>Connected to {html.escape(ctx.name)}</h2>'
        f'<p>Ask a question in plain English, explore the schema, or write SQL. Every query is validated and read-only.</p></div>'
        f'<div>{badge(ctx.dialect.upper() + " · " + str(len(ctx.schema.tables)) + " tables", "neutral", dot=True)}</div></div>',
        unsafe_allow_html=True)
    saved = [i for i in infos if not i.is_sample]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Saved connections", len(saved), help="MySQL connections you saved (the built-in sample is not counted).")
    c2.metric("Active database", ctx.name)
    c3.metric("Tables", len([t for t in ctx.schema.tables if not t.is_view]))
    c4.metric("Queries executed", hist.count(executed_only=True), help="All databases. This database: %d" % hist.count(ctx.connection_id, executed_only=True))

    st.markdown('<div class="qm-section-title">Quick actions</div>', unsafe_allow_html=True)
    q1, q2, q3, q4 = st.columns(4)
    if q1.button("🔌 Connect Database", use_container_width=True):
        add_connection_dialog()
    if q2.button("🧭 Explore Database", use_container_width=True):
        go("explorer")
    if q3.button("💬 Ask QueryMate", type="primary", use_container_width=True):
        go("ask")
    if q4.button("🧪 Open SQL Playground", use_container_width=True):
        go("playground")

    left, right = st.columns([3, 2])
    with left, st.container(border=True):
        st.markdown(f"##### Recent queries · {html.escape(ctx.name)}")
        rows = hist.list(ctx.connection_id, limit=6)
        if not rows:
            st.caption("No queries yet. Ask a question to get started.")
        for r in rows:
            kind = {"success": "success", "failed": "error", "rejected": "warning"}.get(r["execution_status"], "neutral")
            label = r["natural_language_question"] or "Manual SQL"
            st.markdown(f"{badge(r['execution_status'], kind)} &nbsp;**{html.escape(label[:90])}**", unsafe_allow_html=True)
            st.code(r["generated_sql"][:240], language="sql")
    with right, st.container(border=True):
        st.markdown("##### Recent database activity")
        act = hist.list(None, limit=8)
        if not act:
            st.caption("Nothing yet.")
        for r in act:
            st.markdown(f"<span class='qm-muted'>{r['created_at']:%b %d %H:%M}</span> · **{html.escape(names.get(r['connection_id'], r['connection_id']))}** · "
                        f"{r['execution_status']}", unsafe_allow_html=True)
        st.divider()
        st.markdown("##### Connection status")
        st.markdown(badge("Connected", "success", dot=True) + " " + badge(ctx.dialect.upper(), "neutral"), unsafe_allow_html=True)
        for w in ctx.warnings:
            st.warning(w, icon="⚠️")
