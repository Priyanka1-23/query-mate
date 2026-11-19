"""Result display: table, CSV export, charts, insights, save-query."""
from __future__ import annotations

import streamlit as st

from components.chart_renderer import render_chart
from components.status_components import badge
from services.explanation_service import ai_summarize_result, summarize_result
from services.query_execution_service import QueryResult
from utils.exceptions import QueryMateError
from utils.state import get_ai, get_history


def render_result(res: QueryResult, key: str, question: str | None = None, show_save: bool = True) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Rows returned", f"{res.row_count:,}")
    c2.metric("Execution time", f"{res.execution_time * 1000:,.0f} ms" if res.execution_time < 1 else f"{res.execution_time:.2f} s")
    c3.metric("Columns", len(res.dataframe.columns))
    if res.truncated:
        st.warning("Result was truncated at the configured row limit. Increase it in Settings or add filters.", icon="⚠️")
    if res.is_empty:
        st.info("The query ran successfully but returned **no rows**. Try relaxing the filters.", icon="🔍")
        return

    t_res, t_chart, t_ins = st.tabs(["Results", "Visualize", "Insights"])
    with t_res:
        st.dataframe(res.dataframe, use_container_width=True, hide_index=True)
        st.download_button("⬇ Export CSV", res.dataframe.to_csv(index=False).encode("utf-8"),
                           file_name="querymate_result.csv", mime="text/csv", key=f"{key}_csv")
    with t_chart:
        render_chart(res.dataframe, key)
    with t_ins:
        st.markdown(summarize_result(res.dataframe))
        st.caption("Computed directly from the returned rows.")
        ai = get_ai()
        ai_key = f"result_{key}_ai"
        if ai is not None:
            if st.button("✨ Generate AI summary", key=f"{key}_aibtn",
                         help="Sends the SQL and up to 20 result rows to the AI provider."):
                try:
                    with st.spinner("Summarising…"):
                        st.session_state[ai_key] = ai_summarize_result(ai, question, res.sql, res.dataframe)
                except QueryMateError as e:
                    st.error(str(e))
            if st.session_state.get(ai_key):
                st.markdown(st.session_state[ai_key])
                st.caption("AI-written from the first 20 rows; verify against the table.")
        else:
            st.caption("Add a Groq API key in Settings to enable AI summaries.")

    if show_save:
        with st.expander("💾 Save this query"):
            title = st.text_input("Title", key=f"{key}_save_title", placeholder="e.g. Top customers by spend")
            if st.button("Save query", key=f"{key}_save_btn"):
                get_history().save_query(res.connection_id, title or "Untitled query", res.sql, question)
                st.success("Saved. Find it in Query History → Saved queries.")
