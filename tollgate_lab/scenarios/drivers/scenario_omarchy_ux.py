"""SPEC STUB — Omarchy desktop wallet-UX client + pay-button actor.

Port of vm-testbed's uilib semantics (host/uilib.sh + vfind.py +
story-runner.sh). Every method raises NotImplementedError until Phase 1 of
the migration (docs/SCENARIO-LAYER.md) ports the bodies; the docstrings are
the porting spec.

Semantics to preserve:

- **vfind template match** — OpenCV ``matchTemplate`` over a Wayland
  screencopy grab; returns the best match's center once it clears the
  threshold, else fails. Templates come from the profile's ``templates``
  directory (e.g. ``vm-testbed/host/templates``).
- **ydotool via VSSH** — clicks/keys are dispatched through the VM's SSH
  channel (``$VSSH "ydotool click …"``), never from the host's own seat.
- **Re-open the panel before EVERY click** (the 7ed5bdd lesson) — a wallet
  panel closed by focus loss makes template matches stale; never click a
  possibly-hidden panel. ``_click_template`` must call
  ``client.open_wallet_ux()`` immediately before matching.
- API calls into cashud (``http://127.0.0.1:3939``) run from inside the VM
  over VSSH, matching story-runner's ``api``/``api_post`` helpers.
"""

from __future__ import annotations

from pathlib import Path

from tollgate_lab.scenarios.contract import (
    ClientDriver,
    GatewayDriver,
    PayReceipt,
)

__all__ = ["OmarchyUxClient", "UxButtonActor"]


class OmarchyUxClient:
    """ClientDriver over the Omarchy VM (mac80211_hwsim wifi + cashud)."""

    def __init__(self, *, vssh: str, templates: str | Path, name: str = "omarchy_ux") -> None:
        self.name = name
        self._vssh = vssh
        self._templates = Path(templates)

    def connect_wifi(self, ssid: str, *, timeout_s: int = 60) -> None:
        """``nmcli dev wifi connect`` over VSSH, polled until associated."""
        raise NotImplementedError("port vm-testbed uilib wifi_connect (nmcli via VSSH)")

    def active_ssid(self) -> str | None:
        """``nmcli -t -f ACTIVE,SSID dev wifi`` → ssid of the ACTIVE line."""
        raise NotImplementedError("port vm-testbed uilib active_ssid (nmcli via VSSH)")

    def status(self) -> dict[str, object]:
        """``curl -s http://127.0.0.1:3939/status`` from inside the VM.

        Must include ``balance_sats`` (int) — the lifecycle's wallet_fresh
        and wallet_drained steps assert on it.
        """
        raise NotImplementedError("port story-runner api('/status') over VSSH")

    def inject_token(self, token: str) -> None:
        """Receive the token into the wallet: wl-copy + POST /receive.

        vm-testbed primes an offline stash token this way before the first
        payment — the unpaid gate blocks the mint, so funding must arrive
        as a bearer token, not a mint.
        """
        raise NotImplementedError("port story-runner api_post('/receive', {token})")

    def open_wallet_ux(self) -> None:
        """Open the cashu wallet panel from the bar widget via ydotool."""
        raise NotImplementedError("port uilib open_panel (bar widget click via ydotool)")

    def click_template(self, template: str) -> tuple[int, int]:
        """vfind the template, click its center with ydotool.

        MUST re-open the wallet panel first (7ed5bdd): stale panels make
        template matches lie.
        """
        raise NotImplementedError("port uilib click_template (vfind + ydotool via VSSH)")


class UxButtonActor:
    """PaymentActor that clicks the panel's Pay TollGate button."""

    strategy = "ux_button"

    def __init__(self, *, template: str = "btn-pay-tollgate.png") -> None:
        self._template = template

    def pay(self, client: ClientDriver, gateway: GatewayDriver) -> PayReceipt:
        """Open panel → vfind pay button → click → wait for session.

        Success signal is the bar label's session countdown (⏱) or a fresh
        /usage allotment, matching the DEMO story's pay step. Returns a
        PayReceipt with the profile's sats and strategy 'ux_button'.
        """
        raise NotImplementedError(
            "port uilib pay flow: open_wallet_ux → click_template → await countdown"
        )
