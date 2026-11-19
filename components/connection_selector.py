"""Add-connection dialog and the active-database selector."""
from __future__ import annotations

import streamlit as st

from database.connection_manager import ConnectionParams
from utils.exceptions import QueryMateError
from utils.state import apply_pending_activation, get_manager, request_activate, set_active


@st.dialog("Add database connection", width="large")
def add_connection_dialog() -> None:
    st.caption("Use a **read-only** database account. Passwords are encrypted at rest and never sent to the AI provider.")
    with st.form("add_conn_form", clear_on_submit=False):
        name = st.text_input("Connection name", placeholder="e.g. Analytics (read-only)")
        c1, c2 = st.columns([3, 1])
        host = c1.text_input("Host", value="localhost")
        port = c2.number_input("Port", min_value=1, max_value=65535, value=3306, step=1)
        dbname = st.text_input("Database name")
        c3, c4 = st.columns(2)
        user = c3.text_input("Username")
        pwd = c4.text_input("Password", type="password")
        b1, b2, b3 = st.columns(3)
        test = b1.form_submit_button("Test Connection", use_container_width=True)
        save = b2.form_submit_button("Save Connection", type="primary", use_container_width=True)
        cancel = b3.form_submit_button("Cancel", use_container_width=True)

    if cancel:
        st.rerun()
    if not (test or save):
        return
    params = ConnectionParams(name.strip(), host.strip(), int(port), dbname.strip(), user.strip(), pwd)
    mgr = get_manager()
    try:
        with st.spinner("Testing connection…"):
            warnings = mgr.test_connection(params)
    except QueryMateError as e:
        st.error(str(e), icon="🚫")
        return
    st.success("Connection successful.", icon="✅")
    for w in warnings:
        st.warning(w, icon="⚠️")
    if save:
        try:
            cid = mgr.save_connection(params)
            with st.spinner("Reading schema…"):
                mgr.get_context(cid)
        except QueryMateError as e:
            st.error(str(e), icon="🚫")
            return
        request_activate(cid)
        st.rerun()
