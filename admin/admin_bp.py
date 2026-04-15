"""Admin Blueprint — Management Console for local SQL Server tables (LOCAL env only)."""
import os
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

# Only these tables are editable through the admin module (whitelist).
# Value = primary key column name used for update/delete operations.
ALLOWED_TABLES: dict[str, str] = {
    "Parameter": "RowId",
    "Dictionary": "RowId",
    "User": "id",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_db():
    """Use the main app's local SQL Server connection — admin is LOCAL-only."""
    from app import get_db as _app_get_db
    return _app_get_db()


def is_local_env() -> bool:
    """True when not in PROD — write operations are allowed."""
    return session.get("env", "local") != "prod"


def get_pk_column(table_name: str) -> str:
    """Return the primary key column name for the given allowed table."""
    return ALLOWED_TABLES.get(table_name, "id")


def get_table_columns(table_name: str) -> list[str]:
    """Return editable column names (excluding the PK) via INFORMATION_SCHEMA."""
    pk_col = get_pk_column(table_name)
    conn = get_db()
    rows = conn.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = 'ZZZ' AND TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION",
        (table_name,)
    ).fetchall()
    conn.close()
    return [r["COLUMN_NAME"] for r in rows if r["COLUMN_NAME"] != pk_col]


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
    col_names = get_table_columns(table_name)

    conn = get_db()
    rows = conn.execute(
        f"SELECT t.*, t.[{pk_col}] AS rowid FROM BOA.ZZZ.[{table_name}] t ORDER BY t.[{pk_col}]"
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
    values = [request.form.get(col, "") or None for col in col_names]
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(f"[{c}]" for c in col_names)

    try:
        conn = get_db()
        conn.execute(f"INSERT INTO BOA.ZZZ.[{table_name}] ({col_list}) VALUES ({placeholders})", values)
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
    col_names = get_table_columns(table_name)

    set_clause = ", ".join(f"[{col}] = ?" for col in col_names)
    values = [request.form.get(col, "") or None for col in col_names]
    values.append(rowid)

    try:
        conn = get_db()
        conn.execute(f"UPDATE BOA.ZZZ.[{table_name}] SET {set_clause} WHERE [{pk_col}] = ?", values)
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

    try:
        conn = get_db()
        conn.execute(f"DELETE FROM BOA.ZZZ.[{table_name}] WHERE [{pk_col}] = ?", (rowid,))
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
        MAX(CASE WHEN LanguageId = 0 THEN Description END) AS lang_en,
        MAX(CASE WHEN LanguageId = 1 THEN Description END) AS lang_tr
    FROM BOA.ZZZ.Dictionary
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
                MERGE INTO BOA.ZZZ.Dictionary AS target
                USING (SELECT ? AS Id, ? AS LanguageId, ? AS Description) AS source
                    ON target.Id = source.Id AND target.LanguageId = source.LanguageId
                WHEN MATCHED THEN
                    UPDATE SET Description = source.Description
                WHEN NOT MATCHED THEN
                    INSERT (Id, LanguageId, Description)
                    VALUES (source.Id, source.LanguageId, source.Description);
            """
            conn.execute(upsert_sql, (key_id, 0, en_val))
            conn.execute(upsert_sql, (key_id, 1, tr_val))

        conn.commit()
        conn.close()
        return jsonify({"status": "success", "message": "Saved successfully!"})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 500
