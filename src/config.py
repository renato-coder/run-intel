"""Centralized configuration for Run Intel.

Validates all required environment variables at import time.
Fails fast with clear error messages if anything is missing.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (before reading any env vars)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


def _require_env(name: str) -> str:
    """Get a required environment variable or crash with a clear message."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# ── Database ──────────────────────────────────────────────────────
DATABASE_URL = _require_env("DATABASE_URL")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# ── Whoop API ─────────────────────────────────────────────────────
WHOOP_CLIENT_ID = _require_env("WHOOP_CLIENT_ID")
WHOOP_CLIENT_SECRET = _require_env("WHOOP_CLIENT_SECRET")
WHOOP_REDIRECT_URI = _require_env("WHOOP_REDIRECT_URI")

# ── App ───────────────────────────────────────────────────────────
APP_PASSWORD = _require_env("APP_PASSWORD")
SESSION_SECRET = _require_env("SESSION_SECRET")
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
PORT = int(os.environ.get("PORT", 5050))

# ── Paths ─────────────────────────────────────────────────────────
TOKEN_PATH = Path(__file__).resolve().parent.parent / "data" / "tokens.json"
