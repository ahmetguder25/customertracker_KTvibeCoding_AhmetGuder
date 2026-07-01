import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, send_file
from app.shared.db import get_db
from app.shared.utils import get_param_map
from app.shared.config import PRODUCT_DOCS_FOLDER

from . import products_bp

@products_bp.route("/products")
def products_list():
    conn = get_db()
    products = conn.execute(
        "SELECT p.*, "
        "  (SELECT COUNT(*) FROM BOA.STR.MainDeals d WHERE d.ProductCode=p.ProductCode) AS deal_count "
        "FROM BOA.COR.Product p WHERE p.IsActive=1 ORDER BY p.ProductName"
    ).fetchall()
    res_rows = conn.execute(
        "SELECT DISTINCT ResourceCode FROM BOA.COR.Product WHERE ResourceCode IS NOT NULL AND ResourceCode != '' AND IsActive=1"
    ).fetchall()
    resources = sorted(list(set([r["ResourceCode"] for r in res_rows] + ["FOREIGNLOAN", "SYNDICATION"])))
    conn.close()
    return render_template("products/products.html", products=products, resources=resources)


@products_bp.route("/api/products", methods=["GET"])
def api_products_list():
    resource_code = request.args.get("resource_code")
    conn = get_db()
    if resource_code:
        products = conn.execute(
            "SELECT ProductID, ProductCode, ProductName, ResourceCode FROM BOA.COR.Product "
            "WHERE IsActive=1 AND (ResourceCode=? OR ResourceCode IS NULL OR ResourceCode='') "
            "ORDER BY ProductName",
            (resource_code.strip().upper(),)
        ).fetchall()
    else:
        products = conn.execute(
            "SELECT ProductID, ProductCode, ProductName, ResourceCode FROM BOA.COR.Product "
            "WHERE IsActive=1 ORDER BY ProductName"
        ).fetchall()
    conn.close()
    return jsonify({"ok": True, "products": [dict(p) for p in products]})


@products_bp.route("/api/products", methods=["POST"])
def api_product_create():
    data = request.get_json(silent=True) or {}
    res_code = data.get("resource_code")
    res_code = res_code.strip().upper() if res_code else None
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.COR.Product (ProductCode,ProductName,ResourceCode) VALUES (?,?,?)",
        (data.get("code",""), data.get("name",""), res_code)
    )
    conn.commit()
    pid = conn.execute("SELECT MAX(ProductID) AS id FROM BOA.COR.Product").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "product_id": pid})


@products_bp.route("/api/products/<int:pid>", methods=["PATCH"])
def api_product_update(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    if "resource_code" in data:
        res_code = data.get("resource_code")
        res_code = res_code.strip().upper() if res_code else None
        conn.execute(
            "UPDATE BOA.COR.Product SET ProductName=?, ResourceCode=? WHERE ProductID=?",
            (data.get("name"), res_code, pid)
        )
    else:
        conn.execute(
            "UPDATE BOA.COR.Product SET ProductName=? WHERE ProductID=?",
            (data.get("name"), pid)
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@products_bp.route("/api/products/<int:pid>", methods=["DELETE"])
def api_product_delete(pid):
    conn = get_db()
    conn.execute("UPDATE BOA.COR.Product SET IsActive=0 WHERE ProductID=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@products_bp.route("/products/<int:pid>")
def product_detail(pid):
    conn = get_db()
    product = conn.execute(
        "SELECT * FROM BOA.COR.Product WHERE ProductID=? AND IsActive=1", (pid,)
    ).fetchone()
    if not product:
        conn.close()
        return redirect(url_for("products.products_list"))
    documents = conn.execute(
        "SELECT pd.*, cu.Username AS UploaderName "
        "FROM BOA.COR.ProductDocument pd "
        "LEFT JOIN BOA.COR.[User] cu ON pd.UploadedBy = cu.Username "
        "WHERE pd.ProductID=? AND pd.IsActive=1 "
        "ORDER BY pd.UploadedAt DESC",
        (pid,)
    ).fetchall()
    doc_type_map = get_param_map("PRODDOC", conn)
    conn.close()
    return render_template(
        "products/product_detail.html",
        product=product,
        documents=documents,
        doc_type_map=doc_type_map
    )


@products_bp.route("/products/<int:pid>/documents", methods=["POST"])
def product_doc_upload(pid):
    conn = get_db()
    product = conn.execute(
        "SELECT ProductID FROM BOA.COR.Product WHERE ProductID=? AND IsActive=1", (pid,)
    ).fetchone()
    if not product:
        conn.close()
        return jsonify({"ok": False, "error": "Product not found"}), 404

    doc_name  = request.form.get("doc_name", "").strip()
    doc_type  = request.form.get("doc_type", "").strip()
    file      = request.files.get("file")

    if not doc_name or not doc_type or not file or file.filename == "":
        conn.close()
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    original_filename = secure_filename(file.filename)
    file_ext = os.path.splitext(original_filename)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    stored_filename = f"{pid}_{timestamp}_{original_filename}"
    save_path = os.path.join(PRODUCT_DOCS_FOLDER, stored_filename)
    file.save(save_path)

    uploader = session.get("username", "system")
    conn.execute(
        "INSERT INTO BOA.COR.ProductDocument "
        "(ProductID, DocName, DocTypeCode, FileName, FileExt, UploadedBy) "
        "VALUES (?,?,?,?,?,?)",
        (pid, doc_name, int(doc_type), stored_filename, file_ext.lstrip("."), uploader)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("products.product_detail", pid=pid))


@products_bp.route("/api/products/<int:pid>/documents/<int:doc_id>", methods=["PATCH"])
def api_product_doc_edit(pid, doc_id):
    data = request.get_json(silent=True) or {}
    doc_name = data.get("doc_name", "").strip()
    doc_type = data.get("doc_type")
    if not doc_name or not doc_type:
        return jsonify({"ok": False, "error": "Missing fields"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE BOA.COR.ProductDocument SET DocName=?, DocTypeCode=? "
        "WHERE DocID=? AND ProductID=? AND IsActive=1",
        (doc_name, int(doc_type), doc_id, pid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@products_bp.route("/api/products/<int:pid>/documents/<int:doc_id>", methods=["DELETE"])
def api_product_doc_delete(pid, doc_id):
    conn = get_db()
    row = conn.execute(
        "SELECT FileName FROM BOA.COR.ProductDocument WHERE DocID=? AND ProductID=? AND IsActive=1",
        (doc_id, pid)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE BOA.COR.ProductDocument SET IsActive=0 WHERE DocID=?", (doc_id,)
        )
        conn.commit()
        file_path = os.path.join(PRODUCT_DOCS_FOLDER, row["FileName"])
        if os.path.exists(file_path):
            os.remove(file_path)
    conn.close()
    return jsonify({"ok": True})


@products_bp.route("/products/<int:pid>/documents/<int:doc_id>/open")
def product_doc_open(pid, doc_id):
    conn = get_db()
    row = conn.execute(
        "SELECT FileName, DocName, FileExt FROM BOA.COR.ProductDocument "
        "WHERE DocID=? AND ProductID=? AND IsActive=1",
        (doc_id, pid)
    ).fetchone()
    conn.close()
    if not row:
        return "File not found", 404
    file_path = os.path.join(PRODUCT_DOCS_FOLDER, row["FileName"])
    if not os.path.exists(file_path):
        return "File not found on disk", 404
    download_name = f"{row['DocName']}.{row['FileExt']}"
    return send_file(file_path, as_attachment=False, download_name=download_name)
