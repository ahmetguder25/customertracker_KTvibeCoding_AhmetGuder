"""Admin Blueprint — Management Console for local SQL Server tables (LOCAL env only)."""
import os
from typing import Optional
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify
)

from . import admin_bp

# Only these tables are editable through the admin module (whitelist).
# Value = dict with 'pk' (primary key column) and 'schema' (SQL Server schema).
ALLOWED_TABLES: dict[str, dict] = {
    "Parameter": {"pk": "RowId", "schema": "COR"},
    "Dictionary": {"pk": "RowId", "schema": "COR"},
    "User": {"pk": "id", "schema": "COR"},
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_db():
    """Use the main app's local SQL Server connection — admin is LOCAL-only."""
    from app.shared.db import get_db as _app_get_db
    return _app_get_db()


def is_local_env() -> bool:
    """True when not in PROD — write operations are allowed."""
    return session.get("env", "local") != "prod"


def get_pk_column(table_name: str) -> str:
    """Return the primary key column name for the given allowed table."""
    info = ALLOWED_TABLES.get(table_name, {})
    return info.get("pk", "id") if isinstance(info, dict) else "id"


def get_schema(table_name: str) -> str:
    """Return the SQL Server schema for the given allowed table."""
    info = ALLOWED_TABLES.get(table_name, {})
    return info.get("schema", "COR") if isinstance(info, dict) else "COR"


def get_table_columns(table_name: str) -> list[str]:
    """Return editable column names (excluding the PK and hidden cols) via INFORMATION_SCHEMA."""
    pk_col = get_pk_column(table_name)
    schema = get_schema(table_name)
    # Columns that exist in the DB but should not appear in the admin editor
    hidden = set()
    conn = get_db()
    rows = conn.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION",
        (schema, table_name,)
    ).fetchall()
    conn.close()
    return [r["COLUMN_NAME"] for r in rows
            if r["COLUMN_NAME"] != pk_col and r["COLUMN_NAME"].lower() not in hidden]


# ── Routes ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/")
def admin_index():
    """Management Console landing page."""
    return render_template("admin_index.html")


@admin_bp.route("/edit/<table_name>")
def admin_edit(table_name):
    """Dynamic table editor — loads any allowed table from the whitelist."""
    if table_name not in ALLOWED_TABLES:
        flash(f'Table "{table_name}" is not accessible via the Admin module.', "error")
        return redirect(url_for("admin.admin_index"))

    pk_col   = get_pk_column(table_name)
    schema   = get_schema(table_name)
    col_names = get_table_columns(table_name)

    conn = get_db()
    rows = conn.execute(
        f"SELECT t.*, t.[{pk_col}] AS rowid FROM BOA.{schema}.[{table_name}] t ORDER BY t.[{pk_col}]"
    ).fetchall()
    conn.close()

    # Filter args
    filter_col = request.args.get("filter_col", "")
    filter_val = request.args.get("filter_val", "")
    if filter_col and filter_col in col_names and filter_val:
        rows = [r for r in rows if str(r.get(filter_col, "")) == filter_val]

    # Distinct filter values for the filter bar
    filter_options: dict[str, list] = {}
    if table_name == "Parameter":
        filter_options["ParamType"] = sorted({r["ParamType"] for r in rows if r.get("ParamType")})
        filter_options["LanguageId"] = sorted({str(r["LanguageId"]) for r in rows if r.get("LanguageId") is not None})
    elif table_name == "Dictionary":
        filter_options["LanguageId"] = sorted({str(r["LanguageId"]) for r in rows if r.get("LanguageId") is not None})

    return render_template(
        "admin_edit.html",
        table_name=table_name,
        columns=col_names,
        rows=rows,
        is_test=is_local_env(),
        filter_col=filter_col,
        filter_val=filter_val,
        filter_options=filter_options,
    )


