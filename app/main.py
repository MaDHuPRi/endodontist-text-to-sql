"""
Endodontist Practice — Natural Language Query Tool
----------------------------------------------------
Local Flask app that lets front-desk staff and the doctors ask questions
about the practice database in plain English.

Design: instead of a free-roaming LangChain agent (which, on small local
models, tends to narrate a plausible-looking but fake step-by-step tool
trace rather than actually calling tools), this app does two deterministic
steps itself:

  1. Ask the LLM to output ONLY a SQL query (schema is given in the prompt).
  2. Execute that exact SQL against the real SQLite database in Python and
     return the real rows.

This guarantees the SQL shown and the results shown are both real — the
model never has a chance to invent either one.

Run locally:
    ollama pull llama3.1
    ollama serve
    python app/main.py

Or via Docker (see docker-compose.yml in project root).
"""
import os
import re
import sqlite3
from datetime import date, timedelta
from flask import Flask, render_template, request, jsonify

from langchain_ollama import ChatOllama
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "clinic.db")

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")

app = Flask(__name__, template_folder="../templates", static_folder="../static")

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOllama(model=OLLAMA_MODEL, base_url=OLLAMA_BASE_URL, temperature=0)
    return _llm


def get_schema():
    """Reads the REAL schema straight from the database file — never hand-written,
    so the prompt can't drift out of sync with the actual tables/columns.
    Also surfaces real foreign-key relationships so the model knows exactly
    which tables to JOIN (and doesn't invent a column on the wrong table)."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    schema_lines = []
    fk_lines = []
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [f"{row[1]} ({row[2]})" for row in cur.fetchall()]
        schema_lines.append(f"{t}: " + ", ".join(cols))

        cur.execute(f"PRAGMA foreign_key_list({t})")
        for fk in cur.fetchall():
            # fk columns: id, seq, table, from, to, ...
            ref_table, from_col, to_col = fk[2], fk[3], fk[4]
            fk_lines.append(f"{t}.{from_col} -> {ref_table}.{to_col}")
    conn.close()
    schema_text = "\n".join(schema_lines)
    fk_text = "\n".join(fk_lines) if fk_lines else "(none)"
    return schema_text, fk_text


SQL_SYSTEM_PROMPT = """You write SQLite queries. You will be given a database \
schema and a question in plain English.

Respond with ONLY the SQL query. No explanation, no markdown fences, no \
commentary, no "Tool call:" text, no narration of your reasoning. Just the \
raw SQL statement, ending in a semicolon.

Only use tables and columns that are explicitly listed in the schema below. \
Never invent table or column names. Each column belongs only to the table \
it is listed under — do not reference a column on a table it does not \
belong to (e.g. a date column that lives on "appointments" cannot be used \
directly on "treatments"; you must JOIN to reach it).

Only JOIN tables that are actually needed to answer the question. Joining \
an unrelated or unnecessary table can silently drop or duplicate rows and \
produce a wrong answer (e.g. a table that only has rows for completed work \
will exclude no-shows/cancellations if you inner-join it in). If the \
question can be answered from a single table, do not join at all.

Known foreign-key relationships (use these to decide which JOINs are valid \
and how to connect tables):
{foreign_keys}

Rules for dates: all date columns are stored as TEXT in 'YYYY-MM-DD' format \
(e.g. '2025-03-14'). Never use 'M/D/YYYY' or any other format. Never compute \
relative dates yourself (no DATE('now'), no strftime math for "this month" \
etc.) — instead use the exact pre-computed ranges below, matched to whatever \
time period the question refers to. Use BETWEEN start AND end (inclusive) \
against the relevant date column.

{date_ranges}

If the question names a specific year or date not listed above, use \
strftime('%Y', column) = 'YYYY' or the literal date directly.

Rules for text values: match the exact casing and exact wording shown in the \
sample values below — do not guess alternate spellings, casings, or shortened \
versions of these values. EXCEPTION: if the question refers to a broad \
category rather than one specific value (e.g. "root canals" when the sample \
values include several variants like 'Root Canal Therapy - Molar', 'Root \
Canal Therapy - Premolar', etc.), use LIKE with a wildcard to match the \
whole family (e.g. LIKE 'Root Canal%'), not an exact match to a single \
variant — matching only one variant will undercount.
{sample_values}

Word-sense caution: a status column (e.g. appointments.status) has a fixed \
set of literal values shown above. A question can use similar-sounding \
words in a different sense — e.g. "appointments scheduled this week" \
usually means "appointments that occur/take place this week" (a date \
filter), NOT "appointments whose status column equals 'Scheduled'" (which \
would wrongly exclude completed/no-show appointments happening that week). \
Only filter on a status value when the question is clearly asking about \
that status specifically (e.g. "how many appointments are still marked \
Scheduled").

Column selection: choose columns that actually answer the question, not \
just columns used in the WHERE/JOIN condition. If the question filters by a \
specific dentist, patient, or category, do not select that same value back \
out as if it were new information — prefer distinguishing details like \
dates, names, or amounts that tell the person something they don't already \
know from the question itself.

