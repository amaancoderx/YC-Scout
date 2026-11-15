"""Exports: Excel workbook, CSV and Google Sheets - all built from one table model."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config, db

CONF_ORDER = {"verified": 0, "inferred": 1, "likely": 2, "guess": 3}


def _company_where(company_ids: list[int] | None) -> tuple[str, list]:
    if not company_ids:
        return "", []
    return f" WHERE c.id IN ({','.join('?' * len(company_ids))})", list(company_ids)


def build_tables(company_ids: list[int] | None = None) -> dict[str, tuple[list[str], list[list]]]:
    where, params = _company_where(company_ids)
    companies = db.query(f"SELECT c.* FROM companies c{where} ORDER BY COALESCE(c.fit_score, -1) DESC, c.batch_slug DESC, c.name", params)
    ids = [c["id"] for c in companies]
    if not ids:
        ids = [-1]
    ph = ",".join("?" * len(ids))
    founders = db.query(f"SELECT * FROM founders WHERE company_id IN ({ph}) AND is_active=1 ORDER BY id", ids)
    contacts = db.query(f"SELECT * FROM contacts WHERE company_id IN ({ph})", ids)
    jobs = db.query(f"SELECT * FROM jobs WHERE company_id IN ({ph}) AND active=1 ORDER BY id", ids)
    outreach = db.query(f"SELECT * FROM outreach WHERE company_id IN ({ph}) ORDER BY id", ids)

    by_company: dict[int, dict[str, list]] = {c["id"]: {"f": [], "ct": [], "j": [], "o": []} for c in companies}
    for f in founders:
        by_company.get(f["company_id"], {}).setdefault("f", []).append(f)
    for ct in contacts:
        by_company.get(ct["company_id"], {}).setdefault("ct", []).append(ct)
    for j in jobs:
        by_company.get(j["company_id"], {}).setdefault("j", []).append(j)
    for o in outreach:
        by_company.get(o["company_id"], {}).setdefault("o", []).append(o)
    names = {c["id"]: c["name"] for c in companies}
    batches = {c["id"]: c["batch"] for c in companies}

    def best(cts: list[dict], fid: int) -> tuple[dict | None, list[dict]]:
        mine = sorted([c for c in cts if c["founder_id"] == fid],
                      key=lambda c: (CONF_ORDER.get(c["confidence"], 9), -c["is_primary"]))
        return (mine[0] if mine else None), mine[1:]

    c_head = ["Company", "Batch", "Fit score", "Why it fits", "One-liner", "Description", "Website", "Location", "Team size", "Industry", "Tags",
              "Raised", "Funding detail", "Funding source", "Hiring", "Open roles", "Remote roles", "Job links", "Founders",
              "Founder emails", "Company emails", "Phones", "WhatsApp", "Booking link", "LinkedIn", "X / Twitter",
              "Launch post", "YC page", "Stage", "Last contacted", "Notes", "Updated"]
    c_rows = []
    for c in companies:
        g = by_company[c["id"]]
        f_emails = []
        for f in g["f"]:
            b, _ = best(g["ct"], f["id"])
            if b:
                f_emails.append(f"{f['name']}: {b['email']} ({b['confidence']})")
        co_emails = [ct["email"] for ct in g["ct"] if ct["kind"] == "company"]
        phones = [p["number"] for p in db.loads(c["phones"], [])]
        wa = [w.get("number") or w.get("link") for w in db.loads(c["whatsapp"], [])]
        other = db.loads(c["other_links"], {})
        sent = [o["sent_at"] for o in g["o"] if o["sent_at"]]
        c_rows.append([
            c["name"], c["batch"], c["fit_score"], "\n".join(db.loads(c["fit_reasons"], [])), c["one_liner"], c["summary"], c["website"], c["location"], c["team_size"],
            c["industry"], ", ".join(db.loads(c["tags"], [])), c["funding_total"], c["funding_detail"],
            "Researched (cited)" if c["funding_source"] == "researched" else "YC standard deal",
            "Yes" if c["is_hiring"] or g["j"] else "No", len(g["j"]), sum(1 for j in g["j"] if _remote(j)),
            "\n".join(f"{j['title']}: {j['url']}" for j in g["j"]),
            "\n".join(f"{f['name']} ({f['title'] or 'Founder'})" for f in g["f"]),
            "\n".join(f_emails), "\n".join(co_emails), "\n".join(phones), "\n".join(w for w in wa if w),
            other.get("calendly", ""), c["linkedin_url"], c["twitter_url"], c["launch_url"], c["yc_url"],
            c["stage"], max(sent) if sent else "", c["notes"], c["updated_at"],
        ])

    f_head = ["Company", "Batch", "Founder", "Title", "Best email", "Confidence", "Alternates", "LinkedIn", "X / Twitter", "Bio"]
    f_rows = []
    for f in founders:
        cts = by_company.get(f["company_id"], {}).get("ct", [])
        b, alts = best(cts, f["id"])
        f_rows.append([names.get(f["company_id"]), batches.get(f["company_id"]), f["name"], f["title"],
                       b["email"] if b else "", b["confidence"] if b else "",
                       ", ".join(a["email"] for a in alts), f["linkedin_url"], f["twitter_url"], f["bio"]])

    founder_names = {f["id"]: f["name"] for f in founders}
    e_head = ["Company", "Email", "Type", "Person", "Confidence", "Source", "Found on", "Mail server OK", "Primary"]
    e_rows = [[names.get(ct["company_id"]), ct["email"], ct["kind"], founder_names.get(ct["founder_id"], ct["label"] or ""),
               ct["confidence"], ct["source"], ct["source_url"] or "",
               {1: "Yes", 0: "No"}.get(ct["mx_ok"], "Unknown"), "Yes" if ct["is_primary"] else ""]
              for ct in sorted(contacts, key=lambda x: (names.get(x["company_id"], ""), CONF_ORDER.get(x["confidence"], 9)))]

    j_head = ["Company", "Batch", "Title", "Role", "Location", "Remote", "Type", "Salary", "Equity", "Experience", "Visa", "Posted", "Link"]
    j_rows = [[names.get(j["company_id"]), batches.get(j["company_id"]), j["title"], j["role"], j["location"], "Yes" if _remote(j) else "No", j["type"],
               j["salary"], j["equity"], j["experience"], j["visa"], j["posted"], j["url"]] for j in jobs]

    o_head = ["Company", "To", "Name", "Step", "Status", "Subject", "Sent at", "Replied at", "Error"]
    o_rows = [[names.get(o["company_id"]), o["to_email"], o["to_name"], o["step"], o["status"], o["subject"],
               o["sent_at"], o["replied_at"], o["error"]] for o in outreach]

    return {
        "Companies": (c_head, c_rows),
        "Founders": (f_head, f_rows),
        "Emails": (e_head, e_rows),
        "Jobs": (j_head, j_rows),
        "Outreach": (o_head, o_rows),
    }


WIDTHS = {"Description": 60, "One-liner": 40, "Job links": 50, "Founders": 32, "Founder emails": 44, "Bio": 70,
          "Company emails": 30, "Funding detail": 40, "Subject": 40, "Tags": 30, "Notes": 30}


def to_xlsx(company_ids: list[int] | None = None) -> bytes:
    tables = build_tables(company_ids)
    wb = Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill("solid", fgColor="111827")
    for name, (head, rows) in tables.items():
        ws = wb.create_sheet(name)
        ws.append(head)
        for r in rows:
            ws.append([_cell(v) for v in r])
        for i, h in enumerate(head, start=1):
            cell = ws.cell(row=1, column=i)
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = header_fill
            cell.alignment = Alignment(vertical="center")
            ws.column_dimensions[get_column_letter(i)].width = WIDTHS.get(h, max(12, min(28, len(h) + 6)))
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                if isinstance(cell.value, str) and cell.value.startswith("http") and "\n" not in cell.value:
                    cell.hyperlink = cell.value
                    cell.font = Font(color="2563EB", underline="single")
        ws.freeze_panes = "B2"
        if rows:
            ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_csv(company_ids: list[int] | None = None, table: str = "Companies") -> bytes:
    head, rows = build_tables(company_ids)[table]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    for r in rows:
        w.writerow([_cell(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel opens UTF-8 correctly


def save_xlsx() -> str:
    path = config.EXPORT_DIR / f"yc-scout-{datetime.now().strftime('%Y%m%d-%H%M')}.xlsx"
    path.write_bytes(to_xlsx())
    return str(path)


def sync_google_sheet() -> str:
    if not config.sheets_enabled():
        raise RuntimeError("Google Sheets is not configured (GOOGLE_SERVICE_ACCOUNT_FILE and GOOGLE_SHEET_ID).")
    import gspread

    gc = gspread.service_account(filename=config.GOOGLE_SERVICE_ACCOUNT_FILE)
    sh = gc.open_by_key(config.GOOGLE_SHEET_ID)
    existing = {ws.title: ws for ws in sh.worksheets()}
    for name, (head, rows) in build_tables().items():
        values = [head] + [[_cell(v) for v in r] for r in rows]
        ws = existing.get(name) or sh.add_worksheet(title=name, rows=max(100, len(values) + 10), cols=len(head) + 2)
        ws.clear()
        if ws.row_count < len(values) or ws.col_count < len(head):
            ws.resize(rows=max(ws.row_count, len(values) + 10), cols=max(ws.col_count, len(head)))
        ws.update(range_name="A1", values=values, value_input_option="RAW")
        ws.freeze(rows=1)
        ws.format("1:1", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.93, "green": 0.94, "blue": 0.96}})
    # Remove the default empty "Sheet1" if our tabs now exist.
    if "Sheet1" in existing and len(sh.worksheets()) > 1:
        try:
            sh.del_worksheet(existing["Sheet1"])
        except Exception:
            pass
    return sh.url


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, str) and len(v) > 49000:  # Sheets cell limit is 50k chars
        return v[:49000] + "…"
    return v


def _remote(job) -> bool:
    return "remote" in (job["location"] or "").lower()
