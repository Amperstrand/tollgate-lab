"""Omarchy UX adapter tests — fakes only: no guest, no network, no Wayland.

Covers the ported contracts (exec/vision/click seams), the 7ed5bdd
re-open-before-click rule, the pywayland-postmortem teardown discipline,
and the wf-recorder capture pipeline over scripted exec responses.
"""

from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path

import pytest
from scenario_fakes import FakeClient, FakeGateway

from tollgate_lab.scenarios.contract import ScenarioRoles
from tollgate_lab.scenarios.drivers import build_roles
from tollgate_lab.scenarios.drivers.scenario_omarchy_ux import OmarchyUxClient, UxButtonActor
from tollgate_lab.scenarios.drivers.scenario_wf_recorder import WfRecorderCapture
from tollgate_lab.scenarios.drivers.ux_channel import payload_command
from tollgate_lab.scenarios.drivers.ux_vision import Match
from tollgate_lab.scenarios.drivers.wayland_pointer import SessionFactory, VirtualPointer
from tollgate_lab.scenarios.profile import load_profile

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"


class FakeExec:
    """Scripted ExecChannel: records commands, pops scripted stdout.

    Repo fake convention: when a script runs dry, its last entry sticks.
    """

    def __init__(
        self, responses: list[str] | None = None, byte_responses: list[bytes] | None = None
    ):
        self.commands: list[str] = []
        self.timeouts: list[float] = []
        self.responses = list(responses or [])
        self.byte_responses = list(byte_responses or [])

    def run(self, command: str, *, timeout_s: float = 30.0) -> str:
        self.commands.append(command)
        self.timeouts.append(timeout_s)
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0] if self.responses else ""

    def run_bytes(self, command: str, *, timeout_s: float = 60.0) -> bytes:
        self.commands.append(command)
        if len(self.byte_responses) > 1:
            return self.byte_responses.pop(0)
        return self.byte_responses[0] if self.byte_responses else b""


class FakeVision:
    """Scripted TemplateVision recording the open/match order."""

    def __init__(self, matches: dict[str, Match] | None = None):
        self.matches = matches or {}
        self.asked: list[str] = []

    def wait_visible(self, template: str, *, timeout_s: float = 10.0) -> Match:
        self.asked.append(template)
        if template in self.matches:
            return self.matches[template]
        raise AssertionError(f"unexpected template {template!r}")


class FakeClick:
    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def click_at(self, x: int, y: int) -> None:
        self.points.append((x, y))


def make_client(
    exec_channel: FakeExec,
    vision: FakeVision | None = None,
    click: FakeClick | None = None,
) -> tuple[OmarchyUxClient, FakeVision, FakeClick]:
    vision = vision or FakeVision({"panel-open.png": Match(960, 20, 0.99)})
    click = click or FakeClick()
    client = OmarchyUxClient(
        vssh="ssh -p 2222 omarchy@127.0.0.1",
        templates="templates",
        exec_channel=exec_channel,
        vision=vision,
        click=click,
    )
    return client, vision, click


# ---- adapter composition via the shipped omarchy-ux-mock profile ----


def test_omarchy_ux_mock_profile_composes_real_adapters():
    roles = build_roles(load_profile(PROFILES_DIR / "omarchy-ux-mock.yaml"))

    assert isinstance(roles, ScenarioRoles)
    assert isinstance(roles.client, OmarchyUxClient)
    assert isinstance(roles.actor, UxButtonActor)
    assert roles.client.name == "omarchy_ux"
    assert roles.capture is not None and isinstance(roles.capture, WfRecorderCapture)


# ---- exec channel: base64 round-trip payload ----


def test_payload_command_base64_round_trips_quotes_and_json():
    command = """curl --json '{"token": "cashuB'\\''x"}' http://127.0.0.1:3939/receive"""
    wrapped = payload_command(command)

    assert wrapped.startswith("echo ") and " | base64 -d | bash" in wrapped
    encoded = wrapped.removeprefix("echo ").split(" | ", 1)[0]
    assert base64.b64decode(encoded).decode() == command


# ---- ClientDriver contract over the exec seam ----


def test_active_ssid_parses_the_yes_line():
    exec_ch = FakeExec(responses=["no:HomeNet\nyes:TollGate-VM\n"])
    client, _, _ = make_client(exec_ch)

    assert client.active_ssid() == "TollGate-VM"


