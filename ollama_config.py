# ollama_config.py

# Ollama API Endpoint for generating completions
OLLAMA_URL = "http://localhost:11434"

# The local LLM model to use for the chat assistant
OLLAMA_MODEL = "qwen2.5:14b"

# Timeout in seconds for the Ollama API request
OLLAMA_TIMEOUT = 60

# ── Multi-Agent Analysis Configuration ────────────────────────────────────────

# Model used by the multi-agent pipeline (preferably a general reasoning model)
AGENT_MODEL = "qwen2.5:14b"

# Timeout per agent call (longer, since agents chain sequentially)
AGENT_TIMEOUT = 120

# Maximum characters for the final synthesised report saved to the database
AGENT_MAX_CHARS = 1000

# Pool of English names randomly assigned to agents each session
AGENT_NAMES = ["Arthur", "Sarah", "Michael", "Elena", "James", "Priya", "Omar", "Clara"]

# Knowledge base directory (relative to app root)
KNOWLEDGE_BASE_DIR = "knowledge_base"
