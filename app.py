"""Flask application for Customer Tracking System."""
import os
import platform
import json
import requests
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, redirect, url_for,
                   send_file, flash, jsonify, session, has_request_context)
from werkzeug.utils import secure_filename
import io
from flask import stream_with_context, Response
from ollama_config import OLLAMA_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from data_agent_orchestrator import process_agent_turn

from agent_orchestrator import AnalysisOrchestrator
# ── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "customer-tracker-secret-key-2026"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
QUERY_DIR  = os.path.join(BASE_DIR, "queries")

UPLOAD_FOLDER     = os.path.join(BASE_DIR, "static", "logos")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg"}
MAX_LOGO_SIZE      = 2 * 1024 * 1024  # 2 MB


# ── SQL Query Loader ───────────────────────────────────────────────────────────

def load_query(name: str, query_dir: str = None) -> str:
    """Load SQL from <query_dir>/<name>.sql.  Defaults to the main queries/ dir.
    Pass an explicit query_dir (e.g. admin/queries/) to load module-specific SQL.
    No caching — edit files live."""
    directory = query_dir if query_dir is not None else QUERY_DIR
    path = os.path.join(directory, name + ".sql")
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
    """pyodbc connection wrapper for LOCAL and PROD SQL Server.

    Both environments use pyodbc; rows are returned as dicts via _ProdCursorWrapper.
    """

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql: str, params=()):
        cur = self._conn.cursor()
        cur.execute(sql, params)
        return _ProdCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    # context-manager support
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class _PymssqlDbConnection(DbConnection):
    """pymssql-backed connection wrapper.

    pymssql uses %s placeholders; this subclass converts ? → %s transparently
    so all caller code stays identical to the pyodbc path.
    """

    def execute(self, sql: str, params=()):
        sql_converted = sql.replace("?", "%s")
        cur = self._conn.cursor()
        cur.execute(sql_converted, params if params else ())
        return _ProdCursorWrapper(cur)


def get_db() -> DbConnection:
    """Return the local SQL Server connection (Deals, CustomerDetail, cached Customer)."""
    return _get_db_local()


def get_customer_db() -> DbConnection:
    """Return connection to SRVDNZ BOA database if PROD, else local SQL Server."""
    env = session.get("env", "local") if has_request_context() else "local"
    if env == "prod":
        return _get_db_prod()
    return _get_db_local()


def _get_db_local() -> DbConnection:
    """LOCAL connection — autocommit=False."""
    return _make_local_conn(autocommit=False)


def _get_db_prod() -> DbConnection:
    """PROD connection with autocommit=False (for regular reads/writes)."""
    return _make_prod_conn(autocommit=False)


def _get_db_prod_autocommit() -> DbConnection:
    """PROD connection with autocommit=True (required for multi-statement batches with temp tables)."""
    return _make_prod_conn(autocommit=True)


def _make_local_conn(autocommit: bool = False) -> DbConnection:
    """OS-aware factory: connection to the local SQL Server instance.

    - macOS / Linux  → Docker container, pymssql + SQL Auth (sa + config.json)
                       No system ODBC library required — pymssql bundles FreeTDS.
    - Windows        → Installed SQL Server Express/Developer, pyodbc + Windows Auth
    """
    config_path = os.path.join(BASE_DIR, "config.json")
    config: dict = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as exc:
            print(f"Warning: Failed to load config.json: {exc}")

    db_name = config.get("LOCAL_DB_NAME", "BOA")
    os_name = platform.system()

    if os_name == "Windows":
        # Windows: pyodbc + Windows Auth (ODBC built into every Windows install)
        try:
            import pyodbc  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("pyodbc is not installed. Run: pip install pyodbc") from exc

        server = config.get("LOCAL_WIN_SERVER", r".\SQLEXPRESS")
        drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
        if not drivers:
            raise RuntimeError(
                "No SQL Server ODBC driver found. "
                "Install 'ODBC Driver 17/18 for SQL Server' from Microsoft."
            )
        driver = next((d for d in drivers if "18" in d), None) or drivers[0]
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"SERVER={server};"
            f"DATABASE={db_name};"
            "Trusted_Connection=yes;"
        )
        try:
            raw = pyodbc.connect(conn_str, autocommit=autocommit, timeout=10)
            return DbConnection(raw)
        except Exception as exc:
            raise RuntimeError(f"LOCAL connection failed ({server}/{db_name}): {exc}") from exc

    else:
        # macOS / Linux: pymssql — no system ODBC library required
        try:
            import pymssql  # noqa: PLC0415
        except ImportError as exc:
            raise RuntimeError("pymssql is not installed. Run: pip3 install pymssql") from exc

        server_full = config.get("LOCAL_SERVER", "localhost,1433")
        server_addr = server_full.replace(",", ":")  # pymssql uses 'host:port'
        sa_user = config.get("LOCAL_SA_USER", "sa")
        sa_pass = config.get("LOCAL_SA_PASSWORD", "")
        try:
            raw = pymssql.connect(
                server=server_addr,
                user=sa_user,
                password=sa_pass,
                database=db_name,
                login_timeout=10,
            )
            if autocommit:
                raw.autocommit(True)
            return _PymssqlDbConnection(raw)
        except Exception as exc:
            raise RuntimeError(f"LOCAL connection failed ({server_full}/{db_name}): {exc}") from exc


def _make_prod_conn(autocommit: bool = False) -> DbConnection:
    """Internal factory: build a pyodbc connection to SRVDNZ/BOA."""
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
        raw = pyodbc.connect(conn_str, autocommit=autocommit, timeout=10)
        return DbConnection(raw)
    except Exception as exc:
        raise RuntimeError(f"PROD connection failed ({server}/{db_name}): {exc}") from exc


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


def _fmt_dt(v, chars):
    """Format a date/datetime value (datetime obj or string) to a fixed-length string.
    Works with both pymssql datetime objects and plain strings."""
    if not v:
        return ""
    try:
        return str(v)[:chars]
    except Exception:
        return ""

app.jinja_env.filters["fmtdate"]     = lambda v: _fmt_dt(v, 10)   # → YYYY-MM-DD
app.jinja_env.filters["fmtdatetime"] = lambda v: _fmt_dt(v, 16)   # → YYYY-MM-DD HH:MM


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
    if not has_request_context():
        return dict(lang_dict={}, current_lang=0)
    lang_id = session.get("lang", 0)
    try:
        conn = get_db()
        rows = conn.execute(load_query("get_dictionary"), (lang_id,)).fetchall()
        conn.close()
        lang_dict = {row["Id"]: row["Description"] for row in rows}
    except Exception:
        lang_dict = {}
    return dict(lang_dict=lang_dict, current_lang=lang_id)


# ── User Guard ──────────────────────────────────────────────────────────

@app.before_request
def require_user_selection():
    """Redirect to user-login if no user has been selected yet."""
    if not request.endpoint or request.endpoint in ("user_login", "set_user", "static") or request.endpoint.startswith("admin."):
        return
    if "user_id" not in session:
        return redirect(url_for("user_login"))

# ── Environment Guard ──────────────────────────────────────────────────────────

