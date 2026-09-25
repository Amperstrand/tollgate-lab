"""Unit tests for the ZyxelPoEDriver (GS1900-8HP bench PoE control).

All SSH interaction is mocked at the subprocess boundary and time is
faked — no switch, no real waiting. The fake switch models the live
realtek-poe fork: `poe manage` applies after a configurable number of
`poe info` polls (readback lag), or never (wedged daemon).
"""

import subprocess

import pytest
from labgrid import Target, target_factory
from labgrid.driver.exception import ExecutionError

import tollgate_lab.drivers.zyxel_poe as zyxel_poe
from tollgate_lab.drivers.zyxel_poe import ZyxelPoEDriver, ZyxelPoePort

ACTIVE = {"status": "Delivering power", "consumption": 4.9}
SEARCHING = {"status": "Searching"}
DISABLED = {"status": "Disabled"}


class FakeSwitch:
    """Stateful stand-in for the switch's ubus poe object."""

    def __init__(self, state=None, apply_after=0, drop_attempts=0):
        self.state = state if state is not None else dict(ACTIVE)
        self.apply_after = apply_after  # polls before a manage takes effect
        self.drop_attempts = drop_attempts  # manages silently dropped (MCU reject)
        self.pending = None
        self.calls = []

    def info_json(self):
        if self.pending is not None:
            if self.apply_after <= 0:
                self.state = self.pending
                self.pending = None
            else:
                self.apply_after -= 1
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=f'{{"ports": {{"lan5": {repr(self.state)}}}}}'.replace("'", '"'),
            stderr="",
        )

    def run(self, args, **kwargs):
        self.calls.append(args)
        cmd = args[-1]
        if "poe manage" in cmd:
            if self.drop_attempts > 0:
                self.drop_attempts -= 1  # rc=0 but silently dropped (MCU reject)
                return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            self.pending = DISABLED if '"disable"' in cmd else dict(ACTIVE)
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        if "poe info" in cmd:
            return self.info_json()
        raise AssertionError(f"unexpected switch command: {cmd}")


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def switch(monkeypatch):
    sw = FakeSwitch()
    monkeypatch.setattr(zyxel_poe.subprocess, "run", sw.run)
    return sw


@pytest.fixture
def clock(monkeypatch):
    fc = FakeClock()
    monkeypatch.setattr(zyxel_poe.time, "monotonic", fc.monotonic)
    monkeypatch.setattr(zyxel_poe.time, "sleep", fc.sleep)
    return fc


def make_driver(port="lan5", delay=8.0):
    target = Target("rig-dummy")
    ZyxelPoePort(target, name="poe", host="192.168.13.2", port=port)
    driver = ZyxelPoEDriver(target, name="power", delay=delay)
    target.activate(driver)
    return driver


# -- registration -----------------------------------------------------------


def test_zyxel_poe_registered():
    assert "ZyxelPoePort" in target_factory.resources
    assert "ZyxelPoEDriver" in target_factory.drivers


# -- on/off -----------------------------------------------------------------


def test_on_sends_manage_enable_and_verifies(switch, clock):
    switch.state = dict(DISABLED)
    make_driver().on()
    manage = [c for c in switch.calls if "poe manage" in c[-1]]
    assert len(manage) == 1
    assert '"port": "lan5"' in manage[0][-1]
    assert '"action": "enable"' in manage[0][-1]
    assert switch.state["status"] == "Delivering power"  # verify observed it


def test_off_sends_manage_disable_and_verifies(switch, clock):
    make_driver().off()
    manage = [c for c in switch.calls if "poe manage" in c[-1]]
    assert '"action": "disable"' in manage[0][-1]
    assert switch.state["status"] == "Disabled"


def test_ssh_uses_batchmode_and_key_host_checking(switch, clock):
    switch.state = dict(DISABLED)
    make_driver().on()
    args = switch.calls[0]
    assert "BatchMode=yes" in args
    assert "StrictHostKeyChecking=accept-new" in args
    assert "root@192.168.13.2" in args


# -- readback lag (healthy manage, slow MCU settle) ---------------------------


