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
