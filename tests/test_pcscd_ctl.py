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
