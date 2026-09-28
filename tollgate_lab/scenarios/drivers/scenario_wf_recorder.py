"""wf-recorder capture driver — the story-runner recording pipeline.

Port of vm-testbed's recording flow (story-runner.sh + vm.py): the
recorder lives INSIDE the guest, writing to the guest's /tmp; frames are
grim screencopies pulled back byte-clean as timeline markers; stop INTs
the recorder, pulls the raw mkv, and transcodes to webm (libvpx, 1M, no
audio) — the raw file is removed after a successful transcode.

``split_screen`` marks the run for the DEMO.sh composite pipeline (client
+ gateway side by side); the composite render itself lands with the rig
pipeline — this driver records the client side and writes the
``timeline.jsonl`` that aligns steps to it.

Unit tests drive the exec/local-run seams with fakes — no guest, no
ffmpeg.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from tollgate_lab.scenarios.contract import CaptureResult
from tollgate_lab.scenarios.drivers.ux_channel import (
    DEFAULT_GUEST_ENV,
    ExecChannel,
    SshExec,
    grim_pull_command,
)

__all__ = ["WfRecorderCapture"]

log = logging.getLogger(__name__)

_LOCAL_RUN_TIMEOUT_S = 600.0
_RECORDER_INT_SETTLE_S = 3

LocalRun = Callable[[list[str]], None]


class WfRecorderCapture:
    """CaptureDriver over the VM's wf-recorder, story-runner style."""

    def __init__(
        self,
        *,
        split_screen: bool = False,
        vssh: str | None = None,
        guest_env: str = DEFAULT_GUEST_ENV,
        raw_remote_path: str = "/tmp/story-raw.mkv",
        video_name: str = "story.webm",
        exec_channel: ExecChannel | None = None,
        local_run: LocalRun | None = None,
    ) -> None:
        self._split_screen = split_screen
        self._vssh = vssh
        self._guest_env = guest_env
        self._raw_remote = raw_remote_path
        self._video_name = video_name
        self._exec = exec_channel
        self._local_run = local_run if local_run is not None else _subprocess_local_run
        self._artifact_dir: Path | None = None
        self._frames: list[Path] = []
        self._started: float | None = None

    def start(self, artifact_dir: Path) -> None:
        """Kill stale recorders, then launch wf-recorder inside the VM."""
        self._channel()  # fail fast on a missing channel before any state
        self._artifact_dir = Path(artifact_dir)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        (self._artifact_dir / "frames").mkdir(exist_ok=True)
        self._timeline_path().write_text("", encoding="utf-8")
        self._frames = []
        self._channel().run(
            f"pkill -INT wf-recorder 2>/dev/null; sleep 1; "
            f"setsid nohup env {self._guest_env} wf-recorder --no-damage "
            f"-f {self._raw_remote} >/tmp/wf-recorder.log 2>&1 < /dev/null &"
        )
        if self._split_screen:
            log.info(
                "split_screen run: composite rendering lands with the rig DEMO pipeline; "
                "timeline.jsonl is written to align steps to it"
            )
        self._started = time.monotonic()

    def step(self, name: str) -> None:
        """Grab ``frames/<idx>_<name>.png`` as the timeline marker."""
        if self._artifact_dir is None or self._started is None:
            raise RuntimeError("capture step before start()")
        idx = len(self._frames) + 1
        frame = self._artifact_dir / "frames" / f"{idx:02d}_{name}.png"
        frame.write_bytes(self._channel().run_bytes(grim_pull_command(self._guest_env)))
        self._frames.append(frame)
        with self._timeline_path().open("a", encoding="utf-8") as timeline:
            timeline.write(
                json.dumps(
                    {"idx": idx, "name": name, "t_s": round(time.monotonic() - self._started, 3)}
                )
                + "\n"
            )

    def stop(self) -> CaptureResult:
        """INT the recorder, pull the mkv, transcode to story.webm."""
        if self._artifact_dir is None or self._started is None:
            raise RuntimeError("capture stop before start()")
        duration_s = time.monotonic() - self._started
        self._channel().run(f"pkill -INT wf-recorder 2>/dev/null; sleep {_RECORDER_INT_SETTLE_S}")
        raw = self._artifact_dir / Path(self._raw_remote).name
        raw.write_bytes(self._channel().run_bytes(f"cat {self._raw_remote} 2>/dev/null"))
        video_path: Path | None = None
        if raw.stat().st_size == 0:
            log.warning("recorder produced no raw video; returning frames only")
            raw.unlink(missing_ok=True)
        else:
            video_path = self._artifact_dir / self._video_name
            self._local_run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(raw),
                    "-c:v",
                    "libvpx",
                    "-b:v",
                    "1M",
                    "-an",
                    str(video_path),
                ]
            )
            raw.unlink()
        self._started = None
        return CaptureResult(
            video_path=video_path,
            frame_paths=tuple(self._frames),
            duration_s=duration_s,
        )

    def _timeline_path(self) -> Path:
        assert self._artifact_dir is not None
        return self._artifact_dir / "timeline.jsonl"

    def _channel(self) -> ExecChannel:
        if self._exec is None:
            if self._vssh is None:
                raise ValueError(
                    "wf_recorder capture needs the client's vssh channel — "
                    "add 'vssh: <client ssh prefix>' to the capture profile section "
                    "(or inject exec_channel)"
                )
            self._exec = SshExec(self._vssh)
        return self._exec


def _subprocess_local_run(argv: list[str]) -> None:
    proc = subprocess.run(argv, capture_output=True, timeout=_LOCAL_RUN_TIMEOUT_S, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode(errors="replace")[-500:]
        raise RuntimeError(f"{argv[0]} failed (rc={proc.returncode}): {stderr}")
