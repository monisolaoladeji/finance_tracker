import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "finance.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                category TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                occurred_on TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def parse_amount_to_cents(amount_str: str) -> int:
    cleaned = (amount_str or "").strip().replace(",", "")
    value = float(cleaned)
    cents = int(round(value * 100))
    if cents <= 0:
        raise ValueError("Amount must be greater than 0")
    return cents


def start_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def iso(d: date) -> str:
    return d.isoformat()


@app.get("/")
def dashboard():
    today = date.today()
    default_date = iso(today)
    return render_template("dashboard.html", default_date=default_date)


@app.get("/transactions")
def transactions_page():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, amount_cents, category, note, occurred_on
            FROM transactions
            ORDER BY occurred_on DESC, id DESC
            LIMIT 200;
            """
        ).fetchall()
    return render_template("transactions.html", transactions=rows, default_date=iso(date.today()))


@app.post("/transactions")
def create_transaction():
    kind = (request.form.get("kind") or "").strip()
    amount = request.form.get("amount") or ""
    category = (request.form.get("category") or "").strip()
    note = (request.form.get("note") or "").strip()
    occurred_on = (request.form.get("occurred_on") or "").strip()

    if kind not in {"income", "expense"}:
        flash("Please choose income or expense.", "error")
        return redirect(url_for("transactions_page"))

    if not category:
        flash("Category is required.", "error")
        return redirect(url_for("transactions_page"))

    try:
        amount_cents = parse_amount_to_cents(amount)
    except Exception:
        flash("Amount must be a positive number.", "error")
        return redirect(url_for("transactions_page"))

    try:
        datetime.strptime(occurred_on, "%Y-%m-%d")
    except Exception:
        flash("Date must be valid (YYYY-MM-DD).", "error")
        return redirect(url_for("transactions_page"))

    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO transactions (kind, amount_cents, category, note, occurred_on, created_at)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (kind, amount_cents, category, note, occurred_on, created_at),
        )

    flash("Saved.", "success")
    return redirect(url_for("transactions_page"))


@app.post("/transactions/<int:tx_id>/delete")
def delete_transaction(tx_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ?;", (tx_id,))
    if cur.rowcount == 0:
        flash("Transaction not found.", "error")
    else:
        flash("Deleted.", "success")
    return redirect(url_for("transactions_page"))


@app.get("/api/stats")
def api_stats():
    days = int(request.args.get("days", 30))
    days = max(7, min(days, 365))
    end = date.today()
    start = end - timedelta(days=days - 1)

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT kind, amount_cents, category, occurred_on
            FROM transactions
            WHERE occurred_on BETWEEN ? AND ?
            ORDER BY occurred_on ASC;
            """,
            (iso(start), iso(end)),
        ).fetchall()

    by_day = {}
    by_category = {}
    income_cents = 0
    expense_cents = 0

    cur = start
    while cur <= end:
        by_day[iso(cur)] = {"income_cents": 0, "expense_cents": 0}
        cur += timedelta(days=1)

    for r in rows:
        occurred = r["occurred_on"]
        if occurred not in by_day:
            by_day[occurred] = {"income_cents": 0, "expense_cents": 0}

        if r["kind"] == "income":
            by_day[occurred]["income_cents"] += r["amount_cents"]
            income_cents += r["amount_cents"]
        else:
            by_day[occurred]["expense_cents"] += r["amount_cents"]
            expense_cents += r["amount_cents"]
            by_category[r["category"]] = by_category.get(r["category"], 0) + r["amount_cents"]

    labels = list(by_day.keys())
    income_series = [by_day[d]["income_cents"] for d in labels]
    expense_series = [by_day[d]["expense_cents"] for d in labels]

    category_labels = sorted(by_category.keys(), key=lambda k: by_category[k], reverse=True)
    category_values = [by_category[k] for k in category_labels]

    return jsonify(
        {
            "range": {"start": iso(start), "end": iso(end), "days": days},
            "totals": {"income_cents": income_cents, "expense_cents": expense_cents},
            "timeseries": {"labels": labels, "income_cents": income_series, "expense_cents": expense_series},
            "categories": {"labels": category_labels, "expense_cents": category_values},
        }
    )


