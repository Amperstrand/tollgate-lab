# AGENTS.md — tollgate-lab

> Unified hardware testing library for TollGate, FIPS, and Amperstrand embedded
> projects. Built on [labgrid](https://labgrid.readthedocs.io/) for device
> orchestration. **Shared infrastructure layer** consumed by
> [fips-lab](../fips-lab) and physical-router-test-automation — eventually may
> subsume both (Wave 7).

## What this repo does

tollgate-lab is the **shared infrastructure library** for all Amperstrand
hardware testing. It provides labgrid-compatible device drivers, pytest
fixtures, cloud-VM provisioning, deploy helpers, and Nostr result reporting — so
that fips-lab (BLE mesh tests) and physical-router-test-automation (TollGate
WiFi payment tests) don't duplicate device-management code.

It is **not** a test suite itself. Downstream repos write tests against
tollgate-lab's drivers/fixtures; tollgate-lab provides the reusable building
blocks + unit tests for those building blocks.

## Architecture (three layers on labgrid)

```
Consumers:   fips-lab · physical-router-test-automation
                 ↓ depends on
Layer 3:     reporting/    Nostr result publishing (nostr_events.py)
Layer 2:     fixtures/     pytest fixtures wrapping drivers (sessions.py)
Layer 1:     drivers/      labgrid-compatible device drivers
             hardware/     HardwareLock (cross-test mutex on physical devices)
             deploy/       CI artifact + FIPS/TollGate deploy helpers
             cloud/        VM provisioning (SHC / GCP / QEMU)
             strategy/     OpenWrtStrategy state machine
                 ↓ built on
             labgrid       resource → driver → protocol → strategy
```

### Labgrid model

- **Resource** — declares a hardware endpoint (NetworkService, USBSerialPort)
- **Driver** — implements a protocol to interact with a resource
- **Protocol** — interface contract (CommandProtocol, ConsoleProtocol)
- **Strategy** — state machine orchestrating driver transitions
- **Target** — groups resources + drivers for a single device
- **Environment** — YAML defining all targets for a test session

See `docs/ARCHITECTURE.md` for labgrid best practices (udev match rules,
strategy usage, coordinator/exporter mode, `target.get_active_driver()` after
reboots, etc.).

## Modules (8 extracted labgrid drivers + supporting)

| Module | Source repo | Lines | Purpose |
|--------|-------------|-------|---------|
| `drivers/ssh.py` | fips-lab | 178 | `SSHAdapter` + `_ssh_run` — SSH command execution via paramiko, used by all SSH-bound drivers |
| `drivers/esp_flash.py` | fips-lab | 61 | `EspFlashDriver` — ESP32/ESP8266 firmware flashing via `esptool` over USB serial |
| `drivers/fips_service.py` | fips-lab | 98 | `FipsServiceDriver` — FIPS daemon lifecycle via systemd (Linux) / launchd (macOS); Linux restart cycles BLE adapter |
| `drivers/fipsctl.py` | fips-lab | 105 | `FipsctlDriver` — wraps the `fipsctl` CLI (status, peers, echo/throughput benchmarks) |
| `drivers/router.py` | physical-router | 784 | `Router` / `RouterDriver` — OpenWrt router management over SSH |
| `drivers/serial_console.py` | physical-router | 105 | `SerialConsoleDriver` — STM32 / serial console interaction |
| `hardware/lock.py` | physical-router | 117 | `HardwareLock` — cross-test mutex preventing concurrent access to scarce physical hardware |
| `deploy/ci_artifact.py` | physical-router | 1179 | CI artifact resolution + deploy — fetches Nostr/NIP-94/Blossom-published build artifacts, deploys to routers |

**Supporting modules:**
- `drivers/android_adb.py` — `AndroidADBDriver` (ADB for Android phones) — labgrid-native, built fresh
- `drivers/playwright_browser.py` — `PlaywrightBrowserDriver` — browser testing integration
- `drivers/labgrid_router.py` — labgrid-native router driver variant
- `strategy/openwrt.py` — `OpenWrtStrategy` state machine (off → boot → shell → test)
- `fixtures/sessions.py` — NEW (not extracted): pytest fixtures `router_session`, `hardware_lock`, `fips_daemon`
- `reporting/nostr_events.py` — `publish_test_result` — Nostr result publishing
- `deploy/fips.py`, `deploy/tollgate.py` — FIPS + TollGate deploy helpers
- `cloud/` — VM provisioning (below)
- `public.py` — stable public API surface (`from tollgate_lab import HardwareLock`)

**Public API** (`tollgate_lab/__init__.py`, `tollgate_lab/public.py`):
```python
from tollgate_lab import HardwareLock
from tollgate_lab.public import Router
```

## Cloud providers (3 supported)

`tollgate_lab/cloud/` provides a `VMProvider` abstraction for spinning up
isolated cloud labs (primarily OpenWrt-in-QEMU for automated testing). Provider
selection auto-detects from available credentials:

| Provider | Module | Trigger | Cost/run | Notes |
|----------|--------|---------|----------|-------|
| **SHC** (Sovereign Hybrid Compute) | `cloud/shc.py` | `SHC_API_KEY` env var | ~$0.01 | Amperstrand's own nested-virtualization cloud. Default image `debian-12-nested`, machine `n2-standard-4`. |
| **GCP** (Google Cloud) | `cloud/gcp.py` | `GOOGLE_APPLICATION_CREDENTIALS` env var | ~$0.10 | Standard Google Compute Engine. |
| **QEMU** (local) | `cloud/qemu.py` | always available (fallback) | free | Local QEMU VMs — no credentials needed. |

```python
from tollgate_lab.cloud.provider import get_provider, list_providers, VMConfig
provider = get_provider()          # auto-detect, or get_provider("shc")
vm = provider.create(VMConfig(name="tollgate-test-1"))
# ... run tests against vm.ssh_command ...
provider.destroy(vm.name)
```

All providers implement the same `VMProvider` protocol: `create()`, `destroy()`,
`status()`, `list_vms()`, `extend_lease()`.

### SHC ecosystem dependency

The SHC provider (`tollgate_lab.cloud.shc`) integrates with Amperstrand's
**SHC (Sovereign Hybrid Compute)** cloud service and is part of the broader SHC
ecosystem alongside **shc-toolkit** (the standalone SHC CLI/SDK at
`/home/ubuntu/src/shc-toolkit`). tollgate-lab's `shc.py` is a self-contained
HTTP client to the SHC API (`https://shc.amperstrand.com/api/v1`) and does not
import shc-toolkit as a Python dependency, but the two are designed to be used
together — shc-toolkit for ad-hoc VM management, tollgate-lab for test-integrated
provisioning.

> **Critical SHC gotcha:** `provisioning_state` never becomes `"ready"` — check
> `service_status` + assigned IPs instead. (See `/home/ubuntu/src/shc-pulumi/AGENTS.md`.)

## Migration status (from Issue #1)

Roadmap: gradually migrate fips-lab and physical-router-test-automation to
depend on tollgate-lab for shared infrastructure. Eventually tollgate-lab may
subsume both.

| Wave | Title | Status |
|------|-------|--------|
| **1** | Foundation — repo/package structure, extract shared modules, environment templates, fixtures, import tests | ✅ **DONE** |
| **2** | Import fixes — fix `lib.`/`fips_lab.` references in extracted modules, clean public API, type hints, docstrings | ✅ **DONE** |
| **3** | FIPS tests — FIPS deploy to physical-router-test-automation, daemon startup on GL-MT3000, gateway NAT, `.fips` DNS, FIPS+TollGate coexistence | ✅ **DONE** |
| **4** | Migrate fips-lab — `pyproject.toml` depends on tollgate-lab, replace `fips_lab/drivers/*` + `ssh_adapters.py` + `lib/result_publisher.py` | ✅ **DONE** (fips-lab `pyproject.toml` now lists `tollgate-lab>=0.1.0`; `fips_lab/__init__.py` re-exports from tollgate_lab) |
| **5** | Migrate physical-router-test-automation — `requirements.txt` includes tollgate-lab, replace `lib/router.py`, `lib/hardware_lock.py`, `lib/serial_console.py`, `lib/deploy.py` | ✅ **DONE** (937 tests collect, 337 unit pass) |
| **6** | Labgrid migration (physical-router) — labgrid env YAML for GL-MT3000, migrate SSH tests to RouterDriver, AndroidUSBDriver, Playwright integration | ✅ **DONE** |
| **7** | Consolidation (FUTURE) — evaluate merging fips-lab tests into tollgate-lab; evaluate merging physical-router tests; tollgate-lab becomes the single hardware testing entry point | 🔜 **FUTURE** |

**Net:** ~2720 lines extracted from 9 modules across fips-lab and
physical-router-test-automation into tollgate-lab. Both downstream repos now
depend on tollgate-lab.

## Testing protocol

### Unit tests (no hardware required)

```bash
make dev          # pip install -e ".[dev]"
make test-unit    # 52 unit tests across all modules
# or directly:
python -m pytest tests/test_package.py tests/test_cloud.py tests/test_ssh.py \
    tests/test_router.py tests/test_hardware_lock.py tests/test_labgrid_drivers.py \
    tests/test_serial.py tests/test_deploy.py tests/test_strategy.py \
    tests/test_deploy_helpers.py -v
```

Test files (`tests/`):
- `test_package.py` — import/structure tests
- `test_cloud.py` — cloud provider abstraction
- `test_ssh.py` — SSH adapter
- `test_router.py` — router driver
- `test_hardware_lock.py` — hardware lock
- `test_labgrid_drivers.py` — labgrid driver registration
- `test_serial.py` — serial console
- `test_deploy.py`, `test_deploy_helpers.py` — CI artifact + deploy helpers
- `test_strategy.py` — OpenWrtStrategy

### Hardware integration tests (require physical devices)

```bash
make test-fips        # FIPS integration (ROUTER_SSH_HOST=192.168.13.112)
make test-tollgate    # TollGate integration
make test-all         # lint + unit + fips + tollgate
```

Hardware tests are marked `@pytest.mark.hardware` (skipped without devices).
Also: `@pytest.mark.benchmark`, `@pytest.mark.slow`.

### CI (`.github/workflows/ci.yml`)

On push/PR to `main`: Python 3.12, `pip install -e ".[dev]"`, `ruff check`,
`ruff format --check`, `pytest tests/ -v`.

### Lint

```bash
make lint    # ruff check + ruff format --check (line-length 100, py311)
```

## Projects using tollgate-lab

- **[fips-lab](https://github.com/Amperstrand/fips-lab)** — FIPS BLE networking
  tests. Depends on `tollgate-lab>=0.1.0`. FIPS-specific drivers
  (`fips_lab/strategy/fips.py`) sit on top of tollgate-lab's generic device
  management.
- **[physical-router-test-automation](https://github.com/Amperstrand/physical-router-test-automation)**
  — TollGate WiFi payment tests. Migrated `lib/` modules to tollgate-lab.

## Open issues

### Issue #1 — Migration roadmap (OPEN)

Full 7-wave migration plan (Waves 1–6 done, Wave 7 future — see table above).
[View on GitHub](https://github.com/Amperstrand/tollgate-lab/issues/1).

### Issue #2 — Session handoff: 2026-07-20 (OPEN)

State-of-everything snapshot covering ~20 hours of work. Key relevant points:
- 52 unit tests, 8 labgrid drivers, 3 cloud providers
- fips-lab migrated (depends on tollgate-lab)
- physical-router-test-automation migrated (937 tests collect, 337 unit pass)
- SHC credit: $80.18; 1 production SHC VM (europa-vpn-vps)
- **Critical gotcha:** SHC `provisioning_state` never becomes `"ready"` — check
  `service_status` + IPs.
[View on GitHub](https://github.com/Amperstrand/tollgate-lab/issues/2).

## Dependencies

- **labgrid** (`>=25.0`) — device orchestration framework
- **pytest** (`>=8.0`), **paramiko** (`>=3.4`), **pyserial** (`>=3.5`)
- **attrs** (`>=23.0`), **pyyaml** (`>=6.0`)
- **nostr-publish** (`>=0.1.0`) — Blossom/Nostr result publishing
- **shc-toolkit** (ecosystem) — SHC cloud VM management; tollgate-lab's
  `cloud/shc.py` is the test-integrated SHC client (self-contained HTTP, no
  Python import dependency, but designed to be used alongside shc-toolkit)

Dev: **ruff** (`>=0.4`), **mypy** (`>=1.10`), **pytest-cov** (`>=5.0`).

Python `>=3.11`. License: MIT.

## Quick start

```bash
make dev                                       # editable install with dev deps
make test-unit                                 # 52 unit tests
pytest --lg-env=environments/physical-lab.yaml tests/ -v   # with hardware
```

### Define an environment + write a test

```yaml
# environments/physical-lab.yaml
targets:
  router-alpha:
    role: host
    name: GL-MT3000 Alpha
    params:
      ssh_host: "192.168.13.112"
      ssh_user: "root"
```

```python
import pytest
from tollgate_lab.fixtures.sessions import router_session

def test_router_responds(router_session):
    result = router_session.run("echo hello")
    assert result.stdout.strip() == "hello"
```

## Supported hardware

| Device Type | Driver | Transport |
|-------------|--------|-----------|
| OpenWrt routers | `RouterDriver` / `Router` | SSH |
| ESP32 / ESP8266 | `EspFlashDriver` | USB serial (esptool) |
| STM32 | `SerialConsoleDriver` | USB serial (st-flash) |
| Bluetooth adapters | `BleAdapterDriver` | HCI (via SSH or local) |
| Android phones | `AndroidADBDriver` | ADB |
| FIPS daemons | `FipsServiceDriver` | systemd / launchd |
