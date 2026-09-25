"""StockZyxelPoEDriver — per-port PoE control for the STOCK-firmware
GS1900-8HP #2 (ZyXEL V2.90) via its dispatcher.cgi web API.

This is the stock-firmware sibling of ZyxelPoEDriver (OpenWrt/ubus/SSH):
same PowerProtocol surface, same verify-after-set discipline, opposite
transport. Architecture decision: ~/conwrt-bench/docs/poe-backend-decision.md
(client-side Driver + scalar Resource; NO NetworkPowerPort model backends,
NO site-packages patching).

The HTTP client is NOT reimplemented here — it lives in the bench SSOT repo
as ~/conwrt-bench/tools/zyxel_stock.py (StockWeb: two-phase login, full-field
read-modify-write cmd=775, re-poll verification). This driver imports it
lazily (path overridable via BENCH_TOOLS_PATH env) and adds labgrid plumbing,
bench flock serialization, and wedge-class verification.

Stock-firmware failure classes this guards against (see
~/conwrt-bench/docs/stock-2.90-investigation.md, live-verified 2026-09-25):
- cmd=775 responses LIE: partial-field POSTs return an error page while
  still applying the change -> every write is verified by cmd=773 re-poll;
  the client's read-modify-write keeps sibling fields from drifting.
- Only ONE web session per user (fresh login can return NotAuth) ->
  login-shaped responses trigger exactly one re-login.
- (Defensive, unobserved on stock:) a frozen cmd=773 snapshot past the
  settle window is treated as a wedge and reported, never claimed success.
"""

import fcntl
import logging
import os
import re
import sys
import time
from contextlib import contextmanager

import attr
from labgrid import target_factory
from labgrid.driver import Driver
from labgrid.driver.exception import ExecutionError
from labgrid.driver.powerdriver import PowerResetMixin
from labgrid.protocol.powerprotocol import PowerProtocol
from labgrid.resource.common import Resource
from labgrid.step import step

#: Stock-switch port whose PoE must never be toggled from tooling:
#: p1 = lab-LAN uplink (PoE-disable would not cut the link, but the uplink
#: port is out of mandate for power ops; owner-gated manual only).
PROTECTED_PORTS = frozenset({"p1"})

#: Bench-wide mutual exclusion for switch operations (shared with the
#: OpenWrt-side driver flows and manual maintenance — see AGENTS bench rule).
BENCH_LOCK = "/tmp/amperstrand-bench"

#: Mirrors ZyxelPoEDriver timing so both switches verify identically.
SETTLING_S = 35.0        # healthy readback lag tolerated before wedge logic
VERIFY_TIMEOUT_S = 60.0  # total window for a toggle to reflect in cmd=773
FROZEN_GRACE_S = 6.0     # frozen-row persistence past SETTLING_S => wedge
POLL_INTERVAL_S = 1.5    # web polls are slower than ubus; stay gentle
LOCK_TIMEOUT_S = 120.0

_DEFAULT_TOOLS = os.environ.get("BENCH_TOOLS_PATH", "/home/ubuntu/conwrt-bench/tools")
_BENCH_SECRETS = os.environ.get(
    "BENCH_SECRETS", "/home/ubuntu/conwrt-bench/secrets/secrets.json")


def _make_web(host: str, password: str, user: str):
    """StockWeb from the shared library; falls back to the bench SSOT copy
    until tollgate_lab.hardware.zyxel_stock lands (owner layering update,
    2026-09-25: the library path is canonical, the tools copy becomes a thin
    wrapper — never vendor the client into this driver)."""
    try:
        from tollgate_lab.hardware.zyxel_stock import StockWeb
        return StockWeb(host, password, user)
    except ImportError:
        if _DEFAULT_TOOLS not in sys.path:
            sys.path.insert(0, _DEFAULT_TOOLS)
        from zyxel_stock import StockWeb
        return StockWeb(host, password, user)


