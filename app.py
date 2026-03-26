"""Flask application for Customer Tracking System."""
import sqlite3
import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = "customer-tracker-secret-key-2026"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")



# Logo upload config
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db():
    """Get a database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_status_params(conn=None):
    """Load status parameters from the parameter table.
    Returns a dict keyed by ParamCode: {code: {description, bg, text}}
    """
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    rows = conn.execute(
        "SELECT ParamCode, ParamDescription, ParamValue, ParamValue2 "
        "FROM parameter WHERE ParamType='Status' ORDER BY ParamCode"
    ).fetchall()
    if close_conn:
        conn.close()
    status_map = {}
    for r in rows:
        status_map[str(r["ParamCode"])] = {
            "code": str(r["ParamCode"]),
            "description": r["ParamDescription"],
            "bg": r["ParamValue"] or "bg-gray-500/20",
            "text": r["ParamValue2"] or "text-gray-400",
        }
    return status_map


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    status_map = get_status_params(conn)

    # Status counts for pipeline chart — use descriptions as labels
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM customers GROUP BY status"
    ).fetchall()
    status_counts = {str(row["status"]): row["cnt"] for row in rows}
    # Build chart_data with description labels, ordered by code
    chart_data = {}
    for code, info in sorted(status_map.items(), key=lambda x: x[0]):
        chart_data[info["description"]] = status_counts.get(code, 0)

    # Customer details aggregates
    volume_totals = conn.execute("""
        SELECT
            COALESCE(SUM(foreign_trade_volume), 0)  as total_ft,
            COALESCE(SUM(memzuc_151_volume), 0)     as total_151,
            COALESCE(SUM(memzuc_152_volume), 0)     as total_152,
            COALESCE(SUM(credit_limit), 0)          as total_limit
        FROM customer_details
    """).fetchone()

    # Value segment distribution
    segments = conn.execute("""
        SELECT value_segment, COUNT(*) as cnt
        FROM customer_details
        WHERE value_segment IS NOT NULL
        GROUP BY value_segment
    """).fetchall()
    segment_data = {row["value_segment"]: row["cnt"] for row in segments}

    # Region distribution
    regions = conn.execute("""
        SELECT region, COUNT(*) as cnt
        FROM customer_details
        WHERE region IS NOT NULL
        GROUP BY region
    """).fetchall()
    region_data = {row["region"]: row["cnt"] for row in regions}

    conn.close()

    return render_template(
        "dashboard.html",
        chart_data=json.dumps(chart_data),
        status_map=status_map,
        volume_totals={
            "total_ft": volume_totals["total_ft"],
            "total_151": volume_totals["total_151"],
            "total_152": volume_totals["total_152"],
            "total_limit": volume_totals["total_limit"],
        },
        segment_data=json.dumps(segment_data),
        region_data=json.dumps(region_data),
    )


@app.route("/list")
def customer_list():
    conn = get_db()
    status_map = get_status_params(conn)
    customers = conn.execute("""
        SELECT c.*, cd.credit_limit, cd.value_segment, cd.branch, cd.region,
               cd.portfolio_manager, cd.foreign_trade_volume,
               cd.memzuc_151_volume, cd.memzuc_152_volume
        FROM customers c
        LEFT JOIN customer_details cd ON c.id = cd.customer_id
        ORDER BY c.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("list.html", customers=customers, status_map=status_map)


