"""Deep research agent: Gemini + Google Search grounding, then strict verification.

Step 1  Gemini searches the web for funding rounds, published contact details,
        traction and news. Every grounded sentence gets its real source URL.
Step 2  A second, tool-free call turns the notes into a strict JSON schema.
Step 3  We verify: every email must literally appear on the page it was cited
        from (we fetch that page ourselves). Funding, highlights and news must
        point at a source Gemini actually used, or at a page that loads.
        Anything that fails is dropped.
"""
from __future__ import annotations

import re
from datetime import date

from .. import ai, http
from .website import EMAIL_RE, emails_on_page

SYSTEM = """You are a meticulous startup research analyst building a contact and funding database of recent Y Combinator companies. Today is {today}.

Rules:
- Report only facts you found in a source during this session. Every fact needs the exact URL it came from.
- Never guess or construct an email address, phone number or funding amount. If you can't find it, say it wasn't found.
- Prefer primary sources: the company's site, founders' own pages, YC's site, TechCrunch / press releases, Crunchbase news, the founders' X/LinkedIn posts.
- The YC standard deal ($500K) is already known. Look for rounds beyond it (pre-seed, seed, Series A), with amount, date and lead investors.
- Be efficient: a few targeted searches. Open the company website and its YC page when useful.
- Write each fact on its own line and end it with the page URL it came from."""

TASK = """Research this company and write concise notes.

Company: {name} ({batch})
Website: {website}
One-liner: {one_liner}
Description: {description}
Founders: {founders}
Already known emails: {known}

Find:
1. Funding: every announced round (amount, round type, date, lead investors) with source URL. Total raised if stated.
2. Contact: email addresses published for the company or its founders (with the exact page URL where each appears). Any officially published phone or WhatsApp number.
3. Signal: 2-4 notable facts (customers, traction, revenue, launches, notable hires, prior exits) with sources.
4. Recent news (last 12 months): title, URL, date.

Write the notes as a short bulleted list, one fact per bullet, each ending with its source URL."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "total_raised", "funding_rounds", "emails", "phones", "highlights", "news"],
    "properties": {
        "summary": {"type": "string", "description": "2-3 sentence plain description of what the company does and for whom."},
        "total_raised": {"type": ["string", "null"], "description": "Total announced funding incl. YC, e.g. '$3.5M'. null if no round beyond YC was found."},
        "funding_rounds": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["round", "amount", "date", "investors", "source_url"],
                "properties": {
                    "round": {"type": "string"},
                    "amount": {"type": ["string", "null"]},
                    "date": {"type": ["string", "null"]},
                    "investors": {"type": "array", "items": {"type": "string"}},
                    "source_url": {"type": "string"},
                },
            },
        },
        "emails": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["email", "person", "source_url"],
                "properties": {
                    "email": {"type": "string"},
                    "person": {"type": ["string", "null"], "description": "Full name if the address belongs to a person, else null."},
                    "source_url": {"type": "string"},
                },
            },
        },
        "phones": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["number", "is_whatsapp", "source_url"],
                "properties": {
                    "number": {"type": "string"},
                    "is_whatsapp": {"type": "boolean"},
                    "source_url": {"type": "string"},
                },
            },
        },
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["fact", "source_url"],
                "properties": {"fact": {"type": "string"}, "source_url": {"type": "string"}},
            },
        },
        "news": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "url", "date"],
                "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "date": {"type": ["string", "null"]}},
            },
        },
    },
}

EXTRACT_SYSTEM = (
    "You convert research notes into JSON. Copy facts exactly as written in the notes. "
    "Include an item only if the notes give a source URL for it. Never add information that is not in the notes."
)


def research_company(company: dict, founders: list[dict], known_emails: list[str]) -> dict:
    founders_txt = "; ".join(
        f"{f['name']} ({f.get('title') or 'Founder'})"
        + (f", LinkedIn {f['linkedin_url']}" if f.get("linkedin_url") else "")
        for f in founders
    ) or "unknown"
    prompt = TASK.format(
        name=company["name"],
        batch=company.get("batch") or "",
        website=company.get("website") or "unknown",
        one_liner=company.get("one_liner") or "",
        description=(company.get("description") or "")[:1500],
        founders=founders_txt,
        known=", ".join(known_emails) or "none",
    )
    notes, citations = ai.research(system=SYSTEM.format(today=date.today().isoformat()), prompt=prompt)
    if not notes:
        raise ai.AIError("Research returned no notes.")

    data = ai.structured(
        system=EXTRACT_SYSTEM,
        prompt=f"Company: {company['name']}\n\nResearch notes:\n{notes}\n\nCited URLs:\n" + "\n".join(citations),
        schema=SCHEMA,
    )
    data["emails"] = _verify_emails(data.get("emails") or [], company.get("domain"))
    data["phones"] = [p for p in data.get("phones") or [] if _valid_url(p.get("source_url")) and re.search(r"\d{7,}", re.sub(r"\D", "", p.get("number", "")))]
    ok = _SourceCheck(citations)
    data["funding_rounds"] = [r for r in data.get("funding_rounds") or [] if ok(r.get("source_url")) and not _is_yc_only(r)]
    data["highlights"] = [h for h in data.get("highlights") or [] if ok(h.get("source_url"))]
    data["news"] = [n for n in data.get("news") or [] if ok(n.get("url"))]
    data["phones"] = [ph for ph in data["phones"] if ok(ph.get("source_url"))]
    if not data["funding_rounds"]:
        data["total_raised"] = None
    data["notes"] = notes
    data["sources"] = citations
    return data


_YC = ("y combinator", "ycombinator", "yc")


def _is_yc_only(r: dict) -> bool:
    """The YC batch itself is already known (standard deal); keep only rounds beyond it."""
    investors = [i.lower().strip() for i in r.get("investors") or [] if i.strip()]
    name = (r.get("round") or "").lower()
    yc_investors = not investors or all(i in _YC or "combinator" in i for i in investors)
    return yc_investors and ("combinator" in name or name.startswith("yc") or "batch" in name or "accelerator" in name)


def _norm(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip()).rstrip("/").lower()


class _SourceCheck:
    """A source is accepted if Gemini actually used it, or if the page loads."""

    def __init__(self, citations: list[str]):
        self.cited = {_norm(u) for u in citations}
        self.seen: dict[str, bool] = {}

    def __call__(self, url: str | None) -> bool:
        if not _valid_url(url):
            return False
        key = _norm(url)
        if key in self.cited:
            return True
        if key not in self.seen:
            try:
                r = http.get(url, retries=0, timeout=12)
                self.seen[key] = r.status_code < 400
            except Exception:
                self.seen[key] = False
        return self.seen[key]


def _valid_url(url: str | None) -> bool:
    return bool(url) and url.startswith(("http://", "https://"))


def _verify_emails(items: list[dict], domain: str | None) -> list[dict]:
    """Keep an email only if it literally appears on its cited page."""
    verified: list[dict] = []
    page_cache: dict[str, set[str]] = {}
    for item in items:
        email = (item.get("email") or "").strip().lower()
        url = item.get("source_url")
        if not EMAIL_RE.fullmatch(email) or not _valid_url(url):
            continue
        if url not in page_cache:
            try:
                r = http.get(url, retries=1, timeout=15)
                page_cache[url] = emails_on_page(r.text, str(r.url)) if r.status_code < 400 else set()
            except Exception:
                page_cache[url] = set()
        if email in page_cache[url]:
            verified.append({**item, "email": email})
    return verified
