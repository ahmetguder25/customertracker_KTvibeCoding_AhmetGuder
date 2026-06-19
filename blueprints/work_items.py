from flask import Blueprint, render_template, request, jsonify
from core.db import get_db
from core.utils import _load_backlog_json, load_query

work_items_bp = Blueprint("work_items", __name__)

_PARENT_TYPES = ("project", "syndication")

def _sync_project_status(conn, project_id):
    # Same logic as in okrs_bp, needs to sync Project Status when WorkItems change
    from blueprints.okrs import _sync_project_status as _okrs_sync
    _okrs_sync(conn, project_id)

@work_items_bp.route("/api/workitems", methods=["GET"])
def api_workitems_list():
    """JSON endpoint: list work items for a specific parent (used by portal panels)."""
    parent_type = request.args.get("parent_type")
    parent_id   = request.args.get("parent_id", type=int)
    if not parent_type or not parent_id or parent_type not in _PARENT_TYPES:
        return jsonify({"ok": False, "error": "Invalid parent_type or parent_id"}), 400
    conn = get_db()
    items = _load_backlog_json(conn, parent_type, parent_id)
    conn.close()
    return jsonify({"ok": True, "items": items})

@work_items_bp.route("/api/workitems", methods=["POST"])
def api_workitem_create():
    data = request.get_json(silent=True) or {}
    parent_type = data.get("parent_type", "")
    if parent_type not in _PARENT_TYPES:
        return jsonify({"ok": False, "error": f"parent_type must be one of {_PARENT_TYPES}"}), 400
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.WIT.WorkItem (ParentType,ParentID,Title,Description,Deadline,SortOrder) VALUES (?,?,?,?,?,?)",
        (parent_type, data.get("parent_id"), data.get("title",""), data.get("description",""), data.get("deadline") or None, data.get("sort_order",0))
    )
    conn.commit()
    iid = conn.execute("SELECT MAX(ItemID) AS id FROM BOA.WIT.WorkItem").fetchone()["id"]
    assignees = data.get("assignees", [])
    if assignees:
        for a in assignees:
            if a.startswith("U-"):
                conn.execute("INSERT INTO BOA.WIT.WorkItemAssignee (ItemID, UserID) VALUES (?, ?)", (iid, int(a[2:])))
            elif a.startswith("S-"):
                conn.execute("INSERT INTO BOA.WIT.WorkItemAssignee (ItemID, StakeholderID) VALUES (?, ?)", (iid, int(a[2:])))
        conn.commit()
    if parent_type == "project":
        _sync_project_status(conn, data.get("parent_id"))
    conn.close()
    return jsonify({"ok": True, "item_id": iid})

