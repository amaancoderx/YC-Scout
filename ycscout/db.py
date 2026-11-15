"""Storage: a local SQLite file (WAL mode), or a Turso cloud database when TURSO_DATABASE_URL is set."""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY,          -- YC company id
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    batch           TEXT,                         -- "Fall 2026"
    batch_slug      TEXT,                         -- "fall-2026"
    one_liner       TEXT,
    description     TEXT,
    summary         TEXT,                         -- 2-3 line description
    website         TEXT,
    domain          TEXT,
    site_domain     TEXT,                         -- domain the website actually resolves to
    mail_domain     TEXT,                         -- domain founder emails are built on
    location        TEXT,
    country         TEXT,
    team_size       INTEGER,
    year_founded    INTEGER,
    industry        TEXT,
    subindustry     TEXT,
    tags            TEXT DEFAULT '[]',
    yc_status       TEXT,
    is_hiring       INTEGER DEFAULT 0,
    yc_partner      TEXT,
    yc_url          TEXT,
    logo_url        TEXT,
    linkedin_url    TEXT,
    twitter_url     TEXT,
    github_url      TEXT,
    crunchbase_url  TEXT,
    other_links     TEXT DEFAULT '{}',            -- instagram, discord, calendly ...
    launch_title    TEXT,
    launch_url      TEXT,
    launched_at     TEXT,
    funding_total   TEXT,                         -- headline amount
    funding_detail  TEXT,                         -- human readable breakdown
    funding_rounds  TEXT DEFAULT '[]',            -- [{round, amount, date, investors, source}]
    funding_source  TEXT DEFAULT 'yc_standard',   -- yc_standard | researched
    phones          TEXT DEFAULT '[]',            -- [{number, source_url}]
    whatsapp        TEXT DEFAULT '[]',            -- [{number, link, source_url}]
    research_notes  TEXT,                         -- AI research highlights (markdown)
    research_sources TEXT DEFAULT '[]',
    website_ok      INTEGER,
    stage           TEXT DEFAULT 'new',           -- new|qualified|contacted|replied|meeting|won|lost|skip
    priority        INTEGER DEFAULT 0,
    fit_score       INTEGER,                      -- 0-100 match with the sender (ycscout.fit)
    fit_reasons     TEXT DEFAULT '[]',
    fit_proof       TEXT,                         -- sender's most relevant proof line
    notes           TEXT DEFAULT '',
    first_seen_at   TEXT,
    scraped_at      TEXT,
    crawled_at      TEXT,
    researched_at   TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_companies_batch ON companies(batch_slug);
CREATE INDEX IF NOT EXISTS idx_companies_stage ON companies(stage);

CREATE TABLE IF NOT EXISTS founders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    yc_user_id  INTEGER,
    name        TEXT NOT NULL,
    first_name  TEXT,
    last_name   TEXT,
    title       TEXT,
    bio         TEXT,
    linkedin_url TEXT,
    twitter_url TEXT,
    avatar_url  TEXT,
    is_active   INTEGER DEFAULT 1,
    UNIQUE(company_id, name)
);

CREATE TABLE IF NOT EXISTS contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    founder_id  INTEGER REFERENCES founders(id) ON DELETE CASCADE,
    email       TEXT NOT NULL,
    kind        TEXT NOT NULL,       -- founder | company | person
    label       TEXT,                -- e.g. "hello@", "Careers"
    confidence  TEXT NOT NULL,       -- verified | inferred | likely | guess
    source      TEXT NOT NULL,       -- website | research | pattern | manual
    source_url  TEXT,
    mx_ok       INTEGER,
    is_primary  INTEGER DEFAULT 0,
    created_at  TEXT,
    UNIQUE(company_id, email)
);
CREATE INDEX IF NOT EXISTS idx_contacts_company ON contacts(company_id);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY,  -- YC job id
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title       TEXT,
    url         TEXT,
    apply_url   TEXT,
    location    TEXT,
    type        TEXT,
    role        TEXT,
    salary      TEXT,
    equity      TEXT,
    experience  TEXT,
    visa        TEXT,
    posted      TEXT,
    active      INTEGER DEFAULT 1,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);

CREATE TABLE IF NOT EXISTS news (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    title       TEXT,
    url         TEXT,
    date        TEXT,
    source      TEXT DEFAULT 'yc',
    UNIQUE(company_id, url)
);

