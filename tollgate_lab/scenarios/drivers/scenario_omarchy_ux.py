"""Omarchy desktop wallet-UX client + pay-button actor.

Port of the validated rig semantics (omarchy-cashu vm.py + story-runner +
panel flow): guest execution rides the base64 round-trip VSSH channel,
screenshots come from grim inside the guest, template matching runs
locally (OpenCV), clicks dispatch via ydotool inside the guest — and every
click re-opens the wallet panel first (the 7ed5bdd lesson: a panel closed
by focus loss makes template matches stale; never click a possibly-hidden
panel). API calls into cashud run from inside the guest over the same
channel, matching story-runner's api/api_post helpers.

Unit tests drive the exec/vision/click seams with fakes — no guest, no
network, no Wayland (see tests/test_scenario_omarchy_ux.py).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

from tollgate_lab.scenarios.contract import ClientDriver, GatewayDriver, PayReceipt
from tollgate_lab.scenarios.drivers.ux_channel import (
    DEFAULT_GUEST_ENV,
    ClickBackend,
    ExecChannel,
    SshExec,
    YdotoolBackend,
    wait_until,
)
from tollgate_lab.scenarios.drivers.ux_vision import GuestVision, TemplateVision

__all__ = ["OmarchyUxClient", "UxButtonActor"]

_CASHUD_BASE = "http://127.0.0.1:3939"
_PANEL_TEMPLATE = "panel-open.png"
_WIFI_POLL_INTERVAL_S = 1.0
_SESSION_POLL_INTERVAL_S = 1.0
_OPEN_PANEL_TIMEOUT_S = 10.0


class ClickCapableClient(ClientDriver, Protocol):
    """A ClientDriver that can also locate and click on-screen templates."""

    def click_template(self, template: str) -> tuple[int, int]:
        """Re-open the panel, locate ``template``, click its center."""
        ...


class OmarchyUxClient:
    """ClientDriver over the Omarchy VM (mac80211_hwsim wifi + cashud)."""

    def __init__(
        self,
        *,
        vssh: str,
        templates: str | Path,
        name: str = "omarchy_ux",
        cashud_base: str = _CASHUD_BASE,
        guest_env: str = DEFAULT_GUEST_ENV,
        ydotool_socket: str = "/tmp/.ydotool_socket",
        shot_dir: str | Path = "/tmp/tollgate-lab-ux",
        panel_template: str = _PANEL_TEMPLATE,
        exec_channel: ExecChannel | None = None,
        vision: TemplateVision | None = None,
        click: ClickBackend | None = None,
    ) -> None:
        self.name = name
        self._templates = Path(templates)
        self._cashud = cashud_base.rstrip("/")
        self._panel_template = panel_template
        self._exec = exec_channel if exec_channel is not None else SshExec(vssh)
        self._vision = (
            vision
            if vision is not None
            else GuestVision(self._exec, self._templates, guest_env=guest_env, shot_dir=shot_dir)
        )
        self._click = (
            click
            if click is not None
            else YdotoolBackend(self._exec, ydotool_socket=ydotool_socket)
        )

    def connect_wifi(self, ssid: str, *, timeout_s: int = 60) -> None:
        """``nmcli dev wifi connect`` over VSSH, polled until associated."""
        self._exec.run(f"nmcli dev wifi connect {shlex.quote(ssid)}", timeout_s=timeout_s)
        wait_until(
            lambda: self._associated(ssid),
            timeout_s=float(timeout_s),
            interval_s=_WIFI_POLL_INTERVAL_S,
            describe=f"wifi associated with {ssid!r}",
            evidence=lambda: f"active_ssid={self.active_ssid()!r}",
        )

    def _associated(self, ssid: str) -> bool | None:
        return True if self.active_ssid() == ssid else None

    def active_ssid(self) -> str | None:
        """``nmcli -t -f ACTIVE,SSID dev wifi`` → ssid of the ACTIVE line."""
        out = self._exec.run("nmcli -t -f ACTIVE,SSID dev wifi")
        for line in out.splitlines():
            if line.startswith("yes:"):
                ssid = line.split(":", 1)[1]
                return ssid or None
        return None

    def status(self) -> dict[str, Any]:
        """``curl -s http://127.0.0.1:3939/status`` from inside the VM."""
        return self._api("GET", "/status")

    def inject_token(self, token: str) -> None:
        """Receive the token into the wallet over POST /receive.

        vm-testbed primes an offline stash token this way before the first
        payment — the unpaid gate blocks the mint, so funding must arrive
        as a bearer token, not a mint.
        """
        reply = self._api("POST", "/receive", {"token": token})
        if reply.get("ok") is not True:
            raise RuntimeError(f"wallet refused token: {reply!r}")

    def open_wallet_ux(self) -> None:
        """Open the cashu wallet panel via the plugin IPC, wait for chrome.

        ``bash -lc`` is required: omarchy-shell needs OMARCHY_PATH, which
        only login-shell profiles export (vm.py lesson — a bare shell
        silently no-ops the call).
        """
        self._exec.run("bash -lc 'omarchy-shell user.cashu open'")
        self._vision.wait_visible(self._panel_template, timeout_s=_OPEN_PANEL_TIMEOUT_S)

    def run_command(self, command: str, *, timeout_s: int = 15) -> str:
        """Run a shell command inside the VM over VSSH; return stdout."""
        return self._exec.run(command, timeout_s=float(timeout_s))

    def click_template(self, template: str) -> tuple[int, int]:
        """vfind the template, click its center — panel re-opened FIRST.

        7ed5bdd: a wallet panel closed by focus loss makes template
        matches stale; never click a possibly-hidden panel.
        """
        self.open_wallet_ux()
        match = self._vision.wait_visible(template)
        self._click.click_at(match.x, match.y)
        return match.x, match.y

    def _api(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if payload is None:
            command = f"curl -s --max-time 30 -X {method} {self._cashud}{path}"
        else:
            body = json.dumps(payload).replace("'", "'\\''")
            command = f"curl -s --max-time 30 -X {method} --json '{body}' {self._cashud}{path}"
        out = self._exec.run(command, timeout_s=35.0)
        try:
            reply = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"cashud {path} returned non-JSON: {out[:200]!r}") from exc
        if not isinstance(reply, dict):
            raise RuntimeError(f"cashud {path} returned {type(reply).__name__}, expected object")
        return reply


