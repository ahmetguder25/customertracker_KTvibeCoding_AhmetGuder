from flask import Blueprint, render_template, request, jsonify, session
from core.db import get_db
from core.utils import get_param_map, _recalc_all_krs, _load_backlog

okrs_bp = Blueprint("okrs", __name__)

@okrs_bp.route("/okrs")
def okrs_list():
    conn = get_db()
    _recalc_all_krs(conn)
    objectives = conn.execute("SELECT * FROM BOA.ZZZ.Objective WHERE IsActive=1 ORDER BY Period DESC, ObjectiveID").fetchall()
    krs        = conn.execute("SELECT * FROM BOA.ZZZ.KeyResult WHERE IsActive=1 ORDER BY ObjectiveID, KRID").fetchall()
    products   = conn.execute("SELECT * FROM BOA.COR.Product WHERE IsActive=1").fetchall()
    projects   = conn.execute("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE IsActive=1 ORDER BY ProjectName").fetchall()
    status_map = get_param_map("Status", conn)
    conn.close()
    return render_template("okrs/okrs.html", objectives=objectives, krs=krs,
                           products=products, projects=projects, status_map=status_map)

@okrs_bp.route("/api/okrs/objectives", methods=["POST"])
def api_objective_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("INSERT INTO BOA.ZZZ.Objective (Title,Description,Period,Owner) VALUES (?,?,?,?)",
                 (data.get("title",""), data.get("description",""), data.get("period",""), session.get("username","")))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/okrs/objectives/<int:oid>", methods=["DELETE"])
def api_objective_delete(oid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Objective SET IsActive=0 WHERE ObjectiveID=?", (oid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/okrs/krs", methods=["POST"])
def api_kr_create():
    import json as _json
    data = request.get_json(silent=True) or {}
    mtype           = data.get("measurement_type", "manual")
    linked_product  = data.get("linked_product_code") or None
    linked_statuses = _json.dumps(data.get("linked_status_codes", [])) if data.get("linked_status_codes") else None
    linked_project  = data.get("linked_project_id") or None
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.KeyResult "
        "(ObjectiveID,Title,TargetValue,Unit,CalcMethod,MeasurementType,LinkedProductCode,LinkedStatusCodes,LinkedProjectID) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (data.get("objective_id"), data.get("title",""), float(data.get("target",0)),
         data.get("unit",""), data.get("calc_method","manual"),
         mtype, linked_product, linked_statuses, linked_project)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/okrs/krs/<int:krid>", methods=["PATCH"])
def api_kr_update(krid):
    import json as _json
    data = request.get_json(silent=True) or {}
    conn = get_db()
    kr = conn.execute("SELECT * FROM BOA.ZZZ.KeyResult WHERE KRID=?", (krid,)).fetchone()
    if not kr:
        conn.close()
        return jsonify({"ok": False, "error": "KR not found"}), 404

    mtype = data.get("measurement_type", kr["MeasurementType"] or "manual")
    achieved  = float(data.get("achieved",  kr["AchievedValue"]  or 0))
    pipeline  = float(data.get("pipeline",  kr["PipelineValue"]  or 0))

    linked_product  = data.get("linked_product_code") or None
    linked_statuses = _json.dumps(data.get("linked_status_codes", [])) if data.get("linked_status_codes") else None
    linked_project  = data.get("linked_project_id") or None

    conn.execute(
        "UPDATE BOA.ZZZ.KeyResult SET "
        "Title=?, TargetValue=?, Unit=?, CalcMethod=?, "
        "MeasurementType=?, LinkedProductCode=?, LinkedStatusCodes=?, LinkedProjectID=?, "
        "AchievedValue=?, PipelineValue=? "
        "WHERE KRID=?",
        (
            data.get("title", kr["Title"]),
            float(data.get("target", kr["TargetValue"] or 0)),
            data.get("unit", kr["Unit"] or ""),
            data.get("calc_method", kr["CalcMethod"] or "manual"),
            mtype, linked_product, linked_statuses, linked_project,
            achieved, pipeline,
            krid
        )
    )
    conn.commit()
    if mtype in ("product", "project"):
        _recalc_all_krs(conn)
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/okrs/krs/<int:krid>", methods=["DELETE"])
def api_kr_delete(krid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.KeyResult SET IsActive=0 WHERE KRID=?", (krid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/okrs/recalculate", methods=["POST"])
def api_okrs_recalculate():
    conn = get_db()
    _recalc_all_krs(conn)
    conn.close()
    return jsonify({"ok": True})

def _compute_project_status(total_items, done_items, in_progress_items=0):
    if total_items == 0:
        return "Not Started", 0
    if done_items >= total_items:
        return "Completed", 100
    if done_items > 0 or in_progress_items > 0:
        pct = int(done_items / total_items * 100)
        return "Active", pct
    return "Not Started", 0

def _sync_project_status(conn, project_id):
    row = conn.execute(
        "SELECT "
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem WHERE ParentType='project' AND ParentID=? AND IsActive=1) AS total_items, "
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem WHERE ParentType='project' AND ParentID=? AND IsActive=1 AND Status='done') AS done_items, "
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem WHERE ParentType='project' AND ParentID=? AND IsActive=1 AND Status IN ('in_progress','blocked')) AS in_progress_items",
        (project_id, project_id, project_id)
    ).fetchone()
    status, _ = _compute_project_status(
        row["total_items"] or 0, row["done_items"] or 0, row["in_progress_items"] or 0
    )
    conn.execute(
        "UPDATE BOA.ZZZ.Project SET Status=?, UpdatedAt=GETDATE() WHERE ProjectID=?",
        (status, project_id)
    )
    conn.commit()

