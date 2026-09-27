"""SPEC STUB — HTTP-module tollgate gateway adapter.

vm-testbed's parse contracts, wrapped as a GatewayDriver. The body is a
NotImplementedError placeholder; this docstring is the porting spec.

Semantics to preserve (docs/SCENARIO-LAYER.md §4):

- **Advertisement** — Nostr kind **10021** event fetched from the gateway
  base URL; exposes the AP ssid and ``price_per_step`` pricing tags.
- **Session** — kind **1022** events; ``/usage`` parses to
  ``used/allotment``.
- **-1/-1 by design** — the gateway scopes /usage to the client identity
  (socket MAC). A host-side probe reads ``-1/-1`` even while the client's
  session is live. Therefore ``usage``/``session_state`` MUST execute their
  HTTP probes **from inside the client** (the S5 lesson) — e.g. through the
  Omarchy client's VSSH channel or the phone's adb shell.
- **external_reachable** — probe a paid-segment address from inside the
  client; the nft valve only opens the toll segment while a session lives.
- **mint_token** — counterparty (fake) wallet mints a bearer Cashu token;
  never the client's own wallet. ``token_source: fakewallet`` in the
  profile selects the vm-testbed fakewallet.
"""

from __future__ import annotations

from tollgate_lab.scenarios.contract import (
    ClientDriver,
    SessionState,
    Usage,
)

__all__ = ["HttpModuleGateway"]


class HttpModuleGateway:
    """GatewayDriver over the tollgate gateway's HTTP module (:2121)."""

    def __init__(self, *, base: str, token_source: str = "fakewallet") -> None:
        self._base = base.rstrip("/")
        self._token_source = token_source

    def advertisement(self) -> dict[str, object]:
        """GET the kind 10021 advertisement; parse ssid + pricing tags.

        The lifecycle reads ``ssid`` from the returned mapping — it must be
        present.
        """
        raise NotImplementedError("port vm-testbed advertisement parse (kind 10021)")

    def usage(self, client: ClientDriver) -> Usage | None:
        """GET /usage FROM INSIDE the client; parse used/allotment.

        Host-side execution returns -1/-1 by design — the probe must ride
        the client's own channel (VSSH / adb / container shell).
        """
        raise NotImplementedError("port vm-testbed /usage parse (identity-scoped, from client)")

    def session_state(self, client: ClientDriver) -> SessionState:
        """GET /session-state?mac=… from inside the client.

        Maps none/active/expired onto SessionState. Requires the client
        identity (MAC) the gateway derives the session from.
        """
        raise NotImplementedError("port /session-state probe (identity-scoped, from client)")

    def external_reachable(self, client: ClientDriver) -> bool:
        """Probe the paid internet segment from inside the client."""
        raise NotImplementedError("port paid-segment reachability probe (from client)")

    def mint_token(self, sats: int) -> str:
        """Mint a bearer Cashu token via the counterparty wallet."""
        raise NotImplementedError("port fakewallet counterparty mint")
