"""
Evaluation harness for the Clinic Records text-to-SQL system.

Measures SQL correctness: for each test question, the generated SQL's
EXECUTION RESULT is compared against a ground-truth SQL's execution result
(not string-matched against a "correct" SQL string — two different queries
can be equally correct if they return the same rows).

Ground-truth SQL for date-relative questions ("this month", "last week") is
built dynamically using the same date-range logic as app/main.py, so the
eval stays correct regardless of what day it's run.

Usage:
    ollama serve                      # in one terminal
    python eval.py                    # in another, from the project root

Requires the same environment as app/main.py (OLLAMA_MODEL, OLLAMA_BASE_URL
env vars are respected the same way).

Outputs:
    - Per-question PASS/FAIL with generated vs. expected row counts
    - Aggregate accuracy, broken down by category
    - eval_results.json with full detail for later analysis
"""
import json
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

import main as app_main  # noqa: E402


# ---------------------------------------------------------------------------
# Ground-truth SQL is built with the same relative-date logic as the app,
# so "this month" etc. always resolves to the correct real range at eval time.
# ---------------------------------------------------------------------------

def date_ranges():
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    end_of_week = start_of_week + timedelta(days=6)
    start_of_last_week = start_of_week - timedelta(days=7)
    end_of_last_week = start_of_week - timedelta(days=1)
    start_of_month = today.replace(day=1)
    end_of_last_month = start_of_month - timedelta(days=1)
    start_of_last_month = end_of_last_month.replace(day=1)
    next_month = (start_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)
    end_of_month = next_month - timedelta(days=1)
    start_of_year = today.replace(month=1, day=1)
    end_of_year = today.replace(month=12, day=31)
    return {
        "today": today.isoformat(),
        "this_week_start": start_of_week.isoformat(),
        "this_week_end": end_of_week.isoformat(),
        "last_week_start": start_of_last_week.isoformat(),
        "last_week_end": end_of_last_week.isoformat(),
        "this_month_start": start_of_month.isoformat(),
        "this_month_end": end_of_month.isoformat(),
        "last_month_start": start_of_last_month.isoformat(),
        "last_month_end": end_of_last_month.isoformat(),
        "this_year_start": start_of_year.isoformat(),
        "this_year_end": end_of_year.isoformat(),
    }


DR = date_ranges()

# ---------------------------------------------------------------------------
# Test suite: (category, question, ground_truth_sql)
# ---------------------------------------------------------------------------

