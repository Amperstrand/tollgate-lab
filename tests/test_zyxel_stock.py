import urllib.request

import pytest


class _Resp:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


class _Opener:
    """Routes urllib traffic through a scripted handler object."""

    def __init__(self, router):
        self.router = router

    def open(self, req, timeout=None):
        return _Resp(self.router.open(req, timeout=timeout))


class TestRecoveryTooling:
    """2026-09-25 incident: unverified save -> factory revert -> this tooling."""

    def test_password_ladder_returns_working(self, monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        attempts = []

        class FakeWeb:
            def __init__(self, host, pw):
                attempts.append(pw)
                if pw != "right":
                    raise RuntimeError("login failed")

        monkeypatch.setattr(zs, "StockWeb", FakeWeb)
        assert zs.password_ladder("h", ["wrong", "right", "also"]) == "right"
        assert attempts == ["wrong", "right"]

    def test_password_ladder_all_fail(self, monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        class FakeWeb:
            def __init__(self, host, pw):
                raise RuntimeError("nope")

        monkeypatch.setattr(zs, "StockWeb", FakeWeb)
        assert zs.password_ladder("h", ["a", "b"]) is None

    def test_save_config_posts_exact_radio_pair(self, monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        web = zs.StockWeb.__new__(zs.StockWeb)
        web.base = "http://x/cgi-bin/dispatcher.cgi"
        posts = []

        class FakeResp:
            def read(self):
                return b"Configuration saved!"

        class FakeOpener:
            def open(self, req, timeout=None):
                posts.append(req.data.decode())
                return FakeResp()

        web.opener = FakeOpener()
        web.get = lambda cmd: 'name="XSSID" value="DEADBEEF"' if cmd == 5898 else ""
        assert web.save_config() is True
        body = posts[0]
        assert "srcFile=1" in body and "dstFile=2" in body
        assert body.count("srcFile") == 1  # exactly one radio value — the no-op trap
        assert "cmd=5899" in body

    def test_set_static_ip_uses_mode_zero(self, monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        web = zs.StockWeb.__new__(zs.StockWeb)
        web.base = "http://x/cgi-bin/dispatcher.cgi"
        posts = []

        class FakeResp:
            def read(self):
                return b""

        class FakeOpener:
            def open(self, req, timeout=None):
                posts.append(req.data.decode())
                return FakeResp()

        web.opener = FakeOpener()
        web.get = lambda cmd: 'name="XSSID" value="CAFEBABE"' if cmd == 516 else ""
        web.set_static_ip("192.168.13.3")
        body = posts[0]
        assert "mode=0" in body  # static — mode is inverted from intuition
        assert "ip=192.168.13.3" in body and "cmd=517" in body


class TestPasswordGate:
    """#17: the __new__-built gate session must carry the attrs _fetch()
    requires (_in_login, _password) — w.get(30) crashed with AttributeError
    before any gate form was processed."""

    def test_complete_password_gate_fetches_gate_page(self, monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        seen = {"gate_post": False}

        class Router:
            def open(self, req, timeout=None):
                data = req.data.decode() if req.data else ""
                url = getattr(req, "full_url", "")
                if "login=true" in data:
                    return "A1B2C3"  # authId nonce (must be fullmatch hex)
                if "login_chk" in data:
                    return "OK"
                if "cmd=31" in data:
                    seen["gate_post"] = True
                    return "applied"
                if url.endswith("cmd=30"):
                    return '<input name="XSSID" value="6A7E77">'
                if url.endswith("cmd=1"):
                    return '<input name="XSSID" value="B0C41">'
                raise AssertionError(f"unexpected request {url!r} {data!r}")

        router = Router()
        monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Opener(router))
        assert zs.complete_password_gate("h", "old", "new") is True
        assert seen["gate_post"] is True


class TestEvictionRetry:
    """#19: after an eviction the retry must REBUILD the POST body with the
    refreshed XSSID — resubmitting the original serialized Request can never
    apply the write."""

    def test_retry_reposts_with_refreshed_xssid(self, monkeypatch):
        import http.cookiejar

        import tollgate_lab.hardware.zyxel_stock as zs

        writes = []

        class Router:
            def open(self, req, timeout=None):
                data = req.data.decode() if req.data else ""
                url = getattr(req, "full_url", "")
                if "login=true" in data:
                    return "A1B2C3"
                if "login_chk" in data:
                    return "OK"
                if url.endswith("cmd=1"):
                    return '<input name="XSSID" value="D1E2F3">'
                if "XSSID=" in data:
                    writes.append(data)
                    if "XSSID=D1E2F3" in data:
                        return "applied-page"
                    return '<input id="username">'  # evicted shape
                raise AssertionError(f"unexpected request {url!r} {data!r}")

        router = Router()
        monkeypatch.setattr(urllib.request, "build_opener", lambda *a, **k: _Opener(router))
        w = zs.StockWeb.__new__(zs.StockWeb)
        w.base = "http://x/cgi-bin/dispatcher.cgi"
        w.user, w.host = "admin", "x"
        w._password = "pw"
        w._in_login = False
        w.xssid = "STALE01"
        w.jar = http.cookiejar.CookieJar()
        w.opener = _Opener(router)
        assert w.post_cmd(775, {"portlist": "5", "state": "0"}) == "applied-page"
        assert "XSSID=D1E2F3" in writes[-1]


class TestDisableVerification:
    """#20: a disable must verify the admin-state transition — a 0 mW row
    whose state is still Enable is NOT a verified disable (cmd=775 can be
    dropped while the port sits at zero power)."""

    ROW = {
        5: {"state": "Enable", "class": "class0", "priority": "Low", "powerup": "802.3at", "mw": 0}
    }

    @staticmethod
    def _web(rows, apply_cmd=None):
        import tollgate_lab.hardware.zyxel_stock as zs

        w = zs.StockWeb.__new__(zs.StockWeb)
        w.poe_status = lambda: {k: dict(v) for k, v in rows.items()}

        def _post(cmd, fields):
            if apply_cmd:
                apply_cmd(rows)

        w.post_cmd = _post
        return w

    @staticmethod
    def _fast_clock(monkeypatch):
        import tollgate_lab.hardware.zyxel_stock as zs

        now = [1000.0]
        monkeypatch.setattr(zs.time, "monotonic", lambda: now[0])

        def advance(s):
            now[0] += s

        monkeypatch.setattr(zs.time, "sleep", advance)

    def test_disable_rejects_zero_power_enabled_row(self, monkeypatch):
        self._fast_clock(monkeypatch)
        w = self._web(self.ROW)  # cmd=775 dropped: row stays Enable @ 0 mW
        with pytest.raises(RuntimeError, match="unverified"):
            w.set_poe_state(5, False)

    def test_disable_verifies_on_state_disable(self, monkeypatch):
        import copy

        self._fast_clock(monkeypatch)
        rows = copy.deepcopy(self.ROW)

        def apply(rows):
            rows[5]["state"] = "Disable"

        assert self._web(rows, apply).set_poe_state(5, False)["state"] == "Disable"

    def test_enable_still_verifies_on_watts(self, monkeypatch):
        import copy

        self._fast_clock(monkeypatch)
        rows = copy.deepcopy(self.ROW)

        def apply(rows):
            rows[5]["mw"] = 4300

        assert self._web(rows, apply).set_poe_state(5, True)["mw"] == 4300
