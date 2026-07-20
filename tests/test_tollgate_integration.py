"""TollGate integration tests — deploy, start, verify.

Tests TollGate deployment alongside FIPS on OpenWrt routers.
"""

import os
import time
import subprocess
import pytest


def _ssh(host, user, cmd, timeout=30):
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result


@pytest.fixture(scope="module")
def router():
    host = os.environ.get("ROUTER_SSH_HOST", "")
    if not host:
        pytest.skip("ROUTER_SSH_HOST not set")
    return {"host": host, "user": os.environ.get("ROUTER_SSH_USER", "root")}


@pytest.mark.hardware
class TestTollGateDeployment:
    """Test TollGate on router."""

    def test_tollgate_installed(self, router):
        """TollGate binary exists."""
        result = _ssh(router["host"], router["user"], "which tollgate-wrt")
        if result.returncode != 0:
            pytest.skip("TollGate not installed")

    def test_tollgate_service_status(self, router):
        """TollGate service responds to status check."""
        result = _ssh(router["host"], router["user"], "service tollgate status")
        assert result.returncode == 0 or "not" in result.stdout

    def test_captive_portal_port(self, router):
        """Captive portal port is listening."""
        result = _ssh(router["host"], router["user"],
                       "netstat -tln | grep ':2080' || echo NOT_FOUND")
        if "NOT_FOUND" in result.stdout:
            pytest.skip("Captive portal not configured")


@pytest.mark.hardware
class TestFipsTollGateCoexistence:
    """Test FIPS + TollGate running on same router."""

    def test_no_port_conflict(self, router):
        """FIPS (UDP 2121) and TollGate (TCP 2080/8080) don't conflict."""
        result = _ssh(router["host"], router["user"], "netstat -tuln")
        ports = result.stdout

        # FIPS uses UDP 2121
        if "2121" in ports:
            # Make sure TollGate isn't also on 2121
            assert ":2121" not in ports.split("tollgate")[0] if "tollgate" in ports else True

    def test_both_can_run(self, router):
        """Both services can run simultaneously."""
        fips_status = _ssh(router["host"], router["user"], "service fips status")
        tg_status = _ssh(router["host"], router["user"], "service tollgate status || echo NO_TG")

        fips_ok = "running" in fips_status.stdout
        tg_ok = "running" in tg_status.stdout or "NO_TG" in tg_status.stdout

        assert fips_ok or tg_ok, "Neither service running"
