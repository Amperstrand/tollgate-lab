"""Labgrid-registered RouterDriver for OpenWrt routers.

This driver wraps SSH access to OpenWrt routers, implementing
labgrid's CommandProtocol for integration with labgrid strategies.
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
class RouterDriver(Driver, CommandProtocol):
    """SSH-based router control via labgrid.

    Bind to a NetworkService resource in your environment YAML:

    ```yaml
    targets:
      router:
        resources:
          NetworkService:
            address: "192.168.1.1"
            username: "root"
        drivers:
          RouterDriver: {}
    ```
    """

    bindings = {"network": "NetworkService"}

    def __attrs_post_init__(self):
        super().__attrs_post_init__()
        self.logger = logging.getLogger(f"{self}({self.target})")

    @step(args=["command"])
    def run(self, command: str, timeout: float = 30.0):
        """Run a command on the router via SSH.

        Returns:
            Tuple of (stdout_lines, stderr_lines, exitcode).
        """
        host = self.network.address
        user = self.network.username

        result = subprocess.run(
            [
                "ssh", "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=10",
                "-o", "StrictHostKeyChecking=no",
                f"{user}@{host}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        stdout = result.stdout.split("\n") if result.stdout else []
        stderr = result.stderr.split("\n") if result.stderr else []
        return stdout, stderr, result.returncode

    @step(args=["command"])
    def run_check(self, command: str, timeout: float = 30.0):
        """Run a command and raise on non-zero exit.

        Returns:
            List of stdout lines.
        """
        stdout, stderr, exitcode = self.run(command, timeout)
        if exitcode != 0:
            raise subprocess.CalledProcessError(
                exitcode, command, "\n".join(stderr)
            )
        return stdout

    @step(args=["command"])
    def get_status(self):
        """Check router connectivity."""
        try:
            self.run("echo ok", timeout=5.0)
            return "reachable"
        except Exception:
            return "unreachable"

    def put_file(self, source: str, dest: str, timeout: float = 60.0):
        """Upload a file to the router via SCP."""
        host = self.network.address
        user = self.network.username

        subprocess.run(
            [
                "scp", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                source,
                f"{user}@{host}:{dest}",
            ],
            check=True,
            timeout=timeout,
        )

    def get_file(self, source: str, dest: str, timeout: float = 60.0):
        """Download a file from the router via SCP."""
        host = self.network.address
        user = self.network.username

        subprocess.run(
            [
                "scp", "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=no",
                f"{user}@{host}:{source}",
                dest,
            ],
            check=True,
            timeout=timeout,
        )

    def install_package(self, ipk_path: str, timeout: float = 120.0):
        """Install an .ipk package on the router."""
        remote_path = f"/tmp/{ipk_path.split('/')[-1]}"
        self.put_file(ipk_path, remote_path)
        self.run_check(f"opkg install {remote_path}", timeout=timeout)
        self.run(f"rm -f {remote_path}")