def test_readback_lag_within_settling_window_succeeds(switch, clock):
    switch.state = dict(DISABLED)
    switch.apply_after = 20  # ~16s of poll lag < SETTLING_S, healthy
    make_driver().on()
    assert switch.state["status"] == "Delivering power"


# -- wedged daemon ------------------------------------------------------------


def test_transient_mcu_reject_is_retried_once(switch, clock):
    switch.state = dict(DISABLED)
    switch.drop_attempts = 1  # first manage silently rejected (not-ready class)
    make_driver().on()
    manages = [c for c in switch.calls if "poe manage" in c[-1]]
    assert len(manages) == 2
    assert switch.state["status"] == "Delivering power"


def test_frozen_snapshot_raises_dropped_after_retry(switch, clock):
    switch.state = dict(ACTIVE)
    switch.drop_attempts = 10**9  # every manage silently dropped
    with pytest.raises(ExecutionError, match="DROPPED"):
        make_driver().off()
    manages = [c for c in switch.calls if "poe manage" in c[-1]]
    assert len(manages) == 2  # bounded: exactly one retry


def test_flapping_state_raises_unverified(monkeypatch):
    state = {"status": "Delivering power", "consumption": 1.0}

    def run(args, **kwargs):
        cmd = args[-1]
        if "poe manage" in cmd:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        if "poe info" in cmd:
            # digest changes every poll: never frozen, never matching
            state["consumption"] += 1.0
            import json

            return subprocess.CompletedProcess(
                args=[], returncode=0,
                stdout=json.dumps({"ports": {"lan5": state}}),
                stderr="",
            )
        raise AssertionError(f"unexpected switch command: {cmd}")

    monkeypatch.setattr(zyxel_poe.subprocess, "run", run)

    fc = FakeClock()
    monkeypatch.setattr(zyxel_poe.time, "monotonic", fc.monotonic)
    monkeypatch.setattr(zyxel_poe.time, "sleep", fc.sleep)

    with pytest.raises(ExecutionError, match="UNVERIFIED"):
        make_driver().off()


# -- protected ports ---------------------------------------------------------


@pytest.mark.parametrize("port", ["lan1", "lan8"])
def test_protected_ports_refuse_toggle(switch, clock, port):
    driver = make_driver(port=port)
    for action in (driver.on, driver.off, driver.cycle):
        with pytest.raises(ExecutionError, match="protected"):
            action()
    assert switch.calls == []  # nothing ever reached the switch


# -- cycle -------------------------------------------------------------------


def test_cycle_off_sleep8_on(switch, clock):
    driver = make_driver()
    driver.cycle()
    manages = [c[-1] for c in switch.calls if "poe manage" in c[-1]]
    assert len(manages) == 2
    assert '"action": "disable"' in manages[0]
    assert '"action": "enable"' in manages[1]
    # fake-clock sleeps: 8s cycle delay + any poll intervals
    total_slept = 8.0
    assert clock.now >= 1000.0 + total_slept


def test_cycle_delay_configurable(switch, clock):
    make_driver(delay=9.5).cycle()
    manages = [c[-1] for c in switch.calls if "poe manage" in c[-1]]
    assert len(manages) == 2


# -- get/get_status -----------------------------------------------------------


def test_get_true_when_active(switch, clock):
    assert make_driver().get() is True


def test_get_true_when_searching(switch, clock):
    switch.state = dict(SEARCHING)
    assert make_driver().get() is True


def test_get_false_when_disabled(switch, clock):
    switch.state = dict(DISABLED)
    assert make_driver().get() is False


def test_get_status_returns_raw_string(switch, clock):
    switch.state = {"status": "Other fault"}
    assert make_driver().get_status() == "Other fault"


def test_snapshot_missing_port_raises(monkeypatch):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ports": {"lan9": {}}}', stderr=""
        )

    monkeypatch.setattr(zyxel_poe.subprocess, "run", run)
    with pytest.raises(ExecutionError, match="not present"):
        make_driver(port="lan7").get_status()


# -- failure paths ------------------------------------------------------------


