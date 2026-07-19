"""Unit tests for hardware lock."""

import os
import json
from pathlib import Path
from tollgate_lab.hardware.lock import (
    is_hardware_locked,
    read_hardware_lock,
    acquire_hardware_lock,
    release_hardware_lock,
)


def test_not_locked_by_default(tmp_path, monkeypatch):
    """No lock file means not locked."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    assert not is_hardware_locked()


def test_lock_acquire_release(tmp_path, monkeypatch):
    """Lock can be acquired and released."""
    monkeypatch.setattr("tollgate_lab.hardware.lock.HARDWARE_LOCK",
                        tmp_path / "hw.lock")
    acquire_hardware_lock(phase="test")
    assert is_hardware_locked()
    release_hardware_lock()
    assert not is_hardware_locked()


def test_read_lock_data(tmp_path, monkeypatch):
    """Lock file contains session metadata."""
    lock_file = tmp_path / "hw.lock"
    monkeypatch.setattr("tollgate_lab.hardware.lock.HARDWARE_LOCK", lock_file)

    acquire_hardware_lock(phase="test-phase")
    data = read_hardware_lock()
    assert data is not None
    assert data.get("phase") == "test-phase"
    release_hardware_lock()
