"""Cloud lab provisioning for tollgate-lab.

Supports:
- Sovereign Hybrid Compute (SHC) — Amperstrand's cloud VM service
- GCP nested-virtualization — Google Cloud with KVM
- Local QEMU — virtual machines on the test host
"""

from tollgate_lab.cloud.provider import (
    VMProvider,
    get_provider,
    list_providers,
)

__all__ = ["VMProvider", "get_provider", "list_providers"]
