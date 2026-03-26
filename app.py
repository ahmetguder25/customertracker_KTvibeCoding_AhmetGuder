"""Flask application for Customer Tracking System."""
import sqlite3
import os
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")

VALID_STATUSES = ["Lead", "Proposal", "Due Diligence", "Closed Won", "Closed Lost"]


def get_db():
    """Get a database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM customers GROUP BY status"
    ).fetchall()
    conn.close()
    status_counts = {row["status"]: row["cnt"] for row in rows}
    # Ensure every status appears even if count is 0
    chart_data = {s: status_counts.get(s, 0) for s in VALID_STATUSES}
    return render_template("dashboard.html", chart_data=json.dumps(chart_data))


@app.route("/list")
def customer_list():
    conn = get_db()
    customers = conn.execute(
        "SELECT * FROM customers ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template("list.html", customers=customers)


@app.route("/management")
def management():
    conn = get_db()
    customers = conn.execute(
        "SELECT * FROM customers ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template(
        "management.html", customers=customers, statuses=VALID_STATUSES
    )


@app.route("/management/add", methods=["POST"])
def add_customer():
    conn = get_db()
    conn.execute(
        "INSERT INTO customers (company_name, contact_name, deal_size, status, sector, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (
            request.form["company_name"],
            request.form["contact_name"],
            float(request.form["deal_size"]),
            request.form["status"],
            request.form.get("sector", ""),
            request.form.get("notes", ""),
        ),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


@app.route("/management/edit/<int:customer_id>", methods=["GET", "POST"])
def edit_customer(customer_id):
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            """UPDATE customers
               SET company_name=?, contact_name=?, deal_size=?, status=?, sector=?, notes=?
               WHERE id=?""",
            (
                request.form["company_name"],
                request.form["contact_name"],
                float(request.form["deal_size"]),
                request.form["status"],
                request.form.get("sector", ""),
                request.form.get("notes", ""),
                customer_id,
            ),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("management"))

    customer = conn.execute(
        "SELECT * FROM customers WHERE id=?", (customer_id,)
    ).fetchone()
    conn.close()
    if customer is None:
        return redirect(url_for("management"))
    return render_template(
        "edit.html", customer=customer, statuses=VALID_STATUSES
    )


@app.route("/management/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


if __name__ == "__main__":
    # Auto-initialize DB on first run
    from init_db import init_db
    if not os.path.exists(DB_PATH):
        init_db()
    app.run(debug=True, port=5000)
