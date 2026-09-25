"""PoE port power control for OpenWrt switches running realtek-poe.

Implements the labgrid-shaped power interface (``on`` / ``off`` / ``cycle`` /
``status``) over the hardware-verified path used by conwrt: SSH to the
switch, ``ubus call poe manage``, then VERIFY by polling ``ubus call poe
info`` — command success is never treated as power state (the labgrid
NetworkPowerDriver pattern; realtek-poe issue #10 shows status can read
``initializing``/``unknown`` transiently).

Port status is a rich enum, not a boolean: ``SEARCHING`` means the PSE is
admin-enabled but no PD is drawing (device absent or not negotiating),
``FAULT``/``OTHER_FAULT`` need switch-side diagnosis — distinctions that are
lost if everything collapses to True/False (RFC 3621 state model).

Guard rails baked in:

- minimum off-time on ``cycle()`` (default 8 s) — the BCM59121 controller
  needs 5-10 s to renegotiate after a disable/enable pair (conwrt-verified
  on the GS1900-8HP);
- ``initializing``/``unknown`` are treated as transient while polling;
- ``on()`` warns when switch consumption plus the port's power budget would
  exceed the PoE budget (the MCU load-sheds by priority when over budget —
  that would silently power off OTHER lab devices).

Switch host and credentials are supplied by the caller (from gitignored
inventory), never from module constants. Logs carry port names and states,
not the switch address.
"""

from __future__ import annotations

import enum
import json
import logging
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("tollgate_lab.poe")

# Statuses that mean "admin state reached, PD state still settling".
_TRANSIENT = {"INITIALIZING", "UNKNOWN"}


class PoeError(RuntimeError):
    """PoE control failure — raised loudly, never a silent sentinel."""


class PoeUnresponsiveError(PoeError):
    """The daemon answers but its snapshot is frozen: manage calls are
    silently dropped (daemon<->MCU link wedged). See PoePowerController._poll
    for the recovery procedure and its cross-session power-blip warning."""


class PoeProtectedPortError(PoeError):
    """The port is inventory-protected for physical reasons (one-way-trip
    TFTP units, uplink trunks) — refused before any ubus call is issued."""


class PoeStatus(enum.Enum):
    """Operational port state from ``ubus call poe info`` (realtek-poe strings)."""

    DISABLED = "Disabled"
    SEARCHING = "Searching"
    REQUESTING = "Requesting power"
    DELIVERING = "Delivering power"
    FAULT = "Fault"
    OTHER_FAULT = "Other fault"
    INITIALIZING = "initializing"  # daemon has not queried the MCU yet (issue #10)
    UNKNOWN = "unknown"

    @classmethod
    def from_switch(cls, raw: str) -> PoeStatus:
        norm = raw.strip().lower()
        for member in cls:
            if member.value.lower() == norm:
                return member
        raise PoeError(f"unrecognised PoE port status {raw!r}")


@dataclass(frozen=True)
class PoePortInfo:
    port: str
    status: PoeStatus
    priority: int = 0
    consumption_w: float = 0.0
    power_budget_w: float = 0.0

    @property
    def powered(self) -> bool:
        """True only when a PD is actually drawing power."""
        return self.status is PoeStatus.DELIVERING


