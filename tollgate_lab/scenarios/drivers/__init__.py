"""Scenario driver registry: names → adapter factories + required config.

Profiles reference drivers by name (docs/SCENARIO-LAYER.md §3); validation
checks names AND required kwargs against these registries, so a malformed
profile fails at load time with a clear error instead of a TypeError deep
inside adapter construction. Entries with ``factory=None`` are
declared-but-not-yet-ported adapters: profile validation accepts them, but
``build_roles`` refuses to compose them until the port lands.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

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
    "DriverEntry",
    "GATEWAY_DRIVERS",
    "PAYMENT_ACTORS",
    "build_roles",
    "register_driver",
]

_DriverT = TypeVar("_DriverT")


@dataclass(frozen=True)
class DriverEntry(Generic[_DriverT]):
    """One registry slot: adapter factory (or None) + required profile keys."""

    factory: Callable[..., _DriverT] | None = None
    required: tuple[str, ...] = ()


CLIENT_DRIVERS: dict[str, DriverEntry[ClientDriver]] = {
    "omarchy_ux": DriverEntry(OmarchyUxClient, required=("vssh", "templates")),
    # Debian container client over the PRTA QEMU path (Phase 2 migration).
    "debian_container": DriverEntry(None, required=("ssh",)),
    # Physical phone via tollgate_lab.drivers.android_adb (finale rig).
    "phone_adb": DriverEntry(None),
    # Cuttlefish virtual phone (cloud Android).
    "phone_cuttlefish": DriverEntry(None, required=("cf_base",)),
}

PAYMENT_ACTORS: dict[str, DriverEntry[PaymentActor]] = {
    "ux_button": DriverEntry(UxButtonActor),
    # Paste a token straight into the client wallet / CLI.
    "token_paste": DriverEntry(None),
    "portal_tip03": DriverEntry(PortalTip03Actor, required=("portal",)),
    # Client-side CLI payment (cashud /tollgate/pay).
    "cli": DriverEntry(None),
    # No-op actor for rigs that assert unpaid-gate behavior only.
    "skip": DriverEntry(None),
}

GATEWAY_DRIVERS: dict[str, DriverEntry[GatewayDriver]] = {
    "http_module": DriverEntry(HttpModuleGateway, required=("base",)),
}

CAPTURE_DRIVERS: dict[str, DriverEntry[CaptureDriver]] = {
    "wf_recorder": DriverEntry(WfRecorderCapture),
    # PRTA EvidenceRecorder wrapper (Phase 2 migration).
    "evidence_recorder": DriverEntry(None),
}


def register_driver(
    registry: dict[str, DriverEntry[_DriverT]],
    name: str,
    factory: Callable[..., _DriverT],
    required: tuple[str, ...] = (),
    *,
    replace: bool = False,
) -> None:
    """Register an adapter factory from consumer code.

    The supported extension path for stacks that live outside this
    package (PRTA, fips): fill a declared-but-unimplemented slot
    (``factory=None``) directly, and override a stub factory only with
    ``replace=True`` so a live implementation can never be silently
    swapped by a stray import.
    """
    existing = registry.get(name)
    if existing is not None and existing.factory is not None:
        if existing.factory is factory:
            return  # idempotent re-registration (import side effects)
        if not replace:
            raise ValueError(
                f"driver '{name}' already has a factory "
                f"({existing.factory.__name__}); pass replace=True to override"
            )
    registry[name] = DriverEntry(factory, required=required)


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
    registry: dict[str, DriverEntry[_DriverT]], name: str, what: str, config: dict[str, Any]
) -> _DriverT:
    entry = registry.get(name)
    if entry is None:
        known = ", ".join(sorted(registry))
        raise ValueError(f"unknown {what} '{name}' (known: {known})")
    if entry.factory is None:
        raise NotImplementedError(f"{what} '{name}' is declared but not implemented yet")
    return entry.factory(**config)
