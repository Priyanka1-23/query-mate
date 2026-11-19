import streamlit as st

from components.status_components import badge, page_header
from services.ai_service import AIService, build_provider
from utils.config import Preferences
from utils.exceptions import QueryMateError
from utils.state import (
    api_key_source, active_connection_id, clear_workflow_state, get_active_context, get_ai, get_history, get_manager,
    get_prefs, request_activate,
)

RO_USER_SQL = """-- Run as a MySQL admin. Gives QueryMate SELECT-only access to one database.
CREATE USER 'querymate_ro'@'%' IDENTIFIED BY 'choose-a-strong-password';
GRANT SELECT ON your_database.* TO 'querymate_ro'@'%';
FLUSH PRIVILEGES;"""


def render() -> None:
    page_header("Settings", "Preferences, AI provider and maintenance")
    prefs = get_prefs()
    t_pref, t_ai, t_data, t_about = st.tabs(["Preferences", "AI provider", "Data & connections", "About"])

    with t_pref:
        with st.form("prefs_form"):
            c1, c2 = st.columns(2)
            limit = c1.number_input("Default result limit (rows)", 1, 100_000, prefs.result_limit, step=100)
            timeout = c2.number_input("Query timeout (seconds)", 1, 600, prefs.query_timeout, step=5)
            c3, c4 = st.columns(2)
            retries = c3.number_input("Max AI correction attempts", 0, 5, prefs.max_correction_attempts)
            tlimit = c4.number_input("Tables sent to AI per question", 5, 100, prefs.schema_prompt_table_limit)
            if st.form_submit_button("Save preferences", type="primary"):
                new = Preferences(int(limit), int(timeout), prefs.ai_model, int(retries), int(tlimit))
                new.save()
                st.session_state["prefs"] = new
                st.success("Preferences saved.")
        st.caption("Result limit and timeout apply to every query (Ask, Playground, Analysis). Changing the timeout applies to new executions.")

    with t_ai:
        src = api_key_source()
        st.markdown("**Provider:** Groq &nbsp; " + (badge(f"API key configured ({src})", "success", dot=True) if src else badge("No API key", "warning", dot=True)),
                    unsafe_allow_html=True)
        st.caption("Keys are never shown after saving. To make a key permanent, put `GROQ_API_KEY=…` in your `.env` file. "
                   "A key entered below lives only in this browser session.")
        model = st.text_input("Model", prefs.ai_model, help="Any Groq chat model, e.g. llama-3.3-70b-versatile")
        key = st.text_input("Groq API key", type="password", placeholder="gsk_…  (leave blank to keep the current key)")
        c1, c2, c3 = st.columns(3)
        if c1.button("Save for this session", type="primary"):
            if key.strip():
                st.session_state["session_api_key"] = key.strip()
            if model.strip() and model.strip() != prefs.ai_model:
                prefs.ai_model = model.strip()
                prefs.save()
            st.session_state.pop("_ai", None)
            st.success("Saved. The key is hidden from now on.")
            st.rerun()
        if c2.button("Test AI connection"):
            ai = get_ai()
            if ai is None:
                st.error("No API key configured.")
            else:
                try:
                    with st.spinner("Contacting Groq…"):
                        out = ai.complete_text("Reply with the single word OK.", "ping", max_tokens=5)
                    st.success(f"Provider responded: {out[:40]}")
                except QueryMateError as e:
                    st.error(str(e))
        if c3.button("Remove session key", disabled="session_api_key" not in st.session_state):
            st.session_state.pop("session_api_key", None)
            st.session_state.pop("_ai", None)
            st.rerun()
        st.info("Only your question, the relevant schema (table/column names and types) and — if you press an AI summary button — "
                "up to 20 result rows are sent to the AI provider. Database credentials never are.", icon="🔒")

    with t_data:
        mgr, hist = get_manager(), get_history()
        st.markdown("##### Read-only database account (recommended)")
        st.code(RO_USER_SQL, language="sql")
        st.markdown("##### Sample database")
        if st.button("Reset sample database (re-seed with fresh dates)"):
            mgr.reset_sample()
            clear_workflow_state()
            st.success("Sample database re-created.")
        ctx = get_active_context()
        if ctx is not None:
            st.markdown("##### Active database")
            if st.button(f"Clear history & saved queries for “{ctx.name}”"):
                hist.clear(ctx.connection_id)
                st.success("Cleared.")
        saved = [i for i in mgr.list_connections() if not i.is_sample]
        st.markdown("##### Saved connections")
        if not saved:
            st.caption("No saved MySQL connections.")
        for i in saved:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{i.name}** · {i.host} · `{i.database}`")
            if c2.button("Remove", key=f"rm_{i.id}"):
                was_active = active_connection_id() == i.id
                mgr.delete_connection(i.id)
                hist.clear(i.id)
                if was_active:
                    request_activate(None)
                st.rerun()

    with t_about:
        st.markdown("**QueryMate** — Your Database. Your Questions. Real Answers.")
        st.markdown("AI-powered database intelligence: connect, explore, ask, understand and analyse, with every query validated "
                    "by a SQL parser and executed read-only.")
        st.caption("Stack: Streamlit · SQLAlchemy · SQLGlot · Pandas · Plotly · Groq · Pytest. MCA final-year project.")
