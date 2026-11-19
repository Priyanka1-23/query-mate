# QueryMate — Your Database. Your Questions. Real Answers.

AI-powered database intelligence workspace: **Connect → Explore → Ask → Understand → Analyze**.
Natural language → schema-grounded SQL (Groq) → independent validation (SQLGlot) → *user approval* → read-only execution → results, explanations, charts, history and EXPLAIN-based analysis.

## Quick start
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # add GROQ_API_KEY (optional until you use "Ask")
streamlit run app.py
```
Click **Explore Sample Database** (no credentials needed) to try everything. SQL Playground, Explorer, History and Analysis work without an AI key; **Ask QueryMate**, AI explanations and AI summaries need `GROQ_API_KEY`.

## Connecting your own MySQL
Create a SELECT-only account (also shown in Settings → Data & connections):
```sql
CREATE USER 'querymate_ro'@'%' IDENTIFIED BY 'strong-password';
GRANT SELECT ON your_database.* TO 'querymate_ro'@'%';
```
Sidebar → **＋ Add** → fill in the form → *Test Connection* → *Save*. QueryMate warns if the account has write privileges.
To load the sample dataset into your own MySQL server: `python -m database.sample_database --mysql-url "mysql+pymysql://admin:pw@localhost/shop"`.

## Safety model (defence in depth)
| Layer | What it does |
|---|---|
| 1. Prompt | Tells the model: one read-only statement, only the supplied schema. **Not trusted.** |
| 2. Parser validation | SQLGlot AST: exactly one statement; root must be SELECT/UNION/CTE; any INSERT/UPDATE/DELETE/DDL/SET/SHOW/INTO/lock node *anywhere* is rejected; dangerous functions (SLEEP, LOAD_FILE, BENCHMARK…) rejected; unknown tables/columns/other databases rejected; LIMIT injected/capped; SQL regenerated from the AST (comments dropped). |
| 3. Human approval | Nothing runs until **Run Query** is pressed; edited SQL is re-validated; corrected SQL is re-validated and re-approved. |
| 4. Database | Read-only session (`SET SESSION TRANSACTION READ ONLY` / SQLite `query_only` + read-only file mode), execution timeout, row cap, connect/read timeouts. Use a SELECT-only DB user. |
| 5. Secrets | Passwords Fernet-encrypted in the metadata DB; never in prompts, logs, session state or UI; errors are scrubbed. |

## Architecture
```
app.py                 navigation + theme          components/  sidebar, selector, editor, tables, charts
pages/                 7 pages (UI only)           services/    all logic (schema, AI, validation, execution, history, analysis)
database/              connection manager,         prompts/     SQL + explanation prompts
                       metadata ORM, sample DB     utils/       config, security, exceptions, session state
```
`ConnectionContext` (engine + schema snapshot) is passed explicitly everywhere; there is no global "current DB", and switching databases clears all workflow state. History re-runs verify the original connection id.
Metadata (connections, history, saved queries) lives in `.querymate/metadata.db`, separate from analysed databases.

## Testing
```bash
python -m pytest tests -q                      # 138 tests (+1 live-MySQL test, skipped unless QUERYMATE_TEST_MYSQL_URL is set)
python -m evaluation.run_eval                  # offline: unsafe-SQL rejection rate
GROQ_API_KEY=... python -m evaluation.run_eval --live   # 100-question AI evaluation
```

## Verification status (be honest in your viva)
| Area | Status |
|---|---|
| Validation, execution, read-only enforcement, timeout, history, analysis, UI flows (AppTest + real browser screenshots) | Tested on the SQLite sample DB |
| MySQL connection / grants check / `MAX_EXECUTION_TIME` / `EXPLAIN` parsing | Code written; EXPLAIN parsing unit-tested with a fabricated plan; **needs a run against your real MySQL** |
| Groq generation quality | Prompts + parsing tested with a mock provider; **live accuracy is unmeasured** until you run `--live` |
| Code editor | Monospace text area + highlighted preview (no third-party editor dependency) |
