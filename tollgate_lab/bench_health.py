"""Bench health check-in/check-out (B29, 2026-09-13).

Shared-bench hardware is a commons — every session that acquires the rig
runs a health probe BEFORE test work (check-in) and again when done
(check-out). A degraded bench is named in session notes, never silently
absorbed. GM65 wedge classification and the recovery matrix live in
gm65-scanner's AGENTS.md (the module-lore owner).

Usage (any Amperstrand project that touches the QR rig):

    from tollgate_lab.bench_health import bench_health_report

    report = bench_health_report()
    print(report.summary())          # human-readable
    if report.degraded:
        # name the degradation in session notes; classify before healing
        ...

The probe is read-only: CYD ID, GM65 scanner status, disk headroom.
Non-destructive by design — it must be safe to run at any time.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path


@dataclasses.dataclass
class BenchHealth:
    cyd_ok: bool = False
    cyd_detail: str = ""
    gm65_ok: bool = False
    gm65_detail: str = ""
    disk_ok: bool = False
    disk_detail: str = ""

    @property
    def degraded(self) -> bool:
        return not (self.cyd_ok and self.gm65_ok)

    def summary(self) -> str:
        lines = []
        lines.append(f"CYD: {'OK' if self.cyd_ok else 'DEGRADED'} {self.cyd_detail}")
        lines.append(f"GM65: {'OK' if self.gm65_ok else 'DEGRADED'} {self.gm65_detail}")
        if not self.disk_ok:
            lines.append(f"DISK: LOW {self.disk_detail}")
        return "\n".join(lines)


def bench_health_report(cyd_port: Path | None = None) -> BenchHealth:
    """Probe CYD + GM65 (via the F469 wallet CDC) + disk headroom."""
    report = BenchHealth()

    # CYD: answers ID?
    try:
        from tollgate_lab.cyd_qr import CydQrClient
        port = str(cyd_port or Path("/dev/ttyUSB0"))
        cyd = CydQrClient(port, timeout=4.0)
        report.cyd_detail = cyd.id()
        report.cyd_ok = report.cyd_detail.startswith("CYDQR")
        cyd.close()
    except Exception as e:
        report.cyd_detail = f"no reply ({e})"

    # GM65: F469 wallet CDC ScannerStatus
    try:
        import sys
        sys.path.insert(0, "/home/ubuntu/src/micronuts/tools/hil")
        import rig as mn_rig
        port = mn_rig.wait_wallet_cdc(timeout=30.0)
        cdc = mn_rig.cdc_with_retries(port, attempts=3, settle_s=3.0)
        status = cdc.scanner_status()
        cdc.close()
        report.gm65_ok = status.get("connected") == 1
        report.gm65_detail = str(status)
    except Exception as e:
        report.gm65_detail = f"probe failed ({e})"

    # Disk: >5 GB free
    try:
        import shutil
        free_gb = shutil.disk_usage("/").free / 1e9
        report.disk_ok = free_gb > 5.0
        report.disk_detail = f"{free_gb:.1f} GB free"
    except Exception:
        report.disk_detail = "unknown"

    return report
