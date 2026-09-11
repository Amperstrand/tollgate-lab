"""disk_hygiene unit tests — tmpdir-based, nothing real is deleted."""

from __future__ import annotations

import time

from tollgate_lab import disk_hygiene
from tollgate_lab.disk_hygiene import (
    HygieneReport,
    ensure_run_headroom,
    prune_cargo_debug,
    prune_tmp_opencode,
)


def _touch(path, age_days: float = 0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 1024)
    stamp = time.time() - age_days * 86400
    path.touch()
    import os

    os.utime(path, (stamp, stamp))


def test_prune_cargo_debug_removes_only_debug(tmp_path, monkeypatch):
    (tmp_path / "debug" / "deps").mkdir(parents=True)
    (tmp_path / "debug" / "deps" / "a.rmeta").write_bytes(b"junk")
    (tmp_path / "release").mkdir()
    (tmp_path / "release" / "keep.bin").write_bytes(b"keep")
    monkeypatch.setattr(disk_hygiene, "build_processes_running", lambda: False)

    action = prune_cargo_debug(target_dir=tmp_path)

    assert action and "debug" in action
    assert not (tmp_path / "debug").exists()
    assert (tmp_path / "release" / "keep.bin").exists()


def test_prune_cargo_debug_refuses_while_building(tmp_path, monkeypatch):
    (tmp_path / "debug").mkdir()
    monkeypatch.setattr(disk_hygiene, "build_processes_running", lambda: True)

    action = prune_cargo_debug(target_dir=tmp_path)

    assert action and "skipped" in action
    assert (tmp_path / "debug").exists()


def test_prune_cargo_debug_noop_without_debug_dir(tmp_path):
    assert prune_cargo_debug(target_dir=tmp_path) is None


def test_prune_tmp_opencode_respects_age(tmp_path):
    _touch(tmp_path / "old-session" / "artifact.bin", age_days=30)
    _touch(tmp_path / "live-session" / "recent.bin", age_days=0.0)

    action = prune_tmp_opencode(base=tmp_path, max_age_days=7)

    assert action and "1" in action
    assert not (tmp_path / "old-session").exists()
    assert (tmp_path / "live-session").exists()


def test_prune_tmp_opencode_noop_when_all_fresh(tmp_path):
    _touch(tmp_path / "live-session" / "recent.bin")
    assert prune_tmp_opencode(base=tmp_path) is None


def test_ensure_run_headroom_noop_with_headroom(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_hygiene, "disk_headroom_gb", lambda path="/": 100.0)
    report = ensure_run_headroom(min_free_gb=20)
    assert isinstance(report, HygieneReport)
    assert not report.acted and report.ok


def test_ensure_run_headroom_prunes_in_order(tmp_path, monkeypatch):
    state = {"gb": 5.0}
    (tmp_path / "cargo" / "debug").mkdir(parents=True)
    (tmp_path / "cargo" / "debug" / "x").write_bytes(b"j")
    _touch(tmp_path / "tmp" / "old" / "f", age_days=30)

    def fake_headroom(path="/"):
        return state["gb"]

    monkeypatch.setattr(disk_hygiene, "disk_headroom_gb", fake_headroom)
    monkeypatch.setattr(disk_hygiene, "build_processes_running", lambda: False)

    def bump_after_cargo(target_dir=..., force=False):
        # importing the real function via module attr already monkeypatched?
        # call the real pruning logic, then simulate freed space
        import shutil

        shutil.rmtree(tmp_path / "cargo" / "debug", ignore_errors=True)
        state["gb"] = 50.0
        return "removed cargo debug"

    monkeypatch.setattr(disk_hygiene, "prune_cargo_debug", bump_after_cargo)
    report = ensure_run_headroom(
        min_free_gb=20, cargo_target=tmp_path / "cargo", opentmp=tmp_path / "tmp"
    )

    assert report.acted and report.ok
    assert report.free_after_gb == 50.0
    assert not (tmp_path / "cargo" / "debug").exists()
    # headroom reached after step 1 -> tmp prune never needed
    assert (tmp_path / "tmp" / "old").exists()
