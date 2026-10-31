"""Tests for the scenario evidence output schema."""

import json
import re
from datetime import datetime
from pathlib import Path

from tollgate_lab.scenarios.evidence import LifecycleResult, StepRecord, write_evidence


def sample_steps() -> list[StepRecord]:
    return [
        StepRecord(
            name="rig_up",
            status="PASS",
            ts="2026-09-27T12:00:00.000000+00:00",
            duration_s=0.5,
            artifacts=("frames/1_rig_up.png",),
        ),
        StepRecord(
            name="payment_made",
            status="PASS",
            ts="2026-09-27T12:00:05.000000+00:00",
            duration_s=2.25,
            artifacts=("frames/6_payment_made.png", "story.webm"),
        ),
        StepRecord(
            name="fallback_observed",
            status="FAIL",
            ts="2026-09-27T12:01:00.000000+00:00",
            duration_s=1.0,
            error="StepFailureError: client still on 'TollGate-Test'",
        ),
        StepRecord(name="evidence_written", status="SKIP", ts="2026-09-27T12:01:01+00:00"),
    ]


def test_result_json_matches_vm_testbed_shape(tmp_path: Path):
    paths = write_evidence(tmp_path, story="s5-tollgate", steps=sample_steps())

    payload = json.loads(paths.result_json.read_text(encoding="utf-8"))
    assert set(payload) >= {"story", "timestamp", "passed", "failed", "frames", "steps"}
    assert payload["story"] == "s5-tollgate"
    assert payload["passed"] == 2
    assert payload["failed"] == 1
    assert payload["skipped"] == 1
    assert payload["frames"] == ["frames/1_rig_up.png", "frames/6_payment_made.png"]
    lines = payload["steps"].splitlines()
    assert lines[0] == "rig_up: PASS"
    assert lines[2] == "fallback_observed: FAIL (StepFailureError: client still on 'TollGate-Test')"
    assert lines[3] == "evidence_written: SKIP"


def test_timestamp_is_vm_testbed_stamp(tmp_path: Path):
    paths = write_evidence(tmp_path, story="t", steps=sample_steps())

    payload = json.loads(paths.result_json.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{8}T\d{6}Z", payload["timestamp"])
    explicit = write_evidence(tmp_path, story="t", steps=[], timestamp="20260927T120000Z")
    assert json.loads(explicit.result_json.read_text(encoding="utf-8"))["timestamp"] == (
        "20260927T120000Z"
    )


def test_timeline_jsonl_one_event_per_step(tmp_path: Path):
    paths = write_evidence(tmp_path, story="s5-tollgate", steps=sample_steps())

    lines = paths.timeline_jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    events = [json.loads(line) for line in lines]
    assert [e["name"] for e in events] == [
        "rig_up",
        "payment_made",
        "fallback_observed",
        "evidence_written",
    ]
    for event in events:
        assert set(event) == {"name", "ts", "duration_s", "status", "artifacts", "detail", "error"}
        datetime.fromisoformat(event["ts"])
    assert events[0]["duration_s"] == 0.5
    assert events[1]["artifacts"] == ["frames/6_payment_made.png", "story.webm"]
    assert events[2]["status"] == "FAIL"
    assert events[2]["error"].startswith("StepFailureError:")


def test_empty_run_writes_empty_files(tmp_path: Path):
    paths = write_evidence(tmp_path, story="t", steps=[])

    payload = json.loads(paths.result_json.read_text(encoding="utf-8"))
    assert payload["passed"] == payload["failed"] == payload["skipped"] == 0
    assert payload["steps"] == ""
    assert paths.timeline_jsonl.read_text(encoding="utf-8") == ""


def test_lifecycle_result_counters():
    result = LifecycleResult(story="t", steps=tuple(sample_steps()))

    assert result.passed == 2
    assert result.failed == 1
    assert result.skipped == 1
    assert not result.ok

    clean = LifecycleResult(
        story="t",
        steps=tuple([StepRecord(name="rig_up", status="PASS")]),
    )
    assert clean.ok
