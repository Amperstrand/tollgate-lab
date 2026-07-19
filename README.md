# tollgate-lab

Unified hardware testing library for TollGate, FIPS, and Amperstrand embedded
projects. Built on [labgrid](https://github.com/labgrid-project/labgrid) for
device orchestration.

## Supported Hardware

| Device Type | Driver | Transport |
|-------------|--------|-----------|
| OpenWrt routers | `RouterDriver` | SSH |
| ESP32 / ESP8266 | `EspFlashDriver` | USB serial (esptool) |
| STM32 | `SerialConsoleDriver` | USB serial (st-flash) |
| Bluetooth adapters | `BleAdapterDriver` | HCI (via SSH or local) |
| Android phones | `AndroidDriver` | ADB |
| FIPS daemons | `FipsServiceDriver` | systemd / launchd |

## Installation

```bash
pip install tollgate-lab
```

For development:

```bash
pip install -e ".[dev]"
```

## Quick Start

### Define a labgrid environment

```yaml
# environments/physical-lab.yaml
targets:
  router-alpha:
    role: host
    name: GL-MT3000 Alpha
    params:
      ssh_host: "192.168.13.112"
      ssh_user: "root"
      ssh_password: "your-password"

  esp32-d0wd:
    role: child
    name: ESP32 on /dev/ttyUSB0
    params:
      serial_port: "/dev/ttyUSB0"
      chip: "esp32"

  linux-host:
    role: host
    name: Test controller
    params:
      ssh_host: "127.0.0.1"
```

### Write a test

```python
import pytest
from tollgate_lab.fixtures.router import router_session
from tollgate_lab.fixtures.esp32 import esp32_flash

def test_router_responds(router_session):
    result = router_session.run("echo hello")
    assert result.stdout.strip() == "hello"

def test_fips_service_running(router_session):
    result = router_session.run("service fips status")
    assert "running" in result.stdout

@pytest.mark.hardware
def test_esp32_flash_and_boot(esp32_flash):
    assert esp32_flash.is_alive()
```

### Run tests

```bash
# Run with a specific environment
pytest --lg-env=environments/physical-lab.yaml tests/

# Run only hardware tests
pytest --lg-env=environments/physical-lab.yaml -m hardware tests/
```

## Architecture

tollgate-lab provides three layers:

1. **Drivers** (`tollgate_lab.drivers`) — labgrid-compatible device drivers
2. **Fixtures** (`tollgate_lab.fixtures`) — pytest fixtures that wrap drivers
3. **Reporting** (`tollgate_lab.reporting`) — Nostr result publishing

## Projects Using tollgate-lab

- [fips-lab](https://github.com/Amperstrand/fips-lab) — FIPS BLE networking tests
- [physical-router-test-automation](https://github.com/Amperstrand/physical-router-test-automation) — TollGate WiFi payment tests

## License

MIT