def test_ssh_failure_raises_execution_error(monkeypatch):
    def failing_run(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="ubus: not found")

    monkeypatch.setattr(zyxel_poe.subprocess, "run", failing_run)
    with pytest.raises(ExecutionError, match="ubus: not found"):
        make_driver().on()


def test_ssh_timeout_raises_execution_error(monkeypatch):
    def timing_out(args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=15)

    monkeypatch.setattr(zyxel_poe.subprocess, "run", timing_out)
    with pytest.raises(ExecutionError, match="timed out"):
        make_driver().on()


# -- PoeStatus enum (absorbed from the PoePowerController lineage) ------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Disabled", zyxel_poe.PoeStatus.DISABLED),
        ("Searching", zyxel_poe.PoeStatus.SEARCHING),
        ("Requesting power", zyxel_poe.PoeStatus.REQUESTING),
        ("Delivering power", zyxel_poe.PoeStatus.DELIVERING),
        ("Fault", zyxel_poe.PoeStatus.FAULT),
        ("Other fault", zyxel_poe.PoeStatus.OTHER_FAULT),
        ("initializing", zyxel_poe.PoeStatus.INITIALIZING),
        ("unknown", zyxel_poe.PoeStatus.UNKNOWN),
        ("off", zyxel_poe.PoeStatus.OFF),
        ("", zyxel_poe.PoeStatus.EMPTY),
        ("  DELIVERING POWER ", zyxel_poe.PoeStatus.DELIVERING),
    ],
)
def test_poe_status_parse(raw, expected):
    assert zyxel_poe.PoeStatus.parse(raw) is expected


@pytest.mark.parametrize("raw", ["Zombie", "searching power"])
def test_poe_status_parse_unrecognized_is_none(raw):
    # Unrecognized statuses parse to None — never a hard error; the driver
    # keeps treating them as on-class (frozen get() behavior).
    assert zyxel_poe.PoeStatus.parse(raw) is None


def test_verification_sets_derived_from_enum():
    assert set(zyxel_poe.OFF_STATES) == {"disabled", "off", "", "fault"}
    assert set(zyxel_poe.TRANSIENT_STATES) == {"initializing", "unknown"}


# -- budget guard (absorbed from the PoePowerController lineage) --------------


def _budget_fake(monkeypatch, budget, consumption, port_budget):
    """Switch reporting full poe-info docs (budget fields present)."""
    state = {"status": "Delivering power", "consumption": 5.0}

    def run(args, **kwargs):
        cmd = args[-1]
        if "poe manage" in cmd:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        if "poe info" in cmd:
            import json

            doc = {
                "budget": budget,
                "consumption": consumption,
                "ports": {"lan5": {**state, "power_budget": port_budget}},
            }
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(doc), stderr=""
            )
        raise AssertionError(f"unexpected switch command: {cmd}")

    monkeypatch.setattr(zyxel_poe.subprocess, "run", run)


def test_on_warns_when_projected_past_budget(monkeypatch, caplog):
    _budget_fake(monkeypatch, budget=40.0, consumption=27.6, port_budget=15.4)
    with caplog.at_level("WARNING"):
        make_driver().on()
    assert any("load-shed" in r.message for r in caplog.records)


def test_on_silent_within_budget(monkeypatch, caplog):
    _budget_fake(monkeypatch, budget=65.0, consumption=27.6, port_budget=15.4)
    with caplog.at_level("WARNING"):
        make_driver().on()
    assert not any("load-shed" in r.message for r in caplog.records)


def test_off_skips_budget_guard(monkeypatch):
    # off() never load-sheds — the manage must be the FIRST switch call
    # (the verify polls that follow are legitimate).
    calls = []

    def run(args, **kwargs):
        cmd = args[-1]
        calls.append(cmd)
        if "poe manage" in cmd:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        if "poe info" in cmd:
            import json

            return subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"ports": {"lan5": {"status": "Disabled"}}}),
                stderr="",
            )
        raise AssertionError(f"unexpected switch command: {cmd}")

    monkeypatch.setattr(zyxel_poe.subprocess, "run", run)
    make_driver().off()
    assert calls[0].startswith("ubus call poe manage")
