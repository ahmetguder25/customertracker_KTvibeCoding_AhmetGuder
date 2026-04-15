"""data_agent_orchestrator.py

Natural Language Data Agent — converts free-form text into confirmed DB actions.

Architecture (per message turn):
  Phase 1 — Intent Extraction   : LLM reads the text → structured JSON actions
  Phase 2 — Entity Resolution   : fuzzy DB lookup to find customer IDs
  Phase 3 — Context Reading     : fetch existing deals/comments for dedup awareness
  Phase 4 — Field Checking      : build clarification queue for missing required fields
  Phase 5 — Execution           : run DB INSERT after per-action user confirmation

Agent behaviour is controlled entirely by:
  knowledge_base/intent_parser_logic.txt
Edit that file to change extraction rules, action types, and output format.
"""

import os
import json
import requests
from datetime import datetime

from ollama_config import (
    OLLAMA_URL,
    DATA_AGENT_MODEL,
    DATA_AGENT_TIMEOUT,
    KNOWLEDGE_BASE_DIR,
)

# ---------------------------------------------------------------------------
# Status + DealType maps (must match Parameter table in DB)
# Modify here if new codes are added to the Parameter table.
# ---------------------------------------------------------------------------

STATUS_MAP = {
    "lead":           1,
    "proposal":       2,
    "due diligence":  3,
    "dd":             3,
    "closed won":     4,
    "won":            4,
    "closed lost":    5,
    "lost":           5,
}

STATUS_LABELS = {
    1: "Lead",
    2: "Proposal",
    3: "Due Diligence",
    4: "Closed Won",
    5: "Closed Lost",
}

DEALTYPE_MAP = {
    "syndication": 1,
    "bahrain":     2,
    "sukuk":       3,
    "kt ag":       4,
}

DEALTYPE_LABELS = {
    1: "Syndication",
    2: "Bahrain",
    3: "Sukuk",
    4: "KT AG",
}

# Currency codes (FEC parameter — 0=TRY, 1=USD, 19=EUR)
CURRENCY_MAP = {
    "try": 0,  "tl": 0,  "lira": 0,  "turkish lira": 0,
    "usd": 1,  "dollar": 1,  "dollars": 1,
    "eur": 19, "euro": 19, "euros": 19,
}

CURRENCY_LABELS = {0: "TRY", 1: "USD", 19: "EUR"}


def _load_logic(base_dir: str) -> str:
    path = os.path.join(base_dir, KNOWLEDGE_BASE_DIR, "intent_parser_logic.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "[ERROR: intent_parser_logic.txt not found]"


def _ollama(prompt: str, base_dir: str) -> str:
    url = OLLAMA_URL if "api/generate" in OLLAMA_URL else f"{OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {
        "model":  DATA_AGENT_MODEL,
        "stream": False,
        "prompt": prompt,
    }
    resp = requests.post(url, json=payload, timeout=DATA_AGENT_TIMEOUT)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


# ---------------------------------------------------------------------------
# Phase 1 — Intent Extraction
# ---------------------------------------------------------------------------

