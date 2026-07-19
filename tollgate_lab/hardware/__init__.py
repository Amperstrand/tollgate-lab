"""Hardware locking for test session isolation."""

from tollgate_lab.hardware.lock import (
    acquire_hardware_lock,
    release_hardware_lock,
    is_hardware_locked,
    require_hardware_lock,
    read_hardware_lock,
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
