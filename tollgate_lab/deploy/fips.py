"""Deploy FIPS to an OpenWrt router.

Downloads the latest FIPS .ipk from GitHub Actions CI
and installs it on a router via SSH.
"""

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

FIPS_REPO = "Amperstrand/fips"
FIPS_WORKFLOW = "package-openwrt.yml"
FIPS_SERVICE_NAME = "fips"


def download_fips_ipk(
    arch: str = "aarch64_cortex-a53",
    branch: str = "main",
    dest_dir: str = "/tmp",
) -> Path:
    """Download latest FIPS .ipk from GitHub Actions.

    Args:
        arch: Target architecture (aarch64_cortex-a53, x86_64, etc.)
        branch: Branch to download from
        dest_dir: Where to save the .ipk file

    Returns:
        Path to downloaded .ipk file
    """
    dest = Path(dest_dir) / f"fips-{arch}.ipk"
    cmd = [
        "gh", "run", "download",
        "-R", FIPS_REPO,
        "--workflow", FIPS_WORKFLOW,
        "--branch", branch,
        "-n", f"fips-{arch}",
        "-D", str(dest.parent / f"fips-dl-{arch}"),
    ]
    log.info(f"Downloading FIPS .ipk for {arch}...")
    subprocess.run(cmd, check=True, capture_output=True)

    # Find the .ipk in the downloaded directory
    dl_dir = dest.parent / f"fips-dl-{arch}"
    ipk_files = list(dl_dir.glob("*.ipk"))
    if not ipk_files:
        raise FileNotFoundError(f"No .ipk found in {dl_dir}")

    # Move to final destination
    ipk_files[0].rename(dest)
    return dest


def install_fips_on_router(
    ssh_host: str,
    ssh_user: str = "root",
    ipk_path: Path | None = None,
    config: dict | None = None,
) -> bool:
    """Install FIPS on an OpenWrt router.

    Args:
        ssh_host: Router IP address
        ssh_user: SSH username
        ipk_path: Path to .ipk file (auto-download if None)
        config: FIPS config dict to write to /etc/fips/fips.yaml

    Returns:
        True if FIPS service is running after installation
    """
    if ipk_path is None:
        ipk_path = download_fips_ipk()

    ssh_target = f"{ssh_user}@{ssh_host}"

    def ssh(cmd):
        return subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", ssh_target, cmd],
            capture_output=True, text=True, timeout=60,
        )

    # Upload .ipk
    log.info(f"Uploading {ipk_path} to {ssh_target}...")
    subprocess.run(
        ["scp", "-o", "StrictHostKeyChecking=no", str(ipk_path),
         f"{ssh_target}:/tmp/fips.ipk"],
        check=True, timeout=120,
    )

    # Install
    log.info("Installing FIPS package...")
    result = ssh("opkg install /tmp/fips.ipk --force-reinstall 2>&1")
    log.info(result.stdout)

    # Write config if provided
    if config:
        import yaml
        config_str = yaml.dump(config, default_flow_style=False)
        ssh(f"mkdir -p /etc/fips && cat > /etc/fips/fips.yaml << 'EOF'\n{config_str}\nEOF")

    # Start service
    log.info("Starting FIPS service...")
    ssh("service fips start || /etc/init.d/fips start || true")

    import time
    time.sleep(3)

    # Verify
    result = ssh("service fips status || /etc/init.d/fips status || echo 'not running'")
    if "running" in result.stdout:
        log.info("FIPS is running!")
        return True
    else:
        log.warning(f"FIPS not running: {result.stdout}")
        return False


def default_fips_config(
    adapter: str = "hci0",
    udp_bind: str = "0.0.0.0:2121",
    tun: bool = False,
    dns: bool = False,
) -> dict:
    """Generate a default FIPS config for OpenWrt routers."""
    return {
        "node": {
            "identity": {"persistent": True},
            "rekey": {"after_secs": 1800, "enabled": True},
        },
        "transports": {
            "udp": {"bind_addr": udp_bind},
        },
        "tun": {"enabled": tun},
        "dns": {"enabled": dns},
    }