def _resolve_password() -> str:
    """STOCK_ZYXEL_PASSWORD > BENCH_ROOT_PW > sops fleet.bench_root_password.

    The password is never logged, never embedded in exceptions raised onward.
    """
    if os.environ.get("STOCK_ZYXEL_PASSWORD"):
        return os.environ["STOCK_ZYXEL_PASSWORD"]
    if os.environ.get("BENCH_ROOT_PW"):
        return os.environ["BENCH_ROOT_PW"]
    import json
    import subprocess
    env = os.environ.copy()
    env.setdefault("SOPS_AGE_KEY_FILE",
                   os.path.expanduser("~/.config/age/keys.txt"))
    out = subprocess.run(
        ["sops", "-d", _BENCH_SECRETS],
        capture_output=True, text=True, timeout=20, env=env, check=True,
    ).stdout
    return json.loads(out)["fleet"]["bench_root_password"]


@contextmanager
def _bench_flock(timeout: float = LOCK_TIMEOUT_S):
    """Serialize switch-wide ops across agents (bench discipline)."""
    fd = os.open(BENCH_LOCK, os.O_CREAT | os.O_RDWR, 0o666)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise ExecutionError(
                        f"bench lock {BENCH_LOCK} busy >{timeout:.0f}s — "
                        "another agent holds the switch")
                time.sleep(0.5)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@target_factory.reg_resource
@attr.s(eq=False)
class StockZyxelPoePort(Resource):
    """One PoE port on the stock-firmware Zyxel GS1900-8HP #2.

    Wire-safe scalar attrs only (exported via the coordinator with the
    ResourceEntry fallback — same pattern as ZyxelPoePort).

    Args:
        host (str): management IP of the stock switch (web API)
        port (str): switch port, "p2" or "2" (normalized internally)
        username (str): web user (default "admin")
    """

    host = attr.ib(validator=attr.validators.instance_of(str))
    port = attr.ib(validator=attr.validators.instance_of(str))
    username = attr.ib(default="admin", validator=attr.validators.instance_of(str))

    @property
    def port_no(self) -> int:
        m = re.fullmatch(r"p?(\d+)", self.port.strip().lower())
        if not m or not 1 <= int(m.group(1)) <= 8:
            raise ExecutionError(f"invalid stock port {self.port!r} (want p1..p8)")
        return int(m.group(1))


