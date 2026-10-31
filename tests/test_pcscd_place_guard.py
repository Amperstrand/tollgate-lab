"""#525: pcscd restarts deny while OTHER lanes hold labgrid places."""
import sys
from unittest import mock
sys.path.insert(0, ".")
from tollgate_lab import pcscd_ctl


def _who(text: str):
    m = mock.Mock()
    m.returncode = 0
    m.stdout = text
    return m


def test_no_holders_returns_empty():
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who("")):
        assert pcscd_ctl._labgrid_other_holders("mine") == []


def test_other_holder_reported():
    who = "Place 'phone-s20': acquired by phone-hil since 12:00\n"
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who(who)):
        assert pcscd_ctl._labgrid_other_holders("mine") == [
            "Place 'phone-s20': acquired by phone-hil since 12:00"
        ]


def test_own_project_line_ignored():
    who = "Place 'ccid-bench': acquired by ccid-firmware-rs since 12:00\n"
    with mock.patch.object(pcscd_ctl.subprocess, "run", return_value=_who(who)):
        assert pcscd_ctl._labgrid_other_holders("ccid-firmware-rs") == []


def test_labgrid_down_fails_open():
    with mock.patch.object(
        pcscd_ctl.subprocess, "run",
        side_effect=OSError("coordinator down"),
    ):
        assert pcscd_ctl._labgrid_other_holders("mine") == []
