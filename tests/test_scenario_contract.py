"""Tests for scenario contract value objects and role composition."""

import pytest
from scenario_fakes import FakeActor, FakeClient, FakeGateway

from tollgate_lab.scenarios.contract import (
    PayReceipt,
    ScenarioRoles,
    SessionState,
    Usage,
    is_captive_redirect,
)


def test_usage_is_void():
    assert Usage().is_void
    assert Usage(used=-1, allotment=-1).is_void
    assert not Usage(used=0, allotment=3600).is_void
    assert not Usage(used=5, allotment=-1).is_void


def test_session_state_helpers():
    assert SessionState.active().is_active
    assert not SessionState.none().is_active
    assert not SessionState.expired().is_active
    assert SessionState.none().state == "none"
    assert SessionState.expired().state == "expired"


def test_session_state_rejects_unknown_state():
    with pytest.raises(ValueError, match="unknown session state 'zombie'"):
        SessionState("zombie")


def test_pay_receipt_defaults():
    receipt = PayReceipt(sats=21, strategy="ux_button")
    assert receipt.token == ""
    assert receipt.sats == 21


def test_scenario_roles_rejects_nameless_client():
    client = FakeClient()
    client.name = ""
    with pytest.raises(ValueError, match="non-empty name"):
        ScenarioRoles(client=client, actor=FakeActor(FakeClient()), gateway=FakeGateway())


def test_scenario_roles_rejects_strategyless_actor():
    actor = FakeActor(FakeClient())
    actor.strategy = ""
    with pytest.raises(ValueError, match="non-empty strategy"):
        ScenarioRoles(client=FakeClient(), actor=actor, gateway=FakeGateway())


def test_scenario_roles_accepts_full_bundle():
    client = FakeClient()
    roles = ScenarioRoles(client=client, actor=FakeActor(client), gateway=FakeGateway())
    assert roles.capture is None
    assert roles.client.name == "fake_client"


def test_is_captive_redirect_distinguishes_targets():
    assert is_captive_redirect(
        "http://10.99.99.1:2050/splash.html?redir=x", "http://10.99.99.1:2121"
    )
    assert not is_captive_redirect("https://1.1.1.1/", "http://10.99.99.1:2121")
    assert not is_captive_redirect("", "http://10.99.99.1:2121")
