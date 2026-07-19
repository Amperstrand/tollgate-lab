"""Tests for labgrid-registered custom drivers."""

from labgrid import target_factory


def test_router_driver_registered():
    """RouterDriver is registered with labgrid."""
    from tollgate_lab.drivers.labgrid_router import RouterDriver
    assert "RouterDriver" in target_factory.drivers


def test_android_adb_driver_registered():
    """AndroidADBDriver is registered with labgrid."""
    from tollgate_lab.drivers.android_adb import AndroidADBDriver
    assert "AndroidADBDriver" in target_factory.drivers


def test_android_device_resource_registered():
    """AndroidADDDevice resource is registered."""
    from tollgate_lab.drivers.android_adb import AndroidADDDevice
    assert "AndroidADDDevice" in target_factory.resources


def test_playwright_driver_registered():
    """PlaywrightBrowserDriver is registered."""
    from tollgate_lab.drivers.playwright_browser import PlaywrightBrowserDriver
    assert "PlaywrightBrowserDriver" in target_factory.drivers


def test_esp_flash_driver_registered():
    """EspFlashDriver is registered (from fips-lab extraction)."""
    from tollgate_lab.drivers.esp_flash import EspFlashDriver
    assert "EspFlashDriver" in target_factory.drivers


def test_fips_service_driver_registered():
    """FipsServiceDriver is registered."""
    from tollgate_lab.drivers.fips_service import FipsServiceDriver
    assert "FipsServiceDriver" in target_factory.drivers


def test_fipsctl_driver_registered():
    """FipsctlDriver is registered."""
    from tollgate_lab.drivers.fipsctl import FipsctlDriver
    assert "FipsctlDriver" in target_factory.drivers
