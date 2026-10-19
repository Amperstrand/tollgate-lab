"""pcscd coupling domain — reader sessions vs usb/pcscd disturbances.

Bench incident class (bolty-rs lessons B32, 2026-10-19): labgrid places
model per-place hardware exclusivity, but pcscd couples every reader
session on the host with any session that disturbs USB or restarts pcscd
(stick flashing observed re-enumerating the stick and cycling pcscd —
each restart aborts in-flight CCID exchanges bench-wide, the exact
mid-exchange abort that wedges ACR1252 readers).

This lock models that coupling explicitly with one advisory flock and
two roles:

* ``reader`` — LOCK_SH: reader sessions (ACR/CardMan/pcscd consumers)
  coexist with each other;
* ``disturbance`` — LOCK_EX: stick flashing, USB replugging, pcscd
  restarts — excludes readers AND other disturbances.

Order discipline (AB-BA avoidance): take BenchLock FIRST, then any
project locks, THEN this domain lock — never the reverse. Disturbance
holders write holder info into the lock file (single EX writer); readers
are visible via the session registry / journal events instead of the
file (multiple SH writers would garble it).
"""

from __future__ import annotations

import fcntl
import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path

from ..session_registry import bench_event

PCSCD_DOMAIN_PATH = Path("/tmp/amperstrand-pcscd-domain.lock")


@dataclass
class PcscdDomainHeldError(RuntimeError):
    holder: dict[str, str]

    def __str__(self) -> str:  # pragma: no cover - message only
        return (
            f"pcscd domain is held by a {self.holder.get('role', '?')} "
            f"({self.holder.get('project', '?')}, pid "
            f"{self.holder.get('pid', '?')}, since "
            f"{self.holder.get('since', '?')}) — readers and usb/pcscd "
            "disturbances are mutually exclusive (B32)"
        )


def _holder(role: str, project: str, reason: str) -> dict[str, str]:
    return {
        "role": role,
        "session": f"{os.getenv('USER', 'unknown')}@{platform.node()}",
        "pid": str(os.getpid()),
        "project": project or "-",
        "reason": reason or "-",
        "since": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def _read_holder(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        for line in path.read_text().splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                data[key.strip()] = val.strip()
    except OSError:
        pass
    return data


def _acquire(
    role: str,
    project: str,
    reason: str,
    timeout_s: float,
    path: Path | None,
) -> PcscdDomainLock:
    lock_path = path or PCSCD_DOMAIN_PATH
    how = fcntl.LOCK_SH if role == "reader" else fcntl.LOCK_EX
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fcntl.flock(fd, how | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                raise PcscdDomainHeldError(holder=_read_holder(lock_path)) from None
            time.sleep(0.5)

    holder = _holder(role, project, reason)
    if role == "disturbance":
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, "\n".join(f"{k}: {v}" for k, v in holder.items()).encode())
    bench_event(
        "pcscd-domain",
        f"{role} acquired (project={project or '-'}, reason={reason or '-'})",
    )
    return PcscdDomainLock(fd=fd, path=lock_path, holder=holder)


def acquire_pcscd_reader(
    project: str = "",
    reason: str = "",
    timeout_s: float = 0.0,
    path: Path | None = None,
) -> PcscdDomainLock:
    """Shared reader role — coexists with other readers, blocked while a
    disturbance holds the domain."""
    return _acquire("reader", project, reason, timeout_s, path)


def acquire_pcscd_disturbance(
    project: str = "",
    reason: str = "",
    timeout_s: float = 0.0,
    path: Path | None = None,
) -> PcscdDomainLock:
    """Exclusive disturbance role — stick flashing, USB replug, pcscd
    restart. Waits out readers (poll up to timeout_s), then holds the
    domain alone."""
    return _acquire("disturbance", project, reason, timeout_s, path)


class PcscdDomainLock:
    """Held pcscd-domain flock. release() on exit; also a context manager."""

    def __init__(self, fd: int, path: Path, holder: dict[str, str]):
        self.fd = fd
        self.path = path
        self.holder = holder

    def release(self) -> None:
        if self.fd >= 0:
            bench_event(
                "pcscd-domain",
                f"released (project={self.holder.get('project', '-')})",
            )
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = -1

    def __enter__(self) -> PcscdDomainLock:
        return self

    def __exit__(self, *exc) -> None:
        self.release()
