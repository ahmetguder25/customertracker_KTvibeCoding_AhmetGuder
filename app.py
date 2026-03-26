"""Flask application for Customer Tracking System."""
import sqlite3
import os
import json
import requests
import websocket
import re
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, flash
from werkzeug.utils import secure_filename
import io

app = Flask(__name__)
app.secret_key = "customer-tracker-secret-key-2026"
load_dotenv()
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")

# Logo upload config
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2 MB

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_param_map(param_type, conn=None):
    """Load parameter dictionary keyed by ParamCode for a given ParamType."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    rows = conn.execute(
        "SELECT ParamCode, ParamDescription, ParamValue, ParamValue2 "
        "FROM Parameter WHERE ParamType=? ORDER BY CAST(ParamCode AS INTEGER)",
        (param_type,)
    ).fetchall()
    if close_conn:
        conn.close()
    
    param_map = {}
    for r in rows:
        param_map[str(r["ParamCode"])] = {
            "code": str(r["ParamCode"]),
            "description": r["ParamDescription"],
            "bg": r["ParamValue"] or "bg-gray-500/20",
            "text": r["ParamValue2"] or "text-gray-400",
        }
    return param_map


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    conn = get_db()
    status_map = get_param_map("Status", conn)

    # Status counts for pipeline chart (from deals)
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM CustomerDeals GROUP BY status"
    ).fetchall()
    status_counts = {str(row["status"]): row["cnt"] for row in rows}
    
    chart_data = {}
    for code, info in status_map.items():
        chart_data[info["description"]] = status_counts.get(code, 0)

    # Customer aggregates
    volume_totals = conn.execute("""
        SELECT
            COALESCE(SUM(foreign_trade_volume), 0)  as total_ft,
            COALESCE(SUM(memzuc_151_volume), 0)     as total_151,
            COALESCE(SUM(memzuc_152_volume), 0)     as total_152,
            COALESCE(SUM(credit_limit), 0)          as total_limit
        FROM Customer
    """).fetchone()

    segments = conn.execute("""
        SELECT value_segment, COUNT(*) as cnt
        FROM Customer
        WHERE value_segment IS NOT NULL AND value_segment != ''
        GROUP BY value_segment
    """).fetchall()
    segment_data = {row["value_segment"]: row["cnt"] for row in segments}

    regions = conn.execute("""
        SELECT region, COUNT(*) as cnt
        FROM Customer
        WHERE region IS NOT NULL AND region != ''
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
    status_map = get_param_map("Status", conn)
    deal_type_map = get_param_map("DealType", conn)
    
    # Flat list joining Deals and Customers
    deals = conn.execute("""
        SELECT d.*, c.CustomerName, c.sector, c.credit_limit, c.value_segment, 
               c.branch, c.region, c.portfolio_manager, c.foreign_trade_volume, 
               c.memzuc_151_volume, c.memzuc_152_volume
        FROM CustomerDeals d
        JOIN Customer c ON d.customerid = c.Customerid
        ORDER BY d.created_at DESC
    """).fetchall()
    conn.close()
    
    return render_template("list.html", deals=deals, status_map=status_map, deal_type_map=deal_type_map)


