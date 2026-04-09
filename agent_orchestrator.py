"""agent_orchestrator.py

Three-stage sequential Multi-Agent AI Analysis Orchestrator.

Architecture:
  Stage 1 — Strategist: financial health assessment
  Stage 2 — Specialist: sector & peer benchmarking (receives stage 1 output)
  Stage 3 — Editor:     synthesises prior outputs into a final report + action steps

All agent behaviour is driven by plain-text rule files in /knowledge_base/.
To change agent behaviour, edit the .txt files — no Python changes needed.

Usage (streaming):
    orchestrator = AnalysisOrchestrator(base_dir)
    for event in orchestrator.run_stream(customer_data):
        yield event          # SSE-formatted string

Usage (non-streaming):
    result = orchestrator.run(customer_data)
"""

import os
import random
import requests
import json
from datetime import datetime

from ollama_config import (
    OLLAMA_URL,
    AGENT_MODEL,
    AGENT_TIMEOUT,
    AGENT_MAX_CHARS,
    AGENT_NAMES,
    KNOWLEDGE_BASE_DIR,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GROUNDING_SYSTEM = (
    "You are a financial analysis AI agent. "
    "Use ONLY the logic provided in the training text below. "
    "If any required data is missing, state exactly 'DATA_MISSING: <field>'. "
    "Do NOT use external general knowledge. Do NOT hallucinate data. "
    "Be concise and factual."
)


def _load_logic(base_dir: str, filename: str) -> str:
    """Read a knowledge-base rule file. Returns empty string on error."""
    path = os.path.join(base_dir, KNOWLEDGE_BASE_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return f"[ERROR: {filename} not found in knowledge_base]"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _sse(event: str, data: dict) -> str:
    """Format a Server-Sent Event string."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AnalysisOrchestrator:
    """Runs three agents sequentially, streaming progress via SSE."""

    def __init__(self, base_dir: str, language: str = "English"):
        self.base_dir = base_dir
        self.language = language

        # Assign random unique names to the three agents
        pool = AGENT_NAMES.copy()
        random.shuffle(pool)
        self.names = {
            "strategist": pool[0],
            "specialist": pool[1],
            "editor":     pool[2],
        }

        # Load knowledge-base logic files once at init time
        self.strategist_logic = _load_logic(base_dir, "strategist_logic.txt")
        self.specialist_logic  = _load_logic(base_dir, "specialist_logic.txt")
        self.editor_logic      = _load_logic(base_dir, "editor_logic.txt")

    # ------------------------------------------------------------------
    # Internal: single Ollama call
    # ------------------------------------------------------------------

    def _call_agent(self, system_prompt: str, user_prompt: str) -> str:
        """Send a prompt to Ollama and return the model's response text."""
        full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        payload = {
            "model":  AGENT_MODEL,
            "stream": False,
            "prompt": full_prompt,
        }
        url = OLLAMA_URL if "api/generate" in OLLAMA_URL else f"{OLLAMA_URL.rstrip('/')}/api/generate"
        resp = requests.post(url, json=payload, timeout=AGENT_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()

    # ------------------------------------------------------------------
    # Internal: build a human-readable customer data block
    # ------------------------------------------------------------------

    @staticmethod
    def _format_customer_data(data: dict) -> str:
        deals = data.get("deals", [])
        deal_lines = "\n  ".join(
            f"Deal #{i+1}: size=${d.get('deal_size', 'N/A')}, "
            f"status={d.get('status', 'N/A')}, "
            f"pricing={d.get('expected_pricing_pa', 'N/A')}% p.a., "
            f"currency={d.get('currency', 'N/A')}"
            for i, d in enumerate(deals)
        ) or "None recorded"

        won  = sum(1 for d in deals if str(d.get("status")) == "4")
        lost = sum(1 for d in deals if str(d.get("status")) == "5")
        total_size = sum(d.get("deal_size") or 0 for d in deals)

        c = data.get("customer", {})
        return (
            f"Customer Name    : {c.get('CustomerName', 'N/A')}\n"
            f"Sector           : {data.get('sector_desc', c.get('sector', 'N/A'))}\n"
            f"Region           : {c.get('region', 'N/A')}\n"
            f"Branch           : {c.get('branch', 'N/A')}\n"
            f"Portfolio Manager: {c.get('portfolio_manager', 'N/A')}\n"
            f"Value Segment    : {c.get('value_segment', 'N/A')}\n"
            f"Credit Limit (₺) : {c.get('credit_limit', 'N/A')}\n"
            f"Foreign Trade ($): {c.get('foreign_trade_volume', 'N/A')}\n"
            f"Same-Sector Peers: {data.get('same_sector_count', 'N/A')}\n"
            f"Total Deal Size  : ${total_size:,.0f}\n"
            f"Won Deals        : {won} | Lost Deals: {lost}\n"
            f"Deals:\n  {deal_lines}"
        )

    # ------------------------------------------------------------------
    # Public: streaming generator (yields SSE strings)
    # ------------------------------------------------------------------

    def run_stream(self, customer_data: dict):
        """Generator: yields SSE-formatted strings as each stage completes."""
        data_block = self._format_customer_data(customer_data)

        agent_names_out = {
            "strategist": self.names["strategist"],
            "specialist":  self.names["specialist"],
            "editor":      self.names["editor"],
        }

        yield _sse("start", {"agents": agent_names_out, "time": _now()})

        # ── Stage 1: Strategist ─────────────────────────────────────
        yield _sse("progress", {
            "time":    _now(),
            "agent":   self.names["strategist"],
            "role":    "Strategist",
            "message": f"{self.names['strategist']} is applying Strategist Logic...",
        })

        lang_instruction = f"\n\nCRITICAL INSTRUCTION: You MUST write your ENTIRE response natively in {self.language}."

        try:
            system1 = f"{GROUNDING_SYSTEM}\n\n=== STRATEGIST RULES ===\n{self.strategist_logic}"
            user1   = f"Analyse the following customer:\n\n{data_block}{lang_instruction}"
            stage1  = self._call_agent(system1, user1)
        except Exception as e:
            stage1 = f"AGENT_ERROR: {str(e)[:120]}"

        yield _sse("stage1_done", {
            "time":   _now(),
            "agent":  self.names["strategist"],
            "output": stage1,
        })

        # ── Stage 2: Specialist ─────────────────────────────────────
        yield _sse("progress", {
            "time":    _now(),
            "agent":   self.names["specialist"],
            "role":    "Specialist",
            "message": f"{self.names['specialist']} is checking Peer Benchmarks...",
        })

        try:
            system2 = f"{GROUNDING_SYSTEM}\n\n=== SPECIALIST RULES ===\n{self.specialist_logic}"
            user2   = (
                f"Customer data:\n{data_block}\n\n"
                f"Strategist findings:\n{stage1}\n\n"
                f"Apply your Specialist rules to evaluate sector and peer context.{lang_instruction}"
            )
            stage2 = self._call_agent(system2, user2)
        except Exception as e:
            stage2 = f"AGENT_ERROR: {str(e)[:120]}"

        yield _sse("stage2_done", {
            "time":   _now(),
            "agent":  self.names["specialist"],
            "output": stage2,
        })

        # ── Stage 3: Editor ─────────────────────────────────────────
        yield _sse("progress", {
            "time":    _now(),
            "agent":   self.names["editor"],
            "role":    "Editor",
            "message": f"{self.names['editor']} is synthesising the final report...",
        })

        try:
            system3 = f"{GROUNDING_SYSTEM}\n\n=== EDITOR RULES ===\n{self.editor_logic}"
            user3   = (
                f"Customer data:\n{data_block}\n\n"
                f"Strategist findings:\n{stage1}\n\n"
                f"Specialist findings:\n{stage2}\n\n"
                f"Synthesise into a final professional report with Actionable Next Steps.{lang_instruction}"
            )
            stage3 = self._call_agent(system3, user3)
        except Exception as e:
            stage3 = f"AGENT_ERROR: {str(e)[:120]}"

        # Truncate to configured max
        final = stage3[:AGENT_MAX_CHARS]

        yield _sse("done", {
            "time":        _now(),
            "agent":       self.names["editor"],
            "final":       final,
            "stage1":      stage1,
            "stage2":      stage2,
            "agent_names": agent_names_out,
        })

    # ------------------------------------------------------------------
    # Public: blocking (non-streaming) variant
    # ------------------------------------------------------------------

    def run(self, customer_data: dict) -> dict:
        """Run all stages synchronously and return a result dict."""
        result = {}
        for event_str in self.run_stream(customer_data):
            # Parse each SSE line
            lines = event_str.strip().splitlines()
            if len(lines) >= 2:
                data_line = lines[1]  # "data: {...}"
                if data_line.startswith("data: "):
                    payload = json.loads(data_line[6:])
                    result.update(payload)
        return result
