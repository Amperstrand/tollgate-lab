"""tollgate_lab.drivers — labgrid-compatible device drivers.

Public API surface (issue #13): every stable driver/helper class is
re-exported here so consumers write:

    from tollgate_lab.drivers import RouterDriver

Not yet re-exported: the Zyxel PoE drivers (``zyxel_poe``, ``stock_zyxel_poe``)
are still settling under the review-debt wave (#28) — import those via their
submodule paths until they stabilize.
"""

from tollgate_lab.drivers.android_adb import AndroidADBDriver as AndroidADBDriver
from tollgate_lab.drivers.android_adb import AndroidADDDevice as AndroidADDDevice
from tollgate_lab.drivers.esp_flash import EspFlashDriver as EspFlashDriver
from tollgate_lab.drivers.fips_service import FipsServiceDriver as FipsServiceDriver
from tollgate_lab.drivers.fipsctl import FipsctlDriver as FipsctlDriver
from tollgate_lab.drivers.labgrid_router import RouterDriver as RouterDriver
from tollgate_lab.drivers.playwright_browser import (
    PlaywrightBrowserDriver as PlaywrightBrowserDriver,
)
from tollgate_lab.drivers.router import BackendConfig as BackendConfig
from tollgate_lab.drivers.router import Router as Router
from tollgate_lab.drivers.serial_console import SerialConsole as SerialConsole
from tollgate_lab.drivers.ssh import SSHEsp32Adapter as SSHEsp32Adapter
from tollgate_lab.drivers.ssh import SSHFipsAdapter as SSHFipsAdapter
from tollgate_lab.drivers.ssh import SSHFirmwareBuilder as SSHFirmwareBuilder

__all__ = [
    "AndroidADDDevice",
    "AndroidADBDriver",
    "BackendConfig",
    "EspFlashDriver",
    "FipsServiceDriver",
    "FipsctlDriver",
    "PlaywrightBrowserDriver",
    "Router",
    "RouterDriver",
    "SerialConsole",
    "SSHEsp32Adapter",
    "SSHFipsAdapter",
    "SSHFirmwareBuilder",
]
