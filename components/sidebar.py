"""Persistent sidebar: active database, status, switch / add / reconnect."""
from __future__ import annotations

import html

import streamlit as st

from components.connection_selector import add_connection_dialog
from components.status_components import badge
from utils.state import (
    active_connection_id, apply_pending_activation, get_active_context, get_manager, reconnect_active, set_active,
)


def _on_switch() -> None:
    set_active(st.session_state.get("db_selector"))


def render_sidebar() -> None:
    apply_pending_activation()  # must run before the selector widget exists
    mgr = get_manager()
    infos = mgr.list_connections()
    ids = [i.id for i in infos]
    by_id = {i.id: i for i in infos}
    if active_connection_id() and active_connection_id() not in ids:
        set_active(None)
        st.session_state["db_selector"] = None
    if "db_selector" not in st.session_state:
        st.session_state["db_selector"] = active_connection_id()

    with st.sidebar:
        st.markdown('<div class="qm-side-label">Active database</div>', unsafe_allow_html=True)
        st.selectbox(
            "Switch database", ids, key="db_selector", index=None,
            format_func=lambda i: f"{by_id[i].name} · {by_id[i].dialect.upper()}", placeholder="Select a database…",
            on_change=_on_switch, label_visibility="collapsed",
        )
        ctx = get_active_context()
        if ctx is not None:
            st.markdown(
                f'<div class="qm-side-db"><b>{html.escape(ctx.name)}</b><span>{ctx.dialect.upper()} · '
                f'{html.escape(ctx.schema.database_name)} · {len(ctx.schema.tables)} tables</span><br>'
                f'{badge("Connected", "success", dot=True)}</div>', unsafe_allow_html=True)
            for w in ctx.warnings:
                st.caption(f"⚠️ {w}")
        elif active_connection_id():
            st.markdown(f'<div class="qm-side-db"><b>Connection problem</b><br>{badge("Disconnected", "error", dot=True)}</div>', unsafe_allow_html=True)
            if st.session_state.get("conn_error"):
                st.caption(st.session_state["conn_error"])
        else:
            st.markdown(f'<div class="qm-side-db"><b>No database selected</b><br>{badge("Not connected", "neutral")}</div>', unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        if c1.button("＋ Add", use_container_width=True, help="Add a MySQL connection"):
            add_connection_dialog()
        if c2.button("↻ Reconnect", use_container_width=True, disabled=not active_connection_id(), help="Re-open the connection and re-read the schema"):
            reconnect_active()
            st.rerun()
        st.divider()
        st.caption("QueryMate · read-only by design")
