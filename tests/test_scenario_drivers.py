"""Tests for the scenario driver registry + spec-stub adapters."""

import pytest
from scenario_fakes import FakeClient

from tollgate_lab.scenarios.contract import ScenarioRoles
from tollgate_lab.scenarios.drivers import (
    CAPTURE_DRIVERS,
    CLIENT_DRIVERS,
    GATEWAY_DRIVERS,
    PAYMENT_ACTORS,
    build_roles,
)
from tollgate_lab.scenarios.drivers.scenario_http_module import HttpModuleGateway
from tollgate_lab.scenarios.drivers.scenario_omarchy_ux import OmarchyUxClient, UxButtonActor
from tollgate_lab.scenarios.profile import ScenarioProfile, profile_from_dict


def stub_profile(client_driver: str = "omarchy_ux", actor: str = "ux_button") -> ScenarioProfile:
    return profile_from_dict(
        {
            "client": {
                "driver": client_driver,
                "vssh": "ssh -p 2222 omarchy@127.0.0.1",
                "templates": "templates",
            },
            "payment": {"actor": actor, "template": "btn-pay-tollgate.png"},
            "gateway": {"driver": "http_module", "base": "http://127.0.0.1:2121"},
            "capture": {"driver": "wf_recorder", "split_screen": True},
        },
        name="stub-profile",
    )


def test_registry_covers_all_strategy_names():
    assert set(PAYMENT_ACTORS) >= {"ux_button", "token_paste", "portal_tip03", "cli", "skip"}
    assert set(CLIENT_DRIVERS) >= {
        "omarchy_ux",
        "debian_container",
        "phone_adb",
        "phone_cuttlefish",
    }
    assert set(GATEWAY_DRIVERS) == {"http_module"}
    assert set(CAPTURE_DRIVERS) >= {"wf_recorder", "evidence_recorder"}


def test_build_roles_composes_stub_adapters():
    roles = build_roles(stub_profile())

    assert isinstance(roles, ScenarioRoles)
    assert isinstance(roles.client, OmarchyUxClient)
    assert isinstance(roles.actor, UxButtonActor)
    assert isinstance(roles.gateway, HttpModuleGateway)
    assert roles.capture is not None


def test_stub_methods_raise_not_implemented():
    roles = build_roles(stub_profile())

    assert roles.client.name == "omarchy_ux"
    with pytest.raises(NotImplementedError, match="nmcli"):
        roles.client.connect_wifi("TollGate-Test")
    with pytest.raises(NotImplementedError, match="/usage"):
        roles.gateway.usage(FakeClient())


def test_placeholder_driver_refuses_composition():
    with pytest.raises(NotImplementedError, match="declared but not implemented yet"):
        build_roles(stub_profile(client_driver="debian_container"))


def test_unknown_driver_refuses_composition():
    with pytest.raises(ValueError, match=r"unknown client driver 'bogus'"):
        build_roles(stub_profile(client_driver="bogus"))
