"""Public API for tollgate-lab.

Import from here for the stable interface:

    from tollgate_lab import HardwareLock
    from tollgate_lab.public import Router
"""

import contextlib

from tollgate_lab.hardware import HardwareLock

with contextlib.suppress(ImportError):
    from tollgate_lab.drivers.router import Router

with contextlib.suppress(ImportError):
    from tollgate_lab.reporting.nostr_events import publish_test_result

__all__ = [
    "HardwareLock",
    "Router",
    "publish_test_result",
]
