"""Flask application for Customer Tracking System."""
import sqlite3
import os
import json
import requests
import re
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, redirect, url_for,
                   send_file, flash, jsonify, session, has_request_context)
from werkzeug.utils import secure_filename
import io

# ── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "customer-tracker-secret-key-2026"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, "customer_tracker.db")
QUERY_DIR  = os.path.join(BASE_DIR, "queries")

UPLOAD_FOLDER     = os.path.join(BASE_DIR, "static", "logos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
MAX_LOGO_SIZE      = 2 * 1024 * 1024  # 2 MB


# ── SQL Query Loader ───────────────────────────────────────────────────────────

def load_query(name: str) -> str:
    """Load SQL from queries/<name>.sql.  No caching — edit files live."""
    path = os.path.join(QUERY_DIR, name + ".sql")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


# ── Database Abstraction ───────────────────────────────────────────────────────


class _ProdCursorWrapper:
    """Wraps a pyodbc cursor to expose dict-like rows (matching sqlite3.Row)."""

    def __init__(self, cursor):
        self._cur = cursor

    def _to_dict(self, row):
        cols = [d[0] for d in self._cur.description]
        return dict(zip(cols, row))

    def fetchall(self):
        return [self._to_dict(r) for r in self._cur.fetchall()]

    def fetchone(self):
        row = self._cur.fetchone()
        return self._to_dict(row) if row is not None else None

    def __getattr__(self, name):
        return getattr(self._cur, name)


class DbConnection:
    """Unified connection wrapper for SQLite (TEST) and pyodbc SQL Server (PROD).

    Both engines use '?' as parameter placeholder, so no substitution needed.
    pyodbc rows are wrapped to support dict-style col access like sqlite3.Row.
    """

    def __init__(self, raw_conn, is_prod: bool = False):
        self._conn   = raw_conn
        self.is_prod = is_prod
        if not is_prod:
            self._conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params=()):
        if self.is_prod:
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return _ProdCursorWrapper(cur)
        return self._conn.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    # context-manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def get_db() -> DbConnection:
    """Return the local database connection (which has Deals, CustomerDetail, and the cached Customer)."""
    return _get_db_test()


def get_customer_db() -> DbConnection:
    """Return connection to SRVDNZ BOA database if PROD, else local SQLite."""
    env = session.get("env", "test") if has_request_context() else "test"
    if env == "prod":
        return _get_db_prod()
    return _get_db_test()


def _get_db_test() -> DbConnection:
    conn = sqlite3.connect(DB_PATH)
    return DbConnection(conn, is_prod=False)


def _get_db_prod() -> DbConnection:
    try:
        import pyodbc  # noqa: PLC0415 — optional dependency
    except ImportError as exc:
        raise RuntimeError(
            "pyodbc is not installed. Run: pip install pyodbc"
        ) from exc

    server  = "SRVDNZ"
    db_name = ""
    config_path = os.path.join(BASE_DIR, "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                server = config.get("PROD_SERVER", server)
                db_name = config.get("PROD_DB_NAME", db_name)
        except Exception as exc:
            print(f"Warning: Failed to load config.json: {exc}")

    # Auto-detect installed SQL Server ODBC driver (prefer 18, then 17)
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    if not drivers:
        raise RuntimeError(
            "No SQL Server ODBC driver found. "
            "Install 'ODBC Driver 17 for SQL Server' or '18 for SQL Server'."
        )
    driver = next((d for d in drivers if "18" in d), None) or drivers[0]

    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        + (f"DATABASE={db_name};" if db_name else "")
        + "Trusted_Connection=yes;"
    )
    try:
        raw = pyodbc.connect(conn_str, autocommit=False, timeout=10)
        return DbConnection(raw, is_prod=True)
    except Exception as exc:
        raise RuntimeError(f"PROD connection failed: {exc}") from exc


# ── Helpers ────────────────────────────────────────────────────────────────────

