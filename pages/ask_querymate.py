import streamlit as st

from components.result_table import render_result
from components.sql_editor import format_callback, sql_editor, sql_preview
from components.status_components import (
    error_box, page_header, require_connection, validation_panel, warning_box,
)
from services.history_service import HistoryService
from services.query_runner import run_query, validate_for
from services.sql_generation_service import correct_sql, generate_sql, suggest_questions
from utils.exceptions import AIConfigurationError, QueryMateError
from utils.state import (
    get_active_context, get_ai, get_history, get_prefs, go, reset_if_context_changed,
)


def _use_question(q: str) -> None:
    st.session_state["ask_input"] = q
    st.session_state["ask_autorun"] = True


def _generate(ctx, ai, question: str) -> None:
    for k in ("ask_gen", "ask_run", "ask_fix_error", "ask_fix_count"):
        st.session_state.pop(k, None)
    try:
        with st.spinner("QueryMate is reading your schema and writing SQL…"):
            gen = generate_sql(ai, ctx, question, get_prefs().schema_prompt_table_limit)
    except QueryMateError as e:
        st.session_state["ask_error"] = str(e)
        return
    st.session_state.pop("ask_error", None)
    st.session_state["ask_gen"] = gen
    st.session_state["ask_question"] = question
    if gen.status == "sql":
        st.session_state["ask_sql_editor"] = gen.sql


def _fix_callback(ctx_id: str) -> None:
    """on_click callback: may modify widget state safely."""
    ctx = get_active_context()
    ai = get_ai()
    run = st.session_state.get("ask_run")
    gen = st.session_state.get("ask_gen")
    if not (ctx and ai and run and gen) or ctx.connection_id != ctx_id:
        return
    prefs = get_prefs()
    n = st.session_state.get("ask_fix_count", 0)
    if n >= prefs.max_correction_attempts:
        return
    st.session_state["ask_fix_count"] = n + 1
    try:
        fixed = correct_sql(ai, ctx, st.session_state.get("ask_question", ""), st.session_state.get("ask_sql_editor", ""),
                            run.error or "unknown error", prefs.schema_prompt_table_limit)
    except QueryMateError as e:
        st.session_state["ask_fix_error"] = str(e)
        return
    if fixed.status == "sql":
        st.session_state["ask_sql_editor"] = fixed.sql
        st.session_state["ask_gen"] = fixed
        st.session_state.pop("ask_run", None)  # must be re-validated and re-approved
        st.session_state["ask_fix_note"] = "A corrected query was proposed. Review it, then press Run Query."
    else:
        st.session_state["ask_fix_error"] = fixed.reason or fixed.clarifying_question or "The AI could not correct this query."