def test_active_ssid_none_when_disconnected():
    exec_ch = FakeExec(responses=["no:HomeNet\n"])
    client, _, _ = make_client(exec_ch)
    assert client.active_ssid() is None

    exec_ch = FakeExec(responses=["yes:\n"])
    client, _, _ = make_client(exec_ch)
    assert client.active_ssid() is None, "empty ACTIVE ssid must not count as associated"


def test_connect_wifi_issues_nmcli_and_polls_until_associated():
    exec_ch = FakeExec(
        responses=[
            "",  # nmcli connect
            "no:HomeNet\n",  # poll 1: not yet
            "yes:TollGate-VM\n",  # poll 2: associated
        ]
    )
    client, _, _ = make_client(exec_ch)

    client.connect_wifi("TollGate-VM", timeout_s=10)

    assert exec_ch.commands[0] == "nmcli dev wifi connect TollGate-VM"
    assert exec_ch.commands.count("nmcli -t -f ACTIVE,SSID dev wifi") == 2


def test_connect_wifi_times_out_when_never_associated():
    exec_ch = FakeExec(responses=["", "no:HomeNet\n"])
    client, _, _ = make_client(exec_ch)

    with pytest.raises(AssertionError, match="wifi associated with 'TollGate-VM'"):
        client.connect_wifi("TollGate-VM", timeout_s=0.2)


def test_status_returns_cashud_json_with_balance():
    status = {"ok": True, "balance_sats": 21, "session": None}
    exec_ch = FakeExec(responses=[json.dumps(status)])
    client, _, _ = make_client(exec_ch)

    assert client.status()["balance_sats"] == 21
    assert "/status" in exec_ch.commands[0]


def test_status_raises_on_non_json_answer():
    exec_ch = FakeExec(responses=["gateway html junk"])
    client, _, _ = make_client(exec_ch)

    with pytest.raises(RuntimeError, match="non-JSON"):
        client.status()


def test_inject_token_posts_receive_and_requires_ok():
    exec_ch = FakeExec(responses=['{"ok": true, "received_sats": 21}'])
    client, _, _ = make_client(exec_ch)

    client.inject_token("cashuTOKEN")

    assert "/receive" in exec_ch.commands[0] and "cashuTOKEN" in exec_ch.commands[0]
    exec_ch.responses = ['{"ok": false, "error": "spent"}']
    with pytest.raises(RuntimeError, match="refused token"):
        client.inject_token("cashuTOKEN")


def test_run_command_rides_the_channel_with_timeout():
    exec_ch = FakeExec(responses=["pong"])
    client, _, _ = make_client(exec_ch)

    assert client.run_command("ping -c1 gateway", timeout_s=7) == "pong"
    assert exec_ch.commands == ["ping -c1 gateway"]
    assert exec_ch.timeouts == [7.0]


def test_open_wallet_ux_runs_plugin_ipc_and_waits_for_panel():
    exec_ch = FakeExec()
    vision = FakeVision({"panel-open.png": Match(960, 20, 0.99)})
    client, _, _ = make_client(exec_ch, vision=vision)

    client.open_wallet_ux()

    assert any("omarchy-shell user.cashu open" in c for c in exec_ch.commands)
    assert any("bash -lc" in c for c in exec_ch.commands), "IPC needs the login-shell profile"
    assert vision.asked == ["panel-open.png"]


def test_click_template_reopens_panel_before_clicking():
    """The 7ed5bdd regression: never click a possibly-hidden panel."""
    exec_ch = FakeExec()
    vision = FakeVision(
        {
            "panel-open.png": Match(960, 20, 0.99),
            "btn-pay-tollgate.png": Match(1500, 700, 0.97),
        }
    )
    click = FakeClick()
    client, _, _ = make_client(exec_ch, vision=vision, click=click)

    assert client.click_template("btn-pay-tollgate.png") == (1500, 700)

    ipc_index = next(i for i, c in enumerate(exec_ch.commands) if "user.cashu open" in c)
    match_index = vision.asked.index("btn-pay-tollgate.png")
    assert ipc_index < len(exec_ch.commands)
    assert vision.asked[: match_index + 1] == ["panel-open.png", "btn-pay-tollgate.png"], (
        "panel must be re-opened and confirmed before the target match"
    )
    assert click.points == [(1500, 700)]


# ---- UxButtonActor ----


def ux_with_status_script(statuses: list[str]) -> OmarchyUxClient:
    """Client whose panel AND pay-button templates match, with scripted /status."""
    exec_ch = FakeExec()
    vision = FakeVision(
        {
            "panel-open.png": Match(960, 20, 0.99),
            "btn-pay-tollgate.png": Match(1500, 700, 0.97),
        }
    )
    client, _, _ = make_client(exec_ch, vision=vision)
    exec_ch.responses.extend(statuses)
    return client


