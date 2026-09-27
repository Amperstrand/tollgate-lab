"""Tests for scenario profile loading + validation."""

from pathlib import Path

import pytest

from tollgate_lab.scenarios.profile import load_profile, profile_from_dict

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"

SHIPPED_PROFILES = [
    "omarchy-ux-mock",
    "omarchy-ux-real",
    "debian-container-real",
    "phone-adb-mt3000",
    "phone-cuttlefish",
]


def minimal_profile_dict() -> dict:
    return {
        "client": {"driver": "omarchy_ux", "vssh": "ssh -p 2222 omarchy@127.0.0.1"},
        "payment": {"actor": "ux_button"},
        "gateway": {"driver": "http_module", "base": "http://127.0.0.1:2121"},
    }


@pytest.mark.parametrize("name", SHIPPED_PROFILES)
def test_shipped_profiles_load(name: str):
    profile = load_profile(PROFILES_DIR / f"{name}.yaml")
    assert profile.name == name
    assert profile.client.driver
    assert profile.payment.actor
    assert profile.gateway.driver


def test_omarchy_ux_real_shape():
    profile = load_profile(PROFILES_DIR / "omarchy-ux-real.yaml")
    assert profile.client.driver == "omarchy_ux"
    assert profile.payment.actor == "ux_button"
    assert profile.gateway.driver == "http_module"
    assert profile.capture is not None and profile.capture.driver == "wf_recorder"
    assert profile.phases.renewal is True
    assert profile.phases.drain_and_fallback is True
    assert profile.phases.wallet_fresh == "funded"


def test_drained_profiles():
    debian = load_profile(PROFILES_DIR / "debian-container-real.yaml")
    phone = load_profile(PROFILES_DIR / "phone-adb-mt3000.yaml")
    assert debian.phases.wallet_fresh == "drained"
    assert phone.phases.wallet_fresh == "drained"


def test_unknown_client_driver_lists_known():
    data = minimal_profile_dict()
    data["client"]["driver"] = "bogus"
    with pytest.raises(ValueError, match=r"unknown client driver 'bogus' \(known: .*omarchy_ux"):
        profile_from_dict(data, name="t")


def test_unknown_actor_lists_known():
    data = minimal_profile_dict()
    data["payment"]["actor"] = "bogus"
    with pytest.raises(ValueError, match=r"unknown payment actor 'bogus' \(known: .*portal_tip03"):
        profile_from_dict(data, name="t")


def test_unknown_gateway_driver_lists_known():
    data = minimal_profile_dict()
    data["gateway"]["driver"] = "bogus"
    with pytest.raises(ValueError, match=r"unknown gateway driver 'bogus' \(known: http_module\)"):
        profile_from_dict(data, name="t")


def test_unknown_capture_driver_lists_known():
    data = minimal_profile_dict()
    data["capture"] = {"driver": "bogus"}
    with pytest.raises(ValueError, match=r"unknown capture driver 'bogus' \(known: .*wf_recorder"):
        profile_from_dict(data, name="t")


def test_missing_client_section():
    data = minimal_profile_dict()
    del data["client"]
    with pytest.raises(ValueError, match="missing required section 'client'"):
        profile_from_dict(data, name="t")


def test_phases_default_off_and_funded():
    profile = profile_from_dict(minimal_profile_dict(), name="t")
    assert profile.phases.renewal is False
    assert profile.phases.drain_and_fallback is False
    assert profile.phases.wallet_fresh == "funded"


def test_capture_optional():
    profile = profile_from_dict(minimal_profile_dict(), name="t")
    assert profile.capture is None


def test_step_gates_follow_flags():
    data = minimal_profile_dict()
    data["phases"] = {"renewal": True, "drain_and_fallback": True, "wallet_fresh": "drained"}
    profile = profile_from_dict(data, name="t")
    gates = profile.step_gates()
    assert gates == {
        "renewal_observed": True,
        "wallet_drained": True,
        "fallback_observed": True,
    }


def test_bad_wallet_fresh_value():
    data = minimal_profile_dict()
    data["phases"] = {"wallet_fresh": "sparkling"}
    with pytest.raises(ValueError, match=r"wallet_fresh must be one of \['drained', 'funded'\]"):
        profile_from_dict(data, name="t")


def test_unknown_phase_flag_rejected():
    data = minimal_profile_dict()
    data["phases"] = {"renewal": True, "renewl": True}
    with pytest.raises(ValueError, match=r"unknown phase flag\(s\) \['renewl'\]"):
        profile_from_dict(data, name="t")


def test_unknown_top_level_key_rejected():
    data = minimal_profile_dict()
    data["extra"] = {}
    with pytest.raises(ValueError, match="unknown profile key"):
        profile_from_dict(data, name="t")


def test_payment_sats_validated():
    data = minimal_profile_dict()
    data["payment"]["sats"] = 0
    with pytest.raises(ValueError, match="payment.sats must be a positive int"):
        profile_from_dict(data, name="t")


def test_payment_sats_default_and_override():
    assert profile_from_dict(minimal_profile_dict(), name="t").payment.sats == 21
    data = minimal_profile_dict()
    data["payment"]["sats"] = 50
    assert profile_from_dict(data, name="t").payment.sats == 50


def test_invalid_yaml_reports_file(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("client: [unclosed", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid YAML"):
        load_profile(bad)


def test_non_mapping_profile_rejected(tmp_path: Path):
    flat = tmp_path / "flat.yaml"
    flat.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_profile(flat)
