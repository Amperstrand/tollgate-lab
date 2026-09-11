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
from tollgate_lab.hardware import (
    BenchLock as BenchLock,
)
from tollgate_lab.hardware import (
    BenchLockHeldError as BenchLockHeldError,
)
from tollgate_lab.hardware import (
    HardwareLock as HardwareLock,
)
from tollgate_lab.hardware import (
    acquire_bench_lock as acquire_bench_lock,
)
from tollgate_lab.hardware import (
    read_bench_lock as read_bench_lock,
)
from tollgate_lab.disk_hygiene import (
    HygieneReport as HygieneReport,
)
from tollgate_lab.disk_hygiene import (
    disk_headroom_gb as disk_headroom_gb,
)
from tollgate_lab.disk_hygiene import (
    ensure_run_headroom as ensure_run_headroom,
)
from tollgate_lab.reservation import (
    BoardReservation as BoardReservation,
)
from tollgate_lab.reservation import (
    ReservationError as ReservationError,
)
from tollgate_lab.reservation import (
    release as release_board,
)
from tollgate_lab.reservation import (
    reserve as reserve_board,
)
from tollgate_lab.reservation import (
    status as board_status,
)

from tollgate_lab.cyd_qr import CydError as CydError
from tollgate_lab.cyd_qr import CydQrClient as CydQrClient
from tollgate_lab.cyd_qr import QR_WINNING_CAP as QR_WINNING_CAP
from tollgate_lab.cyd_qr import arm_winning_config as arm_winning_config
