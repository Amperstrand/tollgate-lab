"""Post-flash telemetry gate — a flashed device must prove it booted.

The bench contract's last step: after any flash, the firmware's own
telemetry (e.g. the charger fleet's ``[tollgate] phase=...`` lines at
115200) must appear within the window, or the flash session is a failure
(a hash-verified write of a brick is still a brick).
"""

from __future__ import annotations

import re
import time
from typing import Protocol

import serial


class TelemetryGateError(Exception):
    """The firmware did not emit the required telemetry within the window."""

    def __init__(self, matched: int, min_lines: int, window_s: float) -> None:
        super().__init__(
            f"telemetry gate failed: {matched} matching lines in {window_s:.0f}s (need {min_lines})"
        )
        self.matched = matched
        self.min_lines = min_lines


class GateResult:
    """The matched telemetry lines."""

    def __init__(self, matched: tuple[str, ...]) -> None:
        self.matched = matched


class LineSource(Protocol):
    """Reads lines for ``window_s`` seconds (real: serial port; tests: fake)."""

    def read_lines(self, window_s: float) -> list[str]: ...


class FakeSource:
    """Deterministic in-memory line source for tests."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def read_lines(self, window_s: float) -> list[str]:
        del window_s  # deterministic source ignores the window
        return self._lines


class SerialLineSource:
    """115200 baud serial line source (the fleet's bench telemetry rate)."""

    def __init__(self, port: str) -> None:
        self._port = port

    def read_lines(self, window_s: float) -> list[str]:
        lines: list[str] = []
        with serial.Serial(self._port, 115_200, timeout=1) as ser:
            ser.reset_input_buffer()
            buf = b""
            deadline = time.monotonic() + window_s
            while time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        if line.strip():
                            lines.append(line.decode(errors="replace").strip())
        return lines


def assert_telemetry(
    source: LineSource, pattern: re.Pattern[str], min_lines: int, window_s: float
) -> GateResult:
    """Assert the source emits ``min_lines`` pattern-matching lines within ``window_s``."""
    matched = tuple(ln for ln in source.read_lines(window_s) if pattern.search(ln))
    if len(matched) < min_lines:
        raise TelemetryGateError(matched=len(matched), min_lines=min_lines, window_s=window_s)
    return GateResult(matched=matched)