@app.route("/list/export")
def export_excel():
    """Export the customer list (with details) to an Excel file."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    conn = get_db()
    status_map = get_status_params(conn)
    customers = conn.execute("""
        SELECT c.id, c.company_name, c.contact_name, c.deal_size, c.status, c.sector,
               cd.credit_limit, cd.value_segment, cd.branch, cd.region,
               cd.portfolio_manager, cd.foreign_trade_volume,
               cd.memzuc_151_volume, cd.memzuc_152_volume
        FROM customers c
        LEFT JOIN customer_details cd ON c.id = cd.customer_id
        ORDER BY c.id
    """).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Customers"

    # Headers
    headers = [
        "ID", "Company Name", "Contact Name", "Deal Size (USD)", "Status", "Sector",
        "Credit Limit", "Value Segment", "Branch", "Region",
        "Portfolio Manager", "Foreign Trade Volume",
        "MEMZUC 151 Volume", "MEMZUC 152 Volume"
    ]

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1D62F1", end_color="1D62F1", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Data rows
    for row_idx, c in enumerate(customers, 2):
        status_desc = status_map.get(str(c["status"]), {}).get("description", c["status"])
        values = [
            c["id"], c["company_name"], c["contact_name"], c["deal_size"],
            status_desc, c["sector"] or "",
            c["credit_limit"] or "", c["value_segment"] or "",
            c["branch"] or "", c["region"] or "",
            c["portfolio_manager"] or "", c["foreign_trade_volume"] or "",
            c["memzuc_151_volume"] or "", c["memzuc_152_volume"] or "",
        ]
        for col_idx, value in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    # Auto-fit column widths
    for col_idx, header in enumerate(headers, 1):
        max_len = len(header)
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 30)

    # Save to bytes
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"customers_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/management")
def management():
    conn = get_db()
    status_map = get_status_params(conn)
    customers = conn.execute(
        "SELECT * FROM customers ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return render_template(
        "management.html", customers=customers, status_map=status_map
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
        # Handle logo upload
        logo_filename = None
        if "logo" in request.files:
            file = request.files["logo"]
            if file and file.filename and file.filename != "":
                if not allowed_file(file.filename):
                    flash("Invalid file type. Allowed: PNG, JPG, GIF, SVG", "error")
                    return redirect(url_for("edit_customer", customer_id=customer_id))

                # Check file size
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                if file_size > MAX_LOGO_SIZE:
                    flash("Logo file too large. Maximum size is 2 MB.", "error")
                    return redirect(url_for("edit_customer", customer_id=customer_id))

                # Secure filename and save
                ext = file.filename.rsplit(".", 1)[1].lower()
                safe_name = secure_filename(request.form["company_name"].lower().replace(" ", "_")) + "." + ext
                file.save(os.path.join(UPLOAD_FOLDER, safe_name))
                logo_filename = safe_name

        # Update customer data
        if logo_filename:
            conn.execute(
                """UPDATE customers
                   SET company_name=?, contact_name=?, deal_size=?, status=?, sector=?, notes=?, logo_filename=?
                   WHERE id=?""",
                (
                    request.form["company_name"],
                    request.form["contact_name"],
                    float(request.form["deal_size"]),
                    request.form["status"],
                    request.form.get("sector", ""),
                    request.form.get("notes", ""),
                    logo_filename,
                    customer_id,
                ),
            )
        else:
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

    status_map = get_status_params(conn)
    customer = conn.execute(
        "SELECT * FROM customers WHERE id=?", (customer_id,)
    ).fetchone()
    conn.close()
    if customer is None:
        return redirect(url_for("management"))
    return render_template(
        "edit.html", customer=customer, status_map=status_map
    )


@app.route("/management/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


# ── Overview Routes ───────────────────────────────────────────────────────────

@app.route("/overview")
def overview():
    conn = get_db()
    status_map = get_status_params(conn)
    customers = conn.execute(
        "SELECT * FROM customers ORDER BY company_name"
    ).fetchall()
    conn.close()
    return render_template("overview_list.html", customers=customers, status_map=status_map)


@app.route("/overview/<int:customer_id>")
def overview_detail(customer_id):
    conn = get_db()
    customer = conn.execute(
        "SELECT * FROM customers WHERE id=?", (customer_id,)
    ).fetchone()
    if customer is None:
        conn.close()
        return redirect(url_for("overview"))

    comments = conn.execute(
        "SELECT * FROM comments WHERE customer_id=? ORDER BY created_at DESC",
        (customer_id,),
    ).fetchall()

    # Pipeline stats for the analysis section
    total_customers = conn.execute("SELECT COUNT(*) as cnt FROM customers").fetchone()["cnt"]
    same_sector = conn.execute(
        "SELECT COUNT(*) as cnt FROM customers WHERE sector=?", (customer["sector"],)
    ).fetchone()["cnt"]
    avg_deal = conn.execute(
        "SELECT AVG(deal_size) as avg_size FROM customers"
    ).fetchone()["avg_size"] or 0

    conn.close()

    # Calculate days in pipeline
    created = customer["created_at"]
    if created:
        try:
            created_dt = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
            days_in_pipeline = (datetime.now() - created_dt).days
        except ValueError:
            days_in_pipeline = 0
    else:
        days_in_pipeline = 0

    status_map = get_status_params()

    return render_template(
        "overview_detail.html",
        customer=customer,
        comments=comments,
        status_map=status_map,
        days_in_pipeline=days_in_pipeline,
        total_customers=total_customers,
        same_sector=same_sector,
        avg_deal=avg_deal,
    )


@app.route("/overview/<int:customer_id>/comment", methods=["POST"])
def add_comment(customer_id):
    author = request.form.get("author", "").strip()
    content = request.form.get("content", "").strip()
    if author and content:
        conn = get_db()
        conn.execute(
            "INSERT INTO comments (customer_id, author, content) VALUES (?, ?, ?)",
            (customer_id, author, content),
        )
        conn.commit()
        conn.close()
    return redirect(url_for("overview_detail", customer_id=customer_id))


if __name__ == "__main__":
    # Auto-initialize DB on first run
    from init_db import init_db
    if not os.path.exists(DB_PATH):
        init_db()
    app.run(debug=True, port=5000)
