"""Streamlit session helpers. Credentials never live in session state; only connection IDs do."""
from __future__ import annotations

import streamlit as st

from database.connection_manager import ConnectionContext, ConnectionManager
from services.ai_service import AIService, build_provider
from services.history_service import HistoryService
from utils import config
from utils.config import Preferences
from utils.exceptions import QueryMateError

WORKFLOW_PREFIXES = ("ask_", "play_", "analysis_", "hist_", "result_")


@st.cache_resource(show_spinner=False)
def get_manager() -> ConnectionManager:
    return ConnectionManager(timeout=Preferences.load().query_timeout)


def get_history() -> HistoryService:
    return HistoryService(get_manager().session_factory)


def get_prefs() -> Preferences:
    if "prefs" not in st.session_state:
        st.session_state["prefs"] = Preferences.load()
    return st.session_state["prefs"]


# ---------------------------------------------------------------- AI
def api_key_source() -> str | None:
    if st.session_state.get("session_api_key"):
        return "session"
    if config.groq_api_key_from_env():
        return "environment"
    return None


def get_ai() -> AIService | None:
    key = st.session_state.get("session_api_key") or config.groq_api_key_from_env()
    if not key:
        return None
    model = get_prefs().ai_model
    cached = st.session_state.get("_ai")
    if cached and cached[0] == (key, model):
        return cached[1]
    ai = AIService(build_provider(key, model))
    st.session_state["_ai"] = ((key, model), ai)
    return ai


# ---------------------------------------------------------------- active connection
def clear_workflow_state() -> None:
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith(WORKFLOW_PREFIXES):
            del st.session_state[k]


def request_activate(connection_id: str | None) -> None:
    """Safe from any handler: applied at the top of the next run, before widgets are created."""
    st.session_state["_pending_activate"] = connection_id or ""


def apply_pending_activation() -> None:
    if "_pending_activate" not in st.session_state:
        return
    cid = st.session_state.pop("_pending_activate") or None
    set_active(cid)
    st.session_state["db_selector"] = cid


def set_active(connection_id: str | None) -> None:
    if st.session_state.get("active_connection_id") != connection_id:
        clear_workflow_state()  # never carry schema / SQL / results across databases
    st.session_state["active_connection_id"] = connection_id
    st.session_state.pop("conn_error", None)


def active_connection_id() -> str | None:
    return st.session_state.get("active_connection_id")


def get_active_context() -> ConnectionContext | None:
    cid = active_connection_id()
    if not cid:
        return None
    try:
        ctx = get_manager().get_context(cid)
        st.session_state.pop("conn_error", None)
        return ctx
    except QueryMateError as e:
        st.session_state["conn_error"] = str(e)
        return None


def reconnect_active() -> None:
    cid = active_connection_id()
    if cid:
        try:
            get_manager().get_context(cid, refresh=True)
            st.session_state.pop("conn_error", None)
        except QueryMateError as e:
            st.session_state["conn_error"] = str(e)


def reset_if_context_changed(prefix: str, ctx: ConnectionContext) -> None:
    """Drop a page's workflow state if it was created under a different connection."""
    key = f"{prefix}conn"
    if st.session_state.get(key) not in (None, ctx.connection_id):
        for k in list(st.session_state.keys()):
            if isinstance(k, str) and k.startswith(prefix) and k != key:
                del st.session_state[k]
    st.session_state[key] = ctx.connection_id


def page(name: str):
    return st.session_state.get("_pages", {}).get(name)


def go(name: str) -> None:
    pg = page(name)
    if pg is not None:
        st.switch_page(pg)
