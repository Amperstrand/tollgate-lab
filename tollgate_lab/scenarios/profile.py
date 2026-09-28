"""Scenario profile loading + validation.

A profile is the YAML launch config for one rig (docs/SCENARIO-LAYER.md §3):
which client/payment/gateway/capture drivers to compose, their kwargs, and
the phase flags that gate the lifecycle's optional steps.

    client:  {driver: omarchy_ux, vssh: "ssh -p 2222 …", templates: .../templates}
    payment: {actor: ux_button, template: btn-pay-tollgate.png, sats: 21}
    gateway: {driver: http_module, base: "http://10.99.97.2:2121", token_source: fakewallet}
    capture: {driver: wf_recorder, split_screen: true}
    phases:  {renewal: true, drain_and_fallback: true, wallet_fresh: drained}

Driver names are validated against the scenario driver registry; unknown
names fail with an error listing the known ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeVar

import yaml

if TYPE_CHECKING:
    from tollgate_lab.scenarios.drivers import DriverEntry

WalletFreshness = Literal["drained", "funded"]

_KNOWN_WALLET_FRESHNESS = ("drained", "funded")

_RegistryT = TypeVar("_RegistryT")


@dataclass(frozen=True)
class ClientSpec:
    driver: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentSpec:
    actor: str
    sats: int = 21
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GatewaySpec:
    driver: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CaptureSpec:
    driver: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PhaseFlags:
    renewal: bool = False
    drain_and_fallback: bool = False
    wallet_fresh: WalletFreshness = "funded"


@dataclass(frozen=True)
class ScenarioProfile:
    name: str
    client: ClientSpec
    payment: PaymentSpec
    gateway: GatewaySpec
    capture: CaptureSpec | None = None
    phases: PhaseFlags = PhaseFlags()
    ssid: str | None = None

    def step_gates(self) -> dict[str, bool]:
        """Optional-step gates derived from the phase flags."""
        return {
            "renewal_observed": self.phases.renewal,
            "wallet_drained": self.phases.drain_and_fallback,
            "fallback_observed": self.phases.drain_and_fallback,
        }


def load_profile(path: Path | str) -> ScenarioProfile:
    """Load and validate a profile YAML file."""
    profile_path = Path(path)
    try:
        raw = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {profile_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"profile {profile_path} must be a YAML mapping, got {type(raw).__name__}")
    return profile_from_dict(raw, name=profile_path.stem)


def profile_from_dict(data: dict[str, Any], *, name: str) -> ScenarioProfile:
    """Validate a parsed profile mapping into a ScenarioProfile."""
    _reject_unknown_keys(
        set(data), ("client", "payment", "gateway", "capture", "phases", "ssid"), "profile"
    )

    client = _client_spec(data.get("client"))
    payment = _payment_spec(data.get("payment"))
    gateway = _gateway_spec(data.get("gateway"))
    capture = _capture_spec(data.get("capture"))
    phases = _phase_flags(data.get("phases"))
    ssid = data.get("ssid")
    if ssid is not None and (not isinstance(ssid, str) or not ssid):
        raise ValueError(f"profile ssid must be a non-empty string, got {ssid!r}")

    _validate_driver_names(client, payment, gateway, capture)
    return ScenarioProfile(
        name=name,
        client=client,
        payment=payment,
        gateway=gateway,
        capture=capture,
        phases=phases,
        ssid=ssid,
    )


def _reject_unknown_keys(keys: set[str], allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(keys - set(allowed))
    if unknown:
        raise ValueError(f"unknown {where} key(s) {unknown} (allowed: {sorted(allowed)})")


def _require_mapping(section: Any, where: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise ValueError(
            f"profile section '{where}' must be a mapping, got {type(section).__name__}"
        )
    return section


def _client_spec(section: Any) -> ClientSpec:
    if section is None:
        raise ValueError("profile is missing required section 'client'")
    mapping = _require_mapping(section, "client")
    driver = _driver_name(mapping, "client")
    return ClientSpec(driver=driver, config=_kwargs(mapping, "driver"))


def _payment_spec(section: Any) -> PaymentSpec:
    if section is None:
        raise ValueError("profile is missing required section 'payment'")
    mapping = _require_mapping(section, "payment")
    driver = _driver_name(mapping, "payment", key="actor")
    sats = mapping.get("sats", 21)
    if not isinstance(sats, int) or isinstance(sats, bool) or sats <= 0:
        raise ValueError(f"payment.sats must be a positive int, got {sats!r}")
    return PaymentSpec(actor=driver, sats=sats, config=_kwargs(mapping, ("actor", "sats")))


def _gateway_spec(section: Any) -> GatewaySpec:
    if section is None:
        raise ValueError("profile is missing required section 'gateway'")
    mapping = _require_mapping(section, "gateway")
    driver = _driver_name(mapping, "gateway")
    return GatewaySpec(driver=driver, config=_kwargs(mapping, "driver"))


def _capture_spec(section: Any) -> CaptureSpec | None:
    if section is None:
        return None
    mapping = _require_mapping(section, "capture")
    driver = _driver_name(mapping, "capture")
    return CaptureSpec(driver=driver, config=_kwargs(mapping, "driver"))


def _phase_flags(section: Any) -> PhaseFlags:
    if section is None:
        return PhaseFlags()
    mapping = _require_mapping(section, "phases")
    allowed = ("renewal", "drain_and_fallback", "wallet_fresh")
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ValueError(f"unknown phase flag(s) {unknown} (allowed: {sorted(allowed)})")

    renewal = mapping.get("renewal", False)
    drain = mapping.get("drain_and_fallback", False)
    for flag, value in (("renewal", renewal), ("drain_and_fallback", drain)):
        if not isinstance(value, bool):
            raise ValueError(f"phases.{flag} must be a bool, got {value!r}")
    wallet_fresh_raw = mapping.get("wallet_fresh", "funded")
    if wallet_fresh_raw == "drained":
        wallet_fresh: WalletFreshness = "drained"
    elif wallet_fresh_raw == "funded":
        wallet_fresh = "funded"
    else:
        raise ValueError(
            f"phases.wallet_fresh must be one of {list(_KNOWN_WALLET_FRESHNESS)}, "
            f"got {wallet_fresh_raw!r}"
        )
    return PhaseFlags(renewal=renewal, drain_and_fallback=drain, wallet_fresh=wallet_fresh)


def _driver_name(mapping: dict[str, Any], where: str, *, key: str = "driver") -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"profile section '{where}' must carry a non-empty string '{key}'")
    return value


def _kwargs(mapping: dict[str, Any], reserved: str | tuple[str, ...]) -> dict[str, Any]:
    reserved_keys = (reserved,) if isinstance(reserved, str) else reserved
    return {k: v for k, v in mapping.items() if k not in reserved_keys}


def _validate_driver_names(
    client: ClientSpec, payment: PaymentSpec, gateway: GatewaySpec, capture: CaptureSpec | None
) -> None:
    from tollgate_lab.scenarios.drivers import (
        CAPTURE_DRIVERS,
        CLIENT_DRIVERS,
        GATEWAY_DRIVERS,
        PAYMENT_ACTORS,
    )

    _check_known(CLIENT_DRIVERS, client.driver, "client driver", client.config)
    _check_known(PAYMENT_ACTORS, payment.actor, "payment actor", payment.config)
    _check_known(GATEWAY_DRIVERS, gateway.driver, "gateway driver", gateway.config)
    if capture is not None:
        _check_known(CAPTURE_DRIVERS, capture.driver, "capture driver", capture.config)


def _check_known(
    registry: dict[str, DriverEntry[_RegistryT]], name: str, what: str, config: dict[str, Any]
) -> None:
    entry = registry.get(name)
    if entry is None:
        known = ", ".join(sorted(registry))
        raise ValueError(f"unknown {what} '{name}' (known: {known})")
    missing = sorted(key for key in entry.required if key not in config)
    if missing:
        raise ValueError(f"{what} '{name}' is missing required config key(s) {missing}")
