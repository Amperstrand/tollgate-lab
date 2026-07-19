"""Cloud lab VM provider abstraction."""

from __future__ import annotations

import os
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass
class VMConfig:
    """Configuration for a cloud lab VM."""
    name: str = "tollgate-lab-vm"
    image: str = "debian-12"
    machine_type: str = "n2-standard-4"
    disk_size_gb: int = 20
    zone: str = "europe-west1-b"
    ssh_key: str = ""
    run_id: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class VMInstance:
    """A running cloud lab VM."""
    name: str
    external_ip: str
    internal_ip: str
    status: str
    provider: str
    ssh_command: str = ""

    @property
    def is_running(self) -> bool:
        return self.status.lower() in ("running", "active")


class VMProvider(Protocol):
    """Abstract VM provider interface."""

    def create(self, config: VMConfig) -> VMInstance:
        """Create and start a VM."""
        ...

    def destroy(self, name: str) -> None:
        """Destroy a VM."""
        ...

    def status(self, name: str) -> str:
        """Get VM status."""
        ...

    def list_vms(self, label_filter: str = "") -> list[VMInstance]:
        """List VMs."""
        ...

    def extend_lease(self, name: str, minutes: int = 60) -> None:
        """Extend VM lease."""
        ...


def get_provider(name: str | None = None) -> VMProvider | None:
    """Get a VM provider by name.

    Auto-detects based on available credentials:
    1. SHC_API_KEY env var → SHC provider
    2. GOOGLE_APPLICATION_CREDENTIALS → GCP provider
    3. No credentials → Local QEMU provider
    """
    if name is None:
        if os.environ.get("SHC_API_KEY"):
            name = "shc"
        elif os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            name = "gcp"
        else:
            name = "qemu"

    if name == "shc":
        from tollgate_lab.cloud.shc import SHCProvider
        return SHCProvider()
    elif name == "gcp":
        from tollgate_lab.cloud.gcp import GCPProvider
        return GCPProvider()
    elif name == "qemu":
        from tollgate_lab.cloud.qemu import QEMUProvider
        return QEMUProvider()

    raise ValueError(f"Unknown provider: {name}")


def list_providers() -> list[str]:
    """List available VM providers."""
    providers = []
    if os.environ.get("SHC_API_KEY"):
        providers.append("shc")
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        providers.append("gcp")
    providers.append("qemu")  # Always available
    return providers
