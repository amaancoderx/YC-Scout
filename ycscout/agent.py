"""Command agent: operate the whole pipeline in plain English.

Gemini gets tools over the local database and job system. It can search,
qualify, research, draft and approve. Sending is never executed by the agent:
it returns a confirmation request the user clicks in the UI.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date, timedelta
from typing import Iterator

from google.genai import types as T

from . import ai, config, db, jobs, outreach, pipeline
from .sources import yc

SYSTEM = """You are the operator of YC Scout, a tool that sources recently funded Y Combinator startups, finds their founders' contact details and runs email outreach. Today is {today}.

You act through tools on the user's local database. Work like a sharp sales-ops lead:
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

What they want from outreach: {goal}"""

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


def _run_tool(name: str, args: dict, ctx: dict) -> object:
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
}


def _declarations() -> list[T.Tool]:
    return [T.Tool(function_declarations=[
        T.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"])
        for t in TOOLS
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
    if isinstance(out, dict) and out.get("status") == "skipped":
        return "already up to date" if name == "start_sync" else "already researched"
    if name == "research_companies" and isinstance(out, dict) and out.get("skipped_already_researched"):
        return f"job started, {out['skipped_already_researched']} already researched skipped"
    if name in ("draft_emails", "start_sync", "research_companies") and isinstance(out, dict):
        return "job started"
    return "done"


def _plain(obj):
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


def chat_stream(session_id: str | None, message: str) -> Iterator[dict]:
    """Run one user turn and yield UI events:
    session, thinking, text, tool_start, tool_end, runs, confirm, error, done."""
    session_id = session_id or uuid.uuid4().hex
    yield {"type": "session", "session_id": session_id, "model": ai.model_label()}
    with _sessions_lock:
        history: list[T.Content] = _sessions.setdefault(session_id, [])
    history.append(T.Content(role="user", parts=[T.Part(text=message)]))
    ctx: dict = {"runs": [], "confirm": None, "changed": False}
    settings = db.all_settings()
    system = SYSTEM.format(today=date.today().isoformat(),
                           profile=(settings.get("sender_profile") or "(not filled in yet)")[:6000],
                           goal=settings.get("outreach_goal") or "")
    base = dict(system_instruction=system, tools=_declarations(),
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

    if ctx["runs"]:
        yield {"type": "runs", "runs": ctx["runs"]}
    if ctx["confirm"]:
        yield {"type": "confirm", **ctx["confirm"]}
    reset_note = False
    if len(history) > 120:
        reset(session_id)
        reset_note = True
    yield {"type": "done", "changed": ctx["changed"], "session_reset": reset_note}


def chat(session_id: str | None, message: str) -> dict:
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
