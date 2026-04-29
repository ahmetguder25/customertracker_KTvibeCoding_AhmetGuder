# ollama_config.py

# Ollama API Endpoint for generating completions
OLLAMA_URL = "http://localhost:11434"

# The local LLM model to use for the chat assistant
OLLAMA_MODEL = "qwen2.5:32b"

# Timeout in seconds for the Ollama API request
OLLAMA_TIMEOUT = 60

# ── Multi-Agent Analysis Configuration (agent_orchestrator.py) ────────────────

# Model used by the 3-stage analysis pipeline (Strategist → Specialist → Editor)
AGENT_MODEL    = "qwen2.5:72b"
AGENT_TIMEOUT  = 180
AGENT_MAX_CHARS = 1000

AGENT_NAMES = ["Arthur", "Sarah", "Michael", "Elena", "James", "Priya", "Omar", "Clara"]
KNOWLEDGE_BASE_DIR = "knowledge_base"

# ── 4-Layer CoT Data Agent Configuration (data_agent_orchestrator.py) ─────────

# Layer 1 — Multi-Intent Dispatcher: parses free-form text into Action Objects
DISPATCHER_MODEL   = "qwen2.5:72b"
DISPATCHER_TIMEOUT = 120

# Layer 2 — Semantic Resolver & Parameter Mapper: entity resolution + schema validation
RESOLVER_MODEL   = "qwen2.5:32b"
RESOLVER_TIMEOUT = 90

# Layer 3 — SQL Engineer: generates T-SQL preview with plain-language explanation
SQL_ENGINEER_MODEL   = "qwen2.5-coder:32b"
SQL_ENGINEER_TIMEOUT = 90

# Layer 4 — Memory & Feedback Loop: synthesises rejections into persistent Golden Rules
MEMORY_MODEL   = "qwen2.5:72b"
MEMORY_TIMEOUT = 60

# ── Backward-compat alias (used by legacy callers) ─────────────────────────────
DATA_AGENT_MODEL   = RESOLVER_MODEL
DATA_AGENT_TIMEOUT = RESOLVER_TIMEOUT

