"""Settings, all overridable with environment variables."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

DATA_DIR = REPO_DIR / "data"
FRONTEND_DIR = REPO_DIR / "frontend"

DB_PATH = os.getenv("SLOTH_DB", str(BACKEND_DIR / "sloth.db"))

# Ollama can run on another machine/host (e.g. Windows host while the app runs in WSL).
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("SLOTH_MODEL", "gemma3:1b")

# CPU-only laptops are slow; give each email a generous timeout.
LLM_TIMEOUT_S = float(os.getenv("SLOTH_LLM_TIMEOUT", "240"))

# Longest email body (characters) sent to the model.
MAX_BODY_CHARS = int(os.getenv("SLOTH_MAX_BODY", "3000"))

# Cache validated model answers in SQLite so re-running after a code change takes seconds.
USE_CACHE = os.getenv("SLOTH_CACHE", "1") != "0"