def render() -> None:
    ctx = get_active_context()
    if not require_connection(ctx, "Ask QueryMate", "Ask questions about your data in plain English"):
        return
    reset_if_context_changed("ask_", ctx)
    page_header("Ask QueryMate", "Plain English → validated, read-only SQL → real results", ctx)
    prefs, ai, hist = get_prefs(), get_ai(), get_history()

    if ai is None:
        st.warning("No AI provider is configured, so SQL generation is unavailable. Add your Groq API key under **Settings** "
                   "(or `GROQ_API_KEY` in `.env`). You can still use the SQL Playground.", icon="🔑")
        if st.button("Open Settings"):
            go("settings")

    st.text_area("Your question", key="ask_input", height=90, placeholder="e.g. Show the top five customers by total spending")
    ask_clicked = st.button("Ask QueryMate", type="primary", disabled=ai is None)
    autorun = st.session_state.pop("ask_autorun", False)
    if (ask_clicked or autorun) and ai is not None:
        _generate(ctx, ai, st.session_state.get("ask_input", ""))

    with st.expander("💡 Suggested questions", expanded="ask_gen" not in st.session_state):
        sugg = suggest_questions(ctx.schema, 8)
        cols = st.columns(2)
        for i, q in enumerate(sugg):
            cols[i % 2].button(q, key=f"sugg_{i}", on_click=_use_question, args=(q,), use_container_width=True, disabled=ai is None)
        recent = hist.recent_questions(ctx.connection_id, 5)
        if recent:
            st.markdown("**Recent questions**")
            for i, q in enumerate(recent):
                st.button(f"↺ {q}", key=f"recent_{i}", on_click=_use_question, args=(q,), use_container_width=True, disabled=ai is None)

    if st.session_state.get("ask_error"):
        error_box(st.session_state["ask_error"])
        return

    gen = st.session_state.get("ask_gen")
    if gen is None:
        return
    if gen.connection_id != ctx.connection_id:  # defensive: never show another database's proposal
        for k in [k for k in st.session_state if str(k).startswith("ask_") and k != "ask_conn"]:
            del st.session_state[k]
        return

    if gen.status == "clarification_needed":
        with st.container(border=True):
            st.markdown("#### 🤔 I need a bit more detail")
            st.markdown(gen.clarifying_question)
            for i, opt in enumerate(gen.options):
                st.button(opt, key=f"clar_{i}", use_container_width=True, on_click=_use_question,
                          args=(f"{st.session_state.get('ask_question', '')} — {opt}",))
        return
    if gen.status == "unsupported":
        with st.container(border=True):
            st.markdown("#### 🚫 This database can't answer that")
            st.markdown(gen.reason)
            if gen.suggestions:
                st.markdown("**Try one of these instead:**")
                for i, s in enumerate(gen.suggestions):
                    st.button(s, key=f"unsup_{i}", on_click=_use_question, args=(s,), use_container_width=True)
        return

    # ------------------------------------------------ SQL proposal -> validate -> approve -> run
    with st.container(border=True):
        st.markdown("#### Generated SQL")
        if gen.explanation:
            st.caption(gen.explanation)
        if st.session_state.get("ask_fix_note"):
            st.info(st.session_state.pop("ask_fix_note"), icon="🛠️")
        sql = sql_editor("ask_sql_editor", 200)
        st.caption("You can edit the SQL. Every change is re-validated before it can run.")
        v = validate_for(ctx, sql, prefs)
        validation_panel(v)
        if v.is_valid and v.normalized_sql.strip() != sql.strip():
            with st.expander("SQL that will actually be executed (normalised, limit applied)"):
                st.code(v.normalized_sql, language="sql")
        sql_preview(sql)

        b1, b2, b3 = st.columns([2, 1, 1])
        run_clicked = b1.button("▶ Run Query", type="primary", disabled=not v.is_valid, use_container_width=True,
                                help="Nothing runs until you press this.")
        b2.button("✨ Format", use_container_width=True, on_click=format_callback, args=("ask_sql_editor", ctx.dialect))
        if b3.button("Open in Playground", use_container_width=True):
            st.session_state["play_sql_seed"] = sql
            go("playground")

    if run_clicked:
        with st.spinner("Running query…"):
            st.session_state["ask_run"] = run_query(ctx, sql, prefs, hist, st.session_state.get("ask_question"),
                                                    "ask", expected_connection_id=gen.connection_id)
        st.session_state["last_sql"] = sql

    run = st.session_state.get("ask_run")
    if run is None:
        return
    if v.normalized_sql != run.validation.normalized_sql:
        st.info("The SQL changed since the last run. Press **Run Query** to execute the new version.", icon="✏️")
        return
    if run.error:
        error_box(run.error)
        n = st.session_state.get("ask_fix_count", 0)
        if run.result is None and run.validation.is_valid and ai is not None and n < prefs.max_correction_attempts:
            st.button(f"🛠️ Suggest a fix ({prefs.max_correction_attempts - n} left)", on_click=_fix_callback, args=(ctx.connection_id,))
        if st.session_state.get("ask_fix_error"):
            warning_box(st.session_state["ask_fix_error"])
        return
    st.success("Query executed successfully.", icon="✅")
    render_result(run.result, "ask", st.session_state.get("ask_question"))
