"""Headless end-to-end UI tests with Streamlit's AppTest (no browser, no network)."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
APP = str(ROOT / "app.py")


def _new(active=None):
    # NOTE: AppTest renders nothing on a *second* run() of an st.navigation app (harness quirk),
    # so state is preset before the single first run.
    at = AppTest.from_file(APP, default_timeout=30)
    if active:
        at.session_state["_pending_activate"] = active
    at.run()
    return at


def test_boots_without_exception_and_shows_onboarding():
    at = _new()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Real Answers" in text
    assert any("Explore Sample Database" in b.label for b in at.button)


def test_activate_sample_shows_real_dashboard():
    at = _new("sample")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Tables"] == "6" and metrics["Active database"] == "Sample E-commerce"
    assert at.sidebar.selectbox[0].value == "sample"


def _run_page(name):
    import streamlit as st
    from pages import database_explorer, ask_querymate, query_analysis, query_history, settings, sql_playground
    from components.status_components import inject_css
    inject_css()
    st.session_state["_pages"] = {}
    {"explorer": database_explorer, "ask": ask_querymate, "playground": sql_playground,
     "history": query_history, "analysis": query_analysis, "settings": settings}[name].render()


@pytest.mark.parametrize("page", ["explorer", "ask", "playground", "history", "analysis", "settings"])
def test_every_page_renders_with_sample(page):
    at = AppTest.from_function(_run_page, args=(page,), default_timeout=30)
    at.session_state["active_connection_id"] = "sample"
    at.run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", ["explorer", "ask", "playground", "history", "analysis"])
def test_pages_without_connection_show_blocker_not_fake_data(page):
    at = AppTest.from_function(_run_page, args=(page,), default_timeout=30)
    at.run()
    assert not at.exception
    assert any("Explore Sample Database" in b.label for b in at.button)
    assert not at.metric


def test_playground_blocks_write_and_runs_select():
    at = AppTest.from_function(_run_page, args=("playground",), default_timeout=30)
    at.session_state["active_connection_id"] = "sample"
    at.run()
    at.text_area(key="play_sql_editor").set_value("DELETE FROM customers").run()
    assert any("not allowed" in e.value.lower() or "only read-only" in e.value.lower() for e in at.error)
    run_btn = next(b for b in at.button if "Run Query" in b.label)
    assert run_btn.disabled
    at.text_area(key="play_sql_editor").set_value("SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC").run()
    next(b for b in at.button if "Run Query" in b.label).click().run()
    assert not at.exception
    assert any(m.label == "Rows returned" for m in at.metric)
    assert at.session_state["play_run"].result.row_count > 0


def test_ask_flow_with_mock_ai_requires_approval():
    """Generate (mock AI) -> validation shown -> nothing executed until Run is pressed."""
    def page():
        import json as _json
        import streamlit as st
        from pages import ask_querymate
        from services.ai_service import AIService, MockProvider
        from utils import state
        st.session_state["_pages"] = {}
        st.session_state["_ai"] = (("k", state.get_prefs().ai_model),
            AIService(MockProvider(lambda s, u: _json.dumps({"status": "sql", "explanation": "Customers per city",
                       "sql": "SELECT city, COUNT(*) AS n FROM customers GROUP BY city ORDER BY n DESC"}))))
        st.session_state["session_api_key"] = "k"
        ask_querymate.render()

    at = AppTest.from_function(page, default_timeout=30)
    at.session_state["active_connection_id"] = "sample"
    at.run()
    at.text_area(key="ask_input").set_value("customers per city").run()
    next(b for b in at.button if b.label == "Ask QueryMate").click().run()
    assert not at.exception
    assert "ask_run" not in at.session_state      # NOT executed automatically
    assert at.text_area(key="ask_sql_editor").value.startswith("SELECT city")
    next(b for b in at.button if "Run Query" in b.label).click().run()
    assert at.session_state["ask_run"].result.row_count > 0
    assert not at.exception
