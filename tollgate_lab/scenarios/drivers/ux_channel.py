"""Execution channel + timing + click transport for UX adapters.

Ported from the validated rig reference (tests/ux/uxlib in omarchy-cashu):
``vm.py``'s base64 round-trip guest execution (payloads survive nested ssh
quoting byte-clean), ``waiting.py``'s evidence-inlining retry loop, and the
ydotool click transport used inside the Omarchy guest.

Everything here is injectable so scenario unit tests run with fakes — no
ssh, no guest, no Wayland.
"""

from __future__ import annotations

import base64
import shlex
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeVar

__all__ = [
    "ClickBackend",
    "ExecChannel",
    "SshExec",
    "WaitTimeoutError",
    "YdotoolBackend",
    "payload_command",
    "wait_until",
]

_T = TypeVar("_T")

DEFAULT_GUEST_ENV = "WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/1000"
DEFAULT_YDOTOOL_SOCKET = "/tmp/.ydotool_socket"


def payload_command(command: str) -> str:
    """Wrap ``command`` so quotes/JSON survive nested ssh round-trips.

    The guest runs ``echo <b64> | base64 -d | bash`` — the payload travels
    as one base64 word inside one shell argument, immune to any layer of
    nested quoting (the vm.py lesson: JSON payloads with single quotes died
    horribly through the laptop → rig → guest chain).
    """
    encoded = base64.b64encode(command.encode()).decode("ascii")
    return f"echo {encoded} | base64 -d | bash"


class ExecChannel(Protocol):
    """Run a shell command on the client; returns stdout."""

    def run(self, command: str, *, timeout_s: float = 30.0) -> str:
        """Execute ``command``; return decoded stdout."""
        ...

    def run_bytes(self, command: str, *, timeout_s: float = 60.0) -> bytes:
        """Execute ``command``; return raw stdout (binary-safe pulls)."""
        ...


class SshExec:
    """ExecChannel over an ``ssh`` prefix string (the profile's ``vssh``)."""

    def __init__(self, vssh: str) -> None:
        self._argv_prefix = shlex.split(vssh)

    def run(self, command: str, *, timeout_s: float = 30.0) -> str:
        return self.run_bytes(command, timeout_s=timeout_s).decode(errors="replace")

    def run_bytes(self, command: str, *, timeout_s: float = 60.0) -> bytes:
        proc = subprocess.run(
            [*self._argv_prefix, payload_command(command)],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            stderr = proc.stderr.decode(errors="replace")[-500:]
            raise RuntimeError(
                f"guest command failed (rc={proc.returncode}): {command[:160]!r}; stderr: {stderr}"
            )
        return proc.stdout


class WaitTimeoutError(AssertionError):
    """A retried condition never held before its deadline."""

    def __init__(self, describe: str, timeout_s: float, attempts: int, evidence: str) -> None:
        super().__init__(
            f"condition never held within {timeout_s:.1f}s ({attempts} attempts): {describe}; "
            f"last evidence: {evidence}"
        )
        self.describe = describe
        self.timeout_s = timeout_s
        self.attempts = attempts
        self.evidence = evidence


def wait_until(
    probe: Callable[[], _T | None],
    *,
    timeout_s: float,
    interval_s: float = 0.4,
    describe: str = "condition",
    evidence: Callable[[], str] | None = None,
) -> _T:
    """Poll ``probe`` until it returns non-None; return its value.

    The assertion IS the wait (uxlib waiting.py doctrine): never sleep for
    readiness, and fail with the evidence needed to triage without a rerun.
    """
    deadline = time.monotonic() + timeout_s
    attempts = 0
    while True:
        attempts += 1
        found = probe()
        if found is not None:
            return found
        if time.monotonic() >= deadline:
            detail = evidence() if evidence is not None else "no evidence callback"
            raise WaitTimeoutError(describe, timeout_s, attempts, detail)
        time.sleep(interval_s)


class ClickBackend(Protocol):
    """Synthetic click transport at absolute screen coordinates."""

    def click_at(self, x: int, y: int) -> None:
        """Move to (x, y) and click the left button."""
        ...


class YdotoolBackend:
    """Click inside the Omarchy guest via ydotool over the exec channel.

    vm.py's exact dispatch: absolute mousemove, a short settle, then the
    left-button click (0xC0), both under the guest's YDOTOOL_SOCKET.
    """

    def __init__(
        self,
        exec_channel: ExecChannel,
        *,
        ydotool_socket: str = DEFAULT_YDOTOOL_SOCKET,
        settle_s: float = 0.15,
    ) -> None:
        self._exec = exec_channel
        self._socket = ydotool_socket
        self._settle_ms = int(settle_s * 1000)

    def click_at(self, x: int, y: int) -> None:
        env = f"YDOTOOL_SOCKET={self._socket}"
        self._exec.run(
            f"{env} ydotool mousemove -a -x {x} -y {y} && sleep {self._settle_ms / 1000:g} && "
            f"{env} ydotool click 0xC0"
        )


def grim_pull_command(guest_env: str, remote_path: Path | str = "/tmp/ux-shot.png") -> str:
    """Screencopy inside the guest and cat the PNG back (vm.py pattern)."""
    return f"{guest_env} grim -t png {remote_path} && cat {remote_path}"