@app.route("/list/export")
def export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    conn = get_db()
    status_map = get_param_map("Status", conn)
    deal_type_map = get_param_map("DealType", conn)
    
    deals = conn.execute("""
        SELECT d.*, c.CustomerName, c.sector, c.credit_limit, c.value_segment, 
               c.branch, c.region, c.portfolio_manager, c.foreign_trade_volume, 
               c.memzuc_151_volume, c.memzuc_152_volume
        FROM CustomerDeals d
        JOIN Customer c ON d.customerid = c.Customerid
        ORDER BY c.CustomerName, d.created_at DESC
    """).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline Deals"

    headers = [
        "Deal ID", "Company Name", "Contact Name", "Deal Type", "Deal Size (USD)", "Status",
        "Sector", "Credit Limit", "Value Segment", "Branch", "Region",
        "Portfolio Manager", "Foreign Trade Volume", "MEMZUC 151 Volume", "MEMZUC 152 Volume", "Notes"
    ]

    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1D62F1", end_color="1D62F1", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(left=Side(style="thin"), right=Side(style="thin"), top=Side(style="thin"), bottom=Side(style="thin"))

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    for row_idx, d in enumerate(deals, 2):
        status_desc = status_map.get(str(d["status"]), {}).get("description", d["status"])
        dealtype_desc = deal_type_map.get(str(d["dealtype"]), {}).get("description", d["dealtype"])
        
        values = [
            d["id"], d["CustomerName"], d["contact_name"], dealtype_desc, d["deal_size"], status_desc,
            d["sector"] or "", d["credit_limit"] or "", d["value_segment"] or "",
            d["branch"] or "", d["region"] or "", d["portfolio_manager"] or "",
            d["foreign_trade_volume"] or "", d["memzuc_151_volume"] or "", d["memzuc_152_volume"] or "",
            d["notes"] or ""
        ]
        for col_idx, value in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center")

    for col_idx, header in enumerate(headers, 1):
        max_len = len(header)
        for row in ws.iter_rows(min_row=2, min_col=col_idx, max_col=col_idx):
            for cell in row:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 40)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"pipeline_deals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Management Routes ─────────────────────────────────────────────────────────

@app.route("/management")
def management():
    """List all Customers"""
    conn = get_db()
    customers = conn.execute("SELECT * FROM Customer ORDER BY Customerid DESC").fetchall()
    
    # We will compute the sum of deals for each customer manually
    deal_counts = {}
    deal_sums = {}
    aggs = conn.execute("SELECT customerid, COUNT(*) as cnt, SUM(deal_size) as total FROM CustomerDeals GROUP BY customerid").fetchall()
    for row in aggs:
        deal_counts[row["customerid"]] = row["cnt"]
        deal_sums[row["customerid"]] = row["total"]

    conn.close()
    return render_template("management.html", customers=customers, deal_counts=deal_counts, deal_sums=deal_sums)


@app.route("/management/customer/add", methods=["POST"])
def add_customer():
    conn = get_db()
    conn.execute(
        """INSERT INTO Customer (CustomerName, sector, credit_limit, value_segment, branch, region, 
           portfolio_manager, foreign_trade_volume, memzuc_151_volume, memzuc_152_volume) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            request.form["CustomerName"], request.form.get("sector", ""),
            request.form.get("credit_limit") or None, request.form.get("value_segment", ""),
            request.form.get("branch", ""), request.form.get("region", ""),
            request.form.get("portfolio_manager", ""), request.form.get("foreign_trade_volume") or None,
            request.form.get("memzuc_151_volume") or None, request.form.get("memzuc_152_volume") or None,
        )
    )
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


@app.route("/management/edit/<int:customer_id>", methods=["GET", "POST"])
def edit_customer(customer_id):
    conn = get_db()
    if request.method == "POST":
        logo_filename = None
        if "logo" in request.files:
            file = request.files["logo"]
            if file and file.filename and file.filename != "":
                if not allowed_file(file.filename):
                    flash("Invalid file type.", "error")
                    return redirect(url_for("edit_customer", customer_id=customer_id))
                file.seek(0, os.SEEK_END)
                if file.tell() > MAX_LOGO_SIZE:
                    flash("Logo file too large.", "error")
                    return redirect(url_for("edit_customer", customer_id=customer_id))
                file.seek(0)
                ext = file.filename.rsplit(".", 1)[1].lower()
                safe_name = secure_filename(request.form["CustomerName"].lower().replace(" ", "_")) + "." + ext
                file.save(os.path.join(UPLOAD_FOLDER, safe_name))
                logo_filename = safe_name

        q = """UPDATE Customer SET CustomerName=?, sector=?, credit_limit=?, value_segment=?, 
               branch=?, region=?, portfolio_manager=?, foreign_trade_volume=?, 
               memzuc_151_volume=?, memzuc_152_volume=?"""
        params = [
            request.form["CustomerName"], request.form.get("sector", ""),
            request.form.get("credit_limit") or None, request.form.get("value_segment", ""),
            request.form.get("branch", ""), request.form.get("region", ""),
            request.form.get("portfolio_manager", ""), request.form.get("foreign_trade_volume") or None,
            request.form.get("memzuc_151_volume") or None, request.form.get("memzuc_152_volume") or None
        ]
        
        if logo_filename:
            q += ", LogoFilename=?"
            params.append(logo_filename)
            
        q += " WHERE Customerid=?"
        params.append(customer_id)

        conn.execute(q, params)
        conn.commit()
        return redirect(url_for("edit_customer", customer_id=customer_id))

    customer = conn.execute("SELECT * FROM Customer WHERE Customerid=?", (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("management"))

    deals = conn.execute("SELECT * FROM CustomerDeals WHERE customerid=? ORDER BY created_at DESC", (customer_id,)).fetchall()
    status_map = get_param_map("Status", conn)
    deal_type_map = get_param_map("DealType", conn)
    conn.close()

    return render_template("edit.html", customer=customer, deals=deals, status_map=status_map, deal_type_map=deal_type_map)


@app.route("/management/customer/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM Customer WHERE Customerid=?", (customer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


@app.route("/management/deal/add/<int:customer_id>", methods=["POST"])
def add_deal(customer_id):
    conn = get_db()
    conn.execute(
        """INSERT INTO CustomerDeals (customerid, contact_name, deal_size, status, dealtype, notes) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            customer_id, request.form.get("contact_name", ""),
            float(request.form["deal_size"]), request.form["status"],
            request.form["dealtype"], request.form.get("notes", "")
        )
    )
    conn.commit()
    conn.close()
    return redirect(url_for("edit_customer", customer_id=customer_id))


