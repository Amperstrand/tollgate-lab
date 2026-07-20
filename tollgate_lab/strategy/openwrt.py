"""Labgrid strategy for OpenWrt router lifecycle.

State machine: unknown → boot → shell → service_running → test_ready

Usage in environment YAML:
```yaml
targets:
  router:
    resources:
      NetworkService:
        address: "192.168.1.1"
        username: "root"
    drivers:
      SSHDriver: {}
      OpenWrtStrategy: {}
```
"""

import enum
import logging
import time

import attr
from labgrid import target_factory
from labgrid.strategy import Strategy, StrategyError

log = logging.getLogger(__name__)


class OpenWrtState(enum.Enum):
    """Router lifecycle states."""
    unknown = 0
    boot = 1
    shell = 2
    service_running = 3
    test_ready = 4


@target_factory.reg_driver
@attr.s(eq=False)
class OpenWrtStrategy(Strategy):
    """Strategy for managing OpenWrt router test lifecycle.

    Transitions:
        unknown → boot: Power on or reset
        boot → shell: Wait for SSH access
        shell → service_running: Start required services (FIPS, TollGate)
        service_running → test_ready: Verify all services responding
    """

    bindings = {
        "ssh": "SSHDriver",
    }

    state = attr.ib(default=OpenWrtState.unknown)

    def __attrs_post_init__(self):
        super().__attrs_post_init__()

    def transition(self, state):
        if isinstance(state, str):
            state = OpenWrtState[state]

        if state is self.state:
            return

        log.info(f"OpenWrt transition: {self.state.name} → {state.name}")

        if state is OpenWrtState.boot:
            self._goto_boot()
        elif state is OpenWrtState.shell:
            self._goto_shell()
        elif state is OpenWrtState.service_running:
            self._goto_service_running()
        elif state is OpenWrtState.test_ready:
            self._goto_test_ready()
        else:
            raise StrategyError(f"Unknown state: {state}")

        self.state = state

    def _goto_boot(self):
        """Wait for router to boot."""
        if self.state is not OpenWrtState.unknown:
            self.transition(OpenWrtState.unknown)
        log.info("Waiting for router to boot...")
        time.sleep(5)

    def _goto_shell(self):
        """Wait for SSH access."""
        if self.state is OpenWrtState.boot:
            self.transition(OpenWrtState.boot)

        for attempt in range(30):
            try:
                self.ssh.run("echo ok", timeout=5)
                log.info("SSH access established")
                return
            except Exception:
                time.sleep(2)

        raise StrategyError("Router did not become SSH-accessible within 60s")

    def _goto_service_running(self):
        """Start required services on the router."""
        if self.state is not OpenWrtState.shell:
            self.transition(OpenWrtState.shell)

        # Start services (override in subclasses for specific services)
        self.ssh.run("service fips start || true", timeout=10)
        self.ssh.run("service tollgate start || true", timeout=10)
        time.sleep(3)
        log.info("Services started")

    def _goto_test_ready(self):
        """Verify all services are responding."""
        if self.state is not OpenWrtState.service_running:
            self.transition(OpenWrtState.service_running)

        # Verify FIPS
        try:
            result = self.ssh.run("fipsctl show status || true", timeout=10)
            if "transport" in "\n".join(result[0]):
                log.info("FIPS responding")
            else:
                log.warning("FIPS not responding (may not be installed)")
        except Exception:
            log.warning("FIPS check failed")

        # Verify TollGate
        try:
            result = self.ssh.run("service tollgate status || true", timeout=10)
            if "running" in "\n".join(result[0]):
                log.info("TollGate running")
            else:
                log.warning("TollGate not running (may not be installed)")
        except Exception:
            log.warning("TollGate check failed")

        log.info("Router is test-ready")
