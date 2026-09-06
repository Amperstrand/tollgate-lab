"""Session registry tests — begin/status/end, LOST detection, journal.

The LOST case needs a session whose registering process dies without
end(); faked with a subprocess that begins a session and _exit()s.
"""

import json
import os

import subprocess
import sys
import time
from pathlib import Path

import pytest

from tollgate_lab import session_registry as sr


@pytest.fixture()
def reg_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(sr, "JOURNAL", tmp_path / "sessions" / "journal.log")
    return tmp_path / "sessions"


def test_begin_and_status_show_running(reg_dir):
    session = sr.session_begin("t-one", "tests", "unit test session")
    try:
        records = sr.sessions_status()
        assert len(records) == 1
        assert records[0]["status"] == "running"
        assert records[0]["project"] == "tests"
    finally:
        session.end()

    records = sr.sessions_status()
    assert records[0]["status"] == "done"


def test_notes_and_pids_recorded(reg_dir):
    session = sr.session_begin("t-notes", "tests")
    try:
        session.note("udp-port", "21213")
        session.add_pid(4242, "scenario daemon")
        records = sr.sessions_status()
        assert records[0]["resources"]["udp-port"] == "21213"
        assert records[0]["pids"][0]["pid"] == 4242
    finally:
        session.end()


def test_dead_holder_is_flagged_lost(reg_dir):
    code = (
        "from tollgate_lab import session_registry as sr; "
        "s = sr.session_begin('t-dead', 'tests', 'will not end cleanly'); "
        "import os; os._exit(1)"
    )
    # The child deliberately dies without end() — a nonzero exit is the
    # point, so no check=True. It re-imports the module fresh, so the
    # tmp registry travels via env, not the monkeypatch.
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(Path(sr.__file__).resolve().parent.parent),
        env={**os.environ, "BENCH_RESERVATION_DIR": str(reg_dir.parent)},
    )
    records = sr.sessions_status()
    matching = [r for r in records if r["session"] == "t-dead"]
    assert matching and matching[0]["status"] == "LOST"

    journal = sr.journal_tail()
    assert any("lost" in line and "t-dead" in line for line in journal)


def test_journal_records_lifecycle(reg_dir):
    session = sr.session_begin("t-journal", "tests", "with note")
    session.end()
    journal = sr.journal_tail()
    assert any("begin" in line and "t-journal" in line for line in journal)
    assert any("end" in line and "t-journal" in line for line in journal)


def test_old_records_pruned(reg_dir):
    session = sr.session_begin("t-old", "tests")
    record_path = session.path
    session.end()
    record = json.loads(record_path.read_text())
    record["started"] = time.time() - (sr.MAX_RECORD_AGE_SECS + 60)
    record_path.write_text(json.dumps(record))

    records = sr.sessions_status()
    assert all(r["session"] != "t-old" for r in records)
    assert not record_path.exists()
