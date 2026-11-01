"""Regression tests for the PR #6/#7 review-debt wave (issues #17-#24).

Offline only: fake openers stand in for dispatcher.cgi; the real switch
is exercised by the HIL suite, not here.
"""

import http.cookiejar
import types
import urllib.request

import pytest

from tollgate_lab.drivers.stock_zyxel_poe import StockZyxelPoePort, _resolve_password


XSSID_PAGE = (
    '<html><form><input name="XSSID" value="CAFEBABE0123456789ABCDEF0123456789"></form></html>'
)
LOGIN_PAGE = '<html id="username">login_language</html>'


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return self._payload


class FakeOpener:
    def __init__(self, responder, log):
        self._responder = responder
        self.log = log

    def open(self, req, timeout=None):
        self.log.append(req)
        data = (req.data or b"").decode()
        return FakeResponse(self._responder(data, req.full_url).encode())


def patch_opener(monkeypatch, responder, log):
    monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: FakeOpener(responder, log))


def bare_web(monkeypatch, responder, log, xssid="OLDXSSID"):
    """A StockWeb built the way complete_password_gate builds one: no
    __init__, only the attrs a request cycle needs."""
    from tollgate_lab.hardware.zyxel_stock import StockWeb

    patch_opener(monkeypatch, responder, log)
    w = StockWeb.__new__(StockWeb)
    w.base = "http://192.168.13.3/cgi-bin/dispatcher.cgi"
    w.user, w.host = "admin", "192.168.13.3"
    w._in_login = False
    w._password = "bench-pw"
    w.xssid = xssid
    w.jar = http.cookiejar.CookieJar()
    w.opener = FakeOpener(responder, log)
    return w


def test_complete_password_gate_survives_virgin_session(monkeypatch):
    """#17: w.get(30) hit `not self._in_login` AttributeError before the
    gate form was ever fetched."""
    from tollgate_lab.hardware import zyxel_stock

    def responder(data, url):
        if "login=true;" in data:
            return "F00DCAFE"
        if "login_chk=true" in data:
            return "OK"
        if "cmd=31" in data:
            return "<html>applied</html>"
        if data == "" and (url.endswith("cmd=30") or url.endswith("cmd=1")):
            return XSSID_PAGE
        return "<html>?</html>"

    log = []
    patch_opener(monkeypatch, responder, log)
    assert zyxel_stock.complete_password_gate("192.168.13.3", "1234", "new-secret-pw") is True


def test_other_fault_classifies_as_off():
    """#24: "Other fault" is a faulted port — an enable verified against it
    reported success; both OFF_STATES call sites (_verify, get) key off it."""
    from tollgate_lab.drivers.zyxel_poe import OFF_STATES, PoeStatus

    assert PoeStatus.OTHER_FAULT.value.lower() in OFF_STATES


def test_protected_port_guard_normalizes_spelling():
    """#18: port "1" bypassed the raw-spelling p1 guard."""
    for spelling in ("p1", "1", "P1", " p1 "):
        assert StockZyxelPoePort(target=None, name=spelling, host="h", port=spelling).is_protected, spelling
    assert not StockZyxelPoePort(target=None, name="p5", host="h", port="p5").is_protected


def test_port_no_accepts_both_spellings():
    assert StockZyxelPoePort(target=None, name="1", host="h", port="1").port_no == 1
    assert StockZyxelPoePort(target=None, name="p1", host="h", port="p1").port_no == 1


def test_password_override_rejects_sops_ciphertext(monkeypatch):
    """#21: an ENC[...] (or overlong) override must fail loudly, not
    authenticate with ciphertext (AGENTS.md secrets rule)."""
    monkeypatch.setenv("STOCK_ZYXEL_PASSWORD", "ENC[AES256_GCM:data:key]")
    with pytest.raises(Exception, match="ciphertext"):
        _resolve_password()
    monkeypatch.delenv("STOCK_ZYXEL_PASSWORD")
    monkeypatch.setenv("BENCH_ROOT_PW", "x" * 41)
    with pytest.raises(Exception, match="ciphertext"):
        _resolve_password()


def test_password_override_accepts_real_password(monkeypatch):
    monkeypatch.setenv("STOCK_ZYXEL_PASSWORD", "bench-pw-1234")
    assert _resolve_password() == "bench-pw-1234"


def test_sops_decrypt_extracts_only_the_needed_field(monkeypatch):
    """#22: bare `sops -d` materialized every secret in subprocess stdout."""
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return types.SimpleNamespace(stdout='"bench-root-pw-1234"\n', stderr="", returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.delenv("STOCK_ZYXEL_PASSWORD", raising=False)
    monkeypatch.delenv("BENCH_ROOT_PW", raising=False)
    assert _resolve_password() == "bench-root-pw-1234"
    assert calls[0][:4] == ["sops", "-d", "--extract", '["fleet"]["bench_root_password"]']


def test_post_cmd_retry_rebuilds_body_with_fresh_xssid(monkeypatch):
    """#19: the eviction retry must regenerate the POST — the original
    Request's body carries the stale token (urllib data is immutable)."""

    def responder(data, url):
        if "login=true;" in data:
            return "F00DCAFE"
        if "login_chk=true" in data:
            return "OK"
        if "XSSID=OLDXSSID" in data:
            return LOGIN_PAGE
        if data == "":
            return XSSID_PAGE
        return "<html>applied</html>"

    log = []
    w = bare_web(monkeypatch, responder, log)
    body = w.post_cmd(775, {"portlist": "5", "state": "0"})
    assert "applied" in body
    posts = [r for r in log if r.data and b"cmd=775" in r.data]
    assert len(posts) == 2
    assert b"XSSID=OLDXSSID" in posts[0].data
    assert b"XSSID=OLDXSSID" not in posts[1].data


def test_disable_requires_admin_state_not_just_zero_watts(monkeypatch):
    """#20: a dropped cmd=775 leaves the row Enable/0 mW — that must time
    out as UNVERIFIED, not return the Enable row as a successful off."""

    import tollgate_lab.hardware.zyxel_stock as zyxel_stock_module

    monkeypatch.setattr(zyxel_stock_module, "POE_VERIFY_TIMEOUT_S", 0.3)
    row = {
        "state": "Enable",
        "class": "Class 4",
        "priority": "Low",
        "powerup": "802.3at",
        "mw": 0,
    }
    w = bare_web(monkeypatch, lambda data, url: "<html>ok</html>", [])
    w.poe_status = lambda: {5: dict(row)}
    with pytest.raises(RuntimeError, match="unverified"):
        w.set_poe_state(5, enabled=False)


def test_enable_still_verifies_on_watts(monkeypatch):
    row = {
        "state": "Enable",
        "class": "Class 4",
        "priority": "Low",
        "powerup": "802.3at",
        "mw": 6,
    }
    w = bare_web(monkeypatch, lambda data, url: "<html>ok</html>", [])
    w.poe_status = lambda: {5: dict(row)}
    assert w.set_poe_state(5, enabled=True)["mw"] == 6
