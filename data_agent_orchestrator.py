"""data_agent_orchestrator.py

4-Layer Chain-of-Thought Natural Language Data Agent.

Layer 1 — Multi-Intent Dispatcher       (Qwen 72B)
  Parses free-form text into structured Action Objects.
  Injects golden rules from agent_memory.md into the system prompt.

Layer 2 — Semantic Resolver & Parameter Mapper  (Qwen 32B)
  Resolves customer entities via fuzzy DB lookup.
  Fetches live schema from INFORMATION_SCHEMA to drive NOT NULL validation.
  Fetches Parameter table for human→INT value mapping.
  Returns two separate queues:
    clarif_queue  — missing required fields   → UI phase "clarifying"
    select_queue  — ambiguous entity matches  → UI phase "selecting"

Layer 3 — SQL Engineer                  (Qwen 32B-Coder)
  Generates a BEGIN TRANSACTION T-SQL preview for each confirmed action.
  Output is display-only — execute_action() is the authoritative DB writer.

Layer 4 — Memory & Feedback Loop        (Qwen 72B)
  Converts user rejections into "Golden Rules" and appends them to
  knowledge_base/agent_memory.md for permanent context injection.
"""

import os
import json
import requests
from datetime import datetime

from ollama_config import (
    OLLAMA_URL,
    DISPATCHER_MODEL,    DISPATCHER_TIMEOUT,
    RESOLVER_MODEL,      RESOLVER_TIMEOUT,
    SQL_ENGINEER_MODEL,  SQL_ENGINEER_TIMEOUT,
    MEMORY_MODEL,        MEMORY_TIMEOUT,
    KNOWLEDGE_BASE_DIR,
)

# ---------------------------------------------------------------------------
# Static code/value maps — used by execute_action() and build_action_card()
# ---------------------------------------------------------------------------

STATUS_MAP = {
    "lead": 1, "proposal": 2, "due diligence": 3, "dd": 3,
    "closed won": 4, "won": 4, "closed lost": 5, "lost": 5,
}
STATUS_LABELS = {1: "Lead", 2: "Proposal", 3: "Due Diligence", 4: "Closed Won", 5: "Closed Lost"}

DEALTYPE_MAP = {"syndication": 1, "bahrain": 2, "sukuk": 3, "kt ag": 4}
DEALTYPE_LABELS = {1: "Syndication", 2: "Bahrain", 3: "Sukuk", 4: "KT AG"}

CURRENCY_MAP = {
    "try": 0, "tl": 0, "lira": 0, "turkish lira": 0,
    "usd": 1, "dollar": 1, "dollars": 1,
    "eur": 19, "euro": 19, "euros": 19,
}
CURRENCY_LABELS = {0: "TRY", 1: "USD", 19: "EUR"}

