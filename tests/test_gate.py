"""Post-flash telemetry gate tests."""

from __future__ import annotations

import re

import pytest

from tollgate_lab.hardware.gate import FakeSource, TelemetryGateError, assert_telemetry

TOLLGATE_RE = re.compile(r"\[tollgate\] phase=(run|end) kw=")


def test_assert_telemetry_when_min_lines_matched() -> None:
    source = FakeSource([
        "[tollgate] phase=run kw=0.00 kwh=0.000 remaining=1799s",
        "[tollgate] phase=run kw=1.20 kwh=0.001 remaining=1794s",
    ])
    result = assert_telemetry(source, pattern=TOLLGATE_RE, min_lines=2, window_s=0)
    assert len(result.matched) == 2


def test_assert_telemetry_when_too_few_lines() -> None:
    source = FakeSource(["[tollgate] phase=run kw=0.00 kwh=0.000 remaining=1799s"])
    with pytest.raises(TelemetryGateError) as exc:
        assert_telemetry(source, pattern=TOLLGATE_RE, min_lines=2, window_s=0)
    assert exc.value.matched == 1


def test_assert_telemetry_when_silent() -> None:
    with pytest.raises(TelemetryGateError):
        assert_telemetry(FakeSource([]), pattern=TOLLGATE_RE, min_lines=1, window_s=0)