@okrs_bp.route("/projects")
def projects_list():
    conn = get_db()
    projects_raw = conn.execute(
        "SELECT p.*, o.Title AS ObjTitle, "
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem w WHERE w.ParentType='project' AND w.ParentID=p.ProjectID AND w.IsActive=1) AS total_items,"
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem w WHERE w.ParentType='project' AND w.ParentID=p.ProjectID AND w.IsActive=1 AND w.Status='done') AS done_items, "
        "  (SELECT COUNT(*) FROM BOA.WIT.WorkItem w WHERE w.ParentType='project' AND w.ParentID=p.ProjectID AND w.IsActive=1 AND w.Status IN ('in_progress','blocked')) AS in_progress_items "
        "FROM BOA.ZZZ.Project p LEFT JOIN BOA.ZZZ.Objective o ON p.ObjectiveID=o.ObjectiveID "
        "WHERE p.IsActive=1 ORDER BY p.CreatedAt DESC"
    ).fetchall()
    projects = []
    for p in projects_raw:
        d = dict(p)
        d["computed_status"], d["progress_pct"] = _compute_project_status(
            d["total_items"] or 0, d["done_items"] or 0, d["in_progress_items"] or 0
        )
        projects.append(d)
    objectives = conn.execute("SELECT ObjectiveID, Title FROM BOA.ZZZ.Objective WHERE IsActive=1 ORDER BY Title").fetchall()
    conn.close()
    return render_template("okrs/projects.html", projects=projects, objectives=objectives)

@okrs_bp.route("/projects/<int:project_id>")
def project_detail(project_id):
    conn = get_db()
    project_row = conn.execute(
        "SELECT p.*, o.Title AS ObjTitle FROM BOA.ZZZ.Project p "
        "LEFT JOIN BOA.ZZZ.Objective o ON p.ObjectiveID=o.ObjectiveID "
        "WHERE p.ProjectID=? AND p.IsActive=1", (project_id,)
    ).fetchone()
    if not project_row:
        conn.close()
        return "Project not found", 404
    items, prereq_map, subitems_map, assignees_map = _load_backlog(conn, "project", project_id)
    stakeholders = conn.execute("SELECT StakeholderID, FullName, Organization FROM BOA.ZZZ.Stakeholder WHERE IsActive=1 ORDER BY FullName").fetchall()
    users = conn.execute("SELECT id, username, surname FROM BOA.COR.[User] ORDER BY username").fetchall()
    objectives = conn.execute("SELECT ObjectiveID, Title FROM BOA.ZZZ.Objective WHERE IsActive=1 ORDER BY Title").fetchall()
    done_count  = sum(1 for i in items if i["Status"] == "done")
    in_progress_count = sum(1 for i in items if i["Status"] in ("in_progress", "blocked"))
    total_count = len(items)
    computed_status, progress_pct = _compute_project_status(total_count, done_count, in_progress_count)
    project = dict(project_row)
    project["computed_status"] = computed_status
    project["progress_pct"]    = progress_pct
    conn.close()
    return render_template(
        "okrs/project_detail.html",
        project=project,
        items=items,
        prereq_map=prereq_map,
        subitems_map=subitems_map,
        assignees_map=assignees_map,
        stakeholders=stakeholders,
        users=users,
        objectives=objectives,
        done_count=done_count,
        total_count=total_count,
        progress_pct=progress_pct
    )

@okrs_bp.route("/api/projects", methods=["POST"])
def api_project_create():
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "INSERT INTO BOA.ZZZ.Project (ProjectName,Description,Status,Owner,StartDate,Deadline,ObjectiveID) VALUES (?,?,?,?,?,?,?)",
        (data.get("name",""), data.get("description",""), "Not Started",
         session.get("username",""), data.get("start_date") or None, data.get("deadline") or None, data.get("objective_id") or None)
    )
    conn.commit()
    pid = conn.execute("SELECT MAX(ProjectID) AS id FROM BOA.ZZZ.Project").fetchone()["id"]
    conn.close()
    return jsonify({"ok": True, "project_id": pid})

@okrs_bp.route("/api/projects/<int:pid>", methods=["PATCH"])
def api_project_update(pid):
    data = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute(
        "UPDATE BOA.ZZZ.Project SET ProjectName=?,Description=?,Deadline=?,ObjectiveID=?,UpdatedAt=GETDATE() WHERE ProjectID=?",
        (data.get("name"), data.get("description"), data.get("deadline") or None, data.get("objective_id") or None, pid)
    )
    _sync_project_status(conn, pid)
    conn.close()
    return jsonify({"ok": True})

@okrs_bp.route("/api/projects/<int:pid>", methods=["DELETE"])
def api_project_delete(pid):
    conn = get_db()
    conn.execute("UPDATE BOA.ZZZ.Project SET IsActive=0 WHERE ProjectID=?", (pid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
