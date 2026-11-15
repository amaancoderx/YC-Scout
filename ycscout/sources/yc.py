"""Y Combinator data.

Two sources, both public:
  * yc-oss API (https://github.com/yc-oss/api) - a daily mirror of YC's company
    directory. Gives the batch roster and core company facts.
  * The YC company page (ycombinator.com/companies/<slug>) - embeds the same
    JSON the page renders: founders, job postings, news and launch posts.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .. import http

YC_OSS = "https://yc-oss.github.io/api"
YC_BASE = "https://www.ycombinator.com"

_DATA_PAGE = re.compile(r'data-page="([^"]+)"')
_SEASON_ORDER = {"winter": 1, "spring": 2, "summer": 3, "fall": 4}


@dataclass
class Batch:
    slug: str
    name: str
    count: int

    @property
    def sort_key(self) -> tuple[int, int]:
        season, _, year = self.slug.partition("-")
        try:
            return int(year), _SEASON_ORDER.get(season, 0)
        except ValueError:
            return 0, 0


@dataclass
class CompanyPage:
    company: dict
    founders: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    news: list[dict] = field(default_factory=list)
    launch: dict | None = None


def list_batches() -> list[Batch]:
    """All batches, newest first."""
    meta = http.get_json(f"{YC_OSS}/meta.json")
    batches = [
        Batch(slug=slug, name=info.get("name", slug), count=int(info.get("count", 0)))
        for slug, info in (meta.get("batches") or {}).items()
        if re.fullmatch(r"(winter|spring|summer|fall)-\d{4}", slug)
    ]
    batches.sort(key=lambda b: b.sort_key, reverse=True)
    return batches


def recent_batches(n: int = 3, min_count: int = 20) -> list[Batch]:
    """The n most recent batches that are actually populated.

    YC lists a few early-admit companies under future batches; those batches are
    skipped until they have a meaningful roster.
    """
    return [b for b in list_batches() if b.count >= min_count][:n]


def batch_companies(batch_slug: str) -> list[dict]:
    resp = http.get(f"{YC_OSS}/batches/{batch_slug}.json")
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    return json.loads(resp.content.decode("utf-8"))


def company_page(slug: str) -> CompanyPage | None:
    resp = http.get(f"{YC_BASE}/companies/{slug}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    match = _DATA_PAGE.search(resp.text)
    if not match:
        raise ValueError(f"YC page format changed for {slug}: no data-page payload")
    props = json.loads(html.unescape(match.group(1))).get("props", {})
    company = props.get("company") or {}

    founders = []
    for f in company.get("founders") or []:
        name = (f.get("full_name") or "").strip()
        if not name:
            continue
        founders.append({
            "yc_user_id": f.get("user_id"),
            "name": name,
            "title": (f.get("title") or "").strip(),
            "bio": (f.get("founder_bio") or "").strip(),
            "linkedin_url": _clean_url(f.get("linkedin_url")),
            "twitter_url": _clean_url(f.get("twitter_url")),
            # Avatar URLs are signed and expire after an hour; don't store them.
            "avatar_url": None,
            "is_active": 1 if f.get("is_active", True) else 0,
        })

    jobs = []
    for j in props.get("jobPostings") or []:
        jobs.append({
            "id": j.get("id"),
            "title": j.get("title"),
            "url": _abs(j.get("url")),
            "apply_url": _abs(j.get("url")),  # public job page has the apply button
            "location": j.get("location"),
            "type": j.get("type"),
            "role": j.get("prettyRole") or j.get("role"),
            "salary": j.get("salaryRange"),
            "equity": j.get("equityRange"),
            "experience": j.get("minExperience"),
            "visa": j.get("visa"),
            "posted": j.get("createdAt"),
        })

    news = [
        {"title": n.get("title"), "url": n.get("url"), "date": n.get("date")}
        for n in props.get("newsItems") or []
        if n.get("url")
    ]

    launch = None
    launches = props.get("launches") or []
    if launches:
        l0 = launches[0]
        launch = {"title": l0.get("title"), "url": l0.get("url") or l0.get("ycdc_launch_url")}

    return CompanyPage(company=company, founders=founders, jobs=jobs, news=news, launch=launch)


def normalize_company(raw: dict, batch_slug: str) -> dict:
    """Map a yc-oss record to our `companies` columns."""
    website = _clean_url(raw.get("website"))
    launched = raw.get("launched_at")
    return {
        "id": raw["id"],
        "slug": raw["slug"],
        "name": raw.get("name") or raw["slug"],
        "batch": raw.get("batch"),
        "batch_slug": batch_slug,
        "one_liner": (raw.get("one_liner") or "").strip(),
        "description": (raw.get("long_description") or "").replace("\r\n", "\n").strip(),
        "website": website,
        "domain": domain_of(website),
        "location": raw.get("all_locations"),
        "team_size": raw.get("team_size"),
        "industry": raw.get("industry"),
        "subindustry": raw.get("subindustry"),
        "tags": json.dumps(raw.get("tags") or []),
        "yc_status": raw.get("status"),
        "is_hiring": 1 if raw.get("isHiring") else 0,
        "yc_partner": raw.get("partners"),
        "yc_url": raw.get("url") or f"{YC_BASE}/companies/{raw['slug']}",
        "logo_url": raw.get("small_logo_thumb_url"),
        "launched_at": (
            datetime.fromtimestamp(launched, tz=timezone.utc).strftime("%Y-%m-%d")
            if isinstance(launched, (int, float)) else None
        ),
    }


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = re.sub(r"^https?://", "", url.strip(), flags=re.I).split("/")[0].split("?")[0].lower()
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host or None


def _abs(path: str | None) -> str | None:
    if not path:
        return None
    return path if path.startswith("http") else f"{YC_BASE}{path}"


def _clean_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url:
        return None
    if not re.match(r"^https?://", url, flags=re.I):
        url = "https://" + url
    return url
