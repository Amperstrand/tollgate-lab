"""Unit tests for tollgate_lab.hardware.poe — no switch required.

The `poe info` fixture mirrors the live GS1900-8HP shape captured on
2026-09-22 (realtek-poe, firmware v17.1). subprocess.run is monkeypatched;
nothing here touches the network.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from tollgate_lab.hardware.poe import (
    PoeControllerConfig,
    PoeError,
    PoePortInfo,
    PoePowerController,
    PoeProtectedPortError,
    PoeStatus,
    PoeSwitchInfo,
    PoeUnresponsiveError,
)

INFO_DOC: dict[str, Any] = {
    "firmware": "v17.1",
    "mcu": "ST Micro ST32F100 Microcontroller",
    "budget": 65.0,
    "consumption": 27.6,
    "allocated": 0.0,
    "ports": {
        "lan1": {
            "priority": 3, "mode": "PoE", "status": "Disabled",
            "temperature_c": 47.5, "power_limit_type": 0, "power_budget": 15.4,
        },
        "lan2": {
            "priority": 2, "mode": "PoE", "status": "Searching",
            "temperature_c": 47.5, "power_limit_type": 1, "power_budget": 15.4,
        },
        "lan3": {
            "priority": 2, "mode": "PoE", "status": "Delivering power",
            "consumption": 5.6, "temperature_c": 48.0,
            "power_limit_type": 1, "power_budget": 15.4,
        },
    },
}


class FakeSwitch:
    """In-memory realtek-poe: applies manage/set_port_config calls to INFO_DOC.

    Mirrors the live ubus schema verified 2026-09-22:
    ``poe manage {"port","action"}`` and ``poe set_port_config {"port","enable"}``.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_methods: set[str] = set()
        self.no_apply = False  # calls "succeed" but status never changes
        self.frozen = False  # info() serves a byte-identical snapshot (wedged daemon)
        monkeypatch.setattr(subprocess, "run", self._run)

    def _run(self, args: list[str], **_kw: Any) -> subprocess.CompletedProcess[str]:
        cmd = args[-1]
        self.calls.append((" ".join(args[:-1]), cmd))
        if cmd == "ubus call poe info":
            return subprocess.CompletedProcess(args, 0, json.dumps(INFO_DOC), "")
        if "poe manage" in cmd:
            if "manage" in self.fail_methods:
                return subprocess.CompletedProcess(args, 1, "", "Command failed")
            return self._apply(cmd, method="manage", key="action")
        if "poe set_port_config" in cmd:
            if "set_port_config" in self.fail_methods:
                return subprocess.CompletedProcess(args, 1, "", "Command failed")
            return self._apply(cmd, method="set_port_config", key="enable")
        return subprocess.CompletedProcess(args, 1, "", f"unknown command {cmd!r}")

    def _apply(
        self, cmd: str, method: str, key: str
    ) -> subprocess.CompletedProcess[str]:
        if not self.no_apply:
            payload = json.loads(cmd.split(method, 1)[1].strip().strip("'\""))
            enable = payload[key] in ("enable", True)
            INFO_DOC["ports"][payload["port"]]["status"] = (
                "Searching" if enable else "Disabled"
            )
        return subprocess.CompletedProcess(
            ["ubus"], 0, json.dumps({"status": "ok"}), ""
        )


@pytest.fixture
def switch(monkeypatch: pytest.MonkeyPatch) -> FakeSwitch:
    yield FakeSwitch(monkeypatch)
    INFO_DOC["budget"] = 65.0  # undo budget-guard mutations


def make_ctl(poll_interval_s: float = 0.0) -> PoePowerController:
    return PoePowerController(
        PoeControllerConfig(host="switch.invalid", poll_interval_s=poll_interval_s)
    )


