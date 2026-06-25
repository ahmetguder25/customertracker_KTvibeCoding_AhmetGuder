import os
from datetime import datetime, timedelta
from flask import session, has_request_context
from .config import QUERY_DIR, ALLOWED_EXTENSIONS
from .db import get_db

def load_query(name: str, query_dir: str = None) -> str:
    """Load SQL from <query_dir>/<name>.sql.  Defaults to the main queries/ dir.
    Pass an explicit query_dir (e.g. admin/queries/) to load module-specific SQL.
    No caching — edit files live."""
    directory = query_dir if query_dir is not None else QUERY_DIR
    path = os.path.join(directory, name + ".sql")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

def to_tr_time(t_str):
    """Converts UTC SQLite timestamp to Istanbul time (+3) → YYYY-MM-DD HH:MM"""
    if not t_str:
        return ""
    try:
        dt = datetime.strptime(str(t_str)[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        dt += timedelta(hours=3)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(t_str)[:16]

def _fmt_dt(v, chars):
    """Format a date/datetime value (datetime obj or string) to a fixed-length string.
    Works with both pymssql datetime objects and plain strings."""
    if not v:
        return ""
    try:
        return str(v)[:chars]
    except Exception:
        return ""

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_param_map(param_type, conn=None):
    """Load parameter dict keyed by ParamCode for a given ParamType."""
    close_conn = conn is None
    if close_conn:
        conn = get_db()
    lang_id = session.get("lang", 2) if has_request_context() else 2
    rows = conn.execute(load_query("get_parameters"), (param_type, lang_id)).fetchall()
    if close_conn:
        conn.close()
    return {
        str(r["ParamCode"]): {
            "code":        str(r["ParamCode"]),
            "description": r["ParamDescription"],
            "bg":          r["ParamValue"]  or "bg-gray-500/20",
            "text":        r["ParamValue2"] or "text-gray-400",
            "logo":        r["ParamValue3"] or "",
        }
        for r in rows
    }

_PARENT_TYPES = ("project", "syndication")

def _load_backlog(conn, parent_type, parent_id):
    """Load work items and related data for a specific parent (project or syndication)."""
    items = conn.execute(
        "SELECT * FROM BOA.WIT.WorkItem WHERE ParentType=? AND ParentID=? AND IsActive=1 ORDER BY SortOrder, Deadline, ItemID",
        (parent_type, parent_id)
    ).fetchall()
    item_ids = [i["ItemID"] for i in items]
    prereq_map, subitems_map, assignees_map = {}, {}, {}
    if item_ids:
        ph = ",".join("?" * len(item_ids))
        for p in conn.execute(f"SELECT ItemID,RequiresItemID FROM BOA.WIT.WorkItemPrerequisite WHERE ItemID IN ({ph}) AND IsActive=1", item_ids).fetchall():
            prereq_map.setdefault(p["ItemID"], []).append(p["RequiresItemID"])
        for s in conn.execute(f"SELECT * FROM BOA.WIT.WorkSubItem WHERE ParentItemID IN ({ph}) AND IsActive=1 ORDER BY SortOrder,SubItemID", item_ids).fetchall():
            subitems_map.setdefault(s["ParentItemID"], []).append(dict(s))
        for a in conn.execute(
            f"SELECT wa.ItemID, COALESCE(s.FullName, u.username + ' ' + ISNULL(u.surname, '')) AS AssigneeName "
            f"FROM BOA.WIT.WorkItemAssignee wa "
            f"LEFT JOIN BOA.COR.Stakeholder s ON wa.StakeholderID = s.StakeholderID "
            f"LEFT JOIN BOA.COR.[User] u ON wa.UserID = u.id "
            f"WHERE wa.ItemID IN ({ph}) AND wa.IsActive=1", item_ids
        ).fetchall():
            assignees_map.setdefault(a["ItemID"], []).append(a["AssigneeName"])
    return items, prereq_map, subitems_map, assignees_map


def _load_backlog_json(conn, parent_type, parent_id):
    """Load work items as dicts for JSON API responses (portal panels)."""
    items, prereq_map, subitems_map, assignees_map = _load_backlog(conn, parent_type, parent_id)
    result = []
    for item in items:
        d = dict(item)
        d["Deadline"] = str(d["Deadline"]) if d["Deadline"] else None
        d["CreatedAt"] = str(d["CreatedAt"]) if d["CreatedAt"] else None
        d["UpdatedAt"] = str(d["UpdatedAt"]) if d["UpdatedAt"] else None
        d["prereqs"] = prereq_map.get(item["ItemID"], [])
        d["subitems"] = subitems_map.get(item["ItemID"], [])
        d["assignees"] = assignees_map.get(item["ItemID"], [])
        # Serialise subitems
        serialised_subs = []
        for s in d["subitems"]:
            sc = dict(s)
            sc["Deadline"] = str(sc["Deadline"]) if sc["Deadline"] else None
            sc["CreatedAt"] = str(sc["CreatedAt"]) if sc["CreatedAt"] else None
            serialised_subs.append(sc)
        d["subitems"] = serialised_subs
        result.append(d)
    return result

def _recalc_all_krs(conn):
    """Auto-recalculate AchievedValue for all active auto-measurement KRs."""
    krs = conn.execute(
        "SELECT * FROM BOA.WIT.KeyResult WHERE IsActive=1 AND MeasurementType IN ('product','project')"
    ).fetchall()
    for kr in krs:
        new_val = None
        try:
            if kr["MeasurementType"] == "product" and kr["LinkedProductCode"] and kr["LinkedStatusCodes"]:
                import json
                status_codes = json.loads(kr["LinkedStatusCodes"])
                if status_codes:
                    placeholders = ",".join(["?" for _ in status_codes])
                    params = [kr["LinkedProductCode"]] + status_codes
                    row = conn.execute(
                        f"SELECT COALESCE(SUM(s.Amount),0) AS total "
                        f"FROM BOA.STR.MainDeals m "
                        f"JOIN BOA.STR.Syndication s ON m.DealId = s.DealId "
                        f"WHERE m.ProductCode=? AND s.Status IN ({placeholders})",
                        params
                    ).fetchone()
                    new_val = float(row["total"]) if row else 0.0

            elif kr["MeasurementType"] == "project" and kr["LinkedProjectID"]:
                # Project % done = closed work items / total work items * TargetValue
                total_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM BOA.WIT.WorkItem WHERE ParentType='project' AND ParentID=? AND IsActive=1",
                    (kr["LinkedProjectID"],)
                ).fetchone()
                done_row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM BOA.WIT.WorkItem WHERE ParentType='project' AND ParentID=? AND IsActive=1 AND Status='done'",
                    (kr["LinkedProjectID"],)
                ).fetchone()
                total_cnt = total_row["cnt"] if total_row else 0
                done_cnt  = done_row["cnt"]  if done_row  else 0
                pct = (done_cnt / total_cnt * 100.0) if total_cnt > 0 else 0.0
                new_val = round(pct * float(kr["TargetValue"]) / 100.0, 2)

            if new_val is not None:
                conn.execute(
                    "UPDATE BOA.WIT.KeyResult SET AchievedValue=? WHERE KRID=?",
                    (new_val, kr["KRID"])
                )
        except Exception as e:
            print(f"[recalc] KR {kr['KRID']} error: {e}")
    conn.commit()