@target_factory.reg_driver
@attr.s(eq=False)
class StockZyxelPoEDriver(Driver, PowerResetMixin, PowerProtocol):
    """Web-API PoE control for the stock GS1900-8HP.

    Bind to a StockZyxelPoePort resource in your environment YAML:

    ```yaml
    targets:
      main:
        resources:
          StockZyxelPoePort:
            host: "192.168.13.3"
            port: "p5"
        drivers:
          StockZyxelPoEDriver: {}
    ```

    Password source (never an attr, never exported): STOCK_ZYXEL_PASSWORD,
    BENCH_ROOT_PW, or sops fleet.bench_root_password in the bench repo.
    """

    bindings = {"port": "StockZyxelPoePort"}

    #: off()->on() dwell in cycle(): BCM59121 renegotiation, >=7 s (matches
    #: the conwrt-proven flash flow and ZyxelPoEDriver).
    delay = attr.ib(default=8.0, validator=attr.validators.instance_of(float))

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.logger = logging.getLogger(f"{self}({self.target})")
        self._web = None

    # -- low-level helpers -------------------------------------------------

    def _client(self):
        """StockWeb with one re-login on a login-shaped (expired) session."""
        if self._web is None:
            self._web = _make_web(self.port.host, _resolve_password(),
                                  self.port.username)
        return self._web

    def _row(self):
        """cmd=773 row for the bound port (dict) or ExecutionError."""
        try:
            return self._client().poe_status()[self.port.port_no]
        except KeyError:
            raise ExecutionError(
                f"port {self.port.port!r} missing from cmd=773") from None

    def _snapshot(self):
        row = self._row()
        return row["state"], int(row["mw"])

    def _verify(self, enable: bool) -> None:
        """Poll until cmd=773 reflects the requested state.

        Conservative contract: enable means watts must return (every stock
        port we manage carries a PD; an empty-but-disabled port being
        enabled will time out — a loud UNVERIFIED beats a silent success).
        A frozen (state, mw) row past SETTLING_S is a wedge (never success).
        """
        started = time.monotonic()
        deadline = started + VERIFY_TIMEOUT_S
        frozen_since = None
        last_digest = None
        last = ("", 0)
        state_seen = False
        while time.monotonic() < deadline:
            last = self._snapshot()
            state, mw = last
            ok = (state == "Enable" and mw > 0) if enable else \
                 (state == "Disable" and mw == 0)
            if ok:
                return
            want_state = "Enable" if enable else "Disable"
            if state == want_state:
                # Toggle itself reflected (not a wedge); only the secondary
                # condition (watts return) is pending — ride to the timeout.
                state_seen = True
                frozen_since = None
            elif not state_seen:
                digest = f"{state}:{mw}"
                now = time.monotonic()
                if now - started < SETTLING_S:
                    frozen_since = None
                elif digest == last_digest:
                    if frozen_since is None:
                        frozen_since = now
                    elif now - frozen_since > FROZEN_GRACE_S:
                        raise ExecutionError(
                            f"cmd=773 SNAPSHOT FROZEN: port {self.port.port} "
                            f"row stuck at '{state}'/{mw} mW for "
                            f">{FROZEN_GRACE_S:.0f}s past the "
                            f"{SETTLING_S:.0f}s settle window — treat as a "
                            "stock wedge; coordinate before any manual "
                            "recovery (never reboot the switch)."
                        )
                else:
                    frozen_since = None
                last_digest = digest
            time.sleep(POLL_INTERVAL_S)
        raise ExecutionError(
            f"stock PoE toggle UNVERIFIED: port {self.port.port} still "
            f"{last[0]!r}/{last[1]} mW after {VERIFY_TIMEOUT_S:.0f}s "
            f"(wanted {'Enable with power' if enable else 'Disable/0 mW'})"
        )

    def _set(self, enable: bool) -> None:
        no = self.port.port_no
        if self.port.port.strip().lower() in PROTECTED_PORTS:
            raise ExecutionError(
                f"refusing to toggle protected port {self.port.port!r} "
                f"(protected: {sorted(PROTECTED_PORTS)})")
        with _bench_flock():
            pre = self._row()
            if enable and pre["state"] == "Enable" and pre["mw"] == 0:
                # Port already enabled with no PD attached: nothing to verify
                # against (watts can never appear) — accept the steady state.
                self.logger.info(
                    "port %s already Enable with no PD — no-op", self.port.port)
                return
            # Full-field read-modify-write toggle (sibling fields from the
            # CURRENT row — never hardcoded) + state-level re-poll inside
            # the client; conservative wedge verification here.
            self._client().set_poe_state(no, enable)
            self._verify(enable)

    # -- PowerProtocol ------------------------------------------------------

    @Driver.check_active
    @step()
    def on(self):
        """Enable PoE on the bound port (verified via cmd=773)."""
        self._set(True)

    @Driver.check_active
    @step()
    def off(self):
        """Disable PoE on the bound port (verified via cmd=773)."""
        self._set(False)

    @Driver.check_active
    @step()
    def cycle(self):
        """Power-cycle: off, wait ``delay`` s, on (both verified)."""
        self.off()
        time.sleep(self.delay)
        self.on()

    # -- introspection ------------------------------------------------------

    @Driver.check_active
    @step()
    def get_status(self):
        """Raw cmd=773 row summary: 'state/priority/mW'."""
        row = self._row()
        return f"{row['state']}/{row['priority']}/{row['mw']}mW"

    @Driver.check_active
    @step()
    def get(self):
        """True iff the port admin-state is Enable."""
        return self._row()["state"] == "Enable"
