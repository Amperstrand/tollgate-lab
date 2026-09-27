"""Tests for the scenario lifecycle runner — fake drivers only."""

import json
from pathlib import Path

from scenario_fakes import FakeActor, FakeCapture, FakeClient, FakeGateway

from tollgate_lab.scenarios.contract import ScenarioRoles, SessionState, Usage
from tollgate_lab.scenarios.lifecycle import CANONICAL_STEPS, run_lifecycle
from tollgate_lab.scenarios.profile import profile_from_dict

BASE_STEPS = [
    "rig_up",
    "wallet_fresh",
    "actor_mints_token",
    "client_connects",
    "gate_closed_asserted",
    "payment_made",
    "gate_open_asserted",
    "session_asserted",
    "evidence_written",
]

OPTIONAL_STEPS = ["renewal_observed", "wallet_drained", "fallback_observed"]


def make_profile(**phases: object):
    data = {
        "client": {"driver": "omarchy_ux"},
        "payment": {"actor": "ux_button", "sats": 21},
        "gateway": {"driver": "http_module"},
        "phases": phases or {},
    }
    return profile_from_dict(data, name="test-scenario")


def make_rig(
    balance_sats: int = 0,
) -> tuple[ScenarioRoles, FakeClient, FakeGateway, FakeActor, FakeCapture]:
    client = FakeClient(balance_sats=balance_sats)
    gateway = FakeGateway()
    actor = FakeActor(client)
    capture = FakeCapture()
    roles = ScenarioRoles(client=client, actor=actor, gateway=gateway, capture=capture)
    return roles, client, gateway, actor, capture


def failures(result):
    return [s for s in result.steps if s.status == "FAIL"]


def test_canonical_step_names():
    assert [s.name for s in CANONICAL_STEPS] == BASE_STEPS[:-1] + OPTIONAL_STEPS + [
        "evidence_written"
    ]


def test_happy_path(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()

    result = run_lifecycle(roles, make_profile(), tmp_path)

    assert result.ok, failures(result)
    assert [s.name for s in result.steps] == BASE_STEPS
    assert client.wifi_calls == ["TollGate-Test"]
    assert client.tokens and client.tokens[0].startswith("fake-token-1-")
    assert actor.pay_calls == 1
    assert client.balance_sats == 0  # 21 injected, 21 spent
    assert capture.started and capture.stopped
    assert capture.steps == BASE_STEPS
    assert (tmp_path / "result.json").exists()
    assert (tmp_path / "timeline.jsonl").exists()


def test_renewal_phase(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()
    gateway.usage_script = [
        Usage(used=0, allotment=3600),  # session_asserted
        Usage(used=0, allotment=3600),  # renewal: before
        Usage(used=10, allotment=7200),  # renewal: after (allotment grew)
    ]
    gateway.session_state_script = [
        SessionState.active(),  # session_asserted
        SessionState.active(),  # renewal: still active on the renewed session
    ]

    result = run_lifecycle(roles, make_profile(renewal=True), tmp_path)

    assert result.ok, failures(result)
    assert [s.name for s in result.steps] == BASE_STEPS[:-1] + [
        "renewal_observed",
        "evidence_written",
    ]


def test_drain_and_fallback_phase(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()
    client.active_ssid_script = ["TollGate-Test", "HomeWifi"]
    gateway.session_state_script = [
        SessionState.active(),  # session_asserted
        SessionState.expired(),  # fallback_observed
    ]
    gateway.external_script = [False, True, False]

    result = run_lifecycle(roles, make_profile(drain_and_fallback=True), tmp_path)

    assert result.ok, failures(result)
    assert [s.name for s in result.steps] == BASE_STEPS[:-1] + [
        "wallet_drained",
        "fallback_observed",
        "evidence_written",
    ]


def test_step_failure_stops_and_records(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()
    gateway.advertise_error = RuntimeError("rig down")

    result = run_lifecycle(roles, make_profile(), tmp_path)

    assert not result.ok
    statuses = {s.name: s.status for s in result.steps}
    assert statuses["rig_up"] == "FAIL"
    assert statuses["wallet_fresh"] == "SKIP"
    assert statuses["evidence_written"] == "PASS"
    assert "mint_token" not in gateway.calls
    assert client.tokens == []
    assert actor.pay_calls == 0
    payload = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert payload["failed"] == 1
    assert "rig_up: FAIL (RuntimeError: rig down)" in payload["steps"]


def test_wallet_fresh_drained_violation_fails(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig(balance_sats=5)

    result = run_lifecycle(roles, make_profile(wallet_fresh="drained"), tmp_path)

    failed = failures(result)
    assert len(failed) == 1
    assert failed[0].name == "wallet_fresh"
    assert "balance_sats=5" in (failed[0].error or "")


def test_wallet_fresh_drained_with_empty_wallet_passes(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig(balance_sats=0)

    result = run_lifecycle(roles, make_profile(wallet_fresh="drained"), tmp_path)

    assert result.ok, failures(result)


def test_gated_off_steps_omitted(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()

    result = run_lifecycle(roles, make_profile(), tmp_path)

    names = {s.name for s in result.steps}
    assert set(OPTIONAL_STEPS).isdisjoint(names)


def test_no_capture_still_writes_evidence(tmp_path: Path):
    client = FakeClient()
    gateway = FakeGateway()
    roles = ScenarioRoles(client=client, actor=FakeActor(client), gateway=gateway, capture=None)

    result = run_lifecycle(roles, make_profile(), tmp_path)

    assert result.ok, failures(result)
    assert (tmp_path / "result.json").exists()
    assert (tmp_path / "timeline.jsonl").exists()


def test_evidence_written_always_last(tmp_path: Path):
    roles, client, gateway, actor, capture = make_rig()
    gateway.advertise_error = RuntimeError("nope")

    result = run_lifecycle(roles, make_profile(renewal=True, drain_and_fallback=True), tmp_path)

    assert result.steps[-1].name == "evidence_written"
    assert [s.status for s in result.steps] == ["FAIL"] + ["SKIP"] * 10 + ["PASS"]
