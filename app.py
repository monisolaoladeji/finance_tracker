import sys
from pathlib import Path

# Add local libs to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "libs"))

import sqlite3
from datetime import date, datetime, timedelta

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = BASE_DIR / "finance.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-this-in-production"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            return User(row["id"], row["username"])
    return None

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
                amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
                category TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                occurred_on TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            );
            """
        )
        # Migration: Add user_id if it doesn't exist (SQLite doesn't support ADD COLUMN IF NOT EXISTS)
        try:
            conn.execute("ALTER TABLE transactions ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;")
        except sqlite3.OperationalError:
            pass # Column already exists
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                monthly_limit_cents INTEGER NOT NULL,
                UNIQUE(user_id, category),
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
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
@login_required
def dashboard():
    today = date.today()
    default_date = iso(today)
    return render_template("dashboard.html", default_date=default_date)


@app.get("/login")
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.post("/login")
def login():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    
    if row and check_password_hash(row["password_hash"], password):
        user = User(row["id"], row["username"])
        login_user(user)
        return redirect(url_for("dashboard"))
    
    flash("Invalid username or password", "error")
    return redirect(url_for("login_page"))


@app.get("/signup")
def signup_page():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.post("/signup")
def signup():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if len(username) < 3 or len(password) < 6:
        flash("Username must be at least 3 chars, password 6.", "error")
        return redirect(url_for("signup_page"))

    password_hash = generate_password_hash(password)
    created_at = datetime.utcnow().isoformat() + "Z"

    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                (username, password_hash, created_at)
            )
        flash("Account created! Please login.", "success")
        return redirect(url_for("login_page"))
    except sqlite3.IntegrityError:
        flash("Username already exists.", "error")
        return redirect(url_for("signup_page"))


@app.get("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login_page"))


@app.get("/transactions")
@login_required
def transactions_page():
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, amount_cents, category, note, occurred_on
            FROM transactions
            WHERE user_id = ?
            ORDER BY occurred_on DESC, id DESC
            LIMIT 200;
            """,
            (current_user.id,)
        ).fetchall()
    return render_template("transactions.html", transactions=rows, default_date=iso(date.today()))


@app.post("/transactions")
@login_required
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
            INSERT INTO transactions (user_id, kind, amount_cents, category, note, occurred_on, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (current_user.id, kind, amount_cents, category, note, occurred_on, created_at),
        )

    flash("Saved.", "success")
    return redirect(url_for("transactions_page"))


@app.get("/budgets")
@login_required
def budgets_page():
    with get_db() as conn:
        budgets = conn.execute(
            "SELECT * FROM budgets WHERE user_id = ? ORDER BY category ASC",
            (current_user.id,)
        ).fetchall()
        
        # Get actual spending for current month for each category
        first_of_month = date.today().replace(day=1).isoformat()
        spending = conn.execute(
            """
            SELECT category, SUM(amount_cents) as total
            FROM transactions
            WHERE user_id = ? AND kind = 'expense' AND occurred_on >= ?
            GROUP BY category
            """,
            (current_user.id, first_of_month)
        ).fetchall()
        spending_map = {s["category"]: s["total"] for s in spending}

    return render_template("budgets.html", budgets=budgets, spending_map=spending_map)


@app.post("/budgets")
@login_required
def save_budget():
    category = (request.form.get("category") or "").strip()
    amount = request.form.get("amount") or ""

    if not category:
        flash("Category is required.", "error")
        return redirect(url_for("budgets_page"))

    try:
        amount_cents = parse_amount_to_cents(amount)
    except Exception:
        flash("Amount must be a positive number.", "error")
        return redirect(url_for("budgets_page"))

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO budgets (user_id, category, monthly_limit_cents)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit_cents = excluded.monthly_limit_cents;
            """,
            (current_user.id, category, amount_cents)
        )
    
    flash("Budget saved.", "success")
    return redirect(url_for("budgets_page"))


@app.post("/budgets/<int:budget_id>/delete")
@login_required
def delete_budget(budget_id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM budgets WHERE id = ? AND user_id = ?", (budget_id, current_user.id))
    flash("Budget deleted.", "success")
    return redirect(url_for("budgets_page"))


@app.post("/transactions/<int:tx_id>/delete")
@login_required
def delete_transaction(tx_id: int):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM transactions WHERE id = ? AND user_id = ?;", (tx_id, current_user.id))
    if cur.rowcount == 0:
        flash("Transaction not found.", "error")
    else:
        flash("Deleted.", "success")
    return redirect(url_for("transactions_page"))


@app.get("/api/stats")
@login_required
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
            WHERE user_id = ? AND occurred_on BETWEEN ? AND ?
            ORDER BY occurred_on ASC;
            """,
            (current_user.id, iso(start), iso(end)),
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


@app.get("/export/csv")
@login_required
def export_csv():
    import io
    import csv
    from flask import Response

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT kind, amount_cents, category, note, occurred_on, created_at
            FROM transactions
            WHERE user_id = ?
            ORDER BY occurred_on DESC;
            """,
            (current_user.id,)
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Type", "Category", "Amount", "Note", "Created At"])
    
    for r in rows:
        writer.writerow([
            r["occurred_on"],
            r["kind"],
            r["category"],
            f"{r['amount_cents'] / 100:.2f}",
            r["note"],
            r["created_at"]
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=transactions.csv"}
    )


@app.get("/api/insights")
@login_required
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
            WHERE user_id = ? AND occurred_on BETWEEN ? AND ?;
            """,
            (current_user.id, iso(this_week_start), iso(this_week_end)),
        ).fetchall()
        last_4 = conn.execute(
            """
            SELECT kind, amount_cents, category, occurred_on
            FROM transactions
            WHERE user_id = ? AND occurred_on BETWEEN ? AND ?;
            """,
            (current_user.id, iso(last_4_weeks_start), iso(last_full_week_end)),
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
    if not this_week and not last_4:
        insights.append("Welcome! Add your first transaction to start getting insights.")
    
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
