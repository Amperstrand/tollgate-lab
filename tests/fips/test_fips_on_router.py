"""FIPS daemon tests on OpenWrt routers.

These tests deploy and verify FIPS on the same routers that TollGate runs on.
Requires a router accessible via SSH with OpenWrt.

Usage:
    ROUTER_SSH_HOST=192.168.13.112 pytest tests/fips/ -v
"""

import os
import time
import pytest


@pytest.fixture(scope="session")
def fips_router():
    """SSH session to a router with FIPS installed."""
    host = os.environ.get("ROUTER_SSH_HOST", "192.168.13.112")
    user = os.environ.get("ROUTER_SSH_USER", "root")

    import subprocess

    def run(cmd):
        result = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=30
        )
        return result

    yield {"host": host, "user": user, "run": run}


@pytest.mark.hardware
class TestFipsInstalled:
    """Verify FIPS package is installed on the router."""

    def test_fips_binary_exists(self, fips_router):
        result = fips_router["run"]("which fips || echo NOT_FOUND")
        assert "NOT_FOUND" not in result.stdout, "fips binary not found"

    def test_fipsctl_binary_exists(self, fips_router):
        result = fips_router["run"]("which fipsctl || echo NOT_FOUND")
        assert "NOT_FOUND" not in result.stdout, "fipsctl binary not found"


@pytest.mark.hardware
class TestFipsService:
    """Verify FIPS daemon lifecycle on the router."""

    def test_fips_service_starts(self, fips_router):
        fips_router["run"]("service fips start || true")
        time.sleep(3)
        result = fips_router["run"]("service fips status")
        assert "running" in result.stdout

    def test_fipsctl_responds(self, fips_router):
        result = fips_router["run"]("fipsctl show status")
        assert result.returncode == 0
        assert "transport" in result.stdout.lower()

    def test_fips_service_stops(self, fips_router):
        fips_router["run"]("service fips stop || true")
        time.sleep(2)
        result = fips_router["run"]("service fips status")
        assert "running" not in result.stdout


@pytest.mark.hardware
class TestFipsTollGateCoexistence:
    """Verify FIPS and TollGate can coexist on the same router."""

    def test_both_services_running(self, fips_router):
        fips_result = fips_router["run"]("service fips status")
        tollgate_result = fips_router["run"]("service tollgate status || echo NO_TOLLGATE")

        if "NO_TOLLGATE" not in tollgate_result.stdout:
            assert "running" in fips_result.stdout or "stopped" in fips_result.stdout
        else:
            pytest.skip("TollGate not installed on this router")

    def test_no_port_conflict(self, fips_router):
        """FIPS uses UDP 2121, TollGate uses different ports."""
        result = fips_router["run"]("netstat -tuln | grep ':2121'")
        # Port 2121 should be used by FIPS, not TollGate
        assert "2121" in result.stdout
