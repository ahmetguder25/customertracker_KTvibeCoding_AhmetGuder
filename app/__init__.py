"""Flask application for Customer Tracking System."""
import os
import time
import json
from flask import Flask, request, redirect, url_for, session, has_request_context, g
from dotenv import load_dotenv

from app.shared.config import BASE_DIR, QUERY_DIR, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, MAX_LOGO_SIZE, PRODUCT_DOCS_FOLDER, CUSTOMER_DOCS_FOLDER
from app.shared.db import get_db
from app.shared.utils import load_query, to_tr_time, _fmt_dt

def create_app():
    load_dotenv()
    
    app = Flask(__name__, template_folder='templates', static_folder='../static')
    app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

    # --- Jinja Filters ---
    app.jinja_env.filters["tr_time"] = to_tr_time
    app.jinja_env.filters["fmtdate"] = lambda v: _fmt_dt(v, 10)
    app.jinja_env.filters["fmtdatetime"] = lambda v: _fmt_dt(v, 16)

    # --- Context Processors ---
    @app.context_processor
    def inject_lang_dict():
        from app.microservices.routes import get_microservices_state
        if not has_request_context():
            return dict(lang_dict={}, current_lang=0, microservices_state=get_microservices_state())
        lang_id = session.get("lang", 2)
        try:
            conn = get_db()
            rows = conn.execute(load_query("get_dictionary"), (lang_id,)).fetchall()
            conn.close()
            lang_dict = {row["Id"]: row["Description"] for row in rows}
        except Exception:
            lang_dict = {}
        return dict(lang_dict=lang_dict, current_lang=lang_id, microservices_state=get_microservices_state())

    # --- User Guard ---
    @app.before_request
    def require_user_selection():
        if not request.endpoint or request.endpoint in ("auth.user_login", "auth.set_user", "static") or request.endpoint.startswith("admin."):
            return
        if "user_id" not in session:
            return redirect(url_for("auth.user_login"))

    # --- Environment Guard ---
    @app.before_request
    def require_env_selection():
        if not request.endpoint or request.endpoint in ("auth.user_login", "auth.set_user", "auth.env_login", "auth.set_env", "auth.disconnect", "static") or request.endpoint.startswith("admin."):
            return
        if "env" not in session:
            return redirect(url_for("auth.env_login"))

    # --- Frame-mode redirect passthrough ---
    @app.after_request
    def preserve_frame_on_redirect(response):
        is_frame = request.args.get('_frame') == '1' or request.form.get('_frame') == '1'
        if is_frame and response.status_code in (301, 302, 303, 307, 308):
            loc = response.headers.get('Location', '')
            if loc and '_frame=1' not in loc:
                sep = '&' if '?' in loc else '?'
                response.headers['Location'] = loc + sep + '_frame=1'
        return response

    # --- Audit Logging ---
    @app.before_request
    def mark_request_start():
        g.request_start_time = time.time()

    @app.after_request
    def log_activity(response):
        if request.endpoint == 'static':
            return response
        
        try:
            duration_ms = int((time.time() - g.get('request_start_time', time.time())) * 1000)
            
            body_summary = None
            if request.method in ('POST', 'PUT', 'DELETE'):
                safe_keys = {k: v for k, v in request.form.items() 
                            if 'password' not in k.lower() and 'token' not in k.lower()}
                body_summary = str(safe_keys)[:2000] if safe_keys else None
            
            conn = get_db()
            conn.execute(load_query("auditlog_insert"), (
                session.get('user_id'),
                session.get('username', ''),
                session.get('env', 'local'),
                request.method,
                request.path[:500],
                request.blueprints[0] if request.blueprints else None,
                request.endpoint,
                response.status_code,
                duration_ms,
                request.remote_addr,
                str(request.user_agent)[:300],
                None,
                body_summary
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[audit] logging failed (non-fatal): {e}")
        
        return response

    # --- Blueprint Registration ---
    from app.admin.routes import admin_bp
    from app.auth.routes import auth_bp
    from app.dashboard.routes import dashboard_bp
    from app.syndications.routes import syndications_bp
    from app.foreignloans.routes import foreignloans_bp
    from app.management.routes import management_bp
    from app.overview.routes import overview_bp
    from app.products.routes import products_bp
    from app.okrs.routes import okrs_bp
    from app.work_items.routes import work_items_bp
    from app.microservices.routes import microservices_bp

    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(syndications_bp)
    app.register_blueprint(foreignloans_bp)
    app.register_blueprint(management_bp)
    app.register_blueprint(overview_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(okrs_bp)
    app.register_blueprint(work_items_bp)
    app.register_blueprint(microservices_bp)
    
    # Run DB schema checks
    with app.app_context():
        _ensure_isactive_columns()
        _run_platform_migrations()
        _ensure_wit_schema()
        _ensure_customer_doc_schema()
        _ensure_auditlog_schema()

    return app

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

def _ensure_isactive_columns():
    try:
        conn = get_db()
        for table in ("Comment",):
            if not _col_exists(conn, table, "IsActive", schema="CUS"):
                conn.execute(f"ALTER TABLE BOA.CUS.{table} ADD IsActive TINYINT NOT NULL DEFAULT 1")
                conn.commit()
                print(f"[startup] IsActive column added to BOA.CUS.{table}")
            else:
                print(f"[startup] IsActive already present on BOA.CUS.{table} — skipping")
        conn.close()
    except Exception as e:
        print(f"[startup] IsActive migration warning (non-fatal): {e}")

def _run_platform_migrations():
    conn = get_db()
    try:
        if not _table_exists(conn, "Stakeholder", "COR"):
            conn.execute(load_query("schema/stakeholder"))
            conn.commit()
            print("[startup] Created BOA.COR.Stakeholder")

        if not _table_exists(conn, "Product", "COR"):
            conn.execute(load_query("schema/product"))
            conn.execute(load_query("schema/seed_product"))
            conn.commit()
            print("[startup] Created BOA.COR.Product + seeded")

        if not _table_exists(conn, "Objective", "WIT"):
            conn.execute(load_query("schema/objective"))
            conn.commit()
            print("[startup] Created BOA.WIT.Objective")

        if not _table_exists(conn, "KeyResult", "WIT"):
            conn.execute(load_query("schema/keyresult"))
            conn.commit()
            print("[startup] Created BOA.WIT.KeyResult")

        if not _table_exists(conn, "Project", "STR"):
            conn.execute(load_query("schema/project"))
            conn.commit()
            print("[startup] Created BOA.STR.Project")

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

        if not _table_exists(conn, "ForeignLoan", "STF"):
            try:
                conn.execute("CREATE SCHEMA STF")
                conn.commit()
            except Exception:
                pass
            conn.execute(load_query("schema/foreignloan"))
            conn.execute(load_query("schema/foreignloandetail"))
            conn.commit()
            print("[startup] Created ForeignLoan, ForeignLoanDetail tables")

        if not _table_exists(conn, "FinancialReports", "STF"):
            try:
                conn.execute("CREATE SCHEMA STF")
                conn.commit()
            except Exception:
                pass
            conn.execute(load_query("schema/financial_report"))
            conn.commit()
            print("[startup] Created BOA.STF.FinancialReports table")

        if _table_exists(conn, "Product", "COR"):
            if not _col_exists(conn, "Product", "ResourceCode", schema="COR"):
                conn.execute("ALTER TABLE BOA.COR.Product ADD ResourceCode NVARCHAR(50) NULL")
                conn.commit()
                print("[startup] Added ResourceCode column to BOA.COR.Product")
            try:
                conn.execute("UPDATE BOA.COR.Product SET ResourceCode='SYNDICATION' WHERE ProductCode='SYNDICATION' AND ResourceCode IS NULL")
                conn.execute("UPDATE BOA.COR.Product SET ResourceCode='FOREIGNLOAN' WHERE ProductCode='ABCYURTDISI' AND ResourceCode IS NULL")
                if _table_exists(conn, "MainDeals", "STR"):
                    conn.execute("UPDATE BOA.STR.MainDeals SET ProductCode='ABCYURTDISI' WHERE ProductCode='FOREIGNLOAN'")
                conn.commit()
            except Exception as exc:
                print(f"[startup] Resource mapping sync note: {exc}")

    except Exception as e:
        print(f"[startup] Platform migration error (non-fatal): {e}")
    finally:
        conn.close()

def _ensure_customer_doc_schema():
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
    try:
        conn = get_db()
        if not _schema_exists(conn, "WIT"):
            conn.execute("CREATE SCHEMA WIT")
            conn.commit()
            print("[startup] Created schema BOA.WIT")

        if not _table_exists(conn, "WorkItem", "WIT"):
            conn.execute(load_query("schema/wit_workitem"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkItem")

        if not _table_exists(conn, "WorkSubItem", "WIT"):
            conn.execute(load_query("schema/wit_worksubitem"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkSubItem")

        if not _table_exists(conn, "WorkItemPrerequisite", "WIT"):
            conn.execute(load_query("schema/wit_workitemprereq"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkItemPrerequisite")

        if not _table_exists(conn, "WorkItemAssignee", "WIT"):
            conn.execute(load_query("schema/wit_workitemassignee"))
            conn.commit()
            print("[startup] Created BOA.WIT.WorkItemAssignee")

        result = conn.execute(load_query("schema/check_wit_deal")).fetchone()
        if result and int(result["cnt"]) > 0:
            conn.execute(load_query("schema/wit_deal_remap"))
            conn.commit()

        conn.execute(load_query("schema/wit_orphan_deactivate"))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[startup] WIT schema migration warning (non-fatal): {e}")

def _ensure_auditlog_schema():
    conn = get_db()
    try:
        if not _table_exists(conn, "AuditLog", "COR"):
            conn.execute(load_query("schema/auditlog"))
            conn.commit()
            print("[startup] Created BOA.COR.AuditLog")
    except Exception as e:
        print(f"[startup] AuditLog schema migration warning (non-fatal): {e}")
    finally:
        conn.close()
