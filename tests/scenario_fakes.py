"""Fakes for scenario-layer tests — no network, no hardware.

Response scripting convention: each fake exposes a ``*_script`` list that is
popped per call; when the script runs dry the last entry sticks. Tests stay
explicit about every response the lifecycle will observe.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from tollgate_lab.scenarios.contract import (
    CaptureResult,
    ClientDriver,
    GatewayDriver,
    PayReceipt,
    SessionState,
    Usage,
)

_T = TypeVar("_T")


def sticky_pop(script: list[_T], default: _T) -> _T:
    if script:
        return script.pop(0)
    return default


class FakeClient:
    """Scriptable ClientDriver: balance bookkeeping + ssid responses."""

    def __init__(self, *, balance_sats: int = 0) -> None:
        self.name = "fake_client"
        self.balance_sats = balance_sats
        self.token_value = 21
        self.tokens: list[str] = []
        self.wifi_calls: list[str] = []
        self.commands: list[str] = []
        self.opened = False
        self._ssid: str | None = None
        self.active_ssid_script: list[str | None] = []

    def connect_wifi(self, ssid: str, *, timeout_s: int = 60) -> None:
        self.wifi_calls.append(ssid)
        self._ssid = ssid

    def active_ssid(self) -> str | None:
        return sticky_pop(self.active_ssid_script, self._ssid)

    def status(self) -> dict[str, object]:
        return {"balance_sats": self.balance_sats, "ssid": self._ssid}

    def inject_token(self, token: str) -> None:
        self.tokens.append(token)
        self.balance_sats += self.token_value

    def open_wallet_ux(self) -> None:
        self.opened = True

    def run_command(self, command: str, *, timeout_s: int = 15) -> str:
        self.commands.append(command)
        return f"ran: {command}"


class FakeActor:
    """PaymentActor bound to its FakeClient at construction; spends sats."""

    def __init__(self, client: FakeClient, *, sats: int = 21) -> None:
        self.strategy = "fake"
        self._client = client
        self.sats = sats
        self.pay_calls = 0

    def pay(self, client: ClientDriver, gateway: GatewayDriver) -> PayReceipt:
        self.pay_calls += 1
        self._client.balance_sats -= self.sats
        return PayReceipt(sats=self.sats, strategy=self.strategy, token="fake-token-spent")


class FakeGateway:
    """Scriptable GatewayDriver with call logging."""

    def __init__(self, *, ssid: str = "TollGate-Test") -> None:
        self._ssid = ssid
        self.calls: list[str] = []
        self.mint_count = 0
        self.advertise_error: Exception | None = None
        self.usage_script: list[Usage | None] = [Usage(used=0, allotment=3600)]
        self.session_state_script: list[SessionState] = [SessionState.active()]
        self.external_script: list[bool] = [False, True]

    def advertisement(self) -> dict[str, object]:
        self.calls.append("advertisement")
        if self.advertise_error is not None:
            raise self.advertise_error
        return {"ssid": self._ssid, "kind": 10021}

    def usage(self, client: ClientDriver) -> Usage | None:
        self.calls.append("usage")
        fallback = self.usage_script[-1] if self.usage_script else None
        return sticky_pop(self.usage_script, fallback)

    def session_state(self, client: ClientDriver) -> SessionState:
        self.calls.append("session_state")
        return sticky_pop(self.session_state_script, SessionState.none())

    def external_reachable(self, client: ClientDriver) -> bool:
        self.calls.append("external_reachable")
        return sticky_pop(self.external_script, self.external_script[-1])

    def mint_token(self, sats: int) -> str:
        self.calls.append("mint_token")
        self.mint_count += 1
        return f"fake-token-{self.mint_count}-{sats}sats"


class FailingCapture:
    """CaptureDriver whose every call raises — exercises best-effort paths."""

    def start(self, artifact_dir: Path) -> None:
        raise RuntimeError("encoder unavailable")

    def step(self, name: str) -> None:
        raise RuntimeError("marker grab failed")

    def stop(self) -> CaptureResult:
        raise RuntimeError("recorder stop failed")


class FakeCapture:
    """CaptureDriver that writes real frame/video files."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.steps: list[str] = []
        self._artifact_dir: Path | None = None

    def start(self, artifact_dir: Path) -> None:
        self.started = True
        self._artifact_dir = artifact_dir

    def step(self, name: str) -> None:
        self.steps.append(name)
        assert self._artifact_dir is not None
        frames = self._artifact_dir / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        (frames / f"{len(self.steps)}_{name}.png").write_bytes(b"png")

    def stop(self) -> CaptureResult:
        self.stopped = True
        assert self._artifact_dir is not None
        video = self._artifact_dir / "story.webm"
        video.write_bytes(b"webm")
        frame_paths = tuple(sorted((self._artifact_dir / "frames").glob("*.png")))
        return CaptureResult(video_path=video, frame_paths=frame_paths, duration_s=2.5)
