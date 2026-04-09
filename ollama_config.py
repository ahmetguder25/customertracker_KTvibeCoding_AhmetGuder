# ollama_config.py

# Ollama API Endpoint for generating completions
OLLAMA_URL = "http://localhost:11434/api/generate"

# The local LLM model to use for AI generations (e.g. qwen3-coder:30b, llama3, mistral)
OLLAMA_MODEL = "qwen3-coder:30b"

# Timeout in seconds for the Ollama API request
OLLAMA_TIMEOUT = 60
