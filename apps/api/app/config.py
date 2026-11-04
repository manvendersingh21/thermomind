"""Central configuration. Secrets stay server-side; never return the key from any endpoint."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")

APP_VERSION = "0.1.0"
BUILD = os.getenv("THERMOMIND_BUILD", "hackathon-2026-11-04")

DATA_DIR = Path(os.getenv("THERMOMIND_DATA_DIR", REPO_ROOT / "data"))
RAW_UCI_DIR = DATA_DIR / "raw" / "uci_551"
FIXTURE_DIR = DATA_DIR / "fixtures"
MODEL_DIR = Path(os.getenv("THERMOMIND_MODEL_DIR", DATA_DIR / "models"))
DB_PATH = Path(os.getenv("THERMOMIND_DB", DATA_DIR / "thermomind.db"))
WEB_DIST = REPO_ROOT / "apps" / "web" / "dist"

META_BASE_URL = os.getenv("META_BASE_URL", "https://api.meta.ai/v1")
META_MODEL = os.getenv("META_MODEL", "muse-spark-1.3")
META_TIMEOUT_S = float(os.getenv("META_TIMEOUT_S", "120"))
META_MAX_TOOL_ROUNDS = int(os.getenv("META_MAX_TOOL_ROUNDS", "8"))
META_MAX_TOKENS = int(os.getenv("META_MAX_TOKENS", "6000"))

MAX_UPLOAD_BYTES = int(os.getenv("THERMOMIND_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MAX_SERIES_POINTS = 2000
DEFAULT_REFERENCE_ROWS = 240  # reference window immediately preceding the case window

UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/551/gas+turbine+co+and+nox+emission+data+set.zip"


def meta_api_key() -> str | None:
    """MODEL_API_KEY is the documented name; MUSE_API_KEY is accepted as an alias."""
    return os.getenv("MODEL_API_KEY") or os.getenv("MUSE_API_KEY") or None


def meta_configured() -> bool:
    return bool(meta_api_key())