if TYPE_CHECKING:
    # Structural conformance to the ClientDriver contract, checked by mypy.
    _client_conforms: ClientDriver = cast("OmarchyUxClient", None)


class UxButtonActor:
    """PaymentActor that clicks the panel's Pay TollGate button."""

    strategy = "ux_button"

    def __init__(
        self,
        *,
        template: str = "btn-pay-tollgate.png",
        session_timeout_s: float = 30.0,
        poll_interval_s: float = _SESSION_POLL_INTERVAL_S,
    ) -> None:
        self._template = template
        self._timeout_s = session_timeout_s
        self._interval_s = poll_interval_s

    def pay(self, client: ClientDriver, gateway: GatewayDriver, *, sats: int) -> PayReceipt:
        """Open panel → vfind pay button → click → wait for the session.

        Success signal is a live session in the wallet's /status (the bar
        label's countdown reads the same state). The receipt's sats come
        from the session's ``cost_sats`` — what the gateway actually
        charged for this click, not an assumption.
        """
        ux = _as_click_capable(client)
        ux.click_template(self._template)  # click_template re-opens the panel (7ed5bdd)
        session = wait_until(
            lambda: _live_session(ux.status()),
            timeout_s=self._timeout_s,
            interval_s=self._interval_s,
            describe="wallet session live after pay click",
            evidence=lambda: f"status={ux.status()!r}"[:500],
        )
        sats = session.get("cost_sats")
        if not isinstance(sats, int) or sats <= 0:
            raise RuntimeError(f"live session lacks a positive cost_sats: {session!r}")
        return PayReceipt(sats=sats, strategy=self.strategy)


def _as_click_capable(client: ClientDriver) -> ClickCapableClient:
    click = getattr(client, "click_template", None)
    if not callable(click):
        raise TypeError(
            "ux_button actor needs a client with click_template() "
            f"(the OmarchyUxClient), got {type(client).__name__}"
        )
    return cast("ClickCapableClient", client)


def _live_session(status: dict[str, Any]) -> dict[str, Any] | None:
    session = status.get("session")
    if isinstance(session, dict) and session.get("remaining", 0) > 0:
        return session
    return None