@dataclass(frozen=True)
class PoeSwitchInfo:
    budget_w: float
    consumption_w: float
    ports: dict[str, PoePortInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class PoeControllerConfig:
    host: str
    username: str = "root"
    keyfile: str | None = None
    port: int = 22
    ssh_timeout_s: float = 10.0
    command_timeout_s: float = 20.0
    poll_interval_s: float = 1.0
    frozen_grace_s: float = 30.0
    protected_ports: frozenset[str] = frozenset()


class PoePowerController:
    """Per-port PoE control on one OpenWrt switch (realtek-poe over SSH).

    Usage::

        ctl = PoePowerController(PoeControllerConfig(host="<from inventory>"))
        ctl.cycle("lan2")                       # off -> min-off-time -> on
        ctl.assert_delivering("lan2", timeout=90)  # device actually powered
    """

    def __init__(self, config: PoeControllerConfig) -> None:
        self.config = config

    # -- switch transport ---------------------------------------------------

    def _ssh(self, cmd: str, timeout: float | None = None) -> str:
        args = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", f"ConnectTimeout={int(self.config.ssh_timeout_s)}",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
        ]
        if self.config.keyfile:
            args += ["-i", self.config.keyfile, "-o", "IdentitiesOnly=yes"]
        if self.config.port != 22:
            args += ["-p", str(self.config.port)]
        args += [f"{self.config.username}@{self.config.host}", cmd]
        proc = subprocess.run(  # noqa: S604 - fixed argv, no shell
            args,
            capture_output=True,
            text=True,
            timeout=timeout or self.config.command_timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            raise PoeError(f"switch ssh rc={proc.returncode}: {proc.stderr.strip()[:200]}")
        return proc.stdout

    def _ubus(self, path: str, payload: str | None = None) -> str:
        call = f"ubus call {path}"
        if payload is not None:
            call += f" {shlex.quote(payload)}"
        return self._ssh(call)

    # -- state --------------------------------------------------------------

    def info(self) -> PoeSwitchInfo:
        raw = self._ubus("poe", "info")
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as e:
            raise PoeError(f"poe info is not JSON: {raw[:120]!r}") from e
        ports: dict[str, PoePortInfo] = {}
        for name, entry in doc.get("ports", {}).items():
            ports[name] = PoePortInfo(
                port=name,
                status=PoeStatus.from_switch(entry.get("status", "unknown")),
                priority=int(entry.get("priority", 0)),
                consumption_w=float(entry.get("consumption", 0.0)),
                power_budget_w=float(entry.get("power_budget", entry.get("power_budget_w", 0.0))),
            )
        return PoeSwitchInfo(
            budget_w=float(doc.get("budget", 0.0)),
            consumption_w=float(doc.get("consumption", 0.0)),
            ports=ports,
        )

    def port_status(self, port: str) -> PoePortInfo:
        info = self.info()
        try:
            return info.ports[port]
        except KeyError:
            raise PoeError(
                f"switch has no PoE port {port!r} (known: {sorted(info.ports)})"
            ) from None

    # -- control ------------------------------------------------------------

    def _manage(self, port: str, enable: bool) -> None:
        """Set admin state. Live-verified ubus schemas (2026-09-22):
        ``poe manage {"port","action":"enable"|"disable"}`` and the older
        ``poe set_port_config {"port","enable":bool}``. Try action-based
        manage first (declared schema on the Amperstrand fork), fall back
        to set_port_config once. Protected ports are refused before any
        switch interaction."""
        if port in self.config.protected_ports:
            raise PoeProtectedPortError(
                f"poe {port}: inventory-protected port — power control refused "
                "(one-way-trip or uplink port; see configs/labgrid/"
                "inventory.local.yaml protected_ports)"
            )
        action = "enable" if enable else "disable"
        calls = (
            ("manage", json.dumps({"port": port, "action": action})),
            ("set_port_config", json.dumps({"port": port, "enable": enable})),
        )
        errors: list[str] = []
        for method, payload in calls:
            try:
                self._ubus(f"poe {method}", payload)
                return
            except PoeError as e:
                errors.append(f"{method}: {e}")
        raise PoeError(f"poe {port} {action} failed on both interfaces: {errors}")

    def on(self, port: str, timeout_s: float = 45.0, strict_budget: bool = False) -> PoePortInfo:
        """Admin-enable the port and verify it left DISABLED.

        Note: with no PD attached the port settles in SEARCHING — that is a
        correct admin-on. Use ``assert_delivering()`` when a device must be
        actually powered."""
        info = self.info()
        if port in info.ports:
            entry = info.ports[port]
            projected = info.consumption_w + entry.power_budget_w
            if projected > info.budget_w > 0:
                msg = (
                    f"poe {port}: enabling projects {projected:.1f}W over the "
                    f"{info.budget_w:.1f}W budget — the MCU may load-shed "
                    f"OTHER ports by priority"
                )
                if strict_budget:
                    raise PoeError(msg)
                log.warning("%s", msg)
        self._manage(port, True)
        return self._wait_not_in(port, {PoeStatus.DISABLED}, timeout_s)

    def off(self, port: str, timeout_s: float = 45.0) -> PoePortInfo:
        """Admin-disable the port and verify it reached DISABLED."""
        self._manage(port, False)
        return self._wait_in(port, {PoeStatus.DISABLED}, timeout_s, manage_pending=True)

    def cycle(self, port: str, min_off_s: float = 8.0, timeout_s: float = 45.0) -> PoePortInfo:
        """Cold power-cycle: off, honour the BCM59121 minimum off-time, on."""
        self.off(port, timeout_s=timeout_s)
        log.info("poe %s: holding off for %.1fs (controller renegotiation)", port, min_off_s)
        time.sleep(min_off_s)
        return self.on(port, timeout_s=timeout_s)

    def assert_delivering(self, port: str, timeout_s: float = 90.0) -> PoePortInfo:
        """Fail loudly unless a PD is drawing power on *port* within *timeout_s*.

        SEARCHING at deadline means: cable unplugged, device absent, or PoE
        negotiation failure — never a silent pass."""
        return self._wait_in(port, {PoeStatus.DELIVERING}, timeout_s)

    # -- polling ------------------------------------------------------------

    def _poll(
        self,
        port: str,
        done: Callable[[PoePortInfo], bool],
        timeout_s: float,
        manage_pending: bool,
    ) -> PoePortInfo:
        """Poll the port until *done*; detect dropped manage calls.

        A wedged realtek-poe (single process, service 'running') can keep
        answering `poe info` with jittery data from OTHER ports while
        silently dropping manage calls — observed live 2026-09-22 (manage
        rc=0, target port state never changed, port-level snapshot frozen
        while switch-level consumption still jittered). So the freeze
        detector tracks ONLY the target port's (status, watts) digest,
        and only fires when a manage is pending: an absent PD legally
        parks a port in SEARCHING forever, which is a PD problem, not a
        daemon problem. Never restart the daemon to 'fix' a PD problem —
        restart power-blips EVERY PD on the switch; take the bench lock
        and coordinate first."""
        deadline = time.monotonic() + timeout_s
        frozen_since: float | None = None
        last_digest = ""
        last: PoePortInfo | None = None
        while time.monotonic() < deadline:
            info = self.info()
            last = info.ports.get(port)
            if last is None:
                raise PoeError(
                    f"switch has no PoE port {port!r} (known: {sorted(info.ports)})"
                )
            if done(last):
                return last
            digest = f"{last.status.name}:{last.consumption_w:.6f}"
            now = time.monotonic()
            if digest == last_digest:
                if frozen_since is None:
                    frozen_since = now
                elif (
                    manage_pending
                    and now - frozen_since > self.config.frozen_grace_s
                ):
                    raise PoeUnresponsiveError(
                        f"poe {port}: port state frozen for "
                        f"{now - frozen_since:.0f}s after an admin change — "
                        "the realtek-poe daemon is dropping manage calls "
                        "(daemon<->MCU link likely wedged). Recovery: "
                        "'killall -9 realtek-poe; /etc/init.d/poe start' — "
                        "WARNING: restart power-blips EVERY PD on the switch; "
                        "take the bench lock and coordinate first."
                    )
            else:
                frozen_since = None
            last_digest = digest
            time.sleep(self.config.poll_interval_s)
        assert last is not None
        raise PoeError(
            f"poe {port}: timed out after {timeout_s:.0f}s waiting for state "
            f"change, last={last.status.name} ({last.consumption_w:.1f}W) — "
            "snapshot was still updating (not frozen); check the PD/port"
        )

    def _wait_in(
        self, port: str, wanted: set[PoeStatus], timeout_s: float, manage_pending: bool = False
    ) -> PoePortInfo:
        return self._poll(
            port, lambda p: p.status in wanted, timeout_s, manage_pending
        )

    def _wait_not_in(self, port: str, forbidden: set[PoeStatus], timeout_s: float) -> PoePortInfo:
        return self._poll(
            port,
            lambda p: p.status not in forbidden and p.status not in _TRANSIENT,
            timeout_s,
            manage_pending=True,
        )
