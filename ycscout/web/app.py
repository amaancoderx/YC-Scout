"""Dashboard API + static frontend."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__, ai, agent, config, db, export, fit, jobs, outreach, pipeline, scheduler
from ..sources import yc
from . import auth

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="YC Scout", version=__version__, docs_url="/api/docs")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.middleware("http")(auth.middleware)


@app.get("/login")
def login_page(request: Request):
    return auth.login_page(request)


@app.post("/api/login")
def login(request: Request, payload: dict = Body(...)):
    return auth.login(request, payload)


@app.post("/api/logout")
def logout():
    return auth.logout()


@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    # Uptime monitors (e.g. UptimeRobot) often use HEAD requests.
    return {"ok": True}

STAGES = ["new", "qualified", "contacted", "replied", "meeting", "won", "lost", "skip"]
_batch_cache: dict[str, Any] = {"at": 0, "data": None}


@app.on_event("startup")
def _startup() -> None:
    db.init()
    scheduler.start()


@app.exception_handler(ai.AIError)
def _ai_error(_, exc: ai.AIError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.exception_handler(RuntimeError)
def _runtime_error(_, exc: RuntimeError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# Status / overview
# ---------------------------------------------------------------------------

@app.get("/api/status")
def status():
    return {
        "version": __version__,
        "integrations": {
            "ai": {"ok": config.ai_enabled(), "detail": ai.model_label() if config.ai_enabled() else "Add GEMINI_API_KEY to .env",
                   "model": ai.model_label() if config.ai_enabled() else None},
            "smtp": {"ok": config.smtp_enabled(), "detail": (f"{config.FROM_EMAIL} via Gmail API" if config.gmail_api_enabled() else f"{config.FROM_EMAIL} via {config.SMTP_HOST}") if config.smtp_enabled() else "Add SMTP_USER / SMTP_PASSWORD to .env"},
            "imap": {"ok": config.imap_enabled(), "detail": config.IMAP_HOST if config.imap_enabled() else "Uses the SMTP login"},
            "sheets": {"ok": config.sheets_enabled(), "detail": f"Sheet {config.GOOGLE_SHEET_ID[:10]}…" if config.sheets_enabled() else "Add GOOGLE_SERVICE_ACCOUNT_FILE / GOOGLE_SHEET_ID"},
        },
        "scheduler": scheduler.status(),
        "sent_today": outreach.sent_today(),
        "daily_limit": db.get_setting("daily_send_limit", 40),
        "active_runs": db.query("SELECT id, kind, label, progress, total FROM runs WHERE status='running' ORDER BY id DESC"),
        "sender_first_name": _first_name(),
        "auth": {"enabled": auth.enabled(), "email": config.APP_EMAIL if auth.enabled() else None},
    }


def _first_name() -> str:
    name = (outreach.sender_name() or "").strip()
    return name.split()[0] if name else ""


@app.get("/api/overview")
def overview():
    q = db.scalar
    kpis = {
        "companies": q("SELECT COUNT(*) FROM companies") or 0,
        "founders": q("SELECT COUNT(*) FROM founders WHERE is_active=1") or 0,
        "with_verified_email": q("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE confidence IN ('verified','inferred')") or 0,
        "with_any_email": q("SELECT COUNT(DISTINCT company_id) FROM contacts") or 0,
        "hiring": q("SELECT COUNT(*) FROM companies c WHERE is_hiring=1 OR EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1)") or 0,
        "open_roles": q("SELECT COUNT(*) FROM jobs WHERE active=1") or 0,
        "remote_roles": q("SELECT COUNT(*) FROM jobs WHERE active=1 AND lower(COALESCE(location,'')) LIKE '%remote%'") or 0,
        "researched": q("SELECT COUNT(*) FROM companies WHERE researched_at IS NOT NULL") or 0,
        "raised_beyond_yc": q("SELECT COUNT(*) FROM companies WHERE funding_source='researched'") or 0,
        "sent": q("SELECT COUNT(*) FROM outreach WHERE status IN ('sent','replied','bounced')") or 0,
        "replied": q("SELECT COUNT(DISTINCT to_email) FROM outreach WHERE status='replied'") or 0,
        "drafts": q("SELECT COUNT(*) FROM outreach WHERE status='draft'") or 0,
        "approved": q("SELECT COUNT(*) FROM outreach WHERE status='approved'") or 0,
    }
    batches = db.query(
        """SELECT batch, batch_slug, COUNT(*) AS companies,
                  SUM(CASE WHEN EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1) THEN 1 ELSE 0 END) AS hiring,
                  SUM(CASE WHEN EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id AND ct.confidence IN ('verified','inferred')) THEN 1 ELSE 0 END) AS verified
           FROM companies c GROUP BY batch_slug ORDER BY batch_slug DESC""")
    batches.sort(key=lambda b: yc.Batch(b["batch_slug"] or "", "", 0).sort_key, reverse=True)
    funnel = {s: 0 for s in STAGES}
    for r in db.query("SELECT stage, COUNT(*) n FROM companies GROUP BY stage"):
        funnel[r["stage"] or "new"] = r["n"]
    industries = db.query("SELECT industry, COUNT(*) n FROM companies WHERE industry IS NOT NULL GROUP BY industry ORDER BY n DESC LIMIT 8")
    roles = db.query("SELECT role, COUNT(*) n FROM jobs WHERE active=1 AND role IS NOT NULL GROUP BY role ORDER BY n DESC LIMIT 8")
    newest = db.query(
        """SELECT id, name, batch, one_liner, logo_url, first_seen_at FROM companies
           ORDER BY first_seen_at DESC, id DESC LIMIT 6""")
    runs = db.query("SELECT id, kind, label, status, progress, total, summary, started_at, finished_at FROM runs ORDER BY id DESC LIMIT 6")
    return {"kpis": kpis, "batches": batches, "funnel": funnel, "industries": industries, "roles": roles,
            "newest": newest, "runs": runs}


@app.get("/api/batches")
def batches():
    if not _batch_cache["data"] or time.time() - _batch_cache["at"] > 600:
        _batch_cache["data"] = yc.list_batches()
        _batch_cache["at"] = time.time()
    loaded = {r["batch_slug"]: r for r in db.query(
        "SELECT batch_slug, COUNT(*) n, MAX(scraped_at) last FROM companies GROUP BY batch_slug")}
    return [{"slug": b.slug, "name": b.name, "count": b.count,
             "loaded": (loaded.get(b.slug) or {}).get("n", 0), "last_scraped": (loaded.get(b.slug) or {}).get("last")}
            for b in _batch_cache["data"][:12]]


# ---------------------------------------------------------------------------
# Companies
# ---------------------------------------------------------------------------

SORTS = {
    "name": "c.name COLLATE NOCASE", "batch": "c.batch_slug", "team": "c.team_size", "roles": "open_roles", "fit": "COALESCE(c.fit_score, -1)",
    "stage": "c.stage", "updated": "c.updated_at", "added": "c.first_seen_at", "priority": "c.priority",
}


REMOTE_SQL = "lower(COALESCE(j.location,'')) LIKE '%remote%'"
PHONE_SQL = "(COALESCE(c.phones,'[]') NOT IN ('','[]') OR COALESCE(c.whatsapp,'[]') NOT IN ('','[]'))"


@app.get("/api/companies")
def companies(
    q: str = "", batch: str = "", industry: str = "", stage: str = "", hiring: bool = False,
    remote: bool = False, phone: bool = False, email: str = "", researched: bool = False, sort: str = "batch", dir: str = "desc",
    page: int = 1, page_size: int = Query(50, le=500),
):
    where, params = ["1=1"], []
    if q:
        t = f"%{q.lower()}%"
        where.append("(lower(c.name) LIKE ? OR lower(c.one_liner) LIKE ? OR lower(c.description) LIKE ? OR lower(c.tags) LIKE ? "
                     "OR EXISTS (SELECT 1 FROM founders f WHERE f.company_id=c.id AND lower(f.name) LIKE ?))")
        params += [t] * 5
    if batch:
        slugs = [b for b in batch.split(",") if b]
        where.append(f"c.batch_slug IN ({','.join('?' * len(slugs))})")
        params += slugs
    if industry:
        where.append("c.industry=?")
        params.append(industry)
    if stage:
        where.append("c.stage=?")
        params.append(stage)
    if hiring:
        where.append("EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1)")
    if remote:
        where.append(f"EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1 AND {REMOTE_SQL})")
    if phone:
        where.append(PHONE_SQL)
    if email == "verified":
        where.append("EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id AND ct.confidence IN ('verified','inferred'))")
    elif email == "any":
        where.append("EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id)")
    elif email == "none":
        where.append("NOT EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id)")
    if researched:
        where.append("c.researched_at IS NOT NULL")
    w = " AND ".join(where)
    total = db.scalar(f"SELECT COUNT(*) FROM companies c WHERE {w}", params)
    order = SORTS.get(sort, "c.batch_slug")
    direction = "ASC" if dir == "asc" else "DESC"
    rows = db.query(
        f"""SELECT c.id, c.name, c.slug, c.batch, c.batch_slug, c.one_liner, c.website, c.location, c.team_size,
                   c.industry, c.logo_url, c.stage, c.priority, c.funding_total, c.funding_source, c.researched_at,
                   c.fit_score, c.fit_reasons, c.phones, c.whatsapp,
                   (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.active=1) AS open_roles,
                   (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.active=1 AND {REMOTE_SQL}) AS remote_roles,
                   (SELECT GROUP_CONCAT(f.name, ', ') FROM founders f WHERE f.company_id=c.id AND f.is_active=1) AS founders,
                   (SELECT ct.email FROM contacts ct WHERE ct.company_id=c.id AND ct.is_primary=1 ORDER BY
                      CASE ct.kind WHEN 'founder' THEN 0 ELSE 1 END,
                      CASE ct.confidence WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 WHEN 'likely' THEN 2 ELSE 3 END LIMIT 1) AS best_email,
                   (SELECT ct.confidence FROM contacts ct WHERE ct.company_id=c.id AND ct.is_primary=1 ORDER BY
                      CASE ct.kind WHEN 'founder' THEN 0 ELSE 1 END,
                      CASE ct.confidence WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 WHEN 'likely' THEN 2 ELSE 3 END LIMIT 1) AS best_confidence,
                   (SELECT o.status FROM outreach o WHERE o.company_id=c.id ORDER BY o.id DESC LIMIT 1) AS last_outreach
            FROM companies c WHERE {w}
            ORDER BY c.priority DESC, {order} {direction}, c.name COLLATE NOCASE LIMIT ? OFFSET ?""",
        params + [page_size, (max(page, 1) - 1) * page_size],
    )
    industries = [r["industry"] for r in db.query("SELECT DISTINCT industry FROM companies WHERE industry IS NOT NULL ORDER BY industry")]
    return {"rows": rows, "total": total, "page": page, "page_size": page_size, "industries": industries}


@app.get("/api/companies/ids")
def company_ids(q: str = "", batch: str = "", industry: str = "", stage: str = "", hiring: bool = False,
                remote: bool = False, phone: bool = False, email: str = "", researched: bool = False):
    res = companies(q=q, batch=batch, industry=industry, stage=stage, hiring=hiring, remote=remote, phone=phone, email=email,
                    researched=researched, page=1, page_size=500)
    return [r["id"] for r in res["rows"]]


@app.get("/api/companies/{cid}")
def company(cid: int):
    d = agent.company_detail(cid)
    if not d:
        raise HTTPException(404, "Company not found")
    return d


@app.patch("/api/companies/{cid}")
def update_company(cid: int, payload: dict = Body(...)):
    allowed = {"stage", "priority", "notes"}
    sets = {k: v for k, v in payload.items() if k in allowed}
    if "stage" in sets and sets["stage"] not in STAGES:
        raise HTTPException(400, "Invalid stage")
    if sets:
        db.execute(f"UPDATE companies SET {', '.join(f'{k}=?' for k in sets)}, updated_at=? WHERE id=?",
                   (*sets.values(), db.now(), cid))
    return {"ok": True}


@app.post("/api/companies/bulk")
def bulk_companies(payload: dict = Body(...)):
    ids = [int(i) for i in payload.get("ids") or []]
    stage = payload.get("stage")
    if stage not in STAGES or not ids:
        raise HTTPException(400, "ids and a valid stage are required")
    with db.tx() as conn:
        conn.executemany("UPDATE companies SET stage=? WHERE id=?", [(stage, i) for i in ids])
    return {"updated": len(ids)}


@app.post("/api/companies/{cid}/refresh")
def refresh_company(cid: int):
    pipeline.enrich_company(cid, crawl=True)
    fit.rescore([cid])
    return agent.company_detail(cid)


@app.post("/api/contacts")
def add_contact(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    cid = int(payload.get("company_id") or 0)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) or not cid:
        raise HTTPException(400, "Enter a valid email")
    fid = payload.get("founder_id") or None
    db.execute(
        """INSERT INTO contacts(company_id, founder_id, email, kind, confidence, source, created_at)
           VALUES (?,?,?,?, 'verified', 'manual', ?)
           ON CONFLICT(company_id, email) DO UPDATE SET confidence='verified', source='manual', founder_id=COALESCE(excluded.founder_id, contacts.founder_id)""",
        (cid, fid, email, "founder" if fid else "company", db.now()),
    )
    pipeline.rebuild_contacts(cid)
    return agent.company_detail(cid)


@app.delete("/api/contacts/{contact_id}")
def delete_contact(contact_id: int):
    row = db.one("SELECT company_id FROM contacts WHERE id=?", (contact_id,))
    if not row:
        raise HTTPException(404, "Not found")
    db.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
    pipeline.rebuild_contacts(row["company_id"])
    return agent.company_detail(row["company_id"])


# ---------------------------------------------------------------------------
# Jobs (background runs)
# ---------------------------------------------------------------------------

def _start(kind, label, params, fn, exclusive=True):
    try:
        return {"run_id": jobs.start(kind, label, params, fn, exclusive=exclusive)}
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/runs/sync")
def run_sync(payload: dict = Body(...)):
    slugs = [s for s in payload.get("batches") or [] if re.fullmatch(r"(winter|spring|summer|fall)-\d{4}", s)]
    if not slugs:
        raise HTTPException(400, "Pick at least one batch")
    crawl, research, force = bool(payload.get("crawl", True)), bool(payload.get("research")), bool(payload.get("force"))
    if research and not config.ai_enabled():
        raise HTTPException(400, "AI research needs GEMINI_API_KEY in .env")
    label = "Sync " + ", ".join(slugs) + (" + research" if research else "")
    return _start("sync", label, payload, lambda run: pipeline.sync_batches(run, slugs, crawl=crawl, research=research, force=force))


@app.post("/api/runs/research")
def run_research(payload: dict = Body(...)):
    ids = [int(i) for i in payload.get("ids") or []]
    if not ids:
        raise HTTPException(400, "Select companies first")
    if not config.ai_enabled():
        raise HTTPException(400, "AI research needs GEMINI_API_KEY in .env")
    force = bool(payload.get("force"))
    return _start("research", f"Research {len(ids)} compan{'y' if len(ids) == 1 else 'ies'}", {"ids": ids, "force": force},
                  lambda run: pipeline.research_job(run, ids, force=force), exclusive=False)


@app.post("/api/runs/drafts")
def run_drafts(payload: dict = Body(...)):
    ids = [int(i) for i in payload.get("ids") or []]
    if not ids:
        raise HTTPException(400, "Select companies first")
    mode = payload.get("mode", "ai")
    target = payload.get("target", "ceo")
    instructions = (payload.get("instructions") or "").strip() or None
    return _start("drafts", f"Draft emails for {len(ids)} compan{'y' if len(ids) == 1 else 'ies'}", {"ids": ids, "mode": mode},
                  lambda run: agent._draft_job(run, ids, mode, target, instructions), exclusive=False)


@app.post("/api/runs/send")
def run_send():
    if not config.smtp_enabled():
        raise HTTPException(400, "Email sending needs SMTP_USER and SMTP_PASSWORD in .env")
    return _start("send", "Send approved emails", {}, lambda run: outreach.send_approved(run))


@app.post("/api/runs/replies")
def run_replies():
    return _start("replies", "Check replies", {}, lambda run: outreach.check_replies(run))


@app.get("/api/runs")
def runs(limit: int = 30):
    return db.query("SELECT id, kind, label, status, progress, total, summary, started_at, finished_at FROM runs ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int):
    row = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not row:
        raise HTTPException(404, "Run not found")
    return row


@app.post("/api/runs/{run_id}/cancel")
def run_cancel(run_id: int):
    return {"cancelled": jobs.cancel(run_id)}


# ---------------------------------------------------------------------------
# Outreach
# ---------------------------------------------------------------------------

@app.get("/api/outreach")
def outreach_list(status: str = "draft", limit: int = 300):
    statuses = status.split(",")
    rows = db.query(
        f"""SELECT o.*, c.name AS company, c.logo_url, c.batch,
                   (SELECT ct.confidence FROM contacts ct WHERE ct.company_id=o.company_id AND ct.email=o.to_email) AS confidence
            FROM outreach o JOIN companies c ON c.id=o.company_id
            WHERE o.status IN ({','.join('?' * len(statuses))}) ORDER BY o.id DESC LIMIT ?""",
        statuses + [limit])
    counts = {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM outreach GROUP BY status")}
    return {"rows": rows, "counts": counts, "sent_today": outreach.sent_today(), "daily_limit": db.get_setting("daily_send_limit", 40)}


@app.patch("/api/outreach/{oid}")
def outreach_update(oid: int, payload: dict = Body(...)):
    row = db.one("SELECT * FROM outreach WHERE id=?", (oid,))
    if not row:
        raise HTTPException(404, "Not found")
    if row["status"] in ("sent", "replied", "bounced", "sending"):
        raise HTTPException(400, "This email was already sent and can't be edited")
    sets: dict[str, Any] = {}
    if "subject" in payload:
        sets["subject"] = str(payload["subject"]).strip()
    if "body" in payload:
        sets["body"] = str(payload["body"]).rstrip()
    if "to_email" in payload:
        sets["to_email"] = str(payload["to_email"]).strip().lower()
    if payload.get("status") in ("draft", "approved", "cancelled"):
        sets["status"] = payload["status"]
        sets["approved_at"] = db.now() if payload["status"] == "approved" else None
    if sets:
        db.execute(f"UPDATE outreach SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?", (*sets.values(), oid))
    return db.one("SELECT * FROM outreach WHERE id=?", (oid,))


@app.post("/api/outreach/bulk")
def outreach_bulk(payload: dict = Body(...)):
    ids = [int(i) for i in payload.get("ids") or []]
    action = payload.get("action")
    if not ids:
        raise HTTPException(400, "Nothing selected")
    ph = ",".join("?" * len(ids))
    if action == "approve":
        db.execute(f"UPDATE outreach SET status='approved', approved_at=? WHERE id IN ({ph}) AND status='draft'", (db.now(), *ids))
    elif action == "unapprove":
        db.execute(f"UPDATE outreach SET status='draft', approved_at=NULL WHERE id IN ({ph}) AND status='approved'", ids)
    elif action == "delete":
        db.execute(f"DELETE FROM outreach WHERE id IN ({ph}) AND status IN ('draft','approved','cancelled','failed')", ids)
    elif action == "retry":
        db.execute(f"UPDATE outreach SET status='approved', error=NULL, approved_at=? WHERE id IN ({ph}) AND status='failed'", (db.now(), *ids))
    else:
        raise HTTPException(400, "Unknown action")
    return {"ok": True}


@app.post("/api/outreach/{oid}/replied")
def mark_replied(oid: int):
    row = db.one("SELECT * FROM outreach WHERE id=?", (oid,))
    if not row:
        raise HTTPException(404, "Not found")
    db.execute("UPDATE outreach SET status='replied', replied_at=? WHERE to_email=? AND status='sent'", (db.now(), row["to_email"]))
    db.execute("UPDATE outreach SET status='cancelled', error='recipient replied' WHERE to_email=? AND status IN ('draft','approved')", (row["to_email"],))
    db.execute("UPDATE companies SET stage='replied' WHERE id=? AND stage IN ('new','qualified','contacted')", (row["company_id"],))
    return {"ok": True}


@app.post("/api/outreach/followups")
def followups_now():
    return {"created": outreach.schedule_followups()}


@app.post("/api/outreach/preview")
def preview(payload: dict = Body(...)):
    cid = int(payload.get("company_id") or 0)
    company_row = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    if not company_row:
        raise HTTPException(404, "Company not found")
    rcpts = outreach.recipients(cid, payload.get("target", "ceo"))
    if not rcpts:
        raise HTTPException(400, "No usable email for this company")
    settings = db.all_settings()
    values = outreach._vars(company_row, rcpts[0])
    return {"to": rcpts[0]["email"], "subject": outreach.render(settings["template_subject"], values),
            "body": outreach.render(settings["template_body"], values)}


@app.get("/api/suppression")
def suppression_list():
    return db.query("SELECT * FROM suppression ORDER BY created_at DESC")


@app.post("/api/suppression")
def suppression_add(payload: dict = Body(...)):
    email = (payload.get("email") or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "Enter an email")
    db.suppress(email, payload.get("reason") or "manual")
    db.execute("UPDATE outreach SET status='cancelled', error='do not contact' WHERE to_email=? AND status IN ('draft','approved')", (email,))
    return {"ok": True}


@app.delete("/api/suppression/{email}")
def suppression_remove(email: str):
    db.execute("DELETE FROM suppression WHERE email=?", (email.lower(),))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Settings, tests, export, agent
# ---------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings():
    return db.all_settings()


@app.put("/api/settings")
def put_settings(payload: dict = Body(...)):
    ints = {"daily_send_limit": (1, 500), "send_delay_seconds": (5, 3600), "followup_after_days": (1, 60),
            "max_followups": (0, 5), "auto_sync_hours": (1, 720)}
    for k, (lo, hi) in ints.items():
        if k in payload:
            try:
                payload[k] = max(lo, min(hi, int(payload[k])))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} must be a number")
    db.set_settings(payload)
    if "fit_strengths" in payload or "default_proof_line" in payload:
        fit.rescore()
    return db.all_settings()


@app.post("/api/test/{what}")
def test_integration(what: str):
    if what == "smtp":
        return {"ok": True, "detail": outreach.test_smtp()}
    if what == "ai":
        return {"ok": True, "detail": ai.ping()}
    if what == "sheets":
        return {"ok": True, "detail": export.sync_google_sheet()}
    raise HTTPException(404, "Unknown test")


def _ids(ids: str) -> list[int] | None:
    out = [int(i) for i in ids.split(",") if i.strip().isdigit()]
    return out or None


@app.get("/api/export.xlsx")
def export_xlsx(ids: str = ""):
    data = export.to_xlsx(_ids(ids))
    name = f"yc-scout-{time.strftime('%Y%m%d')}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/export.csv")
def export_csv(ids: str = "", table: str = "Companies"):
    if table not in ("Companies", "Founders", "Emails", "Jobs", "Outreach"):
        raise HTTPException(400, "Unknown table")
    data = export.to_csv(_ids(ids), table)
    return Response(data, media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="yc-scout-{table.lower()}.csv"'})


@app.post("/api/sheets/sync")
def sheets_sync():
    return {"url": export.sync_google_sheet()}


@app.post("/api/agent")
def agent_chat(payload: dict = Body(...)):
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Type a request")
    return agent.chat(payload.get("session_id"), message)


@app.post("/api/agent/stream")
def agent_stream(payload: dict = Body(...)):
    """Server-sent events: one JSON event per line (thinking, text, tool steps, done)."""
    message = (payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Type a request")
    if not config.ai_enabled():
        raise HTTPException(400, "The agent needs GEMINI_API_KEY in .env")

    def events():
        answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else None
        for ev in agent.chat_stream(payload.get("session_id"), message, answer):
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/chats")
def chats_list():
    return agent.list_chats()


@app.get("/api/chats/{chat_id}")
def chats_get(chat_id: str):
    c = agent.get_chat(chat_id)
    if not c:
        raise HTTPException(404, "Chat not found")
    return c


@app.patch("/api/chats/{chat_id}")
def chats_rename(chat_id: str, payload: dict = Body(...)):
    if not agent.get_chat(chat_id):
        raise HTTPException(404, "Chat not found")
    agent.rename_chat(chat_id, str(payload.get("title") or ""))
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
def chats_delete(chat_id: str):
    agent.delete_chat(chat_id)
    return {"ok": True}


@app.delete("/api/chats")
def chats_delete_all():
    return {"deleted": agent.delete_all_chats()}


@app.get("/api/memories")
def memories_list():
    return {"enabled": bool(db.get_setting("memory_enabled", True)), "items": agent.list_memories()}


@app.post("/api/memories")
def memories_add(payload: dict = Body(...)):
    try:
        return agent.add_memory(str(payload.get("text") or ""), source="you")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/memories/{memory_id}")
def memories_delete(memory_id: int):
    agent.delete_memory(memory_id)
    return {"ok": True}


@app.delete("/api/memories")
def memories_clear():
    return {"deleted": agent.clear_memories()}


@app.put("/api/memories/enabled")
def memories_toggle(payload: dict = Body(...)):
    db.set_settings({"memory_enabled": bool(payload.get("enabled"))})
    return {"enabled": bool(db.get_setting("memory_enabled", True))}


@app.post("/api/agent/reset")
def agent_reset(payload: dict = Body(...)):
    if payload.get("session_id"):
        agent.reset(payload["session_id"])
    return {"ok": True}
