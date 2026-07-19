"""Tests for tollgate-lab cloud provisioning."""

import os
import pytest
from tollgate_lab.cloud.provider import VMConfig, VMInstance, get_provider, list_providers


def test_list_providers_always_has_qemu():
    providers = list_providers()
    assert "qemu" in providers


def test_get_qemu_provider():
    provider = get_provider("qemu")
    assert provider is not None


def test_shc_provider_requires_api_key():
    os.environ.pop("SHC_API_KEY", None)
    with pytest.raises(RuntimeError, match="SHC_API_KEY"):
        get_provider("shc")


def test_gcp_provider_requires_credentials():
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    with pytest.raises(RuntimeError, match="GOOGLE_APPLICATION_CREDENTIALS"):
        get_provider("gcp")


def test_auto_detect_qemu():
    os.environ.pop("SHC_API_KEY", None)
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    provider = get_provider()  # auto-detect
    assert type(provider).__name__ == "QEMUProvider"


def test_shc_auto_detected_with_key():
    os.environ["SHC_API_KEY"] = "test-key"
    try:
        provider = get_provider()
        assert type(provider).__name__ == "SHCProvider"
    finally:
        os.environ.pop("SHC_API_KEY", None)


def test_vm_config_defaults():
    config = VMConfig()
    assert config.name == "tollgate-lab-vm"
    assert config.disk_size_gb == 20


def test_vm_instance_is_running():
    vm = VMInstance(name="test", external_ip="1.2.3.4", internal_ip="10.0.0.1",
                     status="running", provider="qemu")
    assert vm.is_running


def test_vm_instance_not_running():
    vm = VMInstance(name="test", external_ip="1.2.3.4", internal_ip="10.0.0.1",
                     status="stopped", provider="qemu")
    assert not vm.is_running


def test_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider("aws")
