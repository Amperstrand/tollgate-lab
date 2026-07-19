"""Pytest fixtures for hardware testing via tollgate-lab."""

import os
import pytest


@pytest.fixture(scope="session")
def hardware_lock():
    """Acquire a hardware lock for the test session."""
    from tollgate_lab.hardware.lock import HardwareLock

    lock_name = os.environ.get("TOLLGATE_LAB_LOCK", "default")
    lock = HardwareLock(lock_name)
    if not lock.acquire(timeout=30):
        pytest.skip(f"Could not acquire hardware lock '{lock_name}'")
    yield lock
    lock.release()


@pytest.fixture(scope="session")
def router_env():
    """Load router environment configuration from env vars."""
    return {
        "host": os.environ.get("ROUTER_SSH_HOST", "192.168.13.112"),
        "user": os.environ.get("ROUTER_SSH_USER", "root"),
        "password": os.environ.get("ROUTER_SSH_PASS", ""),
    }


@pytest.fixture(scope="session")
def router_session(router_env):
    """SSH session to an OpenWrt router."""
    from tollgate_lab.drivers.ssh import SSHClient

    session = SSHClient(
        host=router_env["host"],
        user=router_env["user"],
        password=router_env["password"],
    )
    yield session
    session.close()


@pytest.fixture(scope="session")
def fips_daemon(router_session):
    """Ensure FIPS daemon is running on the router."""
    router_session.run("service fips start || true")
    import time
    time.sleep(3)

    result = router_session.run("service fips status")
    if "running" not in result.stdout:
        pytest.skip("FIPS daemon not running on router")

    yield router_session
