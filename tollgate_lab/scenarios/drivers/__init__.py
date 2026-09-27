"""Scenario driver registry: names → adapter factories.

Profiles reference drivers by name (docs/SCENARIO-LAYER.md §3); validation
checks names against these registries. Entries mapped to ``None`` are
declared-but-not-yet-ported adapters: profile validation accepts them, but
``build_roles`` refuses to compose them until the port lands.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from tollgate_lab.scenarios.contract import (
    CaptureDriver,
    ClientDriver,
    GatewayDriver,
    PaymentActor,
    ScenarioRoles,
)
from tollgate_lab.scenarios.drivers.scenario_http_module import HttpModuleGateway
from tollgate_lab.scenarios.drivers.scenario_omarchy_ux import OmarchyUxClient, UxButtonActor
from tollgate_lab.scenarios.drivers.scenario_portal_tip03 import PortalTip03Actor
from tollgate_lab.scenarios.drivers.scenario_wf_recorder import WfRecorderCapture
from tollgate_lab.scenarios.profile import ScenarioProfile

__all__ = [
    "CAPTURE_DRIVERS",
    "CLIENT_DRIVERS",
    "GATEWAY_DRIVERS",
    "PAYMENT_ACTORS",
    "build_roles",
]

CLIENT_DRIVERS: dict[str, Callable[..., ClientDriver] | None] = {
    "omarchy_ux": OmarchyUxClient,
    # Debian container client over the PRTA QEMU path (Phase 2 migration).
    "debian_container": None,
    # Physical phone via tollgate_lab.drivers.android_adb (finale rig).
    "phone_adb": None,
    # Cuttlefish virtual phone (cloud Android).
    "phone_cuttlefish": None,
}

PAYMENT_ACTORS: dict[str, Callable[..., PaymentActor] | None] = {
    "ux_button": UxButtonActor,
    # Paste a token straight into the client wallet / CLI.
    "token_paste": None,
    "portal_tip03": PortalTip03Actor,
    # Client-side CLI payment (cashud /tollgate/pay).
    "cli": None,
    # No-op actor for rigs that assert unpaid-gate behavior only.
    "skip": None,
}

GATEWAY_DRIVERS: dict[str, Callable[..., GatewayDriver] | None] = {
    "http_module": HttpModuleGateway,
}

CAPTURE_DRIVERS: dict[str, Callable[..., CaptureDriver] | None] = {
    "wf_recorder": WfRecorderCapture,
    # PRTA EvidenceRecorder wrapper (Phase 2 migration).
    "evidence_recorder": None,
}

_T = TypeVar("_T")


def build_roles(profile: ScenarioProfile) -> ScenarioRoles:
    """Compose ScenarioRoles from a profile's driver names + kwargs."""
    client = _construct(
        CLIENT_DRIVERS, profile.client.driver, "client driver", profile.client.config
    )
    actor = _construct(
        PAYMENT_ACTORS, profile.payment.actor, "payment actor", profile.payment.config
    )
    gateway = _construct(
        GATEWAY_DRIVERS, profile.gateway.driver, "gateway driver", profile.gateway.config
    )
    capture = (
        _construct(
            CAPTURE_DRIVERS, profile.capture.driver, "capture driver", profile.capture.config
        )
        if profile.capture is not None
        else None
    )
    return ScenarioRoles(client=client, actor=actor, gateway=gateway, capture=capture)


def _construct(
    registry: dict[str, Callable[..., _T] | None], name: str, what: str, config: dict[str, Any]
) -> _T:
    if name not in registry:
        known = ", ".join(sorted(registry))
        raise ValueError(f"unknown {what} '{name}' (known: {known})")
    factory = registry[name]
    if factory is None:
        raise NotImplementedError(f"{what} '{name}' is declared but not implemented yet")
    return factory(**config)
