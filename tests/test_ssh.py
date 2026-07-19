"""Unit tests for SSH driver (mocked subprocess)."""

import subprocess
from unittest.mock import patch, MagicMock
from tollgate_lab.drivers.ssh import _ssh_run


@patch("subprocess.run")
def test_ssh_run_basic(mock_run):
    """SSH run executes and returns stdout."""
    mock_run.return_value = MagicMock(stdout="hello\n", stderr="", returncode=0)
    result = _ssh_run("test-host", "echo hello")
    assert "hello" in result
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_ssh_run_timeout(mock_run):
    """SSH run propagates timeout."""
    mock_run.side_effect = subprocess.TimeoutExpired("ssh", 30)
    try:
        _ssh_run("test-host", "sleep 999", timeout=5)
        assert False, "Should have raised"
    except subprocess.TimeoutExpired:
        pass


@patch("subprocess.run")
def test_ssh_run_with_stdin(mock_run):
    """SSH run passes stdin data."""
    mock_run.return_value = MagicMock(stdout="ok", stderr="", returncode=0)
    _ssh_run("test-host", "cat", stdin_data=b"test data")
    call_kwargs = mock_run.call_args[1]
    assert call_kwargs.get("input") == b"test data"
