import os
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Blueprint, render_template, request, redirect, url_for, jsonify, session, send_file
from app.shared.db import get_db
from app.shared.utils import load_query, get_param_map
from app.shared.config import CUSTOMER_DOCS_FOLDER

from . import overview_bp

@overview_bp.route("/overview")
def overview():
    conn       = get_db()
    customers  = conn.execute(load_query("overview_list")).fetchall()
    sector_map = get_param_map("Sector", conn)
    conn.close()
    return render_template("overview/overview_list.html", customers=customers, sector_map=sector_map)

@overview_bp.route("/overview/<int:customer_id>")
def overview_detail(customer_id):
    conn = get_db()
    customer = conn.execute(load_query("mgmt_get_customer"), (customer_id,)).fetchone()
    if not customer:
        conn.close()
        return redirect(url_for("overview.overview"))

    deals        = conn.execute(load_query("overview_deals"),        (customer_id,)).fetchall()
    comments     = conn.execute(load_query("overview_comments"),     (customer_id,)).fetchall()
    same_sector  = conn.execute(load_query("overview_same_sector"),  (customer["sector"],)).fetchone()["cnt"]
    total_cust   = conn.execute(load_query("overview_total_customers")).fetchone()["cnt"]

    lang_id      = session.get("lang", 2)

    status_map    = get_param_map("Status",   conn)
    deal_type_map = get_param_map("DealType", conn)
    fec_map       = get_param_map("FEC",      conn)
    sector_map    = get_param_map("Sector",   conn)
    
    # Financial items processing
    fin_defs = conn.execute("SELECT * FROM BOA.LNS.FinancialItemDefinition").fetchall()
    allotments = conn.execute("SELECT * FROM BOA.LNS.AllotmentFinancialItems WHERE AllotmentMainId = ? ORDER BY PeriodId", (customer_id,)).fetchall()
    
    # Customer Documents
    documents = conn.execute(
        "SELECT cd.*, cu.Username AS UploaderName "
        "FROM BOA.COR.CustomerDocument cd "
        "LEFT JOIN BOA.COR.[User] cu ON cd.UploadedBy = cu.Username "
        "WHERE cd.CustomerID=? AND cd.IsActive=1 "
        "ORDER BY cd.UploadedAt DESC",
        (customer_id,)
    ).fetchall()
    doc_type_map = get_param_map("CUSTDOC", conn)
    
    conn.close()

    total_deal_size = sum((d["deal_size"] or 0) for d in deals)

    # Build Financial Tree
    fin_map = {}
    for row in fin_defs:
        d = dict(row)
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
        for child in sorted(node["children"], key=lambda x: str(x["Code"])):
            traverse(child, depth + 1)
            
    for r in sorted(roots, key=lambda x: str(x["Code"])):
        traverse(r, 0)
        
    chart_periods = [f"Period {p}" for p in periods]
    asset_data = []
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
        "overview/overview_detail.html",
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
        fin_nodes       = ordered_fin_nodes,
        periods         = periods,
        chart_periods   = chart_periods,
        chart_asset_data= asset_data,
        documents       = documents,
        doc_type_map    = doc_type_map
    )

@overview_bp.route("/overview/<int:cid>/documents", methods=["POST"])
def customer_doc_upload(cid):
    conn = get_db()
    customer = conn.execute(
        "SELECT Customerid FROM BOA.CUS.Customer WHERE Customerid=?", (cid,)
    ).fetchone()
    if not customer:
        conn.close()
        return jsonify({"ok": False, "error": "Customer not found"}), 404

    doc_name  = request.form.get("doc_name", "").strip()
    doc_type  = request.form.get("doc_type", "").strip()
    file      = request.files.get("file")

    if not doc_name or not doc_type or not file or file.filename == "":
        conn.close()
        return jsonify({"ok": False, "error": "Missing required fields"}), 400

    original_filename = secure_filename(file.filename)
    file_ext = os.path.splitext(original_filename)[1].lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    stored_filename = f"{cid}_{timestamp}_{original_filename}"
    save_path = os.path.join(CUSTOMER_DOCS_FOLDER, stored_filename)
    file.save(save_path)

    uploader = session.get("username", "system")
    conn.execute(
        "INSERT INTO BOA.COR.CustomerDocument "
        "(CustomerID, DocName, DocTypeCode, FileName, FileExt, UploadedBy) "
        "VALUES (?,?,?,?,?,?)",
        (cid, doc_name, int(doc_type), stored_filename, file_ext.lstrip("."), uploader)
    )
    conn.commit()
    conn.close()
    return redirect(url_for("overview.overview_detail", customer_id=cid))

@overview_bp.route("/api/customers/<int:cid>/documents/<int:doc_id>", methods=["PATCH"])
def api_customer_doc_edit(cid, doc_id):
    data = request.get_json(silent=True) or {}
    doc_name = data.get("doc_name", "").strip()
    doc_type = data.get("doc_type")
    if not doc_name or not doc_type:
        return jsonify({"ok": False, "error": "Missing fields"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE BOA.COR.CustomerDocument SET DocName=?, DocTypeCode=? "
        "WHERE DocID=? AND CustomerID=? AND IsActive=1",
        (doc_name, int(doc_type), doc_id, cid)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@overview_bp.route("/api/customers/<int:cid>/documents/<int:doc_id>", methods=["DELETE"])
def api_customer_doc_delete(cid, doc_id):
    conn = get_db()
    row = conn.execute(
        "SELECT FileName FROM BOA.COR.CustomerDocument WHERE DocID=? AND CustomerID=? AND IsActive=1",
        (doc_id, cid)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE BOA.COR.CustomerDocument SET IsActive=0 WHERE DocID=?", (doc_id,)
        )
        conn.commit()
        file_path = os.path.join(CUSTOMER_DOCS_FOLDER, row["FileName"])
        if os.path.exists(file_path):
            os.remove(file_path)
    conn.close()
    return jsonify({"ok": True})

@overview_bp.route("/overview/<int:cid>/documents/<int:doc_id>/open")
def customer_doc_open(cid, doc_id):
    conn = get_db()
    row = conn.execute(
        "SELECT FileName, DocName, FileExt FROM BOA.COR.CustomerDocument "
        "WHERE DocID=? AND CustomerID=? AND IsActive=1",
        (doc_id, cid)
    ).fetchone()
    conn.close()
    if not row:
        return "File not found", 404
    file_path = os.path.join(CUSTOMER_DOCS_FOLDER, row["FileName"])
    if not os.path.exists(file_path):
        return "File not found on disk", 404
    download_name = f"{row['DocName']}.{row['FileExt']}"
    return send_file(file_path, as_attachment=False, download_name=download_name)

@overview_bp.route("/overview/<int:customer_id>/comment", methods=["POST"])
def add_comment(customer_id):
    author  = session.get("username", "System")
    content = request.form.get("content", "").strip()
    if author and content:
        conn = get_db()
        conn.execute(load_query("comment_insert"), (customer_id, author, content))
        conn.commit()
        conn.close()
    return redirect(url_for("overview.overview_detail", customer_id=customer_id))
