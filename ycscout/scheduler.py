"""In-process scheduler (runs while the dashboard is open).

Every few minutes it checks, based on settings:
  * auto sync  - re-pull the chosen batches every N hours (new companies, new jobs)
  * replies    - scan the inbox for replies and bounces (hourly)
  * follow-ups - create follow-up drafts for unanswered emails; send them if
                 auto-follow-ups is on. First-touch emails are never auto-sent.
  * keep-awake - when hosted (PUBLIC_URL / RENDER_EXTERNAL_URL), ping /healthz every
                 10 minutes so a free instance never sleeps.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

from . import config, db, jobs, outreach, pipeline
from .sources import yc

TICK_SECONDS = 300
_started = False
_state = {"last_reply_check": None, "last_tick": None, "last_error": None}


def _last_run(kind: str) -> datetime | None:
    ts = db.scalar("SELECT MAX(started_at) FROM runs WHERE kind=? AND status IN ('done','running')", (kind,))
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def tick() -> None:
    now = datetime.now(timezone.utc)
    _state["last_tick"] = now.isoformat()
    s = db.all_settings()

    if s.get("auto_sync_enabled") and not jobs.is_running("sync"):
        last = _last_run("sync")
        if not last or now - last > timedelta(hours=max(1, int(s.get("auto_sync_hours") or 24))):
            slugs = s.get("auto_sync_batches") or [b.slug for b in yc.recent_batches(2)]
            research = bool(s.get("auto_research_new"))
            jobs.start("sync", f"Scheduled sync {', '.join(slugs)}", {"batches": slugs, "scheduled": True},
                       lambda run: pipeline.sync_batches(run, slugs, research=research))

    if config.imap_enabled():
        last = _state["last_reply_check"]
        if not last or now - last > timedelta(hours=1):
            _state["last_reply_check"] = now
            if db.scalar("SELECT COUNT(*) FROM outreach WHERE status='sent'"):
                jobs.start("replies", "Check replies", {"scheduled": True}, lambda run: outreach.check_replies(run))

    outreach.schedule_followups()
    if s.get("auto_followups") and config.smtp_enabled() and not jobs.is_running("send"):
        if db.scalar("SELECT COUNT(*) FROM outreach WHERE status='approved' AND step>1"):
            jobs.start("send", "Send follow-ups", {"scheduled": True},
                       lambda run: outreach.send_approved(run, only_followups=True))


def _loop() -> None:
    time.sleep(20)
    while True:
        try:
            tick()
            _state["last_error"] = None
        except Exception as exc:
            _state["last_error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(TICK_SECONDS)


def start() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()
    if config.PUBLIC_URL:
        threading.Thread(target=_keep_awake, name="keep-awake", daemon=True).start()


KEEP_AWAKE_SECONDS = 600


def _keep_awake() -> None:
    """Hosted (e.g. Render Free): visit our own public URL every 10 minutes.

    Free instances sleep after 15 minutes without inbound traffic; a request to the
    public URL goes through the platform's proxy and counts as traffic, so the app,
    its scheduler and any running jobs stay up. Use an external uptime monitor too.
    """
    import httpx

    url = config.PUBLIC_URL + "/healthz"
    time.sleep(60)
    while True:
        try:
            httpx.get(url, timeout=20)
            _state["last_ping"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except Exception as exc:
            _state["last_ping_error"] = f"{type(exc).__name__}: {exc}"
        time.sleep(KEEP_AWAKE_SECONDS)


def status() -> dict:
    return dict(_state, last_reply_check=_state["last_reply_check"].isoformat() if _state["last_reply_check"] else None)
