"""#525: pcscd restarts deny while OTHER lanes hold labgrid places.

Parser tests use the REAL `labgrid-client who` table format (live-verified
2026-10-31; the first draft parsed a sentence format that does not exist —
Codex P1 on tollgate-lab#26).
"""
import sys
from unittest import mock

sys.path.insert(0, ".")
from tollgate_lab import pcscd_ctl


def _who(text: str):
    m = mock.Mock()
    m.returncode = 0
    m.stdout = text
    return m


REAL = (
    "User    Host             Place             Changed                   \n"
    "root    ai-legion        android-emulator  2026-10-31 11:45:52.044706\n"
    "ubuntu  ai-legion-small  nr7101-router     2026-10-28 22:01:30.875204\n"
)


def test_no_holders_returns_empty():
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who("")):
        assert pcscd_ctl._labgrid_other_holders("mine") == []


def test_real_table_other_holders_reported():
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who(REAL)):
        holders = pcscd_ctl._labgrid_other_holders("mine")
        assert len(holders) == 2
        assert "android-emulator" in holders[0]
        assert "nr7101-router" in holders[1]


def test_own_project_place_ignored():
    who = (
        "User    Host      Place       Changed\n"
        "root    ai-legion ccid-bench  2026-10-31 11:45:52\n"
    )
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who(who)):
        assert pcscd_ctl._labgrid_other_holders("ccid-firmware-rs") == []


def test_labgrid_down_fails_open():
    with mock.patch.object(
        pcscd_ctl.subprocess, "run",
        side_effect=OSError("coordinator down"),
    ):
        assert pcscd_ctl._labgrid_other_holders("mine") == []
