"""Hardware locking for test session isolation."""

from tollgate_lab.hardware.bench_lock import (
    BenchLock as BenchLock,
)
from tollgate_lab.hardware.bench_lock import (
    BenchLockHeldError as BenchLockHeldError,
)
from tollgate_lab.hardware.bench_lock import (
    acquire_bench_lock as acquire_bench_lock,
)
from tollgate_lab.hardware.bench_lock import (
    read_bench_lock as read_bench_lock,
)
from tollgate_lab.hardware.gate import (
    FakeSource as FakeSource,
)
from tollgate_lab.hardware.gate import (
    SerialLineSource as SerialLineSource,
)
from tollgate_lab.hardware.gate import (
    TelemetryGateError as TelemetryGateError,
)
from tollgate_lab.hardware.gate import (
    assert_telemetry as assert_telemetry,
)
from tollgate_lab.hardware.lock import (
    acquire_hardware_lock as acquire_hardware_lock,
)
from tollgate_lab.hardware.lock import (
    is_hardware_locked as is_hardware_locked,
)
from tollgate_lab.hardware.lock import (
    read_hardware_lock as read_hardware_lock,
)
from tollgate_lab.hardware.lock import (
    release_hardware_lock,
    require_hardware_lock,
)
from tollgate_lab.hardware.poe import (
    PoeControllerConfig as PoeControllerConfig,
)
from tollgate_lab.hardware.poe import (
    PoeError as PoeError,
)
from tollgate_lab.hardware.poe import (
    PoePortInfo as PoePortInfo,
)
from tollgate_lab.hardware.poe import (
    PoePowerController as PoePowerController,
)
from tollgate_lab.hardware.poe import (
    PoeProtectedPortError as PoeProtectedPortError,
)
from tollgate_lab.hardware.poe import (
    PoeStatus as PoeStatus,
)
from tollgate_lab.hardware.poe import (
    PoeSwitchInfo as PoeSwitchInfo,
)
from tollgate_lab.hardware.poe import (
    PoeUnresponsiveError as PoeUnresponsiveError,
)
from tollgate_lab.hardware.port import (
    AmbiguousPortError as AmbiguousPortError,
)
from tollgate_lab.hardware.port import (
    FlashPolicy as FlashPolicy,
)
from tollgate_lab.hardware.port import (
    PortAbsentError as PortAbsentError,
)
from tollgate_lab.hardware.port import (
    PortMatch as PortMatch,
)
from tollgate_lab.hardware.port import (
    policy_for as policy_for,
)
from tollgate_lab.hardware.port import (
    resolve_port as resolve_port,
)
from tollgate_lab.hardware.zyxel_stock import (
    StockCLI as StockCLI,
)
from tollgate_lab.hardware.zyxel_stock import (
    StockWeb as StockWeb,
)
from tollgate_lab.hardware.zyxel_stock import (
    mac_address_table as mac_address_table,
)
from tollgate_lab.hardware.zyxel_stock import (
    zyxel_encode as zyxel_encode,
)


class HardwareLock:
    """Context manager for hardware test isolation."""

    def __init__(self, name: str = "default"):
        self.name = name

    def acquire(self, timeout: int = 30) -> bool:
        try:
            require_hardware_lock()
            return True
        except Exception:
            return False

    def release(self):
        release_hardware_lock()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
