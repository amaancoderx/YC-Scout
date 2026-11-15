"""Command agent: operate the whole pipeline in plain English.

Gemini gets tools over the local database and job system. It can search,
qualify, research, draft and approve. Sending is never executed by the agent:
it returns a confirmation request the user clicks in the UI.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import date, timedelta
from typing import Iterator

from google.genai import types as T

from . import ai, config, db, jobs, outreach, pipeline
from .sources import yc

SYSTEM = """You are the operator of YC Scout, a tool that sources recently funded Y Combinator startups, finds their founders' contact details and runs email outreach. Today is {today}.

You act through tools on the user's local database. Work like a sharp sales-ops lead:
- You can see the whole dashboard: the snapshot below for the big picture, and tools for everything else
  (companies, jobs, people, emails and drafts, pipeline jobs and logs, settings, analytics, memory).
- Use search_companies to find targets; combine filters rather than guessing ids.
- When the user asks for outreach, draft first (draft_emails), then summarize what was drafted. Drafts can be reviewed on the Outreach page.
- Approve drafts only when the user explicitly asks you to approve or send them.
- To send, call request_send. It does not send: it asks the user to confirm in the UI. Never claim emails were sent.
- Starting a sync or research job runs in the background; report the job and where to watch it (Pipeline page).
- Never re-collect what the dashboard already has. Before start_sync, call stats: if the batches are already loaded, answer from the database instead of syncing (a sync only refreshes jobs, and skips companies refreshed in the last 2 days). Before research_companies, prefer search_companies with researched=false; already-researched companies are skipped automatically. Use force only when the user explicitly asks to refresh or redo.
- Write like a sharp, friendly colleague. Lead with the answer. Use markdown: short paragraphs, **bold** for key names, bullet lists, and tables (company | why | contact) for results. Mention company names, never ids.
- Never invent data. Everything about companies comes from tools: only mention companies a tool returned in this conversation. Planning a search in your thoughts is not running it; call the tool, then answer. No emojis, no em dashes. Keep headings rare; prefer a short intro line, then the table or list, then one suggested next step.
- Email confidence: verified (published), inferred (company's own format), likely (first@domain), guess.
- Every company has a fit score (0-100) against the user's profile with reasons. When the user asks for the best targets, "companies that fit me", or doesn't specify an order, sort by fit and mention the reasons.
- When drafting, pass the user's intent as `instructions` (e.g. which role to ask about, internship vs full-time vs contract).

The user (the sender of all outreach):
{profile}

What they want from outreach: {goal}

Live dashboard snapshot (refreshed every message; use it directly for overview questions,
and call tools for details, lists, or anything not shown here):
{snapshot}

{memory}"""

TOOLS = [
    {
        "name": "search_companies",
        "description": "Search companies in the local database. All filters optional. Returns up to `limit` rows with best contact email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Free text matched against name, one-liner, description and tags."},
                "batches": {"type": "array", "items": {"type": "string"}, "description": "Batch names like 'Fall 2026' or slugs like 'fall-2026'."},
                "industry": {"type": "string"},
                "hiring_only": {"type": "boolean"},
                "remote_jobs_only": {"type": "boolean", "description": "Only companies with at least one open remote role."},
                "has_phone": {"type": "boolean", "description": "Only companies that publish a phone or WhatsApp number."},
                "researched": {"type": "boolean", "description": "true = only AI-researched companies, false = only not yet researched."},
                "stage": {"type": "string", "enum": ["new", "qualified", "contacted", "replied", "meeting", "won", "lost", "skip"]},
                "min_email_confidence": {"type": "string", "enum": ["verified", "inferred", "likely", "guess"]},
                "max_team_size": {"type": "integer"},
                "not_contacted": {"type": "boolean", "description": "Exclude companies that already have outreach."},
                "min_fit": {"type": "integer", "description": "Minimum fit score 0-100 against the user's profile."},
                "sort": {"type": "string", "enum": ["fit", "newest", "name", "roles"], "description": "Default: fit."},
                "limit": {"type": "integer", "description": "Default 25, max 200."},
            },
        },
    },
    {
        "name": "get_company",
        "description": "Full profile of one company: founders, emails with confidence, jobs, funding, research notes, outreach history.",
        "input_schema": {"type": "object", "properties": {"company_id": {"type": "integer"}}, "required": ["company_id"]},
    },
    {
        "name": "update_companies",
        "description": "Set pipeline stage and/or priority, or append a note, on one or more companies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_ids": {"type": "array", "items": {"type": "integer"}},
                "stage": {"type": "string", "enum": ["new", "qualified", "contacted", "replied", "meeting", "won", "lost", "skip"]},
                "priority": {"type": "integer", "description": "0 normal, 1 high, 2 top"},
                "note": {"type": "string"},
            },
            "required": ["company_ids"],
        },
    },
    {
        "name": "draft_emails",
        "description": "Create first-touch email drafts (background job). target: 'ceo' (one founder per company), 'founders' (every founder), 'inbox' (company inbox).",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_ids": {"type": "array", "items": {"type": "integer"}},
                "target": {"type": "string", "enum": ["ceo", "founders", "inbox"]},
                "instructions": {"type": "string", "description": "Extra guidance for these emails, e.g. angle or offer."},
                "use_template": {"type": "boolean", "description": "Use the saved template instead of AI writing."},
            },
            "required": ["company_ids"],
        },
    },
    {
        "name": "list_outreach",
        "description": "List outreach emails by status.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["draft", "approved", "sent", "replied", "bounced", "failed", "cancelled"]},
                           "limit": {"type": "integer"}},
        },
    },
    {
        "name": "approve_drafts",
        "description": "Approve drafts so they enter the send queue. Only when the user explicitly asked.",
        "input_schema": {"type": "object", "properties": {"outreach_ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["outreach_ids"]},
    },
    {
        "name": "request_send",
        "description": "Ask the user to confirm sending all approved emails. Does not send by itself.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "start_sync",
        "description": "Fetch/refresh companies from YC batches (background job): YC page, founders, jobs, website crawl, emails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "batches": {"type": "array", "items": {"type": "string"}, "description": "Batch slugs, e.g. ['fall-2026']. Empty = 2 most recent."},
                "research": {"type": "boolean", "description": "Also run AI deep research (funding, verified emails). Costs API credits."},
                "force": {"type": "boolean", "description": "Re-sync even if the batches were synced recently. Only when the user explicitly asks to refresh."},
            },
        },
    },
    {
        "name": "research_companies",
        "description": "Run AI deep web research on specific companies (funding rounds, published emails, highlights). Background job.",
        "input_schema": {"type": "object", "properties": {
            "company_ids": {"type": "array", "items": {"type": "integer"}},
            "force": {"type": "boolean", "description": "Re-research companies already researched. Only when the user explicitly asks to refresh."}},
            "required": ["company_ids"]},
    },
    {
        "name": "stats",
        "description": "Database and pipeline statistics, available batches and how many of each are loaded.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_sessions: dict[str, list] = {}
_sessions_lock = threading.Lock()
MAX_STEPS = 14


def _batch_filter(batches: list[str]) -> tuple[str, list]:
    names = []
    for b in batches:
        b = b.strip()
        if "-" in b and b.split("-")[0].lower() in ("winter", "spring", "summer", "fall"):
            names.append(b.lower())
        else:
            names.append(b.lower().replace(" ", "-"))
    return f"c.batch_slug IN ({','.join('?' * len(names))})", names


def search_companies(args: dict) -> list[dict]:
    where, params = ["1=1"], []
    if args.get("text"):
        t = f"%{args['text'].lower()}%"
        where.append("(lower(c.name) LIKE ? OR lower(c.one_liner) LIKE ? OR lower(c.description) LIKE ? OR lower(c.tags) LIKE ? OR lower(c.industry) LIKE ?)")
        params += [t] * 5
    if args.get("batches"):
        clause, p = _batch_filter(args["batches"])
        where.append(clause)
        params += p
    if args.get("industry"):
        where.append("(lower(c.industry) LIKE ? OR lower(c.subindustry) LIKE ? OR lower(c.tags) LIKE ?)")
        params += [f"%{args['industry'].lower()}%"] * 3
    if args.get("hiring_only"):
        where.append("(c.is_hiring=1 OR EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1))")
    if args.get("remote_jobs_only"):
        where.append("EXISTS (SELECT 1 FROM jobs j WHERE j.company_id=c.id AND j.active=1 AND lower(COALESCE(j.location,'')) LIKE '%remote%')")
    if args.get("researched") is True:
        where.append("c.researched_at IS NOT NULL")
    elif args.get("researched") is False:
        where.append("c.researched_at IS NULL")
    if args.get("has_phone"):
        where.append("(COALESCE(c.phones,'[]') NOT IN ('','[]') OR COALESCE(c.whatsapp,'[]') NOT IN ('','[]'))")
    if args.get("stage"):
        where.append("c.stage=?")
        params.append(args["stage"])
    if args.get("max_team_size"):
        where.append("c.team_size<=?")
        params.append(int(args["max_team_size"]))
    if args.get("not_contacted"):
        where.append("NOT EXISTS (SELECT 1 FROM outreach o WHERE o.company_id=c.id AND o.status!='cancelled')")
    if args.get("min_email_confidence"):
        levels = ["verified", "inferred", "likely", "guess"]
        allowed = levels[: levels.index(args["min_email_confidence"]) + 1]
        where.append(f"EXISTS (SELECT 1 FROM contacts ct WHERE ct.company_id=c.id AND ct.confidence IN ({','.join('?' * len(allowed))}))")
        params += allowed
    if args.get("min_fit") is not None:
        where.append("COALESCE(c.fit_score,0)>=?")
        params.append(int(args["min_fit"]))
    order = {"fit": "COALESCE(c.fit_score,0) DESC", "newest": "c.batch_slug DESC", "name": "c.name",
             "roles": "open_roles DESC"}.get(args.get("sort") or "fit", "COALESCE(c.fit_score,0) DESC")
    limit = max(1, min(int(args.get("limit") or 25), 200))
    rows = db.query(
        f"""SELECT c.id, c.name, c.batch, c.one_liner, c.industry, c.team_size, c.stage, c.funding_total,
               c.fit_score, c.fit_reasons, c.phones, c.whatsapp, c.researched_at, c.scraped_at AS last_synced,
               (SELECT COUNT(*) FROM jobs j WHERE j.company_id=c.id AND j.active=1) AS open_roles,
               (SELECT GROUP_CONCAT(j.title || ' [' || COALESCE(j.location,'') || ']', '; ') FROM jobs j WHERE j.company_id=c.id AND j.active=1) AS roles,
               (SELECT ct.email || ' (' || ct.confidence || ')' FROM contacts ct WHERE ct.company_id=c.id AND ct.is_primary=1
                ORDER BY CASE ct.confidence WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 WHEN 'likely' THEN 2 ELSE 3 END LIMIT 1) AS best_email
            FROM companies c WHERE {' AND '.join(where)} ORDER BY c.priority DESC, {order}, c.name LIMIT ?""",
        params + [limit],
    )
    for r in rows:
        r["fit_reasons"] = db.loads(r.get("fit_reasons"), [])
        r["phones"] = [p.get("number") for p in db.loads(r.get("phones"), []) if p.get("number")]
        r["whatsapp"] = [w.get("number") or w.get("link") for w in db.loads(r.get("whatsapp"), [])]
    return rows


def company_detail(cid: int) -> dict | None:
    c = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    if not c:
        return None
    for key, default in (("tags", []), ("phones", []), ("whatsapp", []), ("other_links", {}), ("funding_rounds", []), ("research_sources", [])):
        c[key] = db.loads(c.get(key), default)
    c["founders"] = db.query("SELECT * FROM founders WHERE company_id=? ORDER BY is_active DESC, id", (cid,))
    c["contacts"] = db.query(
        """SELECT * FROM contacts WHERE company_id=? ORDER BY
           CASE confidence WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 WHEN 'likely' THEN 2 ELSE 3 END, is_primary DESC""", (cid,))
    c["jobs"] = db.query("SELECT * FROM jobs WHERE company_id=? AND active=1 ORDER BY id", (cid,))
    c["news"] = db.query("SELECT * FROM news WHERE company_id=? ORDER BY id DESC LIMIT 12", (cid,))
    c["outreach"] = db.query("SELECT * FROM outreach WHERE company_id=? ORDER BY id DESC", (cid,))
    return c


def stats() -> dict:
    rows = db.query("SELECT batch_slug, COUNT(*) n, MAX(scraped_at) last_synced, "
                    "SUM(researched_at IS NOT NULL) researched FROM companies GROUP BY batch_slug")
    loaded = {r["batch_slug"]: r for r in rows}
    def info(slug):
        r = loaded.get(slug) or {}
        return {"loaded": r.get("n", 0), "last_synced": r.get("last_synced"), "researched": r.get("researched", 0)}
    try:
        available = [{"slug": b.slug, "name": b.name, "companies": b.count, **info(b.slug)} for b in yc.list_batches()[:8]]
    except Exception:
        available = [{"slug": k, **info(k)} for k in loaded]
    return {
        "companies": db.scalar("SELECT COUNT(*) FROM companies"),
        "founders": db.scalar("SELECT COUNT(*) FROM founders WHERE is_active=1"),
        "emails_by_confidence": {r["confidence"]: r["n"] for r in db.query("SELECT confidence, COUNT(*) n FROM contacts GROUP BY confidence")},
        "open_roles": db.scalar("SELECT COUNT(*) FROM jobs WHERE active=1"),
        "researched": db.scalar("SELECT COUNT(*) FROM companies WHERE researched_at IS NOT NULL"),
        "not_researched": db.scalar("SELECT COUNT(*) FROM companies WHERE researched_at IS NULL"),
        "stages": {r["stage"]: r["n"] for r in db.query("SELECT stage, COUNT(*) n FROM companies GROUP BY stage")},
        "outreach": {r["status"]: r["n"] for r in db.query("SELECT status, COUNT(*) n FROM outreach GROUP BY status")},
        "batches": available,
    }


# ---------------------------------------------------------------------------
# Whole-dashboard awareness: a live snapshot in every turn + tools for the rest
# ---------------------------------------------------------------------------
def dashboard_snapshot() -> str:
    """Compact, always-fresh overview injected into the system prompt each turn."""
    q, s = db.query, db.scalar
    batches = q("SELECT batch, batch_slug, COUNT(*) n, MAX(scraped_at) synced, SUM(researched_at IS NOT NULL) r "
                "FROM companies GROUP BY batch_slug ORDER BY batch_slug DESC")
    conf = {r["confidence"]: r["n"] for r in q("SELECT confidence, COUNT(*) n FROM contacts GROUP BY confidence")}
    stages = {r["stage"]: r["n"] for r in q("SELECT stage, COUNT(*) n FROM companies GROUP BY stage")}
    out = {r["status"]: r["n"] for r in q("SELECT status, COUNT(*) n FROM outreach GROUP BY status")}
    top = q("SELECT name, fit_score FROM companies WHERE fit_score IS NOT NULL ORDER BY fit_score DESC, name LIMIT 8")
    running = q("SELECT id, kind, label, progress, total FROM runs WHERE status='running' ORDER BY id DESC")
    last = db.one("SELECT id, kind, label, status, summary, finished_at FROM runs WHERE status!='running' ORDER BY id DESC LIMIT 1")
    st = db.all_settings()
    verified_cos = s("SELECT COUNT(DISTINCT company_id) FROM contacts WHERE confidence IN ('verified','inferred')")
    remote_roles = s("SELECT COUNT(*) FROM jobs WHERE active=1 AND lower(COALESCE(location,'')) LIKE '%remote%'")
    with_phone = s("SELECT COUNT(*) FROM companies WHERE COALESCE(phones,'[]') NOT IN ('','[]') OR COALESCE(whatsapp,'[]') NOT IN ('','[]')")
    lines = [
        f"Companies: {s('SELECT COUNT(*) FROM companies')} | founders: {s('SELECT COUNT(*) FROM founders WHERE is_active=1')}"
        f" | AI-researched: {s('SELECT COUNT(*) FROM companies WHERE researched_at IS NOT NULL')}",
        "Batches loaded: " + ("; ".join(f"{b['batch']} ({b['batch_slug']}) {b['n']} companies, synced {b['synced'] or 'never'}, {b['r']} researched" for b in batches) or "none"),
        f"Emails: {sum(conf.values())} total ({', '.join(f'{k} {v}' for k, v in conf.items())}); "
        f"companies with a verified/inferred contact: {verified_cos}",
        f"Hiring: {s('SELECT COUNT(DISTINCT company_id) FROM jobs WHERE active=1')} companies, {s('SELECT COUNT(*) FROM jobs WHERE active=1')} open roles "
        f"({remote_roles} remote)",
        f"Published phone/WhatsApp: {with_phone} companies",
        "Top fits: " + (", ".join(f"{t['name']} {t['fit_score']}" for t in top) or "none scored"),
        "Stages: " + (", ".join(f"{k} {v}" for k, v in stages.items()) or "none"),
        "Outreach: " + (", ".join(f"{k} {v}" for k, v in out.items()) or "nothing drafted yet")
        + f" | sent today {outreach.sent_today()} of {st.get('daily_send_limit')} daily limit",
        "Running jobs: " + (", ".join(f"#{r['id']} {r['label']} {r['progress']}/{r['total']}" for r in running) or "none")
        + (f" | last finished: #{last['id']} {last['label']} ({last['status']}): {last['summary'] or ''}" if last else ""),
        f"Integrations: AI {ai.model_label() if config.ai_enabled() else 'off'}; email sending {'on (' + (config.FROM_EMAIL or '') + ')' if config.smtp_enabled() else 'off'}; "
        f"reply tracking {'on' if config.imap_enabled() else 'off'}; Google Sheets {'on' if config.sheets_enabled() else 'off'}",
        f"Rules: {st.get('send_delay_seconds')}s between emails, follow-up after {st.get('followup_after_days')} days, max {st.get('max_followups')} follow-ups, "
        f"auto follow-ups {'on' if st.get('auto_followups') else 'off'}, auto-sync {'every ' + str(st.get('auto_sync_hours')) + 'h' if st.get('auto_sync_enabled') else 'off'}",
    ]
    return "\n".join(lines)


EXTRA_TOOLS = [
    {
        "name": "search_jobs",
        "description": "Search open job postings across all companies (title, location, salary, equity, visa, link, company fit).",
        "input_schema": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Matched against job title and company name, e.g. 'ML engineer'."},
            "remote_only": {"type": "boolean"},
            "role": {"type": "string", "description": "YC role category, e.g. Engineering, Sales, Operations, Product, Science."},
            "batches": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer"}}},
    },
    {
        "name": "search_people",
        "description": "Find founders by name, title or email, with their company, title, best email (confidence) and LinkedIn.",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["text"]},
    },
    {
        "name": "get_outreach",
        "description": "Read one email in full (to, subject, body, status, dates, error) by outreach id.",
        "input_schema": {"type": "object", "properties": {"outreach_id": {"type": "integer"}}, "required": ["outreach_id"]},
    },
    {
        "name": "update_draft",
        "description": "Edit the subject and/or body of a draft email (only status draft). Use when the user asks to rewrite or tweak a draft.",
        "input_schema": {"type": "object", "properties": {"outreach_id": {"type": "integer"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["outreach_id"]},
    },
    {
        "name": "cancel_drafts",
        "description": "Cancel draft or approved (not yet sent) emails by id.",
        "input_schema": {"type": "object", "properties": {"outreach_ids": {"type": "array", "items": {"type": "integer"}}}, "required": ["outreach_ids"]},
    },
    {
        "name": "list_runs",
        "description": "Recent pipeline jobs (sync, research, drafts, send, replies) with status, progress, summary and the last log lines. Use to answer 'is the sync done?' or 'what failed?'.",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}, "run_id": {"type": "integer"}}},
    },
    {
        "name": "get_settings",
        "description": "The user's settings: email templates, follow-up template, sending limits, footer, strengths used for fit scoring, automation switches. No secrets.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "analytics",
        "description": "Breakdowns for charts and comparisons: companies by industry, by batch, by team size, open roles by category, fit score distribution, email confidence by batch, outreach funnel.",
        "input_schema": {"type": "object", "properties": {}},
    },
]
TOOLS.extend(EXTRA_TOOLS)


def _search_jobs(args: dict) -> list[dict]:
    where, params = ["j.active=1"], []
    if args.get("text"):
        t = f"%{args['text'].lower()}%"
        where.append("(lower(j.title) LIKE ? OR lower(c.name) LIKE ?)")
        params += [t, t]
    if args.get("remote_only"):
        where.append("lower(COALESCE(j.location,'')) LIKE '%remote%'")
    if args.get("role"):
        where.append("lower(COALESCE(j.role,''))=?")
        params.append(args["role"].lower())
    if args.get("batches"):
        clause, p = _batch_filter(args["batches"])
        where.append(clause)
        params += p
    limit = max(1, min(int(args.get("limit") or 40), 200))
    return db.query(
        f"""SELECT c.name AS company, c.id AS company_id, c.batch, c.fit_score, j.title, j.role, j.location, j.type,
                   j.salary, j.equity, j.experience, j.visa, j.posted, j.url
            FROM jobs j JOIN companies c ON c.id=j.company_id WHERE {' AND '.join(where)}
            ORDER BY COALESCE(c.fit_score,0) DESC, c.name LIMIT ?""", params + [limit])


def _search_people(args: dict) -> list[dict]:
    t = f"%{(args.get('text') or '').lower()}%"
    limit = max(1, min(int(args.get("limit") or 20), 100))
    rows = db.query(
        """SELECT f.id AS founder_id, f.name, f.title, f.linkedin_url, f.twitter_url, c.name AS company, c.id AS company_id, c.batch
           FROM founders f JOIN companies c ON c.id=f.company_id
           WHERE f.is_active=1 AND (lower(f.name) LIKE ? OR lower(COALESCE(f.title,'')) LIKE ?
                 OR EXISTS (SELECT 1 FROM contacts ct WHERE ct.founder_id=f.id AND lower(ct.email) LIKE ?))
           ORDER BY c.fit_score DESC LIMIT ?""", (t, t, t, limit))
    for r in rows:
        best = db.one("""SELECT email, confidence FROM contacts WHERE founder_id=? ORDER BY
                         CASE confidence WHEN 'verified' THEN 0 WHEN 'inferred' THEN 1 WHEN 'likely' THEN 2 ELSE 3 END LIMIT 1""",
                      (r["founder_id"],))
        r["best_email"] = f"{best['email']} ({best['confidence']})" if best else None
    return rows


def _list_runs(args: dict) -> list[dict] | dict:
    if args.get("run_id"):
        r = db.one("SELECT * FROM runs WHERE id=?", (int(args["run_id"]),))
        if not r:
            return {"error": "job not found"}
        r["log"] = "\n".join((r.get("log") or "").splitlines()[-40:])
        return r
    limit = max(1, min(int(args.get("limit") or 8), 50))
    rows = db.query("SELECT id, kind, label, status, progress, total, summary, started_at, finished_at, log FROM runs ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["log_tail"] = "\n".join((r.pop("log") or "").splitlines()[-6:])
    return rows


SAFE_SETTINGS = ("sender_profile", "outreach_goal", "email_tone", "template_subject", "template_body", "followup_subject",
                 "followup_body", "signature_footer", "physical_address", "daily_send_limit", "send_delay_seconds",
                 "followup_after_days", "max_followups", "auto_followups", "auto_sync_enabled", "auto_sync_hours",
                 "auto_sync_batches", "auto_research_new", "auto_sheet_sync", "fit_strengths", "default_proof_line", "memory_enabled")


def _analytics() -> dict:
    q = db.query
    return {
        "companies_by_industry": q("SELECT COALESCE(industry,'Unknown') industry, COUNT(*) n FROM companies GROUP BY 1 ORDER BY n DESC"),
        "companies_by_batch": q("SELECT batch, COUNT(*) n, SUM(researched_at IS NOT NULL) researched FROM companies GROUP BY batch ORDER BY batch_slug DESC"),
        "team_size": q("""SELECT CASE WHEN team_size IS NULL THEN 'unknown' WHEN team_size<=2 THEN '1-2' WHEN team_size<=5 THEN '3-5'
                          WHEN team_size<=10 THEN '6-10' WHEN team_size<=50 THEN '11-50' ELSE '50+' END bucket, COUNT(*) n
                          FROM companies GROUP BY 1 ORDER BY MIN(COALESCE(team_size,9999))"""),
        "open_roles_by_category": q("SELECT COALESCE(role,'Other') role, COUNT(*) n, SUM(lower(COALESCE(location,'')) LIKE '%remote%') remote FROM jobs WHERE active=1 GROUP BY 1 ORDER BY n DESC"),
        "fit_distribution": q("""SELECT CASE WHEN fit_score>=60 THEN 'strong 60+' WHEN fit_score>=35 THEN 'medium 35-59' ELSE 'weak <35' END band,
                                 COUNT(*) n FROM companies GROUP BY 1"""),
        "email_confidence_by_batch": q("""SELECT c.batch, ct.confidence, COUNT(*) n FROM contacts ct JOIN companies c ON c.id=ct.company_id
                                          GROUP BY c.batch, ct.confidence ORDER BY c.batch"""),
        "outreach_funnel": q("SELECT step, status, COUNT(*) n FROM outreach GROUP BY step, status ORDER BY step"),
    }


def _extra_tool(name: str, args: dict, ctx: dict):
    if name == "search_jobs":
        return _search_jobs(args)
    if name == "search_people":
        return _search_people(args)
    if name == "get_outreach":
        r = db.one("""SELECT o.*, c.name AS company FROM outreach o JOIN companies c ON c.id=o.company_id WHERE o.id=?""",
                   (int(args["outreach_id"]),))
        return r or {"error": "email not found"}
    if name == "update_draft":
        oid = int(args["outreach_id"])
        row = db.one("SELECT status FROM outreach WHERE id=?", (oid,))
        if not row:
            return {"error": "email not found"}
        if row["status"] != "draft":
            return {"error": f"only drafts can be edited (this one is {row['status']})"}
        if args.get("subject"):
            db.execute("UPDATE outreach SET subject=? WHERE id=?", (args["subject"].strip(), oid))
        if args.get("body"):
            db.execute("UPDATE outreach SET body=? WHERE id=?", (outreach._tidy_body(args["body"]), oid))
        ctx["changed"] = True
        return {"updated": True, "outreach_id": oid}
    if name == "cancel_drafts":
        n = 0
        for oid in [int(i) for i in args.get("outreach_ids") or []]:
            n += 1 if db.one("SELECT 1 FROM outreach WHERE id=? AND status IN ('draft','approved')", (oid,)) else 0
            db.execute("UPDATE outreach SET status='cancelled' WHERE id=? AND status IN ('draft','approved')", (oid,))
        ctx["changed"] = True
        return {"cancelled": n}
    if name == "list_runs":
        return _list_runs(args)
    if name == "get_settings":
        st = db.all_settings()
        return {k: st.get(k) for k in SAFE_SETTINGS}
    if name == "analytics":
        return _analytics()
    return None


def _run_tool(name: str, args: dict, ctx: dict) -> object:
    extra = _extra_tool(name, args, ctx)
    if extra is not None:
        return extra
    if name == "search_companies":
        return search_companies(args)
    if name == "get_company":
        d = company_detail(int(args["company_id"]))
        if not d:
            return {"error": "not found"}
        for f in d["founders"]:
            f.pop("avatar_url", None)
        d["description"] = (d.get("description") or "")[:1500]
        return d
    if name == "update_companies":
        ids = [int(i) for i in args.get("company_ids") or []]
        for cid in ids:
            if args.get("stage"):
                db.execute("UPDATE companies SET stage=? WHERE id=?", (args["stage"], cid))
            if args.get("priority") is not None:
                db.execute("UPDATE companies SET priority=? WHERE id=?", (int(args["priority"]), cid))
            if args.get("note"):
                db.execute("UPDATE companies SET notes=TRIM(COALESCE(notes,'') || char(10) || ?) WHERE id=?", (args["note"], cid))
        ctx["changed"] = True
        return {"updated": len(ids)}
    if name == "draft_emails":
        ids = [int(i) for i in args.get("company_ids") or []]
        mode = "template" if args.get("use_template") else "ai"
        target = args.get("target") or "ceo"
        run_id = jobs.start("drafts", f"Draft emails for {len(ids)} companies", {"ids": ids, "target": target},
                            lambda run: _draft_job(run, ids, mode, target, args.get("instructions")), exclusive=False)
        ctx["runs"].append(run_id)
        return {"job_id": run_id, "status": "started", "companies": len(ids), "mode": mode if config.ai_enabled() else "template"}
    if name == "list_outreach":
        status = args.get("status")
        limit = max(1, min(int(args.get("limit") or 30), 200))
        sql = "SELECT o.id, c.name AS company, o.to_email, o.step, o.status, o.subject, o.sent_at FROM outreach o JOIN companies c ON c.id=o.company_id"
        rows = db.query(sql + (" WHERE o.status=?" if status else "") + " ORDER BY o.id DESC LIMIT ?", ([status] if status else []) + [limit])
        return rows
    if name == "approve_drafts":
        ids = [int(i) for i in args.get("outreach_ids") or []]
        ts = db.now()
        n = 0
        for oid in ids:
            row = db.one("SELECT status FROM outreach WHERE id=?", (oid,))
            if row and row["status"] == "draft":
                db.execute("UPDATE outreach SET status='approved', approved_at=? WHERE id=?", (ts, oid))
                n += 1
        ctx["changed"] = True
        return {"approved": n}
    if name == "request_send":
        n = db.scalar("SELECT COUNT(*) FROM outreach WHERE status='approved'") or 0
        ctx["confirm"] = {"action": "send", "count": n}
        return {"pending_user_confirmation": True, "approved_in_queue": n,
                "daily_limit": db.get_setting("daily_send_limit"), "sent_today": outreach.sent_today()}
    if name == "start_sync":
        slugs = args.get("batches") or [b.slug for b in yc.recent_batches(2)]
        slugs = [s.lower().replace(" ", "-") for s in slugs]
        research = bool(args.get("research"))
        if not args.get("force") and not research:
            # Don't re-collect: batches synced in the last 12 hours are already in the dashboard.
            fresh = []
            for s in slugs:
                last = db.scalar("SELECT MIN(scraped_at) FROM companies WHERE batch_slug=?", (s,))
                if last and not pipeline._older_than(last, timedelta(hours=12)):
                    fresh.append({"batch": s, "companies": db.scalar("SELECT COUNT(*) FROM companies WHERE batch_slug=?", (s,)),
                                  "last_synced": last})
            if len(fresh) == len(slugs):
                return {"status": "skipped", "reason": "Already up to date: these batches were synced in the last 12 hours, "
                        "so their companies, founders, jobs and emails are already in the dashboard. Answer from the database. "
                        "Only pass force=true if the user explicitly asks to refresh anyway.", "batches": fresh}
        run_id = jobs.start("sync", f"Sync {', '.join(slugs)}", {"batches": slugs, "research": research},
                            lambda run: pipeline.sync_batches(run, slugs, research=research, force=bool(args.get("force"))))
        ctx["runs"].append(run_id)
        return {"job_id": run_id, "status": "started", "batches": slugs}
    if name == "research_companies":
        ids = [int(i) for i in args.get("company_ids") or []]
        force = bool(args.get("force"))
        already = {r["id"] for r in db.query(
            f"SELECT id FROM companies WHERE researched_at IS NOT NULL AND id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
        todo = ids if force else [i for i in ids if i not in already]
        if not todo:
            return {"status": "skipped", "reason": "All of these companies are already researched; their data is in the dashboard.",
                    "already_researched": len(already)}
        run_id = jobs.start("research", f"Research {len(todo)} companies", {"ids": todo, "force": force},
                            lambda run: pipeline.research_job(run, todo, force=force), exclusive=False)
        ctx["runs"].append(run_id)
        return {"job_id": run_id, "status": "started", "researching": len(todo),
                "skipped_already_researched": 0 if force else len(already)}
    if name == "stats":
        return stats()
    if name == "remember":
        res = add_memory(args.get("fact") or "", source="agent", chat_id=ctx.get("chat_id"))
        ctx["memory_changed"] = True
        return res
    if name == "forget":
        ok = delete_memory(int(args.get("memory_id") or 0))
        ctx["memory_changed"] = True
        return {"deleted": ok}
    return {"error": f"unknown tool {name}"}


def _draft_job(run, ids, mode, target, instructions):
    res = outreach.create_drafts(ids, mode=mode, target=target, instructions=instructions, run=run)
    return f"{res['drafted']} drafts created, {res['skipped']} skipped (already contacted / opted out), {res['failed']} failed"


# ---------------------------------------------------------------------------
# Conversation loop (Gemini, streamed)
# ---------------------------------------------------------------------------

NUDGE = ("(System note: your last turn produced no visible answer and no tool call. Thinking is not doing. "
         "Call the tools you need now to get real data, then write the answer for the user. "
         "Only mention companies that a tool returned in this conversation.)")

TOOL_LABELS = {
    "search_companies": "Searching companies",
    "get_company": "Reading company profile",
    "update_companies": "Updating companies",
    "draft_emails": "Drafting emails",
    "list_outreach": "Checking outreach",
    "approve_drafts": "Approving drafts",
    "request_send": "Preparing to send",
    "start_sync": "Starting a sync",
    "research_companies": "Starting AI research",
    "stats": "Reading database stats",
    "remember": "Saving to memory",
    "search_jobs": "Searching jobs",
    "search_people": "Searching people",
    "get_outreach": "Reading email",
    "update_draft": "Editing draft",
    "cancel_drafts": "Cancelling emails",
    "list_runs": "Checking pipeline jobs",
    "get_settings": "Reading settings",
    "analytics": "Crunching numbers",
    "forget": "Updating memory",
}


MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": "Save one durable fact or preference about the user for future chats (goals, preferences, constraints, companies to avoid). Not for one-off requests or secrets.",
        "input_schema": {"type": "object", "properties": {"fact": {"type": "string", "description": "One short sentence in third person, e.g. 'Prefers remote roles open to India.'"}}, "required": ["fact"]},
    },
    {
        "name": "forget",
        "description": "Delete a saved memory by its id when the user asks to forget it or it is no longer true.",
        "input_schema": {"type": "object", "properties": {"memory_id": {"type": "integer"}}, "required": ["memory_id"]},
    },
]


def _declarations(memory_on: bool = True) -> list[T.Tool]:
    return [T.Tool(function_declarations=[
        T.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"])
        for t in TOOLS + (MEMORY_TOOLS if memory_on else [])
    ])]


def _tool_summary(name: str, out: object) -> str:
    if isinstance(out, dict) and out.get("error"):
        return str(out["error"])
    if name == "search_companies" and isinstance(out, list):
        return f"{len(out)} compan{'y' if len(out) == 1 else 'ies'}"
    if name == "get_company" and isinstance(out, dict):
        return out.get("name") or ""
    if name == "list_outreach" and isinstance(out, list):
        return f"{len(out)} email{'s' if len(out) != 1 else ''}"
    if name == "update_companies" and isinstance(out, dict):
        return f"{out.get('updated', 0)} updated"
    if name == "approve_drafts" and isinstance(out, dict):
        return f"{out.get('approved', 0)} approved"
    if name == "request_send" and isinstance(out, dict):
        return f"{out.get('approved_in_queue', 0)} ready to send"
    if name in ("search_jobs", "search_people", "list_runs") and isinstance(out, list):
        unit = {"search_jobs": "job", "search_people": "person", "list_runs": "job run"}[name]
        return f"{len(out)} {unit}{'' if len(out) == 1 else ('people' if unit == 'person' else 's')}".replace("personpeople", "people")
    if name == "get_outreach" and isinstance(out, dict):
        return f"{out.get('company', '')} ({out.get('status', '')})"
    if name == "update_draft":
        return "draft updated"
    if name == "cancel_drafts" and isinstance(out, dict):
        return f"{out.get('cancelled', 0)} cancelled"
    if name == "remember" and isinstance(out, dict):
        return "already remembered" if out.get("duplicate") else "saved"
    if name == "forget" and isinstance(out, dict):
        return "forgotten" if out.get("deleted") else "not found"
    if isinstance(out, dict) and out.get("status") == "skipped":
        return "already up to date" if name == "start_sync" else "already researched"
    if name == "research_companies" and isinstance(out, dict) and out.get("skipped_already_researched"):
        return f"job started, {out['skipped_already_researched']} already researched skipped"
    if name in ("draft_emails", "start_sync", "research_companies") and isinstance(out, dict):
        return "job started"
    return "done"


def _plain(obj):
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Saved chats and memory
# ---------------------------------------------------------------------------
HISTORY_KEEP = 80  # Gemini turns kept per chat (older turns are trimmed, the transcript stays)


def _title_from(message: str) -> str:
    t = " ".join(message.split())
    if len(t) <= 60:
        return t
    cut = t[:60].rsplit(" ", 1)[0]
    return (cut or t[:60]) + "…"


def list_chats(limit: int = 200) -> list[dict]:
    return db.query("SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,))


def get_chat(chat_id: str) -> dict | None:
    row = db.one("SELECT id, title, messages, created_at, updated_at FROM chats WHERE id=?", (chat_id,))
    if not row:
        return None
    row["messages"] = db.loads(row["messages"], [])
    return row


def rename_chat(chat_id: str, title: str) -> None:
    db.execute("UPDATE chats SET title=? WHERE id=?", (title.strip()[:120] or "Untitled chat", chat_id))


def delete_chat(chat_id: str) -> None:
    db.execute("DELETE FROM chats WHERE id=?", (chat_id,))
    reset(chat_id)


def delete_all_chats() -> int:
    n = db.scalar("SELECT COUNT(*) FROM chats") or 0
    db.execute("DELETE FROM chats")
    with _sessions_lock:
        _sessions.clear()
    return n


def _load(chat_id: str) -> tuple[list[T.Content], list[dict], str | None, bool]:
    """(gemini history, ui transcript, title, exists)"""
    row = db.one("SELECT title, history, messages FROM chats WHERE id=?", (chat_id,))
    if not row:
        return [], [], None, False
    with _sessions_lock:
        cached = _sessions.get(chat_id)
    if cached is not None:
        history = cached
    else:
        history = []
        for c in db.loads(row["history"], []):
            try:
                history.append(T.Content.model_validate(c))
            except Exception:
                continue
    return history, db.loads(row["messages"], []), row["title"], True


def _trim(history: list[T.Content]) -> list[T.Content]:
    """Keep the last HISTORY_KEEP turns, starting at a real user message so calls and results stay paired."""
    if len(history) <= HISTORY_KEEP:
        return history
    for i in range(len(history) - HISTORY_KEEP, len(history)):
        c = history[i]
        if c.role == "user" and any(p.text and not p.function_response for p in (c.parts or [])):
            return history[i:]
    return history[-HISTORY_KEEP:]


def _save(chat_id: str, title: str, history: list[T.Content], messages: list[dict], created: bool) -> None:
    hist_json = json.dumps([c.model_dump(mode="json", exclude_none=True) for c in history], ensure_ascii=False)
    msgs_json = json.dumps(messages, ensure_ascii=False, default=str)
    now = db.now()
    if created:
        db.execute("INSERT INTO chats(id, title, history, messages, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                   (chat_id, title, hist_json, msgs_json, now, now))
    else:
        db.execute("UPDATE chats SET history=?, messages=?, updated_at=? WHERE id=?", (hist_json, msgs_json, now, chat_id))


def list_memories() -> list[dict]:
    return db.query("SELECT id, text, source, created_at FROM memories ORDER BY id")


def add_memory(text: str, source: str = "you", chat_id: str | None = None) -> dict:
    text = " ".join((text or "").split())[:400]
    if not text:
        raise ValueError("Memory is empty")
    existing = db.one("SELECT id, text FROM memories WHERE lower(text)=lower(?)", (text,))
    if existing:
        return {**existing, "duplicate": True}
    mid = db.execute("INSERT INTO memories(text, source, chat_id, created_at) VALUES (?,?,?,?)",
                     (text, source, chat_id, db.now()))
    return {"id": mid, "text": text}


def delete_memory(memory_id: int) -> bool:
    found = db.scalar("SELECT 1 FROM memories WHERE id=?", (int(memory_id),))
    db.execute("DELETE FROM memories WHERE id=?", (int(memory_id),))
    return bool(found)


def clear_memories() -> int:
    n = db.scalar("SELECT COUNT(*) FROM memories") or 0
    db.execute("DELETE FROM memories")
    return n


def _memory_block(enabled: bool) -> str:
    if not enabled:
        return "Memory is turned off by the user. Do not save or mention memories."
    mems = list_memories()
    lines = "\n".join(f"- [{m['id']}] {m['text']}" for m in mems) or "(nothing saved yet)"
    return ("Memory: durable facts and preferences the user shared in earlier chats. Use them silently; "
            "don't recite them unless asked.\n" + lines + "\n"
            "When the user states a lasting preference, goal, constraint or fact about themselves or their outreach "
            "(not a one-off request), call remember with one short sentence. If they ask you to forget something, or a "
            "memory is now wrong, call forget with its id. Never store passwords, keys or other secrets.")


# ---------------------------------------------------------------------------
# Conversation loop (Gemini, streamed)
# ---------------------------------------------------------------------------
def chat_stream(session_id: str | None, message: str) -> Iterator[dict]:
    """Run one user turn, persist the chat, and yield UI events:
    session, thinking, text, tool_start, tool_end, runs, confirm, error, done."""
    chat_id = session_id or uuid.uuid4().hex
    history, messages, title, exists = _load(chat_id)
    title = title or _title_from(message)
    yield {"type": "session", "session_id": chat_id, "title": title, "model": ai.model_label(), "new": not exists}

    now_ms = lambda: int(time.time() * 1000)  # noqa: E731
    bot: dict = {"role": "bot", "blocks": [], "ts": now_ms()}
    messages.append({"role": "user", "text": message, "ts": now_ms()})
    messages.append(bot)
    blocks = bot["blocks"]

    def close_thinking():
        if blocks and blocks[-1]["kind"] == "thinking" and not blocks[-1].get("t1"):
            blocks[-1]["t1"] = now_ms()

    ctx: dict = {"runs": [], "confirm": None, "changed": False, "memory_changed": False, "chat_id": chat_id}
    for ev in _run_turn(history, message, ctx):
        t = ev["type"]
        if t == "thinking":
            if blocks and blocks[-1]["kind"] == "thinking" and not blocks[-1].get("t1"):
                blocks[-1]["text"] += ev["text"]
            else:
                blocks.append({"kind": "thinking", "text": ev["text"], "t0": now_ms()})
        elif t == "text":
            close_thinking()
            if blocks and blocks[-1]["kind"] == "text":
                blocks[-1]["text"] += ev["text"]
            else:
                blocks.append({"kind": "text", "text": ev["text"]})
        elif t == "tool_start":
            close_thinking()
            blocks.append({"kind": "tool", "id": ev["id"], "name": ev["name"], "label": ev["label"], "input": ev["input"]})
        elif t == "tool_end":
            for b in blocks:
                if b["kind"] == "tool" and b["id"] == ev["id"]:
                    b.update(done=True, ok=ev["ok"], summary=ev["summary"])
        elif t == "error":
            bot["error"] = ev["message"]
        yield ev
    close_thinking()
    if ctx["runs"]:
        bot["runs"] = ctx["runs"]
        yield {"type": "runs", "runs": ctx["runs"]}
    if ctx["confirm"]:
        bot["confirm"] = ctx["confirm"]
        yield {"type": "confirm", **ctx["confirm"]}

    history[:] = _trim(history)
    with _sessions_lock:
        _sessions[chat_id] = history
    try:
        _save(chat_id, title, history, messages, created=not exists)
    except Exception as exc:  # never lose the answer because saving failed
        yield {"type": "error", "message": f"Couldn't save this chat: {exc}"}
    yield {"type": "done", "changed": ctx["changed"], "memory_changed": ctx["memory_changed"],
           "title": title, "session_id": chat_id, "session_reset": False}


def _run_turn(history: list[T.Content], message: str, ctx: dict) -> Iterator[dict]:
    history.append(T.Content(role="user", parts=[T.Part(text=message)]))
    settings = db.all_settings()
    memory_on = bool(settings.get("memory_enabled", True))
    system = SYSTEM.format(today=date.today().isoformat(),
                           profile=(settings.get("sender_profile") or "(not filled in yet)")[:6000],
                           goal=settings.get("outreach_goal") or "",
                           memory=_memory_block(memory_on),
                           snapshot=dashboard_snapshot())
    base = dict(system_instruction=system, tools=_declarations(memory_on),
                thinking_config=T.ThinkingConfig(include_thoughts=True))

    try:
        nudges = 0
        for step in range(MAX_STEPS + 1):
            final = step == MAX_STEPS
            cfg = T.GenerateContentConfig(**base, tool_config=T.ToolConfig(
                function_calling_config=T.FunctionCallingConfig(mode="NONE" if final else "AUTO")))
            parts_out: list[T.Part] = []
            text_buf, text_sig = "", None
            calls: list[T.FunctionCall] = []
            for _model, chunk in ai.stream(history, cfg):
                cand = chunk.candidates[0] if chunk.candidates else None
                for part in ((cand.content.parts or []) if cand and cand.content else []):
                    if part.function_call:
                        if text_buf:
                            parts_out.append(T.Part(text=text_buf, thought_signature=text_sig))
                            text_buf, text_sig = "", None
                        parts_out.append(part)
                        calls.append(part.function_call)
                    elif part.thought:
                        if part.text:
                            yield {"type": "thinking", "text": part.text}
                        if part.thought_signature:
                            parts_out.append(part)
                    elif part.text:
                        text_buf += part.text
                        if part.thought_signature:
                            text_sig = part.thought_signature
                        yield {"type": "text", "text": part.text}
                    elif part.thought_signature:
                        text_sig = part.thought_signature
            if text_buf or text_sig:
                parts_out.append(T.Part(text=text_buf, thought_signature=text_sig))
            if parts_out:
                history.append(T.Content(role="model", parts=parts_out))
            if not calls and not text_buf.strip():
                # The model thought but neither acted nor answered. Nudge it (max twice).
                if nudges < 2 and not final:
                    nudges += 1
                    nudge = T.Part(text=NUDGE)
                    if history and history[-1].role == "user":
                        history[-1].parts.append(nudge)
                    else:
                        history.append(T.Content(role="user", parts=[nudge]))
                    continue
                yield {"type": "text", "text": "I couldn't put an answer together this time. Gemini may be busy; please send that again."}
                break
            if not calls:
                break
            responses = []
            for i, fc in enumerate(calls):
                name = fc.name
                args = _plain(dict(fc.args or {}))
                call_id = fc.id or f"{step}-{i}"
                yield {"type": "tool_start", "id": call_id, "name": name,
                       "label": TOOL_LABELS.get(name, name), "input": args}
                try:
                    out = _run_tool(name, args, ctx)
                    ok = not (isinstance(out, dict) and out.get("error"))
                except Exception as exc:  # tool failures go back to the model, not the user
                    out, ok = {"error": str(exc)}, False
                yield {"type": "tool_end", "id": call_id, "name": name, "ok": ok, "summary": _tool_summary(name, out)}
                payload = _plain(out)
                if len(json.dumps(payload, ensure_ascii=False)) > 60000:
                    payload = {"truncated": json.dumps(payload, ensure_ascii=False)[:60000]}
                responses.append(T.Part(function_response=T.FunctionResponse(
                    id=fc.id, name=name, response={"result": payload})))
            history.append(T.Content(role="user", parts=responses))
    except Exception as exc:
        # Keep history valid for the next turn: drop a dangling model turn.
        while history and history[-1].role == "model":
            history.pop()
        msg = str(exc) if isinstance(exc, ai.AIError) else f"Something went wrong: {exc}"
        yield {"type": "error", "message": msg}



def chat(session_id: str | None, message: str) -> dict:  # noqa: F811
    """Non-streaming wrapper (CLI, tests)."""
    out = {"session_id": session_id, "reply": "", "actions": [], "runs": [], "confirm": None,
           "changed": False, "session_reset": False}
    for ev in chat_stream(session_id, message):
        t = ev["type"]
        if t == "session":
            out["session_id"] = ev["session_id"]
        elif t == "text":
            out["reply"] += ev["text"]
        elif t == "tool_end":
            out["actions"].append({"tool": ev["name"], "ok": ev["ok"], "summary": ev["summary"]})
        elif t == "runs":
            out["runs"] = ev["runs"]
        elif t == "confirm":
            out["confirm"] = {k: v for k, v in ev.items() if k != "type"}
        elif t == "error":
            out["error"] = ev["message"]
            out["reply"] = out["reply"] or ev["message"]
        elif t == "done":
            out["changed"], out["session_reset"] = ev["changed"], ev["session_reset"]
    out["reply"] = out["reply"].strip()
    return out


def reset(session_id: str) -> None:
    with _sessions_lock:
        _sessions.pop(session_id, None)
