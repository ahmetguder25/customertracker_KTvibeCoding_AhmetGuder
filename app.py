"""Flask application for Customer Tracking System."""
# ── Imports and Initialization ──
import os
import platform
import json
from datetime import datetime, timedelta
from flask import (Flask, render_template, request, redirect, url_for,
                   send_file, flash, jsonify, session, has_request_context,
                   Response, stream_with_context)
from werkzeug.utils import secure_filename
import io
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ── App Setup ─────────────────────────────────────────────────────────────────
# ── Global Configurations & Hooks ──
app = Flask(__name__)
app.secret_key = "customer-tracker-secret-key-2026"

from core.config import (
    BASE_DIR, QUERY_DIR, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, MAX_LOGO_SIZE,
    PRODUCT_DOCS_FOLDER, CUSTOMER_DOCS_FOLDER
)
from core.db import get_db, get_customer_db, DbConnection
from core.utils import load_query, to_tr_time, _fmt_dt, allowed_file, get_param_map

app.jinja_env.filters["tr_time"] = to_tr_time
app.jinja_env.filters["fmtdate"]     = lambda v: _fmt_dt(v, 10)
app.jinja_env.filters["fmtdatetime"] = lambda v: _fmt_dt(v, 16)


# ── Context Processors ─────────────────────────────────────────────────────────

@app.context_processor
def inject_lang_dict():
    """Inject lang_dict + current_lang into all templates."""
    if not has_request_context():
        return dict(lang_dict={}, current_lang=0)
    lang_id = session.get("lang", 2)
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
    if not request.endpoint or request.endpoint in ("auth.user_login", "auth.set_user", "static") or request.endpoint.startswith("admin."):
        return
    if "user_id" not in session:
        return redirect(url_for("auth.user_login"))

# ── Environment Guard ──────────────────────────────────────────────────────────

@app.before_request
def require_env_selection():
    """Redirect to env-login if no environment has been selected yet."""
    if not request.endpoint or request.endpoint in ("auth.user_login", "auth.set_user", "auth.env_login", "auth.set_env", "auth.disconnect", "static") or request.endpoint.startswith("admin."):
        return
    if "env" not in session:
        return redirect(url_for("auth.env_login"))

# ── Frame-mode redirect passthrough ───────────────────────────────────────────

@app.after_request
def preserve_frame_on_redirect(response):
    """If the request came from an iframe (_frame=1), keep it on redirects."""
    is_frame = request.args.get('_frame') == '1' or request.form.get('_frame') == '1'
    if is_frame and response.status_code in (301, 302, 303, 307, 308):
        loc = response.headers.get('Location', '')
        if loc and '_frame=1' not in loc:
            sep = '&' if '?' in loc else '?'
            response.headers['Location'] = loc + sep + '_frame=1'
    return response

# ── Authentication Routes ───────────────────────────────────────────────














# ── Blueprint Registration ───────────────────────────────────────────────────────────
from admin.admin_bp import admin_bp  # noqa: E402
from blueprints.auth import auth_bp
from blueprints.dashboard import dashboard_bp
from blueprints.syndications import syndications_bp
from blueprints.management import management_bp
from blueprints.overview import overview_bp
from blueprints.products import products_bp
from blueprints.okrs import okrs_bp
from blueprints.work_items import work_items_bp
from ai_apps.overviewai.analysis_routes import ai_analysis_bp
from ai_apps.chatbot1.chatbot_routes import chatbot_bp

app.register_blueprint(admin_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(syndications_bp)
app.register_blueprint(management_bp)
app.register_blueprint(overview_bp)
app.register_blueprint(products_bp)
app.register_blueprint(okrs_bp)
app.register_blueprint(work_items_bp)
app.register_blueprint(ai_analysis_bp)
app.register_blueprint(chatbot_bp)

# ── Entry Point ────────────────────────────────────────────────────────────────

# ── Database Utility Functions ──

def _col_exists(conn, table: str, column: str, schema: str = "ZZZ") -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA=? AND TABLE_NAME=? AND COLUMN_NAME=?",
        (schema, table, column)
    ).fetchone()
    return row and int(row["cnt"]) > 0


def _table_exists(conn, table: str, schema: str = "ZZZ") -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA=? AND TABLE_NAME=?",
        (schema, table)
    ).fetchone()
    return row and int(row["cnt"]) > 0


def _schema_exists(conn, schema: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=?",
        (schema,)
    ).fetchone()
    return row and int(row["cnt"]) > 0


# ── Schema Migrations ──

