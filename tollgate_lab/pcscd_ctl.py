"""pcscd-ctl — coordinated pcscd restarts and status.

B32 (bolty-rs lessons, 2026-10-19): a naked ``systemctl restart pcscd``
aborts every in-flight CCID exchange bench-wide — the mid-exchange abort
class that wedges ACR1252 readers. All pcscd restarts on this bench go
through here: take the pcscd-domain disturbance lock (waits out reader
sessions), restart, wait for the daemon to answer PC/SC again, journal
the event. ``status`` answers "is pcscd alive and how many readers" plus
the last journal lines.

Exit codes: 0 healthy/stable, 2 unstable, 3 lock contention (passed
through from the domain lock).
"""

from __future__ import annotations

import argparse
import subprocess
import time

from .hardware.pcscd_domain import acquire_pcscd_disturbance
from .session_registry import bench_event, journal_tail


def pcscd_stable() -> tuple[bool, str]:
    """One PC/SC round-trip (establish + list readers). Falls back to
    systemctl is-active when pyscard is absent (host CI)."""
    try:
        from smartcard.scard import (
            SCARD_SCOPE_USER,
            SCardEstablishContext,
            SCardGetErrorMessage,
            SCardListReaders,
            SCardReleaseContext,
        )
    except ImportError:
        r = subprocess.run(
            ["systemctl", "is-active", "pcscd"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        active = (r.stdout or "").strip() == "active"
        return active, f"systemctl is-active: {(r.stdout or '').strip() or '?'}"

    rc, ctx = SCardEstablishContext(SCARD_SCOPE_USER)
    if rc != 0:
        return False, f"establish: {SCardGetErrorMessage(rc)}"
    rc, readers = SCardListReaders(ctx, [])
    detail = (
        f"{len(list(readers or []))} readers listed"
        if rc == 0
        else f"list: {SCardGetErrorMessage(rc)}"
    )
    SCardReleaseContext(ctx)
    return rc == 0, detail


def systemctl_restart_pcscd() -> int:
    r = subprocess.run(
        ["systemctl", "restart", "pcscd"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    return r.returncode


def _shares_lane_token(project: str, place: str) -> bool:
    """True when project and place names share a lane-meaningful token
    (split on - _ ., tokens >= 3 chars — 'rs'/'hp' class noise ignored)."""
    pt = {t for t in project.replace("_", "-").replace(".", "-").split("-") if len(t) >= 3}
    st = {t for t in place.replace("_", "-").replace(".", "-").split("-") if len(t) >= 3}
    return bool(pt & st)


def _labgrid_other_holders(project: str) -> list[str]:
    """Places currently acquired by OTHER lanes (labgrid-client who).

    #525 (ccid-firmware-rs): pcscd restarts disturb every lane whose
    readers live on this host. The flock serializes restarts but cannot
    see dependencies — labgrid place ownership is the bench's real
    dependency currency, so a restart is denied while any OTHER lane
    holds a place. Output is the named holder rows (empty = clear).
    Fail-open ONLY if labgrid itself is unreachable (its coordinator
    being down must not add a second outage on top).

    Format = the ACTUAL `labgrid-client who` table (verified live
    2026-10-31; Codex P1 on tollgate-lab#26 caught the first parser
    matching a format that does not exist):
        User    Host        Place       Changed
        root    ai-legion   some-place  2026-10-31 11:45:52
    A row is OURS when the project tag matches the Place name (place
    names are the lane currency, e.g. 'ccid-bench' for project
    ccid-firmware-rs); everything else is another lane's dependency.
    """
    try:
        r = subprocess.run(
            ["labgrid-client", "who"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    others: list[str] = []
    for line in r.stdout.splitlines():
        if not line.strip() or line.lstrip().startswith("User "):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        place = parts[2]
        # Own-lane exemption: project tags and place names share tokens
        # rather than substrings ('ccid-firmware-rs' owns 'ccid-bench').
        if project and _shares_lane_token(project, place):
            continue
        others.append(line.rstrip())
    return others


def restart(
    project: str = "",
    reason: str = "",
    wait_readers_s: float = 0.0,
    stable_timeout_s: float = 20.0,
) -> dict[str, object]:
    """Disturbance-locked pcscd restart. Waits out reader sessions (up to
    wait_readers_s), restarts, then waits for PC/SC to answer again."""
    others = _labgrid_other_holders(project)
    if others:
        bench_event(
            "pcscd-restart-denied",
            f"project={project or '-'} holders={'; '.join(others)}",
        )
        return {
            "systemctl_rc": -1,
            "stable": False,
            "detail": "DENIED: other lanes hold labgrid places: "
                      + "; ".join(others),
        }
    lock = acquire_pcscd_disturbance(
        project=project,
        reason=reason,
        timeout_s=wait_readers_s,
    )
    try:
        bench_event("pcscd-restart", f"project={project or '-'} reason={reason or '-'}")
        rc = systemctl_restart_pcscd()
        stable, detail = False, "not probed"
        deadline = time.monotonic() + stable_timeout_s
        while time.monotonic() < deadline:
            time.sleep(1.0)
            stable, detail = pcscd_stable()
            if stable:
                break
        bench_event(
            "pcscd-restart-done" if stable else "pcscd-restart-unstable",
            f"systemctl_rc={rc} {detail}",
        )
        return {"systemctl_rc": rc, "stable": stable, "detail": detail}
    finally:
        lock.release()


def status() -> dict[str, object]:
    stable, detail = pcscd_stable()
    return {
        "stable": stable,
        "detail": detail,
        "journal": journal_tail(8),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pcscd-ctl",
        description="Coordinated pcscd restart/status (B32 disturbance lock)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_restart = sub.add_parser("restart", help="disturbance-locked restart")
    p_restart.add_argument("--project", default="", help="lane/project name")
    p_restart.add_argument("--reason", default="", help="why (journaled)")
    p_restart.add_argument(
        "--wait-readers-s",
        type=float,
        default=0.0,
        help="how long to wait for reader sessions to finish",
    )
    sub.add_parser("status", help="probe + last journal lines")
    args = parser.parse_args(argv)

    if args.cmd == "restart":
        out = restart(
            project=args.project,
            reason=args.reason,
            wait_readers_s=args.wait_readers_s,
        )
        print(f"stable={out['stable']} rc={out['systemctl_rc']} {out['detail']}")
        return 0 if out["stable"] else 2
    st = status()
    print(f"stable={st['stable']} {st['detail']}")
    for line in st["journal"]:
        print(line)
    return 0 if st["stable"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
