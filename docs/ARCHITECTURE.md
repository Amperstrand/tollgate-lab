# tollgate-lab Architecture

## Overview

tollgate-lab is built on [labgrid](https://labgrid.readthedocs.io/) for device
orchestration. Labgrid provides a resource → driver → protocol → strategy
abstraction for hardware testing.

## Labgrid Architecture (from research)

```
Resources (passive hardware endpoints)
    ↓
Drivers (implement protocols, use resources)
    ↓
Protocols (interfaces: ConsoleProtocol, CommandProtocol)
    ↓
Strategies (state machines for complex workflows)
```

### Key labgrid concepts:
- **Resource**: Declares a hardware endpoint (NetworkService, USBSerialPort, etc.)
- **Driver**: Implements a protocol to interact with a resource
- **Protocol**: Interface contract (CommandProtocol, ConsoleProtocol)
- **Strategy**: State machine that orchestrates driver transitions
- **Target**: Groups resources + drivers for a single device
- **Environment**: YAML file defining all targets for a test session

## tollgate-lab Custom Drivers

### Extracted (from existing repos):

| Driver | Source | Labgrid Protocol | Hardware |
|--------|--------|------------------|----------|
| `EspFlashDriver` | fips-lab | CommandProtocol | ESP32/ESP8266 via esptool |
| `FipsServiceDriver` | fips-lab | CommandProtocol | FIPS daemon (systemd/launchd) |
| `FipsctlDriver` | fips-lab | CommandProtocol | fipsctl CLI wrapper |
| `RouterSSH` | physical-router | (standalone) | OpenWrt routers via SSH |

### To be built (labgrid-native):

| Driver | Protocol | Hardware | Priority |
|--------|----------|----------|----------|
| `AndroidADBDriver` | CommandProtocol | Android phones | High |
| `PlaywrightDriver` | (custom) | Browser testing | Medium |
| `Stm32FlashDriver` | CommandProtocol | STM32 via st-flash | Low |
| `BleAdapterDriver` | (custom) | Bluetooth adapters | Low |

## Labgrid Best Practices (from research)

### DO:
- Use `USBSerialPort` with udev `match` rules (never hard-code `/dev/ttyUSB0`)
- Use `Strategy` state machines for boot → shell → test transitions
- Use `target.get_active_driver()` after reboots (not cached driver references)
- Use `@pytest.mark.lg_feature("camera")` for feature-gated tests
- Use coordinator/exporter mode for multi-machine labs
- Use `RemotePlace` for remote device access

### DON'T:
- Don't hard-code serial paths (`/dev/ttyUSB0` → use udev match)
- Don't skip driver deactivation after reboots
- Don't assume devices are in correct state (always use strategies)
- Don't forget to acquire/release places in CI jobs
- Don't use `kernel.printk = 7` (breaks console parsing)

## Environment YAML Schema

```yaml
targets:
  router-alpha:
    resources:
      NetworkService:
        address: "192.168.13.112"
        username: "root"
    drivers:
      SSHDriver:
        keyfile: ""

  esp32-d0wd:
    resources:
      USBSerialPort:
        match:
          ID_SERIAL_SHORT: "P-00-00682"
          ID_USB_INTERFACE_NUM: "00"
        speed: 115200
    drivers:
      SerialDriver: {}
```

## Custom Driver Pattern

```python
import attr
from labgrid import target_factory
from labgrid.driver import Driver
from labgrid.protocol.commandprotocol import CommandProtocol


@target_factory.reg_driver
@attr.s(eq=False)
class CustomRouterDriver(Driver, CommandProtocol):
    bindings = {"network": "NetworkService"}

    def __attrs_post_init__(self):
        super().__attrs_post_init__()

    def run(self, command, timeout=None):
        # Implement CommandProtocol.run
        ...

    def run_check(self, command, timeout=None):
        # Implement CommandProtocol.run_check
        ...
```

## Migration Plan

See [Issue #1](https://github.com/Amperstrand/tollgate-lab/issues/1) for the
full 7-wave migration roadmap.

## SHC (Sovereign Hybrid Compute) Integration

tollgate-lab is designed to work with SHC cloud labs for CI testing:
- Deploy OpenWrt VMs on SHC
- Run FIPS + TollGate tests in isolated cloud environments
- Cost: ~$0.01 per test run on SHC vs ~$0.10 on GCP

Future: tollgate-lab will include SHC provisioning helpers for automated
cloud lab creation and teardown.