CREATE TABLE IF NOT EXISTS outreach (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id  INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    founder_id  INTEGER REFERENCES founders(id) ON DELETE SET NULL,
    to_email    TEXT NOT NULL,
    to_name     TEXT,
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    step        INTEGER DEFAULT 1,     -- 1 = first touch, 2+ = follow-ups
    status      TEXT DEFAULT 'draft',  -- draft|approved|sending|sent|failed|replied|bounced|cancelled
    generated_by TEXT,                 -- ai | template
    message_id  TEXT,
    thread_ref  TEXT,                  -- message id of step 1, for threading
    error       TEXT,
    created_at  TEXT,
    approved_at TEXT,
    sent_at     TEXT,
    replied_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_outreach_status ON outreach(status);
CREATE INDEX IF NOT EXISTS idx_outreach_email ON outreach(to_email);

CREATE TABLE IF NOT EXISTS suppression (
    email       TEXT PRIMARY KEY,
    reason      TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    label       TEXT,
    params      TEXT DEFAULT '{}',
    status      TEXT DEFAULT 'queued',   -- queued|running|done|failed|cancelled
    progress    INTEGER DEFAULT 0,
    total       INTEGER DEFAULT 0,
    summary     TEXT,
    log         TEXT DEFAULT '',
    started_at  TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- Agent conversations: Gemini history (to continue) + UI transcript (to show).
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    history     TEXT DEFAULT '[]',
    messages    TEXT DEFAULT '[]',
    created_at  TEXT,
    updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_chats_updated ON chats(updated_at);

-- Long-term memory the agent carries across chats.
CREATE TABLE IF NOT EXISTS memories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT NOT NULL,
    source      TEXT DEFAULT 'agent',      -- agent | you
    chat_id     TEXT,
    created_at  TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_text ON memories(lower(text));
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "sender_profile": (
        "Name: \nRole: \nWhat I offer: \nWhy YC startups: \nProof / links: \n"
    ),
    "outreach_goal": "Introduce myself and ask for a short call.",
    "email_tone": "Direct, warm, concise. Plain text. No buzzwords.",
    "template_subject": "Quick question about {{company}}",
    "template_body": (
        "Hi {{first_name}},\n\n"
        "I came across {{company}} in YC's {{batch}} batch ({{one_liner}}) and wanted to reach out.\n\n"
        "[One or two lines about who you are and why you're reaching out.]\n\n"
        "Would you be open to a 15-minute call next week?\n\n"
        "Best,\n{{sender_name}}"
    ),
    "followup_subject": "Re: {{original_subject}}",
    "followup_body": (
        "Hi {{first_name}},\n\n"
        "Bumping this in case it got buried. Happy to keep it short.\n\n"
        "Best,\n{{sender_name}}"
    ),
    "signature_footer": "If this isn't relevant, just reply \"no thanks\" and I won't follow up.",
    "physical_address": "",
    "daily_send_limit": 40,
    "send_delay_seconds": 45,
    "followup_after_days": 4,
    "max_followups": 1,
    "auto_followups": False,
    "auto_sync_enabled": False,
    "auto_sync_hours": 24,
    "auto_sync_batches": [],
    "auto_research_new": False,
    "auto_sheet_sync": True,
    # One per line:  keyword, keyword => proof line used in emails ({{proof_line}})
    "fit_strengths": "",
    "memory_enabled": True,
    "default_proof_line": "",
}

# Columns added after the first release; created on startup if missing.
MIGRATIONS = {
    "companies": {"fit_score": "INTEGER", "fit_reasons": "TEXT DEFAULT '[]'", "fit_proof": "TEXT"},
}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Connections: a local SQLite file, or a Turso (libSQL) cloud database when
# TURSO_DATABASE_URL is set (used on Render, whose disk is wiped on restart).
# Both expose the same sqlite3-style API to the rest of the app.
# ---------------------------------------------------------------------------
class _Row(tuple):
    """Row usable as row[0], row["name"] and dict(row), like sqlite3.Row."""

    _names: tuple = ()

    def __new__(cls, values, names):
        r = super().__new__(cls, values)
        r._names = names
        return r

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._names.index(key))
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


class _Cursor:
    def __init__(self, cur):
        self._cur = cur
        # SQLite names are case-insensitive; Turso can return a column as declared (e.g. KEY).
        # Every column and alias in this app is lowercase, so normalise to that.
        self._names = tuple(str(d[0]).lower() for d in (cur.description or ()))

    def fetchall(self):
        return [_Row(r, self._names) for r in self._cur.fetchall()]

    def fetchone(self):
        r = self._cur.fetchone()
        return None if r is None else _Row(r, self._names)

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description


