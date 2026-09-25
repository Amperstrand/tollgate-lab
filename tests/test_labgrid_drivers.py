"""Tests for labgrid-registered custom drivers."""

from labgrid import target_factory


def test_router_driver_registered():
    """RouterDriver is registered with labgrid."""
    from tollgate_lab.drivers.labgrid_router import RouterDriver  # noqa: F401
    assert "RouterDriver" in target_factory.drivers


def test_android_adb_driver_registered():
    """AndroidADBDriver is registered with labgrid."""
    from tollgate_lab.drivers.android_adb import AndroidADBDriver  # noqa: F401
    assert "AndroidADBDriver" in target_factory.drivers


def test_android_device_resource_registered():
    """AndroidADDDevice resource is registered."""
    from tollgate_lab.drivers.android_adb import AndroidADDDevice  # noqa: F401
    assert "AndroidADDDevice" in target_factory.resources


def test_playwright_driver_registered():
    """PlaywrightBrowserDriver is registered."""
    from tollgate_lab.drivers.playwright_browser import PlaywrightBrowserDriver  # noqa: F401
    assert "PlaywrightBrowserDriver" in target_factory.drivers


def test_esp_flash_driver_registered():
    """EspFlashDriver is registered (from fips-lab extraction)."""
    from tollgate_lab.drivers.esp_flash import EspFlashDriver  # noqa: F401
    assert "EspFlashDriver" in target_factory.drivers


def test_fips_service_driver_registered():
    """FipsServiceDriver is registered."""
    from tollgate_lab.drivers.fips_service import FipsServiceDriver  # noqa: F401
    assert "FipsServiceDriver" in target_factory.drivers


def test_fipsctl_driver_registered():
    """FipsctlDriver is registered."""
    from tollgate_lab.drivers.fipsctl import FipsctlDriver  # noqa: F401
    assert "FipsctlDriver" in target_factory.drivers


def test_android_add_device_constructible():
    """AndroidADDDevice subclasses Resource (factory-constructible via env
    yaml + coordinator wire); found broken during android-phone bringup."""
    from labgrid import Target

    from tollgate_lab.drivers.android_adb import AndroidADDDevice  # noqa: F401

    target = Target("construct-dummy")
    resource = AndroidADDDevice(target, name="phone", serial="")
    assert resource.serial == ""
