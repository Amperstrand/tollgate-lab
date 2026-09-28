"""Evidence contract: result.json + timeline.jsonl.

`result.json` keeps today's vm-testbed story schema (story-runner.sh):
story / timestamp / passed / failed / frames / steps — one PASS/FAIL line per
step — plus a `skipped` counter for post-failure truncation.

`timeline.jsonl` is new: one JSON event per step (name, ts, duration_s,
status, artifact hints) so test-films can align the capture video with every
step — a human must be able to watch the video and follow the run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import Literal

StepStatus = Literal["PASS", "FAIL", "SKIP"]

_STAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_STAMP_PATTERN = re.compile(r"^\d{8}T\d{6}Z$")

__all__ = [
    "EvidencePaths",
    "LifecycleResult",
    "StepRecord",
    "StepStatus",
    "write_evidence",
]


@dataclass(frozen=True)
class StepRecord:
    """One lifecycle step's outcome — doubles as the timeline event."""

    name: str
    status: StepStatus
    ts: str = ""  # ISO-8601 UTC, set by the lifecycle runner
    duration_s: float = 0.0
    error: str | None = None
    artifacts: tuple[str, ...] = ()  # paths relative to the artifact dir
    detail: str | None = None


@dataclass(frozen=True)
class LifecycleResult:
    """A whole scenario run: per-step records + derived counters."""

    story: str
    steps: tuple[StepRecord, ...]

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.status == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if s.status == "FAIL")

    @property
    def skipped(self) -> int:
        return sum(1 for s in self.steps if s.status == "SKIP")

    @property
    def ok(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True)
class EvidencePaths:
    result_json: Path
    timeline_jsonl: Path


def step_line(record: StepRecord) -> str:
    """One vm-testbed-style `name: PASS` / `name: FAIL (reason)` line."""
    if record.status == "FAIL" and record.error:
        return f"{record.name}: FAIL ({record.error})"
    return f"{record.name}: {record.status}"


def write_evidence(
    artifact_dir: Path,
    *,
    story: str,
    steps: tuple[StepRecord, ...] | list[StepRecord],
    timestamp: str | None = None,
) -> EvidencePaths:
    """Write result.json + timeline.jsonl into artifact_dir; return paths."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = timestamp if _is_stamp(timestamp) else _utc_stamp()
    records = tuple(steps)

    result_json = artifact_dir / "result.json"
    result_json.write_text(
        json.dumps(
            {
                "story": story,
                "timestamp": stamp,
                "passed": sum(1 for s in records if s.status == "PASS"),
                "failed": sum(1 for s in records if s.status == "FAIL"),
                "skipped": sum(1 for s in records if s.status == "SKIP"),
                "frames": [a for s in records for a in s.artifacts if a.lower().endswith(".png")],
                "steps": "\n".join(step_line(s) for s in records),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    timeline_path = artifact_dir / "timeline.jsonl"
    lines = [
        json.dumps(
            {
                "name": s.name,
                "ts": s.ts,
                "duration_s": round(s.duration_s, 3),
                "status": s.status,
                "artifacts": list(s.artifacts),
                "detail": s.detail,
                "error": s.error,
            }
        )
        for s in records
    ]
    timeline_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    return EvidencePaths(result_json=result_json, timeline_jsonl=timeline_path)


def _utc_stamp() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime(_STAMP_FORMAT)


def _is_stamp(value: str | None) -> bool:
    return value is not None and bool(_STAMP_PATTERN.match(value))