TEST_CASES = [
    ("simple_filter", "Which patients have an unpaid balance over $500?",
     """SELECT DISTINCT p.full_name FROM patients p JOIN invoices i
        ON p.patient_id = i.patient_id
        WHERE i.amount_due > 500 AND i.amount_paid < i.amount_due;"""),

    ("simple_filter", "List all patients insured by Delta Dental.",
     """SELECT full_name FROM patients WHERE insurance_provider = 'Delta Dental';"""),

    ("simple_filter", "Which appointments have a status of No-Show?",
     """SELECT appointment_id, patient_id, appointment_date FROM appointments
        WHERE status = 'No-Show';"""),

    ("join", "List all root canal treatments performed by Dr. Sarah Chen.",
     """SELECT t.procedure_name, a.appointment_date FROM treatments t
        JOIN appointments a ON t.appointment_id = a.appointment_id
        JOIN dentists d ON a.dentist_id = d.dentist_id
        WHERE d.full_name = 'Dr. Sarah Chen' AND t.procedure_name LIKE 'Root Canal%';"""),

    ("join", "What is the total invoice amount due for each insurance provider?",
     """SELECT p.insurance_provider, SUM(i.amount_due) AS total_due
        FROM patients p JOIN invoices i ON p.patient_id = i.patient_id
        GROUP BY p.insurance_provider;"""),

    ("join", "Which dentist has performed the most treatments?",
     """SELECT d.full_name, COUNT(*) AS treatment_count
        FROM treatments t JOIN appointments a ON t.appointment_id = a.appointment_id
        JOIN dentists d ON a.dentist_id = d.dentist_id
        GROUP BY d.full_name ORDER BY treatment_count DESC LIMIT 1;"""),

    ("date_filter", "How many appointments were scheduled this week?",
     f"""SELECT COUNT(*) FROM appointments
         WHERE appointment_date BETWEEN '{DR['this_week_start']}' AND '{DR['this_week_end']}';"""),

    ("date_filter", "How many appointments were scheduled last week?",
     f"""SELECT COUNT(*) FROM appointments
         WHERE appointment_date BETWEEN '{DR['last_week_start']}' AND '{DR['last_week_end']}';"""),

    ("date_filter", "How many root canals were completed last month?",
     f"""SELECT COUNT(*) FROM treatments t JOIN appointments a
         ON t.appointment_id = a.appointment_id
         WHERE a.appointment_date BETWEEN '{DR['last_month_start']}' AND '{DR['last_month_end']}'
         AND t.procedure_name LIKE 'Root Canal%';"""),

    ("date_filter", "List appointments for Dr. Sarah Chen this month.",
     f"""SELECT a.appointment_date, a.appointment_type FROM appointments a
         JOIN dentists d ON a.dentist_id = d.dentist_id
         WHERE d.full_name = 'Dr. Sarah Chen'
         AND a.appointment_date BETWEEN '{DR['this_month_start']}' AND '{DR['this_month_end']}';"""),

    ("aggregation", "What's our no-show rate this year?",
     f"""SELECT CAST(SUM(CASE WHEN status = 'No-Show' THEN 1 ELSE 0 END) AS REAL) * 100 / COUNT(*)
         FROM appointments
         WHERE appointment_date BETWEEN '{DR['this_year_start']}' AND '{DR['this_year_end']}';"""),

    ("aggregation", "What is the average cost of a root canal treatment?",
     """SELECT AVG(cost) FROM treatments WHERE procedure_name LIKE 'Root Canal%';"""),

    ("aggregation", "How many unique patients have been seen in total?",
     """SELECT COUNT(DISTINCT patient_id) FROM appointments;"""),

    ("aggregation", "What is the total revenue collected (amount paid) across all invoices?",
     """SELECT SUM(amount_paid) FROM invoices;"""),

    ("text_match", "Which patients were referred by a general dentist?",
     """SELECT full_name FROM patients WHERE referred_by LIKE '%General Dentist%';"""),

    ("text_match", "How many invoices are marked as Unpaid?",
     """SELECT COUNT(*) FROM invoices WHERE payment_status = 'Unpaid';"""),

    ("multi_condition", "Which completed appointments were for emergency pain visits with Dr. Michael Alvarez?",
     """SELECT a.appointment_date FROM appointments a JOIN dentists d
        ON a.dentist_id = d.dentist_id
        WHERE d.full_name = 'Dr. Michael Alvarez' AND a.appointment_type = 'Emergency Pain Visit'
        AND a.status = 'Completed';"""),
]


# ---------------------------------------------------------------------------
# Result comparison.
#
# We do NOT require exact column match — a generated query that does
# `SELECT *` and returns 6 columns when the ground truth only asked for 2 is
# not "wrong," it just returned extra context. What matters is whether the
# actual answer (the ground-truth's values) is present in what the model
# returned.
#
# So: same row COUNT is required (that reflects real filtering/join logic),
# and each ground-truth row's values must be a sub-multiset of some
# generated row's values (one-to-one matched, order-independent). This is
# tolerant of SELECT * / extra columns / reordered columns, while still
# catching genuinely wrong data, wrong filters, or wrong row counts.
# ---------------------------------------------------------------------------
from collections import Counter


def normalize_value(v):
    if isinstance(v, float):
        return round(v, 2)
    return v


def row_multiset(row):
    return Counter(normalize_value(v) for v in row)


def multiset_subset(a, b):
    """Is multiset `a` fully contained within multiset `b`?"""
    return all(b.get(k, 0) >= count for k, count in a.items())


