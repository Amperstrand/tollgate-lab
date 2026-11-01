"""pcscd-ctl unit tests — restart sequencing and journaling, with the
domain lock, systemctl, and the stability probe stubbed."""

from tollgate_lab import pcscd_ctl


class FakeLock:
    def __init__(self, events):
        self._events = events
        self.holder = {"project": "test"}

    def release(self):
        self._events.append(("lock-released", ""))


def _patch(monkeypatch, events, stable=(True, "5 readers listed"), rc=0):
    monkeypatch.setattr(
        pcscd_ctl,
        "bench_event",
        lambda e, d="": events.append((e, d)),
    )
    monkeypatch.setattr(
        pcscd_ctl,
        "acquire_pcscd_disturbance",
        lambda **k: FakeLock(events),
    )
    monkeypatch.setattr(pcscd_ctl, "systemctl_restart_pcscd", lambda: rc)
    monkeypatch.setattr(pcscd_ctl, "pcscd_stable", lambda: stable)
    # Isolate from the LIVE labgrid coordinator: without this stub the tests
    # fail on any host whose coordinator has real place holders (the DENIED
    # path is correct product behavior — the tests must not depend on fleet
    # state). CI runners are clean, so this only bites lab hosts.
    monkeypatch.setattr(pcscd_ctl, "_labgrid_other_holders", lambda project: [])


def test_restart_sequences_lock_journal_wait_release(monkeypatch):
    events: list = []
    _patch(monkeypatch, events)
    out = pcscd_ctl.restart(project="lane", reason="test", stable_timeout_s=0.1)
    assert out["stable"] is True
    assert out["systemctl_rc"] == 0
    kinds = [e for e, _ in events]
    assert kinds == ["pcscd-restart", "pcscd-restart-done", "lock-released"]


def test_restart_reports_unstable(monkeypatch):
    events: list = []
    _patch(monkeypatch, events, stable=(False, "Service not available"))
    out = pcscd_ctl.restart(project="lane", reason="test", stable_timeout_s=0.1)
    assert out["stable"] is False
    kinds = [e for e, _ in events]
    assert "pcscd-restart-unstable" in kinds
    assert kinds[-1] == "lock-released"


def test_restart_releases_lock_on_systemctl_failure(monkeypatch):
    events: list = []
    _patch(monkeypatch, events, rc=1)
    out = pcscd_ctl.restart(project="lane", reason="test", stable_timeout_s=0.1)
    assert out["systemctl_rc"] == 1
    assert events[-1] == ("lock-released", "")


def test_status_shape(monkeypatch):
    _patch(monkeypatch, [])
    monkeypatch.setattr(pcscd_ctl, "journal_tail", lambda n=8: ["x journal line"])
    st = pcscd_ctl.status()
    assert st["stable"] is True
    assert st["journal"] == ["x journal line"]


class TestMainExitCodes:
    """Issue #23: denied restarts and lock contention must surface in the
    exit code, not print a stable-looking line and return 0/1."""

    def test_denied_restart_is_exit_4(self, monkeypatch, capsys):
        events: list[tuple[str, str]] = []
        _patch(monkeypatch, events, stable=(True, "5 readers listed"), rc=1)
        rc = pcscd_ctl.main(["restart", "--project", "lane"])
        assert rc == 4, "stable-but-denied restart must not exit 0"
        assert "rc=1" in capsys.readouterr().out

    def test_clean_restart_is_exit_0(self, monkeypatch):
        events: list[tuple[str, str]] = []
        _patch(monkeypatch, events, rc=0)
        assert pcscd_ctl.main(["restart", "--project", "lane"]) == 0

    def test_unstable_is_exit_2(self, monkeypatch):
        events: list[tuple[str, str]] = []
        _patch(monkeypatch, events, stable=(False, "no answer"), rc=0)
        assert pcscd_ctl.main(["restart", "--project", "lane"]) == 2

    def test_lock_contention_is_exit_3(self, monkeypatch, capsys):
        from tollgate_lab import PcscdDomainHeldError

        def boom(**kwargs):
            raise PcscdDomainHeldError(holder={"project": "other-lane"})

        monkeypatch.setattr(pcscd_ctl, "acquire_pcscd_disturbance", boom)
        monkeypatch.setattr(pcscd_ctl, "bench_event", lambda e, d="": None)
        monkeypatch.setattr(pcscd_ctl, "_labgrid_other_holders", lambda project: [])
        rc = pcscd_ctl.main(["restart", "--project", "lane"])
        assert rc == 3, "contention must exit 3 (documented), not traceback 1"
        assert "lock-contention" in capsys.readouterr().out


def test_restart_emits_unstable_event_when_systemctl_fails(monkeypatch):
    """Codex P2 on PR #15: a denied systemctl restart with the old daemon
    still stable must not emit pcscd-restart-done (exit half fixed in #23,
    event half here)."""
    events = []
    _patch(monkeypatch, events, stable=(True, "5 readers listed"), rc=1)
    pcscd_ctl.restart(project="test", reason="unit")
    kinds = [e for e, _d in events]
    assert "pcscd-restart-done" not in kinds
    assert "pcscd-restart-unstable" in kinds