def test_actor_pay_clicks_then_awaits_live_session():
    session = {"session": {"remaining": 24000, "cost_sats": 1}}
    client = ux_with_status_script(
        [
            json.dumps({"ok": True, "balance_sats": 21, "session": None}),
            json.dumps({"ok": True, **session}),
        ]
    )
    actor = UxButtonActor(session_timeout_s=5, poll_interval_s=0.05)

    receipt = actor.pay(client, FakeGateway())

    assert (receipt.sats, receipt.strategy) == (1, "ux_button")


def test_actor_pay_times_out_when_no_session_appears():
    client = ux_with_status_script([json.dumps({"ok": True, "session": None})])
    actor = UxButtonActor(session_timeout_s=0.2, poll_interval_s=0.05)

    with pytest.raises(AssertionError, match="wallet session live"):
        actor.pay(client, FakeGateway())


def test_actor_pay_rejects_clients_without_click_support():
    actor = UxButtonActor()
    with pytest.raises(TypeError, match="click_template"):
        actor.pay(FakeClient(), FakeGateway())


def test_actor_pay_requires_positive_cost_sats():
    resumed = {"ok": True, "session": {"remaining": 24000, "cost_sats": 0}}
    client = ux_with_status_script([json.dumps(resumed)])
    actor = UxButtonActor(session_timeout_s=5, poll_interval_s=0.05)

    with pytest.raises(RuntimeError, match="cost_sats"):
        actor.pay(client, FakeGateway())


# ---- VirtualPointer teardown discipline (pywayland postmortem) ----


class FakeProxy:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.calls: list[str] = []

    def motion_absolute(self, time_ms: int, x: int, y: int, w: int, h: int) -> None:
        self.calls.append(f"motion:{x},{y}")

    def button(self, time_ms: int, button: int, state: int) -> None:
        self.calls.append(f"button:{button}:{state}")

    def frame(self) -> None:
        self.calls.append("frame")


