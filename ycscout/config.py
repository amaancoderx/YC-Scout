"""Runtime configuration.

Secrets (API keys, SMTP passwords) live in `.env`. Everything a user may want to
tweak from the dashboard (sender profile, templates, limits) lives in the
`settings` table and is read through `ycscout.db.get_setting`.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

try:  # Use the OS certificate store for every TLS client (Google, SMTP, Anthropic).
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


DATA_DIR = Path(_env("YCSCOUT_DATA_DIR", str(ROOT / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "ycscout.db"
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# --- Gemini (AI research, email writing, agent) ------------------------------
GEMINI_API_KEY = _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
GEMINI_MODEL = _env("GEMINI_MODEL", "gemini-3.5-flash")
# Tried in order when the main model is rate-limited, overloaded or unavailable.
GEMINI_FALLBACK_MODELS = [m.strip() for m in (_env("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash,gemini-flash-lite-latest,gemini-3.1-flash-lite") or "").split(",") if m.strip()]
# Requests per minute across the whole app (free tier is ~10/min on Flash models).
GEMINI_RPM = _env_int("GEMINI_RPM", 10)
# Web research needs Google Search grounding; on free keys that quota exists on 2.5 Flash.
GEMINI_RESEARCH_MODEL = _env("GEMINI_RESEARCH_MODEL", "gemini-2.5-flash")

# --- Email (SMTP for sending, IMAP for reply/bounce detection) --------------
SMTP_HOST = _env("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
FROM_EMAIL = _env("FROM_EMAIL") or SMTP_USER
FROM_NAME = _env("FROM_NAME")
IMAP_HOST = _env("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = _env_int("IMAP_PORT", 993)

# --- Google Sheets ------------------------------------------------------------
GOOGLE_SERVICE_ACCOUNT_FILE = _env("GOOGLE_SERVICE_ACCOUNT_FILE")
if GOOGLE_SERVICE_ACCOUNT_FILE and not Path(GOOGLE_SERVICE_ACCOUNT_FILE).is_absolute():
    GOOGLE_SERVICE_ACCOUNT_FILE = str(ROOT / GOOGLE_SERVICE_ACCOUNT_FILE)
GOOGLE_SHEET_ID = _env("GOOGLE_SHEET_ID")

# --- Web server ---------------------------------------------------------------
HOST = _env("YCSCOUT_HOST", "127.0.0.1")
PORT = _env_int("YCSCOUT_PORT", 8000)

# --- Scraping -----------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
YC_CONCURRENCY = _env_int("YC_CONCURRENCY", 4)
CRAWL_CONCURRENCY = _env_int("CRAWL_CONCURRENCY", 8)

# YC's standard investment. Shown when no company-specific round is on record.
YC_STANDARD_DEAL = "$500K"
YC_STANDARD_DEAL_DETAIL = "YC standard deal: $125K for 7% + $375K uncapped MFN SAFE"


def ai_enabled() -> bool:
    return bool(GEMINI_API_KEY)


def smtp_enabled() -> bool:
    return bool(SMTP_HOST and SMTP_USER and SMTP_PASSWORD and FROM_EMAIL)


def imap_enabled() -> bool:
    return bool(IMAP_HOST and SMTP_USER and SMTP_PASSWORD)


def sheets_enabled() -> bool:
    return bool(GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEET_ID and Path(GOOGLE_SERVICE_ACCOUNT_FILE).exists())
