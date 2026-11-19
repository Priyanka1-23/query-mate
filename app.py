"""QueryMate entry point: theme, navigation, sidebar."""
import streamlit as st

st.set_page_config(page_title="QueryMate", page_icon="🗄️", layout="wide", initial_sidebar_state="auto")

from components.sidebar import render_sidebar  # noqa: E402
from components.status_components import ASSETS, inject_css  # noqa: E402
from pages import (  # noqa: E402
    database_explorer, ask_querymate, overview, query_analysis, query_history, settings, sql_playground,
)

inject_css()
st.logo(str(ASSETS / "logo.svg"), icon_image=str(ASSETS / "logo_icon.svg"), size="large")

pages = {
    "overview": st.Page(overview.render, title="Overview", icon=":material/dashboard:", url_path="overview", default=True),
    "explorer": st.Page(database_explorer.render, title="Database Explorer", icon=":material/account_tree:", url_path="explorer"),
    "ask": st.Page(ask_querymate.render, title="Ask QueryMate", icon=":material/chat:", url_path="ask"),
    "playground": st.Page(sql_playground.render, title="SQL Playground", icon=":material/code:", url_path="playground"),
    "history": st.Page(query_history.render, title="Query History", icon=":material/history:", url_path="history"),
    "analysis": st.Page(query_analysis.render, title="Query Analysis", icon=":material/speed:", url_path="analysis"),
    "settings": st.Page(settings.render, title="Settings", icon=":material/settings:", url_path="settings"),
}
st.session_state["_pages"] = pages

nav = st.navigation(list(pages.values()), position="sidebar")
render_sidebar()
nav.run()