@work_items_bp.route("/api/workitems/<int:iid>", methods=["PATCH"])
def api_workitem_update(iid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    parent_type = data.get("parent_type")
    parent_id   = data.get("parent_id")
    if parent_type and parent_id and parent_type in _PARENT_TYPES:
        conn.execute(
            "UPDATE BOA.WIT.WorkItem SET Title=?,Description=?,Status=?,Deadline=?,ParentType=?,ParentID=?,UpdatedAt=GETDATE() WHERE ItemID=?",
            (data.get("title"), data.get("description"), data.get("status"),
             data.get("deadline") or None, parent_type, parent_id, iid)
        )
    else:
        conn.execute(
            "UPDATE BOA.WIT.WorkItem SET Title=?,Description=?,Status=?,Deadline=?,UpdatedAt=GETDATE() WHERE ItemID=?",
            (data.get("title"), data.get("description"), data.get("status"),
             data.get("deadline") or None, iid)
        )
    new_assignees = data.get("assignees")
    if new_assignees is not None:
        conn.execute("UPDATE BOA.WIT.WorkItemAssignee SET IsActive=0 WHERE ItemID=?", (iid,))
        for a in new_assignees:
            if a.startswith("U-"):
                conn.execute("INSERT INTO BOA.WIT.WorkItemAssignee (ItemID, UserID) VALUES (?, ?)", (iid, int(a[2:])))
            elif a.startswith("S-"):
                conn.execute("INSERT INTO BOA.WIT.WorkItemAssignee (ItemID, StakeholderID) VALUES (?, ?)", (iid, int(a[2:])))
    conn.commit()
    wi = conn.execute("SELECT ParentType, ParentID FROM BOA.WIT.WorkItem WHERE ItemID=?", (iid,)).fetchone()
    if wi and wi["ParentType"] == "project":
        _sync_project_status(conn, wi["ParentID"])
    if parent_type and parent_type == "project" and parent_id and (not wi or parent_id != wi["ParentID"]):
        _sync_project_status(conn, parent_id)
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/workitems/<int:iid>/status", methods=["PATCH"])
def api_workitem_status(iid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE BOA.WIT.WorkItem SET Status=?,UpdatedAt=GETDATE() WHERE ItemID=?", (data.get("status"), iid))
    conn.commit()
    wi = conn.execute("SELECT ParentType, ParentID FROM BOA.WIT.WorkItem WHERE ItemID=?", (iid,)).fetchone()
    if wi and wi["ParentType"] == "project":
        _sync_project_status(conn, wi["ParentID"])
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/workitems/<int:iid>", methods=["DELETE"])
def api_workitem_delete(iid):
    conn = get_db()
    wi = conn.execute("SELECT ParentType, ParentID FROM BOA.WIT.WorkItem WHERE ItemID=?", (iid,)).fetchone()
    conn.execute("UPDATE BOA.WIT.WorkItem SET IsActive=0 WHERE ItemID=?", (iid,))
    conn.commit()
    if wi and wi["ParentType"] == "project":
        _sync_project_status(conn, wi["ParentID"])
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/workitems/<int:iid>/prerequisites", methods=["POST"])
def api_workitem_add_prereq(iid):
    data = request.get_json(silent=True) or {}
    req_id = data.get("requires_item_id")
    conn = get_db()
    if not conn.execute("SELECT LinkID FROM BOA.WIT.WorkItemPrerequisite WHERE ItemID=? AND RequiresItemID=? AND IsActive=1", (iid, req_id)).fetchone():
        conn.execute("INSERT INTO BOA.WIT.WorkItemPrerequisite (ItemID,RequiresItemID) VALUES (?,?)", (iid, req_id))
        conn.commit()
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/workitems/<int:iid>/prerequisites/<int:req_id>", methods=["DELETE"])
def api_workitem_remove_prereq(iid, req_id):
    conn = get_db()
    conn.execute("UPDATE BOA.WIT.WorkItemPrerequisite SET IsActive=0 WHERE ItemID=? AND RequiresItemID=?", (iid, req_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/subitems", methods=["POST"])
def api_subitem_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("INSERT INTO BOA.WIT.WorkSubItem (ParentItemID,Title,Deadline,SortOrder) VALUES (?,?,?,?)",
                 (data.get("parent_item_id"), data.get("title",""), data.get("deadline") or None, data.get("sort_order",0)))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/subitems/<int:sid>/status", methods=["PATCH"])
def api_subitem_status(sid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE BOA.WIT.WorkSubItem SET Status=? WHERE SubItemID=?", (data.get("status"), sid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/api/subitems/<int:sid>", methods=["DELETE"])
def api_subitem_delete(sid):
    conn = get_db()
    conn.execute("UPDATE BOA.WIT.WorkSubItem SET IsActive=0 WHERE SubItemID=?", (sid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@work_items_bp.route("/backlog")
def global_backlog():
    conn = get_db()
    items = conn.execute(load_query("wit_global_backlog")).fetchall()
    stakeholders = conn.execute("SELECT StakeholderID, FullName FROM BOA.ZZZ.Stakeholder WHERE IsActive=1 ORDER BY FullName").fetchall()
    users        = conn.execute("SELECT id, username, surname FROM BOA.COR.[User] ORDER BY username").fetchall()
    projects     = conn.execute("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE IsActive=1 ORDER BY ProjectName").fetchall()
    syndications = conn.execute(
        "SELECT m.DealId, c.CustomerName + ' / Syndication #' + CAST(m.DealId AS NVARCHAR) AS DisplayName "
        "FROM BOA.STR.MainDeals m "
        "JOIN BOA.CUS.Customer c ON m.CustomerId = c.Customerid "
        "WHERE m.ProductCode = 'SYNDICATION' "
        "ORDER BY m.DealId"
    ).fetchall()
    conn.close()
    from datetime import datetime as _dt
    return render_template(
        "work_items/backlog.html",
        items=items,
        stakeholders=stakeholders,
        users=users,
        projects=projects,
        syndications=syndications,
        now=_dt.utcnow()
    )
