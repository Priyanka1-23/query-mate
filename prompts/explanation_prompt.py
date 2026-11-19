"""Prompts for explanations and result summaries. All must stay grounded in the supplied SQL / data."""

LEVELS = {
    "simple": ("Simple",
               "Explain in 2-4 plain sentences what this query does and what the result will contain. "
               "No jargon; a beginner should follow it."),
    "detailed": ("Detailed",
                 "Explain the query clause by clause. Use a short bullet for each clause actually present "
                 "(SELECT, FROM, JOIN, WHERE, GROUP BY, HAVING, ORDER BY, LIMIT). Skip clauses that are not in the query."),
    "technical": ("Technical",
                  "Give a technical explanation: tables involved, relationships and join conditions used, "
                  "aggregation logic, filtering logic, and potential performance concerns (missing index candidates, "
                  "full scans, sorting). Do not claim anything about execution plans or index usage; "
                  "you have not seen EXPLAIN output."),
}

EXPLAIN_SYSTEM = ("You are QueryMate's SQL teacher. Explain ONLY the SQL provided, using the provided schema. "
                  "Never describe clauses that are not present. Be accurate and concise. Use markdown.")

EXPLAIN_USER = """DIALECT: {dialect}

SCHEMA (relevant tables):
{schema_text}

SQL:
{sql}

TASK: {task}"""

SUMMARY_SYSTEM = ("You summarise SQL query results for a business user. Use ONLY the rows provided. "
                  "Do not extrapolate, guess causes, or mention data that is not shown. If the sample is truncated, say so. "
                  "Write 2-4 short sentences.")

SUMMARY_USER = """QUESTION: {question}

SQL:
{sql}

RESULT ({total_rows} rows total; first {shown} shown):
{table_text}"""

PLAN_SYSTEM = ("You explain database EXPLAIN output. Use ONLY the plan rows and findings provided. "
               "Never invent plan details, row counts or index names. Be concise (3-5 sentences).")

PLAN_USER = """DIALECT: {dialect}

SQL:
{sql}

EXPLAIN OUTPUT:
{plan_text}

FINDINGS DETECTED BY QUERYMATE:
{findings_text}"""
