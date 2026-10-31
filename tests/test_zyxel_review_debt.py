"""Regression tests for the PR #6/#7 review-debt wave (issues #17-#24).

Offline only: fake openers stand in for dispatcher.cgi; the real switch
is exercised by the HIL suite, not here.
"""

import http.cookiejar
import types
import urllib.request

import pytest


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
    assert zyxel_stock.complete_password_gate("192.168.13.3", "1234", "new-secret-pw") is True


def test_other_fault_classifies_as_off():
    """#24: "Other fault" is a faulted port — an enable verified against it
    reported success; both OFF_STATES call sites (_verify, get) key off it."""
    from tollgate_lab.drivers.zyxel_poe import OFF_STATES, PoeStatus

    assert PoeStatus.OTHER_FAULT.value.lower() in OFF_STATES


def test_protected_port_guard_normalizes_spelling():
    """#18: port "1" bypassed the raw-spelling p1 guard."""
    for spelling in ("p1", "1", "P1", " p1 "):
        assert StockZyxelPoePort(host="h", port=spelling).is_protected, spelling
    assert not StockZyxelPoePort(host="h", port="p5").is_protected


def test_port_no_accepts_both_spellings():
    assert StockZyxelPoePort(host="h", port="1").port_no == 1
    assert StockZyxelPoePort(host="h", port="p1").port_no == 1
