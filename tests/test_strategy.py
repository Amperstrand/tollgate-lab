"""Tests for OpenWrtStrategy."""

from labgrid import target_factory
from tollgate_lab.strategy.openwrt import OpenWrtStrategy, OpenWrtState


def test_strategy_registered():
    """OpenWrtStrategy is registered with labgrid."""
    assert "OpenWrtStrategy" in target_factory.drivers


def test_state_enum():
    """OpenWrtState has expected states."""
    assert OpenWrtState.unknown.value == 0
    assert OpenWrtState.boot.value == 1
    assert OpenWrtState.shell.value == 2
    assert OpenWrtState.service_running.value == 3
    assert OpenWrtState.test_ready.value == 4


def test_state_from_string():
    """Can get state by name."""
    state = OpenWrtState["shell"]
    assert state is OpenWrtState.shell
