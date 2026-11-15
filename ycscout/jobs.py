"""Background job runner with persistent progress and logs (the `runs` table)."""
from __future__ import annotations

import json
import threading
import traceback
from datetime import datetime
from typing import Callable

from . import db

MAX_LOG_LINES = 600

_active: dict[int, "Run"] = {}
_active_lock = threading.Lock()


class Cancelled(Exception):
    pass


class Run:
    def __init__(self, run_id: int, kind: str):
        self.id = run_id
        self.kind = kind
        self._cancel = threading.Event()
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self.done = 0
        self.total = 0

    # -- reporting ---------------------------------------------------------
    def log(self, message: str) -> None:
        line = f"{datetime.now().strftime('%H:%M:%S')}  {message}"
        with self._lock:
            self._lines.append(line)
            self._lines = self._lines[-MAX_LOG_LINES:]
            text = "\n".join(self._lines)
        db.execute("UPDATE runs SET log=? WHERE id=?", (text, self.id))

    def set_total(self, total: int) -> None:
        self.total = total
        db.execute("UPDATE runs SET total=?, progress=? WHERE id=?", (total, self.done, self.id))

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self.done += n
            done = self.done
        db.execute("UPDATE runs SET progress=? WHERE id=?", (done, self.id))

    # -- cancellation --------------------------------------------------------
    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise Cancelled()


def start(kind: str, label: str, params: dict, fn: Callable[[Run], str | None], *, exclusive: bool = True) -> int:
    """Start `fn(run)` in a thread. Returns the run id.

    With exclusive=True a second run of the same kind is refused while one is active.
    """
    with _active_lock:
        if exclusive and any(r.kind == kind for r in _active.values()):
            raise RuntimeError(f"A '{kind}' job is already running.")
        run_id = db.execute(
            "INSERT INTO runs(kind, label, params, status, started_at) VALUES (?,?,?,?,?)",
            (kind, label, json.dumps(params), "running", db.now()),
        )
        run = Run(run_id, kind)
        _active[run_id] = run

    def target() -> None:
        status, summary = "done", None
        try:
            summary = fn(run)
        except Cancelled:
            status, summary = "cancelled", "Cancelled by user"
            run.log("Cancelled.")
        except Exception as exc:  # surface every failure in the UI
            status, summary = "failed", f"{type(exc).__name__}: {exc}"
            run.log("ERROR " + summary)
            run.log(traceback.format_exc(limit=4))
        finally:
            db.execute(
                "UPDATE runs SET status=?, summary=?, finished_at=?, progress=? WHERE id=?",
                (status, summary, db.now(), run.done, run_id),
            )
            with _active_lock:
                _active.pop(run_id, None)

    threading.Thread(target=target, name=f"run-{run_id}-{kind}", daemon=True).start()
    return run_id


def cancel(run_id: int) -> bool:
    with _active_lock:
        run = _active.get(run_id)
    if run:
        run.cancel()
        return True
    return False


def is_running(kind: str) -> bool:
    with _active_lock:
        return any(r.kind == kind for r in _active.values())
