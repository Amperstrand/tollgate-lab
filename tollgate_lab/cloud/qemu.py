"""Local QEMU VM provider for development and CI.

Spawns OpenWrt + Debian VMs using QEMU on the local machine.
No cloud credentials needed — runs entirely locally.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from tollgate_lab.cloud.provider import VMConfig, VMInstance

log = logging.getLogger(__name__)

DEFAULT_OPENWRT_VERSION = "24.10.1"
DEFAULT_DEBIAN_IMAGE = "debian-12-nocloud-amd64.qcow2"
DEFAULT_WORKDIR = Path.home() / ".tollgate-lab-vms"


class QEMUProvider:
    """Local QEMU VM provider."""

    def __init__(self):
        self.workdir = DEFAULT_WORKDIR
        self.workdir.mkdir(parents=True, exist_ok=True)

    def create(self, config: VMConfig) -> VMInstance:
        """Create local QEMU VMs."""
        vm_dir = self.workdir / config.name
        vm_dir.mkdir(parents=True, exist_ok=True)

        # Download OpenWrt x86 image if needed
        openwrt_img = vm_dir / "openwrt.img"
        if not openwrt_img.exists():
            url = f"https://downloads.openwrt.org/releases/{DEFAULT_OPENWRT_VERSION}/targets/x86/64/openwrt-{DEFAULT_OPENWRT_VERSION}-x86-64-generic-ext4-rootfs.img.gz"
            subprocess.run(["wget", "-q", "-O", str(openwrt_img) + ".gz", url], check=True)
            subprocess.run(["gunzip", str(openwrt_img) + ".gz"], check=True)

        # Start QEMU (simplified — real impl would configure networking)
        log.info(f"QEMU VM {config.name} would start here (stub)")
        log.info(f"OpenWrt image: {openwrt_img}")

        return VMInstance(
            name=config.name,
            external_ip="127.0.0.1",
            internal_ip="10.99.99.1",
            status="running",
            provider="qemu",
            ssh_command=f"ssh root@127.0.0.1",
        )

    def destroy(self, name: str) -> None:
        """Destroy local VM."""
        vm_dir = self.workdir / name
        if vm_dir.exists():
            # Kill QEMU process
            subprocess.run(["pkill", "-f", f"name {name}"], capture_output=True)
            # Clean up
            import shutil
            shutil.rmtree(vm_dir, ignore_errors=True)
        log.info(f"Destroyed QEMU VM: {name}")

    def status(self, name: str) -> str:
        """Check if QEMU process is running."""
        result = subprocess.run(
            ["pgrep", "-f", f"name {name}"],
            capture_output=True
        )
        return "running" if result.returncode == 0 else "stopped"

    def list_vms(self, label_filter: str = "") -> list[VMInstance]:
        """List local VMs."""
        vms = []
        for vm_dir in self.workdir.iterdir():
            if vm_dir.is_dir():
                status = self.status(vm_dir.name)
                vms.append(VMInstance(
                    name=vm_dir.name,
                    external_ip="127.0.0.1",
                    internal_ip="",
                    status=status,
                    provider="qemu",
                ))
        return vms

    def extend_lease(self, name: str, minutes: int = 60) -> None:
        """No-op for local VMs."""
        pass