@app.before_request
def require_env_selection():
    """Redirect to env-login if no environment has been selected yet."""
    if not request.endpoint or request.endpoint in ("user_login", "set_user", "env_login", "set_env", "disconnect", "static") or request.endpoint.startswith("admin."):
        return
    if "env" not in session:
        return redirect(url_for("env_login"))


# ── Authentication Routes ───────────────────────────────────────────────

@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("user_login"))
    if "env" not in session:
        return redirect(url_for("env_login"))
    return redirect(url_for("dashboard"))


@app.route("/user-login")
def user_login():
    try:
        conn = get_db()
        users = conn.execute("SELECT * FROM BOA.ZZZ.[User] ORDER BY username").fetchall()
        conn.close()
    except RuntimeError as exc:
        flash(str(exc), "error")
        users = []
    return render_template("user_login.html", users=users)


@app.route("/set-user", methods=["POST"])
def set_user():
    user_id = request.form.get("user_id")
    if not user_id:
        return redirect(url_for("user_login"))

    try:
        conn = get_db()
        user = conn.execute("SELECT * FROM BOA.ZZZ.[User] WHERE id = ?", (user_id,)).fetchone()
        conn.close()
    except RuntimeError:
        return redirect(url_for("user_login"))

    if user:
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        try:
            session["surname"] = user["surname"] or ""
            session["lang"] = user["default_language"] if user["default_language"] is not None else 0
            session["theme"] = user["default_theme"] or "dark" # Use DB default
        except Exception:
            # Fallback if columns don't exist during transition
            session["surname"] = ""
            session["lang"] = 0
            session["theme"] = "dark"
            
        return redirect(url_for("env_login"))
    return redirect(url_for("user_login"))

@app.route("/env-login")
def env_login():
    return render_template("env_login.html")


@app.route("/set-env", methods=["POST"])
def set_env():
    env = request.form.get("env", "local")
    if env not in ("local", "prod"):
        env = "local"

    if env == "prod":
        # Try the connection before committing to PROD to surface errors early
        try:
            conn = _get_db_prod()
            conn.close()
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("env_login"))
    else:
        # Validate LOCAL connection on selection too
        try:
            conn = _get_db_local()
            conn.close()
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("env_login"))

    session["env"] = env
    return redirect(url_for("dashboard"))


@app.route("/disconnect")
def disconnect():
    session.pop("env", None)
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("surname", None)
    session.pop("lang", None)
    session.pop("theme", None)
    return redirect(url_for("user_login"))


# ── Language ───────────────────────────────────────────────────────────────────

@app.route("/set_language/<int:lang_id>")
def set_language(lang_id):
    if lang_id in (0, 1):
        session["lang"] = lang_id
        user_id = session.get("user_id")
        if user_id:
            conn = get_db()
            conn.execute("UPDATE BOA.ZZZ.[User] SET default_language = ? WHERE id = ?", (lang_id, user_id))
            conn.commit()
            conn.close()
    return redirect(request.referrer or url_for("dashboard"))

@app.route("/set_theme/<theme>")
def set_theme(theme):
    if theme in ("light", "dark"):
        session["theme"] = theme
        user_id = session.get("user_id")
        if user_id:
            conn = get_db()
            conn.execute("UPDATE BOA.ZZZ.[User] SET default_theme = ? WHERE id = ?", (theme, user_id))
            conn.commit()
            conn.close()
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
        active_env   = session.get("env", "local"),
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
    items, prereq_map, subitems_map = _load_backlog(conn, "deal", deal_id)
    conn.close()
    return render_template("deal_detail.html", deal=deal, status_map=status_map,
                           deal_type_map=deal_type_map, fec_map=fec_map,
                           sector_map=sector_map, items=items, prereq_map=prereq_map, subitems_map=subitems_map)


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
    # Recalculate KR
    deal_id = conn.execute("SELECT MAX(id) AS id FROM BOA.ZZZ.CustomerDeals").fetchone()["id"]
    pid = conn.execute("SELECT ProductID FROM BOA.ZZZ.CustomerDeals WHERE id=?", (deal_id,)).fetchone()["ProductID"]
    _recalc_kr(conn, pid)
    conn.close()
    return redirect(url_for("customer_list"))


@app.route("/deals/edit/<int:deal_id>", methods=["GET", "POST"])
def edit_deal(deal_id):
    conn = get_db()
    if request.method == "POST":
        old_pid = conn.execute("SELECT ProductID FROM BOA.ZZZ.CustomerDeals WHERE id=?", (deal_id,)).fetchone()["ProductID"]
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
        new_pid = conn.execute("SELECT ProductID FROM BOA.ZZZ.CustomerDeals WHERE id=?", (deal_id,)).fetchone()["ProductID"]
        _recalc_kr(conn, old_pid)
        if new_pid != old_pid:
            _recalc_kr(conn, new_pid)
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
    pid = conn.execute("SELECT ProductID FROM BOA.ZZZ.CustomerDeals WHERE id=?", (deal_id,)).fetchone()["ProductID"]
    conn.execute(load_query("deal_delete"), (deal_id,))
    conn.commit()
    _recalc_kr(conn, pid)
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
    conn         = get_db()
    sector_map   = get_param_map("Sector", conn)
    customers    = conn.execute(load_query("mgmt_list_customers")).fetchall()
    stakeholders = conn.execute(
        "SELECT * FROM BOA.ZZZ.Stakeholder WHERE IsActive=1 ORDER BY FullName"
    ).fetchall()
    conn.close()
    return render_template("management.html", customers=customers, sector_map=sector_map,
                           stakeholders=stakeholders)


# ── Stakeholder CRUD ───────────────────────────────────────────────────────────

@app.route("/api/stakeholders", methods=["POST"])
def api_stakeholder_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.Stakeholder (FullName,Organization,Department,Email) VALUES (?,?,?,?)",
        (data.get("full_name", ""), data.get("organization", ""),
         data.get("department", ""), data.get("email", ""))
    )
    conn.commit()
    sid = conn.execute("SELECT MAX(StakeholderID) AS id FROM BOA.ZZZ.Stakeholder").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "stakeholder_id": sid})