@app.get("/api/insights")
def api_insights():
    """
    "Simple AI" suggestions: lightweight pattern checks.
    - This week spend vs average of last 4 full weeks
    - Top category this week
    - Savings rate hint (income - expense)
    """
    today = date.today()
    this_week_start = start_of_week(today)
    this_week_end = today

    last_full_week_end = this_week_start - timedelta(days=1)
    last_4_weeks_start = start_of_week(this_week_start - timedelta(days=28))

    with get_db() as conn:
        this_week = conn.execute(
            """
            SELECT kind, amount_cents, category, occurred_on
            FROM transactions
            WHERE occurred_on BETWEEN ? AND ?;
            """,
            (iso(this_week_start), iso(this_week_end)),
        ).fetchall()
        last_4 = conn.execute(
            """
            SELECT kind, amount_cents, category, occurred_on
            FROM transactions
            WHERE occurred_on BETWEEN ? AND ?;
            """,
            (iso(last_4_weeks_start), iso(last_full_week_end)),
        ).fetchall()

    def sum_expenses(rows):
        return sum(r["amount_cents"] for r in rows if r["kind"] == "expense")

    def sum_income(rows):
        return sum(r["amount_cents"] for r in rows if r["kind"] == "income")

    this_week_exp = sum_expenses(this_week)
    this_week_inc = sum_income(this_week)

    week_bins = {}
    for r in last_4:
        d = datetime.strptime(r["occurred_on"], "%Y-%m-%d").date()
        wk = start_of_week(d)
        key = iso(wk)
        week_bins.setdefault(key, {"expense_cents": 0})
        if r["kind"] == "expense":
            week_bins[key]["expense_cents"] += r["amount_cents"]

    weekly_expenses = [week_bins[k]["expense_cents"] for k in sorted(week_bins.keys())]
    avg_weekly_exp = int(round(sum(weekly_expenses) / len(weekly_expenses))) if weekly_expenses else 0

    by_cat = {}
    for r in this_week:
        if r["kind"] == "expense":
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount_cents"]
    top_cat = None
    if by_cat:
        top_cat = max(by_cat.keys(), key=lambda k: by_cat[k])

    insights = []
    if avg_weekly_exp > 0:
        if this_week_exp > int(avg_weekly_exp * 1.15):
            insights.append(
                f"You’ve spent more than usual this week: {this_week_exp/100:.2f} vs your typical {avg_weekly_exp/100:.2f}."
            )
        elif this_week_exp < int(avg_weekly_exp * 0.85):
            insights.append(
                f"Nice—spending is below your usual weekly level: {this_week_exp/100:.2f} vs {avg_weekly_exp/100:.2f}."
            )
        else:
            insights.append(
                f"Your spending is close to normal this week: {this_week_exp/100:.2f} (usual ~{avg_weekly_exp/100:.2f})."
            )
    else:
        insights.append("Add a bit more history to get weekly-spend comparisons.")

    if top_cat:
        insights.append(f"Top expense category this week: {top_cat}.")

    net = this_week_inc - this_week_exp
    if this_week_inc > 0:
        savings_rate = net / this_week_inc
        if savings_rate < 0:
            insights.append("You spent more than you earned this week. Consider trimming one category or adding income.")
        elif savings_rate < 0.1:
            insights.append("Savings rate is under 10% this week. Try setting a small weekly cap for one category.")
        else:
            insights.append(f"Good job—estimated savings rate this week: {savings_rate*100:.0f}%.")
    else:
        if this_week_exp > 0:
            insights.append("No income recorded this week. Add income entries to track savings rate.")

    return jsonify(
        {
            "period": {"week_start": iso(this_week_start), "week_end": iso(this_week_end)},
            "this_week": {"income_cents": this_week_inc, "expense_cents": this_week_exp},
            "avg_weekly_expense_cents": avg_weekly_exp,
            "insights": insights,
        }
    )


init_db()


if __name__ == "__main__":
    app.run(debug=True, port=5001)