@app.route("/management/deal/delete/<int:deal_id>", methods=["POST"])
def delete_deal(deal_id):
    conn = get_db()
    deal = conn.execute("SELECT customerid FROM CustomerDeals WHERE id=?", (deal_id,)).fetchone()
    if deal:
        conn.execute("DELETE FROM CustomerDeals WHERE id=?", (deal_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("edit_customer", customer_id=deal["customerid"]))
    conn.close()
    return redirect(url_for("management"))


# ── Overview Routes ───────────────────────────────────────────────────────────

@app.route("/overview")
def overview():
    conn = get_db()
    # List Customers and their total active deals vs sizes
    customers = conn.execute("""
        SELECT c.*, COUNT(d.id) as deal_count, SUM(d.deal_size) as total_deal_size
        FROM Customer c
        LEFT JOIN CustomerDeals d ON c.Customerid = d.customerid
        GROUP BY c.Customerid
        ORDER BY c.CustomerName
    """).fetchall()
    conn.close()
    return render_template("overview_list.html", customers=customers)


@app.route("/overview/<int:customer_id>")
def overview_detail(customer_id):
    conn = get_db()
    customer = conn.execute("SELECT * FROM Customer WHERE Customerid=?", (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("overview"))

    deals = conn.execute("SELECT * FROM CustomerDeals WHERE customerid=? ORDER BY created_at DESC", (customer_id,)).fetchall()
    comments = conn.execute("SELECT * FROM Comment WHERE customer_id=? ORDER BY created_at DESC", (customer_id,)).fetchall()

    same_sector = conn.execute("SELECT COUNT(*) as cnt FROM Customer WHERE sector=?", (customer["sector"],)).fetchone()["cnt"]
    total_customers = conn.execute("SELECT COUNT(*) as cnt FROM Customer").fetchone()["cnt"]

    analysis_row = conn.execute("SELECT * FROM CustomerAnalysis WHERE customer_id=? ORDER BY created_at DESC LIMIT 1", (customer_id,)).fetchone()

    status_map = get_param_map("Status", conn)
    deal_type_map = get_param_map("DealType", conn)
    conn.close()

    total_deal_size = sum((d["deal_size"] or 0) for d in deals)

    return render_template(
        "overview_detail.html",
        customer=customer,
        deals=deals,
        comments=comments,
        status_map=status_map,
        deal_type_map=deal_type_map,
        total_customers=total_customers,
        same_sector=same_sector,
        total_deal_size=total_deal_size,
        analysis=analysis_row
    )


@app.route("/api/analysis/generate/<int:customer_id>", methods=["POST"])
def generate_analysis(customer_id):
    load_dotenv(override=True)
    conn = get_db()
    customer = conn.execute("SELECT * FROM Customer WHERE Customerid=?", (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return {"error": "Customer not found"}, 404

    deals = conn.execute("SELECT * FROM CustomerDeals WHERE customerid=?", (customer_id,)).fetchall()
    
    deal_info = ", ".join([f"${d['deal_size']} (Status ID {d['status']})" for d in deals])
    prompt = f"Analyze customer '{customer['CustomerName']}' in sector '{customer['sector']}'. They have deals: {deal_info}. Write a 100 character max analysis."

    api_key = os.getenv("OPENAI_API_KEY")
    endpoint = os.getenv("OPENAI_ENDPOINT")
    
    analysis_text = "Analysis not available due to missing API key or endpoint."
    if api_key and endpoint and api_key != "ABC123":
        try:
            ws_url = endpoint.replace("https://", "wss://").replace("http://", "ws://")
            if "/chat/completions" in ws_url:
                match = re.search(r"/deployments/([^/]+)/", ws_url)
                deployment = match.group(1) if match else ""
                base = ws_url.split("/openai/")[0]
                api_version = re.search(r"api-version=([^&]+)", ws_url)
                api_version = api_version.group(1) if api_version else "2024-10-01-preview"
                ws_url = f"{base}/openai/realtime?api-version={api_version}&deployment={deployment}"

            ws = websocket.WebSocket()
            ws.connect(ws_url, header={"api-key": api_key})
            
            request_payload = {
                "type": "response.create",
                "response": {
                    "modalities": ["text"],
                    "instructions": prompt
                }
            }
            ws.send(json.dumps(request_payload))
            
            analysis_text = ""
            while True:
                msg = ws.recv()
                if not msg:
                    break
                data = json.loads(msg)
                if data["type"] == "response.text.delta":
                    analysis_text += data.get("delta", "")
                elif data["type"] == "response.done":
                    break
                elif data["type"] == "error":
                    analysis_text = f"API Error: {data.get('error', {}).get('message', 'Unknown')}"
                    break
                    
            ws.close()
            
            if not analysis_text.strip():
                analysis_text = "Analysis completed but returned empty."
                
        except Exception as e:
            analysis_text = f"Error: {str(e)[:50]}"
    else:
        # Fallback if placeholder string
        analysis_text = f"Sample AI Analysis for {customer['CustomerName']}: Solid sector footprint with {len(deals)} active deals."

    analysis_text = analysis_text[:100]

    conn.execute("INSERT INTO CustomerAnalysis (customer_id, analysis_text) VALUES (?, ?)", (customer_id, analysis_text))
    conn.commit()
    
    latest = conn.execute("SELECT * FROM CustomerAnalysis WHERE customer_id=? ORDER BY created_at DESC LIMIT 1", (customer_id,)).fetchone()
    conn.close()

    return {"status": "success", "analysis": latest["analysis_text"], "created_at": latest["created_at"]}


@app.route("/overview/<int:customer_id>/comment", methods=["POST"])
def add_comment(customer_id):
    author = request.form.get("author", "").strip()
    content = request.form.get("content", "").strip()
    if author and content:
        conn = get_db()
        conn.execute(
            "INSERT INTO Comment (customer_id, author, content) VALUES (?, ?, ?)",
            (customer_id, author, content),
        )
        conn.commit()
        conn.close()
    return redirect(url_for("overview_detail", customer_id=customer_id))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