def results_match(gt_rows, gen_rows):
    if len(gt_rows) != len(gen_rows):
        return False

    gt_multisets = [row_multiset(r) for r in gt_rows]
    gen_multisets = [row_multiset(r) for r in gen_rows]
    used = [False] * len(gen_multisets)

    for gt_ms in gt_multisets:
        matched = False
        for i, gen_ms in enumerate(gen_multisets):
            if not used[i] and multiset_subset(gt_ms, gen_ms):
                used[i] = True
                matched = True
                break
        if not matched:
            return False
    return True


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def generate_sql_for_question(question):
    """Mirrors the app's /api/ask logic exactly, including the one-shot retry."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
    import sqlite3

    llm = app_main.get_llm()
    schema, foreign_keys = app_main.get_schema()
    sample_values = app_main.get_sample_values()
    date_ranges_text = app_main.get_date_ranges()
    system_prompt = app_main.SQL_SYSTEM_PROMPT.format(
        schema=schema, foreign_keys=foreign_keys,
        sample_values=sample_values, date_ranges=date_ranges_text,
    )
    messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]

    response = llm.invoke(messages)
    sql = app_main.extract_sql(response.content)

    try:
        columns, rows = app_main.run_sql(sql)
        return sql, columns, rows, False  # False = no retry needed
    except sqlite3.Error as db_err:
        retry_messages = messages + [
            AIMessage(content=sql),
            HumanMessage(content=(
                f"That query failed with this SQLite error:\n{db_err}\n\n"
                "Fix the query. Respond with ONLY the corrected SQL."
            )),
        ]
        retry_response = llm.invoke(retry_messages)
        sql = app_main.extract_sql(retry_response.content)
        columns, rows = app_main.run_sql(sql)  # let this raise if it fails again
        return sql, columns, rows, True


def run_eval():
    results = []
    category_totals = {}

    print(f"Running {len(TEST_CASES)} test cases against model: {app_main.OLLAMA_MODEL}\n")
    print("=" * 80)

    for i, (category, question, ground_truth_sql) in enumerate(TEST_CASES, 1):
        category_totals.setdefault(category, {"pass": 0, "total": 0})
        category_totals[category]["total"] += 1

        print(f"\n[{i}/{len(TEST_CASES)}] ({category}) {question}")

        entry = {
            "category": category,
            "question": question,
            "ground_truth_sql": ground_truth_sql.strip(),
        }

        # Ground truth must always execute — if it doesn't, the test case itself is broken.
        try:
            gt_columns, gt_rows = app_main.run_sql(ground_truth_sql)
        except Exception as exc:
            print(f"  !! GROUND TRUTH SQL FAILED — fix the test case: {exc}")
            entry["status"] = "test_case_error"
            entry["error"] = str(exc)
            results.append(entry)
            continue

        entry["ground_truth_row_count"] = len(gt_rows)

        try:
            gen_sql, gen_columns, gen_rows, used_retry = generate_sql_for_question(question)
            entry["generated_sql"] = gen_sql
            entry["generated_row_count"] = len(gen_rows)
            entry["used_retry"] = used_retry

            if results_match(gt_rows, gen_rows):
                entry["status"] = "pass"
                category_totals[category]["pass"] += 1
                print(f"  PASS  ({len(gen_rows)} rows match)" + (" [needed retry]" if used_retry else ""))
            else:
                entry["status"] = "fail"
                print(f"  FAIL  generated {len(gen_rows)} rows, expected {len(gt_rows)}")
                print(f"        Generated SQL: {gen_sql}")

        except Exception as exc:
            entry["status"] = "error"
            entry["error"] = str(exc)
            print(f"  ERROR  {exc}")

        results.append(entry)

    # ---------------- summary ----------------
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total_pass = sum(c["pass"] for c in category_totals.values())
    total_all = sum(c["total"] for c in category_totals.values())

    for cat, counts in category_totals.items():
        pct = 100 * counts["pass"] / counts["total"] if counts["total"] else 0
        print(f"  {cat:20s}  {counts['pass']}/{counts['total']}  ({pct:.0f}%)")

    overall_pct = 100 * total_pass / total_all if total_all else 0
    print(f"\n  OVERALL: {total_pass}/{total_all}  ({overall_pct:.1f}%)")
    print(f"  Model:   {app_main.OLLAMA_MODEL}")
    print(f"  Date:    {date.today().isoformat()}")

    with open("eval_results.json", "w") as f:
        json.dump({
            "model": app_main.OLLAMA_MODEL,
            "date": date.today().isoformat(),
            "overall_accuracy": round(overall_pct, 1),
            "total_pass": total_pass,
            "total_cases": total_all,
            "category_breakdown": {
                cat: {"pass": c["pass"], "total": c["total"],
                      "pct": round(100 * c["pass"] / c["total"], 1) if c["total"] else 0}
                for cat, c in category_totals.items()
            },
            "results": results,
        }, f, indent=2, default=str)

    print("\nFull results written to eval_results.json")


if __name__ == "__main__":
    run_eval()
