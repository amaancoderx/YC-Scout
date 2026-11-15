"""YC Scout command line.

  python scout.py serve                     Open the dashboard (default)
  python scout.py batches                   List YC batches
  python scout.py sync [slug ...]           Pull + enrich batches (default: 2 newest)
        --research                          ...and run AI deep research
        --force                             ...re-scrape fresh companies too
  python scout.py research <slug|all>       AI research for a batch
  python scout.py export                    Write an Excel workbook to data/exports
  python scout.py sheet                     Push everything to Google Sheets
  python scout.py replies                   Check the inbox for replies / bounces
  python scout.py push-db                   Copy local data/ycscout.db into the Turso cloud database
  python scout.py gmail-auth                Connect Gmail for sending over HTTPS (Gmail API)

Sync is safe to schedule (Windows Task Scheduler / cron): it only re-scrapes
companies older than 2 days and never sends email.
"""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from ycscout import config, db, export, jobs, outreach, pipeline
from ycscout.sources import yc


def _run_blocking(kind: str, label: str, fn) -> None:
    """Run a job in the foreground and stream its log to the terminal."""
    done = threading.Event()
    printed = 0

    def wrapped(run):
        try:
            return fn(run)
        finally:
            done.set()

    run_id = jobs.start(kind, label, {"cli": True}, wrapped)
    try:
        while True:
            finished = done.wait(1.0)
            row = db.one("SELECT log, status, summary FROM runs WHERE id=?", (run_id,))
            lines = (row["log"] or "").splitlines()
            for line in lines[printed:]:
                print(line, flush=True)
            printed = len(lines)
            if finished and row["status"] != "running":
                print(f"\n{row['status'].upper()}: {row['summary'] or ''}")
                break
    except KeyboardInterrupt:
        jobs.cancel(run_id)
        print("\nCancelling…")
        done.wait(30)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="scout", description="YC Scout")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("serve")
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("batches")
    sy = sub.add_parser("sync")
    sy.add_argument("batches", nargs="*")
    sy.add_argument("--research", action="store_true")
    sy.add_argument("--force", action="store_true")
    sy.add_argument("--no-crawl", action="store_true")
    r = sub.add_parser("research")
    r.add_argument("target")
    r.add_argument("--force", action="store_true", help="re-research companies that were already researched")
    sub.add_parser("export")
    sub.add_parser("sheet")
    sub.add_parser("replies")
    sub.add_parser("push-db")
    sub.add_parser("gmail-auth")
    args = p.parse_args(argv)

    if args.cmd == "gmail-auth":
        from ycscout import gmail_auth
        token = gmail_auth.run()
        print("Gmail connected. Saved GMAIL_REFRESH_TOKEN to .env.")
        print("On Render, add it as an environment variable:")
        print("GMAIL_REFRESH_TOKEN=" + token)
        return 0
    if args.cmd == "push-db":
        if not db.remote():
            print("Set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN in .env first (see DEPLOY.md).")
            return 1
        local = config.DATA_DIR / "ycscout.db"
        print(f"Copying {local} to {config.TURSO_DATABASE_URL} ...")
        counts = db.push_local_to_remote(local)
        print("Done:", ", ".join(f"{k} {v}" for k, v in counts.items()))
        return 0
    db.init()

    if args.cmd in (None, "serve"):
        import uvicorn
        url = f"http://{config.HOST}:{config.PORT}"
        print(f"YC Scout running at {url}  (Ctrl+C to stop)")
        if not getattr(args, "no_browser", False):
            threading.Timer(1.2, lambda: webbrowser.open(url)).start()
        uvicorn.run("ycscout.web.app:app", host=config.HOST, port=config.PORT, log_level="warning")
        return 0

    if args.cmd == "batches":
        for b in yc.list_batches()[:16]:
            loaded = db.scalar("SELECT COUNT(*) FROM companies WHERE batch_slug=?", (b.slug,))
            print(f"{b.slug:<14} {b.name:<14} {b.count:>4} companies   {loaded:>4} loaded")
        return 0

    if args.cmd == "sync":
        slugs = args.batches or [b.slug for b in yc.recent_batches(2)]
        if args.research and not config.ai_enabled():
            print("--research needs GEMINI_API_KEY in .env")
            return 1
        _run_blocking("sync", f"Sync {', '.join(slugs)}", lambda run: pipeline.sync_batches(
            run, slugs, crawl=not args.no_crawl, research=args.research, force=args.force))
        return 0

    if args.cmd == "research":
        if not config.ai_enabled():
            print("Research needs GEMINI_API_KEY in .env")
            return 1
        sql = "SELECT id FROM companies" + ("" if args.target == "all" else " WHERE batch_slug=?")
        ids = [r["id"] for r in db.query(sql, () if args.target == "all" else (args.target,))]
        _run_blocking("research", f"Research {len(ids)} companies", lambda run: pipeline.research_job(run, ids, force=args.force))
        return 0

    if args.cmd == "export":
        print(export.save_xlsx())
        return 0
    if args.cmd == "sheet":
        print(export.sync_google_sheet())
        return 0
    if args.cmd == "replies":
        print(outreach.check_replies())
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