def to_tr_time(t_str):
    """Converts UTC SQLite timestamp to Istanbul time (+3) → YYYY-MM-DD HH:MM"""
    if not t_str:
        return ""
    try:
        dt = datetime.strptime(str(t_str)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        dt += timedelta(hours=3)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(t_str)[:16]


app.jinja_env.filters["tr_time"] = to_tr_time


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_param_map(param_type, conn=None):
    """Load parameter dict keyed by ParamCode for a given ParamType."""
    close_conn = conn is None
    if close_conn:
        conn = get_db()
    lang_id = session.get("lang", 0) if has_request_context() else 0
    rows = conn.execute(load_query("get_parameters"), (param_type, lang_id)).fetchall()
    if close_conn:
        conn.close()
    return {
        str(r["ParamCode"]): {
            "code":        str(r["ParamCode"]),
            "description": r["ParamDescription"],
            "bg":          r["ParamValue"]  or "bg-gray-500/20",
            "text":        r["ParamValue2"] or "text-gray-400",
            "logo":        r["ParamValue3"] or "",
        }
        for r in rows
    }


# ── Context Processors ─────────────────────────────────────────────────────────

@app.context_processor
def inject_lang_dict():
    """Inject lang_dict + current_lang into all templates."""
    if not has_request_context() or "env" not in session:
        return dict(lang_dict={}, current_lang=0)
    lang_id = session.get("lang", 0)
    conn = get_db()
    rows = conn.execute(load_query("get_dictionary"), (lang_id,)).fetchall()
    conn.close()
    lang_dict = {row["Id"]: row["Description"] for row in rows}
    return dict(lang_dict=lang_dict, current_lang=lang_id)


# ── Environment Guard ──────────────────────────────────────────────────────────

@app.before_request
def require_env_selection():
    """Redirect to env-login if no environment has been selected yet."""
    if request.endpoint in ("env_login", "set_env", "static"):
        return
    if "env" not in session:
        return redirect(url_for("env_login"))


# ── Environment Login / Selector ───────────────────────────────────────────────

@app.route("/")
def index():
    if "env" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("env_login"))


@app.route("/env-login")
def env_login():
    return render_template("env_login.html")


@app.route("/set-env", methods=["POST"])
def set_env():
    env = request.form.get("env", "test")
    if env not in ("test", "prod"):
        env = "test"

    if env == "prod":
        # Try the connection before committing to PROD to surface errors early
        try:
            conn = _get_db_prod()
            conn.close()
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("env_login"))

    session["env"] = env
    return redirect(url_for("dashboard"))


@app.route("/disconnect")
def disconnect():
    """Return to env selection (clear env from session)."""
    session.pop("env", None)
    return redirect(url_for("env_login"))


# ── Language ───────────────────────────────────────────────────────────────────

@app.route("/set_language/<int:lang_id>")
def set_language(lang_id):
    if lang_id in (0, 1):
        session["lang"] = lang_id
    return redirect(request.referrer or url_for("dashboard"))


# ── Dashboard ──────────────────────────────────────────────────────────────────

@app.route("/dashboard")
def dashboard():
    conn = get_db()
    status_map = get_param_map("Status", conn)

    rows          = conn.execute(load_query("dashboard_status_counts")).fetchall()
    status_counts = {str(row["status"]): row["cnt"] for row in rows}
    chart_data    = {
        str(code): {
            "label": info["description"],
            "count": status_counts.get(str(code), 0)
        }
        for code, info in status_map.items()
    }

    volume_totals = conn.execute(load_query("dashboard_volume_totals")).fetchone()
    segments      = conn.execute(load_query("dashboard_segments")).fetchall()
    regions       = conn.execute(load_query("dashboard_regions")).fetchall()
    conn.close()

    segment_data = {row["value_segment"]: row["cnt"] for row in segments}
    region_data  = {row["region"]:        row["cnt"] for row in regions}

    return render_template(
        "dashboard.html",
        chart_data    = json.dumps(chart_data),
        status_map    = status_map,
        volume_totals = {
            "total_ft":    volume_totals["total_ft"],
            "total_151":   volume_totals["total_151"],
            "total_152":   volume_totals["total_152"],
            "total_limit": volume_totals["total_limit"],
        },
        segment_data = json.dumps(segment_data),
        region_data  = json.dumps(region_data),
        active_env   = session.get("env", "test"),
    )


# ── Deals ──────────────────────────────────────────────────────────────────────

@app.route("/list")
def customer_list():
    conn = get_db()
    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    deals         = conn.execute(load_query("list_deals")).fetchall()
    customers     = conn.execute(load_query("list_customers_simple")).fetchall()
    conn.close()
    return render_template("list.html", deals=deals, status_map=status_map,
                           deal_type_map=deal_type_map, fec_map=fec_map,
                           sector_map=sector_map, customers=customers)


