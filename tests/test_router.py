"""Unit tests for Router driver (mocked subprocess)."""

import subprocess
from unittest.mock import patch, MagicMock
from tollgate_lab.drivers.router import Router, BackendConfig


def test_backend_config_defaults():
    """BackendConfig has correct defaults."""
    config = BackendConfig()
    assert config.name == "go"
    assert config.port == 8080
    assert config.service_name == "tollgate"


def test_backend_config_custom():
    """BackendConfig accepts custom values."""
    config = BackendConfig(name="rust", port=9090)
    assert config.name == "rust"
    assert config.port == 9090


@patch("subprocess.run")
def test_router_ssh_command(mock_run):
    """Router.ssh executes SSH command."""
    mock_run.return_value = MagicMock(stdout="ok\n", stderr="", returncode=0)

    router = Router(host="192.168.1.1", phone_ip="10.0.0.2",
                     phone_mac="aa:bb:cc:dd:ee:ff", domain="test.local")
    result = router.ssh("echo ok")

    assert "ok" in result
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_router_backend_url(mock_run):
    """Router constructs correct backend URL."""
    mock_run.return_value = MagicMock(stdout="{}", stderr="", returncode=0)

    router = Router(host="192.168.1.1", phone_ip="10.0.0.2",
                     phone_mac="aa:bb:cc:dd:ee:ff", domain="test.local")
    url = router.backend_url("/api/status")
    assert "8080" in str(url) or "/api/status" in str(url)


@patch("subprocess.run")
def test_router_router_fetch(mock_run):
    """Router.router_fetch executes curl on router."""
    mock_run.return_value = MagicMock(stdout='{"status":"ok"}', stderr="", returncode=0)

    router = Router(host="192.168.1.1", phone_ip="10.0.0.2",
                     phone_mac="aa:bb:cc:dd:ee:ff", domain="test.local")
    result = router.router_fetch("http://localhost:8080/status")
    assert "ok" in result
