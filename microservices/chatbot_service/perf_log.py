"""perf_log.py — Self-contained performance logging for the STF Chatbot microservice.

Stores detailed timing, model info, and pipeline metrics in a local SQLite DB
so different methods/models can be compared side-by-side.

Usage:
    from microservices.chatbot_service.perf_log import init_perf_db, log_chat_perf, get_perf_logs
"""

import os
import sqlite3
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PERF_DB_PATH = os.path.join(BASE_DIR, "perf_log.db")


def _get_conn():
    conn = sqlite3.connect(PERF_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_perf_db():
    """Create the performance log table if it doesn't exist."""
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_perf_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT DEFAULT (datetime('now', 'localtime')),
            message_id      INTEGER,

            -- Input context
            prompt          TEXT,
            prompt_words    INTEGER,
            selected_docs   TEXT,
            language        TEXT,

            -- Models used (for A/B comparison)
            model_gen       TEXT,
            model_embed     TEXT,
            method          TEXT,

            -- Pipeline step timings (milliseconds)
            t_total_ms      INTEGER,
            t_expand_ms     INTEGER,
            t_embed_ms      INTEGER,
            t_search_ms     INTEGER,
            t_generate_ms   INTEGER,

            -- Pipeline output metrics
            queries_expanded    INTEGER,
            embed_calls         INTEGER,
            chunks_retrieved    INTEGER,
            context_chars       INTEGER,
            tokens_generated    INTEGER,

            -- Result
            status          TEXT,
            error_message   TEXT
        )
    """)
    conn.commit()
    conn.close()
    print("[perf_log] Performance log DB ready.")


def log_chat_perf(**kwargs):
    """Insert a performance record. Pass any column name as a keyword argument."""
    conn = _get_conn()
    columns = [
        "message_id", "prompt", "prompt_words", "selected_docs", "language",
        "model_gen", "model_embed", "method",
        "t_total_ms", "t_expand_ms", "t_embed_ms", "t_search_ms", "t_generate_ms",
        "queries_expanded", "embed_calls", "chunks_retrieved", "context_chars",
        "tokens_generated", "status", "error_message"
    ]
    # Only insert columns that were provided
    present = {k: v for k, v in kwargs.items() if k in columns}
    if not present:
        return

    cols = ", ".join(present.keys())
    placeholders = ", ".join("?" for _ in present)
    values = list(present.values())

    conn.execute(f"INSERT INTO chat_perf_log ({cols}) VALUES ({placeholders})", values)
    conn.commit()
    conn.close()


def get_perf_logs(limit=50, offset=0):
    """Return recent performance logs, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM chat_perf_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_perf_summary():
    """Aggregate stats for dashboard display."""
    conn = _get_conn()
    summary = {}

    # Overall stats
    row = conn.execute("""
        SELECT
            COUNT(*)                                    AS total_queries,
            ROUND(AVG(t_total_ms))                      AS avg_total_ms,
            ROUND(AVG(t_expand_ms))                     AS avg_expand_ms,
            ROUND(AVG(t_embed_ms))                      AS avg_embed_ms,
            ROUND(AVG(t_search_ms))                     AS avg_search_ms,
            ROUND(AVG(t_generate_ms))                   AS avg_generate_ms,
            ROUND(AVG(tokens_generated))                AS avg_tokens,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count
        FROM chat_perf_log
    """).fetchone()
    summary["overall"] = dict(row) if row else {}

    # Per-model breakdown
    model_rows = conn.execute("""
        SELECT
            model_gen,
            COUNT(*)                    AS queries,
            ROUND(AVG(t_total_ms))      AS avg_total_ms,
            ROUND(AVG(t_expand_ms))     AS avg_expand_ms,
            ROUND(AVG(t_generate_ms))   AS avg_generate_ms,
            ROUND(AVG(tokens_generated)) AS avg_tokens
        FROM chat_perf_log
        WHERE status = 'success'
        GROUP BY model_gen
        ORDER BY avg_total_ms ASC
    """).fetchall()
    summary["by_model"] = [dict(r) for r in model_rows]

    # Per-method breakdown
    method_rows = conn.execute("""
        SELECT
            method,
            COUNT(*)                    AS queries,
            ROUND(AVG(t_total_ms))      AS avg_total_ms,
            ROUND(AVG(t_expand_ms))     AS avg_expand_ms,
            ROUND(AVG(t_embed_ms))      AS avg_embed_ms,
            ROUND(AVG(t_search_ms))     AS avg_search_ms
        FROM chat_perf_log
        WHERE status = 'success'
        GROUP BY method
        ORDER BY avg_total_ms ASC
    """).fetchall()
    summary["by_method"] = [dict(r) for r in method_rows]

    conn.close()
    return summary
