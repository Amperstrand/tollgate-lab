"""Disk hygiene for the bench host: keep debug artifacts from filling the disk.

The 2026-09-11 incident: the shared cargo target dir
(``~/.cargo-target``, one dir for every Amperstrand Rust project via the
global config) grew a 29 GB ``debug/`` tree and /tmp/opencode held 11 GB of
dead session artifacts — the box hit ENOSPC mid-flash and every build
failed confusingly ("No space left on device" buried in rustc noise).

``ensure_run_headroom()`` is the pre-run hook: a no-op while free space is
above the threshold, and a conservative pruner below it.

Safety rules (multi-session host — playbook multi-session-coordination):
- NEVER prune while cargo/rustc/ldproxy processes are running (deleting
  artifacts under a live build corrupts it).
- /tmp/opencode entries are pruned only when their newest file is older
  than ``max_age_days`` — an actively-writing session keeps mtimes fresh.
- Removals are rebuildable caches only; nothing under $HOME/src is touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MIN_FREE_GB = 20.0
DEFAULT_MAX_AGE_DAYS = 7
CARGO_TARGET = Path.home() / ".cargo-target"
OPENCACHE_TMP = Path("/tmp/opencode")
_BUILD_PROCESSES = ("cargo", "rustc", "ldproxy", "probe-rs")


@dataclass
class HygieneReport:
    min_free_gb: float
    free_before_gb: float
    free_after_gb: float
    acted: bool = False
    actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.free_after_gb >= self.min_free_gb


def disk_headroom_gb(path: str | Path = "/") -> float:
    usage = shutil.disk_usage(str(path))
    return usage.free / (1000**3)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def build_processes_running() -> bool:
    """True while any cargo/rustc/ldproxy/probe-rs process is alive."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", *list(_BUILD_PROCESSES)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True  # cannot tell — assume busy, refuse to prune
    return result.returncode == 0


def _newest_mtime(path: Path) -> float:
    """Newest FILE mtime under `path` (directory mtimes change on create/
    delete, so a stray touch must not keep a dead session "live")."""
    newest = 0.0
    for p in path.rglob("*"):
        try:
            if p.is_file() and not p.is_symlink():
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            continue
    return newest if newest else path.stat().st_mtime


def prune_cargo_debug(target_dir: Path = CARGO_TARGET, force: bool = False) -> str | None:
    """Remove the rebuildable ``debug/`` tree under the shared cargo target.

    Returns an action description, or None when nothing was done. Refuses
    while build processes run unless ``force``.
    """
    debug_dir = target_dir / "debug"
    if not debug_dir.exists():
        return None
    if not force and build_processes_running():
        return "skipped: cargo/rustc running (debug/ left in place)"
    shutil.rmtree(debug_dir, ignore_errors=True)
    return f"removed {target_dir}/debug (rebuildable host artifacts)"


def prune_tmp_opencode(
    base: Path = OPENCACHE_TMP, max_age_days: int = DEFAULT_MAX_AGE_DAYS
) -> str | None:
    """Drop /tmp/opencode session dirs whose newest file is stale."""
    if not base.exists():
        return None
    cutoff = time.time() - max_age_days * 86400
    removed = []
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        try:
            if _newest_mtime(entry) < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(entry.name)
        except OSError:
            continue
    if not removed:
        return None
    return f"removed {len(removed)} stale /tmp/opencode dirs (> {max_age_days}d idle)"


def ensure_run_headroom(
    min_free_gb: float = DEFAULT_MIN_FREE_GB,
    cargo_target: Path = CARGO_TARGET,
    opentmp: Path = OPENCACHE_TMP,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> HygieneReport:
    """The pre-run hook. No-op with headroom; conservative prunes without.

    Call once at bench-harness entry (before flashing/building), e.g. right
    after taking the bench lock. Never raises — disk hygiene must not kill
    a run; the report says what happened.
    """
    before = disk_headroom_gb()
    report = HygieneReport(min_free_gb=min_free_gb, free_before_gb=before, free_after_gb=before)
    if before >= min_free_gb:
        return report

    for step in (
        lambda: prune_cargo_debug(cargo_target),
        lambda: prune_tmp_opencode(opentmp, max_age_days),
    ):
        try:
            action = step()
        except OSError:
            action = None
        if action:
            report.acted = True
            report.actions.append(action)
            report.free_after_gb = disk_headroom_gb()
            if report.free_after_gb >= min_free_gb:
                break
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--min-free", type=float, default=DEFAULT_MIN_FREE_GB,
                    help="target free space in GB (default %(default)s)")
    ap.add_argument("--force", action="store_true",
                    help="prune even while build processes run")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="print the report as JSON")
    args = ap.parse_args(argv)

    if args.force:
        report = HygieneReport(
            min_free_gb=args.min_free,
            free_before_gb=disk_headroom_gb(),
            free_after_gb=disk_headroom_gb(),
        )
        for step in (lambda: prune_cargo_debug(force=True), prune_tmp_opencode):
            action = step()
            if action:
                report.acted = True
                report.actions.append(action)
        report.free_after_gb = disk_headroom_gb()
    else:
        report = ensure_run_headroom(min_free_gb=args.min_free)

    if args.as_json:
        print(json.dumps(report.__dict__))
    else:
        state = "OK" if report.ok else "LOW"
        print(f"disk hygiene [{state}] free {report.free_before_gb:.1f} -> "
              f"{report.free_after_gb:.1f} GB (min {report.min_free_gb:.0f})")
        for action in report.actions:
            print(f"  - {action}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
