"""Admin Blueprint — Management Console for local SQLite tables (TEST env only)."""
import os
import sqlite3
from typing import Optional
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, session, jsonify
)

# ── Blueprint Setup ────────────────────────────────────────────────────────────
admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH    = os.path.join(BASE_DIR, "customer_tracker.db")

# Only these tables are editable through the admin module (whitelist)
ALLOWED_TABLES = {"Parameter", "Dictionary", "User"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_db():
    """Always use local SQLite — admin is TEST-only."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def is_test_env() -> bool:
    return session.get("env", "test") == "test"


def get_table_columns(table_name: str) -> list:
    """Return list of column info dicts via PRAGMA table_info."""
    conn = get_db()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pk_column(columns: list) -> Optional[str]:
    """Find the primary key column name; fallback to rowid."""
    for col in columns:
        if col["pk"]:
            return col["name"]
    return None


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

    columns = get_table_columns(table_name)
    col_names = [c["name"] for c in columns]

    # Always include rowid for stable row identification
    conn = get_db()
    rows = conn.execute(
        f"SELECT rowid, * FROM {table_name} ORDER BY rowid"
    ).fetchall()
    rows = [dict(r) for r in rows]
    conn.close()

    # Filter args
    filter_col  = request.args.get("filter_col", "")
    filter_val  = request.args.get("filter_val", "")
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
        is_test=is_test_env(),
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

    if not is_test_env():
        flash("Write operations are only permitted in the TEST environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    columns = get_table_columns(table_name)
    col_names = [c["name"] for c in columns]

    values = [request.form.get(col, "") or None for col in col_names]
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(col_names)

    try:
        conn = get_db()
        conn.execute(f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})", values)
        conn.commit()
        conn.close()
        flash(f"Row added to {table_name} successfully.", "success")
    except Exception as exc:
        flash(f"Error adding row: {exc}", "error")

    return redirect(url_for("admin.admin_edit", table_name=table_name))


@admin_bp.route("/edit/<table_name>/update/<int:rowid>", methods=["POST"])
def admin_update_row(table_name, rowid):
    """Update an existing row identified by its SQLite rowid."""
    if table_name not in ALLOWED_TABLES:
        flash("Access denied.", "error")
        return redirect(url_for("admin.admin_index"))

    if not is_test_env():
        flash("Write operations are only permitted in the TEST environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    columns = get_table_columns(table_name)
    col_names = [c["name"] for c in columns]

    set_clause = ", ".join(f"{col} = ?" for col in col_names)
    values = [request.form.get(col, "") or None for col in col_names]
    values.append(rowid)

    try:
        conn = get_db()
        conn.execute(f"UPDATE {table_name} SET {set_clause} WHERE rowid = ?", values)
        conn.commit()
        conn.close()
        flash(f"Row {rowid} updated successfully.", "success")
    except Exception as exc:
        flash(f"Error updating row: {exc}", "error")

    return redirect(url_for("admin.admin_edit", table_name=table_name))


@admin_bp.route("/edit/<table_name>/delete/<int:rowid>", methods=["POST"])
def admin_delete_row(table_name, rowid):
    """Delete a row by its rowid."""
    if table_name not in ALLOWED_TABLES:
        flash("Access denied.", "error")
        return redirect(url_for("admin.admin_index"))

    if not is_test_env():
        flash("Write operations are only permitted in the TEST environment.", "error")
        return redirect(url_for("admin.admin_edit", table_name=table_name))

    try:
        conn = get_db()
        conn.execute(f"DELETE FROM {table_name} WHERE rowid = ?", (rowid,))
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
    if not is_test_env():
        flash("Admin console operations restrict write, but read is ok. (Test env required for edit)", "info")
        
    conn = get_db()
    query = """
    SELECT 
        Id,
        MAX(CASE WHEN LanguageId = 0 THEN Description END) as lang_en,
        MAX(CASE WHEN LanguageId = 1 THEN Description END) as lang_tr
    FROM Dictionary
    GROUP BY Id
    ORDER BY Id COLLATE NOCASE
    """
    rows = conn.execute(query).fetchall()
    conn.close()
    
    return render_template(
        "admin_dictionary.html",
        rows=rows,
        is_test=is_test_env()
    )


@admin_bp.route("/dictionary-editor/save", methods=["POST"])
def admin_dictionary_save():
    """Bulk save dictionary changes via JSON."""
    if not is_test_env():
        return jsonify({"status": "error", "message": "Modifications are only permitted in the TEST environment"}), 403
        
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
            
            # Using INSERT OR REPLACE to upsert records into the Dictionary table.
            conn.execute("INSERT OR REPLACE INTO Dictionary (Id, LanguageId, Description) VALUES (?, ?, ?)", (key_id, 0, en_val))
            conn.execute("INSERT OR REPLACE INTO Dictionary (Id, LanguageId, Description) VALUES (?, ?, ?)", (key_id, 1, tr_val))
            
        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Saved successfully!"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
