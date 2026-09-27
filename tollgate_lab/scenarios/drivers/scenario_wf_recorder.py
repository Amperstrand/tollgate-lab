"""SPEC STUB — wf-recorder capture driver.

Port of vm-testbed story-runner.sh's recording pipeline; the body is a
NotImplementedError placeholder and this docstring is the porting spec.

Semantics to preserve:

- **start** — ``pkill -INT wf-recorder`` (clean any stale recording), then
  ``setsid nohup env WAYLAND_DISPLAY=wayland-1 XDG_RUNTIME_DIR=/run/user/1000
  wf-recorder --no-damage -f /tmp/story-raw.mkv`` over VSSH; the recorder
  lives inside the VM, writing to the VM's /tmp.
- **step** — timeline marker: grab a Wayland screencopy PNG named
  ``<idx>_<name>.png`` under the artifact dir's ``frames/`` (story-runner's
  ``frame`` helper) so vision review and test-films can follow each step.
- **stop** — ``pkill -INT wf-recorder``, ``cat /tmp/story-raw.mkv`` over
  VSSH into the artifact dir, then ffmpeg → ``story.webm`` (libvpx, 1M,
  no audio); raw mkv removed after transcode. Return a CaptureResult with
  the video path, frame paths, and wall-clock duration.
- **split_screen** — when true (DEMO.sh pipeline), additionally render the
  split-screen composite so a human can watch client + gateway side by
  side; timeline.jsonl aligns steps to it.
"""

from __future__ import annotations

from pathlib import Path

from tollgate_lab.scenarios.contract import CaptureResult

__all__ = ["WfRecorderCapture"]


class WfRecorderCapture:
    """CaptureDriver over the VM's wf-recorder, story-runner style."""

    def __init__(self, *, split_screen: bool = False) -> None:
        self._split_screen = split_screen

    def start(self, artifact_dir: Path) -> None:
        """Kill stale recorders, then launch wf-recorder inside the VM."""
        raise NotImplementedError("port story-runner wf-recorder launch over VSSH")

    def step(self, name: str) -> None:
        """Grab ``frames/<idx>_<name>.png`` as the timeline marker."""
        raise NotImplementedError("port story-runner frame() screencopy over VSSH")

    def stop(self) -> CaptureResult:
        """INT the recorder, pull the mkv, transcode to story.webm."""
        raise NotImplementedError("port story-runner recorder stop + ffmpeg webm pipeline")