@app.route("/deals/<int:deal_id>")
def deal_detail(deal_id):
    conn = get_db()
    deal = conn.execute(load_query("deal_detail"), (deal_id,)).fetchone()
    if not deal:
        conn.close()
        return redirect(url_for("customer_list"))
    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    conn.close()
    return render_template("deal_detail.html", deal=deal, status_map=status_map,
                           deal_type_map=deal_type_map, fec_map=fec_map,
                           sector_map=sector_map)


@app.route("/deals/add", methods=["POST"])
def add_deal():
    conn = get_db()
    conn.execute(load_query("deal_insert"), (
        int(request.form["customerid"]),
        request.form.get("contact_name", ""),
        float(request.form["deal_size"]),
        float(request.form["expected_pricing_pa"]) if request.form.get("expected_pricing_pa") else None,
        int(request.form.get("currency", 0)),
        request.form["status"],
        request.form["dealtype"],
        request.form.get("notes", ""),
    ))
    conn.commit()
    conn.close()
    return redirect(url_for("customer_list"))


@app.route("/deals/edit/<int:deal_id>", methods=["GET", "POST"])
def edit_deal(deal_id):
    conn = get_db()
    if request.method == "POST":
        conn.execute(load_query("deal_update"), (
            request.form.get("contact_name", ""),
            float(request.form["deal_size"]),
            float(request.form["expected_pricing_pa"]) if request.form.get("expected_pricing_pa") else None,
            int(request.form.get("currency", 0)),
            request.form["status"],
            request.form["dealtype"],
            request.form.get("notes", ""),
            deal_id,
        ))
        conn.commit()
        conn.close()
        return redirect(url_for("deal_detail", deal_id=deal_id))

    deal = conn.execute(load_query("deal_edit_detail"), (deal_id,)).fetchone()
    if not deal:
        conn.close()
        return redirect(url_for("customer_list"))
    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    conn.close()
    return render_template("deal_edit.html", deal=deal, status_map=status_map,
                           deal_type_map=deal_type_map, fec_map=fec_map,
                           sector_map=sector_map)


@app.route("/deals/delete/<int:deal_id>", methods=["POST"])
def delete_deal(deal_id):
    conn = get_db()
    conn.execute(load_query("deal_delete"), (deal_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("customer_list"))


@app.route("/list/export")
def export_excel():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    conn          = get_db()
    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    deals         = conn.execute(load_query("export_deals")).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline Deals"

    headers = [
        "Deal ID", "Company Name", "Contact Name", "Deal Type", "Deal Size",
        "Expected Pricing p.a.", "Currency", "Status", "Sector", "Credit Limit",
        "Value Segment", "Branch", "Region", "Portfolio Manager",
        "Foreign Trade Volume", "MEMZUC 151 Volume", "MEMZUC 152 Volume", "Notes",
    ]
    hfont  = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    hfill  = PatternFill(start_color="1D62F1", end_color="1D62F1", fill_type="solid")
    halign = Alignment(horizontal="center", vertical="center", wrap_text=True)
    border = Border(left=Side(style="thin"), right=Side(style="thin"),
                    top=Side(style="thin"), bottom=Side(style="thin"))

    for ci, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=ci, value=h)
        c.font, c.fill, c.alignment, c.border = hfont, hfill, halign, border

    for ri, d in enumerate(deals, 2):
        vals = [
            d["id"], d["CustomerName"], d["contact_name"],
            deal_type_map.get(str(d["dealtype"]),  {}).get("description", d["dealtype"]),
            d["deal_size"],
            d["expected_pricing_pa"] or "",
            fec_map.get(str(d["currency"] or 0), {}).get("bg", "TRY"),
            status_map.get(str(d["status"]),      {}).get("description", d["status"]),
            sector_map.get(str(d["sector"] or ""),{}).get("description", d["sector"]) or "",
            d["credit_limit"] or "", d["value_segment"] or "", d["branch"] or "",
            d["region"] or "", d["portfolio_manager"] or "",
            d["foreign_trade_volume"] or "", d["memzuc_151_volume"] or "",
            d["memzuc_152_volume"] or "", d["notes"] or "",
        ]
        for ci, v in enumerate(vals, 1):
            cell = ws.cell(row=ri, column=ci, value=v)
            cell.border    = border
            cell.alignment = Alignment(vertical="center")

    for ci, h in enumerate(headers, 1):
        mx = max(
            [len(h)] + [len(str(ws.cell(r, ci).value or ""))
                        for r in range(2, ws.max_row + 1)]
        )
        ws.column_dimensions[ws.cell(1, ci).column_letter].width = min(mx + 4, 40)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf, as_attachment=True,
        download_name=f"pipeline_deals_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ── Management ─────────────────────────────────────────────────────────────────

