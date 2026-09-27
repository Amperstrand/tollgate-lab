"""Driver contracts for the scenario layer.

Four native Protocols (docs/SCENARIO-LAYER.md §1) plus the small value
objects they exchange. No runtime dependencies beyond stdlib: adapters bring
their own transports (VSSH, adb, HTTP, wf-recorder).

The `dict[str, Any]` payloads (`ClientDriver.status`, `GatewayDriver.advertisement`)
are arbitrary JSON from the wallet daemon and the gateway's Nostr events —
the parse contracts (kind 10021/1022, `used/allotment`) live in the
adapters, not in the contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

__all__ = [
    "CaptureDriver",
    "CaptureResult",
    "ClientDriver",
    "GatewayDriver",
    "PayReceipt",
    "PaymentActor",
    "ScenarioRoles",
    "SessionState",
    "Usage",
]


@dataclass(frozen=True)
class PayReceipt:
    """What a payment produced — one ecash spend through the tollgate."""

    sats: int
    strategy: str  # ux_button|token_paste|portal_tip03|cli|skip
    token: str = ""  # the token that was spent ("" if the actor did not log it)


@dataclass(frozen=True)
class Usage:
    """Parsed `/usage` view: used/allotment.

    `-1/-1` is the gateway's honest "no session for this identity" answer —
    host-side probes read it by design (the S5 lesson), so identity-scoped
    probes must run from inside the client.
    """

    used: int = -1
    allotment: int = -1

    @property
    def is_void(self) -> bool:
        """True when the view carries no session (`-1/-1`)."""
        return self.used < 0 and self.allotment < 0


@dataclass(frozen=True)
class SessionState:
    """Parsed `/session-state` answer: none | active | expired."""

    state: str

    def __post_init__(self) -> None:
        if self.state not in ("none", "active", "expired"):
            raise ValueError(f"unknown session state {self.state!r}")

    @property
    def is_active(self) -> bool:
        return self.state == "active"

    @classmethod
    def none(cls) -> SessionState:
        return cls("none")

    @classmethod
    def active(cls) -> SessionState:
        return cls("active")

    @classmethod
    def expired(cls) -> SessionState:
        return cls("expired")


@dataclass(frozen=True)
class CaptureResult:
    """What a capture driver produced: paths + durations."""

    video_path: Path | None = None
    frame_paths: tuple[Path, ...] = ()
    duration_s: float = 0.0


class ClientDriver(Protocol):
    """The paying device's wallet client (Omarchy VM, container, phone)."""

    name: str

    def connect_wifi(self, ssid: str, *, timeout_s: int = 60) -> None:
        """Join the given SSID (nmcli/adb/netsh — adapter's choice)."""
        ...

    def active_ssid(self) -> str | None:
        """Currently associated SSID, or None when disconnected."""
        ...

    def status(self) -> dict[str, Any]:
        """Wallet `/status` shape (balance + session summary)."""
        ...

    def inject_token(self, token: str) -> None:
        """Fund the wallet with an ecash token (clipboard/adb/type)."""
        ...

    def open_wallet_ux(self) -> None:
        """Open the wallet panel/app so UX-driven actors can click it."""
        ...


class PaymentActor(Protocol):
    """How the toll gets paid on this rig."""

    strategy: str  # ux_button|token_paste|portal_tip03|cli|skip

    def pay(self, client: ClientDriver, gateway: GatewayDriver) -> PayReceipt:
        """Perform one tollgate payment; raise on failure."""
        ...


class GatewayDriver(Protocol):
    """The tollgate gateway + counterparty wallet, as seen by one client."""

    def advertisement(self) -> dict[str, Any]:
        """Kind 10021 advertisement (ssid, pricing, mint)."""
        ...

    def usage(self, client: ClientDriver) -> Usage | None:
        """Identity-scoped `/usage` — MUST be probed from inside the client."""
        ...

    def session_state(self, client: ClientDriver) -> SessionState:
        """none/active/expired for this client's identity."""
        ...

    def external_reachable(self, client: ClientDriver) -> bool:
        """Can the client reach the paid internet segment?"""
        ...

    def mint_token(self, sats: int) -> str:
        """Mint a fresh ecash token from the counterparty (fake) wallet."""
        ...


class CaptureDriver(Protocol):
    """Video/frame capture — evidence stays first-class."""

    def start(self, artifact_dir: Path) -> None:
        """Begin recording into the artifact dir."""
        ...

    def step(self, name: str) -> None:
        """Mark a timeline event (frame grab / chapter marker)."""
        ...

    def stop(self) -> CaptureResult:
        """Finish recording; return paths + durations."""
        ...


@dataclass
class ScenarioRoles:
    """One composed rig: the four contracts bound to concrete adapters."""

    client: ClientDriver
    actor: PaymentActor
    gateway: GatewayDriver
    capture: CaptureDriver | None = None  # None = run without video evidence

    def __post_init__(self) -> None:
        if not self.client.name:
            raise ValueError("client driver must carry a non-empty name")
        if not self.actor.strategy:
            raise ValueError("payment actor must carry a non-empty strategy")
