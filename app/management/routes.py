import os
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, flash, session, has_request_context
from app.shared.db import get_db, get_customer_db, _get_db_prod, _get_db_prod_autocommit
from app.shared.utils import load_query, get_param_map, allowed_file
from app.shared.config import UPLOAD_FOLDER, MAX_LOGO_SIZE

from . import management_bp

@management_bp.route("/management")
def management():
    conn         = get_db()
    sector_map   = get_param_map("Sector", conn)
    customers    = conn.execute(load_query("mgmt_list_customers")).fetchall()
    stakeholders = conn.execute(
        "SELECT * FROM BOA.COR.Stakeholder WHERE IsActive=1 ORDER BY FullName"
    ).fetchall()
    conn.close()
    return render_template("management/management.html", customers=customers, sector_map=sector_map,
                           stakeholders=stakeholders)


@management_bp.route("/api/stakeholders", methods=["POST"])
def api_stakeholder_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.COR.Stakeholder (FullName,Organization,Department,Email) VALUES (?,?,?,?)",
        (data.get("full_name", ""), data.get("organization", ""),
         data.get("department", ""), data.get("email", ""))
    )
    conn.commit()
    sid = conn.execute("SELECT MAX(StakeholderID) AS id FROM BOA.COR.Stakeholder").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "stakeholder_id": sid})


@management_bp.route("/api/stakeholders/<int:sid>", methods=["PATCH"])
def api_stakeholder_update(sid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "UPDATE BOA.COR.Stakeholder SET FullName=?,Organization=?,Department=?,Email=? WHERE StakeholderID=?",
        (data.get("full_name"), data.get("organization"), data.get("department"), data.get("email"), sid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@management_bp.route("/api/stakeholders/<int:sid>", methods=["DELETE"])
def api_stakeholder_delete(sid):
    conn = get_db()
    conn.execute("UPDATE BOA.COR.Stakeholder SET IsActive=0 WHERE StakeholderID=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@management_bp.route("/api/customer/lookup/<int:account_number>")
def lookup_customer(account_number):
    try:
        conn_real = _get_db_prod()
        customer = conn_real.execute(load_query("prod_lookup_customer"), (account_number,)).fetchone()
        conn_real.close()

        if customer is None:
            return jsonify({"found": False})

        conn_local = get_db()
        already = conn_local.execute(
            "SELECT IsStructured FROM BOA.CUS.Customer WHERE Customerid = ?", (account_number,)
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
        msg = str(e)
        print(f"[lookup_customer] connection error: {msg}")
        return jsonify({"found": False, "connection_error": True, "error": msg})
    except Exception as e:
        msg = str(e)
        print(f"[lookup_customer] query error: {msg}")
        return jsonify({"found": False, "query_error": True, "error": msg})


@management_bp.route("/management/customer/add", methods=["POST"])
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
        
    return redirect(url_for("management.management"))


@management_bp.route("/management/api/sync/queue", methods=["GET"])
def sync_queue():
    conn_local = get_db()
    customers = conn_local.execute("SELECT Customerid, CustomerName FROM BOA.CUS.Customer WHERE IsStructured = 1").fetchall()
    conn_local.close()
    
    return jsonify({
        "success": True,
        "customers": [{"id": c["Customerid"], "name": c["CustomerName"]} for c in customers]
    })

@management_bp.route("/management/api/sync/batch", methods=["POST"])
def sync_batch():
    env = session.get("env", "local") if has_request_context() else "local"
    data = request.get_json()
    cids = data.get("customer_ids", [])

    if not cids:
        return jsonify({"success": False, "error": "No customers to sync."})

    if env != "prod":
        return jsonify({
            "success": False,
            "env_error": True,
            "error": "Update is only available in PROD environment. Switch to PROD to sync real customer data."
        })

    try:
        query_text = load_query("real_batch_customer_sync")
        ids_occurrences = query_text.count("{ids}")
        placeholders = ",".join("?" for _ in cids)
        query_text = query_text.replace("{ids}", placeholders)

        conn_real = _get_db_prod_autocommit()
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


@management_bp.route("/management/edit/<int:customer_id>", methods=["GET", "POST"])
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
                    return redirect(url_for("management.edit_customer", customer_id=customer_id))
                file.seek(0, os.SEEK_END)
                if file.tell() > MAX_LOGO_SIZE:
                    flash("Logo file too large.", "error")
                    conn.close()
                    return redirect(url_for("management.edit_customer", customer_id=customer_id))
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
        return redirect(url_for("management.edit_customer", customer_id=customer_id))

    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("management.management"))
    sector_map = get_param_map("Sector", conn)
    conn.close()
    return render_template("management/edit.html", customer=customer, sector_map=sector_map)


@management_bp.route("/management/customer/delete/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):
    conn = get_db()
    conn.execute(load_query("mgmt_remove_structured"), (customer_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("management.management"))