def extract_intents(text: str, base_dir: str) -> dict:
    """
    Call the LLM with the intent_parser_logic.txt rules and the user's text.
    Returns a dict with keys: language, actions (list of dicts).
    On failure returns {"language": "en", "actions": [], "error": "..."}.
    """
    logic = _load_logic(base_dir)
    prompt = (
        f"{logic}\n\n"
        "---\n\n"
        "Now parse the following user input and return ONLY the JSON object. "
        "No explanation. No markdown. Raw JSON only.\n\n"
        f"User input: {text}"
    )
    try:
        raw = _ollama(prompt, base_dir)
        # Strip markdown code fences if model wraps it
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        result = json.loads(clean.strip())
        if "actions" not in result:
            result["actions"] = []
        if "language" not in result:
            result["language"] = "en"
        return result
    except Exception as e:
        return {"language": "en", "actions": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Phase 2 — Entity Resolution
# ---------------------------------------------------------------------------

def resolve_entities(actions: list, conn) -> tuple:
    """
    For each action, fuzzy-search the Customer table for the customer_name.
    Returns (resolved_actions, clarification_queue).

    resolved_actions: list of actions with customer_id filled or None if ambiguous.
    clarification_queue: list of {action_index, field, question, options} dicts.
    """
    resolved = []
    clarifications = []

    for i, action in enumerate(actions):
        a = dict(action)
        name = a.get("customer_name", "").strip()
        if not name:
            clarifications.append({
                "action_index": i,
                "field": "customer_name",
                "question": "Which customer does this action relate to?",
                "options": [],
            })
            a["customer_id"] = None
            resolved.append(a)
            continue

        # Fuzzy search — progressive loosening:
        #  1. Exact match (case-insensitive)
        #  2. LIKE with extracted name
        #  3. Strip possessive 's / s ("ABCs" → "ABC") and retry LIKE
        #  4. Strip last word ("ABC AS Company" → "ABC AS") and retry LIKE
        rows = conn.execute(
            "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
            "WHERE IsStructured = 1 AND LOWER(CustomerName) = LOWER(?)",
            (name,)
        ).fetchall()

        if not rows:
            rows = conn.execute(
                "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
                "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)",
                (f"%{name}%",)
            ).fetchall()

        # Strip possessive: "ABCs" → "ABC", "ABC's" → "ABC"
        if not rows:
            stripped = name.rstrip("s").rstrip("'").strip()
            if stripped and stripped != name:
                rows = conn.execute(
                    "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
                    "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)",
                    (f"%{stripped}%",)
                ).fetchall()

        # Drop last word: "ABC Energy Corp" → "ABC Energy"
        if not rows and " " in name:
            shorter = name.rsplit(" ", 1)[0].strip()
            rows = conn.execute(
                "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
                "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)",
                (f"%{shorter}%",)
            ).fetchall()

        if len(rows) == 1:
            a["customer_id"]   = rows[0]["Customerid"]
            a["customer_name"] = rows[0]["CustomerName"]  # use canonical name
        elif len(rows) == 0:
            clarifications.append({
                "action_index": i,
                "field": "customer_name",
                "question": f'No customer found matching "{name}". Which customer did you mean?',
                "options": [],
                "no_match": True,
            })
            a["customer_id"] = None
        else:
            options = [{"id": r["Customerid"], "label": r["CustomerName"]} for r in rows[:6]]
            clarifications.append({
                "action_index": i,
                "field": "customer_name",
                "question": f'Multiple customers match "{name}". Which one?',
                "options": options,
            })
            a["customer_id"] = None

        resolved.append(a)

    return resolved, clarifications


# ---------------------------------------------------------------------------
# Phase 3 — Context Reading
# ---------------------------------------------------------------------------

def read_context(actions: list, conn) -> list:
    """
    For each action that has a resolved customer_id, fetch recent deals and comments
    and attach as 'context' for the planning step / dedup display.
    """
    enriched = []
    for action in actions:
        a = dict(action)
        cid = a.get("customer_id")
        if cid:
            deals = conn.execute(
                "SELECT TOP 5 id, deal_size, currency, status, dealtype, notes, created_at "
                "FROM BOA.ZZZ.CustomerDeals WHERE customerid = ? ORDER BY created_at DESC",
                (cid,)
            ).fetchall()
            comments = conn.execute(
                "SELECT TOP 3 id, content, created_at FROM BOA.ZZZ.Comment "
                "WHERE customer_id = ? ORDER BY created_at DESC",
                (cid,)
            ).fetchall()
            a["context"] = {
                "recent_deals":    [dict(d) for d in deals],
                "recent_comments": [dict(c) for c in comments],
            }
        else:
            a["context"] = {}
        enriched.append(a)
    return enriched


# ---------------------------------------------------------------------------
# Phase 4 — Field Checking
# ---------------------------------------------------------------------------

def check_required_fields(actions: list, conn=None) -> list:
    """
    For each action that is ready (has customer_id), check for missing required fields.
    Returns a list of clarification dicts: {action_index, field, question, options}.

    NOT-NULL columns in CustomerDeals that must be supplied:
      contact_name, deal_size, currency (int code), status
    """
    clarifications = []
    for i, action in enumerate(actions):
        if action.get("customer_id") is None:
            continue  # already queued for entity clarification

        atype = action.get("type")

        if atype == "update_deal":
            cname = action.get("customer_name", "this deal")
            if action.get("deal_id") is None and conn is not None:
                # Fetch all deals for this customer
                rows = conn.execute(
                    "SELECT TOP 10 id, contact_name, deal_size, currency, status, dealtype, notes "
                    "FROM BOA.ZZZ.CustomerDeals WHERE customerid = ? ORDER BY created_at DESC",
                    (action["customer_id"],)
                ).fetchall()

                # ── Apply filter context extracted by LLM ──────────────────
                # filter_* fields narrow down WHICH deal without asking the user.
                # Each filter is applied independently; only accepted if it keeps
                # at least one row (avoids over-filtering on ambiguous data).
                filtered = list(rows)

                fdt = (action.get("filter_dealtype") or "").lower().strip()
                if fdt:
                    dt_code = DEALTYPE_MAP.get(fdt)
                    if dt_code is not None:
                        candidate = [r for r in filtered if str(r["dealtype"]) == str(dt_code)]
                        if candidate:
                            filtered = candidate

                fst = (action.get("filter_status") or "").lower().strip()
                if fst:
                    st_code = STATUS_MAP.get(fst)
                    if st_code is not None:
                        candidate = [r for r in filtered if r["status"] == st_code]
                        if candidate:
                            filtered = candidate

                fco = (action.get("filter_contact") or "").lower().strip()
                if fco:
                    candidate = [r for r in filtered
                                 if fco in (r["contact_name"] or "").lower()]
                    if candidate:
                        filtered = candidate

                fsz = action.get("filter_size_approx")
                if fsz:
                    try:
                        fsz_f = float(fsz)
                        candidate = [r for r in filtered
                                     if r["deal_size"] and
                                     abs(float(r["deal_size"]) - fsz_f) / max(fsz_f, 1) <= 0.20]
                        if candidate:
                            filtered = candidate
                    except (TypeError, ValueError):
                        pass

                # ── Fallback: use dealtype_hint as a filter if filter_dealtype is absent ──
                # Handles the common LLM error of putting a descriptive deal type
                # (e.g. "sukuk deal completed") into dealtype_hint instead of filter_dealtype.
                # Safety guard: only apply when at least one OTHER update field exists
                # (status_hint, deal_size, contact_name, notes) so we don’t accidentally
                # filter when the user’s intent is purely to CHANGE the deal type.
                if len(filtered) > 1 and not fdt:
                    dth = (action.get("dealtype_hint") or "").lower().strip()
                    other_updates = any([
                        action.get("status_hint"),
                        action.get("deal_size"),
                        action.get("contact_name"),
                        action.get("notes"),
                    ])
                    if dth and other_updates:
                        dt_code = DEALTYPE_MAP.get(dth)
                        if dt_code is not None:
                            candidate = [r for r in filtered if str(r["dealtype"]) == str(dt_code)]
                            if candidate:
                                filtered = candidate
                # ────────────────────────────────────────────────────────────

                rows = filtered  # use narrowed list for the decision below

                if len(rows) == 0:
                    clarifications.append({
                        "action_index": i,
                        "field": "deal_id",
                        "question": f'No existing deals found for **{cname}**. Nothing to update.',
                        "options": [],
                        "no_match": True,
                    })
                elif len(rows) == 1:
                    action["deal_id"] = rows[0]["id"]  # auto-select — filters resolved ambiguity
                    _cache_current(action, rows[0])     # store current values for from→to display
                else:
                    options = [
                        {
                            "id": str(r["id"]),
                            "label": f'#{r["id"]} — {STATUS_LABELS.get(r["status"], "?")}'
                                     + (f' · {r["deal_size"]:,.0f} {CURRENCY_LABELS.get(r["currency"], "?")}' if r["deal_size"] else '')
                                     + (f' · {r["contact_name"]}' if r["contact_name"] else ''),
                        }
                        for r in rows
                    ]
                    clarifications.append({
                        "action_index": i,
                        "field": "deal_id",
                        "question": f'**{cname}** has multiple matching deals. Which one do you want to update?',
                        "options": options,
                    })
            continue  # update_deal has no NOT NULL field requirements beyond deal selection

        if atype == "query_deals":
            continue  # read-only, no field checks needed

        if atype == "insert_deal":
            cname = action.get("customer_name", "this deal")

            # 1. contact_name — NOT NULL
            if not (action.get("contact_name") or "").strip():
                clarifications.append({
                    "action_index": i,
                    "field": "contact_name",
                    "question": f'Who is the contact person for the deal with **{cname}**?',
                    "options": [],
                })

            # 2. deal_size — NOT NULL
            if action.get("deal_size") is None:
                clarifications.append({
                    "action_index": i,
                    "field": "deal_size",
                    "question": f'What is the deal size for **{cname}**? (e.g. 500000 or 1.5m)',
                    "options": [],
                })

            # 3. currency — NOT NULL (stored as int code: 0=TRY, 1=USD, 19=EUR)
            if not (action.get("currency") or "").strip():
                clarifications.append({
                    "action_index": i,
                    "field": "currency",
                    "question": f'What is the currency for the deal with **{cname}**?',
                    "options": [{"id": str(k), "label": v} for k, v in CURRENCY_LABELS.items()],
                })

            # 4. status — NOT NULL
            if not action.get("status_hint"):
                clarifications.append({
                    "action_index": i,
                    "field": "status_hint",
                    "question": f'What is the deal status for **{cname}**?',
                    "options": [{"id": str(v), "label": l} for v, l in STATUS_LABELS.items()],
                })

        elif atype == "insert_comment":
            # comment_text is always set by LLM; nothing extra required
            pass

    return clarifications


# ---------------------------------------------------------------------------
# Phase 5 — Execution
# ---------------------------------------------------------------------------

def execute_action(action: dict, conn, author: str = "Agent") -> dict:
    """
    Execute a single confirmed action against the database.
    Returns {"success": bool, "message": str}.
    """
    atype      = action.get("type")
    cid        = action.get("customer_id")
    cname      = action.get("customer_name", "Unknown")

    try:
        if atype == "insert_deal":
            deal_size    = action.get("deal_size") or None
            contact_name = (action.get("contact_name") or "").strip() or None
            notes        = action.get("notes") or None

            # Resolve status code
            status_hint = (action.get("status_hint") or "Lead").lower().strip()
            status_code = STATUS_MAP.get(status_hint, 1)

            # Resolve dealtype code
            type_hint   = (action.get("dealtype_hint") or "").lower().strip()
            type_code   = DEALTYPE_MAP.get(type_hint) or None

            # Resolve currency string → int code (0=TRY, 1=USD, 19=EUR)
            currency_raw  = (action.get("currency") or "").strip().lower()
            currency_code = CURRENCY_MAP.get(currency_raw, 0)  # default TRY

            # pricing: not extracted by LLM but required by schema as nullable
            pricing = action.get("expected_pricing_pa") or None

            conn.execute(
                "INSERT INTO BOA.ZZZ.CustomerDeals "
                "(customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, contact_name, deal_size, pricing, currency_code, status_code, type_code, notes)
            )
            conn.commit()
            status_label = STATUS_LABELS.get(status_code, str(status_code))
            return {
                "success": True,
                "message": f'Deal inserted for **{cname}** (Status: {status_label}' +
                           (f', {deal_size:,} {currency}' if deal_size else '') + ').',
            }

        elif atype == "insert_comment":
            text = action.get("comment_text", "").strip()
            if not text:
                return {"success": False, "message": "Comment text is empty."}

            date_hint = action.get("comment_date_hint", "")
            full_text = text
            if date_hint:
                full_text = f"[{date_hint}] {text}"

            conn.execute(
                "INSERT INTO BOA.ZZZ.Comment (customer_id, author, content) VALUES (?, ?, ?)",
                (cid, author, full_text)
            )
            conn.commit()
            return {
                "success": True,
                "message": f'Comment added for **{cname}**.',
            }

        elif atype == "query_deals":
            rows = conn.execute(
                "SELECT d.id, d.contact_name, d.deal_size, d.currency, d.status, "
                "d.dealtype, d.notes, d.created_at "
                "FROM BOA.ZZZ.CustomerDeals d "
                "WHERE d.customerid = ? ORDER BY d.created_at DESC",
                (cid,)
            ).fetchall()
            if not rows:
                return {"success": True, "message": f'No deals found for **{cname}**.', "deals": []}
            deal_list = []
            for r in rows:
                status_lbl  = STATUS_LABELS.get(r["status"], str(r["status"]))
                _dt         = r["dealtype"]
                type_lbl    = DEALTYPE_LABELS.get(int(_dt), str(_dt)) if _dt is not None else "—"
                curr_lbl    = CURRENCY_LABELS.get(r["currency"], str(r["currency"]) if r["currency"] is not None else "—")
                size_str    = f"{r['deal_size']:,.0f} {curr_lbl}" if r["deal_size"] else "—"
                deal_list.append({
                    "id":           r["id"],
                    "contact":      r["contact_name"] or "—",
                    "size":         size_str,
                    "status":       status_lbl,
                    "type":         type_lbl,
                    "notes":        (r["notes"] or "")[:120],
                })
            return {"success": True, "message": f'Found {len(deal_list)} deal(s) for **{cname}**.', "deals": deal_list}

        elif atype == "update_deal":
            deal_id = action.get("deal_id")
            if not deal_id:
                return {"success": False, "message": "No deal selected to update."}

            # Fetch current values
            current = conn.execute(
                "SELECT contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes "
                "FROM BOA.ZZZ.CustomerDeals WHERE id = ?",
                (deal_id,)
            ).fetchone()
            if not current:
                return {"success": False, "message": f"Deal #{deal_id} not found."}

            # Overlay only the fields present in this action
            status_hint  = action.get("status_hint")
            type_hint    = action.get("dealtype_hint")
            currency_raw = (action.get("currency") or "").strip().lower()

            new_contact  = (action.get("contact_name") or "").strip() or current["contact_name"]
            new_size     = action.get("deal_size") if action.get("deal_size") is not None else current["deal_size"]
            new_pricing  = action.get("expected_pricing_pa") if action.get("expected_pricing_pa") is not None else current["expected_pricing_pa"]
            new_currency = CURRENCY_MAP.get(currency_raw, current["currency"]) if currency_raw else current["currency"]
            new_status   = STATUS_MAP.get((status_hint or "").lower().strip(), current["status"]) if status_hint else current["status"]
            new_dealtype = DEALTYPE_MAP.get((type_hint or "").lower().strip(), current["dealtype"]) if type_hint else current["dealtype"]
            new_notes    = action.get("notes") if action.get("notes") is not None else current["notes"]

            conn.execute(
                "UPDATE BOA.ZZZ.CustomerDeals "
                "SET contact_name=?, deal_size=?, expected_pricing_pa=?, currency=?, status=?, dealtype=?, notes=? "
                "WHERE id=?",
                (new_contact, new_size, new_pricing, new_currency, new_status, new_dealtype, new_notes, deal_id)
            )
            conn.commit()
            changed = []
            if status_hint:  changed.append(f"Status → {STATUS_LABELS.get(new_status, new_status)}")
            if type_hint:    changed.append(f"Type → {DEALTYPE_LABELS.get(new_dealtype, new_dealtype)}")
            if currency_raw: changed.append(f"Currency → {CURRENCY_LABELS.get(new_currency, new_currency)}")
            if action.get("deal_size"):    changed.append(f"Size → {new_size:,.0f}")
            if action.get("contact_name"): changed.append(f"Contact → {new_contact}")
            if action.get("notes"):        changed.append(f"Notes updated")
            summary = ", ".join(changed) if changed else "No fields changed"
            return {"success": True, "message": f'Deal #{deal_id} for **{cname}** updated: {summary}.'}

        else:
            return {"success": False, "message": f'Unknown action type: {atype}'}

    except Exception as e:
        return {"success": False, "message": f"DB error: {str(e)}"}


# ---------------------------------------------------------------------------
# Internal helper: cache current DB row values onto an action dict
# ---------------------------------------------------------------------------

def _cache_current(action: dict, row) -> None:
    """
    Store the current DB values of a deal row onto the action dict
    as _current_* fields so build_action_card can render from→to diffs.
    """
    action["_current_status"]   = STATUS_LABELS.get(row["status"], str(row["status"]))
    _dt = row["dealtype"]
    action["_current_dealtype"] = DEALTYPE_LABELS.get(int(_dt), str(_dt)) if _dt is not None else "—"
    _cur = row["currency"]
    action["_current_currency"] = CURRENCY_LABELS.get(_cur, str(_cur)) if _cur is not None else ""
    action["_current_deal_size"]    = row["deal_size"]
    action["_current_contact_name"] = row["contact_name"] or ""
    action["_current_notes"]        = (row["notes"] or "")[:80]


# ---------------------------------------------------------------------------
# Action card builder — for UI display
# ---------------------------------------------------------------------------

def build_action_card(action: dict) -> dict:
    """Build a human-readable summary dict for the confirmation UI."""
    atype = action.get("type")
    cname = action.get("customer_name", "?")

    if atype == "insert_deal":
        status_hint   = (action.get("status_hint") or "Lead")
        type_hint     = action.get("dealtype_hint", "")
        size          = action.get("deal_size")
        currency_raw  = (action.get("currency") or "").strip().lower()
        currency_code = CURRENCY_MAP.get(currency_raw)
        currency_disp = CURRENCY_LABELS.get(currency_code, action.get("currency", "") or "")
        contact       = action.get("contact_name", "")
        notes         = action.get("notes", "")
        details = []
        if contact:   details.append(f"Contact: {contact}")
        if size:      details.append(f"{size:,} {currency_disp}".strip())
        if type_hint: details.append(f"Type: {type_hint}")
        if status_hint: details.append(f"Status: {status_hint}")
        if notes:     details.append(f'Notes: "{notes}"')
        return {
            "type":    "insert_deal",
            "icon":    "deal",
            "title":   f"New Deal — {cname}",
            "details": details,
            "requires_confirmation": True,
        }

    elif atype == "insert_comment":
        text      = action.get("comment_text", "")
        date_hint = action.get("comment_date_hint", "")
        details   = [f'"{text}"']
        if date_hint: details.append(f"Date reference: {date_hint}")
        return {
            "type":    "insert_comment",
            "icon":    "comment",
            "title":   f"New Comment — {cname}",
            "details": details,
            "requires_confirmation": True,
        }

    elif atype == "update_deal":
        deal_id       = action.get("deal_id", "?")
        changes       = []
        status_hint   = action.get("status_hint", "")
        type_hint     = action.get("dealtype_hint", "")
        currency_raw  = (action.get("currency") or "").strip().lower()
        currency_code = CURRENCY_MAP.get(currency_raw)
        currency_disp = CURRENCY_LABELS.get(currency_code, action.get("currency", "") or "")

        # Use cached current DB values for the "from" side.
        # Fall back to filter_* fields if cache not yet populated
        # (e.g. when deal_id was just selected via chip).
        cur_type    = action.get("_current_dealtype")   or action.get("filter_dealtype", "")
        cur_status  = action.get("_current_status")     or action.get("filter_status", "")
        cur_contact = action.get("_current_contact_name") or action.get("filter_contact", "")
        cur_size    = action.get("_current_deal_size")
        cur_curr    = action.get("_current_currency", "")
        cur_notes   = action.get("_current_notes", "")

        if type_hint:
            from_lbl = f"{cur_type} → " if cur_type and cur_type != type_hint else ""
            changes.append(f"Type: {from_lbl}{type_hint}")
        if status_hint:
            from_lbl = f"{cur_status} → " if cur_status and cur_status != status_hint else ""
            changes.append(f"Status: {from_lbl}{status_hint}")
        if action.get("contact_name"):
            from_lbl = f"{cur_contact} → " if cur_contact and cur_contact != action["contact_name"] else ""
            changes.append(f"Contact: {from_lbl}{action['contact_name']}")
        if action.get("deal_size"):
            from_lbl = f"{cur_size:,.0f} {cur_curr} → ".strip() if cur_size else ""
            changes.append(f"Size: {from_lbl}{action['deal_size']:,} {currency_disp}".strip())
        if action.get("notes"):
            from_lbl = f'"{cur_notes}" → ' if cur_notes else ""
            changes.append(f'Notes: {from_lbl}"{action["notes"]}"')

        return {
            "type":    "update_deal",
            "icon":    "deal",
            "title":   f"Update Deal #{deal_id} — {cname}",
            "details": changes or ["(fields to update not yet specified)"],
            "requires_confirmation": True,
        }

    elif atype == "query_deals":
        return {
            "type":    "query_deals",
            "icon":    "query",
            "title":   f"List Deals — {cname}",
            "details": ["Fetching existing deals from the database…"],
            "requires_confirmation": False,
        }

    return {
        "type":    atype,
        "icon":    "action",
        "title":   f"{atype} — {cname}",
        "details": [],
        "requires_confirmation": True,
    }
