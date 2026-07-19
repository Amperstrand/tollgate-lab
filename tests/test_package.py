"""Tests for tollgate-lab package."""

import pytest


def test_package_imports():
    """Verify tollgate_lab can be imported."""
    import tollgate_lab
    assert tollgate_lab.__version__ == "0.1.0"


def test_drivers_module():
    """Verify drivers subpackage is accessible."""
    import tollgate_lab.drivers
    assert hasattr(tollgate_lab.drivers, "__path__")


def test_hardware_lock_module():
    """Verify hardware lock functions exist."""
    from tollgate_lab.hardware import lock
    assert hasattr(lock, "acquire_hardware_lock")
    assert hasattr(lock, "release_hardware_lock")
    assert hasattr(lock, "is_hardware_locked")


def test_fixtures_imports():
    """Verify fixtures can be imported."""
    from tollgate_lab.fixtures import sessions
    assert hasattr(sessions, "router_session")


def test_ssh_driver_imports():
    """Verify SSH driver can be imported."""
    from tollgate_lab.drivers import ssh
    assert hasattr(ssh, "_ssh_run")


def test_esp_flash_driver_imports():
    """Verify ESP flash driver can be imported."""
    from tollgate_lab.drivers import esp_flash
    assert esp_flash is not None


def test_serial_console_imports():
    """Verify serial console can be imported."""
    from tollgate_lab.drivers import serial_console
    assert serial_console is not None


def test_nostr_reporting_imports():
    """Verify Nostr reporting can be imported."""
    from tollgate_lab.reporting import nostr_events
    assert nostr_events is not None


def test_deploy_imports():
    """Verify deploy module can be imported."""
    from tollgate_lab.deploy import ci_artifact
    assert ci_artifact is not None