class TestStatusParsing:
    def test_info_parses_all_ports(self, switch: FakeSwitch) -> None:
        info = make_ctl().info()
        assert isinstance(info, PoeSwitchInfo)
        assert info.budget_w == pytest.approx(65.0)
        assert info.consumption_w == pytest.approx(27.6)
        assert set(info.ports) == {"lan1", "lan2", "lan3"}
        assert info.ports["lan3"].status is PoeStatus.DELIVERING
        assert info.ports["lan3"].powered is True
        assert info.ports["lan3"].consumption_w == pytest.approx(5.6)

    def test_port_status_unknown_port_refused(self, switch: FakeSwitch) -> None:
        with pytest.raises(PoeError, match="no PoE port 'lan9'"):
            make_ctl().port_status("lan9")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Disabled", PoeStatus.DISABLED),
            ("Searching", PoeStatus.SEARCHING),
            ("Delivering power", PoeStatus.DELIVERING),
            ("Requesting power", PoeStatus.REQUESTING),
            ("Fault", PoeStatus.FAULT),
            ("Other fault", PoeStatus.OTHER_FAULT),
            ("initializing", PoeStatus.INITIALIZING),
            ("unknown", PoeStatus.UNKNOWN),
        ],
    )
    def test_status_enum_mapping(self, raw: str, expected: PoeStatus) -> None:
        assert PoeStatus.from_switch(raw) is expected

    def test_garbage_status_refused(self) -> None:
        with pytest.raises(PoeError, match="unrecognised"):
            PoeStatus.from_switch("Zombie")


