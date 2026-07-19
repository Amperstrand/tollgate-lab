"""tollgate-lab: Unified hardware testing library for Amperstrand projects.

Built on labgrid for device orchestration. Supports:
- OpenWrt routers (SSH)
- ESP32 / ESP8266 (serial, esptool)
- STM32 (serial, st-flash)
- Bluetooth adapters (HCI)
- Android phones (ADB)

Quick start:
    from tollgate_lab import HardwareLock
    from tollgate_lab.fixtures.sessions import router_session
"""

__version__ = "0.1.0"

# Public API — stable interface
from tollgate_lab.hardware import HardwareLock
