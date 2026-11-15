"""Outreach: drafting, sending, reply/bounce detection and follow-ups.

Safety model
  * First-touch emails are always drafts until a human approves them.
  * Only follow-ups can be auto-approved (setting: auto_followups).
  * Daily send cap, delay between sends, suppression list and per-address
    de-duplication are enforced at send time, not just at draft time.
"""
from __future__ import annotations

import email.utils
import imaplib
import re
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import ai, config, db, fit
from .jobs import Run

CONF_ORDER = {"verified": 0, "inferred": 1, "likely": 2, "guess": 3}


# ---------------------------------------------------------------------------
# Recipients
# ---------------------------------------------------------------------------

def recipients(company_id: int, target: str = "ceo") -> list[dict]:
    """target: ceo | founders | inbox"""
    founders = db.query(
        "SELECT * FROM founders WHERE company_id=? AND is_active=1 ORDER BY id", (company_id,))
    contacts = db.query("SELECT * FROM contacts WHERE company_id=?", (company_id,))
    out: list[dict] = []

    def best_for(fid: int) -> dict | None:
        items = [c for c in contacts if c["founder_id"] == fid and c["mx_ok"] != 0]
        return min(items, key=lambda c: (CONF_ORDER.get(c["confidence"], 9), -c["is_primary"])) if items else None

    if target in ("ceo", "founders"):
        ordered = sorted(founders, key=lambda f: 0 if re.search(r"\bceo\b|chief executive", f.get("title") or "", re.I) else 1)
        for f in ordered:
            c = best_for(f["id"])
            if c:
                out.append({"email": c["email"], "name": f["name"], "first_name": f["first_name"],
                            "founder_id": f["id"], "confidence": c["confidence"], "founder": f})
            if target == "ceo" and out:
                break
    if target == "inbox" or not out:
        inbox = [c for c in contacts if c["kind"] == "company" and c["is_primary"]]
        if inbox:
            c = inbox[0]
            first = founders[0]["first_name"] if len(founders) == 1 else None
            out.append({"email": c["email"], "name": None, "first_name": first or "there",
                        "founder_id": None, "confidence": c["confidence"], "founder": None})
    return out


# ---------------------------------------------------------------------------
# Drafting
# ---------------------------------------------------------------------------

def _vars(company: dict, rcpt: dict, extra: dict | None = None) -> dict:
    jobs = db.query("SELECT title, location FROM jobs WHERE company_id=? AND active=1", (company["id"],))
    batch = company.get("batch") or ""
    eng = [j for j in jobs if fit.ENG_ROLE.search(j["title"] or "")]
    pick = (eng or jobs or [None])[0]
    if pick:
        hiring_line = f"I saw you're hiring for {_role(pick['title'])}"
        if "remote" in (pick["location"] or "").lower():
            hiring_line += " (remote), which is exactly what I'm looking for."
        else:
            hiring_line += ", which is exactly the kind of work I do."
    else:
        hiring_line = ""
    proof = (company.get("fit_proof") or db.get_setting("default_proof_line") or "").strip()
    m = re.match(r"(\w+) (\d{4})", batch)
    short = f"{m.group(1)[0]}{m.group(2)[2:]}" if m else batch
    return {
        "first_name": rcpt.get("first_name") or "there",
        "full_name": rcpt.get("name") or "",
        "company": company["name"],
        "one_liner": _midsentence((company.get("one_liner") or "").strip().rstrip(".")),
        "batch": short,
        "batch_full": batch,
        "website": company.get("website") or "",
        "location": company.get("location") or "",
        "job_title": pick["title"] if pick else "",
        "hiring_line": hiring_line,
        "proof_line": proof,
        "open_roles": str(len(jobs)),
        "sender_name": sender_name(),
        **(extra or {}),
    }


def _role(title: str) -> str:
    """'Founding AI Engineer' -> 'a Founding AI Engineer'."""
    t = title.strip()
    if re.match(r"(a|an|the)\s", t, re.I):
        return t
    return ("an " if t[:1].lower() in "aeiou" else "a ") + t