# Uncertainty phrases — if a clarification answer matches these, re-ask instead of storing
_UNCERTAINTY_PHRASES = {
    "i don't know", "i dont know", "idk", "don't know", "dont know",
    "no idea", "not sure", "i'm not sure", "im not sure", "unknown",
    "bilmiyorum", "bilmem", "emin değilim", "emin degilim", "yok",
    "n/a", "na", "?", "--", "none", "nothing",
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ollama(model: str, prompt: str, timeout: int) -> str:
    """Single Ollama /api/generate call. Returns raw response text."""
    url = OLLAMA_URL if "api/generate" in OLLAMA_URL else f"{OLLAMA_URL.rstrip('/')}/api/generate"
    payload = {"model": model, "stream": False, "prompt": prompt}
    resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()


def _load_kb_file(base_dir: str, filename: str) -> str:
    """Read a file from the knowledge_base directory. Returns '' if missing."""
    path = os.path.join(base_dir, KNOWLEDGE_BASE_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def _clean_json(raw: str) -> str:
    """Strip markdown code fences from an LLM JSON response."""
    clean = raw.strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        clean = parts[1] if len(parts) > 1 else clean
        if clean.lower().startswith("json"):
            clean = clean[4:]
    return clean.strip()


# ---------------------------------------------------------------------------
# DB Helpers (called by Layer 2)
# ---------------------------------------------------------------------------

def fetch_live_schema(conn) -> dict:
    """
    Query INFORMATION_SCHEMA.COLUMNS for CustomerDeals and Comment.
    Returns { "CustomerDeals": [...], "Comment": [...] } where each item is:
      { column, type, nullable (bool), default (str|None) }
    """
    schema = {}
    for table in ("CustomerDeals", "Comment"):
        try:
            rows = conn.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = 'ZZZ' AND TABLE_NAME = ? "
                "ORDER BY ORDINAL_POSITION",
                (table,)
            ).fetchall()
            schema[table] = [
                {
                    "column":   r["COLUMN_NAME"],
                    "type":     r["DATA_TYPE"],
                    "nullable": r["IS_NULLABLE"] == "YES",
                    "default":  r["COLUMN_DEFAULT"],
                }
                for r in rows
            ]
        except Exception:
            schema[table] = []
    return schema


def fetch_parameter_labels(conn) -> dict:
    """
    Fetch all parameter codes and labels from BOA.ZZZ.Parameter for value mapping.
    Returns { "Status": {"1": "Lead", ...}, "DealType": {...}, ... }
    Falls back to empty dict if table is unavailable.
    """
    try:
        rows = conn.execute(
            "SELECT ParamType, ParamCode, ParamDescription FROM BOA.ZZZ.Parameter"
        ).fetchall()
        result = {}
        for r in rows:
            pt = r["ParamType"]
            if pt not in result:
                result[pt] = {}
            result[pt][str(r["ParamCode"])] = r["ParamDescription"]
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Layer 4 Helper — Agent Memory
# ---------------------------------------------------------------------------

def load_agent_memory(base_dir: str) -> str:
    """
    Load golden rules from knowledge_base/agent_memory.md.
    Returns only the rules section (below the marker comment).
    """
    content = _load_kb_file(base_dir, "agent_memory.md")
    marker = "<!-- Rules will be appended below -->"
    if marker in content:
        rules = content.split(marker, 1)[1].strip()
        return rules
    return content


def synthesize_feedback(rejection_note: str, action_card: dict, base_dir: str) -> str:
    """
    Layer 4 — Memory & Feedback Loop (Qwen 72B).

    Converts a user's rejection of a CRM action into a single Golden Rule
    and appends it to knowledge_base/agent_memory.md.

    Returns the generated rule text (for display in the UI).
    """
    action_summary = (
        f"Action type: {action_card.get('type', '?')}, "
        f"Title: {action_card.get('title', '?')}, "
        f"Details: {action_card.get('details', [])}"
    )
    rejection_text = rejection_note.strip() if rejection_note else "(no reason provided)"

    prompt = (
        "You are a Feedback Specialist agent embedded in a CRM data pipeline. "
        "Your ONLY job is to convert a user's rejection of a data action into a single, "
        "concrete Golden Rule that prevents the same mistake in the future.\n\n"
        "Requirements for the rule:\n"
        "- Must be specific and actionable (reference fields, values, or customer types)\n"
        "- Written as a declarative RULE statement (not a question, not a suggestion)\n"
        "- 1–2 sentences maximum\n"
        "- No prefix like 'RULE:' or 'Golden Rule:' — just the rule text itself\n\n"
        f"Rejected action summary:\n{action_summary}\n\n"
        f"User's rejection reason: {rejection_text}\n\n"
        "Output ONLY the rule text. No explanation, no markdown, no preamble."
    )

    try:
        rule_text = _ollama(MEMORY_MODEL, prompt, MEMORY_TIMEOUT).strip()
        # Strip common model-added prefixes
        for prefix in ("rule:", "golden rule:", "rule -", "•"):
            if rule_text.lower().startswith(prefix):
                rule_text = rule_text[len(prefix):].strip()
                break

        # Append to agent_memory.md
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M")
        rule_entry = f"\n- **[{timestamp}]** {rule_text}"
        mem_path   = os.path.join(base_dir, KNOWLEDGE_BASE_DIR, "agent_memory.md")
        with open(mem_path, "a", encoding="utf-8") as f:
            f.write(rule_entry)

        return rule_text

    except Exception as e:
        return f"(memory write error: {e})"


# ---------------------------------------------------------------------------
# Layer 1 — Multi-Intent Dispatcher (Qwen 72B)
# ---------------------------------------------------------------------------

def dispatch_intents(text: str, base_dir: str) -> dict:
    """
    Layer 1: Parse user free-form text into a list of structured Action Objects.

    Uses Qwen 72B + intent_parser_logic.txt rules + agent_memory golden rules.
    Returns { "language": "en"|"tr", "actions": [...] } on success.
    Returns { "language": "en", "actions": [], "error": "..." } on failure.
    """
    parser_logic  = _load_kb_file(base_dir, "intent_parser_logic.txt")
    golden_rules  = load_agent_memory(base_dir)

    memory_block = ""
    if golden_rules:
        memory_block = (
            "\n\n=== AGENT MEMORY — GOLDEN RULES ===\n"
            "Apply these rules to every request without exception:\n"
            + golden_rules
            + "\n=== END GOLDEN RULES ===\n"
        )

    prompt = (
        f"{parser_logic}{memory_block}\n\n"
        "---\n\n"
        "Now parse the following user input and return ONLY the JSON object. "
        "No explanation. No markdown. Raw JSON only.\n\n"
        f"User input: {text}"
    )

    try:
        raw    = _ollama(DISPATCHER_MODEL, prompt, DISPATCHER_TIMEOUT)
        clean  = _clean_json(raw)
        result = json.loads(clean)
        if "actions" not in result:
            result["actions"] = []
        if "language" not in result:
            result["language"] = "en"
        return result
    except Exception as e:
        return {"language": "en", "actions": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Layer 2 — Semantic Resolver & Parameter Mapper (Qwen 32B)
# ---------------------------------------------------------------------------

def resolve_and_map(actions: list, conn, base_dir: str) -> tuple:
    """
    Layer 2: Resolve customer entities, validate fields against live DB schema,
    and map human-readable values to their INT DB codes.

    Returns: (resolved_actions, clarif_queue, select_queue)

      resolved_actions — list of action dicts with customer_id filled where possible
      clarif_queue     — [{action_index, field, question, options}]  → phase "clarifying"
      select_queue     — [{action_index, selection_type, question, options}] → phase "selecting"
    """
    live_schema  = fetch_live_schema(conn)
    param_labels = fetch_parameter_labels(conn)  # noqa: unused for now, available for future use

    resolved     = []
    clarif_queue = []
    select_queue = []

    # ── Phase 2A: Entity Resolution ─────────────────────────────────────────────
    for i, action in enumerate(actions):
        a    = dict(action)
        atype = a.get("type")

        # Handle needs_clarification emitted by Layer 1 — route directly to clarif_queue
        if atype == "needs_clarification":
            clarif_queue.append({
                "action_index": i,
                "field":        "_clarification_question",
                "question":     a.get("clarification_question",
                                      "Could you provide more details about what you meant?"),
                "options":      [],
                "skip_action":  True,   # this action has no DB write; just asks the user
            })
            a["customer_id"] = None
            resolved.append(a)
            continue

        name = a.get("customer_name", "").strip()

        # Work item / sub-item actions don't belong to a customer — skip entity resolution
        if atype in ("insert_workitem", "insert_subitem"):
            a["customer_id"] = None
            resolved.append(a)
            continue

        # For portfolio queries (no customer name), skip entity resolution entirely
        if not name and atype == "query_deals":
            a["customer_id"] = None   # portfolio-level — no specific customer
            resolved.append(a)
            continue

        if not name:
            select_queue.append({
                "action_index":   i,
                "selection_type": "customer",
                "question":       "Which customer does this action relate to?",
                "options":        [],
            })
            a["customer_id"] = None
            resolved.append(a)
            continue

        rows = _fuzzy_customer_search(conn, name)

        if len(rows) == 1:
            a["customer_id"]   = rows[0]["Customerid"]
            a["customer_name"] = rows[0]["CustomerName"]
        elif len(rows) == 0:
            select_queue.append({
                "action_index":   i,
                "selection_type": "customer",
                "question":       f'No customer found matching "{name}". Which customer did you mean?',
                "options":        [],
                "no_match":       True,
            })
            a["customer_id"] = None
        else:
            options = [{"id": r["Customerid"], "label": r["CustomerName"]} for r in rows[:6]]
            select_queue.append({
                "action_index":   i,
                "selection_type": "customer",
                "question":       f'Multiple customers match "{name}". Which one?',
                "options":        options,
            })
            a["customer_id"] = None

        resolved.append(a)

    # ── Phase 2B: Context Enrichment ─────────────────────────────────────────────
    resolved = read_context(resolved, conn)

    # ── Phase 2C: Field Validation (driven by live schema NOT NULL columns) ──────
    deals_schema  = live_schema.get("CustomerDeals", [])
    # Build set of required columns: NOT NULL + no default + not system-managed
    _system_cols  = {"id", "customerid", "created_at", "isactive"}
    required_cols = {
        c["column"].lower()
        for c in deals_schema
        if not c["nullable"] and c["default"] is None
        and c["column"].lower() not in _system_cols
    }

    for i, action in enumerate(resolved):
        if action.get("customer_id") is None:
            continue  # entity not resolved yet — skip field check

        atype = action.get("type")

        if atype == "insert_deal":
            cname = action.get("customer_name", "this deal")

            if "contact_name" in required_cols and not (action.get("contact_name") or "").strip():
                clarif_queue.append({
                    "action_index": i,
                    "field":        "contact_name",
                    "question":     f'Who is the contact person for the deal with **{cname}**?',
                    "options":      [],
                })
            if "deal_size" in required_cols and action.get("deal_size") is None:
                clarif_queue.append({
                    "action_index": i,
                    "field":        "deal_size",
                    "question":     f'What is the deal size for **{cname}**? (e.g. 500000 or 1.5m)',
                    "options":      [],
                })
            if "currency" in required_cols and not (action.get("currency") or "").strip():
                clarif_queue.append({
                    "action_index": i,
                    "field":        "currency",
                    "question":     f'What is the currency for the deal with **{cname}**?',
                    "options":      [{"id": str(k), "label": v} for k, v in CURRENCY_LABELS.items()],
                })
            if "status" in required_cols and not action.get("status_hint"):
                clarif_queue.append({
                    "action_index": i,
                    "field":        "status_hint",
                    "question":     f'What is the deal status for **{cname}**?',
                    "options":      [{"id": str(v), "label": l} for v, l in STATUS_LABELS.items()],
                })

        elif atype == "update_deal":
            if action.get("deal_id") is None and action.get("customer_id") is not None:
                _resolve_deal_selection(action, i, conn, select_queue)

        # Resolve product mapping if present
        if atype in ("insert_deal", "update_deal"):
            pname = action.pop("product_name", None)
            if pname:
                pid = _fuzzy_product_search(conn, pname)
                if pid:
                    action["product_id"] = pid
            fpname = action.pop("filter_product_name", None)
            if fpname:
                fpid = _fuzzy_product_search(conn, fpname)
                if fpid:
                    action["filter_product_id"] = fpid

        # Resolve project for workitem / subitem actions
        if atype in ("insert_workitem", "insert_subitem"):
            pjname = (action.get("project_name") or "").strip()
            if pjname:
                pj = _fuzzy_project_search(conn, pjname)
                if pj:
                    action["project_id"]   = pj["ProjectID"]
                    action["project_name"] = pj["ProjectName"]
                else:
                    select_queue.append({
                        "action_index":   i,
                        "selection_type": "project",
                        "question":       f'No project found matching "{pjname}". Which project did you mean?',
                        "options":        [],
                        "no_match":       True,
                    })
                    action["project_id"] = None
            else:
                select_queue.append({
                    "action_index":   i,
                    "selection_type": "project",
                    "question":       "Which project should this work item be added to?",
                    "options":        _list_projects(conn),
                })
                action["project_id"] = None

        # query_deals: no validation needed (read-only, portfolio queries allowed with no customer_id)

    return resolved, clarif_queue, select_queue


def _fuzzy_customer_search(conn, name: str) -> list:
    """4-step progressive fuzzy search against BOA.ZZZ.Customer (IsStructured=1 only)."""
    # Step 1: exact case-insensitive
    rows = conn.execute(
        "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
        "WHERE IsStructured = 1 AND LOWER(CustomerName) = LOWER(?)", (name,)
    ).fetchall()
    if rows:
        return rows
    # Step 2: LIKE
    rows = conn.execute(
        "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
        "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)", (f"%{name}%",)
    ).fetchall()
    if rows:
        return rows
    # Step 3: strip possessive suffix ("ABCs" → "ABC")
    stripped = name.rstrip("s").rstrip("'").strip()
    if stripped and stripped != name:
        rows = conn.execute(
            "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
            "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)", (f"%{stripped}%",)
        ).fetchall()
        if rows:
            return rows
    # Step 4: drop last word ("ABC Energy Corp" → "ABC Energy")
    if " " in name:
        shorter = name.rsplit(" ", 1)[0].strip()
        rows = conn.execute(
            "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
            "WHERE IsStructured = 1 AND LOWER(CustomerName) LIKE LOWER(?)", (f"%{shorter}%",)
        ).fetchall()
        if rows:
            return rows
    return []

def _fuzzy_product_search(conn, name: str):
    if not name: return None
    r = conn.execute("SELECT ProductID FROM BOA.ZZZ.Product WHERE LOWER(ProductName) = LOWER(?) AND IsActive=1", (name,)).fetchone()
    if r: return r["ProductID"]
    r = conn.execute("SELECT ProductID FROM BOA.ZZZ.Product WHERE LOWER(ProductName) LIKE LOWER(?) AND IsActive=1", (f"%{name}%",)).fetchone()
    if r: return r["ProductID"]
    return None


def _fuzzy_project_search(conn, name: str):
    """4-step fuzzy search against BOA.ZZZ.Project."""
    for sql in [
        ("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE LOWER(ProjectName) = LOWER(?) AND IsActive=1", (name,)),
        ("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE LOWER(ProjectName) LIKE LOWER(?) AND IsActive=1", (f"%{name}%",)),
    ]:
        r = conn.execute(sql[0], sql[1]).fetchone()
        if r: return {"ProjectID": r["ProjectID"], "ProjectName": r["ProjectName"]}
    # Try matching on every word
    for word in name.split():
        if len(word) < 3: continue
        r = conn.execute("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE LOWER(ProjectName) LIKE LOWER(?) AND IsActive=1", (f"%{word}%",)).fetchone()
        if r: return {"ProjectID": r["ProjectID"], "ProjectName": r["ProjectName"]}
    return None


def _list_projects(conn) -> list:
    """Return [{id, label}] for all active projects."""
    rows = conn.execute("SELECT ProjectID, ProjectName FROM BOA.ZZZ.Project WHERE IsActive=1 ORDER BY ProjectName").fetchall()
    return [{"id": str(r["ProjectID"]), "label": r["ProjectName"]} for r in rows]


def _resolve_deal_selection(action: dict, action_idx: int, conn, select_queue: list) -> None:
    """
    Try to auto-select a single deal for an update_deal action using filter fields.
    If ambiguous (0 or >1), appends to select_queue so the UI can ask the user.
    """
    rows = conn.execute(
        "SELECT TOP 10 id, contact_name, deal_size, currency, status, dealtype, notes "
        "FROM BOA.ZZZ.CustomerDeals "
        "WHERE customerid = ? AND IsActive = 1 ORDER BY created_at DESC",
        (action["customer_id"],)
    ).fetchall()

    filtered = list(rows)

    # Apply filter_dealtype
    fdt = (action.get("filter_dealtype") or "").lower().strip()
    if fdt:
        dt_code = DEALTYPE_MAP.get(fdt)
        if dt_code is not None:
            candidate = [r for r in filtered if str(r["dealtype"]) == str(dt_code)]
            if candidate:
                filtered = candidate

    # Apply filter_status
    fst = (action.get("filter_status") or "").lower().strip()
    if fst:
        st_code = STATUS_MAP.get(fst)
        if st_code is not None:
            candidate = [r for r in filtered if r["status"] == st_code]
            if candidate:
                filtered = candidate

    # Apply filter_contact
    fco = (action.get("filter_contact") or "").lower().strip()
    if fco:
        candidate = [r for r in filtered if fco in (r["contact_name"] or "").lower()]
        if candidate:
            filtered = candidate

    # Apply filter_size_approx (within 20%)
    fsz = action.get("filter_size_approx")
    if fsz:
        try:
            fsz_f     = float(fsz)
            candidate = [
                r for r in filtered
                if r["deal_size"] and abs(float(r["deal_size"]) - fsz_f) / max(fsz_f, 1) <= 0.20
            ]
            if candidate:
                filtered = candidate
        except (TypeError, ValueError):
            pass

    # dealtype_hint as fallback filter when other update fields are present
    if len(filtered) > 1 and not fdt:
        dth = (action.get("dealtype_hint") or "").lower().strip()
        other_updates = any([
            action.get("status_hint"), action.get("deal_size"),
            action.get("contact_name"), action.get("notes"),
        ])
        if dth and other_updates:
            dt_code = DEALTYPE_MAP.get(dth)
            if dt_code is not None:
                candidate = [r for r in filtered if str(r["dealtype"]) == str(dt_code)]
                if candidate:
                    filtered = candidate

    cname = action.get("customer_name", "this customer")

    if len(filtered) == 0:
        select_queue.append({
            "action_index":   action_idx,
            "selection_type": "deal",
            "question":       f'No active deals found for **{cname}**. Nothing to update.',
            "options":        [],
            "no_match":       True,
        })
    elif len(filtered) == 1:
        action["deal_id"] = filtered[0]["id"]
        _cache_current(action, filtered[0])
    else:
        options = [
            {
                "id":    str(r["id"]),
                "label": (
                    f'#{r["id"]} — {STATUS_LABELS.get(r["status"], "?")}'
                    + (f' · {r["deal_size"]:,.0f} {CURRENCY_LABELS.get(r["currency"], "?")}' if r["deal_size"] else "")
                    + (f' · {r["contact_name"]}' if r["contact_name"] else "")
                ),
            }
            for r in filtered
        ]
        select_queue.append({
            "action_index":   action_idx,
            "selection_type": "deal",
            "question":       f'**{cname}** has multiple matching deals. Which one do you want to update?',
            "options":        options,
        })


# ---------------------------------------------------------------------------
# Context Reading (called inside resolve_and_map Phase 2B)
# ---------------------------------------------------------------------------

def read_context(actions: list, conn) -> list:
    """
    Attach recent active deals and comments to each resolved action for UI dedup display.
    Returns the enriched action list.
    """
    enriched = []
    for action in actions:
        a   = dict(action)
        cid = a.get("customer_id")
        if cid:
            deals = conn.execute(
                "SELECT TOP 5 id, deal_size, currency, status, dealtype, notes, created_at "
                "FROM BOA.ZZZ.CustomerDeals "
                "WHERE customerid = ? AND IsActive = 1 ORDER BY created_at DESC",
                (cid,)
            ).fetchall()
            comments = conn.execute(
                "SELECT TOP 3 id, content, created_at FROM BOA.ZZZ.Comment "
                "WHERE customer_id = ? AND IsActive = 1 ORDER BY created_at DESC",
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
# Layer 3 — SQL Engineer (Qwen 32B-Coder)
# ---------------------------------------------------------------------------

def generate_sql_preview(action: dict, schema_info: dict) -> dict:
    """
    Layer 3: Generate a T-SQL preview for a fully-resolved action.

    OUTPUT IS DISPLAY-ONLY. execute_action() remains the authoritative DB writer.
    Returns { "sql": "...", "explanation": "<one sentence>" }.
    Falls back gracefully if the model is unavailable.
    """
    schema_summary = _format_schema_for_prompt(schema_info)
    # Build a clean action dict for the model (strip internal _* fields and context blob)
    action_clean = {
        k: v for k, v in action.items()
        if not k.startswith("_") and k != "context"
    }

    prompt = (
        "You are a T-SQL Engineer for a CRM database on Microsoft SQL Server.\n"
        "Generate a safe, transaction-wrapped T-SQL PREVIEW for the following action.\n\n"
        "STRICT RULES:\n"
        "1. Wrap ALL statements in BEGIN TRANSACTION ... COMMIT\n"
        "2. Use SET NOCOUNT ON at the top\n"
        "3. Every UPDATE or DELETE must include a WHERE clause scoped to a specific id\n"
        "4. For soft-deletes: SET IsActive = 0 — never use DELETE\n"
        "5. For INSERT: do NOT insert IsActive (column default handles it)\n"
        "6. Use ? as parameter placeholders\n"
        "7. After the SQL block output exactly this on a new line:\n"
        "   EXPLANATION: <one sentence plain English summary>\n\n"
        f"Relevant table schemas:\n{schema_summary}\n\n"
        f"Action to generate SQL for (JSON):\n{json.dumps(action_clean, indent=2)}\n\n"
        "Output format:\n"
        "```sql\n<T-SQL here>\n```\n"
        "EXPLANATION: <one sentence>"
    )

    try:
        raw         = _ollama(SQL_ENGINEER_MODEL, prompt, SQL_ENGINEER_TIMEOUT)
        sql, expl   = _parse_sql_response(raw)
        return {"sql": sql, "explanation": expl}
    except Exception as e:
        return {"sql": "", "explanation": f"(SQL preview unavailable: {e})"}


def _format_schema_for_prompt(schema_info: dict) -> str:
    """Format live schema dict into a readable string for the SQL Engineer prompt."""
    lines = []
    for table, cols in schema_info.items():
        lines.append(f"\nTable: BOA.ZZZ.{table}")
        for c in cols:
            nullable = "NULL" if c["nullable"] else "NOT NULL"
            default  = f" DEFAULT {c['default']}" if c["default"] else ""
            lines.append(f"  {c['column']}  {c['type']}  {nullable}{default}")
    return "\n".join(lines)


def _parse_sql_response(raw: str) -> tuple:
    """Extract (sql_block, explanation) from a Layer 3 model response."""
    sql         = ""
    explanation = ""

    # Extract SQL from fenced code block
    if "```" in raw:
        parts = raw.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:  # inside a fence
                sql = part.strip()
                if sql.lower().startswith("sql"):
                    sql = sql[3:].strip()
                break
    else:
        # No fences — everything before EXPLANATION:
        upper = raw.upper()
        if "EXPLANATION:" in upper:
            sql = raw[:upper.index("EXPLANATION:")].strip()
        else:
            sql = raw.strip()

    # Extract EXPLANATION line
    upper = raw.upper()
    if "EXPLANATION:" in upper:
        idx         = upper.index("EXPLANATION:")
        explanation = raw[idx + len("EXPLANATION:"):].strip().splitlines()[0].strip()

    return sql, explanation


# ---------------------------------------------------------------------------
# Phase 5 — Execution (Python-controlled — the authoritative DB writer)
# ---------------------------------------------------------------------------

def execute_action(action: dict, conn, author: str = "Agent") -> dict:
    """
    Execute a single confirmed action against the database.
    This function — NOT Layer 3's generated SQL — is the source of truth for all writes.
    Returns { "success": bool, "message": str }.
    """
    atype = action.get("type")
    cid   = action.get("customer_id")
    cname = action.get("customer_name", "Unknown")

    try:
        if atype == "insert_deal":
            deal_size     = action.get("deal_size") or None
            contact_name  = (action.get("contact_name") or "").strip() or None
            notes         = action.get("notes") or None
            status_hint   = (action.get("status_hint") or "Lead").lower().strip()
            status_code   = STATUS_MAP.get(status_hint, 1)
            type_hint     = (action.get("dealtype_hint") or "").lower().strip()
            type_code     = DEALTYPE_MAP.get(type_hint) or None
            currency_raw  = (action.get("currency") or "").strip().lower()
            currency_code = CURRENCY_MAP.get(currency_raw, 0)
            pricing       = action.get("expected_pricing_pa") or None
            product_id    = action.get("product_id") or 1100001

            conn.execute(
                "INSERT INTO BOA.ZZZ.CustomerDeals "
                "(customerid, contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes, ProductID) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cid, contact_name, deal_size, pricing, currency_code, status_code, type_code, notes, product_id)
            )
            conn.commit()
            status_label = STATUS_LABELS.get(status_code, str(status_code))
            size_str     = f", {deal_size:,} {currency_raw.upper()}" if deal_size else ""
            return {"success": True, "message": f'Deal inserted for **{cname}** (Status: {status_label}{size_str}).'}

        elif atype == "insert_comment":
            text = action.get("comment_text", "").strip()
            if not text:
                return {"success": False, "message": "Comment text is empty."}
            date_hint = action.get("comment_date_hint", "")
            full_text = f"[{date_hint}] {text}" if date_hint else text
            conn.execute(
                "INSERT INTO BOA.ZZZ.Comment (customer_id, author, content) VALUES (?, ?, ?)",
                (cid, author, full_text)
            )
            conn.commit()
            return {"success": True, "message": f'Comment added for **{cname}**.'}

        elif atype == "query_deals":
            # ── Customer-specific query ──
            if cid:
                rows = conn.execute(
                    "SELECT d.id, d.contact_name, d.deal_size, d.currency, d.status, "
                    "d.dealtype, d.notes, d.created_at "
                    "FROM BOA.ZZZ.CustomerDeals d "
                    "WHERE d.customerid = ? AND d.IsActive = 1 ORDER BY d.created_at DESC",
                    (cid,)
                ).fetchall()
                label = f"**{cname}**"

            # ── Portfolio-level filtered query ──
            else:
                sql_parts   = ["WHERE d.IsActive = 1"]
                sql_params  = []
                filter_desc = []

                fdt = (action.get("filter_dealtype") or "").lower().strip()
                if fdt:
                    dt_code = DEALTYPE_MAP.get(fdt)
                    if dt_code is not None:
                        sql_parts.append("AND d.dealtype = ?")
                        sql_params.append(dt_code)
                        filter_desc.append(DEALTYPE_LABELS.get(dt_code, fdt.title()))

                fst = (action.get("filter_status") or "").lower().strip()
                if fst:
                    st_code = STATUS_MAP.get(fst)
                    if st_code is not None:
                        sql_parts.append("AND d.status = ?")
                        sql_params.append(st_code)
                        filter_desc.append(STATUS_LABELS.get(st_code, fst.title()))

                fcur = (action.get("filter_currency") or "").lower().strip()
                if fcur:
                    cur_code = CURRENCY_MAP.get(fcur)
                    if cur_code is not None:
                        sql_parts.append("AND d.currency = ?")
                        sql_params.append(cur_code)
                        filter_desc.append(fcur.upper())

                fcust = (action.get("filter_customer_name") or "").strip()
                if fcust:
                    sql_parts.append("AND LOWER(c.CustomerName) LIKE LOWER(?)")
                    sql_params.append(f"%{fcust}%")
                    filter_desc.append(f'customer contains "{fcust}"')

                where_clause = " ".join(sql_parts)
                portfolio_sql = (
                    "SELECT d.id, c.CustomerName AS customer_name, d.contact_name, "
                    "d.deal_size, d.currency, d.status, d.dealtype, d.notes, d.created_at "
                    "FROM BOA.ZZZ.CustomerDeals d "
                    "JOIN BOA.ZZZ.Customer c ON d.customerid = c.Customerid "
                    + where_clause +
                    " ORDER BY c.CustomerName, d.created_at DESC"
                )
                rows = conn.execute(portfolio_sql, sql_params).fetchall()
                label = "the portfolio" if not filter_desc else ", ".join(filter_desc)
                label = f"**{label}**"

            if not rows:
                return {"success": True, "message": f'No active deals found for {label}.', "deals": []}

            deal_list = []
            for r in rows:
                _dt      = r["dealtype"]
                curr_lbl = CURRENCY_LABELS.get(r["currency"], str(r["currency"]) if r["currency"] is not None else "—")
                row_dict = {
                    "id":      r["id"],
                    "contact": r["contact_name"] or "—",
                    "size":    f"{r['deal_size']:,.0f} {curr_lbl}" if r["deal_size"] else "—",
                    "status":  STATUS_LABELS.get(r["status"], "?"),
                    "type":    DEALTYPE_LABELS.get(int(_dt), str(_dt)) if _dt is not None else "—",
                    "notes":   (r["notes"] or "")[:120],
                }
                # Include customer name column for portfolio queries
                raw_cust = dict(r).get("customer_name")
                if raw_cust:
                    row_dict["customer"] = raw_cust
                deal_list.append(row_dict)
            return {"success": True, "message": f'Found **{len(deal_list)}** active deal(s) for {label}.', "deals": deal_list}

        elif atype == "update_deal":
            deal_id = action.get("deal_id")
            if not deal_id:
                return {"success": False, "message": "No deal selected to update."}

            current = conn.execute(
                "SELECT contact_name, deal_size, expected_pricing_pa, currency, status, dealtype, notes "
                "FROM BOA.ZZZ.CustomerDeals WHERE id = ? AND IsActive = 1",
                (deal_id,)
            ).fetchone()
            if not current:
                return {"success": False, "message": f"Deal #{deal_id} not found or inactive."}

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
                "WHERE id=? AND IsActive = 1",
                (new_contact, new_size, new_pricing, new_currency, new_status, new_dealtype, new_notes, deal_id)
            )
            conn.commit()
            changed = []
            if status_hint:              changed.append(f"Status → {STATUS_LABELS.get(new_status, new_status)}")
            if type_hint:                changed.append(f"Type → {DEALTYPE_LABELS.get(new_dealtype, new_dealtype)}")
            if currency_raw:             changed.append(f"Currency → {CURRENCY_LABELS.get(new_currency, new_currency)}")
            if action.get("deal_size"):  changed.append(f"Size → {new_size:,.0f}")
            if action.get("contact_name"): changed.append(f"Contact → {new_contact}")
            if action.get("notes"):      changed.append("Notes updated")
            summary = ", ".join(changed) if changed else "No fields changed"
            return {"success": True, "message": f'Deal #{deal_id} for **{cname}** updated: {summary}.'}

        elif atype == "insert_workitem":
            proj_id = action.get("project_id")
            if not proj_id:
                return {"success": False, "message": "Project not resolved for this work item."}
            title       = (action.get("title") or "").strip()
            description = (action.get("description") or "").strip() or None
            status      = action.get("status") or "not_started"
            deadline    = action.get("deadline") or None
            if not title:
                return {"success": False, "message": "Work item title is required."}
            conn.execute(
                "INSERT INTO BOA.ZZZ.WorkItem (ParentType, ParentID, Title, Description, Status, Deadline) "
                "VALUES ('project', ?, ?, ?, ?, ?)",
                (proj_id, title, description, status, deadline)
            )
            conn.commit()
            proj_name = action.get("project_name", f"Project #{proj_id}")
            return {"success": True, "message": f'Work item **"{title}"** added to project **{proj_name}**.', "_project_id": proj_id, "_item_title": title}

        elif atype == "insert_subitem":
            proj_id          = action.get("project_id")
            parent_item_title = (action.get("parent_item_title") or "").strip()
            title            = (action.get("title") or "").strip()
            deadline         = action.get("deadline") or None
            if not proj_id:
                return {"success": False, "message": "Project not resolved for this sub-item."}
            if not parent_item_title:
                return {"success": False, "message": "parent_item_title is required for insert_subitem."}
            if not title:
                return {"success": False, "message": "Sub-item title is required."}
            # Resolve parent WorkItem
            parent = conn.execute(
                "SELECT ItemID FROM BOA.ZZZ.WorkItem "
                "WHERE ParentType='project' AND ParentID=? AND LOWER(Title)=LOWER(?) AND IsActive=1",
                (proj_id, parent_item_title)
            ).fetchone()
            if not parent:
                # Fuzzy fallback
                parent = conn.execute(
                    "SELECT ItemID FROM BOA.ZZZ.WorkItem "
                    "WHERE ParentType='project' AND ParentID=? AND LOWER(Title) LIKE LOWER(?) AND IsActive=1",
                    (proj_id, f"%{parent_item_title}%")
                ).fetchone()
            if not parent:
                return {"success": False, "message": f'Parent work item "{parent_item_title}" not found in project. Create it first.'}
            conn.execute(
                "INSERT INTO BOA.ZZZ.WorkSubItem (ParentItemID, Title, Deadline) VALUES (?, ?, ?)",
                (parent["ItemID"], title, deadline)
            )
            conn.commit()
            proj_name = action.get("project_name", f"Project #{proj_id}")
            return {"success": True, "message": f'Sub-item **"{title}"** added under **"{parent_item_title}"** in project **{proj_name}**.', "_project_id": proj_id}

        else:
            return {"success": False, "message": f"Unknown action type: {atype}"}

    except Exception as e:
        return {"success": False, "message": f"DB error: {str(e)}"}


# ---------------------------------------------------------------------------
# UI Action Card Builder
# ---------------------------------------------------------------------------

def build_action_card(action: dict) -> dict:
    """
    Build a human-readable summary dict for the confirmation UI.
    Includes sql_explanation from Layer 3 if already generated.
    """
    atype           = action.get("type")
    cname           = action.get("customer_name", "?")
    sql_explanation = action.get("_explanation", "")

    if atype == "insert_deal":
        status_hint   = action.get("status_hint", "Lead")
        type_hint     = action.get("dealtype_hint", "")
        size          = action.get("deal_size")
        currency_raw  = (action.get("currency") or "").strip().lower()
        currency_disp = CURRENCY_LABELS.get(CURRENCY_MAP.get(currency_raw), action.get("currency", "") or "")
        contact       = action.get("contact_name", "")
        notes         = action.get("notes", "")
        details       = []
        if contact:      details.append(f"Contact: {contact}")
        if size:         details.append(f"{size:,} {currency_disp}".strip())
        if type_hint:    details.append(f"Type: {type_hint}")
        if status_hint:  details.append(f"Status: {status_hint}")
        if notes:        details.append(f'Notes: "{notes}"')
        return {
            "type": "insert_deal", "icon": "deal",
            "title": f"New Deal — {cname}", "details": details,
            "sql_explanation": sql_explanation,
            "requires_confirmation": True,
        }

    elif atype == "insert_comment":
        text      = action.get("comment_text", "")
        date_hint = action.get("comment_date_hint", "")
        details   = [f'"{text}"']
        if date_hint:
            details.append(f"Date reference: {date_hint}")
        return {
            "type": "insert_comment", "icon": "comment",
            "title": f"New Comment — {cname}", "details": details,
            "sql_explanation": sql_explanation,
            "requires_confirmation": True,
        }

    elif atype == "update_deal":
        deal_id      = action.get("deal_id", "?")
        currency_raw = (action.get("currency") or "").strip().lower()
        currency_disp = CURRENCY_LABELS.get(CURRENCY_MAP.get(currency_raw), action.get("currency", "") or "")
        cur_type     = action.get("_current_dealtype")    or action.get("filter_dealtype", "")
        cur_status   = action.get("_current_status")      or action.get("filter_status", "")
        cur_contact  = action.get("_current_contact_name") or action.get("filter_contact", "")
        cur_size     = action.get("_current_deal_size")
        cur_curr     = action.get("_current_currency", "")
        cur_notes    = action.get("_current_notes", "")
        changes      = []
        type_hint    = action.get("dealtype_hint", "")
        status_hint  = action.get("status_hint", "")
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
            "type": "update_deal", "icon": "deal",
            "title": f"Update Deal #{deal_id} — {cname}",
            "details": changes or ["(fields to update not yet specified)"],
            "sql_explanation": sql_explanation,
            "requires_confirmation": True,
        }

    elif atype == "query_deals":
        # Build a human-readable description of what we're querying
        filters = []
        if cname and cname != "Unknown":
            filters.append(f"Customer: {cname}")
        fdt = (action.get("filter_dealtype") or "").lower().strip()
        if fdt:
            dt_code = DEALTYPE_MAP.get(fdt)
            filters.append(f"Type: {DEALTYPE_LABELS.get(dt_code, fdt.title())}" if dt_code else f"Type: {fdt.title()}")
        fst = (action.get("filter_status") or "").lower().strip()
        if fst:
            st_code = STATUS_MAP.get(fst)
            filters.append(f"Status: {STATUS_LABELS.get(st_code, fst.title())}" if st_code else f"Status: {fst.title()}")
        fcur = (action.get("filter_currency") or "").lower().strip()
        if fcur:
            filters.append(f"Currency: {fcur.upper()}")
        fcust = (action.get("filter_customer_name") or "").strip()
        if fcust:
            filters.append(f'Customer contains: "{fcust}"')
        if not filters:
            filters = ["All active deals across the portfolio"]
        title = f"List Deals" + (f" — {cname}" if (cname and cname != 'Unknown') else " — Portfolio View")
        return {
            "type": "query_deals", "icon": "query",
            "title": title,
            "details": filters,
            "sql_explanation": "",
            "requires_confirmation": False,
        }

    elif atype == "insert_workitem":
        proj_name = action.get("project_name", "?")
        title_val = action.get("title", "?")
        details   = [f"Project: {proj_name}", f"Task: {title_val}"]
        if action.get("description"): details.append(f"Description: {action['description']}")
        if action.get("status"):      details.append(f"Status: {action['status']}")
        if action.get("deadline"):    details.append(f"Deadline: {action['deadline']}")
        return {
            "type": "insert_workitem", "icon": "task",
            "title": f"New Work Item — {proj_name}",
            "details": details,
            "sql_explanation": action.get("_explanation", ""),
            "requires_confirmation": True,
        }

    elif atype == "insert_subitem":
        proj_name   = action.get("project_name", "?")
        parent_title = action.get("parent_item_title", "?")
        title_val   = action.get("title", "?")
        details     = [f"Project: {proj_name}", f"Parent Task: {parent_title}", f"Sub-task: {title_val}"]
        if action.get("deadline"): details.append(f"Deadline: {action['deadline']}")
        return {
            "type": "insert_subitem", "icon": "subtask",
            "title": f"New Sub-task under \"{parent_title}\"",
            "details": details,
            "sql_explanation": action.get("_explanation", ""),
            "requires_confirmation": True,
        }

    return {
        "type": atype, "icon": "action",
        "title": f"{atype} — {cname}", "details": [],
        "sql_explanation": sql_explanation,
        "requires_confirmation": True,
    }


# ---------------------------------------------------------------------------
# Internal helper: cache current DB row values onto action dict
# ---------------------------------------------------------------------------

def _cache_current(action: dict, row) -> None:
    """Store current DB values on the action dict for from→to diff display."""
    action["_current_status"]       = STATUS_LABELS.get(row["status"], str(row["status"]))
    _dt = row["dealtype"]
    action["_current_dealtype"]     = DEALTYPE_LABELS.get(int(_dt), str(_dt)) if _dt is not None else "—"
    _cur = row["currency"]
    action["_current_currency"]     = CURRENCY_LABELS.get(_cur, str(_cur)) if _cur is not None else ""
    action["_current_deal_size"]    = row["deal_size"]
    action["_current_contact_name"] = row["contact_name"] or ""
    action["_current_notes"]        = (row["notes"] or "")[:80]


# ===========================================================================
# Engine — State Machine (no Flask dependencies)
# ===========================================================================
# All functions below take/return plain dicts.
# They never import Flask, touch session, or call jsonify.
# app.py calls process_agent_turn() and uses its return value directly.
# ===========================================================================

def _is_portfolio_query(action: dict) -> bool:
    """True when a query_deals action is portfolio-level (no specific customer)."""
    return action.get("type") == "query_deals" and action.get("customer_id") is None


def _build_done(state: dict) -> dict:
    """Build the final done response payload."""
    state["phase"] = "done"
    return {"phase": "done", "results": state.get("results", [])}


def _build_selecting(state: dict) -> dict:
    """Build a selecting phase payload for the current select_queue item."""
    queue = state["select_queue"]
    si    = state["select_index"]
    if si >= len(queue):
        return _advance_from_selecting_pure(state)
    sel = queue[si]
    return {
        "phase":          "selecting",
        "message":        sel["question"],
        "options":        sel.get("options", []),
        "selection_type": sel.get("selection_type", "customer"),
        "action_index":   state["confirm_index"],
        "total_actions":  len(state["actions"]),
    }


def _build_clarifying(state: dict) -> dict:
    """Build a clarifying phase payload for the current clarif_queue item."""
    queue = state["clarif_queue"]
    ci    = state["clarif_index"]
    if ci >= len(queue):
        state["phase"] = "confirming"
        return _build_confirming(state)
    clarif = queue[ci]
    return {
        "phase":         "clarifying",
        "message":       clarif["question"],
        "options":       clarif.get("options", []),
        "action_index":  state["confirm_index"],
        "total_actions": len(state["actions"]),
    }


def _auto_execute(action: dict, conn, author: str) -> dict:
    """Execute a non-confirmation action (e.g. query_deals). Returns result dict."""
    if action.get("customer_id") is not None or _is_portfolio_query(action):
        return execute_action(action, conn, author=author)
    return {"success": None, "message": "Customer not resolved — skipped."}


def _build_confirming(state: dict) -> dict:
    """
    Build a confirming phase payload.
    Auto-executes any requires_confirmation=False actions inline before returning.
    Layer 3 SQL preview is generated lazily for write actions.
    """
    actions = state["actions"]

    # Auto-execute any non-confirmation actions at the front of the queue
    while state["confirm_index"] < len(actions):
        idx     = state["confirm_index"]
        current = actions[idx]
        card    = build_action_card(current)

        if card.get("requires_confirmation", True):
            break  # This action needs user input — stop and show it

        # Auto-execute (query_deals etc.) — conn must be passed via state
        conn   = state.get("_conn")
        author = state.get("_author", "Agent")
        result = _auto_execute(current, conn, author)
        state["results"].append({"action": card, "result": result})
        state["confirm_index"] = idx + 1

    if state["confirm_index"] >= len(actions):
        return _build_done(state)

    # Next action needs user confirmation — generate Layer 3 SQL preview
    idx         = state["confirm_index"]
    current     = actions[idx]
    schema_info = state.get("schema_info", {})

    if not current.get("_explanation"):
        preview = generate_sql_preview(current, schema_info)
        current["_generated_sql"] = preview.get("sql", "")
        current["_explanation"]   = preview.get("explanation", "")
        actions[idx]              = current

    all_cards = [build_action_card(a) for a in actions]
    card      = all_cards[idx]

    return {
        "phase":          "confirming",
        "current_action": card,
        "action_index":   idx,
        "total_actions":  len(actions),
        "all_cards":      all_cards,
        "message":        None,
    }


def _advance_from_selecting_pure(state: dict) -> dict:
    """Re-run resolution after all selecting steps are answered, then route."""
    conn     = state.get("_conn")
    base_dir = state.get("_base_dir", ".")

    _, new_clarifs, new_selects = resolve_and_map(state["actions"], conn, base_dir)

    existing_clarif_keys = {(c["action_index"], c["field"]) for c in state["clarif_queue"]}
    for c in new_clarifs:
        if (c["action_index"], c["field"]) not in existing_clarif_keys:
            state["clarif_queue"].append(c)

    existing_select_keys = {(s["action_index"], s.get("selection_type")) for s in state["select_queue"]}
    for s in new_selects:
        if (s["action_index"], s.get("selection_type")) not in existing_select_keys:
            state["select_queue"].append(s)

    if state["select_index"] < len(state["select_queue"]):
        state["phase"] = "selecting"
        return _build_selecting(state)
    if state["clarif_index"] < len(state["clarif_queue"]):
        state["phase"] = "clarifying"
        return _build_clarifying(state)

    state["phase"] = "confirming"
    return _build_confirming(state)


def _handle_selection(state: dict, answer: str, option_id) -> dict:
    """Process a selecting-phase answer. Returns next response payload."""
    conn       = state.get("_conn")
    select_queue = state["select_queue"]
    si           = state["select_index"]

    if si >= len(select_queue):
        return _advance_from_selecting_pure(state)

    sel        = select_queue[si]
    action_idx = sel["action_index"]
    sel_type   = sel.get("selection_type", "customer")

    if sel_type == "customer":
        if option_id:
            row = conn.execute(
                "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer WHERE Customerid = ?",
                (int(option_id),)
            ).fetchone()
            if row:
                state["actions"][action_idx]["customer_id"]   = row["Customerid"]
                state["actions"][action_idx]["customer_name"] = row["CustomerName"]
        elif answer:
            rows = conn.execute(
                "SELECT Customerid, CustomerName FROM BOA.ZZZ.Customer "
                "WHERE IsStructured=1 AND LOWER(CustomerName) LIKE LOWER(?)",
                (f"%{answer}%",)
            ).fetchall()
            if len(rows) == 1:
                state["actions"][action_idx]["customer_id"]   = rows[0]["Customerid"]
                state["actions"][action_idx]["customer_name"] = rows[0]["CustomerName"]
            elif len(rows) > 1:
                opts = [{"id": r["Customerid"], "label": r["CustomerName"]} for r in rows[:6]]
                select_queue[si]["question"] = f'Multiple matches for "{answer}". Which one?'
                select_queue[si]["options"]  = opts
                return _build_selecting(state)

    elif sel_type == "deal":
        if option_id:
            deal_id = int(option_id)
            state["actions"][action_idx]["deal_id"] = deal_id
            row = conn.execute(
                "SELECT id, contact_name, deal_size, currency, status, dealtype, notes "
                "FROM BOA.ZZZ.CustomerDeals WHERE id = ? AND IsActive = 1",
                (deal_id,)
            ).fetchone()
            if row:
                _cache_current(state["actions"][action_idx], row)

    state["select_index"] = si + 1
    if state["select_index"] >= len(select_queue):
        return _advance_from_selecting_pure(state)
    return _build_selecting(state)


def _handle_clarification(state: dict, answer: str, option_id, base_dir: str) -> dict:
    """Process a clarifying-phase answer. Returns next response payload."""
    conn         = state.get("_conn")
    author       = state.get("_author", "Agent")
    clarif_queue = state["clarif_queue"]
    ci           = state["clarif_index"]

    if ci >= len(clarif_queue):
        state["phase"] = "confirming"
        return _build_confirming(state)

    current_clarif = clarif_queue[ci]
    action_idx     = current_clarif["action_index"]
    field          = current_clarif["field"]

    # Uncertainty detection
    if answer and not option_id:
        answer_normalized = answer.lower().strip().rstrip("!.?")
        if (answer_normalized in _UNCERTAINTY_PHRASES
                or answer_normalized.startswith("i don")
                or answer_normalized.startswith("bilmi")):
            required_label = {
                "contact_name": "contact person's name",
                "deal_size":    "deal size (e.g. 1.5m or 500000)",
                "currency":     "currency",
                "status_hint":  "deal status",
            }.get(field, field)
            clarif_queue[ci]["question"] = (
                f'"{answer}" is not a valid {required_label}. '
                f'This is a required field — please provide a real value, '
                f'or type "skip" to skip this entire action.'
            )
            return _build_clarifying(state)

    # Skip entire action
    if answer.lower().strip() == "skip":
        state["actions"][action_idx]["_skipped"] = True
        state["clarif_index"] = ci + 1
        if state["clarif_index"] >= len(clarif_queue):
            state["phase"] = "confirming"
            return _build_confirming(state)
        return _build_clarifying(state)

    # Vague restart — treat answer as a fresh message
    if field == "_clarification_question":
        return _fresh_turn(answer, conn, base_dir, author)

    # Apply answer to field
    if field == "contact_name":
        state["actions"][action_idx]["contact_name"] = answer
    elif field == "deal_size":
        try:
            raw = answer.lower().replace(",", "").replace(" ", "").strip()
            if raw.endswith("m"):
                state["actions"][action_idx]["deal_size"] = float(raw[:-1]) * 1_000_000
            elif raw.endswith("k"):
                state["actions"][action_idx]["deal_size"] = float(raw[:-1]) * 1_000
            else:
                state["actions"][action_idx]["deal_size"] = float(raw)
        except ValueError:
            pass
    elif field == "currency":
        if option_id is not None:
            label = CURRENCY_LABELS.get(int(option_id), answer)
            state["actions"][action_idx]["currency"] = label
        elif answer:
            state["actions"][action_idx]["currency"] = answer
    elif field == "status_hint":
        if option_id:
            label = STATUS_LABELS.get(int(option_id), answer)
            state["actions"][action_idx]["status_hint"] = label
        elif answer:
            state["actions"][action_idx]["status_hint"] = answer

    state["clarif_index"] = ci + 1
    if state["clarif_index"] >= len(clarif_queue):
        state["phase"] = "confirming"
        return _build_confirming(state)
    return _build_clarifying(state)


def _handle_confirmation(state: dict, action: str, rejection_note: str) -> dict:
    """Process a confirming-phase action (confirm/skip/reject). Returns next payload."""
    conn   = state.get("_conn")
    author = state.get("_author", "Agent")
    base_dir = state.get("_base_dir", ".")

    idx     = state["confirm_index"]
    actions = state["actions"]

    if idx < len(actions):
        current = actions[idx]
        card    = build_action_card(current)

        if action == "confirm":
            if current.get("customer_id") is not None or _is_portfolio_query(current):
                result = execute_action(current, conn, author=author)
            else:
                result = {"success": False,
                          "message": f'Skipped — customer not resolved for {current.get("customer_name","?")}'}
            state["results"].append({"action": build_action_card(current), "result": result})
            state["confirm_index"] = idx + 1

        elif action == "skip":
            state["results"].append({
                "action": build_action_card(current),
                "result": {"success": None, "message": "Skipped by user."},
            })
            state["confirm_index"] = idx + 1

        elif action == "reject":
            golden_rule = synthesize_feedback(rejection_note, card, base_dir)
            state["results"].append({
                "action": card,
                "result": {
                    "success":     None,
                    "message":     f'Rejected. Golden Rule recorded: "{golden_rule}"',
                    "golden_rule": golden_rule,
                },
            })
            state["confirm_index"] = idx + 1

    if state["confirm_index"] >= len(state["actions"]):
        return _build_done(state)

    return _build_confirming(state)


def _fresh_turn(message: str, conn, base_dir: str, author: str) -> dict:
    """Start a brand-new turn from a raw user message. Returns initial state + response."""
    try:
        parsed = dispatch_intents(message, base_dir)
    except Exception as e:
        return {"_new_state": {}, "phase": "error", "message": f"Layer 1 (Dispatcher) error: {e}"}

    if parsed.get("error") and not parsed.get("actions"):
        return {"_new_state": {}, "phase": "error", "message": f"Could not parse intent: {parsed['error']}"}

    if not parsed.get("actions"):
        return {
            "_new_state": {},
            "phase": "error",
            "message": "I couldn't identify any actions. Try mentioning a customer name and what happened.",
        }

    language = parsed.get("language", "en")
    resolved, clarif_queue, select_queue = resolve_and_map(parsed["actions"], conn, base_dir)
    schema_info = fetch_live_schema(conn)

    opening_phase = (
        "selecting"  if select_queue  else
        "clarifying" if clarif_queue  else
        "confirming"
    )

    state = {
        "actions":       resolved,
        "clarif_queue":  clarif_queue,
        "select_queue":  select_queue,
        "clarif_index":  0,
        "select_index":  0,
        "confirm_index": 0,
        "results":       [],
        "language":      language,
        "schema_info":   schema_info,
        "phase":         opening_phase,
        "_conn":         conn,
        "_author":       author,
        "_base_dir":     base_dir,
    }

    if opening_phase == "selecting":
        response = _build_selecting(state)
    elif opening_phase == "clarifying":
        response = _build_clarifying(state)
    else:
        response = _build_confirming(state)

    response["_new_state"] = state
    return response


# ---------------------------------------------------------------------------
# Public entry point — called by app.py
# ---------------------------------------------------------------------------

def process_agent_turn(
    state: dict,
    user_input: dict,
    conn,
    base_dir: str,
    author: str = "Agent",
) -> tuple:
    """
    The single public entry point for the Data Agent engine.

    Parameters
    ----------
    state      : current agent state dict (from session; empty dict for a fresh turn)
    user_input : { "message": str }  — new text starts a fresh turn
                 { "action": str, "answer": str, "option_id": ..., "rejection_note": str }
                   — continuation of an existing turn
    conn       : open DB connection (caller opens/closes it)
    base_dir   : directory containing knowledge_base/
    author     : username written into DB records

    Returns
    -------
    (new_state, response_payload)
      new_state       — updated state dict to persist in session
      response_payload — plain dict; caller passes to jsonify()
    """
    incoming_msg   = (user_input.get("message") or "").strip()
    action         = user_input.get("action")
    answer         = (user_input.get("answer") or "").strip()
    option_id      = user_input.get("option_id")
    rejection_note = (user_input.get("rejection_note") or "").strip()

    # Inject transient context so sub-functions can reach conn/author/base_dir
    # without threading them through every argument chain.
    # These _private keys are stripped before saving to session.
    def _inject(s: dict) -> dict:
        s["_conn"]     = conn
        s["_author"]   = author
        s["_base_dir"] = base_dir
        return s

    def _strip(s: dict) -> dict:
        return {k: v for k, v in s.items() if not k.startswith("_")}

    # ── Fresh turn ────────────────────────────────────────────────────────────
    if incoming_msg:
        response = _fresh_turn(incoming_msg, conn, base_dir, author)
        new_state = _strip(response.pop("_new_state", {}))
        return new_state, response

    # ── Continuation ─────────────────────────────────────────────────────────
    if not state:
        return {}, {"phase": "error", "message": "No active session. Please type a message to start."}

    _inject(state)
    phase = state.get("phase")

    if phase == "selecting" and action == "answer":
        response  = _handle_selection(state, answer, option_id)
        new_state = _strip(state)
        return new_state, response

    if phase == "clarifying" and action == "answer":
        response  = _handle_clarification(state, answer, option_id, base_dir)
        new_state = _strip(response.pop("_new_state", state))
        return new_state, response

    if phase == "confirming":
        response  = _handle_confirmation(state, action, rejection_note)
        new_state = _strip(state)
        return new_state, response

    if phase == "done":
        return _strip(state), _build_done(state)

    return _strip(state), {"phase": "error", "message": "Unexpected state. Please type a message to start over."}

