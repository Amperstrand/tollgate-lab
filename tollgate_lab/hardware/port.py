"""Serial-matched USB port resolution and per-device flash policies.

Port selection is by USB serial, NEVER by VID:PID — the Amperstrand ATOMs
share FTDI 0403:6001 with an off-limits M5 Stack on the same bench
(fips-lab registry lesson; a wrong match flashes the wrong board).
Ambiguity is always refused rather than resolved heuristically.

Measured link policies live in FLASH_POLICIES. atom-b (9D529068B4):
the FT232R only survives esptool at 115200 — the link dies at the 230400
baud switch and reads corrupt mid-transfer (2026-09-12 bench session);
writes are block-acked and reliable.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class PortError(Exception):
    """Base class for port resolution refusals."""


@dataclass(frozen=True)
class PortAbsentError(PortError):
    serial: str

    def __str__(self) -> str:
        return f"no attached device carries serial {self.serial!r}"


@dataclass(frozen=True)
class AmbiguousPortError(PortError):
    serial: str
    candidates: tuple[Path, ...]

    def __str__(self) -> str:
        return f"serial {self.serial!r} matches {len(self.candidates)} devices — refusing to pick"


@dataclass(frozen=True)
class PortMatch:
    path: Path
    serial: str


@dataclass(frozen=True)
class FlashPolicy:
    tool: str
    baud: int


DEFAULT_FLASH_POLICY = FlashPolicy(tool="esptool", baud=115_200)

# Per-serial measured link policies (see module docstring for the atom-b story).
FLASH_POLICIES: dict[str, FlashPolicy] = {
    "9D529068B4": FlashPolicy(tool="esptool", baud=115_200),
}


def policy_for(serial: str) -> FlashPolicy:
    """Return the measured flash policy for a serial, or the conservative default."""
    return FLASH_POLICIES.get(serial, DEFAULT_FLASH_POLICY)


def candidate_paths() -> list[Path]:
    """Enumerate USB-serial device paths for this platform (unknown platforms: none)."""
    if sys.platform == "darwin":
        return sorted(Path("/dev").glob("cu.usbserial-*"))
    if sys.platform == "linux":
        by_id = Path("/dev/serial/by-id")
        if by_id.is_dir():
            return sorted(p for p in by_id.glob("*") if p.is_file())
        return []
    return []


def resolve_port(serial: str, paths: Sequence[Path] | None = None) -> PortMatch:
    """Find the single device path carrying ``serial``; refuse zero or many."""
    candidates = tuple(
        p for p in (paths if paths is not None else candidate_paths()) if serial in p.name
    )
    if len(candidates) == 1:
        return PortMatch(path=candidates[0], serial=serial)
    if not candidates:
        raise PortAbsentError(serial=serial)
    raise AmbiguousPortError(serial=serial, candidates=candidates)