@admin_bp.route("/edit/<table_name>/add", methods=["POST"])
def admin_add_row(table_name):
    """Insert a new row into the specified table."""
    if table_name not in ALLOWED_TABLES:
        flash("Access denied.", "error")
        return redirect(url_for("admin.admin_index"))

    if not is_local_env():
        flash("Write operations are only permitted in the LOCAL environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    col_names = get_table_columns(table_name)
    schema    = get_schema(table_name)
    values = [request.form.get(col, "") or None for col in col_names]
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(f"[{c}]" for c in col_names)

    try:
        conn = get_db()
        conn.execute(f"INSERT INTO BOA.{schema}.[{table_name}] ({col_list}) VALUES ({placeholders})", values)
        conn.commit()
        conn.close()
        flash(f"Row added to {table_name} successfully.", "success")
    except Exception as exc:
        flash(f"Error adding row: {exc}", "error")

    return redirect(url_for("admin.admin_edit", table_name=table_name))


@admin_bp.route("/edit/<table_name>/update/<int:rowid>", methods=["POST"])
def admin_update_row(table_name, rowid):
    """Update an existing row identified by its primary key value."""
    if table_name not in ALLOWED_TABLES:
        flash("Access denied.", "error")
        return redirect(url_for("admin.admin_index"))

    if not is_local_env():
        flash("Write operations are only permitted in the LOCAL environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    pk_col    = get_pk_column(table_name)
    schema    = get_schema(table_name)
    col_names = get_table_columns(table_name)

    set_clause = ", ".join(f"[{col}] = ?" for col in col_names)
    values = [request.form.get(col, "") or None for col in col_names]
    values.append(rowid)

    try:
        conn = get_db()
        conn.execute(f"UPDATE BOA.{schema}.[{table_name}] SET {set_clause} WHERE [{pk_col}] = ?", values)
        conn.commit()
        conn.close()
        flash(f"Row {rowid} updated successfully.", "success")
    except Exception as exc:
        flash(f"Error updating row: {exc}", "error")

    return redirect(url_for("admin.admin_edit", table_name=table_name))


@admin_bp.route("/edit/<table_name>/delete/<int:rowid>", methods=["POST"])
def admin_delete_row(table_name, rowid):
    """Delete a row by its primary key value."""
    if table_name not in ALLOWED_TABLES:
        flash("Access denied.", "error")
        return redirect(url_for("admin.admin_index"))

    if not is_local_env():
        flash("Write operations are only permitted in the LOCAL environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    pk_col = get_pk_column(table_name)
    schema = get_schema(table_name)

    try:
        conn = get_db()
        conn.execute(f"DELETE FROM BOA.{schema}.[{table_name}] WHERE [{pk_col}] = ?", (rowid,))
        conn.commit()
        conn.close()
        flash(f"Row {rowid} deleted from {table_name}.", "success")
    except Exception as exc:
        flash(f"Error deleting row: {exc}", "error")

    return redirect(url_for("admin.admin_edit", table_name=table_name))


# ── Translation Interface ──────────────────────────────────────────────────────

@admin_bp.route("/dictionary-editor")
def admin_dictionary_editor():
    """Custom comparative UI for managing translations."""
    if not is_local_env():
        flash("Admin console operations restrict write, but read is ok. (Local env required for edit)", "info")

    conn = get_db()
    query = """
    SELECT
        Id,
        MAX(CASE WHEN LanguageId = 2 THEN Description END) AS lang_en,
        MAX(CASE WHEN LanguageId = 1 THEN Description END) AS lang_tr
    FROM BOA.COR.Dictionary
    GROUP BY Id
    ORDER BY Id
    """
    rows = conn.execute(query).fetchall()
    conn.close()

    return render_template(
        "admin_dictionary.html",
        rows=rows,
        is_test=is_local_env()
    )


@admin_bp.route("/dictionary-editor/save", methods=["POST"])
def admin_dictionary_save():
    """Bulk save dictionary changes via JSON."""
    if not is_local_env():
        return jsonify({"status": "error", "message": "Modifications are only permitted in the LOCAL environment"}), 403

    data = request.json
    if not data or not isinstance(data, list):
        return jsonify({"status": "error", "message": "Invalid JSON payload format"}), 400

    try:
        conn = get_db()
        for item in data:
            key_id = item.get("id")
            en_val = item.get("en", "")
            tr_val = item.get("tr", "")
            if not key_id:
                continue

            # T-SQL MERGE: upsert each language variant of the Dictionary entry.
            upsert_sql = """
                MERGE INTO BOA.COR.Dictionary AS target
                USING (SELECT ? AS Id, ? AS LanguageId, ? AS Description) AS source
                    ON target.Id = source.Id AND target.LanguageId = source.LanguageId
                WHEN MATCHED THEN
                    UPDATE SET Description = source.Description
                WHEN NOT MATCHED THEN
                    INSERT (Id, LanguageId, Description)
                    VALUES (source.Id, source.LanguageId, source.Description);
            """
            conn.execute(upsert_sql, (key_id, 2, en_val))
            conn.execute(upsert_sql, (key_id, 1, tr_val))

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Saved successfully!"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500

# ── Activity Log ───────────────────────────────────────────────────────────────

@admin_bp.route("/activity-log")
def activity_log():
    from app.shared.utils import load_query
    conn = get_db()
    
    # Get stats
    stats_queries = [q.strip() for q in load_query("auditlog_stats").split(";") if q.strip()]
    stats = {
        "TotalRequests": 0,
        "UniqueUsers": 0,
        "ErrorCount": 0,
        "AvgResponseTime": 0
    }
    try:
        if len(stats_queries) >= 4:
            stats["TotalRequests"] = conn.execute(stats_queries[0]).fetchone().get("TotalRequests", 0)
            stats["UniqueUsers"] = conn.execute(stats_queries[1]).fetchone().get("UniqueUsers", 0)
            stats["ErrorCount"] = conn.execute(stats_queries[2]).fetchone().get("ErrorCount", 0)
            stats["AvgResponseTime"] = conn.execute(stats_queries[3]).fetchone().get("AvgResponseTime", 0)
    except Exception as e:
        print(f"Stats error: {e}")

    # Build filter query
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    per_page = 50
    offset = (page - 1) * per_page
    
    where_clauses = []
    params = []
    
    user_filter = request.args.get("user")
    if user_filter:
        where_clauses.append("Username = ?")
        params.append(user_filter)
        
    method_filter = request.args.get("method")
    if method_filter:
        where_clauses.append("Method = ?")
        params.append(method_filter)
        
    bp_filter = request.args.get("blueprint")
    if bp_filter:
        where_clauses.append("Blueprint = ?")
        params.append(bp_filter)
        
    status_filter = request.args.get("status")
    if status_filter:
        if status_filter == "2xx":
            where_clauses.append("StatusCode >= 200 AND StatusCode < 300")
        elif status_filter == "3xx":
            where_clauses.append("StatusCode >= 300 AND StatusCode < 400")
        elif status_filter == "4xx":
            where_clauses.append("StatusCode >= 400 AND StatusCode < 500")
        elif status_filter == "5xx":
            where_clauses.append("StatusCode >= 500")
            
    query = "SELECT * FROM BOA.COR.AuditLog"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY Timestamp DESC OFFSET ? ROWS FETCH NEXT ? ROWS ONLY"
    
    params.extend([offset, per_page])
    logs = conn.execute(query, params).fetchall()
    
    # Get distinct options for dropdowns
    users = [r["Username"] for r in conn.execute("SELECT DISTINCT Username FROM BOA.COR.AuditLog WHERE Username IS NOT NULL ORDER BY Username").fetchall()]
    blueprints = [r["Blueprint"] for r in conn.execute("SELECT DISTINCT Blueprint FROM BOA.COR.AuditLog WHERE Blueprint IS NOT NULL ORDER BY Blueprint").fetchall()]
    
    conn.close()
    
    return render_template(
        "admin_activity_log.html",
        logs=logs,
        stats=stats,
        page=page,
        users=users,
        blueprints=blueprints,
        is_test=is_local_env()
    )

@admin_bp.route("/activity-log/cleanup", methods=["POST"])
def activity_log_cleanup():
    if not is_local_env():
        flash("Cleanup operations are only permitted in the LOCAL environment.", "error")
        return redirect(url_for("admin.activity_log"))
        
    from app.shared.utils import load_query
    try:
        conn = get_db()
        # Execute delete
        conn.execute(load_query("auditlog_cleanup"))
        conn.commit()
        conn.close()
        flash("Old activity logs cleaned up successfully.", "success")
    except Exception as exc:
        flash(f"Error cleaning up logs: {exc}", "error")
        
    return redirect(url_for("admin.activity_log"))