Schema:
{schema}
"""


def get_date_ranges():
    """Pre-computes every relative date range a user might ask about, so the
    model only has to pattern-match a phrase to a range instead of doing its
    own (frequently wrong) date arithmetic."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    start_of_week = today - timedelta(days=today.weekday())  # Monday
    end_of_week = start_of_week + timedelta(days=6)
    start_of_last_week = start_of_week - timedelta(days=7)
    end_of_last_week = start_of_week - timedelta(days=1)
    start_of_next_week = end_of_week + timedelta(days=1)
    end_of_next_week = start_of_next_week + timedelta(days=6)

    start_of_month = today.replace(day=1)
    end_of_last_month = start_of_month - timedelta(days=1)
    start_of_last_month = end_of_last_month.replace(day=1)
    # end of this month
    next_month = (start_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_of_month = next_month - timedelta(days=1)

    start_of_year = today.replace(month=1, day=1)
    end_of_year = today.replace(month=12, day=31)
    start_of_last_year = start_of_year.replace(year=start_of_year.year - 1)
    end_of_last_year = end_of_year.replace(year=end_of_year.year - 1)

    def r(d1, d2):
        return f"'{d1.isoformat()}' AND '{d2.isoformat()}'"

    return "\n".join([
        f"today: {today.isoformat()}",
        f"yesterday: {yesterday.isoformat()}",
        f"tomorrow: {tomorrow.isoformat()}",
        f"this week (Mon–Sun): {r(start_of_week, end_of_week)}",
        f"last week: {r(start_of_last_week, end_of_last_week)}",
        f"next week: {r(start_of_next_week, end_of_next_week)}",
        f"this month: {r(start_of_month, end_of_month)}",
        f"last month: {r(start_of_last_month, end_of_last_month)}",
        f"this year: {r(start_of_year, end_of_year)}",
        f"last year: {r(start_of_last_year, end_of_last_year)}",
    ])


def get_sample_values():
    """Pulls distinct values from any TEXT column with low cardinality (a
    handful of repeating values, like a status/category/procedure name) so
    the model matches real wording instead of guessing plausible-looking
    strings. Skips high-cardinality free-text columns like names/notes."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    lines = []
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        for row in cur.fetchall():
            col_name, col_type = row[1], row[2]
            if col_type.upper() != "TEXT":
                continue
            cur.execute(f"SELECT COUNT(DISTINCT {col_name}) FROM {t}")
            distinct_count = cur.fetchone()[0]
            if 0 < distinct_count <= 15:
                cur.execute(f"SELECT DISTINCT {col_name} FROM {t} LIMIT 15")
                vals = [str(v[0]) for v in cur.fetchall() if v[0] is not None]
                if vals:
                    lines.append(f"{t}.{col_name}: {vals}")
    conn.close()
    return "\n".join(lines) if lines else "(none)"


def extract_sql(raw_text: str) -> str:
    """Strip markdown fences / stray prose in case the model adds them anyway."""
    text = raw_text.strip()
    text = re.sub(r"^```sql\s*|^```\s*|```$", "", text, flags=re.MULTILINE).strip()
    # If the model still rambled, grab the first SELECT/INSERT/UPDATE/DELETE statement.
    match = re.search(r"(SELECT|WITH|INSERT|UPDATE|DELETE)\b.*?;", text,
                       re.IGNORECASE | re.DOTALL)
    return match.group(0).strip() if match else text


def run_sql(sql: str):
    """Executes against the real DB. Read-only enforced for this demo tool."""
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed.")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(sql)
    columns = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    conn.close()
    return columns, rows


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ask", methods=["POST"])
def ask():
    question = (request.json or {}).get("question", "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    try:
        llm = get_llm()
        schema, foreign_keys = get_schema()
        sample_values = get_sample_values()
        date_ranges = get_date_ranges()
        system_prompt = SQL_SYSTEM_PROMPT.format(
            schema=schema,
            foreign_keys=foreign_keys,
            sample_values=sample_values,
            date_ranges=date_ranges,
        )
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=question),
        ]

        response = llm.invoke(messages)
        sql = extract_sql(response.content)

        try:
            columns, rows = run_sql(sql)
        except sqlite3.Error as db_err:
            # The model referenced a column/table that doesn't exist, or wrote
            # invalid SQL. Give it one chance to self-correct with the real
            # SQLite error message in hand, instead of failing outright.
            retry_messages = messages + [
                AIMessage(content=sql),
                HumanMessage(content=(
                    f"That query failed with this SQLite error:\n{db_err}\n\n"
                    "Fix the query. Remember: only use columns on the table "
                    "they actually belong to (see the schema and foreign-key "
                    "list above), and JOIN when a column lives on a different "
                    "table. Respond with ONLY the corrected SQL."
                )),
            ]
            retry_response = llm.invoke(retry_messages)
            sql = extract_sql(retry_response.content)
            columns, rows = run_sql(sql)  # let this raise if it fails again

        return jsonify({
            "question": question,
            "sql": sql,
            "columns": columns,
            "rows": rows,
        })
    except Exception as exc:  # noqa: BLE001 — surface a readable error to the UI
        hint = (
            " (Is Ollama running? Try `ollama serve` and confirm the model is "
            f"pulled: `ollama pull {OLLAMA_MODEL}`)"
        )
        return jsonify({"error": str(exc) + hint}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=True)