@app.route("/management")
def management():
    conn       = get_db()
    sector_map = get_param_map("Sector", conn)
    customers  = conn.execute(load_query("mgmt_list_customers")).fetchall()
    conn.close()
    return render_template("management.html", customers=customers, sector_map=sector_map)


@app.route("/api/customer/lookup/<int:account_number>")
def lookup_customer(account_number):
    env = session.get("env", "test") if has_request_context() else "test"
    
    if env == "prod":
        conn_real = get_customer_db()
        customer = conn_real.execute(load_query("real_customer_sync"), (account_number,)).fetchone()
        conn_real.close()
        
        if customer:
            conn_local = get_db()
            already = conn_local.execute("SELECT IsStructured FROM Customer WHERE Customerid = ?", (account_number,)).fetchone()
            conn_local.close()
            
            return jsonify({
                "found": True,
                "Customerid": customer["Customerid"],
                "CustomerName": customer["CustomerName"],
                "sector": "",
                "branch": customer["BranchName"] or "",
                "region": customer["ReginalOfficeName"] or "",
                "value_segment": customer["ValueSegment"] or "",
                "portfolio_manager": customer["PortfolioOwnerName"],
                "IsStructured": 1 if already and already["IsStructured"] else 0
            })
        return jsonify({"found": False})
    
    else:
        conn     = get_db()
        customer = conn.execute(load_query("mgmt_lookup_customer"), (account_number,)).fetchone()
        conn.close()
        if customer:
            sector_map = get_param_map("Sector")
            sector_desc = sector_map.get(str(customer["sector"] or ""), {}).get("description", customer["sector"])
            return jsonify({
                "found":            True,
                "Customerid":       customer["Customerid"],
                "CustomerName":     customer["CustomerName"],
                "sector":           sector_desc or "",
                "branch":           customer["branch"] or "",
                "region":           customer["region"] or "",
                "value_segment":    customer["value_segment"] or "",
                "portfolio_manager": customer["portfolio_manager"] or "",
                "IsStructured":     customer["IsStructured"],
            })
        return jsonify({"found": False})


@app.route("/management/customer/add", methods=["POST"])
def add_customer():
    customer_id = int(request.form["Customerid"])
    env = session.get("env", "test") if has_request_context() else "test"
    
    if env == "prod":
        conn_real = get_customer_db()
        customer = conn_real.execute(load_query("real_customer_sync"), (customer_id,)).fetchone()
        conn_real.close()
        
        if customer:
            conn_local = get_db()
            conn_local.execute("""
                INSERT INTO Customer (Customerid, CustomerName, credit_limit, credit_limit_currency, foreign_trade_volume, memzuc_151_volume, memzuc_152_volume, value_segment, branch, region, portfolio_manager, IsStructured)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(Customerid) DO UPDATE SET
                    CustomerName = excluded.CustomerName,
                    credit_limit = excluded.credit_limit,
                    credit_limit_currency = excluded.credit_limit_currency,
                    foreign_trade_volume = excluded.foreign_trade_volume,
                    memzuc_151_volume = excluded.memzuc_151_volume,
                    memzuc_152_volume = excluded.memzuc_152_volume,
                    value_segment = excluded.value_segment,
                    branch = excluded.branch,
                    region = excluded.region,
                    portfolio_manager = excluded.portfolio_manager,
                    IsStructured = 1
            """, (
                customer["Customerid"], customer["CustomerName"], customer["TotalLimit"], customer["credit_limit_currency"],
                customer["foreign_trade_volume"], customer["memzuc_151_volume"], customer["memzuc_152_volume"],
                customer["ValueSegment"], customer["BranchName"], customer["ReginalOfficeName"],
                customer["PortfolioOwnerName"]
            ))
            conn_local.commit()
            conn_local.close()
    else:
        conn = get_db()
        conn.execute(load_query("mgmt_set_structured"), (customer_id,))
        conn.commit()
        conn.close()
        
    return redirect(url_for("management"))


