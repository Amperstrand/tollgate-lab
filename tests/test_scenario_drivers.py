"""Tests for the scenario driver registry + spec-stub adapters."""

import pytest
from scenario_fakes import FakeClient

from tollgate_lab.scenarios.contract import ScenarioRoles
from tollgate_lab.scenarios.drivers import (
    CAPTURE_DRIVERS,
    CLIENT_DRIVERS,
    GATEWAY_DRIVERS,
    PAYMENT_ACTORS,
    DriverEntry,
    build_roles,
    register_driver,
)
from tollgate_lab.scenarios.drivers.scenario_http_module import HttpModuleGateway
from tollgate_lab.scenarios.drivers.scenario_omarchy_ux import OmarchyUxClient, UxButtonActor
from tollgate_lab.scenarios.profile import ScenarioProfile, profile_from_dict


def stub_profile(client: dict | None = None, actor: str = "ux_button") -> ScenarioProfile:
    client_section = client or {
        "driver": "omarchy_ux",
        "vssh": "ssh -p 2222 omarchy@127.0.0.1",
        "templates": "templates",
    }
    return profile_from_dict(
        {
            "client": client_section,
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
    # The omarchy_ux client + wf_recorder capture bodies landed (phase 1);
    # the http_module gateway remains a spec stub until its phase.
    with pytest.raises(NotImplementedError, match="/usage"):
        roles.gateway.usage(FakeClient())


def test_placeholder_driver_refuses_composition():
    debian = {"driver": "debian_container", "ssh": "ssh debian@10.0.0.5"}
    with pytest.raises(NotImplementedError, match="declared but not implemented yet"):
        build_roles(stub_profile(client=debian))


def test_placeholder_actor_refuses_composition():
    with pytest.raises(NotImplementedError, match="payment actor 'token_paste'"):
        build_roles(stub_profile(actor="token_paste"))


def test_unknown_driver_refuses_composition():
    with pytest.raises(ValueError, match=r"unknown client driver 'bogus'"):
        build_roles(stub_profile(client={"driver": "bogus"}))


def test_register_driver_fills_empty_and_guards_replacement():
    class A:
        pass

    class B:
        pass

    registry: dict[str, DriverEntry[A]] = {
        "stub": DriverEntry(None),
        "live": DriverEntry(A),
    }

    # filling an empty slot is fine — the registry is untyped at runtime
    def factory_a(**kwargs):
        return A()

    register_driver(registry, "stub", factory_a)
    assert registry["stub"].factory is factory_a

    def factory_b(**kwargs):
        return B()

    with pytest.raises(ValueError, match="replace=True"):
        register_driver(registry, "live", factory_b)
    register_driver(registry, "live", factory_b, replace=True)
    assert registry["live"].factory is factory_b
