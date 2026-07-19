"""Deploy TollGate to an OpenWrt router.

Wraps the existing deploy.py logic from physical-router-test-automation
in a clean tollgate-lab API.
"""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

TOLLGATE_REPO = "Amperstrand/tollgate-module-basic-go"
TOLLGATE_SERVICE = "tollgate"


def install_tollgate_on_router(
    ssh_host: str,
    ssh_user: str = "root",
    branch: str = "main",
) -> bool:
    """Install latest TollGate CI build on a router.

    Args:
        ssh_host: Router IP address
        ssh_user: SSH username
        branch: Branch to install from

    Returns:
        True if TollGate service starts
    """
    ssh_target = f"{ssh_user}@{ssh_host}"

    def ssh(cmd):
        return subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target, cmd],
            capture_output=True, text=True, timeout=60,
        )

    # Download CI artifact
    log.info(f"Downloading TollGate from {branch} branch...")
    subprocess.run([
        "gh", "run", "download",
        "-R", TOLLGATE_REPO,
        "--branch", branch,
        "-D", "/tmp/tollgate-dl",
    ], check=True, capture_output=True)

    # Find .ipk files
    ipk_files = list(Path("/tmp/tollgate-dl").rglob("*.ipk"))
    if not ipk_files:
        raise FileNotFoundError("No .ipk found in CI artifacts")

    # Detect architecture
    arch_result = ssh("opkg print-architecture")
    router_arch = "aarch64_cortex-a53"
    for line in arch_result.stdout.split("\n"):
        if "aarch64" in line:
            router_arch = "aarch64_cortex-a53"
            break
        elif "x86_64" in line or "x86" in line:
            router_arch = "x86_64"
            break

    # Find matching .ipk
    matching = [f for f in ipk_files if router_arch.split("_")[0] in f.name]
    if not matching:
        matching = ipk_files  # fallback to first available

    ipk_path = matching[0]

    # Upload and install
    subprocess.run([
        "scp", "-o", "StrictHostKeyChecking=no",
        str(ipk_path), f"{ssh_target}:/tmp/tollgate.ipk"
    ], check=True, timeout=120)

    log.info("Installing TollGate...")
    result = ssh("opkg install /tmp/tollgate.ipk --force-reinstall 2>&1")
    log.info(result.stdout[:500])

    # Restart service
    ssh(f"service {TOLLGATE_SERVICE} restart || true")

    import time
    time.sleep(3)

    result = ssh(f"service {TOLLGATE_SERVICE} status")
    return "running" in result.stdout
