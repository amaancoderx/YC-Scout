"""Email intelligence.

Confidence levels, from strongest to weakest:
  verified  - published by the company or found in a cited public source
  inferred  - built from the company's own observed address format
              (e.g. we found jane.doe@acme.com, so john.smith@acme.com)
  likely    - first@domain on a small team with a working mail server; this is
              how the overwhelming majority of early YC founders are reachable
  guess     - another common format; kept as an alternate, never primary
"""
from __future__ import annotations

import re
import threading
import unicodedata
from functools import lru_cache

import dns.exception
import dns.resolver

GENERIC_LOCALS = {
    "hello", "hi", "hey", "info", "contact", "team", "founders", "founder", "support", "help", "sales",
    "careers", "jobs", "hiring", "recruiting", "talent", "press", "media", "pr", "partnerships",
    "partners", "bd", "business", "admin", "office", "inquiries", "enquiries", "general", "privacy",
    "legal", "security", "abuse", "billing", "accounts", "ops", "investors", "ir", "feedback",
    "community", "marketing", "noreply", "no-reply", "dpo", "compliance", "care", "customers", "success",
}
GENERIC_LOCALS |= {"news", "newsletter", "superadmin", "webmaster", "hr", "people", "inbox", "mail", "orders", "service", "notifications", "updates", "demo", "events"}
PERSONAL_PROVIDERS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com", "icloud.com", "me.com", "proton.me", "protonmail.com", "hey.com", "fastmail.com", "aol.com"}
# Mailboxes that are never a person and never worth emailing for outreach.
NON_OUTREACH = {"privacy", "legal", "security", "abuse", "billing", "noreply", "no-reply", "dpo", "compliance", "accounts"}

LABELS = {
    "hello": "General", "hi": "General", "hey": "General", "info": "General", "contact": "General",
    "general": "General", "team": "Team", "founders": "Founders", "founder": "Founders",
    "careers": "Careers", "jobs": "Careers", "hiring": "Careers", "recruiting": "Careers", "talent": "Careers",
    "sales": "Sales", "support": "Support", "help": "Support", "press": "Press", "media": "Press", "pr": "Press",
    "partnerships": "Partnerships", "partners": "Partnerships", "bd": "Partnerships", "investors": "Investors",
}

PATTERNS = {
    "first": lambda f, l: f,
    "first.last": lambda f, l: f"{f}.{l}" if l else None,
    "firstlast": lambda f, l: f"{f}{l}" if l else None,
    "flast": lambda f, l: f"{f[0]}{l}" if l else None,
    "f.last": lambda f, l: f"{f[0]}.{l}" if l else None,
    "firstl": lambda f, l: f"{f}{l[0]}" if l else None,
    "first_last": lambda f, l: f"{f}_{l}" if l else None,
    "last": lambda f, l: l or None,
}

_resolver_lock = threading.Lock()


def ascii_slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def split_name(full: str) -> tuple[str, str]:
    """Return (first, last) as display strings."""
    clean = re.sub(r"\(.*?\)|\".*?\"", " ", full)
    clean = re.sub(r"\b(Dr|Mr|Ms|Mrs|PhD|MD|Jr|Sr|II|III)\.?\b", " ", clean, flags=re.I)
    parts = [p for p in re.split(r"\s+", clean.strip()) if p]
    if not parts:
        return full.strip(), ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def classify(email: str, founders: list[dict]) -> tuple[str, str | None, int | None]:
    """Return (kind, label, founder_id) for an address found in the wild."""
    local = email.split("@")[0].lower()
    if local in GENERIC_LOCALS:
        return "company", LABELS.get(local, local.capitalize()), None
    for f in founders:
        first, last = ascii_slug(f.get("first_name") or ""), ascii_slug(f.get("last_name") or "")
        if not first:
            continue
        if detect_pattern(local, first, last):
            return "founder", None, f.get("id")
    return "person", None, None


def detect_pattern(local: str, first: str, last: str) -> str | None:
    local = re.sub(r"[^a-z._]", "", local.lower())
    for name, build in PATTERNS.items():
        try:
            candidate = build(first, last)
        except IndexError:
            candidate = None
        if candidate and candidate == local:
            return name
    return None


@lru_cache(maxsize=4096)
def has_mx(domain: str) -> bool | None:
    """True if the domain accepts mail. None if DNS could not answer."""
    if not domain:
        return False
    with _resolver_lock:
        resolver = dns.resolver.Resolver()
    resolver.lifetime = 6.0
    resolver.timeout = 3.0
    try:
        answers = resolver.resolve(domain, "MX")
        return any(str(r.exchange).strip(".") for r in answers)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        # No MX: RFC 5321 falls back to the A record, but in practice startups
        # without MX don't receive mail. Treat as no.
        return False
    except (dns.exception.Timeout, dns.resolver.LifetimeTimeout):
        return None
    except Exception:
        return None


def founder_candidates(
    founder: dict,
    domain: str,
    team_size: int | None,
    observed_pattern: str | None,
) -> list[tuple[str, str]]:
    """Ranked [(email, confidence)] for a founder at a domain (max 3)."""
    first = ascii_slug(founder.get("first_name") or "")
    last = ascii_slug(founder.get("last_name") or "")
    if not first or not domain:
        return []
    out: list[tuple[str, str]] = []

    def add(pattern: str, confidence: str) -> None:
        local = PATTERNS[pattern](first, last)
        if local:
            email = f"{local}@{domain}"
            if email not in {e for e, _ in out}:
                out.append((email, confidence))

    if observed_pattern:
        add(observed_pattern, "inferred")
    small = team_size is None or team_size <= 15
    add("first", "likely" if small else "guess")
    add("first.last", "guess")
    add("flast", "guess")
    return out[:3]


def observed_pattern(found_emails: list[str], founders: list[dict], domain: str) -> str | None:
    """Infer the company's naming format from addresses tied to known people."""
    counts: dict[str, int] = {}
    for email in found_emails:
        local, _, dom = email.partition("@")
        if dom != domain:
            continue
        for f in founders:
            pat = detect_pattern(local, ascii_slug(f.get("first_name") or ""), ascii_slug(f.get("last_name") or ""))
            if pat:
                counts[pat] = counts.get(pat, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)
