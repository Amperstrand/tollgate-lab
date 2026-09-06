"""Cross-session registry — who is doing what on this bench host right now.

The bench stack already has exclusivity (``hardware.bench_lock.BenchLock``
— same-user cross-session flock), scheduling (``reservation.BoardReservation``
— WHEN a board may be used, with TTL), and state visibility (labgrid place
tags via fips-lab's ``note_board_state``). What it lacked — proven painful
on 2026-09-06, when two agent sessions shared one bench and long test runs
died silently to another session's process hygiene — is a SESSION layer:

* every long-running agent session announces itself, the resources it
  touches, and its live child PIDs;
* ``sessions_status()`` answers "who is doing what right now" before
  anyone starts work;
* process hygiene can kill exactly the REGISTERED PIDs instead of
  pattern-matching the whole process table (the ``pkill -f`` class of
  blue-on-blue kills);
* a session that dies without cleanup is DETECTED (LOST) and journaled,
  so the next session at least notices, instead of inheriting a silent
  mess.

Storage: one JSON file per session under the reservation dir (default
``~/bench-reservations/sessions/``) plus an append-only ``sessions/journal.log``.
Liveness is the session file's flock, held by the registering process and
kernel-released when it dies — a running-marked record whose flock is free
is a LOST session. No daemon, no cleanup jobs: same design posture as
BenchLock.

Composability: sessions do not serialize anything (locks do that) — they
make the actors VISIBLE. Take BenchLock / reservations as before; the
session record is the human- and agent-readable story of who holds them.
"""

from __future__ import annotations

import fcntl
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

SESSIONS_DIR = Path(
    os.environ.get("BENCH_RESERVATION_DIR", "~/bench-reservations")
    if os.environ.get("BENCH_RESERVATION_DIR")
    else "~/bench-reservations"
).expanduser() / "sessions"

JOURNAL = SESSIONS_DIR / "journal.log"

#: A running-marked session whose flock went away without an `end` event
#: is LOST. Records older than this are pruned from status regardless.
MAX_RECORD_AGE_SECS = 7 * 24 * 3600


def _journal(event: str, record: dict[str, Any], detail: str = "") -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    line = " ".join(
        [
            time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            event,
            f"{record.get('session', '?')}/{record.get('pid', '?')}",
            f"project={record.get('project', '-')}",
            detail,
        ]
    ).rstrip()
    with JOURNAL.open("a") as f:
        f.write(line + "\n")


class Session:
    """One announced session. Holds its file's flock for its lifetime."""

    def __init__(self, path: Path, record: dict[str, Any], fd: int):
        self.path = path
        self.record = record
        self._fd = fd

    def note(self, key: str, value: Any) -> None:
        """Record a resource claim other sessions should respect (a port,
        a target dir, a board serial, a tmux session name, ...)."""
        self.record.setdefault("resources", {})[key] = value
        self._flush()

    def add_pid(self, pid: int, what: str = "") -> None:
        """Register a long-lived child (test run, tap, daemon...) so hygiene
        tools can kill exactly these instead of pattern-matching."""
        self.record.setdefault("pids", []).append({"pid": pid, "what": what})
        self._flush()

    def end(self, status: str = "done") -> None:
        self.record["status"] = status
        self.record["ended"] = time.time()
        self._flush()
        _journal("end", self.record)
        os.close(self._fd)  # releases the flock

    def _flush(self) -> None:
        self.path.write_text(json.dumps(self.record, indent=2))


def session_begin(
    name: str, project: str, note_text: str = ""
) -> Session:
    """Announce a session. Cheap, never blocks, never fails closed — a
    registry outage must not block bench work (best-effort visibility)."""
    record = {
        "session": name,
        "owner": f"{os.getenv('USER', 'unknown')}@{platform.node()}",
        "pid": os.getpid(),
        "project": project,
        "note": note_text,
        "started": time.time(),
        "status": "running",
        "resources": {},
        "pids": [],
        "cmdline": _cmdline(os.getpid()),
    }
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{name}-{os.getpid()}-{int(time.time())}.json"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    session = Session(path, record, fd)
    session._flush()
    _journal("begin", record, note_text)
    return session


def sessions_status() -> list[dict[str, Any]]:
    """All live/recent session records, LOST ones flagged. The pre-work
    view: run this (or `python3 -m tollgate_lab.session_registry status`)
    before starting bench or device work."""
    records: list[dict[str, Any]] = []
    if not SESSIONS_DIR.exists():
        return records
    for path in sorted(SESSIONS_DIR.glob("*.json")):
        try:
            record = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if time.time() - record.get("started", 0) > MAX_RECORD_AGE_SECS:
            path.unlink(missing_ok=True)
            continue
        if record.get("status") == "running" and not _flock_held(path):
            record["status"] = "LOST"
            _journal("lost", record, "died without end()")
        records.append(record)
    return records


def journal_tail(lines: int = 40) -> list[str]:
    if not JOURNAL.exists():
        return []
    return JOURNAL.read_text().splitlines()[-lines:]


def _flock_held(path: Path) -> bool:
    """True if some live process still holds the session file's flock."""
    try:
        fd = os.open(path, os.O_RDWR)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except BlockingIOError:
        return True
    finally:
        os.close(fd)


def _cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(
            b"\0", b" "
        ).decode(errors="replace")[:200]
    except OSError:
        return "-"


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command", choices=("status", "journal"), help="what to show"
    )
    args = parser.parse_args()
    if args.command == "journal":
        for line in journal_tail():
            print(line)
        return 0
    records = sessions_status()
    if not records:
        print("no sessions recorded")
        return 0
    for record in records:
        age_h = (time.time() - record.get("started", 0)) / 3600
        print(
            f"{record.get('status', '?'):7} {age_h:5.1f}h "
            f"{record.get('session', '?')} (pid {record.get('pid', '?')}, "
            f"project {record.get('project', '?')}): "
            f"{record.get('note', '') or '-'}"
        )
        for key, value in (record.get("resources") or {}).items():
            print(f"         resource {key}={value}")
        for entry in record.get("pids") or []:
            print(
                f"         pid {entry.get('pid')} {entry.get('what', '')}".rstrip()
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
