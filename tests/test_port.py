"""Serial-matched port resolution — never VID:PID, refuse ambiguity."""

from __future__ import annotations

from pathlib import Path

import pytest

from tollgate_lab.hardware.port import (
    AmbiguousPortError,
    PortAbsentError,
    policy_for,
    resolve_port,
)

ATOM_B = "9D529068B4"


def test_resolve_port_when_serial_suffix_matches() -> None:
    paths = [
        Path("/dev/cu.usbserial-9D529068B4"),
        Path("/dev/cu.usbserial-2"),
        Path("/dev/cu.Bluetooth-Incoming-Port"),
    ]
    match = resolve_port(ATOM_B, paths)
    assert match.path == Path("/dev/cu.usbserial-9D529068B4")
    assert match.serial == ATOM_B


def test_resolve_port_when_serial_absent() -> None:
    with pytest.raises(PortAbsentError):
        resolve_port(ATOM_B, [Path("/dev/cu.usbserial-2")])


def test_resolve_port_when_multiple_matches() -> None:
    paths = [Path("/dev/cu.usbserial-9D529068B4"), Path("/dev/cu.usbmodem-9D529068B4-1")]
    with pytest.raises(AmbiguousPortError):
        resolve_port(ATOM_B, paths)


def test_policy_for_when_serial_in_table() -> None:
    assert policy_for(ATOM_B).baud == 115_200
    assert policy_for(ATOM_B).tool == "esptool"


def test_policy_for_when_serial_unknown() -> None:
    assert policy_for("FFFFFFFF00").baud == 115_200
