"""Public API for tollgate-lab.

Import from here for the stable interface:

    from tollgate_lab import HardwareLock
    from tollgate_lab.public import Router
"""

from tollgate_lab.hardware import HardwareLock

try:
    from tollgate_lab.drivers.router import Router
except ImportError:
    pass

try:
    from tollgate_lab.reporting.nostr_events import publish_test_result
except ImportError:
    pass

__all__ = [
    "HardwareLock",
    "Router",
]
