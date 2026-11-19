"""Plotly charts chosen from the result's structure. Refuses unsuitable data instead of misleading."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

PALETTE = ["#2563EB", "#6366F1", "#16A34A", "#D97706", "#DC2626", "#0891B2", "#7C3AED", "#DB2777"]
MAX_CATEGORIES = 30
MAX_PIE = 12


def _is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def _is_time(name: str, s: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True
    if s.dtype == object or pd.api.types.is_string_dtype(s):
        sample = s.dropna().astype(str).head(20)
        if len(sample) and sample.str.match(r"^\d{4}(-\d{2}(-\d{2})?)?").all() and any(k in name.lower() for k in ("date", "month", "year", "day", "time", "week", "period")):
            return True
    return False


def analyze(df: pd.DataFrame) -> dict:
    cols = list(df.columns)
    num = [c for c in cols if _is_numeric(df[c])]
    time = [c for c in cols if _is_time(c, df[c])]
    cat = [c for c in cols if c not in num and c not in time]
    # an ID-like numeric column next to another measure is a label, not a measure
    measures = [c for c in num if not c.lower().endswith("_id") and c.lower() != "id"] or num
    return {"num": num, "measures": measures, "time": time, "cat": cat}


def chart_options(df: pd.DataFrame) -> tuple[list[str], str | None, str]:
    """-> (available chart types, default, reason if none)"""
    if len(df) < 2:
        return [], None, "A chart needs at least two rows."
    a = analyze(df)
    if not a["measures"]:
        return [], None, "This result has no numeric column to plot."
    if a["time"]:
        return ["Line", "Bar", "Scatter"], "Line", ""
    if a["cat"]:
        opts = ["Bar", "Scatter"]
        n = df[a["cat"][0]].nunique()
        if n <= MAX_PIE and (df[a["measures"][-1]].dropna() >= 0).all():
            opts += ["Pie", "Donut"]
        return opts, ("Bar" if n > 6 else "Bar"), ""
    if len(a["num"]) >= 2:
        return ["Scatter", "Line", "Bar"], "Scatter", ""
    return ["Bar"], "Bar", ""


def render_chart(df: pd.DataFrame, key: str) -> None:
    opts, default, reason = chart_options(df)
    if not opts:
        st.info(f"No chart suggested: {reason}", icon="📊")
        return
    a = analyze(df)
    c1, c2, c3 = st.columns(3)
    ctype = c1.selectbox("Chart type", opts, index=opts.index(default), key=f"{key}_ctype")
    xs = a["time"] + a["cat"] + [c for c in a["num"]]
    x = c2.selectbox("X axis / labels", xs, index=0, key=f"{key}_x")
    ys = [c for c in a["measures"] if c != x] or [c for c in a["num"] if c != x]
    if not ys:
        st.info("Pick a different X column: no numeric column left for the Y axis.", icon="📊")
        return
    y = c3.selectbox("Y axis / values", ys, index=len(ys) - 1, key=f"{key}_y")

    data = df[[x, y]].dropna().copy()
    if _is_time(x, data[x]):
        data[x] = pd.to_datetime(data[x], errors="coerce")
        data = data.dropna().sort_values(x)
    if ctype in ("Bar", "Pie", "Donut") and not _is_time(x, data[x]) and data[x].nunique() > MAX_CATEGORIES:
        st.caption(f"Showing the top {MAX_CATEGORIES} of {data[x].nunique()} categories.")
        data = data.nlargest(MAX_CATEGORIES, y)
    if ctype in ("Pie", "Donut"):
        if (data[y] < 0).any() or data[x].nunique() > MAX_PIE:
            st.warning("Pie charts need non-negative values and ≤ 12 slices; choose Bar instead.", icon="⚠️")
            return
        fig = px.pie(data, names=x, values=y, hole=0.5 if ctype == "Donut" else 0, color_discrete_sequence=PALETTE)
    elif ctype == "Line":
        fig = px.line(data, x=x, y=y, markers=True, color_discrete_sequence=PALETTE)
    elif ctype == "Scatter":
        fig = px.scatter(data, x=x, y=y, color_discrete_sequence=PALETTE)
    else:
        fig = px.bar(data, x=x, y=y, color_discrete_sequence=PALETTE)
        fig.update_yaxes(rangemode="tozero")  # bars always start at zero: no exaggerated differences
    fig.update_layout(template="plotly_white", font=dict(family="Inter, sans-serif", color="#0F172A"),
                      margin=dict(l=10, r=10, t=30, b=10), height=420, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      title=dict(text=f"{y} by {x}" if ctype not in ("Pie", "Donut") else f"{y} share by {x}", font=dict(size=14)))
    st.plotly_chart(fig, use_container_width=True, key=f"{key}_fig")
