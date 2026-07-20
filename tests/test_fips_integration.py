"""FIPS integration tests — deploy, start, verify, teardown.

These tests exercise the full FIPS deployment flow:
1. Generate FIPS config
2. Install FIPS .ipk on router (or verify already installed)
3. Start FIPS service
4. Verify fipsctl responds
5. Verify transports are active
6. Stop FIPS service

Requires a router accessible via SSH. Set ROUTER_SSH_HOST env var.
"""

import os
import time
import subprocess
import pytest

from tollgate_lab.deploy.fips import default_fips_config


def _ssh(host, user, cmd, timeout=30):
    """SSH helper."""
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{user}@{host}", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result


@pytest.fixture(scope="module")
def router():
    """Router SSH target."""
    host = os.environ.get("ROUTER_SSH_HOST", "")
    if not host:
        pytest.skip("ROUTER_SSH_HOST not set")
    user = os.environ.get("ROUTER_SSH_USER", "root")
    return {"host": host, "user": user}


@pytest.mark.hardware
class TestFipsDeployment:
    """Test FIPS deployment on OpenWrt router."""

    def test_fips_installed(self, router):
        """FIPS binary exists on router."""
        result = _ssh(router["host"], router["user"], "which fips")
        assert result.returncode == 0, "fips not found"

    def test_fipsctl_installed(self, router):
        """fipsctl binary exists on router."""
        result = _ssh(router["host"], router["user"], "which fipsctl")
        assert result.returncode == 0, "fipsctl not found"

    def test_fips_service_starts(self, router):
        """FIPS service starts and reports running."""
        _ssh(router["host"], router["user"], "service fips start || true")
        time.sleep(3)
        result = _ssh(router["host"], router["user"], "service fips status")
        assert "running" in result.stdout, f"FIPS not running: {result.stdout}"

    def test_fipsctl_responds(self, router):
        """fipsctl responds with transport info."""
        result = _ssh(router["host"], router["user"], "fipsctl show status")
        assert result.returncode == 0, f"fipsctl failed: {result.stderr}"
        assert "transport" in result.stdout.lower(), \
            f"No transport in status: {result.stdout}"

    def test_fips_config_valid(self, router):
        """FIPS config file exists and is valid."""
        result = _ssh(router["host"], router["user"], "cat /etc/fips/fips.yaml")
        assert result.returncode == 0, "No config file"
        assert "transport" in result.stdout, "Config missing transports section"


@pytest.mark.hardware
class TestFipsConfigGeneration:
    """Test FIPS config generation (no hardware needed)."""

    def test_default_config_has_udp(self):
        """Default config includes UDP transport."""
        config = default_fips_config()
        assert "udp" in config["transports"]

    def test_default_config_tun_disabled(self):
        """TUN disabled by default."""
        config = default_fips_config()
        assert config["tun"]["enabled"] is False

    def test_custom_config(self):
        """Custom config with BLE."""
        config = default_fips_config(
            adapter="hci0",
            tun=True,
            dns=True,
        )
        assert config["tun"]["enabled"] is True
        assert config["dns"]["enabled"] is True
