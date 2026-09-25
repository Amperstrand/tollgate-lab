"""ZyxelPoEDriver — per-port PoE control for the GS1900-8HP bench switch.

Speaks the Amperstrand realtek-poe fork's ubus object over SSH (key auth):

    ubus call poe manage '{"port":"lanN","action":"enable"|"disable"}'
    ubus call poe info

Design decisions and the comparison against the previous conwrt_poe
NetworkPowerPort backend are recorded in the conwrt repo:
labgrid/POE-BACKEND-DECISION.md. Security posture: SSH key auth only,
no uhttpd-mod-ubus / unauthenticated-ubus HTTP ACLs on the switch, host
keys verified via accept-new.

Operational hardening ported from conwrt_poe.py (verified against two
live wedge incidents, 2026-09-2x):
- A wedged realtek-poe daemon answers `poe info` with a frozen snapshot
  while silently dropping `manage` calls (rc=0, state never changes).
  Every set is therefore followed by poll-until-reflected verification.
- A HEALTHY manage's status readback can lag ~30 s (MCU settle): frozen
  digests inside the settling window are not wedge evidence (T23).
- The poe service is NEVER restarted from tooling: it power-blips every
  PD on the switch. Wedged-daemon recovery = take the bench lock
  (amperstrand-bench flock), coordinate, restart /etc/init.d/poe by hand.
"""

import json
import logging
import subprocess
import time

import attr
from labgrid import target_factory
from labgrid.driver import Driver
from labgrid.driver.exception import ExecutionError
from labgrid.driver.powerdriver import PowerResetMixin
from labgrid.protocol.powerprotocol import PowerProtocol
from labgrid.resource.common import Resource
from labgrid.step import step

#: Ports that must never be power-cycled on the bench switch:
#: lan1 = lab-LAN uplink + DUT-VLAN trunk, lan8 = cascade to GS1900-8HP #2.
PROTECTED_PORTS = frozenset({"lan1", "lan8"})

#: Status strings meaning "port is off / not powered".
OFF_STATES = frozenset({"disabled", "off", "", "fault"})
#: Status strings that are neither on nor off yet — never accepted as a
#: verification match.
TRANSIENT_STATES = frozenset({"initializing", "unknown"})

#: Healthy readback lag tolerance before a frozen snapshot counts as a wedge.
SETTLING_S = 35.0
#: Total window for a manage to become visible in `poe info`.
VERIFY_TIMEOUT_S = 60.0
#: How long a frozen (state, watts) digest must persist past SETTLING_S to
#: be judged a wedged daemon.
FROZEN_GRACE_S = 6.0
POLL_INTERVAL_S = 0.8

#: The PoE MCU intermittently rejects manage commands (not-ready /
#: bad-checksum class, observed live 2026-09-25) with rc=0. One bounded
#: retry absorbs the transient; a second frozen window is a real wedge.
MANAGE_ATTEMPTS = 2

#: Reuse one authenticated connection across verification polls.
SSH_OPTS = (
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ControlMaster=auto",
    "-o", "ControlPath=/tmp/tlab-poe-%r@%h:%p",
    "-o", "ControlPersist=30s",
)


@target_factory.reg_resource
@attr.s(eq=False)
class ZyxelPoePort(Resource):
    """One PoE port on the OpenWrt-managed Zyxel GS1900-8HP bench switch.

    Args:
        host (str): management IP of the switch (SSH, key auth)
        port (str): switch port name, e.g. "lan5"
        username (str): SSH user on the switch (default "root")
    """

    host = attr.ib(validator=attr.validators.instance_of(str))
    port = attr.ib(validator=attr.validators.instance_of(str))
    username = attr.ib(default="root", validator=attr.validators.instance_of(str))