def _midsentence(text: str) -> str:
    """'The AI platform' -> 'the AI platform', but keep 'AI-native …' / 'GPU …'."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


def render(template: str, values: dict) -> str:
    def sub(m: re.Match) -> str:
        return str(values.get(m.group(1).strip(), ""))
    text = re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", sub, template)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()  # an empty variable on its own line leaves no gap


def sender_name() -> str:
    if config.FROM_NAME:
        return config.FROM_NAME
    profile = db.get_setting("sender_profile") or ""
    m = re.search(r"^[ \t]*Name:[ \t]*(\S.*)$", profile, re.M)
    return m.group(1).strip() if m and m.group(1).strip() else ""


DRAFT_SYSTEM = """You write cold emails to startup founders that get replies. You are writing on behalf of the sender described below.

Sender profile:
{profile}

Goal of the outreach: {goal}
Tone: {tone}

Rules:
- 60-120 words. Plain text, no markdown, no emojis, no bullet lists, no em dashes (use commas or periods).
- Format like a real email: "Hi <first name>," on its own line, then 2-3 short paragraphs separated by blank lines, then the sign-off on its own line.
- Open with one specific, accurate detail about their company (from the dossier), not generic praise.
- Say who the sender is and why it is relevant to *this* company in one or two sentences. Pick the ONE project from the profile closest to what this company builds (the dossier suggests one) and mention it with a concrete number or detail and its link.
- If they have an open role that fits, name that exact role. If not, offer to help as an intern, full-time engineer or contractor, whichever suits a company this size.
- Exactly one clear, low-friction ask.
- Never invent facts about the sender or the company. Use only the profile and dossier.
- No placeholders like [Name]. If something is unknown, write around it.
- Subject: under 7 words, lowercase-ish, specific, not salesy.
- Sign off with the sender's first name only (or nothing if unknown). Don't add an unsubscribe line; it is appended automatically."""

DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "body"],
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
}


def _dossier(company: dict, rcpt: dict) -> str:
    jobs = db.query("SELECT title, location, salary FROM jobs WHERE company_id=? AND active=1", (company["id"],))
    lines = [
        f"Company: {company['name']} (YC {company.get('batch')})",
        f"One-liner: {company.get('one_liner')}",
        f"Description: {(company.get('description') or '')[:1200]}",
        f"Website: {company.get('website')}",
        f"Location: {company.get('location')} · Team size: {company.get('team_size')}",
        f"Funding: {company.get('funding_total')} ({company.get('funding_detail')})",
    ]
    if company.get("launch_title"):
        lines.append(f"Launch post: {company['launch_title']}")
    if jobs:
        lines.append("Open roles: " + "; ".join(f"{j['title']} ({j['location']}{', ' + j['salary'] if j['salary'] else ''})" for j in jobs[:6]))
    reasons = db.loads(company.get("fit_reasons"), [])
    if reasons:
        lines.append(f"Why this company fits the sender (score {company.get('fit_score')}/100): " + "; ".join(reasons))
    if company.get("fit_proof"):
        lines.append(f"Sender's most relevant proof point for this company: {company['fit_proof']}")
    if company.get("research_notes"):
        lines.append("Research highlights:\n" + company["research_notes"][:1500])
    f = rcpt.get("founder")
    if f:
        lines.append(f"Recipient: {f['name']}, {f.get('title') or 'Founder'}")
        if f.get("bio"):
            lines.append(f"Recipient bio: {f['bio'][:800]}")
    else:
        lines.append("Recipient: the company's general inbox (address the team).")
    return "\n".join(lines)


def ai_draft(company: dict, rcpt: dict, instructions: str | None = None) -> tuple[str, str]:
    settings = db.all_settings()
    system = DRAFT_SYSTEM.format(
        profile=settings.get("sender_profile") or "(not provided)",
        goal=settings.get("outreach_goal") or "Start a conversation.",
        tone=settings.get("email_tone") or "Direct and warm.",
    )
    prompt = _dossier(company, rcpt)
    if instructions:
        prompt += f"\n\nExtra instructions for this email: {instructions}"
    data = ai.structured(system=system, prompt=prompt, schema=DRAFT_SCHEMA, effort="medium", max_tokens=6000)
    return data["subject"].replace("\u2014", "-").strip(), _tidy_body(data["body"])


def _tidy_body(body: str) -> str:
    """Guarantee email shape even if the model returns one block of text."""
    body = body.replace("\r\n", "\n").strip()
    body = body.replace(" \u2014 ", ", ").replace("\u2014", ", ")  # em dashes read as machine-written
    if "\n\n" in body:
        return body
    m = re.match(r"^((?:Hi|Hey|Hello|Dear)\b[^,\n]{0,60},)\s*(.*)$", body, re.S)
    greet, rest = (m.group(1), m.group(2)) if m else ("", body)
    sign = ""
    m2 = re.search(r"\s((?:Best|Thanks|Cheers|Regards)[^\n.]{0,20},?\s*)?([A-Z][a-z]+)\s*$", rest)
    if m2:
        lead = (m2.group(1) or "").strip()
        sign = (lead + "\n" if lead else "") + m2.group(2)
        rest = rest[: m2.start()].strip()
    sentences = re.split(r"(?<=[.?!])\s+(?=[A-Z])", rest)
    paras, cur = [], []
    for sent in sentences:
        cur.append(sent)
        if len(cur) == 2:
            paras.append(" ".join(cur))
            cur = []
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(x for x in [greet, *paras, sign] if x)


def create_drafts(company_ids: list[int], *, mode: str = "ai", target: str = "ceo",
                  instructions: str | None = None, run: Run | None = None) -> dict:
    """Create step-1 drafts. Returns counts."""
    if mode == "ai" and not config.ai_enabled():
        mode = "template"
        if run:
            run.log("No GEMINI_API_KEY, using your email template instead of AI drafting.")
    settings = db.all_settings()
    made = skipped = failed = 0
    if run:
        run.set_total(len(company_ids))
    for cid in company_ids:
        if run:
            run.check()
        company = db.one("SELECT * FROM companies WHERE id=?", (cid,))
        if not company:
            continue
        rcpts = recipients(cid, target)
        if not rcpts and run:
            run.log(f"  – {company['name']}: no usable email")
        for r in rcpts:
            if db.is_suppressed(r["email"]) or db.one(
                    "SELECT 1 FROM outreach WHERE to_email=? AND step=1 AND status NOT IN ('cancelled','failed')", (r["email"],)):
                skipped += 1
                continue
            try:
                if mode == "ai":
                    subject, body = ai_draft(company, r, instructions)
                else:
                    values = _vars(company, r)
                    subject = render(settings["template_subject"], values)
                    body = render(settings["template_body"], values)
                db.execute(
                    """INSERT INTO outreach(company_id, founder_id, to_email, to_name, subject, body, step, status,
                           generated_by, created_at) VALUES (?,?,?,?,?,?,1,'draft',?,?)""",
                    (cid, r["founder_id"], r["email"], r["name"], subject, body, mode, db.now()),
                )
                made += 1
                if run:
                    run.log(f"  ✓ {company['name']} → {r['email']} ({r['confidence']})")
            except Exception as exc:
                failed += 1
                if run:
                    run.log(f"  ! {company['name']}: {exc}")
                if isinstance(exc, ai.AINotConfigured):
                    raise
        if run:
            run.advance()
    return {"drafted": made, "skipped": skipped, "failed": failed}


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def sent_today() -> int:
    start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    return db.scalar("SELECT COUNT(*) FROM outreach WHERE status IN ('sent','replied','bounced') AND sent_at>=?", (start,)) or 0


def _footer() -> str:
    parts = [db.get_setting("signature_footer") or "", db.get_setting("physical_address") or ""]
    return "\n".join(p.strip() for p in parts if p and p.strip())


def _build(row: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((sender_name() or None, config.FROM_EMAIL)) if sender_name() else config.FROM_EMAIL
    msg["To"] = email.utils.formataddr((row["to_name"], row["to_email"])) if row.get("to_name") else row["to_email"]
    msg["Subject"] = row["subject"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=config.FROM_EMAIL.split("@")[-1])
    msg["List-Unsubscribe"] = f"<mailto:{config.FROM_EMAIL}?subject=unsubscribe>"
    if row.get("thread_ref"):
        msg["In-Reply-To"] = row["thread_ref"]
        msg["References"] = row["thread_ref"]
    footer = _footer()
    msg.set_content(row["body"].rstrip() + (f"\n\n--\n{footer}" if footer else "") + "\n")
    return msg


def _smtp() -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    if config.SMTP_PORT == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=ctx, timeout=30)
    else:
        server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30)
        server.ehlo()
        server.starttls(context=ctx)
        server.ehlo()
    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
    return server


def test_smtp() -> str:
    if not config.smtp_enabled():
        raise RuntimeError("SMTP is not configured in .env")
    server = _smtp()
    server.quit()
    return f"Logged in to {config.SMTP_HOST} as {config.SMTP_USER}"


def send_approved(run: Run, *, only_followups: bool = False) -> str:
    if not config.smtp_enabled():
        raise RuntimeError("SMTP is not configured. Add SMTP_USER / SMTP_PASSWORD to .env.")
    limit = int(db.get_setting("daily_send_limit", 40))
    delay = max(5, int(db.get_setting("send_delay_seconds", 45)))
    sql = "SELECT * FROM outreach WHERE status='approved'" + (" AND step>1" if only_followups else "") + " ORDER BY approved_at, id"
    queue = db.query(sql)
    remaining = limit - sent_today()
    if remaining <= 0:
        run.log(f"Daily limit of {limit} reached. Nothing sent.")
        return f"Daily limit reached ({limit})"
    queue = queue[:remaining]
    run.set_total(len(queue))
    if not queue:
        return "Nothing approved to send"
    run.log(f"Sending {len(queue)} emails (limit left today: {remaining}, {delay}s apart) ...")
    sent = failed = 0
    server = None
    try:
        for i, row in enumerate(queue):
            run.check()
            if db.is_suppressed(row["to_email"]):
                db.execute("UPDATE outreach SET status='cancelled', error='suppressed' WHERE id=?", (row["id"],))
                run.log(f"  – {row['to_email']} is on the do-not-contact list; skipped")
                run.advance()
                continue
            if row["step"] == 1 and db.one(
                    "SELECT 1 FROM outreach WHERE to_email=? AND step=1 AND status IN ('sent','replied','bounced') AND id!=?",
                    (row["to_email"], row["id"])):
                db.execute("UPDATE outreach SET status='cancelled', error='already contacted' WHERE id=?", (row["id"],))
                run.log(f"  – {row['to_email']} already contacted; skipped")
                run.advance()
                continue
            db.execute("UPDATE outreach SET status='sending' WHERE id=?", (row["id"],))
            try:
                if server is None:
                    server = _smtp()
                msg = _build(row)
                server.send_message(msg)
                ts = db.now()
                db.execute("UPDATE outreach SET status='sent', sent_at=?, message_id=?, error=NULL, "
                           "thread_ref=COALESCE(thread_ref, ?) WHERE id=?",
                           (ts, msg["Message-ID"], msg["Message-ID"], row["id"]))
                db.execute("UPDATE companies SET stage='contacted' WHERE id=? AND stage IN ('new','qualified')", (row["company_id"],))
                sent += 1
                run.log(f"  ✓ sent to {row['to_email']}")
            except smtplib.SMTPRecipientsRefused as exc:
                db.execute("UPDATE outreach SET status='bounced', error=? WHERE id=?", (str(exc)[:300], row["id"]))
                db.suppress(row["to_email"], "refused by server")
                failed += 1
                run.log(f"  ! {row['to_email']}: recipient refused")
            except (smtplib.SMTPException, OSError) as exc:
                db.execute("UPDATE outreach SET status='failed', error=? WHERE id=?", (str(exc)[:300], row["id"]))
                failed += 1
                run.log(f"  ! {row['to_email']}: {exc}")
                try:
                    if server:
                        server.quit()
                except Exception:
                    pass
                server = None
            run.advance()
            if i < len(queue) - 1:
                for _ in range(delay):
                    run.check()
                    time.sleep(1)
    finally:
        if server:
            try:
                server.quit()
            except Exception:
                pass
    return f"Sent {sent}" + (f", {failed} failed" if failed else "")


# ---------------------------------------------------------------------------
# Replies, bounces, follow-ups
# ---------------------------------------------------------------------------

def check_replies(run: Run | None = None) -> str:
    if not config.imap_enabled():
        raise RuntimeError("IMAP is not configured (uses SMTP_USER / SMTP_PASSWORD with IMAP_HOST).")
    pending = db.query(
        "SELECT to_email, MIN(sent_at) AS first_sent FROM outreach WHERE status='sent' GROUP BY to_email")
    if not pending:
        return "No sent emails awaiting replies"
    imap = imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT, ssl_context=ssl.create_default_context())
    replied = bounced = 0
    try:
        imap.login(config.SMTP_USER, config.SMTP_PASSWORD)
        imap.select("INBOX", readonly=True)
        earliest = min(p["first_sent"] for p in pending)
        since = datetime.strptime(earliest, "%Y-%m-%dT%H:%M:%SZ").strftime("%d-%b-%Y")
        for p in pending:
            addr = p["to_email"]
            typ, data = imap.search(None, "FROM", f'"{addr}"', "SINCE", since)
            if typ == "OK" and data and data[0].split():
                ts = db.now()
                db.execute("UPDATE outreach SET status='replied', replied_at=? WHERE to_email=? AND status='sent'", (ts, addr))
                db.execute("UPDATE outreach SET status='cancelled', error='recipient replied' WHERE to_email=? AND status IN ('draft','approved')", (addr,))
                db.execute("UPDATE companies SET stage='replied' WHERE id IN (SELECT company_id FROM outreach WHERE to_email=?) "
                           "AND stage IN ('new','qualified','contacted')", (addr,))
                replied += 1
                if run:
                    run.log(f"  ✓ reply from {addr}")
        # Bounces: delivery-failure notices that mention one of our recipients.
        typ, data = imap.search(None, "SINCE", since, "OR", "FROM", '"mailer-daemon"', "FROM", '"postmaster"')
        if typ == "OK" and data and data[0]:
            addrs = {p["to_email"] for p in pending}
            for num in data[0].split()[-200:]:
                typ, msg_data = imap.fetch(num, "(BODY.PEEK[TEXT])")
                if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                    continue
                text = msg_data[0][1].decode("utf-8", "ignore").lower()
                for addr in list(addrs):
                    if addr in text:
                        db.execute("UPDATE outreach SET status='bounced' WHERE to_email=? AND status='sent'", (addr,))
                        db.execute("UPDATE outreach SET status='cancelled', error='bounced' WHERE to_email=? AND status IN ('draft','approved')", (addr,))
                        db.execute("UPDATE contacts SET mx_ok=0 WHERE email=?", (addr,))
                        db.suppress(addr, "bounced")
                        addrs.discard(addr)
                        bounced += 1
                        if run:
                            run.log(f"  ! bounce for {addr}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return f"{replied} new replies, {bounced} bounces"


def schedule_followups() -> int:
    """Create follow-up drafts for sent emails with no reply after N days."""
    days = int(db.get_setting("followup_after_days", 4))
    max_f = int(db.get_setting("max_followups", 1))
    auto = bool(db.get_setting("auto_followups", False))
    settings = db.all_settings()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = db.query(
        """SELECT o.* FROM outreach o WHERE o.status='sent' AND o.sent_at<=? AND o.step<=?
           AND NOT EXISTS (SELECT 1 FROM outreach x WHERE x.to_email=o.to_email AND x.step>o.step)
           AND NOT EXISTS (SELECT 1 FROM outreach r WHERE r.to_email=o.to_email AND r.status IN ('replied','bounced'))""",
        (cutoff, max_f),
    )
    made = 0
    for o in rows:
        if db.is_suppressed(o["to_email"]):
            continue
        company = db.one("SELECT * FROM companies WHERE id=?", (o["company_id"],))
        founder = db.one("SELECT * FROM founders WHERE id=?", (o["founder_id"],)) if o["founder_id"] else None
        rcpt = {"first_name": founder["first_name"] if founder else "there", "name": o["to_name"]}
        values = _vars(company, rcpt, {"original_subject": re.sub(r"^(re:\s*)+", "", o["subject"], flags=re.I)})
        subject = render(settings["followup_subject"], values)
        body = render(settings["followup_body"], values)
        ts = db.now()
        db.execute(
            """INSERT INTO outreach(company_id, founder_id, to_email, to_name, subject, body, step, status, generated_by,
                   thread_ref, created_at, approved_at) VALUES (?,?,?,?,?,?,?,?, 'template', ?, ?, ?)""",
            (o["company_id"], o["founder_id"], o["to_email"], o["to_name"], subject, body, o["step"] + 1,
             "approved" if auto else "draft", o["thread_ref"] or o["message_id"], ts, ts if auto else None),
        )
        made += 1
    return made