def _ensure_isactive_columns():
    """Idempotently add IsActive to CustomerDeals and Comment."""
    try:
        conn = get_db()
        for table in ("Comment",):
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
        if not _table_exists(conn, "Stakeholder"):
            conn.execute(load_query("schema/stakeholder"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.Stakeholder")

        if not _table_exists(conn, "Product", "COR"):
            conn.execute(load_query("schema/product"))
            conn.execute(load_query("schema/seed_product"))
            conn.commit()
            print("[startup] Created BOA.COR.Product + seeded")

        if not _table_exists(conn, "Objective"):
            conn.execute(load_query("schema/objective"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.Objective")

        if not _table_exists(conn, "KeyResult"):
            conn.execute(load_query("schema/keyresult"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.KeyResult")

        if not _table_exists(conn, "Project"):
            conn.execute(load_query("schema/project"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.Project")

        if not _table_exists(conn, "WorkItem"):
            conn.execute(load_query("schema/workitem"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItem")

        if not _table_exists(conn, "WorkSubItem"):
            conn.execute(load_query("schema/worksubitem"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkSubItem")

        if not _table_exists(conn, "WorkItemPrerequisite"):
            conn.execute(load_query("schema/workitemprereq"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItemPrerequisite")

        if not _table_exists(conn, "WorkItemAssignee"):
            conn.execute(load_query("schema/workitemassignee"))
            conn.commit()
            print("[startup] Created BOA.ZZZ.WorkItemAssignee")

        if not _table_exists(conn, "MainDeals", "STR"):
            conn.execute(load_query("schema/maindeals"))
            try:
                conn.execute("CREATE SCHEMA STR")
                conn.commit()
            except Exception:
                pass
            conn.execute(load_query("schema/syndication"))
            conn.execute(load_query("schema/syndicationbanks"))
            conn.commit()
            print("[startup] Created MainDeals, Syndications, SyndicationDetail tables")

    except Exception as e:
        print(f"[startup] Platform migration error (non-fatal): {e}")
        import traceback; traceback.print_exc()
    finally:
        conn.close()



def _ensure_customer_doc_schema():
    """Create BOA.COR.CustomerDocument and CUSTDOC parameters if not exist."""
    conn = get_db()
    try:
        conn.execute("SELECT 1 FROM BOA.COR.CustomerDocument").fetchone()
    except Exception:
        print("[startup] Creating BOA.COR.CustomerDocument table...")
        conn.execute(load_query("schema/customerdoc"))
        conn.commit()

    params_count = conn.execute("SELECT COUNT(*) as c FROM BOA.COR.Parameter WHERE ParamType='CUSTDOC'").fetchone()["c"]
    if params_count == 0:
        print("[startup] Inserting default CUSTDOC parameters...")
        conn.execute(load_query("schema/seed_custdoc"))
        conn.commit()
    conn.close()





def _ensure_wit_schema():
    """
    Idempotently create the WIT schema and migrate WorkItem tables from ZZZ.
    """
    try:
        conn = get_db()

        # Create WIT schema if it does not exist
        if not _schema_exists(conn, "WIT"):
            conn.execute("CREATE SCHEMA WIT")
            conn.commit()
            print("[startup] Created schema BOA.WIT")

        # 1. Migrate WorkItem
        if not _table_exists(conn, "WorkItem", "WIT"):
            conn.execute(load_query("schema/wit_workitem"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkItem")
            if _table_exists(conn, "WorkItem", "ZZZ"):
                conn.execute(load_query("schema/copy_wit_workitem"))
                conn.commit()
                print("[startup] Copied rows from BOA.ZZZ.WorkItem → BOA.WIT.WorkItem")
        else:
            if _table_exists(conn, "WorkItem", "ZZZ"):
                missing = conn.execute(load_query("schema/count_missing_wit_workitem")).fetchone()
                if missing and int(missing["cnt"]) > 0:
                    conn.execute(load_query("schema/catchup_wit_workitem"))
                    conn.commit()

        # 2. Migrate WorkSubItem
        if not _table_exists(conn, "WorkSubItem", "WIT"):
            conn.execute(load_query("schema/wit_worksubitem"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkSubItem")
            if _table_exists(conn, "WorkSubItem", "ZZZ"):
                conn.execute(load_query("schema/copy_wit_worksubitem"))
                conn.commit()
        else:
            if _table_exists(conn, "WorkSubItem", "ZZZ"):
                missing = conn.execute(load_query("schema/count_missing_wit_worksubitem")).fetchone()
                if missing and int(missing["cnt"]) > 0:
                    conn.execute(load_query("schema/catchup_wit_worksubitem"))
                    conn.commit()

        # 3. Migrate WorkItemPrerequisite
        if not _table_exists(conn, "WorkItemPrerequisite", "WIT"):
            conn.execute(load_query("schema/wit_workitemprereq"))
            conn.commit()
            if _table_exists(conn, "WorkItemPrerequisite", "ZZZ"):
                conn.execute(load_query("schema/copy_wit_workitemprereq"))
                conn.commit()

        # 4. Migrate WorkItemAssignee
        if not _table_exists(conn, "WorkItemAssignee", "WIT"):
            has_user_col = _col_exists(conn, "WorkItemAssignee", "UserID", "ZZZ")
            conn.execute(load_query("schema/wit_workitemassignee"))
            conn.commit()
            if _table_exists(conn, "WorkItemAssignee", "ZZZ"):
                if has_user_col:
                    conn.execute(load_query("schema/copy_wit_workitemassignee"))
                else:
                    conn.execute(load_query("schema/copy_wit_workitemassignee_legacy"))
                conn.commit()

        # 5. Deal Remap and Orphan Deactivate
        result = conn.execute(load_query("schema/check_wit_deal")).fetchone()
        if result and int(result["cnt"]) > 0:
            conn.execute(load_query("schema/wit_deal_remap"))
            conn.commit()

        conn.execute(load_query("schema/wit_orphan_deactivate"))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[startup] WIT schema migration warning (non-fatal): {e}")
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    _ensure_isactive_columns()
    _run_platform_migrations()
    _ensure_wit_schema()
    _ensure_customer_doc_schema()
    app.run(debug=True, port=5000)
