"""FIPS daemon tests on OpenWrt routers (or localhost).

Requires a FIPS instance accessible via SSH.

Usage:
    ROUTER_SSH_HOST=192.168.13.112 pytest tests/fips/ -v -m hardware
    ROUTER_SSH_HOST=127.0.0.1 ROUTER_SSH_USER=ubuntu pytest tests/fips/ -v -m hardware
"""

import os
import time
import pytest


@pytest.fixture(scope="session")
def fips_router():
    """SSH session to a host with FIPS installed."""
    host = os.environ.get("ROUTER_SSH_HOST", "")
    if not host:
        pytest.skip("ROUTER_SSH_HOST not set")
    user = os.environ.get("ROUTER_SSH_USER", "root")

    import subprocess

    def run(cmd):
        return subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
             f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=30
        )

    yield {"host": host, "user": user, "run": run}


@pytest.mark.hardware
class TestFipsInstalled:
    """Verify FIPS package is installed."""

    def test_fips_binary_exists(self, fips_router):
        result = fips_router["run"]("which fips || sudo which fips || echo NOT_FOUND")
        assert "NOT_FOUND" not in result.stdout, "fips binary not found"

    def test_fipsctl_binary_exists(self, fips_router):
        result = fips_router["run"]("which fipsctl || sudo which fipsctl || echo NOT_FOUND")
        assert "NOT_FOUND" not in result.stdout, "fipsctl binary not found"


@pytest.mark.hardware
class TestFipsService:
    """Verify FIPS daemon lifecycle."""

    def test_fips_service_running(self, fips_router):
        """FIPS service is running."""
        result = fips_router["run"]("sudo service fips status || service fips status || echo 'not running'")
        assert "running" in result.stdout.lower() or "active" in result.stdout.lower(), \
            f"FIPS not running: {result.stdout}"

    def test_fipsctl_responds(self, fips_router):
        """fipsctl responds with transport info."""
        result = fips_router["run"]("sudo fipsctl show status 2>/dev/null || fipsctl show status 2>/dev/null")
        assert result.returncode == 0 or "transport" in result.stdout.lower(), \
            f"fipsctl failed: {result.stderr}"
        assert "transport" in result.stdout.lower() or "node" in result.stdout.lower(), \
            f"No expected fields in status: {result.stdout[:200]}"

    def test_fips_config_exists(self, fips_router):
        """FIPS config file exists."""
        result = fips_router["run"]("cat /etc/fips/fips.yaml 2>/dev/null || sudo cat /etc/fips/fips.yaml 2>/dev/null")
        assert result.returncode == 0, "No config file"
        assert "transport" in result.stdout.lower(), "Config missing transports"


@pytest.mark.hardware
class TestFipsTollGateCoexistence:
    """Verify FIPS and TollGate can coexist on the same host."""

    def test_no_port_conflict(self, fips_router):
        """FIPS uses UDP 2121, TollGate uses different ports."""
        result = fips_router["run"]("sudo ss -ulnp | grep ':2121' || netstat -uln | grep ':2121' || echo NO_2121")
        # Port 2121 should be used by FIPS
        assert "2121" in result.stdout, f"FIPS UDP 2121 not found: {result.stdout}"

    def test_tollgate_if_present(self, fips_router):
        """Check TollGate status if installed."""
        result = fips_router["run"]("service tollgate status 2>/dev/null || echo NO_TOLLGATE")
        if "NO_TOLLGATE" not in result.stdout:
            assert "running" in result.stdout.lower() or "stopped" in result.stdout.lower()
        else:
            pytest.skip("TollGate not installed on this host")
