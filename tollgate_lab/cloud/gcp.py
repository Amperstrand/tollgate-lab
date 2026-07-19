"""GCP nested-virtualization VM provider.

Wraps the existing GCP code from physical-router-test-automation.
"""

from __future__ import annotations

import logging
import os
from tollgate_lab.cloud.provider import VMConfig, VMInstance

log = logging.getLogger(__name__)


class GCPProvider:
    """GCP cloud VM provider (delegates to existing infrastructure)."""

    def __init__(self):
        if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set")
        log.warning("GCPProvider is a stub — use physical-router-test-automation's cloud-lab.py for full functionality")

    def create(self, config: VMConfig) -> VMInstance:
        raise NotImplementedError("Use scripts/cloud-lab.py from physical-router-test-automation")

    def destroy(self, name: str) -> None:
        raise NotImplementedError("Use scripts/cloud-lab.py")

    def status(self, name: str) -> str:
        raise NotImplementedError("Use scripts/cloud-lab.py")

    def list_vms(self, label_filter: str = "") -> list[VMInstance]:
        return []

    def extend_lease(self, name: str, minutes: int = 60) -> None:
        raise NotImplementedError("Use scripts/cloud-lab.py")
