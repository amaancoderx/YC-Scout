"""How well each company fits the sender: a transparent 0-100 score with reasons.

The score is deterministic so it is free, instant and explainable:
  hiring at all                          +10
  a software / AI engineering role open  +20
  a remote role open to India/worldwide  +25   (remote limited to another country: +8)
  company based in India                 +10
  each of your strengths it matches      +10   (max 30)
  small team (<= 10)                     +5    (founders read their own inbox)

"Strengths" come from the `fit_strengths` setting (Settings > Your strengths), one
per line:  keyword, keyword, keyword => proof line used in emails.
The best-matching strength's proof line becomes the {{proof_line}} template variable.
"""
from __future__ import annotations

import json
import re

from . import db

ENG_ROLE = re.compile(
    r"\b(ai|ml|machine learning|llm|engineer|developer|full[- ]?stack|back[- ]?end|front[- ]?end|software|"
    r"technical staff|mts|swe|sde|forward deployed|fde|applied scientist|research engineer)\b", re.I)
NON_SOFTWARE = re.compile(
    r"\b(mechanical|electrical|hardware|chemical|civil|process|manufacturing|technician|structural|robotics field|"
    r"sales engineer|solutions engineer|tax|legal|cpa|nurse|clinical)\b", re.I)
REMOTE_WIDE = re.compile(r"remote(?!\s*\()|remote\s*\((in|india|worldwide|global|anywhere)\b", re.I)
REMOTE_REGION = re.compile(r"remote\s*\(([^)]*)\)", re.I)


def is_software_role(job: dict) -> bool:
    title = job.get("title") or ""
    if NON_SOFTWARE.search(title):
        return False
    role = (job.get("role") or "").lower()
    if role == "engineering":
        return True
    return bool(ENG_ROLE.search(title)) and role in ("", "science", "product")


def parse_strengths(text: str | None) -> list[dict]:
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=>" not in line:
            continue
        keys, proof = line.split("=>", 1)
        kws = [k.strip().lower() for k in keys.split(",") if k.strip()]
        if kws and proof.strip():
            out.append({"keywords": kws, "proof": proof.strip(), "label": kws[0]})
    return out


def _kw_hit(kw: str, text: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text) is not None


def score_company(company: dict, jobs: list[dict], strengths: list[dict]) -> tuple[int, list[str], str]:
    reasons: list[str] = []
    score = 0
    if jobs:
        score += 10
        reasons.append(f"Hiring ({len(jobs)} open role{'s' if len(jobs) != 1 else ''})")
        eng = [j for j in jobs if is_software_role(j)]
        if eng:
            score += 20
            reasons.append(f"Software/AI role: {eng[0]['title']}")
        # Remote counts in full only for roles you'd actually do (software/AI).
        pool = eng or jobs
        weight = 1.0 if eng else 0.3
        remote = [j for j in pool if "remote" in (j.get("location") or "").lower()]
        wide = [j for j in remote if REMOTE_WIDE.search(j.get("location") or "")]
        if wide:
            score += round(25 * weight)
            reasons.append(f"Remote role open to India/worldwide: {wide[0]['title']}")
        elif remote:
            score += round(8 * weight)
            m = REMOTE_REGION.search(remote[0].get("location") or "")
            reasons.append(f"Remote role, but limited to {m.group(1) if m else 'one region'}: {remote[0]['title']}")

    loc = (company.get("location") or "").lower()
    if "india" in loc or re.search(r",\s*in\b", loc):
        score += 10
        reasons.append(f"Based in India ({company.get('location')})")

    text = " ".join(str(company.get(k) or "") for k in ("name", "one_liner", "description", "tags", "industry", "subindustry"))
    text = text.lower()
    matched = []
    for s in strengths:
        hits = [k for k in s["keywords"] if _kw_hit(k, text)]
        if hits:
            matched.append((len(hits), s, hits))
    matched.sort(key=lambda m: -m[0])
    if matched:
        score += min(30, 10 * len(matched))
        reasons.append("Matches your work in: " + ", ".join(m[2][0] for m in matched[:4]))

    team = company.get("team_size")
    if team and team <= 10:
        score += 5
        reasons.append(f"Small team ({team}), founders likely read email")

    proof = matched[0][1]["proof"] if matched else ""
    return min(score, 100), reasons, proof


def rescore(company_ids: list[int] | None = None) -> int:
    strengths = parse_strengths(db.get_setting("fit_strengths"))
    default_proof = (db.get_setting("default_proof_line") or "").strip()
    where, params = "", []
    if company_ids:
        where = f"WHERE id IN ({','.join('?' * len(company_ids))})"
        params = list(company_ids)
    companies = db.query(f"SELECT * FROM companies {where}", params)
    jobs_by: dict[int, list[dict]] = {}
    for j in db.query("SELECT company_id, title, role, location FROM jobs WHERE active=1"):
        jobs_by.setdefault(j["company_id"], []).append(j)
    with db.tx() as conn:
        for c in companies:
            s, reasons, proof = score_company(c, jobs_by.get(c["id"], []), strengths)
            conn.execute("UPDATE companies SET fit_score=?, fit_reasons=?, fit_proof=? WHERE id=?",
                         (s, json.dumps(reasons), proof or default_proof, c["id"]))
    return len(companies)