class TestControl:
    def test_off_then_disabled(self, switch: FakeSwitch) -> None:
        result = make_ctl().off("lan2")
        assert result.status is PoeStatus.DISABLED
        assert any(
            "poe manage" in cmd and '"action": "disable"' in cmd
            for _, cmd in switch.calls
        )

    def test_on_reaches_searching_without_pd(self, switch: FakeSwitch) -> None:
        result = make_ctl().on("lan2")  # FakeSwitch parks enabled ports in Searching
        assert result.status is PoeStatus.SEARCHING

    def test_assert_delivering_fails_loudly_on_searching(self, switch: FakeSwitch) -> None:
        with pytest.raises(PoeError, match="SEARCHING"):
            make_ctl().assert_delivering("lan2", timeout_s=0.2)

    def test_cycle_enforces_min_off(
        self, switch: FakeSwitch, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slept: list[float] = []
        monkeypatch.setattr(
            "tollgate_lab.hardware.poe.time.sleep", lambda s: slept.append(s)
        )
        result = make_ctl().cycle("lan2", min_off_s=8.0)
        assert result.status is PoeStatus.SEARCHING
        assert slept and max(slept) == pytest.approx(8.0)
        off_idx = [i for i, (_, c) in enumerate(switch.calls) if '"action": "disable"' in c]
        on_idx = [i for i, (_, c) in enumerate(switch.calls) if '"action": "enable"' in c]
        assert off_idx and on_idx and off_idx[0] < on_idx[0]

    def test_manage_falls_back_to_set_port_config(self, switch: FakeSwitch) -> None:
        switch.fail_methods.add("manage")
        result = make_ctl().on("lan2")
        assert result.status is PoeStatus.SEARCHING
        assert any("set_port_config" in cmd for _, cmd in switch.calls)

    def test_manage_both_failing_raises(self, switch: FakeSwitch) -> None:
        switch.fail_methods.update({"manage", "set_port_config"})
        with pytest.raises(PoeError, match="both interfaces"):
            make_ctl().on("lan2")

    def test_off_timeout_raises(self, switch: FakeSwitch) -> None:
        # Manage "succeeds" but the port never reaches Disabled -> timeout.
        switch.no_apply = True
        with pytest.raises(PoeError, match="timed out"):
            make_ctl().off("lan2", timeout_s=0.2)

    def test_frozen_snapshot_raises_unresponsive(
        self, switch: FakeSwitch
    ) -> None:
        # Live-observed failure mode (2026-09-22): daemon answers poe info
        # with a byte-identical cached snapshot and drops manage calls.
        # The controller must name the recovery, not just time out.
        switch.no_apply = True
        ctl = PoePowerController(
            PoeControllerConfig(
                host="switch.invalid", poll_interval_s=0.05, frozen_grace_s=0.2
            )
        )
        with pytest.raises(PoeUnresponsiveError, match="killall -9 realtek-poe"):
            ctl.off("lan2", timeout_s=10.0)

    def test_frozen_without_manage_is_a_pd_problem_not_daemon(
        self, switch: FakeSwitch
    ) -> None:
        # An absent PD legally parks a healthy port in SEARCHING forever —
        # assert_delivering must raise a plain timeout (check the PD/port),
        # never the daemon-restart error.
        switch.no_apply = True
        ctl = PoePowerController(
            PoeControllerConfig(
                host="switch.invalid", poll_interval_s=0.05, frozen_grace_s=0.2
            )
        )
        with pytest.raises(PoeError, match="check the PD/port") as excinfo:
            ctl.assert_delivering("lan2", timeout_s=1.0)
        assert not isinstance(excinfo.value, PoeUnresponsiveError)

    def test_transient_unknown_is_polled_through(
        self, switch: FakeSwitch, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # First info shows 'unknown', second shows the applied state.
        real_info = json.dumps(INFO_DOC)
        seq = [real_info.replace('"Searching"', '"unknown"'), real_info]
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda args, **kw: subprocess.CompletedProcess(
                args, 0, seq.pop(0) if args[-1] == "ubus call poe info" else json.dumps({}), ""
            ),
        )
        result = make_ctl().on("lan2")
        assert result.status is PoeStatus.SEARCHING


class TestBudgetGuard:
    def test_budget_projection_warns(
        self, switch: FakeSwitch, caplog: pytest.LogCaptureFixture
    ) -> None:
        INFO_DOC["budget"] = 40.0  # 27.6 + 15.4 > 40
        with caplog.at_level("WARNING", logger="tollgate_lab.poe"):
            make_ctl().on("lan2")
        assert any("load-shed" in r.message for r in caplog.records)

    def test_strict_budget_raises(self, switch: FakeSwitch) -> None:
        INFO_DOC["budget"] = 40.0
        with pytest.raises(PoeError, match="budget"):
            make_ctl().on("lan2", strict_budget=True)


class TestProtectedPorts:
    def test_protected_port_refused_before_any_switch_call(
        self, switch: FakeSwitch
    ) -> None:
        # lan5-class port: one-way trip — must refuse without issuing any
        # mutating ubus call, on every entry point. (on() may perform its
        # read-only budget-projection info() first; that is harmless.)
        ctl = PoePowerController(
            PoeControllerConfig(host="switch.invalid", protected_ports=frozenset({"lan5"}))
        )
        for call in (lambda: ctl.off("lan5"), lambda: ctl.on("lan5"),
                     lambda: ctl.cycle("lan5")):
            with pytest.raises(PoeProtectedPortError, match="inventory-protected"):
                call()
        mutating = [
            c for _, c in switch.calls if "manage" in c or "set_port_config" in c
        ]
        assert mutating == []

    def test_readonly_paths_still_allowed_on_protected_port(
        self, switch: FakeSwitch
    ) -> None:
        ctl = PoePowerController(
            PoeControllerConfig(host="switch.invalid", protected_ports=frozenset({"lan3"}))
        )
        assert ctl.port_status("lan3").status is PoeStatus.DELIVERING


class TestSshArgs:
    def test_ssh_uses_batchmode_and_keyfile(self, switch: FakeSwitch) -> None:
        ctl = PoePowerController(
            PoeControllerConfig(host="h", keyfile="/keys/lab", port=2222)
        )
        ctl.info()
        argv, _ = switch.calls[0]
        assert "BatchMode=yes" in argv
        assert "/keys/lab" in argv
        assert "IdentitiesOnly=yes" in argv
        assert "-p 2222" in argv


def test_portinfo_is_frozen() -> None:
    entry = PoePortInfo(port="lan2", status=PoeStatus.SEARCHING)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass contract
        entry.status = PoeStatus.DELIVERING  # type: ignore[misc]
