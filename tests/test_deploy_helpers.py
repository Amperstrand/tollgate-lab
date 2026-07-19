"""Tests for FIPS and TollGate deploy helpers."""

from tollgate_lab.deploy.fips import default_fips_config, FIPS_SERVICE_NAME
from tollgate_lab.deploy.tollgate import TOLLGATE_SERVICE, TOLLGATE_REPO


def test_default_fips_config():
    """Default FIPS config has expected keys."""
    config = default_fips_config()
    assert "node" in config
    assert "transports" in config
    assert "udp" in config["transports"]


def test_default_fips_config_tun_disabled():
    """TUN disabled by default."""
    config = default_fips_config()
    assert config["tun"]["enabled"] is False


def test_default_fips_config_dns_disabled():
    """DNS disabled by default."""
    config = default_fips_config()
    assert config["dns"]["enabled"] is False


def test_fips_service_name():
    assert FIPS_SERVICE_NAME == "fips"


def test_tollgate_service_name():
    assert TOLLGATE_SERVICE == "tollgate"


def test_tollgate_repo():
    assert "tollgate" in TOLLGATE_REPO.lower()
