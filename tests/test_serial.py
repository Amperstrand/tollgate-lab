"""Tests for serial console module."""

from tollgate_lab.drivers.serial_console import SerialConsole


def test_serial_console_imports():
    """SerialConsole can be imported."""
    assert SerialConsole is not None


def test_serial_console_has_methods():
    """SerialConsole has expected methods."""
    methods = [m for m in dir(SerialConsole) if not m.startswith("_")]
    assert len(methods) > 0