class FakeSession:
    """Fake PointerSession recording the destroy order."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.pointer = FakeProxy("pointer", self.events)

    def flush(self) -> None:
        self.events.append("flush")

    def destroy_pointer(self) -> None:
        self.events.append("destroy:pointer")

    def destroy_manager(self) -> None:
        self.events.append("destroy:manager")

    def destroy_registry(self) -> None:
        self.events.append("destroy:registry")

    def disconnect_display(self) -> None:
        self.events.append("display:disconnect")


def destroys(events: list[str]) -> list[str]:
    return [e for e in events if e.startswith(("destroy:", "display:"))]


def test_pointer_close_destroys_in_creation_order_exactly_once():
    session = FakeSession()
    pointer = VirtualPointer(session_factory=lambda: session)
    pointer.click_at(100, 200, 1920, 1080)

    pointer.close()
    pointer.close()  # idempotent: the double-destroy guard

    assert destroys(session.events) == [
        "destroy:pointer",
        "destroy:manager",
        "destroy:registry",
        "display:disconnect",
    ]


def test_pointer_del_without_close_runs_the_same_teardown():
    session = FakeSession()
    pointer = VirtualPointer(session_factory=lambda: session)
    del pointer  # forgot-to-close path must not explode or double-destroy

    assert destroys(session.events) == [
        "destroy:pointer",
        "destroy:manager",
        "destroy:registry",
        "display:disconnect",
    ]


def test_pointer_backend_uses_a_fresh_closed_pointer_per_click():
    sessions: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession()
        sessions.append(session)
        return session

    class PointerClickBackend:
        def __init__(self, session_factory: SessionFactory) -> None:
            self._factory = session_factory

        def click_at(self, x: int, y: int) -> None:
            pointer = VirtualPointer(session_factory=self._factory)
            try:
                pointer.click_at(x, y, 1920, 1080)
            finally:
                pointer.close()

    backend = PointerClickBackend(factory)
    backend.click_at(10, 20)
    backend.click_at(30, 40)

    expected = [
        "destroy:pointer",
        "destroy:manager",
        "destroy:registry",
        "display:disconnect",
    ]
    assert len(sessions) == 2, "each click must own a fresh session (no shared connections)"
    assert sessions[0] is not sessions[1]
    assert [destroys(s.events) for s in sessions] == [expected, expected], (
        "every pointer must complete the full teardown after its click"
    )


def test_pointer_click_emits_move_press_release_frames():
    session = FakeSession()
    pointer = VirtualPointer(session_factory=lambda: session)

    pointer.click_at(100, 200, 1920, 1080)

    calls = session.pointer.calls
    assert calls[0] == "motion:100,200"
    assert "button:272:1" in calls and "button:272:0" in calls, "press then release"
    assert calls.count("frame") >= 3, "frame after motion, press, and release"


# ---- WfRecorderCapture ----


def fake_capture() -> tuple[WfRecorderCapture, FakeExec, list[list[str]]]:
    exec_ch = FakeExec(byte_responses=[b"PNGFRAME1" * 200, b"PNGFRAME2" * 200, b"MKVDATA" * 1000])
    ffmpeg_calls: list[list[str]] = []

    def local_run(argv: list[str]) -> None:
        ffmpeg_calls.append(argv)
        out = Path(argv[-1])
        out.write_bytes(b"WEBM")

    capture = WfRecorderCapture(exec_channel=exec_ch, local_run=local_run)
    return capture, exec_ch, ffmpeg_calls


def test_capture_requires_a_channel_at_start(tmp_path: Path):
    capture = WfRecorderCapture()
    with pytest.raises(ValueError, match="vssh"):
        capture.start(tmp_path)


def test_capture_start_kills_stale_recorder_and_launches(tmp_path: Path):
    capture, exec_ch, _ = fake_capture()

    capture.start(tmp_path)

    joined = "\n".join(exec_ch.commands)
    assert "pkill -INT wf-recorder" in joined
    assert "setsid nohup env WAYLAND_DISPLAY=wayland-1" in joined
    assert "wf-recorder --no-damage -f /tmp/story-raw.mkv" in joined


def test_capture_step_writes_frames_and_timeline(tmp_path: Path):
    capture, _, _ = fake_capture()
    capture.start(tmp_path)

    capture.step("gate_closed")
    capture.step("payment_made")

    frames = sorted((tmp_path / "frames").iterdir())
    assert [f.name for f in frames] == [
        "01_gate_closed.png",
        "02_payment_made.png",
    ]
    assert (frames[0].read_bytes()).startswith(b"PNGFRAME1")
    timeline = [json.loads(line) for line in (tmp_path / "timeline.jsonl").read_text().splitlines()]
    assert [e["name"] for e in timeline] == ["gate_closed", "payment_made"]
    assert [e["idx"] for e in timeline] == [1, 2]


def test_capture_stop_pulls_transcodes_and_cleans_raw(tmp_path: Path):
    capture, exec_ch, ffmpeg_calls = fake_capture()
    capture.start(tmp_path)
    capture.step("pay")

    result = capture.stop()

    assert result.video_path == tmp_path / "story.webm"
    assert result.video_path is not None and result.video_path.exists()
    assert result.frame_paths == (tmp_path / "frames" / "01_pay.png",)
    assert result.duration_s > 0
    assert not (tmp_path / "story-raw.mkv").exists(), "raw removed after transcode"
    assert ffmpeg_calls and ffmpeg_calls[0][0] == "ffmpeg"
    assert "libvpx" in ffmpeg_calls[0] and "-an" in ffmpeg_calls[0]
    assert any("pkill -INT wf-recorder" in c and "sleep 3" in c for c in exec_ch.commands)


def test_capture_stop_without_video_returns_frames_only(tmp_path: Path):
    exec_ch = FakeExec(byte_responses=[b"", b""])
    capture = WfRecorderCapture(
        exec_channel=exec_ch, local_run=lambda argv: pytest.fail("no ffmpeg expected")
    )
    capture.start(tmp_path)

    result = capture.stop()

    assert result.video_path is None
    assert not (tmp_path / "story-raw.mkv").exists()


def test_capture_step_before_start_is_an_error(tmp_path: Path):
    capture, _, _ = fake_capture()
    with pytest.raises(RuntimeError, match="before start"):
        capture.step("oops")


# ---- keep the no-subprocess guarantee honest ----


def test_no_real_subprocess_in_fakes(monkeypatch: pytest.MonkeyPatch):
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("unit tests must not spawn real processes")

    monkeypatch.setattr(subprocess, "run", boom)
    exec_ch = FakeExec(responses=["yes:TollGate-VM\n"])
    client, _, _ = make_client(exec_ch)
    assert client.active_ssid() == "TollGate-VM"
