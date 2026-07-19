"""Sovereign Hybrid Compute (SHC) VM provider.

SHC is Amperstrand's cloud VM service. It provides nested-virtualization
VMs for running OpenWrt routers in QEMU for automated testing.

Cost: ~$0.01 per test run.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from typing import cast

from tollgate_lab.cloud.provider import VMConfig, VMInstance, VMProvider

log = logging.getLogger(__name__)

SHC_API_BASE = "https://shc.amperstrand.com/api/v1"
SHC_DEFAULT_IMAGE = "debian-12-nested"
SHC_DEFAULT_MACHINE = "n2-standard-4"


class SHCProvider:
    """SHC cloud VM provider."""

    def __init__(self):
        self.api_key = os.environ.get("SHC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("SHC_API_KEY not set")

    def _api(self, method: str, path: str, **kwargs) -> dict:
        """Call SHC API."""
        import requests

        url = f"{SHC_API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        resp = requests.request(method, url, headers=headers, timeout=120, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def create(self, config: VMConfig) -> VMInstance:
        """Create a VM on SHC."""
        labels = {"tollgate-run": "true", **config.labels}
        if config.run_id:
            labels["run-id"] = config.run_id

        payload = {
            "name": config.name,
            "image": config.image or SHC_DEFAULT_IMAGE,
            "machine_type": config.machine_type or SHC_DEFAULT_MACHINE,
            "disk_size_gb": config.disk_size_gb,
            "labels": labels,
        }

        result = self._api("POST", "/vms", json=payload)

        # Wait for VM to be ready
        for _ in range(60):
            status = self.status(config.name)
            if status == "running":
                break
            time.sleep(10)

        # Get VM details
        details = self._api("GET", f"/vms/{config.name}")
        return VMInstance(
            name=config.name,
            external_ip=details.get("external_ip", ""),
            internal_ip=details.get("internal_ip", ""),
            status="running",
            provider="shc",
            ssh_command=f"ssh ubuntu@{details.get('external_ip', '')}",
        )

    def destroy(self, name: str) -> None:
        """Destroy a VM."""
        self._api("DELETE", f"/vms/{name}")
        log.info(f"Destroyed SHC VM: {name}")

    def status(self, name: str) -> str:
        """Get VM status."""
        try:
            result = self._api("GET", f"/vms/{name}")
            return result.get("status", "unknown")
        except Exception:
            return "not_found"

    def list_vms(self, label_filter: str = "") -> list[VMInstance]:
        """List VMs."""
        params = {}
        if label_filter:
            params["filter"] = label_filter

        result = self._api("GET", "/vms", params=params)
        vms = []
        for vm in result.get("vms", []):
            vms.append(VMInstance(
                name=vm["name"],
                external_ip=vm.get("external_ip", ""),
                internal_ip=vm.get("internal_ip", ""),
                status=vm.get("status", "unknown"),
                provider="shc",
            ))
        return vms

    def extend_lease(self, name: str, minutes: int = 60) -> None:
        """Extend VM lease."""
        self._api("POST", f"/vms/{name}/extend", json={"minutes": minutes})
        log.info(f"Extended SHC VM {name} lease by {minutes} minutes")
