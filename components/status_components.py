"""Reusable status / layout pieces in the Midnight Slate style."""
from __future__ import annotations

import html
from pathlib import Path

import streamlit as st

from services.sql_validation_service import ValidationResult

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def inject_css() -> None:
    css = (ASSETS / "styles.css").read_text()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def badge(text: str, kind: str = "neutral", dot: bool = False) -> str:
    d = '<span class="qm-dot"></span>' if dot else ""
    return f'<span class="qm-badge {kind}">{d}{html.escape(text)}</span>'


def db_badge(ctx) -> str:
    return badge(f"{ctx.name} · {ctx.dialect.upper()}", "info", dot=True)


def page_header(title: str, subtitle: str | None = None, ctx=None) -> None:
    right = db_badge(ctx) if ctx is not None else ""
    sub = f'<div class="qm-sub">{html.escape(subtitle)}</div>' if subtitle else ""
    st.markdown(
        f'<div class="qm-header"><div><h1>{html.escape(title)}</h1>{sub}</div><div>{right}</div></div>',
        unsafe_allow_html=True,
    )


def empty_state(title: str, text: str, icon: str = "🗂️") -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        st.caption(text)


def success_box(msg: str) -> None:
    st.success(msg, icon="✅")


def warning_box(msg: str) -> None:
    st.warning(msg, icon="⚠️")


def error_box(msg: str) -> None:
    st.error(msg, icon="🚫")


def validation_panel(v: ValidationResult) -> None:
    """Validation status, errors, warnings and notes."""
    if not v.is_valid:
        st.markdown(badge("Validation failed", "error", dot=True), unsafe_allow_html=True)
        for e in v.errors:
            st.error(e, icon="🛡️")
        return
    kind, label = ("warning", "Valid · with warnings") if v.warnings else ("success", "Valid · read-only")
    st.markdown(badge(label, kind, dot=True) + " " + badge("Safe to run", "success"), unsafe_allow_html=True)
    for w in v.warnings:
        st.warning(w, icon="⚠️")
    for n in v.notes:
        st.caption(f"ℹ️ {n}")


def require_connection(ctx, page_title: str, subtitle: str) -> bool:
    """Render a friendly blocker when there is no usable active connection. Returns True if OK."""
    if ctx is not None:
        return True
    page_header(page_title, subtitle)
    err = st.session_state.get("conn_error")
    if err:
        error_box(f"Could not open the selected database. {err}")
    else:
        st.info("Select a database in the sidebar, or explore the built-in sample database to get started.", icon="🗄️")
    c1, c2 = st.columns(2)
    from components.connection_selector import add_connection_dialog
    from utils.state import request_activate
    if c1.button("Explore Sample Database", type="primary", use_container_width=True, key=f"req_sample_{page_title}"):
        request_activate("sample")
        st.rerun()
    if c2.button("Connect MySQL Database", use_container_width=True, key=f"req_mysql_{page_title}"):
        add_connection_dialog()
    return False
