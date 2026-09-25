"""Unit tests for StockZyxelPoEDriver (stock GS1900-8HP web-API PoE driver).

No hardware: the StockWeb client is replaced by a fake via monkeypatching
the module's _make_web/_resolve_password seams. Timing constants are
shrunk for test speed.
"""

import pytest

import tollgate_lab.drivers.stock_zyxel_poe as mod
from tollgate_lab.drivers.stock_zyxel_poe import (
    StockZyxelPoePort,
    StockZyxelPoEDriver,
    ExecutionError,
)

from labgrid import Target


class FakeWeb:
    """Duck-typed stand-in for zyxel_stock.StockWeb."""

    def __init__(self, rows, on_set=None):
        # rows: {port_no: {"state","class","priority","powerup","mw"}}
        self.rows = {k: dict(v) for k, v in rows.items()}
        self.on_set = on_set
        self.calls = []

    def poe_status(self):
        return {k: dict(v) for k, v in self.rows.items()}

    def set_poe_state(self, port, enabled):
        self.calls.append((port, enabled))
        if self.on_set:
            self.on_set(self, port, enabled)


def _make_target_with(fake, monkeypatch, host="192.168.13.106", port="p2"):
    monkeypatch.setattr(mod, "_make_web", lambda h, p, u: fake)
    monkeypatch.setattr(mod, "_resolve_password", lambda: "test-pw")
    t = Target("test")
    StockZyxelPoePort(t, name="res", host=host, port=port)
    d = StockZyxelPoEDriver(t, name="drv")
    from labgrid.binding import BindingState
    d.state = BindingState.active  # bypass activation machinery for unit tests
    return d


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch):
    monkeypatch.setattr(mod, "SETTLING_S", 0.3)
    monkeypatch.setattr(mod, "FROZEN_GRACE_S", 0.2)
    monkeypatch.setattr(mod, "POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(mod, "VERIFY_TIMEOUT_S", 2.0)


ROWS_ON = {2: {"state": "Enable", "class": "class0", "priority": "Critical",
               "powerup": "802.3at", "mw": 5200}}
ROWS_OFF = {2: {"state": "Disable", "class": "class0", "priority": "Critical",
                "powerup": "802.3at", "mw": 0}}


def test_registration():
    from labgrid import target_factory
    assert "StockZyxelPoePort" in target_factory.resources
    assert "StockZyxelPoEDriver" in target_factory.drivers


def test_port_normalization():
    from labgrid import Target
    t = Target("t")
    assert StockZyxelPoePort(t, name="res", host="h", port="p2").port_no == 2
    assert StockZyxelPoePort(t, name="res", host="h", port="7").port_no == 7
    for bad in ("p9", "p0", "lan2", "", "px"):
        with pytest.raises(ExecutionError):
            StockZyxelPoePort(t, name="res", host="h", port=bad).port_no


def test_off_verifies_disable(monkeypatch):
    web = FakeWeb(dict(ROWS_ON))
    d = _make_target_with(web, monkeypatch)

    def to_off(fake, port, enabled):  # noqa: ANN001
        assert enabled is False
        fake.rows[2] = dict(ROWS_OFF[2])

    web.on_set = to_off
    d.off()
    assert web.calls == [(2, False)]


def test_on_with_pd_requires_watts(monkeypatch):
    web = FakeWeb(dict(ROWS_OFF))

    def to_on(fake, port, enabled):
        assert enabled is True
        # PD boots: state flips immediately, watts appear on a later poll
        fake.rows[2] = {**ROWS_OFF[2], "state": "Enable", "mw": 0}

        def later(fk):
            fk.rows[2]["mw"] = 4500
        import threading
        threading.Timer(0.15, later, args=(fake,)).start()

    web.on_set = to_on
    d = _make_target_with(web, monkeypatch)
    d.on()  # must NOT pass until mw > 0
    assert web.rows[2]["mw"] == 4500


def test_on_without_watts_times_out(monkeypatch):
    web = FakeWeb(dict(ROWS_OFF))

    def to_on_no_power(fake, port, enabled):
        fake.rows[2] = {**ROWS_OFF[2], "state": "Enable", "mw": 0}

    web.on_set = to_on_no_power
    d = _make_target_with(web, monkeypatch)
    with pytest.raises(ExecutionError, match="UNVERIFIED"):
        d.on()


def test_frozen_snapshot_is_wedge(monkeypatch):
    # set_poe_state "applies" but the 773 row never changes: frozen wedge.
    web = FakeWeb(dict(ROWS_ON), on_set=lambda f, p, e: None)
    d = _make_target_with(web, monkeypatch)
    with pytest.raises(ExecutionError, match="SNAPSHOT FROZEN"):
        d.off()


def test_protected_port_refused(monkeypatch):
    web = FakeWeb(dict(ROWS_ON))
    d = _make_target_with(web, monkeypatch, port="p1")
    with pytest.raises(ExecutionError, match="protected"):
        d.off()
    assert web.calls == []


def test_empty_port_enable_noop(monkeypatch):
    rows = {3: {"state": "Enable", "class": "class0", "priority": "Low",
                "powerup": "802.3at", "mw": 0}}
    web = FakeWeb(rows)
    d = _make_target_with(web, monkeypatch, port="p3")
    d.on()  # already enabled, no PD — accepted without a set call
    assert web.calls == []


def test_cycle_off_delay_on(monkeypatch):
    web = FakeWeb(dict(ROWS_ON))
    seq = iter([False, True])

    def tog(fake, port, enabled):
        want = next(seq)
        assert enabled is want
        fake.rows[2] = dict(ROWS_OFF[2] if not enabled else
                            {**ROWS_ON[2], "mw": 4800})

    web.on_set = tog
    d = _make_target_with(web, monkeypatch)
    d.delay = 0.05
    d.cycle()
    assert web.calls == [(2, False), (2, True)]


def test_get_status_and_get(monkeypatch):
    web = FakeWeb(dict(ROWS_ON))
    d = _make_target_with(web, monkeypatch)
    assert d.get() is True
    assert "Enable" in d.get_status() and "5200" in d.get_status()