class _RemoteConn:
    """Thin wrapper over a libsql connection; one per thread, reused."""

    def __init__(self, raw):
        self._c = raw

    def execute(self, sql, params=()):
        return _Cursor(self._c.execute(sql, tuple(params)))

    def executemany(self, sql, seq):
        for params in seq:
            self._c.execute(sql, tuple(params))

    def executescript(self, script):
        self._c.executescript(script)

    def commit(self):
        self._c.commit()

    def rollback(self):
        try:
            self._c.rollback()
        except Exception:
            pass

    def close(self):  # kept open and reused by the thread
        pass


_local = threading.local()


def remote() -> bool:
    return bool(config.TURSO_DATABASE_URL)


def _remote_conn() -> _RemoteConn:
    conn = getattr(_local, "conn", None)
    if conn is None:
        import libsql  # only needed in the cloud

        conn = _RemoteConn(libsql.connect(config.TURSO_DATABASE_URL, auth_token=config.TURSO_AUTH_TOKEN))
        _local.conn = conn
    return conn


def _drop_remote_conn() -> None:
    _local.conn = None


def _connect():
    if remote():
        return _remote_conn()
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def tx():
    """Serialized write transaction."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            if remote():
                _drop_remote_conn()  # a broken stream is not reused
            raise
        finally:
            conn.close()


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    except Exception:
        if remote():
            _drop_remote_conn()
        raise
    finally:
        conn.close()


def one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: Iterable[Any] = ()) -> Any:
    row = one(sql, params)
    return next(iter(row.values())) if row else None


def execute(sql: str, params: Iterable[Any] = ()) -> int:
    with tx() as conn:
        cur = conn.execute(sql, tuple(params))
        return cur.lastrowid


def init() -> None:
    with tx() as conn:
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if have:
                for col, ddl in cols.items():
                    if col not in have:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
    # Any run left 'running' by a crashed process is no longer running.
    execute(
        "UPDATE runs SET status='failed', summary=COALESCE(summary,'Interrupted (app restarted)'), "
        "finished_at=? WHERE status IN ('running','queued')",
        (now(),),
    )
    execute("UPDATE outreach SET status='approved' WHERE status='sending'")


def get_setting(key: str, default: Any = None) -> Any:
    row = one("SELECT value FROM settings WHERE key=?", (key,))
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    try:
        return json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return row["value"]


def all_settings() -> dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    for row in query("SELECT key, value FROM settings"):
        try:
            out[row["key"]] = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError):
            out[row["key"]] = row["value"]
    return out


def set_settings(values: dict[str, Any]) -> None:
    with tx() as conn:
        for key, value in values.items():
            if key not in DEFAULT_SETTINGS:
                continue
            conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )


def loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def is_suppressed(email: str) -> bool:
    return one("SELECT 1 FROM suppression WHERE email=?", (email.lower(),)) is not None


def suppress(email: str, reason: str) -> None:
    execute(
        "INSERT OR IGNORE INTO suppression(email, reason, created_at) VALUES (?, ?, ?)",
        (email.lower(), reason, now()),
    )


# ---------------------------------------------------------------------------
# Copy data between the local file and the cloud database
# ---------------------------------------------------------------------------
TABLE_ORDER = ["companies", "founders", "contacts", "jobs", "news", "outreach", "suppression",
               "runs", "settings", "chats", "memories"]


def push_local_to_remote(local_path, log=print) -> dict:
    """Replace the cloud database contents with the local SQLite file (schema is created first)."""
    if not remote():
        raise RuntimeError("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN first.")
    init()
    src = sqlite3.connect(str(local_path))
    src.row_factory = sqlite3.Row
    counts = {}
    try:
        with tx() as conn:
            for table in reversed(TABLE_ORDER):
                conn.execute(f"DELETE FROM {table}")
        for table in TABLE_ORDER:
            local_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
            remote_cols = {str(r[1]).lower() for r in _connect().execute(f"PRAGMA table_info({table})").fetchall()}
            cols = [c for c in local_cols if c.lower() in remote_cols]
            if not cols:
                continue
            rows = src.execute(f"SELECT {', '.join(f'"{c}"' for c in cols)} FROM {table}").fetchall()
            per = max(1, 800 // len(cols))  # stay under SQLite's bound-parameter limit
            with tx() as conn:
                for i in range(0, len(rows), per):
                    chunk = rows[i:i + per]
                    marks = ", ".join("(" + ", ".join("?" * len(cols)) + ")" for _ in chunk)
                    params = [v for r in chunk for v in tuple(r)]
                    quoted = ", ".join(f'"{c}"' for c in cols)
                    conn.execute(f"INSERT OR REPLACE INTO {table} ({quoted}) VALUES {marks}", params)
            counts[table] = len(rows)
            log(f"  {table}: {len(rows)} rows")
    finally:
        src.close()
    return counts