@app.route("/api/stakeholders/<int:sid>", methods=["PATCH"])
def api_stakeholder_update(sid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "UPDATE BOA.ZZZ.Stakeholder SET FullName=?,Organization=?,Department=?,Email=? WHERE StakeholderID=?",
        (data.get("full_name"), data.get("organization"), data.get("department"), data.get("email"), sid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/stakeholders/<int:sid>", methods=["DELETE"])
def api_stakeholder_delete(sid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Stakeholder SET IsActive=0 WHERE StakeholderID=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/customer/lookup/<int:account_number>")
def lookup_customer(account_number):
    """Fetch a customer from BOADWH.CUS.Customer on SRVDNZ and check local tracking status.
    Always uses the PROD SQL Server connection (the Fetch button is disabled in TEST via HTML).
    Returns distinct JSON flags so the frontend can show actionable error messages.
    """
    try:
        conn_real = _get_db_prod()  # always hit PROD regardless of session env
        customer = conn_real.execute(load_query("prod_lookup_customer"), (account_number,)).fetchone()
        conn_real.close()

        if customer is None:
            return jsonify({"found": False})

        # Check if already tracked in local SQLite
        conn_local = get_db()
        already = conn_local.execute(
            "SELECT IsStructured FROM BOA.ZZZ.Customer WHERE Customerid = ?", (account_number,)
        ).fetchone()
        conn_local.close()

        return jsonify({
            "found": True,
            "Customerid": customer.get("Customerid", account_number),
            "CustomerName": customer.get("CustomerName", ""),
            "sector": customer.get("sector", "") or "",
            "branch": customer.get("branch", "") or "",
            "region": customer.get("region", "") or "",
            "value_segment": customer.get("value_segment", "") or "",
            "portfolio_manager": customer.get("portfolio_manager", "") or "",
            "customer_class": customer.get("CustomerClassName", "") or "",
            "IsStructured": 1 if already and already["IsStructured"] else 0
        })

    except RuntimeError as e:
        # Connection problem: pyodbc missing, no ODBC driver, SRVDNZ unreachable
        msg = str(e)
        print(f"[lookup_customer] connection error: {msg}")
        return jsonify({"found": False, "connection_error": True, "error": msg})
    except Exception as e:
        # SQL execution error (permissions, bad query, etc.)
        msg = str(e)
        print(f"[lookup_customer] query error: {msg}")
        return jsonify({"found": False, "query_error": True, "error": msg})


@app.route("/management/customer/add", methods=["POST"])
def add_customer():
    customer_id = int(request.form["Customerid"])
    env = session.get("env", "local") if has_request_context() else "local"
    
    if env == "prod":
        conn_real = get_customer_db()
        customer = conn_real.execute(load_query("real_customer_sync"), (customer_id,)).fetchone()
        conn_real.close()
        
        if customer:
            conn_local = get_db()
            conn_local.execute(load_query("customer_upsert"), (
                customer.get("Customerid", customer_id),
                customer.get("CustomerName", ""),
                customer.get("TotalLimit", 0),
                customer.get("credit_limit_currency", "TRY"),
                customer.get("foreign_trade_volume", 1),
                customer.get("memzuc_151_volume", 1),
                customer.get("memzuc_152_volume", 1),
                customer.get("value_segment", ""),
                customer.get("branch", ""),
                customer.get("region", ""),
                customer.get("portfolio_manager", ""),
                customer.get("CustomerClassName", "")
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
    customers = conn_local.execute("SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer WHERE IsStructured = 1").fetchall()
    conn_local.close()
    
    return jsonify({
        "success": True,
        "customers": [{"id": c["Customerid"], "name": c["CustomerName"]} for c in customers]
    })

@app.route("/management/api/sync/batch", methods=["POST"])
def sync_batch():
    env = session.get("env", "local") if has_request_context() else "local"
    data = request.get_json()
    cids = data.get("customer_ids", [])

    if not cids:
        return jsonify({"success": False, "error": "No customers to sync."})

    # TEST environment — clearly blocked, no fake data
    if env != "prod":
        return jsonify({
            "success": False,
            "env_error": True,
            "error": "Update is only available in PROD environment. Switch to PROD to sync real customer data."
        })

    # PROD: connect to SRVDNZ > BOA and run batch sync against BOADWH tables
    try:
        query_text = load_query("real_batch_customer_sync")
        # Count how many times {ids} appears BEFORE replacing (each becomes N ?-marks)
        ids_occurrences = query_text.count("{ids}")
        placeholders = ",".join("?" for _ in cids)
        query_text = query_text.replace("{ids}", placeholders)

        # The batch query uses multi-statement (SET NOCOUNT ON + temp tables).
        # It needs autocommit=True so temp table drops/creates don't conflict with a transaction.
        conn_real = _get_db_prod_autocommit()
        # Pass cids once per {ids} occurrence so param count equals marker count
        params = tuple(cids) * ids_occurrences
        results = conn_real.execute(query_text, params).fetchall()
        conn_real.close()
    except RuntimeError as e:
        return jsonify({"success": False, "connection_error": True, "error": str(e)})
    except Exception as e:
        return jsonify({"success": False, "query_error": True, "error": str(e)})

    if results:
        conn_local = get_db()
        for customer in results:
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
                    portfolio_manager = ?,
                    CustomerClassName = ?,
                    sector = ?
                WHERE Customerid = ?
            """, (
                customer.get("CustomerName", ""),
                customer.get("TotalLimit", 0),
                customer.get("credit_limit_currency", "TRY"),
                customer.get("foreign_trade_volume", 1),
                customer.get("memzuc_151_volume", 1),
                customer.get("memzuc_152_volume", 1),
                customer.get("value_segment", ""),
                customer.get("branch", ""),
                customer.get("region", ""),
                customer.get("portfolio_manager", ""),
                customer.get("CustomerClassName", ""),
                customer.get("sector", ""),
                customer.get("Customerid", customer.get("CustomerID", 0)),
            ))
        conn_local.commit()
        conn_local.close()
        return jsonify({"success": True, "count": len(results)})

    return jsonify({"success": False, "error": "No matching customers found on SRVDNZ (BOADWH). Verify account numbers are correct."})


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
    
    # Financial items processing
    fin_defs = conn.execute("SELECT * FROM BOA.ZZZ.FinancialItemDefinition").fetchall()
    allotments = conn.execute("SELECT * FROM BOA.ZZZ.AllotmentFinancialItems WHERE AllotmentMainId = ? ORDER BY PeriodId", (customer_id,)).fetchall()
    conn.close()

    total_deal_size = sum((d["deal_size"] or 0) for d in deals)

    # Build Financial Tree
    fin_map = {}
    for row in fin_defs:
        d = dict(row)
        # ParentId may be stored as the string 'NULL' instead of Python None — normalize it
        pid = d["ParentId"]
        if pid == 'NULL' or pid == '' or pid == 0:
            d["ParentId"] = None
        else:
            try:
                d["ParentId"] = int(pid)
            except (TypeError, ValueError):
                d["ParentId"] = None
        fin_map[d["FinancialItemDefinitionId"]] = d

    periods = sorted(list(set([a["PeriodId"] for a in allotments])))
    
    for f in fin_map.values():
        f["children"] = []
        f["amounts"] = {p: 0 for p in periods}
        
    for f in fin_map.values():
        pid = f["ParentId"]
        if pid and pid in fin_map:
            fin_map[pid]["children"].append(f)
            
    for a in allotments:
        fid = a["FinancialItemDefinitionId"]
        if fid in fin_map:
            fin_map[fid]["amounts"][a["PeriodId"]] += (a["OriginalValue"] or 0)

    def compute_values(node):
        for child in node["children"]:
            compute_values(child)
            for p in periods:
                node["amounts"][p] += child["amounts"][p]

    roots = [n for n in fin_map.values() if not n["ParentId"]]
    for r in roots:
        compute_values(r)
        
    ordered_fin_nodes = []
    def traverse(node, depth):
        # Determine total value to hide completely empty zeroed branches if necessary, but keep all for accuracy
        node_copy = {
            "id": node["FinancialItemDefinitionId"],
            "code": node["Code"],
            "parent_id": node["ParentId"],
            "name": node["NameInEnglish"] or node["Name"],
            "depth": depth,
            "amounts": node["amounts"],
            "has_children": len(node["children"]) > 0
        }
        ordered_fin_nodes.append(node_copy)
        # Sort children safely by putting strings into comparable format, simple string comparison works for codes
        for child in sorted(node["children"], key=lambda x: str(x["Code"])):
            traverse(child, depth + 1)
            
    for r in sorted(roots, key=lambda x: str(x["Code"])):
        traverse(r, 0)
        
    # Prepare Chart Data for Total Assets
    # In Turkish CoA, Assets are 1 (Current) and 2 (Non-Current) or sum thereof
    chart_periods = [f"Period {p}" for p in periods]
    asset_data = []
    # Try to find nodes '1' and '2' explicitly and sum them, or fallback to simple sum of all active leaves.
    node_1 = next((n for n in fin_map.values() if str(n["Code"]) == "1"), None)
    node_2 = next((n for n in fin_map.values() if str(n["Code"]) == "2"), None)
    
    for p in periods:
        val = 0
        if node_1: val += node_1["amounts"].get(p, 0)
        if node_2: val += node_2["amounts"].get(p, 0)
        if not node_1 and not node_2:
            val = sum(n["amounts"][p] for n in fin_map.values() if n["IsLeaf"] and (str(n["Code"]).startswith("1") or str(n["Code"]).startswith("2")))
        asset_data.append(val)

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
        fin_nodes       = ordered_fin_nodes,
        periods         = periods,
        chart_periods   = chart_periods,
        chart_asset_data= asset_data
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
    sector_map  = get_param_map("Sector", conn)
    sector_desc = sector_map.get(str(customer["sector"] or ""), {}).get("description", customer["sector"])

    same_sector_count = conn.execute(
        "SELECT COUNT(*) as c FROM Customer WHERE sector = ?",
        (customer["sector"],)
    ).fetchone()["c"]

    customer_data = {
        "customer": dict(customer),
        "deals": [dict(d) for d in deals],
        "sector_desc": sector_desc,
        "same_sector_count": same_sector_count
    }

    try:
        from agent_orchestrator import AnalysisOrchestrator
        target_lang = "Turkish" if lang_id == 1 else "English"
        orchestrator = AnalysisOrchestrator(BASE_DIR, language=target_lang)
        result = orchestrator.run(customer_data)
        analysis_text = result.get("final", "ERROR: Multi-Agent generation failed.")
    except Exception as e:
        analysis_text = f"Ollama Error: {str(e)[:50]}"

    analysis_text = analysis_text[:1000]
    conn.execute(load_query("analysis_insert"), (customer_id, analysis_text, lang_id))
    conn.commit()
    latest = conn.execute(load_query("analysis_latest"), (customer_id, lang_id)).fetchone()
    conn.close()
    return {"status": "success", "analysis": latest["analysis_text"], "created_at": to_tr_time(latest["created_at"])}


# ── Multi-Agent Streaming Analysis ─────────────────────────────────────────────────────

@app.route("/api/analyze/<int:customer_id>")
def analyze_stream(customer_id):
    """SSE endpoint: runs the 3-stage orchestrator and streams events to the browser."""
    conn = get_db()
    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return jsonify({"error": "Customer not found"}), 404

    deals      = conn.execute(load_query("analysis_get_deals"), (customer_id,)).fetchall()
    lang_id    = session.get("lang", 0)
    sector_map = get_param_map("Sector", conn)
    sector_desc = sector_map.get(str(customer["sector"] or ""), {}).get("description", customer["sector"])
    same_sector = conn.execute(load_query("overview_same_sector"), (customer["sector"],)).fetchone()["cnt"]

    customer_data = {
        "customer":         dict(customer),
        "deals":            [dict(d) for d in deals],
        "sector_desc":      sector_desc,
        "same_sector_count": same_sector,
    }
    conn.close()

    target_lang = "Turkish" if session.get("lang") == 1 else "English"
    orchestrator = AnalysisOrchestrator(BASE_DIR, language=target_lang)

    def generate():
        nonlocal_holder = [None]   # list trick avoids nonlocal scoping issue
        for event_str in orchestrator.run_stream(customer_data):
            yield event_str
            # Capture the final report from the done event
            if event_str.startswith("event: done"):
                import json as _json
                data_line = [l for l in event_str.splitlines() if l.startswith("data: ")]
                if data_line:
                    payload = _json.loads(data_line[0][6:])
                    nonlocal_holder[0] = payload.get("final", "")

        # Persist to DB after streaming completes
        final_text = nonlocal_holder[0]
        if final_text:
            with get_db() as save_conn:
                save_conn.execute(load_query("analysis_insert"), (customer_id, final_text[:1000], lang_id))
                save_conn.commit()

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":  "no-cache",
            "X-Accel-Buffering": "no",
        },
    )



@app.route("/api/agent/chat", methods=["POST"])
def api_agent_chat():
    """
    Data Agent HTTP endpoint — thin controller.
    All business logic lives in data_agent_orchestrator.process_agent_turn().
    """
    body        = request.get_json(silent=True) or {}
    author      = session.get("username", "Agent")

    agent_state = session.get("agent_state", {})

    conn = get_db()
    try:
        new_state, response = process_agent_turn(
            agent_state, body, conn, BASE_DIR, author
        )
    finally:
        conn.close()

    session["agent_state"] = new_state
    session.modified = True
    return jsonify(response)


@app.route("/api/agent/reset", methods=["POST"])
def api_agent_reset():
    """Reset the agent conversation state."""
    session.pop("agent_state", None)
    return jsonify({"status": "ok"})



# ── Comments ───────────────────────────────────────────────────────────────────

@app.route("/overview/<int:customer_id>/comment", methods=["POST"])
def add_comment(customer_id):
    author  = session.get("username", "System")
    content = request.form.get("content", "").strip()
    if author and content:
        conn = get_db()
        conn.execute(load_query("comment_insert"), (customer_id, author, content))
        conn.commit()
        conn.close()
    return redirect(url_for("overview_detail", customer_id=customer_id))


# ── Blueprint Registration ───────────────────────────────────────────────────────────
from admin.admin_bp import admin_bp  # noqa: E402
app.register_blueprint(admin_bp)

# ── Entry Point ────────────────────────────────────────────────────────────────

def _col_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='ZZZ' AND TABLE_NAME=? AND COLUMN_NAME=?",
        (table, column)
    ).fetchone()
    return row and int(row["cnt"]) > 0


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA='ZZZ' AND TABLE_NAME=?",
        (table,)
    ).fetchone()
    return row and int(row["cnt"]) > 0


def _ensure_isactive_columns():
    """Idempotently add IsActive to CustomerDeals and Comment."""
    try:
        conn = get_db()
        for table in ("CustomerDeals", "Comment"):
            if not _col_exists(conn, table, "IsActive"):
                conn.execute(f"ALTER TABLE BOA.ZZZ.{table} ADD IsActive TINYINT NOT NULL DEFAULT 1")
                conn.commit()
                print(f"[startup] IsActive column added to BOA.ZZZ.{table}")
            else:
                print(f"[startup] IsActive already present on BOA.ZZZ.{table} — skipping")
        conn.close()
    except Exception as e:
        print(f"[startup] IsActive migration warning (non-fatal): {e}")


def _run_platform_migrations():
    """
    Idempotently create all new platform tables (Products, OKRs, Projects, Backlog).
    Safe to call on every startup.
    """
    conn = get_db()
    try:
        # 510xxxx — Stakeholders
        if not _table_exists(conn, "Stakeholder"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.Stakeholder (
                    StakeholderID INT IDENTITY(5100001,1) PRIMARY KEY,
                    FullName      NVARCHAR(200) NOT NULL,
                    Organization  NVARCHAR(200),
                    Department    NVARCHAR(200),
                    Email         NVARCHAR(200),
                    IsActive      TINYINT NOT NULL DEFAULT 1,
                    CreatedAt     DATETIME NOT NULL DEFAULT GETDATE()
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.Stakeholder")
        else:
            print("[startup] Stakeholder exists — skipping")

        # 110xxxx — Product
        if not _table_exists(conn, "Product"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.Product (
                    ProductID           INT IDENTITY(1100001,1) PRIMARY KEY,
                    ProductCode         NVARCHAR(50)  NOT NULL,
                    ProductName         NVARCHAR(200) NOT NULL,
                    ProductType         NVARCHAR(100),
                    IslamicContractType NVARCHAR(100),
                    PartnerInstitution  NVARCHAR(200),
                    DefaultCurrencyID   INT,
                    Description         NVARCHAR(MAX),
                    IsActive            TINYINT NOT NULL DEFAULT 1,
                    CreatedAt           DATETIME NOT NULL DEFAULT GETDATE(),
                    UpdatedAt           DATETIME
                )""")
            conn.execute(
                "INSERT INTO BOA.ZZZ.Product (ProductCode,ProductName,ProductType,Description) "
                "VALUES ('UNCLASSIFIED','Unclassified','Legacy','Auto-created for pre-product deals')"
            )
            conn.commit()
            print("[startup] Created BOA.ZZZ.Product + seeded Unclassified (ID 1100001)")
        else:
            print("[startup] Product exists — skipping")

        # 111xxxx — ProductField
        if not _table_exists(conn, "ProductField"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.ProductField (
                    FieldID      INT IDENTITY(1110001,1) PRIMARY KEY,
                    ProductID    INT NOT NULL,
                    FieldName    NVARCHAR(100) NOT NULL,
                    FieldType    NVARCHAR(20)  NOT NULL DEFAULT 'text',
                    DefaultValue NVARCHAR(200),
                    IsRequired   TINYINT NOT NULL DEFAULT 0,
                    IsActive     TINYINT NOT NULL DEFAULT 1,
                    FOREIGN KEY (ProductID) REFERENCES BOA.ZZZ.Product(ProductID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.ProductField")
        else:
            print("[startup] ProductField exists — skipping")

        # 310xxxx — Objective
        if not _table_exists(conn, "Objective"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.Objective (
                    ObjectiveID INT IDENTITY(3100001,1) PRIMARY KEY,
                    Title       NVARCHAR(300) NOT NULL,
                    Description NVARCHAR(MAX),
                    Period      NVARCHAR(50),
                    Owner       NVARCHAR(100),
                    IsActive    TINYINT NOT NULL DEFAULT 1,
                    CreatedAt   DATETIME NOT NULL DEFAULT GETDATE()
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.Objective")
        else:
            print("[startup] Objective exists — skipping")

        # 311xxxx — KeyResult
        if not _table_exists(conn, "KeyResult"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.KeyResult (
                    KRID          INT IDENTITY(3110001,1) PRIMARY KEY,
                    ObjectiveID   INT NOT NULL,
                    Title         NVARCHAR(300) NOT NULL,
                    TargetValue   DECIMAL(18,2) NOT NULL DEFAULT 0,
                    AchievedValue DECIMAL(18,2) NOT NULL DEFAULT 0,
                    PipelineValue DECIMAL(18,2) NOT NULL DEFAULT 0,
                    Unit          NVARCHAR(50),
                    CalcMethod    NVARCHAR(20)  NOT NULL DEFAULT 'count',
                    IsActive      TINYINT NOT NULL DEFAULT 1,
                    FOREIGN KEY (ObjectiveID) REFERENCES BOA.ZZZ.Objective(ObjectiveID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.KeyResult")
        else:
            print("[startup] KeyResult exists — skipping")

        # 312xxxx — OKRProductLink
        if not _table_exists(conn, "OKRProductLink"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.OKRProductLink (
                    LinkID    INT IDENTITY(3120001,1) PRIMARY KEY,
                    KRID      INT NOT NULL,
                    ProductID INT NOT NULL,
                    IsActive  TINYINT NOT NULL DEFAULT 1,
                    FOREIGN KEY (KRID)      REFERENCES BOA.ZZZ.KeyResult(KRID),
                    FOREIGN KEY (ProductID) REFERENCES BOA.ZZZ.Product(ProductID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.OKRProductLink")
        else:
            print("[startup] OKRProductLink exists — skipping")

        # 320xxxx — Project
        if not _table_exists(conn, "Project"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.Project (
                    ProjectID   INT IDENTITY(3200001,1) PRIMARY KEY,
                    ProjectName NVARCHAR(300) NOT NULL,
                    Description NVARCHAR(MAX),
                    Status      NVARCHAR(50) NOT NULL DEFAULT 'Planning',
                    Owner       NVARCHAR(100),
                    StartDate   DATE,
                    Deadline    DATE,
                    ObjectiveID INT,
                    IsActive    TINYINT NOT NULL DEFAULT 1,
                    CreatedAt   DATETIME NOT NULL DEFAULT GETDATE(),
                    UpdatedAt   DATETIME,
                    FOREIGN KEY (ObjectiveID) REFERENCES BOA.ZZZ.Objective(ObjectiveID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.Project")
        else:
            print("[startup] Project exists — skipping")

        # 410xxxx — WorkItem
        if not _table_exists(conn, "WorkItem"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.WorkItem (
                    ItemID      INT IDENTITY(4100001,1) PRIMARY KEY,
                    ParentType  NVARCHAR(10) NOT NULL,
                    ParentID    INT NOT NULL,
                    Title       NVARCHAR(300) NOT NULL,
                    Description NVARCHAR(MAX),
                    Status      NVARCHAR(20) NOT NULL DEFAULT 'not_started',
                    Deadline    DATE,
                    SortOrder   INT NOT NULL DEFAULT 0,
                    IsActive    TINYINT NOT NULL DEFAULT 1,
                    CreatedAt   DATETIME NOT NULL DEFAULT GETDATE(),
                    UpdatedAt   DATETIME
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItem")
        else:
            print("[startup] WorkItem exists — skipping")

        # 411xxxx — WorkSubItem
        if not _table_exists(conn, "WorkSubItem"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.WorkSubItem (
                    SubItemID    INT IDENTITY(4110001,1) PRIMARY KEY,
                    ParentItemID INT NOT NULL,
                    Title        NVARCHAR(300) NOT NULL,
                    Status       NVARCHAR(20) NOT NULL DEFAULT 'not_started',
                    Deadline     DATE,
                    SortOrder    INT NOT NULL DEFAULT 0,
                    IsActive     TINYINT NOT NULL DEFAULT 1,
                    CreatedAt    DATETIME NOT NULL DEFAULT GETDATE(),
                    FOREIGN KEY (ParentItemID) REFERENCES BOA.ZZZ.WorkItem(ItemID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkSubItem")
        else:
            print("[startup] WorkSubItem exists — skipping")

        # 412xxxx — WorkItemPrerequisite
        if not _table_exists(conn, "WorkItemPrerequisite"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.WorkItemPrerequisite (
                    LinkID         INT IDENTITY(4120001,1) PRIMARY KEY,
                    ItemID         INT NOT NULL,
                    RequiresItemID INT NOT NULL,
                    IsActive       TINYINT NOT NULL DEFAULT 1,
                    FOREIGN KEY (ItemID)         REFERENCES BOA.ZZZ.WorkItem(ItemID),
                    FOREIGN KEY (RequiresItemID) REFERENCES BOA.ZZZ.WorkItem(ItemID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItemPrerequisite")
        else:
            print("[startup] WorkItemPrerequisite exists — skipping")

        # 413xxxx — WorkItemAssignee
        if not _table_exists(conn, "WorkItemAssignee"):
            conn.execute("""
                CREATE TABLE BOA.ZZZ.WorkItemAssignee (
                    AssigneeID    INT IDENTITY(4130001,1) PRIMARY KEY,
                    ItemID        INT NOT NULL,
                    StakeholderID INT NOT NULL,
                    IsActive      TINYINT NOT NULL DEFAULT 1,
                    FOREIGN KEY (ItemID)        REFERENCES BOA.ZZZ.WorkItem(ItemID),
                    FOREIGN KEY (StakeholderID) REFERENCES BOA.ZZZ.Stakeholder(StakeholderID)
                )""")
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItemAssignee")
        else:
            print("[startup] WorkItemAssignee exists — skipping")

        # CustomerDeals.ProductID — add if missing
        if not _col_exists(conn, "CustomerDeals", "ProductID"):
            conn.execute(
                "ALTER TABLE BOA.ZZZ.CustomerDeals ADD ProductID INT NOT NULL DEFAULT 1100001"
            )
            conn.execute(
                "ALTER TABLE BOA.ZZZ.CustomerDeals ADD CONSTRAINT FK_Deal_Product "
                "FOREIGN KEY (ProductID) REFERENCES BOA.ZZZ.Product(ProductID)"
            )
            conn.commit()
            print("[startup] Added ProductID to CustomerDeals — legacy deals assigned to Unclassified")
        else:
            print("[startup] CustomerDeals.ProductID exists — skipping")

    except Exception as e:
        print(f"[startup] Platform migration error (non-fatal): {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()





# ── Products ─────────────────────────────────────────────────────────────────────────

@app.route("/products")
def products_list():
    conn = get_db()
    products = conn.execute(
        "SELECT p.*, "
        "  (SELECT COUNT(*) FROM BOA.ZZZ.CustomerDeals d WHERE d.ProductID=p.ProductID AND d.IsActive=1) AS deal_count "
        "FROM BOA.ZZZ.Product p WHERE p.IsActive=1 ORDER BY p.ProductName"
    ).fetchall()
    conn.close()
    return render_template("products.html", products=products)


@app.route("/products/<int:product_id>")
def product_detail(product_id):
    conn = get_db()
    product = conn.execute("SELECT * FROM BOA.ZZZ.Product WHERE ProductID=? AND IsActive=1", (product_id,)).fetchone()
    if not product:
        conn.close()
        return "Product not found", 404
    fields   = conn.execute("SELECT * FROM BOA.ZZZ.ProductField WHERE ProductID=? AND IsActive=1 ORDER BY FieldID", (product_id,)).fetchall()
    linked_krs = conn.execute(
        "SELECT kr.KRID, kr.Title AS KRTitle, o.Title AS ObjTitle "
        "FROM BOA.ZZZ.OKRProductLink lnk "
        "JOIN BOA.ZZZ.KeyResult kr ON lnk.KRID=kr.KRID "
        "JOIN BOA.ZZZ.Objective o ON kr.ObjectiveID=o.ObjectiveID "
        "WHERE lnk.ProductID=? AND lnk.IsActive=1", (product_id,)
    ).fetchall()
    deals = conn.execute(
        "SELECT d.id, c.CustomerName, d.deal_size, d.currency, d.status "
        "FROM BOA.ZZZ.CustomerDeals d JOIN BOA.ZZZ.Customer c ON d.customerid=c.Customerid "
        "WHERE d.ProductID=? AND d.IsActive=1 ORDER BY d.id DESC", (product_id,)
    ).fetchall()
    all_krs = conn.execute(
        "SELECT kr.KRID, kr.Title, o.Title AS ObjTitle FROM BOA.ZZZ.KeyResult kr "
        "JOIN BOA.ZZZ.Objective o ON kr.ObjectiveID=o.ObjectiveID WHERE kr.IsActive=1 ORDER BY o.Title, kr.Title"
    ).fetchall()
    conn.close()
    return render_template("product_detail.html", product=product, fields=fields, linked_krs=linked_krs, deals=deals, all_krs=all_krs)


@app.route("/api/products", methods=["POST"])
def api_product_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.Product (ProductCode,ProductName,ProductType,IslamicContractType,PartnerInstitution,Description) VALUES (?,?,?,?,?,?)",
        (data.get("code",""), data.get("name",""), data.get("type",""), data.get("islamic_contract",""), data.get("partner",""), data.get("description",""))
    )
    conn.commit()
    pid = conn.execute("SELECT MAX(ProductID) AS id FROM BOA.ZZZ.Product").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "product_id": pid})


@app.route("/api/products/<int:pid>", methods=["PATCH"])
def api_product_update(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "UPDATE BOA.ZZZ.Product SET ProductName=?,ProductType=?,IslamicContractType=?,PartnerInstitution=?,Description=?,UpdatedAt=GETDATE() WHERE ProductID=?",
        (data.get("name"), data.get("type"), data.get("islamic_contract"), data.get("partner"), data.get("description"), pid)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>", methods=["DELETE"])
def api_product_delete(pid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Product SET IsActive=0 WHERE ProductID=?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>/fields", methods=["POST"])
def api_product_field_create(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.ProductField (ProductID,FieldName,FieldType,DefaultValue,IsRequired) VALUES (?,?,?,?,?)",
        (pid, data.get("name",""), data.get("field_type","text"), data.get("default",""), 1 if data.get("required") else 0)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/products/fields/<int:fid>", methods=["DELETE"])
def api_product_field_delete(fid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.ProductField SET IsActive=0 WHERE FieldID=?", (fid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>/link-kr", methods=["POST"])
def api_product_link_kr(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if not conn.execute("SELECT LinkID FROM BOA.ZZZ.OKRProductLink WHERE KRID=? AND ProductID=? AND IsActive=1", (data.get("kr_id"), pid)).fetchone():
        conn.execute("INSERT INTO BOA.ZZZ.OKRProductLink (KRID,ProductID) VALUES (?,?)", (data.get("kr_id"), pid))
        conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/products/<int:pid>/unlink-kr/<int:krid>", methods=["DELETE"])
def api_product_unlink_kr(pid, krid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.OKRProductLink SET IsActive=0 WHERE ProductID=? AND KRID=?", (pid, krid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ── OKRs ─────────────────────────────────────────────────────────────────────────────

@app.route("/okrs")
def okrs_list():
    conn = get_db()
    objectives = conn.execute("SELECT * FROM BOA.ZZZ.Objective WHERE IsActive=1 ORDER BY Period DESC, ObjectiveID").fetchall()
    krs        = conn.execute("SELECT * FROM BOA.ZZZ.KeyResult WHERE IsActive=1 ORDER BY ObjectiveID, KRID").fetchall()
    conn.close()
    return render_template("okrs.html", objectives=objectives, krs=krs)


@app.route("/api/okrs/objectives", methods=["POST"])
def api_objective_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("INSERT INTO BOA.ZZZ.Objective (Title,Description,Period,Owner) VALUES (?,?,?,?)",
                 (data.get("title",""), data.get("description",""), data.get("period",""), session.get("username","")))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/okrs/objectives/<int:oid>", methods=["DELETE"])
def api_objective_delete(oid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Objective SET IsActive=0 WHERE ObjectiveID=?", (oid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/okrs/krs", methods=["POST"])
def api_kr_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("INSERT INTO BOA.ZZZ.KeyResult (ObjectiveID,Title,TargetValue,Unit,CalcMethod) VALUES (?,?,?,?,?)",
                 (data.get("objective_id"), data.get("title",""), float(data.get("target",0)), data.get("unit","deals"), data.get("calc_method","count")))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/okrs/krs/<int:krid>", methods=["DELETE"])
def api_kr_delete(krid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.KeyResult SET IsActive=0 WHERE KRID=?", (krid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/okrs/krs/<int:krid>/deals")
def api_kr_deals(krid):
    conn = get_db()
    deals = conn.execute("""
        SELECT d.id, c.CustomerName, d.contact_name, d.deal_size, d.status
        FROM BOA.ZZZ.CustomerDeals d
        JOIN BOA.ZZZ.Customer c ON d.customerid = c.Customerid
        WHERE d.IsActive = 1
        AND d.ProductID IN (
            SELECT ProductID FROM BOA.ZZZ.OKRProductLink WHERE KRID = ? AND IsActive = 1
        )
        AND d.status IN ('2', '3', '4')
        ORDER BY d.deal_size DESC
    """, (krid,)).fetchall()
    
    status_map = get_param_map("Status", conn)
    conn.close()
    
    results = []
    for d in deals:
        results.append({
            "id": d["id"],
            "company": d["CustomerName"],
            "contact": d["contact_name"],
            "size": d["deal_size"],
            "status": str(d["status"]),
            "status_label": status_map.get(str(d["status"]), {}).get("description", str(d["status"]))
        })
    return jsonify({"deals": results})


def _recalc_kr(conn, product_id):
    links = conn.execute(
        "SELECT lnk.KRID, kr.CalcMethod FROM BOA.ZZZ.OKRProductLink lnk "
        "JOIN BOA.ZZZ.KeyResult kr ON lnk.KRID=kr.KRID "
        "WHERE lnk.ProductID=? AND lnk.IsActive=1 AND kr.IsActive=1", (product_id,)
    ).fetchall()
    for link in links:
        krid, calc = link["KRID"], link["CalcMethod"]
        if calc == "count":
            achieved = conn.execute("SELECT COUNT(*) AS v FROM BOA.ZZZ.CustomerDeals WHERE ProductID=? AND IsActive=1 AND status=4", (product_id,)).fetchone()["v"]
            pipeline = conn.execute("SELECT COUNT(*) AS v FROM BOA.ZZZ.CustomerDeals WHERE ProductID=? AND IsActive=1 AND status IN (2,3)", (product_id,)).fetchone()["v"]
        elif calc == "sum_size":
            achieved = conn.execute("SELECT ISNULL(SUM(deal_size),0) AS v FROM BOA.ZZZ.CustomerDeals WHERE ProductID=? AND IsActive=1 AND status=4", (product_id,)).fetchone()["v"]
            pipeline = conn.execute("SELECT ISNULL(SUM(deal_size),0) AS v FROM BOA.ZZZ.CustomerDeals WHERE ProductID=? AND IsActive=1 AND status IN (2,3)", (product_id,)).fetchone()["v"]
        else:
            continue
        conn.execute("UPDATE BOA.ZZZ.KeyResult SET AchievedValue=?,PipelineValue=? WHERE KRID=?", (achieved, pipeline, krid))


# ── Projects ─────────────────────────────────────────────────────────────────────────

@app.route("/projects")
def projects_list():
    conn = get_db()
    projects = conn.execute(
        "SELECT p.*, o.Title AS ObjTitle, "
        "  (SELECT COUNT(*) FROM BOA.ZZZ.WorkItem w WHERE w.ParentType='project' AND w.ParentID=p.ProjectID AND w.IsActive=1) AS total_items,"
        "  (SELECT COUNT(*) FROM BOA.ZZZ.WorkItem w WHERE w.ParentType='project' AND w.ParentID=p.ProjectID AND w.IsActive=1 AND w.Status='done') AS done_items "
        "FROM BOA.ZZZ.Project p LEFT JOIN BOA.ZZZ.Objective o ON p.ObjectiveID=o.ObjectiveID "
        "WHERE p.IsActive=1 ORDER BY p.CreatedAt DESC"
    ).fetchall()
    objectives = conn.execute("SELECT ObjectiveID, Title FROM BOA.ZZZ.Objective WHERE IsActive=1 ORDER BY Title").fetchall()
    conn.close()
    return render_template("projects.html", projects=projects, objectives=objectives)


@app.route("/projects/<int:project_id>")
def project_detail(project_id):
    conn = get_db()
    project = conn.execute(
        "SELECT p.*, o.Title AS ObjTitle FROM BOA.ZZZ.Project p "
        "LEFT JOIN BOA.ZZZ.Objective o ON p.ObjectiveID=o.ObjectiveID "
        "WHERE p.ProjectID=? AND p.IsActive=1", (project_id,)
    ).fetchone()
    if not project:
        conn.close()
        return "Project not found", 404
    items, prereq_map, subitems_map = _load_backlog(conn, "project", project_id)
    stakeholders = conn.execute("SELECT StakeholderID, FullName, Organization FROM BOA.ZZZ.Stakeholder WHERE IsActive=1 ORDER BY FullName").fetchall()
    conn.close()
    return render_template("project_detail.html", project=project, items=items, prereq_map=prereq_map, subitems_map=subitems_map, stakeholders=stakeholders)


@app.route("/api/projects", methods=["POST"])
def api_project_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.Project (ProjectName,Description,Status,Owner,StartDate,Deadline,ObjectiveID) VALUES (?,?,?,?,?,?,?)",
        (data.get("name",""), data.get("description",""), data.get("status","Planning"),
         session.get("username",""), data.get("start_date") or None, data.get("deadline") or None, data.get("objective_id") or None)
    )
    conn.commit()
    pid = conn.execute("SELECT MAX(ProjectID) AS id FROM BOA.ZZZ.Project").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "project_id": pid})


@app.route("/api/projects/<int:pid>", methods=["PATCH"])
def api_project_update(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "UPDATE BOA.ZZZ.Project SET ProjectName=?,Description=?,Status=?,Deadline=?,ObjectiveID=?,UpdatedAt=GETDATE() WHERE ProjectID=?",
        (data.get("name"), data.get("description"), data.get("status"), data.get("deadline") or None, data.get("objective_id") or None, pid)
    )
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/projects/<int:pid>", methods=["DELETE"])
def api_project_delete(pid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Project SET IsActive=0 WHERE ProjectID=?", (pid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ── Work Items (shared) ───────────────────────────────────────────────────────────────

def _load_backlog(conn, parent_type, parent_id):
    items = conn.execute(
        "SELECT * FROM BOA.ZZZ.WorkItem WHERE ParentType=? AND ParentID=? AND IsActive=1 ORDER BY SortOrder, Deadline, ItemID",
        (parent_type, parent_id)
    ).fetchall()
    item_ids = [i["ItemID"] for i in items]
    prereq_map, subitems_map = {}, {}
    if item_ids:
        ph = ",".join("?" * len(item_ids))
        for p in conn.execute(f"SELECT ItemID,RequiresItemID FROM BOA.ZZZ.WorkItemPrerequisite WHERE ItemID IN ({ph}) AND IsActive=1", item_ids).fetchall():
            prereq_map.setdefault(p["ItemID"], []).append(p["RequiresItemID"])
        for s in conn.execute(f"SELECT * FROM BOA.ZZZ.WorkSubItem WHERE ParentItemID IN ({ph}) AND IsActive=1 ORDER BY SortOrder,SubItemID", item_ids).fetchall():
            subitems_map.setdefault(s["ParentItemID"], []).append(dict(s))
    return items, prereq_map, subitems_map


@app.route("/api/workitems", methods=["POST"])
def api_workitem_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.WorkItem (ParentType,ParentID,Title,Description,Deadline,SortOrder) VALUES (?,?,?,?,?,?)",
        (data.get("parent_type"), data.get("parent_id"), data.get("title",""), data.get("description",""), data.get("deadline") or None, data.get("sort_order",0))
    )
    conn.commit()
    iid = conn.execute("SELECT MAX(ItemID) AS id FROM BOA.ZZZ.WorkItem").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "item_id": iid})


@app.route("/api/workitems/<int:iid>", methods=["PATCH"])
def api_workitem_update(iid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkItem SET Title=?,Description=?,Status=?,Deadline=?,UpdatedAt=GETDATE() WHERE ItemID=?",
                 (data.get("title"), data.get("description"), data.get("status"), data.get("deadline") or None, iid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/workitems/<int:iid>/status", methods=["PATCH"])
def api_workitem_status(iid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkItem SET Status=?,UpdatedAt=GETDATE() WHERE ItemID=?", (data.get("status"), iid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/workitems/<int:iid>", methods=["DELETE"])
def api_workitem_delete(iid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkItem SET IsActive=0 WHERE ItemID=?", (iid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/workitems/<int:iid>/prerequisites", methods=["POST"])
def api_workitem_add_prereq(iid):
    data = request.get_json(silent=True) or {}
    req_id = data.get("requires_item_id")
    conn = get_db()
    if not conn.execute("SELECT LinkID FROM BOA.ZZZ.WorkItemPrerequisite WHERE ItemID=? AND RequiresItemID=? AND IsActive=1", (iid, req_id)).fetchone():
        conn.execute("INSERT INTO BOA.ZZZ.WorkItemPrerequisite (ItemID,RequiresItemID) VALUES (?,?)", (iid, req_id))
        conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/workitems/<int:iid>/prerequisites/<int:req_id>", methods=["DELETE"])
def api_workitem_remove_prereq(iid, req_id):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkItemPrerequisite SET IsActive=0 WHERE ItemID=? AND RequiresItemID=?", (iid, req_id))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/subitems", methods=["POST"])
def api_subitem_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("INSERT INTO BOA.ZZZ.WorkSubItem (ParentItemID,Title,Deadline,SortOrder) VALUES (?,?,?,?)",
                 (data.get("parent_item_id"), data.get("title",""), data.get("deadline") or None, data.get("sort_order",0)))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/subitems/<int:sid>/status", methods=["PATCH"])
def api_subitem_status(sid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkSubItem SET Status=? WHERE SubItemID=?", (data.get("status"), sid))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


@app.route("/api/subitems/<int:sid>", methods=["DELETE"])
def api_subitem_delete(sid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.WorkSubItem SET IsActive=0 WHERE SubItemID=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({"ok": True})


# ── Global Backlog ────────────────────────────────────────────────────────────────────

@app.route("/backlog")
def global_backlog():
    conn = get_db()
    items = conn.execute(
        "SELECT w.*, "
        "  CASE w.ParentType "
        "    WHEN 'project' THEN (SELECT ProjectName FROM BOA.ZZZ.Project WHERE ProjectID=w.ParentID) "
        "    WHEN 'deal' THEN (SELECT TOP 1 c.CustomerName + ' Deal #'+CAST(d.id AS NVARCHAR) "
        "                     FROM BOA.ZZZ.CustomerDeals d JOIN BOA.ZZZ.Customer c ON d.customerid=c.Customerid "
        "                     WHERE d.id=w.ParentID) "
        "  END AS ParentName, "
        "  (SELECT STRING_AGG(CAST(s.StakeholderID AS NVARCHAR), ',') "
        "   FROM BOA.ZZZ.WorkItemAssignee wa "
        "   JOIN BOA.ZZZ.Stakeholder s ON wa.StakeholderID = s.StakeholderID "
        "   WHERE wa.ItemID = w.ItemID) AS AssigneeIDs, "
        "  (SELECT STRING_AGG(s.FullName, ', ') "
        "   FROM BOA.ZZZ.WorkItemAssignee wa "
        "   JOIN BOA.ZZZ.Stakeholder s ON wa.StakeholderID = s.StakeholderID "
        "   WHERE wa.ItemID = w.ItemID) AS Assignees "
        "FROM BOA.ZZZ.WorkItem w WHERE w.IsActive=1 AND w.Status != 'done' "
        "ORDER BY w.Deadline ASC, w.SortOrder ASC, w.ItemID ASC"
    ).fetchall()
    stakeholders = conn.execute("SELECT StakeholderID, FullName FROM BOA.ZZZ.Stakeholder WHERE IsActive=1 ORDER BY FullName").fetchall()
    conn.close()
    from datetime import datetime as _dt
    return render_template("backlog.html", items=items, stakeholders=stakeholders, now=_dt.utcnow())


if __name__ == "__main__":
    _ensure_isactive_columns()
    _run_platform_migrations()
    app.run(debug=True, port=5000)
