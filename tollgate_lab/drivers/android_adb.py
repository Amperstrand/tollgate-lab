"""Labgrid-registered AndroidADBDriver for Android phones via ADB.

Labgrid has fastboot support but no native ADB driver. This fills that gap.
"""

import logging
import subprocess
import attr

from labgrid import target_factory
from labgrid.driver import Driver
from labgrid.protocol.commandprotocol import CommandProtocol
from labgrid.step import step


@target_factory.reg_driver
@attr.s(eq=False)
class AndroidADBDriver(Driver, CommandProtocol):
    """ADB-based Android phone control via labgrid.

    ```yaml
    targets:
      phone:
        resources:
          NetworkService:
            address: "localhost"
            username: "ubuntu"
        drivers:
          AndroidADBDriver:
            device_serial: ""
    ```
    """

    bindings = {"network": "NetworkService", "device_serial": "AndroidADDDevice"}

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.logger = logging.getLogger(f"{self}({self.target})")
        self._serial = None

    def on_activate(self):
        if self.device_serial:
            self._serial = self.device_serial.serial
        else:
            self._serial = ""

    def _adb(self, args: list[str], timeout: float = 30.0) -> subprocess.CompletedProcess:
        cmd = ["adb"]
        if self._serial:
            cmd += ["-s", self._serial]
        cmd += args
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    @step(args=["command"])
    def run(self, command: str, timeout: float = 30.0):
        """Run a shell command on the Android device."""
        result = self._adb(["shell", command], timeout)
        stdout = result.stdout.split("\n") if result.stdout else []
        stderr = result.stderr.split("\n") if result.stderr else []
        return stdout, stderr, result.returncode

    @step(args=["command"])
    def run_check(self, command: str, timeout: float = 30.0):
        """Run command and raise on failure."""
        stdout, stderr, exitcode = self.run(command, timeout)
        if exitcode != 0:
            raise subprocess.CalledProcessError(exitcode, command, "\n".join(stderr))
        return stdout

    @step()
    def get_status(self):
        """Check device connectivity."""
        result = self._adb(["get-state"], timeout=5.0)
        return result.stdout.strip() or "unreachable"

    def screenshot(self, dest_path: str):
        """Capture a screenshot from the device."""
        self._adb(["shell", "screencap", "-p", "/sdcard/screen.png"])
        self._adb(["pull", "/sdcard/screen.png", dest_path])
        self._adb(["shell", "rm", "/sdcard/screen.png"])

    def open_url(self, url: str):
        """Open a URL in the device's browser."""
        self._adb(["shell", "am", "start", "-a", "android.intent.action.VIEW",
                       "-d", url])

    def install_apk(self, apk_path: str, timeout: float = 120.0):
        """Install an APK on the device."""
        self._adb(["install", "-r", apk_path], timeout=timeout)


@target_factory.reg_resource
@attr.s(eq=False)
class AndroidADDDevice:
    """Resource describing an ADB-accessible Android device."""
    serial = attr.ib(default=None)
