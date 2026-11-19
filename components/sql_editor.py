"""SQL editor: monospace text area + highlighted preview, formatting helper."""
from __future__ import annotations

import sqlglot
import streamlit as st


def format_sql(sql: str, dialect: str) -> str:
    try:
        return ";\n".join(sqlglot.transpile(sql, read=dialect, write=dialect, pretty=True))
    except Exception:
        return sql


def format_callback(key: str, dialect: str) -> None:
    """Use as on_click: widget state may be changed in callbacks (before the widget is re-created)."""
    st.session_state[key] = format_sql(st.session_state.get(key, ""), dialect)


def sql_editor(key: str, height: int = 220, label: str = "SQL", placeholder: str = "SELECT …") -> str:
    # NOTE: the widget owns st.session_state[key]; seed it BEFORE calling this function.
    return st.text_area(label, key=key, height=height, placeholder=placeholder, label_visibility="collapsed")


def sql_preview(sql: str) -> None:
    with st.expander("Syntax-highlighted view", expanded=False):
        st.code(sql or "-- empty", language="sql")
