"""Tests for tollgate-lab package."""

import pytest


def test_package_imports():
    """Verify tollgate_lab can be imported."""
    import tollgate_lab
    assert tollgate_lab is not None


def test_drivers_module():
    """Verify drivers subpackage is accessible."""
    import tollgate_lab.drivers
    assert hasattr(tollgate_lab.drivers, "__path__")


def test_hardware_lock_imports():
    """Verify hardware lock can be imported."""
    from tollgate_lab.hardware import lock as lock_module
    assert lock_module is not None


def test_fixtures_imports():
    """Verify fixtures can be imported."""
    from tollgate_lab.fixtures import sessions
    assert hasattr(sessions, "router_session")


def test_ssh_driver_imports():
    """Verify SSH driver can be imported."""
    from tollgate_lab.drivers import ssh
    assert ssh is not None


def test_esp_flash_driver_imports():
    """Verify ESP flash driver can be imported."""
    from tollgate_lab.drivers import esp_flash
    assert esp_flash is not None


@pytest.mark.hardware
def test_hardware_lock_acquire_release():
    """Test hardware lock acquire/release cycle."""
    from tollgate_lab.hardware.lock import HardwareLock

    lock = HardwareLock("test-tollgate-lab")
    assert lock.acquire(timeout=5)
    assert not lock.acquire(timeout=1)  # Already locked
    lock.release()
    assert lock.acquire(timeout=5)  # Can re-acquire after release
    lock.release()