@app.route("/management/api/sync/queue", methods=["GET"])
def sync_queue():
    # Available in both TEST (demo) and PROD
    conn_local = get_db()
    customers = conn_local.execute("SELECT Customerid, CustomerName FROM Customer WHERE IsStructured = 1").fetchall()
    conn_local.close()
    
    return jsonify({
        "success": True,
        "customers": [{"id": c["Customerid"], "name": c["CustomerName"]} for c in customers]
    })

@app.route("/management/api/sync/<int:cid>", methods=["POST"])
def sync_single(cid):
    import time
    env = session.get("env", "test") if has_request_context() else "test"
    
    # TEST environment: simulate a short delay then return dummy success
    if env != "prod":
        time.sleep(0.4)  # simulate network round-trip
        conn_local = get_db()
        row = conn_local.execute("SELECT CustomerName FROM Customer WHERE Customerid = ?", (cid,)).fetchone()
        conn_local.close()
        name = row["CustomerName"] if row else f"Customer {cid}"
        return jsonify({"success": True, "name": name, "demo": True})
    
    conn_real = get_customer_db()
    customer = conn_real.execute(load_query("real_customer_sync"), (cid,)).fetchone()
    conn_real.close()
    
    if customer:
        conn_local = get_db()
        conn_local.execute("""
            UPDATE Customer SET
                CustomerName = ?,
                credit_limit = ?,
                credit_limit_currency = ?,
                foreign_trade_volume = ?,
                memzuc_151_volume = ?,
                memzuc_152_volume = ?,
                value_segment = ?,
                branch = ?,
                region = ?,
                portfolio_manager = ?
            WHERE Customerid = ?
        """, (
            customer["CustomerName"], customer["TotalLimit"], customer["credit_limit_currency"],
            customer["foreign_trade_volume"], customer["memzuc_151_volume"], customer["memzuc_152_volume"],
            customer["ValueSegment"], customer["BranchName"],
            customer["ReginalOfficeName"], customer["PortfolioOwnerName"],
            cid
        ))
        conn_local.commit()
        conn_local.close()
        return jsonify({"success": True, "name": customer["CustomerName"]})
    return jsonify({"success": False, "error": "Not found on remote."})


@app.route("/management/edit/<int:customer_id>", methods=["GET", "POST"])
def edit_customer(customer_id):
    conn = get_db()
    if request.method == "POST":
        logo_filename = None
        if "logo" in request.files:
            file = request.files["logo"]
            if file and file.filename:
                if not allowed_file(file.filename):
                    flash("Invalid file type.", "error")
                    conn.close()
                    return redirect(url_for("edit_customer", customer_id=customer_id))
                file.seek(0, os.SEEK_END)
                if file.tell() > MAX_LOGO_SIZE:
                    flash("Logo file too large.", "error")
                    conn.close()
                    return redirect(url_for("edit_customer", customer_id=customer_id))
                file.seek(0)
                ext       = file.filename.rsplit(".", 1)[1].lower()
                safe_name = secure_filename(request.form["CustomerName"].lower().replace(" ", "_")) + "." + ext
                file.save(os.path.join(UPLOAD_FOLDER, safe_name))
                logo_filename = safe_name

        if logo_filename:
            conn.execute(load_query("mgmt_update_customer_logo"), (
                request.form["CustomerName"],
                request.form.get("sector", ""),
                request.form.get("portfolio_manager", ""),
                logo_filename,
                customer_id,
            ))
        else:
            conn.execute(load_query("mgmt_update_customer"), (
                request.form["CustomerName"],
                request.form.get("sector", ""),
                request.form.get("portfolio_manager", ""),
                customer_id,
            ))
        conn.commit()
        conn.close()
        return redirect(url_for("edit_customer", customer_id=customer_id))

    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("management"))
    sector_map = get_param_map("Sector", conn)
    conn.close()
    return render_template("edit.html", customer=customer, sector_map=sector_map)


