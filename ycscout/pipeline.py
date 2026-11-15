"""End-to-end sourcing pipeline.

  roster (yc-oss)  →  YC company page  →  website crawl  →  email intelligence
                   →  [optional] AI deep research  →  Google Sheet sync
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from . import ai, config, db, fit
from .enrich import emails as em
from .enrich import website
from .enrich.research import _is_yc_only, research_company
from .jobs import Run
from .sources import yc

CONFIDENCE_RANK = {"verified": 0, "inferred": 1, "likely": 2, "guess": 3}
RESCRAPE_AFTER = timedelta(days=2)   # YC page: new jobs / founders show up often
RECRAWL_AFTER = timedelta(days=14)   # company website: rarely changes, don't re-collect it


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def sync_batches(run: Run, batch_slugs: list[str], *, crawl: bool = True, research: bool = False,
                 force: bool = False) -> str:
    company_ids: list[int] = []
    new_count = 0
    for slug in batch_slugs:
        run.check()
        run.log(f"Fetching roster for {slug} ...")
        roster = yc.batch_companies(slug)
        if not roster:
            run.log(f"  {slug}: no companies found")
            continue
        added = upsert_roster(roster, slug)
        new_count += added
        company_ids += [c["id"] for c in roster]
        run.log(f"  {slug}: {len(roster)} companies ({added} new)")

    todo = [cid for cid in company_ids if force or _needs_scrape(cid)]
    skipped = len(company_ids) - len(todo)
    if skipped:
        run.log(f"{skipped} companies are fresh (scraped < 2 days ago) and were skipped. Use 'Force refresh' to redo them.")
    run.set_total(len(todo) + (len(company_ids) if research else 0))
    run.log(f"Enriching {len(todo)} companies (YC page{' + website' if crawl else ''} + emails) ...")

    stats = {"ok": 0, "failed": 0, "emails": 0, "jobs": 0}
    with ThreadPoolExecutor(max_workers=max(1, config.YC_CONCURRENCY)) as pool:
        futures = {pool.submit(enrich_company, cid, crawl=crawl and (force or _needs_crawl(cid)), run=run): cid
                   for cid in todo}
        for fut in as_completed(futures):
            if run.cancelled:
                for f in futures:
                    f.cancel()
                run.check()
            cid = futures[fut]
            try:
                res = fut.result()
                stats["ok"] += 1
                stats["emails"] += res["emails"]
                stats["jobs"] += res["jobs"]
            except Exception as exc:
                stats["failed"] += 1
                name = db.scalar("SELECT name FROM companies WHERE id=?", (cid,))
                run.log(f"  ! {name}: {type(exc).__name__}: {exc}")
            run.advance()

    if research:
        ids = [cid for cid in company_ids if force or not db.scalar("SELECT researched_at FROM companies WHERE id=?", (cid,))]
        run.advance(len(company_ids) - len(ids))
        research_many(run, ids)

    summary = (
        f"{len(company_ids)} companies in scope, {new_count} new · {stats['ok']} enriched"
        f"{', ' + str(stats['failed']) + ' failed' if stats['failed'] else ''} · "
        f"{stats['emails']} emails · {stats['jobs']} open roles"
    )
    run.log(summary)
    dupes = dedupe_all()
    if any(dupes.values()):
        run.log(f"Removed duplicates: {dupes['phones']} phone, {dupes['whatsapp']} WhatsApp, {dupes['jobs']} job postings")
    fit.rescore()
    _maybe_sync_sheet(run)
    return summary


def research_many(run: Run, company_ids: list[int]) -> str:
    if not config.ai_enabled():
        run.log("AI research skipped: GEMINI_API_KEY is not set.")
        return "AI research skipped (no API key)"
    if not run.total:
        run.set_total(len(company_ids))
    run.log(f"AI deep research on {len(company_ids)} companies ...")
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(research_one, cid): cid for cid in company_ids}
        for fut in as_completed(futures):
            if run.cancelled:
                for f in futures:
                    f.cancel()
                run.check()
            cid = futures[fut]
            name = db.scalar("SELECT name FROM companies WHERE id=?", (cid,))
            try:
                found = fut.result()
                ok += 1
                run.log(f"  ✓ {name}: {found}")
            except ai.AINotConfigured as exc:
                run.log(str(exc))
                break
            except Exception as exc:
                failed += 1
                run.log(f"  ! {name}: {exc}")
            run.advance()
    summary = f"Researched {ok} companies" + (f", {failed} failed" if failed else "")
    run.log(summary)
    return summary


def research_job(run: Run, company_ids: list[int], force: bool = False) -> str:
    company_ids = list(dict.fromkeys(company_ids))
    if not force:
        done = {r["id"] for r in db.query(
            f"SELECT id FROM companies WHERE researched_at IS NOT NULL AND id IN ({','.join('?' * len(company_ids))})",
            company_ids)} if company_ids else set()
        if done:
            run.log(f"{len(done)} already researched, skipped (their data is in the dashboard). Use refresh to redo them.")
        company_ids = [c for c in company_ids if c not in done]
        if not company_ids:
            run.log("Nothing new to research.")
            return f"Nothing new to research ({len(done)} already researched)"
    summary = research_many(run, company_ids)
    fit.rescore(company_ids)
    _maybe_sync_sheet(run)
    return summary


def _older_than(ts: str | None, age: timedelta) -> bool:
    if not ts:
        return True
    try:
        when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - when > age


def _needs_crawl(cid: int) -> bool:
    return _older_than(db.scalar("SELECT crawled_at FROM companies WHERE id=?", (cid,)), RECRAWL_AFTER)


def _needs_scrape(cid: int) -> bool:
    ts = db.scalar("SELECT scraped_at FROM companies WHERE id=?", (cid,))
    if not ts:
        return True
    try:
        when = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - when > RESCRAPE_AFTER


def _maybe_sync_sheet(run: Run) -> None:
    if config.sheets_enabled() and db.get_setting("auto_sheet_sync", True):
        from . import export
        try:
            url = export.sync_google_sheet()
            run.log(f"Google Sheet updated: {url}")
        except Exception as exc:
            run.log(f"Google Sheet sync failed: {exc}")


# ---------------------------------------------------------------------------
# Per-company steps
# ---------------------------------------------------------------------------

def upsert_roster(roster: list[dict], batch_slug: str) -> int:
    added = 0
    ts = db.now()
    with db.tx() as conn:
        for raw in roster:
            row = yc.normalize_company(raw, batch_slug)
            exists = conn.execute("SELECT 1 FROM companies WHERE id=?", (row["id"],)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=:{k}" for k in row if k != "id")
                conn.execute(f"UPDATE companies SET {sets}, updated_at=:ts WHERE id=:id", {**row, "ts": ts})
            else:
                added += 1
                cols = list(row) + ["first_seen_at", "updated_at", "funding_total", "funding_detail", "summary"]
                vals = {**row, "first_seen_at": ts, "updated_at": ts,
                        "funding_total": config.YC_STANDARD_DEAL, "funding_detail": config.YC_STANDARD_DEAL_DETAIL,
                        "summary": make_summary(row.get("description"), row.get("one_liner"))}
                conn.execute(
                    f"INSERT INTO companies({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})", vals
                )
    return added


def enrich_company(cid: int, *, crawl: bool = True, run: Run | None = None) -> dict:
    company = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    if not company:
        raise ValueError(f"Unknown company {cid}")
    page = yc.company_page(company["slug"])
    if page is None:
        raise ValueError("YC page not found")
    save_yc_page(cid, page)

    crawl_info = ""
    if crawl:
        result = website.crawl(company.get("website"))
        save_crawl(cid, result)
        crawl_info = f", site: {len(result.emails)} emails" if result.ok else f", site: {result.error}"
    rebuild_contacts(cid)

    n_emails = db.scalar("SELECT COUNT(*) FROM contacts WHERE company_id=?", (cid,)) or 0
    n_jobs = db.scalar("SELECT COUNT(*) FROM jobs WHERE company_id=? AND active=1", (cid,)) or 0
    if run:
        run.log(f"  ✓ {company['name']}: {len(page.founders)} founders, {n_jobs} jobs{crawl_info}")
    return {"emails": n_emails, "jobs": n_jobs}


def save_yc_page(cid: int, page: yc.CompanyPage) -> None:
    c = page.company
    ts = db.now()
    with db.tx() as conn:
        conn.execute(
            """UPDATE companies SET year_founded=COALESCE(?, year_founded), country=COALESCE(?, country),
                   linkedin_url=COALESCE(?, linkedin_url), twitter_url=COALESCE(?, twitter_url),
                   github_url=COALESCE(?, github_url), crunchbase_url=COALESCE(?, crunchbase_url),
                   launch_title=?, launch_url=?, scraped_at=?, updated_at=? WHERE id=?""",
            (
                c.get("year_founded"), c.get("country") or None,
                c.get("linkedin_url") or None, c.get("twitter_url") or None,
                c.get("github_url") or None, c.get("cb_url") or None,
                (page.launch or {}).get("title"), (page.launch or {}).get("url"),
                ts, ts, cid,
            ),
        )
        names = []
        for f in page.founders:
            first, last = em.split_name(f["name"])
            names.append(f["name"])
            conn.execute(
                """INSERT INTO founders(company_id, yc_user_id, name, first_name, last_name, title, bio,
                       linkedin_url, twitter_url, avatar_url, is_active)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(company_id, name) DO UPDATE SET yc_user_id=excluded.yc_user_id,
                       first_name=excluded.first_name, last_name=excluded.last_name, title=excluded.title,
                       bio=excluded.bio, linkedin_url=excluded.linkedin_url, twitter_url=excluded.twitter_url,
                       is_active=excluded.is_active""",
                (cid, f["yc_user_id"], f["name"], first, last, f["title"], f["bio"],
                 f["linkedin_url"], f["twitter_url"], f["avatar_url"], f["is_active"]),
            )
        if names:
            # Founders that left the company page are marked inactive, not deleted
            # (they may have outreach history).
            conn.execute(
                f"UPDATE founders SET is_active=0 WHERE company_id=? AND name NOT IN ({','.join('?' * len(names))})",
                (cid, *names),
            )
        conn.execute("UPDATE jobs SET active=0 WHERE company_id=?", (cid,))
        seen_jobs: set[tuple] = set()
        for j in page.jobs:
            if not j.get("id"):
                continue
            # YC sometimes lists the same posting several times; keep one.
            sig = tuple((j.get(k) or "").strip().lower() for k in
                        ("title", "location", "type", "salary", "equity", "experience", "visa"))
            if sig in seen_jobs:
                continue
            seen_jobs.add(sig)
            conn.execute(
                """INSERT INTO jobs(id, company_id, title, url, apply_url, location, type, role, salary, equity,
                       experience, visa, posted, active, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, url=excluded.url, apply_url=excluded.apply_url,
                       location=excluded.location, type=excluded.type, role=excluded.role, salary=excluded.salary,
                       equity=excluded.equity, experience=excluded.experience, visa=excluded.visa,
                       posted=excluded.posted, active=1, updated_at=excluded.updated_at""",
                (j["id"], cid, j["title"], j["url"], j["apply_url"], j["location"], j["type"], j["role"],
                 j["salary"], j["equity"], j["experience"], j["visa"], j["posted"], ts),
            )
        if page.jobs:
            conn.execute("UPDATE companies SET is_hiring=1 WHERE id=?", (cid,))
        for n in page.news:
            conn.execute(
                "INSERT OR IGNORE INTO news(company_id, title, url, date, source) VALUES (?,?,?,?, 'yc')",
                (cid, n["title"], n["url"], n["date"]),
            )


def save_crawl(cid: int, result: website.CrawlResult) -> None:
    company = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    founders = db.query("SELECT * FROM founders WHERE company_id=?", (cid,))
    ts = db.now()
    other = db.loads(company.get("other_links"), {})
    with db.tx() as conn:
        conn.execute("DELETE FROM contacts WHERE company_id=? AND source='website'", (cid,))
        for email, url in result.emails.items():
            kind, label, fid = em.classify(email, founders)
            conn.execute(
                """INSERT OR IGNORE INTO contacts(company_id, founder_id, email, kind, label, confidence, source,
                       source_url, created_at) VALUES (?,?,?,?,?, 'verified', 'website', ?, ?)""",
                (cid, fid, email, kind, label, url, ts),
            )
        phones = merge_phones(db.loads(company.get("phones"), []), [
            {"number": n, "source_url": u} for n, u in result.phones.items()])
        wa = merge_whatsapp(db.loads(company.get("whatsapp"), []), list(result.whatsapp.values()))
        for kind in ("instagram", "youtube", "discord", "calendly"):
            if kind in result.socials:
                other[kind] = result.socials[kind]
        conn.execute(
            """UPDATE companies SET website_ok=?, site_domain=?, phones=?, whatsapp=?, other_links=?,
                   linkedin_url=COALESCE(linkedin_url, ?), twitter_url=COALESCE(twitter_url, ?),
                   github_url=COALESCE(github_url, ?), crawled_at=?, updated_at=? WHERE id=?""",
            (1 if result.ok else 0, yc.domain_of(result.final_url) if result.ok else None,
             json.dumps(phones), json.dumps(wa), json.dumps(other),
             result.socials.get("linkedin"), result.socials.get("twitter"), result.socials.get("github"),
             ts, ts, cid),
        )


def rebuild_contacts(cid: int) -> None:
    """Regenerate pattern-based founder emails and pick primary contacts."""
    company = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    founders = db.query("SELECT * FROM founders WHERE company_id=? AND is_active=1", (cid,))
    domain = company.get("domain")
    ts = db.now()
    with db.tx() as conn:
        conn.execute("DELETE FROM contacts WHERE company_id=? AND source='pattern'", (cid,))
        found = [r["email"] for r in conn.execute(
            "SELECT email FROM contacts WHERE company_id=? AND source!='pattern'", (cid,)).fetchall()]
        # Re-link found person addresses to founders (founders may be new since the crawl).
        for row in conn.execute("SELECT id, email FROM contacts WHERE company_id=? AND founder_id IS NULL AND kind!='company'", (cid,)).fetchall():
            kind, _, fid = em.classify(row["email"], founders)
            if fid:
                conn.execute("UPDATE contacts SET founder_id=?, kind='founder' WHERE id=?", (fid, row["id"]))

        domain, mx = _mail_domain(company, found)
        conn.execute("UPDATE companies SET mail_domain=? WHERE id=?", (domain, cid))
        if domain and mx is not False:
            pattern = em.observed_pattern(found, founders, domain)
            for f in founders:
                has_real = conn.execute(
                    "SELECT 1 FROM contacts WHERE founder_id=? AND confidence='verified' AND COALESCE(mx_ok, 1)=1",
                    (f["id"],)).fetchone()
                if has_real:
                    continue
                for email, confidence in em.founder_candidates(f, domain, company.get("team_size"), pattern):
                    conn.execute(
                        """INSERT OR IGNORE INTO contacts(company_id, founder_id, email, kind, confidence, source,
                               mx_ok, created_at) VALUES (?,?,?, 'founder', ?, 'pattern', ?, ?)""",
                        (cid, f["id"], email, confidence, 1 if mx else None, ts),
                    )
        for row in conn.execute("SELECT id, email FROM contacts WHERE company_id=? AND mx_ok IS NULL", (cid,)).fetchall():
            ok = em.has_mx(row["email"].split("@")[1])
            if ok is not None:
                conn.execute("UPDATE contacts SET mx_ok=? WHERE id=?", (int(ok), row["id"]))

        # Primary = best confidence per founder; plus the best general company inbox.
        conn.execute("UPDATE contacts SET is_primary=0 WHERE company_id=?", (cid,))
        rows = [dict(r) for r in conn.execute("SELECT * FROM contacts WHERE company_id=?", (cid,)).fetchall()]
        by_founder: dict[int, list[dict]] = {}
        for r in rows:
            if r["founder_id"]:
                by_founder.setdefault(r["founder_id"], []).append(r)
        for items in by_founder.values():
            # An address whose domain can't receive mail never wins.
            best = min(items, key=lambda r: (r["mx_ok"] == 0, CONFIDENCE_RANK.get(r["confidence"], 9), r["id"]))
            conn.execute("UPDATE contacts SET is_primary=1 WHERE id=?", (best["id"],))
        generic = [r for r in rows if r["kind"] == "company" and r["email"].split("@")[0] not in em.NON_OUTREACH]
        if generic:
            order = ["founders", "hello", "hi", "team", "contact", "info"]
            generic.sort(key=lambda r: order.index(r["email"].split("@")[0]) if r["email"].split("@")[0] in order else 99)
            conn.execute("UPDATE contacts SET is_primary=1 WHERE id=?", (generic[0]["id"],))


def research_one(cid: int) -> str:
    company = db.one("SELECT * FROM companies WHERE id=?", (cid,))
    founders = db.query("SELECT * FROM founders WHERE company_id=? AND is_active=1", (cid,))
    known = [r["email"] for r in db.query(
        "SELECT email FROM contacts WHERE company_id=? AND confidence='verified'", (cid,))]
    data = research_company(company, founders, known)
    ts = db.now()

    rounds = data.get("funding_rounds") or []
    total = data.get("total_raised")
    if rounds or total:
        parts = [f"{r['round']}{' ' + r['amount'] if r.get('amount') else ''}{' (' + r['date'] + ')' if r.get('date') else ''}"
                 + (f" led by {', '.join(r['investors'][:3])}" if r.get("investors") else "") for r in rounds]
        detail = "; ".join(parts) or config.YC_STANDARD_DEAL_DETAIL
        funding = (total or config.YC_STANDARD_DEAL, detail, json.dumps(rounds), "researched")
    else:
        # Nothing new found: keep an earlier cited round, but never a YC-batch-only "round".
        prev = [r for r in db.loads(company.get("funding_rounds"), []) if not _is_yc_only(r)]
        if prev and company.get("funding_source") == "researched":
            funding = (company["funding_total"], company["funding_detail"], json.dumps(prev), "researched")
        else:
            funding = (config.YC_STANDARD_DEAL, config.YC_STANDARD_DEAL_DETAIL, "[]", "yc_standard")

    highlights = data.get("highlights") or []
    notes_md = "\n".join(f"- {h['fact']} ([source]({h['source_url']}))" for h in highlights)
    phones = db.loads(company.get("phones"), [])
    wa = db.loads(company.get("whatsapp"), [])
    for p in data.get("phones") or []:
        num = "+" + re.sub(r"\D", "", p["number"]) if p["number"].strip().startswith("+") else re.sub(r"\D", "", p["number"])
        if p.get("is_whatsapp"):
            wa = merge_whatsapp(wa, [{"number": num, "link": f"https://wa.me/{num.lstrip('+')}", "source_url": p["source_url"]}])
        else:
            phones = merge_phones(phones, [{"number": num, "source_url": p["source_url"]}])

    with db.tx() as conn:
        conn.execute(
            """UPDATE companies SET summary=COALESCE(NULLIF(?, ''), summary), funding_total=?, funding_detail=?,
                   funding_rounds=?, funding_source=?, research_notes=?, research_sources=?, phones=?, whatsapp=?,
                   researched_at=?, updated_at=? WHERE id=?""",
            (data.get("summary", "").strip(), *funding, notes_md, json.dumps(data.get("sources") or []),
             json.dumps(phones), json.dumps(wa), ts, ts, cid),
        )
        for item in data.get("emails") or []:
            kind, label, fid = em.classify(item["email"], founders)
            if not fid and item.get("person"):
                person = item["person"].strip().lower()
                fid = next((f["id"] for f in founders if f["name"].lower() == person), None)
                if fid:
                    kind = "founder"
            conn.execute(
                """INSERT INTO contacts(company_id, founder_id, email, kind, label, confidence, source, source_url, created_at)
                   VALUES (?,?,?,?,?, 'verified', 'research', ?, ?)
                   ON CONFLICT(company_id, email) DO UPDATE SET confidence='verified',
                       source=CASE WHEN contacts.source='pattern' THEN 'research' ELSE contacts.source END,
                       source_url=COALESCE(contacts.source_url, excluded.source_url),
                       founder_id=COALESCE(contacts.founder_id, excluded.founder_id)""",
                (cid, fid, item["email"], kind, label, item["source_url"], ts),
            )
        for n in data.get("news") or []:
            conn.execute("INSERT OR IGNORE INTO news(company_id, title, url, date, source) VALUES (?,?,?,?, 'research')",
                         (cid, n["title"], n["url"], n.get("date")))
    rebuild_contacts(cid)

    bits = [f"funding {funding[0]}"]
    if data.get("emails"):
        bits.append(f"{len(data['emails'])} verified emails")
    if highlights:
        bits.append(f"{len(highlights)} highlights")
    return ", ".join(bits)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mail_domain(company: dict, found_emails: list[str]) -> tuple[str | None, bool | None]:
    """Pick the domain founder addresses live on, from evidence first.

    1. The domain most used by addresses the company itself publishes.
    2. Otherwise the YC-listed domain, then the domain the site redirects to,
       whichever has a working mail server.
    """
    counts: dict[str, int] = {}
    for e in found_emails:
        dom = e.split("@")[1]
        if dom not in em.PERSONAL_PROVIDERS:
            counts[dom] = counts.get(dom, 0) + 1
    if counts:
        best = max(counts, key=counts.get)
        return best, em.has_mx(best)
    candidates = [d for d in (company.get("domain"), company.get("site_domain")) if d]
    unknown = None
    for d in dict.fromkeys(candidates):
        mx = em.has_mx(d)
        if mx:
            return d, True
        if mx is None and unknown is None:
            unknown = d
    if unknown:
        return unknown, None
    return (candidates[0] if candidates else None), False


def make_summary(description: str | None, one_liner: str | None, max_chars: int = 340) -> str:
    """First 2-3 sentences of YC's description (the founders' own words)."""
    text = re.sub(r"\s+", " ", (description or "").replace("#", " ")).strip()
    if not text:
        return (one_liner or "").strip()
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    out = ""
    for s in sentences[:3]:
        if len(out) + len(s) > max_chars and out:
            break
        out = f"{out} {s}".strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out


def phone_key(number: str | None) -> str:
    """Same number with or without country code / 00 prefix -> same key."""
    d = re.sub(r"\D", "", number or "")
    if d.startswith("00"):
        d = d[2:]
    return d[-10:] if len(d) >= 10 else d


def merge_phones(existing: list[dict], new: list[dict]) -> list[dict]:
    """Each number once; the international (+...) spelling wins."""
    out: list[dict] = []
    index: dict[str, int] = {}
    for item in [*existing, *new]:
        k = phone_key(item.get("number"))
        if not k:
            continue
        if k in index:
            cur = out[index[k]]
            if not str(cur["number"]).startswith("+") and str(item["number"]).startswith("+"):
                out[index[k]] = {**cur, "number": item["number"]}
            continue
        index[k] = len(out)
        out.append(item)
    return out


def merge_whatsapp(existing: list[dict], new: list[dict]) -> list[dict]:
    """WhatsApp entries keyed by number when known (wa.me/1… == wa.me/+1…), else by link."""
    out: list[dict] = []
    index: dict[str, int] = {}
    for item in [*existing, *new]:
        k = ("n:" + phone_key(item.get("number"))) if item.get("number") else ("l:" + str(item.get("link") or "").rstrip("/"))
        if k in ("n:", "l:"):
            continue
        if k in index:
            cur = out[index[k]]
            if item.get("number") and str(item["number"]).startswith("+") and not str(cur.get("number") or "").startswith("+"):
                out[index[k]] = {**cur, "number": item["number"]}
            continue
        index[k] = len(out)
        out.append(item)
    return out


def _merge_list(existing: list[dict], new: list[dict], key: str) -> list[dict]:
    seen = {e.get(key) for e in existing}
    out = list(existing)
    for item in new:
        if item.get(key) and item.get(key) not in seen:
            out.append(item)
            seen.add(item.get(key))
    return out


def dedupe_all() -> dict:
    """Safety net run after every sync: each phone, WhatsApp number and job posting once."""
    fixed = {"phones": 0, "whatsapp": 0, "jobs": 0}
    with db.tx() as conn:
        for c in conn.execute("SELECT id, phones, whatsapp FROM companies").fetchall():
            phones = db.loads(c["phones"], [])
            wa = db.loads(c["whatsapp"], [])
            p2, w2 = merge_phones([], phones), merge_whatsapp([], wa)
            if len(p2) != len(phones) or len(w2) != len(wa):
                fixed["phones"] += len(phones) - len(p2)
                fixed["whatsapp"] += len(wa) - len(w2)
                conn.execute("UPDATE companies SET phones=?, whatsapp=? WHERE id=?", (json.dumps(p2), json.dumps(w2), c["id"]))
        seen: set[tuple] = set()
        for j in conn.execute("SELECT * FROM jobs WHERE active=1 ORDER BY company_id, id").fetchall():
            sig = (j["company_id"],) + tuple((j[k] or "").strip().lower() for k in
                                             ("title", "location", "type", "salary", "equity", "experience", "visa"))
            if sig in seen:
                conn.execute("UPDATE jobs SET active=0 WHERE id=?", (j["id"],))
                fixed["jobs"] += 1
            else:
                seen.add(sig)
    return fixed
