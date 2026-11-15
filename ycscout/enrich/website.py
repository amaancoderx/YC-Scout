"""Company website crawler.

Visits the homepage plus a handful of high-signal pages (contact, about, team,
careers, privacy/legal) and extracts only what the company itself publishes:
email addresses, phone / WhatsApp links, booking links and social profiles.
Nothing here is guessed - every value carries the URL it was found on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .. import http
from ..sources.yc import domain_of
from .emails import PERSONAL_PROVIDERS

MAX_PAGES = 7
KEY_PATHS = re.compile(
    r"(contact|about|team|company|careers|jobs|join|privacy|terms|legal|imprint|impressum|press|support|help)",
    re.I,
)
FALLBACK_PATHS = ["/contact", "/about", "/careers", "/privacy"]

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}(?![\w-])")
OBFUSCATED_RE = re.compile(
    r"\b([A-Za-z0-9._%+-]{1,64})\s*[\[\(\{]\s*at\s*[\]\)\}]\s*([A-Za-z0-9-]+)\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*([A-Za-z]{2,24})\b",
    re.I,
)
ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "avif", "ico", "css", "js", "mp4", "webm", "woff", "woff2", "ttf"}
BLOCKED_DOMAINS = {
    "example.com", "example.org", "domain.com", "email.com", "yourdomain.com", "yourcompany.com", "company.com",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "w3.org", "schema.org", "godaddy.com",
    "mysite.com", "test.com", "acme.com", "placeholder.com", "website.com", "ingest.sentry.io",
}
BLOCKED_LOCALS = {"name", "your", "you", "user", "username", "email", "yourname", "john", "jane", "johndoe", "john.doe", "jane.doe", "firstname", "first.last", "example", "test"}

SOCIAL_PATTERNS = {
    "linkedin": re.compile(r"linkedin\.com/(company|in|school)/[^/?#\s]+", re.I),
    "twitter": re.compile(r"(?:twitter|x)\.com/(?!intent|share|home|search)[A-Za-z0-9_]{1,15}/?$", re.I),
    "github": re.compile(r"github\.com/[A-Za-z0-9-]+/?$", re.I),
    "instagram": re.compile(r"instagram\.com/[A-Za-z0-9_.]+/?$", re.I),
    "youtube": re.compile(r"youtube\.com/(@|c/|channel/|user/)[^/?#\s]+", re.I),
    "discord": re.compile(r"(discord\.gg|discord\.com/invite)/[A-Za-z0-9-]+", re.I),
    "calendly": re.compile(r"(calendly\.com|cal\.com)/[A-Za-z0-9_-]+", re.I),
}


@dataclass
class CrawlResult:
    ok: bool = False
    final_url: str | None = None
    emails: dict[str, str] = field(default_factory=dict)       # email -> source url
    phones: dict[str, str] = field(default_factory=dict)       # e164-ish -> source url
    whatsapp: dict[str, dict] = field(default_factory=dict)    # number/link -> {link, source_url}
    socials: dict[str, str] = field(default_factory=dict)      # kind -> url
    pages: list[str] = field(default_factory=list)
    error: str | None = None


def crawl(website: str | None) -> CrawlResult:
    result = CrawlResult()
    if not website:
        result.error = "no website"
        return result
    company_domain = domain_of(website)
    try:
        resp = http.get(website, retries=1, timeout=15)
    except Exception as exc:  # network failures are data, not crashes
        result.error = f"unreachable: {type(exc).__name__}"
        return result
    if resp.status_code >= 400:
        result.error = f"HTTP {resp.status_code}"
        return result

    result.ok = True
    result.final_url = str(resp.url)
    site_domain = domain_of(result.final_url) or company_domain
    domains = {d for d in (company_domain, site_domain) if d}

    queue: list[str] = []
    seen: set[str] = set()

    def visit(url: str, html_text: str) -> None:
        seen.add(_norm(url))
        result.pages.append(url)
        links = _extract(html_text, url, domains, result)
        for link in links:
            if len(queue) >= MAX_PAGES * 2:
                break
            n = _norm(link)
            if n not in seen and n not in {_norm(q) for q in queue}:
                queue.append(link)

    visit(result.final_url, resp.text)
    for path in FALLBACK_PATHS:
        candidate = urljoin(result.final_url, path)
        if _norm(candidate) not in {_norm(q) for q in queue}:
            queue.append(candidate)

    while queue and len(result.pages) < MAX_PAGES:
        url = queue.pop(0)
        if _norm(url) in seen:
            continue
        seen.add(_norm(url))
        try:
            r = http.get(url, retries=0, timeout=12)
        except Exception:
            continue
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400 or "html" not in ctype:
            continue
        # Redirected off-site (e.g. careers on Ashby) - still parse, don't follow further.
        visit(str(r.url), r.text)

    return result


def emails_on_page(html_text: str, page_url: str) -> set[str]:
    """Every address on a page, including Cloudflare-protected and mailto ones."""
    result = CrawlResult()
    domains = {m.split("@")[1].lower() for m in EMAIL_RE.findall(html_text)}
    host = domain_of(page_url)
    if host:
        domains.add(host)
    _extract(html_text, page_url, domains, result)
    found = set(result.emails)
    found |= {e.lower() for e in EMAIL_RE.findall(html_text)}
    for el in BeautifulSoup(html_text, "lxml").select("[data-cfemail]"):
        decoded = _decode_cfemail(el.get("data-cfemail", ""))
        if decoded:
            found.add(decoded.lower())
    return found


def _norm(url: str) -> str:
    p = urlparse(url)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/').lower()}"


def _extract(html_text: str, page_url: str, domains: set[str], result: CrawlResult) -> list[str]:
    soup = BeautifulSoup(html_text, "lxml")
    follow: list[str] = []

    # Cloudflare email protection: <a data-cfemail="hex">
    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cfemail(el.get("data-cfemail", ""))
        if decoded:
            _add_email(decoded, page_url, domains, result, from_mailto=True)

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            addr = unquote(href[7:].split("?")[0]).strip()
            for part in addr.split(","):
                _add_email(part.strip(), page_url, domains, result, from_mailto=True)
            continue
        if low.startswith("tel:"):
            num = _normalize_phone(unquote(href[4:]))
            if num:
                result.phones.setdefault(num, page_url)
            continue
        if "wa.me/" in low or "whatsapp.com/send" in low or low.startswith("whatsapp:"):
            num = _whatsapp_number(href)
            key = num or href
            result.whatsapp.setdefault(key, {"number": num, "link": href, "source_url": page_url})
            continue
        if "chat.whatsapp.com/" in low:
            result.whatsapp.setdefault(href, {"number": None, "link": href, "source_url": page_url})
            continue

        absolute = urljoin(page_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        for kind, pattern in SOCIAL_PATTERNS.items():
            if kind not in result.socials and pattern.search(absolute.split("?")[0]):
                result.socials[kind] = absolute.split("?")[0]
        host = (parsed.netloc or "").lower().removeprefix("www.")
        if host in domains and KEY_PATHS.search(parsed.path or ""):
            if not re.search(r"\.(pdf|png|jpg|zip)$", parsed.path, re.I):
                follow.append(absolute.split("#")[0])

    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    for match in EMAIL_RE.findall(text):
        _add_email(match, page_url, domains, result, from_mailto=False)
    for local, dom, tld in OBFUSCATED_RE.findall(text):
        _add_email(f"{local}@{dom}.{tld}", page_url, domains, result, from_mailto=False)
    return follow


def _add_email(raw: str, page_url: str, domains: set[str], result: CrawlResult, *, from_mailto: bool) -> None:
    email = raw.strip().strip(".,;:()<>[]'\"").lower()
    if not EMAIL_RE.fullmatch(email):
        return
    local, _, dom = email.partition("@")
    tld = dom.rsplit(".", 1)[-1]
    if tld in ASSET_TLDS or dom in BLOCKED_DOMAINS or local in BLOCKED_LOCALS:
        return
    if re.search(r"@\d+x\.", email) or len(local) > 40:
        return
    on_domain = any(dom == d or dom.endswith("." + d) for d in domains)
    # Same brand on another TLD (site on acme.ai, mail on acme.dev).
    same_brand = _brand(dom) in {_brand(d) for d in domains}
    # Other off-domain addresses are usually customers, testimonials or vendors.
    # The exception is a deliberate mailto to a personal inbox (a founder's gmail).
    if on_domain or same_brand or (from_mailto and dom in PERSONAL_PROVIDERS):
        result.emails.setdefault(email, page_url)


_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu"}


def _brand(domain: str) -> str:
    """'mail.acme.co.uk' -> 'acme'; 'getacme.ai' -> 'getacme'."""
    parts = domain.lower().split(".")
    if len(parts) >= 3 and parts[-2] in _SECOND_LEVEL:
        return parts[-3]
    return parts[-2] if len(parts) >= 2 else domain


def _decode_cfemail(hex_str: str) -> str | None:
    try:
        key = int(hex_str[:2], 16)
        return "".join(chr(int(hex_str[i:i + 2], 16) ^ key) for i in range(2, len(hex_str), 2))
    except (ValueError, IndexError):
        return None


def _normalize_phone(raw: str) -> str | None:
    raw = raw.strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        return None
    return ("+" if plus else "") + digits


def _whatsapp_number(href: str) -> str | None:
    m = re.search(r"wa\.me/\+?(\d{7,15})", href)
    if m:
        return "+" + m.group(1)
    q = parse_qs(urlparse(href).query)
    phone = (q.get("phone") or [None])[0]
    if phone:
        digits = re.sub(r"\D", "", phone)
        if 7 <= len(digits) <= 15:
            return "+" + digits
    return None