@app.route("/management/customer/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    conn = get_db()
    conn.execute(load_query("mgmt_remove_structured"), (customer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("management"))


# ── Overview ───────────────────────────────────────────────────────────────────

@app.route("/overview")
def overview():
    conn       = get_db()
    customers  = conn.execute(load_query("overview_list")).fetchall()
    sector_map = get_param_map("Sector", conn)
    conn.close()
    return render_template("overview_list.html", customers=customers, sector_map=sector_map)


@app.route("/overview/<int:customer_id>")
def overview_detail(customer_id):
    conn = get_db()
    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("overview"))

    deals        = conn.execute(load_query("overview_deals"),        (customer_id,)).fetchall()
    comments     = conn.execute(load_query("overview_comments"),     (customer_id,)).fetchall()
    same_sector  = conn.execute(load_query("overview_same_sector"),  (customer["sector"],)).fetchone()["cnt"]
    total_cust   = conn.execute(load_query("overview_total_customers")).fetchone()["cnt"]

    lang_id      = session.get("lang", 0)
    analysis_row = conn.execute(load_query("overview_latest_analysis"), (customer_id, lang_id)).fetchone()

    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    conn.close()

    total_deal_size = sum((d["deal_size"] or 0) for d in deals)

    return render_template(
        "overview_detail.html",
        customer        = customer,
        deals           = deals,
        comments        = comments,
        status_map      = status_map,
        deal_type_map   = deal_type_map,
        fec_map         = fec_map,
        sector_map      = sector_map,
        total_customers = total_cust,
        same_sector     = same_sector,
        total_deal_size = total_deal_size,
        analysis        = analysis_row,
    )


# ── AI Analysis ────────────────────────────────────────────────────────────────

@app.route("/api/analysis/generate/<int:customer_id>", methods=["POST"])
def generate_analysis(customer_id):
    conn     = get_db()
    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return {"error": "Customer not found"}, 404

    deals    = conn.execute(load_query("analysis_get_deals"), (customer_id,)).fetchall()
    lang_id  = session.get("lang", 0)
    deal_info = ", ".join([f"${d['deal_size']} (Status ID {d['status']})" for d in deals])

    prompt_file = "prompt_tr.txt" if lang_id == 1 else "prompt_en.txt"
    prompt_path = os.path.join(BASE_DIR, prompt_file)
    max_chars   = 100
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except Exception:
        if lang_id == 1:
            prompt_template = "'{sector}' sektöründeki '{customer_name}' müşterisini analiz et. Anlaşmalar: {deal_info}. En fazla {max_chars} karakterlik analiz yaz."
        else:
            prompt_template = "Analyze customer '{customer_name}' in sector '{sector}'. Deals: {deal_info}. Write a {max_chars} character max analysis."

    sector_map  = get_param_map("Sector", conn)
    sector_desc = sector_map.get(str(customer["sector"] or ""), {}).get("description", customer["sector"])
    prompt = prompt_template.format(
        customer_name=customer["CustomerName"],
        sector=sector_desc, deal_info=deal_info, max_chars=max_chars,
    )

    try:
        payload = {"model": "qwen3-coder:30b", "stream": False, "prompt": prompt}
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        analysis_text = resp.json().get("response", "Analysis completed but returned empty.")
    except Exception as e:
        analysis_text = f"Ollama Error: {str(e)[:50]}"

    analysis_text = analysis_text[:100]
    conn.execute(load_query("analysis_insert"), (customer_id, analysis_text, lang_id))
    conn.commit()
    latest = conn.execute(load_query("analysis_latest"), (customer_id, lang_id)).fetchone()
    conn.close()
    return {"status": "success", "analysis": latest["analysis_text"], "created_at": to_tr_time(latest["created_at"])}


# ── Chat ───────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "No message provided"}), 400
    payload = {"model": "qwen3-coder:30b", "stream": False, "prompt": data["message"]}
    try:
        resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=60)
        resp.raise_for_status()
        return jsonify({"response": resp.json().get("response", "")})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Ollama API error: {str(e)}"}), 500


# ── Comments ───────────────────────────────────────────────────────────────────

@app.route("/overview/<int:customer_id>/comment", methods=["POST"])
def add_comment(customer_id):
    author  = request.form.get("author",  "").strip()
    content = request.form.get("content", "").strip()
    if author and content:
        conn = get_db()
        conn.execute(load_query("comment_insert"), (customer_id, author, content))
        conn.commit()
        conn.close()
    return redirect(url_for("overview_detail", customer_id=customer_id))


# ── Entry Point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
