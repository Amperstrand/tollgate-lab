"""Cross-project bench exclusivity via a kernel-enforced flock.

HardwareLock (hardware.lock) is same-user-permissive by design — it scopes
multi-USER access on one host and does not serialize two sessions of the
SAME user. But "blue on blue" interference is exactly that case: two agent
sessions (same unix user) driving one bench collided twice within 20
minutes on 2026-09-03 (lab-daemon port bind + shared cargo target/ race —
microfips #199). The labgrid place acquire covers only labgrid-aware
callers; the hil flock covers only hil.

BenchLock is the shared primitive all Amperstrand bench harnesses take
FIRST: an advisory flock on a fixed path. Kernel-enforced for same-user
concurrent processes, released automatically when the holding process
dies (no stale-lock cleanup), and its file content names the holder for
humans ("who holds the bench" without parsing process tables).
"""

from __future__ import annotations

import fcntl
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

BENCH_LOCK_PATH = Path("/tmp/amperstrand-bench.lock")


@dataclass
class BenchLockHeldError(RuntimeError):
    holder: dict[str, str]

    def __str__(self) -> str:  # pragma: no cover - message only
        return (
            f"bench is held by {self.holder.get('session', '?')} "
            f"(pid {self.holder.get('pid', '?')}, project "
            f"{self.holder.get('project', '?')}, since "
            f"{self.holder.get('since', '?')}) — flocks release when the "
            "holder dies; if this persists, check that pid first"
        )


def read_bench_lock(path: Path | None = None) -> dict[str, str]:
    """Holder info from a lock file's content (advisory — the flock is the
    truth; content identifies the holder for humans)."""
    data: dict[str, str] = {}
    try:
        for line in (path or BENCH_LOCK_PATH).read_text().splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                data[key.strip()] = val.strip()
    except OSError:
        pass
    return data


def _session_id() -> str:
    return f"{os.getenv('USER', 'unknown')}@{platform.node()}"


def _git_branch(cwd: str | None) -> str:
    if not cwd:
        return "-"
    try:
        out = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        return out.stdout.strip() or "-" if out.returncode == 0 else "-"
    except (OSError, subprocess.TimeoutExpired):
        return "-"


def acquire_bench_lock(
    name: str = "amperstrand-bench",
    timeout_s: float = 0.0,
    project: str = "",
    cwd: str | None = None,
) -> BenchLock:
    """Take the cross-project bench flock. Non-blocking by default
    (timeout_s=0 raises immediately if held); a positive timeout polls.
    Order discipline for composite locking: BenchLock FIRST, then any
    legacy/project locks — never the reverse (AB-BA avoidance)."""
    path = Path(f"/tmp/{name}.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise BenchLockHeldError(holder=read_bench_lock(path)) from None
            time.sleep(0.5)

    holder = {
        "session": _session_id(),
        "pid": str(os.getpid()),
        "project": project or "-",
        "branch": _git_branch(cwd),
        "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, "\n".join(f"{k}: {v}" for k, v in holder.items()).encode())
    return BenchLock(fd=fd, path=path, name=name, holder=holder)


class BenchLock:
    """Held bench flock. release() on exit; also a context manager."""

    def __init__(self, fd: int, path: Path, name: str, holder: dict[str, str]):
        self.fd = fd
        self.path = path
        self.name = name
        self.holder = holder

    def release(self) -> None:
        if self.fd >= 0:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = -1

    def __enter__(self) -> BenchLock:
        return self

    def __exit__(self, *args) -> None:
        self.release()