@target_factory.reg_driver
@attr.s(eq=False)
class ZyxelPoEDriver(Driver, PowerResetMixin, PowerProtocol):
    """SSH + ubus PoE port control for the GS1900-8HP bench switch.

    Bind to a ZyxelPoePort resource in your environment YAML:

    ```yaml
    targets:
      main:
        resources:
          ZyxelPoePort:
            host: "192.168.13.2"
            port: "lan5"
        drivers:
          ZyxelPoEDriver: {}
    ```
    """

    bindings = {"port": "ZyxelPoePort"}

    #: Seconds between off() and on() in cycle(): the BCM59121 PoE controller
    #: needs 5-10 s to renegotiate after a disable/enable; 8 s matches the
    #: conwrt-proven flash flow. Do not go below 7.
    delay = attr.ib(default=8.0, validator=attr.validators.instance_of(float))
    #: Timeout for each individual SSH invocation against the switch.
    ssh_timeout = attr.ib(default=15.0, validator=attr.validators.instance_of(float))

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.logger = logging.getLogger(f"{self}({self.target})")

    # -- low-level helpers -------------------------------------------------

    def _assert_not_protected(self):
        if self.port.port in PROTECTED_PORTS:
            raise ExecutionError(
                f"refusing to toggle protected port {self.port.port!r} "
                f"(protected: {sorted(PROTECTED_PORTS)})"
            )

    def _ssh(self, command):
        """Run a command on the switch via SSH (key auth only)."""
        args = [
            "ssh", *SSH_OPTS,
            f"{self.port.username}@{self.port.host}",
            command,
        ]
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.ssh_timeout,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ExecutionError(
                f"switch command failed ({command!r}): {exc.stderr.strip()}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExecutionError(
                f"switch command timed out after {self.ssh_timeout}s: {command!r}"
            ) from exc
        return result.stdout

    def _port_snapshot(self):
        """Return (status, watts) for the bound port from `poe info`."""
        info = json.loads(self._ssh("ubus call poe info"))
        ports = info.get("ports", {})
        entry = None
        if isinstance(ports, dict):
            entry = ports.get(self.port.port)
        elif isinstance(ports, list):
            entry = next((p for p in ports if p.get("port") == self.port.port), None)
        if entry is None:
            raise ExecutionError(
                f"port {self.port.port!r} not present in poe info "
                f"(ports: {sorted(ports) if isinstance(ports, dict) else 'list'})"
            )
        if isinstance(entry, dict):
            status = str(entry.get("status", "unknown")).strip()
            try:
                watts = float(entry.get("consumption", 0.0))
            except (TypeError, ValueError):
                watts = 0.0
        else:
            status, watts = str(entry).strip(), 0.0
        return status, watts

    def _verify_manage(self, want_disabled):
        """Poll until the port reflects the requested state.

        Raises ExecutionError on a frozen snapshot (wedged daemon, DROPPED)
        or on timeout (UNVERIFIED). Never restarts the poe service — that
        power-blips every PD on the switch (bench rule; see module docstring).
        """
        started = time.monotonic()
        deadline = started + VERIFY_TIMEOUT_S
        frozen_since = None
        last_digest = None
        last_state = ""
        while time.monotonic() < deadline:
            last_state, watts = self._port_snapshot()
            state = last_state.lower()
            disabled = state in OFF_STATES
            if disabled == want_disabled and state not in TRANSIENT_STATES:
                return
            digest = f"{state}:{watts:.3f}"
            now = time.monotonic()
            if now - started < SETTLING_S:
                frozen_since = None
            elif digest == last_digest:
                if frozen_since is None:
                    frozen_since = now
                elif now - frozen_since > FROZEN_GRACE_S:
                    raise ExecutionError(
                        f"poe manage DROPPED: {self.port.port} snapshot frozen "
                        f"at '{last_state}' ({watts:.1f}W) for "
                        f">{FROZEN_GRACE_S:.0f}s past the {SETTLING_S:.0f}s "
                        "readback-lag window — wedged daemon. Do NOT restart "
                        "the poe service from tooling (power-blips every PD); "
                        "take the bench lock and coordinate, then restart "
                        "/etc/init.d/poe manually."
                    )
            else:
                frozen_since = None
            last_digest = digest
            time.sleep(POLL_INTERVAL_S)
        raise ExecutionError(
            f"poe manage UNVERIFIED: {self.port.port} still '{last_state}' "
            f"after {VERIFY_TIMEOUT_S:.0f}s (wanted "
            f"{'disabled-class' if want_disabled else 'active-class'})"
        )

    def _set(self, enable):
        self._assert_not_protected()
        payload = json.dumps(
            {"port": self.port.port, "action": "enable" if enable else "disable"}
        )
        for attempt in range(1, MANAGE_ATTEMPTS + 1):
            self._ssh(f"ubus call poe manage '{payload}'")
            try:
                self._verify_manage(want_disabled=not enable)
                return
            except ExecutionError as exc:
                is_drop = "DROPPED" in str(exc)
                if not is_drop or attempt == MANAGE_ATTEMPTS:
                    raise
                self.logger.warning(
                    "poe manage dropped (attempt %d/%d) — retrying once",
                    attempt, MANAGE_ATTEMPTS,
                )

    # -- PowerProtocol ------------------------------------------------------

    @Driver.check_active
    @step()
    def on(self):
        """Enable PoE on the bound port (verified in `poe info`)."""
        self._set(True)

    @Driver.check_active
    @step()
    def off(self):
        """Disable PoE on the bound port (verified in `poe info`)."""
        self._set(False)

    @Driver.check_active
    @step()
    def cycle(self):
        """Power-cycle: off, wait ``delay`` s (BCM59121 renegotiation), on."""
        self.off()
        time.sleep(self.delay)
        self.on()

    # -- introspection ------------------------------------------------------

    @Driver.check_active
    @step()
    def get_status(self):
        """Raw PoE status string for the bound port.

        Observed on the live switch: "Delivering power", "Searching",
        "Disabled", "Other fault".
        """
        status, _watts = self._port_snapshot()
        return status

    @Driver.check_active
    @step()
    def get(self):
        """True iff the port is in an enabled/active state (not off-class)."""
        status, _watts = self._port_snapshot()
        return status.lower() not in OFF_STATES
