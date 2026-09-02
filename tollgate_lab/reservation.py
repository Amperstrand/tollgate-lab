"""Cross-project board reservations — the coordination layer for the
Amperstrand benches (microfips, tollgate, bolty-rs, gm65, ...).

Problem this solves: each project's test framework used its OWN lock file
inside its own checkout, so a microfips bench run and a bolty-rs HIL run
could both grab the same board. Reservations here live in ONE shared
location and carry owner/project/TTL, so any project — and any machine on
the lab network — can see and respect them.

Storage: a reservation directory (default ``~/bench-reservations``,
override with ``BENCH_RESERVATION_DIR``). On a single machine the
directory is naturally shared; for multi-machine benches point every
machine at the same directory (lab NFS/sync) or run the directory on the
coordinator host and mount it.

Contract:
- ``reserve(serial, project, ttl_secs)`` writes ``<serial>.json`` with
  owner, project, pid, host, and expiry. Refuses if a LIVE reservation
  by a DIFFERENT project exists.
- ``release(serial, project)`` removes it (only the holder may release).
- ``status()`` lists all live reservations — the "who is using what"
  view for agents and humans.
- Expired reservations (past TTL) are ignored and reclaimable: a crashed
  session cannot wedge the bench longer than its TTL.

The boards.toml safety contract (which hardware exists and what ops are
allowed) is ORTHOGONAL: fips-lab's ``require_board`` gates what may be
flashed; this module gates WHEN. Use both.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESERVATION_DIR = Path(
    os.environ.get("BENCH_RESERVATION_DIR", "~/bench-reservations")
).expanduser()


def _now() -> float:
    return time.time()


def _expired(entry: dict, now: float) -> bool:
    exp = entry.get("expires_at")
    return not isinstance(exp, (int, float)) or exp <= now


class ReservationError(RuntimeError):
    """The board is reserved by someone else (or the request is invalid)."""


def reserve(
    serial: str,
    project: str,
    ttl_secs: int = 3600,
    reservation_dir: Path | None = None,
    note: str = "",
) -> dict:
    """Reserve a board exclusively for `project`. Returns the entry.

    Raises ReservationError if a live reservation by another project
    exists. TTL bounds the damage of a crashed session: the reservation
    expires and the board becomes reclaimable even if the holder dies.
    """
    if not serial or not project:
        raise ReservationError("serial and project are required")

    rdir = Path(reservation_dir) if reservation_dir else DEFAULT_RESERVATION_DIR
    rdir.mkdir(parents=True, exist_ok=True)
    path = rdir / f"{serial}.json"

    now = _now()
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = None
        if existing and not _expired(existing, now):
            holder = existing.get("project", "?")
            if holder == project:
                # Same project re-reserving: refresh and return.
                entry = _write(path, serial, project, ttl_secs, now, note)
                return entry
            raise ReservationError(
                f"board {serial} is reserved for project {holder!r} "
                f"(owner {existing.get('owner', '?')}, "
                f"expires in {int(existing['expires_at'] - now)}s) — refusing"
            )
        # Expired entry: reclaimable.

    entry = {
        "serial": serial,
        "project": project,
        "owner": os.getenv("USER", "unknown"),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "note": note,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "acquired_at": now,
        "expires_at": now + ttl_secs,
    }
    fd, tmp = tempfile.mkstemp(dir=str(rdir), prefix=f".{serial}-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return entry


def release(serial: str, project: str, reservation_dir: Path | None = None) -> bool:
    """Release a reservation. Only the holding project may release."""
    rdir = Path(reservation_dir) if reservation_dir else DEFAULT_RESERVATION_DIR
    path = rdir / f"{serial}.json"
    if not path.exists():
        return False
    try:
        entry = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        path.unlink(missing_ok=True)
        return True
    if entry.get("project") != project:
        raise ReservationError(
            f"board {serial} is reserved for project "
            f"{entry.get('project', '?')!r} — {project!r} cannot release it"
        )
    path.unlink(missing_ok=True)
    return True


def status(reservation_dir: Path | None = None) -> dict[str, dict]:
    """All reservations, keyed by serial. Expired entries are pruned and
    marked ``expired: true`` in the returned dicts (still visible — agents
    and humans should see recently-expired holds when diagnosing)."""
    rdir = Path(reservation_dir) if reservation_dir else DEFAULT_RESERVATION_DIR
    out: dict[str, dict] = {}
    if not rdir.is_dir():
        return out
    now = _now()
    for path in sorted(rdir.glob("*.json")):
        try:
            entry = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        serial = entry.get("serial", path.stem)
        entry["expired"] = _expired(entry, now)
        out[serial] = entry
    return out


def reclaim_if_expired(serial: str, project: str, reservation_dir: Path | None = None) -> bool:
    """Take over an EXPIRED reservation held by another project."""
    rdir = Path(reservation_dir) if reservation_dir else DEFAULT_RESERVATION_DIR
    path = rdir / f"{serial}.json"
    if not path.exists():
        return False
    try:
        entry = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if entry.get("project") == project:
        return False
    return _expired(entry, time.time())


def _write(path: Path, serial: str, project: str, ttl_secs: int, now: float, note: str) -> dict:
    entry = {
        "serial": serial,
        "project": project,
        "owner": os.getenv("USER", "unknown"),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "note": note,
        "refreshed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "acquired_at": now,
        "expires_at": now + ttl_secs,
    }
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{serial}-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entry, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return entry


class BoardReservation:
    """Context manager: reserve on enter, release on exit.

    Example:
        with BoardReservation("F4:12:FA:CF:03:84", "microfips", ttl_secs=600):
            run_scenarios()
    """

    def __init__(
        self,
        serial: str,
        project: str,
        ttl_secs: int = 3600,
        reservation_dir: Path | None = None,
        note: str = "",
    ):
        self.serial = serial
        self.project = project
        self.ttl_secs = ttl_secs
        self.reservation_dir = reservation_dir
        self.note = note
        self.entry: dict | None = None

    def __enter__(self) -> dict:
        self.entry = reserve(
            self.serial, self.project, self.ttl_secs,
            self.reservation_dir, self.note,
        )
        return self.entry

    def __exit__(self, *exc):
        release(self.serial, self.project, self.reservation_dir)
        return False
