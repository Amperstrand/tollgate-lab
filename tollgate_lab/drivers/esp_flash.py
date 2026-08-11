"""Driver for flashing firmware to ESP32 devices via esptool.

Supports multiple reset strategies for different board types:
- auto_reset: USB-UART bridge (CH340/CP210x/FT232) with DTR/RTS auto-reset
- firmware_rst: App firmware has CDC RST handler, use --after soft_reset
- manual: Operator presses physical BOOT+RST buttons
"""

import attr
import logging
import sys

from labgrid import target_factory
from labgrid.driver import Driver
from labgrid.protocol.commandprotocol import CommandProtocol

logger = logging.getLogger(__name__)


@target_factory.reg_driver
@attr.s(eq=False)
class EspFlashDriver(Driver):
    """Flash firmware images to ESP32-family microcontrollers.

    Handles ELF-to-binary conversion and correct partition offset.
    Uses esptool over SSH to the host with the USB-serial connection.
    """

    bindings = {"shell": "CommandProtocol"}

    chip = attr.ib(validator=attr.validators.instance_of(str))
    serial_port = attr.ib(validator=attr.validators.instance_of(str))
    tool = attr.ib(default="esptool", validator=attr.validators.instance_of(str))
    baud = attr.ib(default=460800, validator=attr.validators.instance_of(int))
    flash_addr = attr.ib(default="0x10000", validator=attr.validators.instance_of(str))
    reset_method = attr.ib(
        default="auto_reset",
        validator=attr.validators.in_(["auto_reset", "firmware_rst", "manual"]),
    )

    def _prompt_user(self, msg: str):
        logger.info("MANUAL INTERVENTION: %s", msg)
        print(f"\n  >>> {msg}\n", file=sys.stderr)
        input("  Press Enter when done...")

    def _before_flag(self) -> str:
        if self.reset_method == "auto_reset":
            return "--before default_reset"
        return "--before no_reset"

    def _after_flag(self) -> str:
        if self.reset_method == "auto_reset":
            return "--after hard_reset"
        if self.reset_method == "firmware_rst":
            return "--after soft_reset"
        return "--after no_reset"

    def _ensure_bootloader(self):
        if self.reset_method == "manual":
            self._prompt_user(
                f"Press BOOT+RST on the board at {self.serial_port} to enter bootloader"
            )

    @Driver.check_active
    def flash(self, firmware_path: str):
        """Write firmware to the ESP32.

        Args:
            firmware_path: Path to ELF or binary on the remote host.
                          ELF files are auto-converted via elf2image.
        """
        self._ensure_bootloader()

        if firmware_path.endswith(".elf") or "." not in firmware_path.rsplit("/", 1)[-1]:
            binary_path = "/tmp/fips-flash.bin"
            convert_cmd = (
                f"sudo {self.tool} --chip {self.chip} "
                f"elf2image {firmware_path} --output {binary_path}"
            )
            self.shell.run_check(convert_cmd)
            flash_path = binary_path
        else:
            flash_path = firmware_path

        cmd = (
            f"sudo {self.tool}"
            f" --chip {self.chip}"
            f" --port {self.serial_port}"
            f" --baud {self.baud}"
            f" {self._before_flag()}"
            f" {self._after_flag()}"
            f" write_flash {self.flash_addr} {flash_path}"
        )
        return self.shell.run_check(cmd)

    @Driver.check_active
    def erase_flash(self):
        """Erase the entire flash chip."""
        self._ensure_bootloader()
        return self.shell.run_check(
            f"sudo {self.tool} --chip {self.chip} --port {self.serial_port}"
            f" {self._before_flag()} erase_flash"
        )

    @Driver.check_active
    def reset_app(self):
        """Reset the running app via firmware CDC RST handler.

        Only works when reset_method='firmware_rst' and the app
        firmware has the CDC RST handler installed.
        """
        if self.reset_method != "firmware_rst":
            raise NotImplementedError(
                f"reset_app requires firmware_rst, got {self.reset_method}"
            )
        self.shell.run_check(
            f"echo RST > {self.serial_port}"
        )
