"""CYD QR-source client — the shared bench display (ESP32 + ST7796, cyd-qr
line protocol over the CH340 UART).

Extracted from gm65-scanner's rig.py (2026-09-11 DRY audit): the class and
the winning render configuration were duplicated verbatim into micronuts'
harness; now tollgate-lab owns them and every Amperstrand QR rig imports
this module.

Blessed usage:

    from tollgate_lab.cyd_qr import CydQrClient, arm_winning_config

    cyd = CydQrClient(str(cyd_port()))
    arm_winning_config(cyd)                 # inverted + ECC-H
    modules, px = cyd.show_qr(payload)      # 224px cap

The winning configuration is bench-measured (gm65-scanner matrix
2026-09-10): INVERTED polarity + ECC-H + 224px cap is the only setup that
decodes reliably on the GM65+ST7796 rig.
"""

from __future__ import annotations

import time

import serial

#: Bench-measured winning QR cap (pixels) — see module docstring.
QR_WINNING_CAP = 224


class CydError(RuntimeError):
    """CYD line-protocol failure (no reply, stuck toggle, bad render)."""


class CydQrClient:
    """Line-protocol client for the cyd-qr firmware (CH340 UART0).

    Commands: ID, INV, ECCH, QRS <cap> <hex>, QR <hex>, CLR.
    """

    def __init__(self, port: str, timeout: float = 8.0):
        self.ser = serial.Serial(port, 115200, timeout=timeout)
        self.ser.reset_input_buffer()

    def close(self):
        self.ser.close()

    def _cmd(self, line: str) -> str:
        self.ser.reset_input_buffer()
        self.ser.write(line.encode() + b"\n")
        self.ser.flush()
        reply = self.ser.readline().decode(errors="replace").strip()
        if not reply:
            raise CydError(f"CYD no reply to {line!r}")
        return reply

    def id(self) -> str:
        return self._cmd("ID")

    def set_inverted(self, target: bool) -> None:
        """Film-negative rendering (white modules on black) — the proven
        decodable polarity on this GM65+ST7796 rig (matrix experiment
        2026-09-10: only INV cells decoded)."""
        for _ in range(2):
            r = self._cmd("INV")
            if (target and r == "INVERTED 1") or (not target and r == "INVERTED 0"):
                return
        raise CydError(f"INV toggle stuck at {r!r}")

    def set_ecch(self, target: bool) -> None:
        for _ in range(2):
            r = self._cmd("ECCH")
            if (target and r == "ECC HIGH") or (not target and r == "ECC MEDIUM"):
                return
        raise CydError(f"ECCH toggle stuck at {r!r}")

    def show_qr_capped(self, payload: bytes, cap: int) -> tuple[int, int]:
        reply = self._cmd(f"QRS {cap} " + payload.hex())
        parts = reply.split()
        if len(parts) != 4 or parts[0] != "RENDERED":
            raise CydError(f"CYD QR render failed: {reply!r} (payload {payload[:20]!r})")
        return int(parts[1]), int(parts[2])

    def show_qr(self, payload: bytes) -> tuple[int, int]:
        return self.show_qr_capped(payload, QR_WINNING_CAP)

    def clear(self) -> None:
        reply = self._cmd("CLR")
        if reply != "CLEARED":
            raise CydError(f"CYD clear failed: {reply!r}")


def arm_winning_config(cyd: CydQrClient) -> None:
    """Apply the bench-winning render configuration (inverted + ECC-H)."""
    cyd.set_inverted(True)
    cyd.set_ecch(True)


def cyd_replies_ok(cyd: CydQrClient, settle_s: float = 2.0) -> bool:
    """Post-flash liveness probe: the CH340 enumerates before the firmware
    answers; poll ID briefly."""
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            return bool(cyd.id())
        except (CydError, serial.SerialException, OSError):
            time.sleep(settle_s)
    return False
