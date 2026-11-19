"""AI quality evaluation (spec §21.5).

  python -m evaluation.run_eval                 # offline part only: unsafe-SQL rejection rate
  GROQ_API_KEY=... python -m evaluation.run_eval --live [--limit N]

Reports: execution accuracy, grounding accuracy, ambiguity handling, unsupported handling,
unsafe rejection rate, correction success rate, latency. Nothing is claimed that was not measured.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.connection_manager import ConnectionManager  # noqa: E402
from evaluation.questions import QUESTIONS, UNSAFE_SQL  # noqa: E402
from services.ai_service import AIService, build_provider  # noqa: E402
from services.query_execution_service import execute_query  # noqa: E402
from services.sql_generation_service import correct_sql, generate_sql  # noqa: E402
from services.sql_validation_service import validate_sql  # noqa: E402
from utils.config import Preferences, groq_api_key_from_env  # noqa: E402
from utils.exceptions import QueryMateError  # noqa: E402


def pct(a: int, b: int) -> str:
    return f"{a}/{b} = {100 * a / b:.1f}%" if b else "n/a"


def offline(ctx) -> None:
    rejected = sum(1 for s in UNSAFE_SQL if not validate_sql(s, "mysql", ctx.schema).is_valid)
    print(f"Unsafe query rejection (mysql dialect): {pct(rejected, len(UNSAFE_SQL))}")
    rejected = sum(1 for s in UNSAFE_SQL if not validate_sql(s, "sqlite", ctx.schema).is_valid)
    print(f"Unsafe query rejection (sqlite dialect): {pct(rejected, len(UNSAFE_SQL))}")


def live(ctx, limit: int | None) -> None:
    key = groq_api_key_from_env()
    if not key:
        sys.exit("Set GROQ_API_KEY to run the live evaluation.")
    prefs = Preferences.load()
    ai = AIService(build_provider(key, prefs.ai_model))
    qs = QUESTIONS[:limit] if limit else QUESTIONS
    m = dict(ans=0, exec_ok=0, grounded=0, amb=0, amb_ok=0, uns=0, uns_ok=0, fixed_try=0, fixed_ok=0, errors=0)
    lat = []
    for q, cat in qs:
        try:
            g = generate_sql(ai, ctx, q)
        except QueryMateError as e:
            m["errors"] += 1
            print(f"[error] {q!r}: {e}")
            continue
        lat.append(g.latency)
        if cat == "ambiguous":
            m["amb"] += 1; m["amb_ok"] += g.status == "clarification_needed"
        elif cat == "unsupported":
            m["uns"] += 1; m["uns_ok"] += g.status == "unsupported"
        else:
            m["ans"] += 1
            if g.status != "sql":
                continue
            v = validate_sql(g.sql, ctx.dialect, ctx.schema, prefs.result_limit)
            m["grounded"] += v.is_valid
            sql = g.sql
            try:
                if not v.is_valid:
                    raise QueryMateError("; ".join(v.errors))
                execute_query(ctx, v, prefs.result_limit, prefs.query_timeout)
                m["exec_ok"] += 1
            except QueryMateError as e:
                m["fixed_try"] += 1
                for _ in range(prefs.max_correction_attempts):
                    fx = correct_sql(ai, ctx, q, sql, str(e))
                    if fx.status != "sql":
                        break
                    fv = validate_sql(fx.sql, ctx.dialect, ctx.schema, prefs.result_limit)
                    if fv.is_valid:
                        try:
                            execute_query(ctx, fv, prefs.result_limit, prefs.query_timeout)
                            m["fixed_ok"] += 1
                            break
                        except QueryMateError as e2:
                            e, sql = e2, fx.sql
        time.sleep(0.3)  # gentle on rate limits
    print(f"Questions evaluated: {len(qs)}  (provider errors: {m['errors']})")
    print(f"SQL execution accuracy (executes without error): {pct(m['exec_ok'], m['ans'])}")
    print(f"Table/column grounding accuracy (passes schema validation): {pct(m['grounded'], m['ans'])}")
    print(f"Ambiguous questions -> clarification: {pct(m['amb_ok'], m['amb'])}")
    print(f"Unsupported questions -> declined: {pct(m['uns_ok'], m['uns'])}")
    print(f"Query correction success: {pct(m['fixed_ok'], m['fixed_try'])}")
    if lat:
        s = sorted(lat)
        print(f"Latency: mean {statistics.mean(lat):.2f}s, median {statistics.median(lat):.2f}s, p95 {s[int(0.95 * (len(s) - 1))]:.2f}s")
    print("NOTE: 'executes' is not the same as 'semantically correct'. Spot-check results by hand before claiming accuracy.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    ctx = ConnectionManager().get_context("sample")
    print(f"Question set size: {len(QUESTIONS)}")
    offline(ctx)
    if a.live:
        live(ctx, a.limit)
