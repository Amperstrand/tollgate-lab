import pytest


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


# -- review-debt wave 2026-10-31 (#17, #19, #20) -----------------------------


class TestCompletePasswordGate:
    """#17: the gate-page fetch must not route through StockWeb._fetch on a
    bare __new__ instance (AttributeError on _in_login before the form is
    processed)."""

    def test_gate_page_fetched_without_attribute_error(self, monkeypatch):
        import urllib.request as urllib_request

        import tollgate_lab.hardware.zyxel_stock as zs

        opens = []

        class FakeResponse:
            def __init__(self, body):
                self._body = body.encode("latin-1")

            def read(self):
                return self._body

        class FakeOpener:
            def open(self, req, timeout=8):
                url = req.full_url
                data = req.data.decode() if req.data else ""
                opens.append((url, data))
                if "login=true" in data:
                    return FakeResponse("ABCDEF0123")
                if "login_chk" in data:
                    return FakeResponse("OK")
                if "cmd=30" in url:
                    return FakeResponse(
                        '<input name="XSSID" value="DEADBEEF01">'
                    )
                return FakeResponse("")

        class NeverWeb:
            def __init__(self, host, pw):
                raise RuntimeError("final verification fails in this test")

        monkeypatch.setattr(urllib_request, "build_opener", lambda *a: FakeOpener())
        monkeypatch.setattr(urllib_request, "HTTPCookieProcessor", lambda *a: None)
        monkeypatch.setattr(zs, "StockWeb", NeverWeb)
        # reaching the final verification (False, not AttributeError) proves
        # the gate page was fetched and the form POSTed
        assert zs.complete_password_gate("h", "old", "new") is False
        gate_gets = [o for o in opens if "cmd=30" in o[0]]
        assert gate_gets, "gate page never fetched"
        gate_post = [o for o in opens if "cmd=31" in o[1]]
        assert gate_post, "gate form never POSTed"


class TestEvictionRebuild:
    """#19: after a re-login the retried POST must carry the FRESH XSSID."""

    def _make_web(self):
        import tollgate_lab.hardware.zyxel_stock as zs

        w = zs.StockWeb.__new__(zs.StockWeb)
        w.base = "http://h/cgi-bin/dispatcher.cgi"
        w.user, w.host = "admin", "h"
        w._password = "pw"
        w._in_login = False
        w.xssid = "STALE01"
        return w

    def test_retry_rebuilds_body_with_fresh_token(self, monkeypatch):
        import urllib.request

        import tollgate_lab.hardware.zyxel_stock as zs

        w = self._make_web()
        responses = ["LOGINPAGE", "ok"]  # first open = evicted, second = healthy
        calls = []

        class Opener:
            def open(self, req, timeout=8):
                calls.append(req.data.decode() if req.data else "GET")
                body = responses.pop(0).encode()
                return type("R", (), {"read": lambda s: body})()

        def fake_login(self, password):
            w.opener = Opener()  # post-login opener
            w.xssid = "FRESH99"  # re-login refreshes the CSRF token

        monkeypatch.setattr(zs.StockWeb, "_login", fake_login)
        monkeypatch.setattr(
            zs.StockWeb, "_evicted", lambda self, body: body == "LOGINPAGE"
        )

        def rebuild():
            return urllib.request.Request(
                w.base,
                data=f"XSSID={w.xssid}&cmd=775".encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        w.opener = Opener()
        body = w._fetch(rebuild(), rebuild=rebuild)
        assert body == "ok"
        assert calls[0].startswith("XSSID=STALE01")
        assert calls[1].startswith("XSSID=FRESH99"), "retry reused the stale token"


class TestDisableVerification:
    """#20: a disable on a 0 mW port whose admin row still says Enable must
    NOT verify (dropped cmd=775 read as success before)."""

    def _web_with_rows(self, monkeypatch, rows, clock):
        import tollgate_lab.hardware.zyxel_stock as zs

        w = zs.StockWeb.__new__(zs.StockWeb)
        w.base = "http://h/cgi-bin/dispatcher.cgi"
        w._password = "pw"
        w._in_login = False
        monkeypatch.setattr(
            zs.StockWeb, "post_cmd", lambda self, cmd, fields: "", raising=True
        )
        monkeypatch.setattr(
            zs.StockWeb, "poe_status", lambda self: {k: dict(v) for k, v in rows.items()}
        )
        monkeypatch.setattr(zs.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(zs.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
        return w

    def test_dropped_disable_does_not_verify(self, monkeypatch):

        clock = {"t": 0.0}
        rows = {5: {"state": "Enable", "class": "class0", "priority": "Low",
                    "powerup": "802.3at", "mw": 0}}
        w = self._web_with_rows(monkeypatch, rows, clock)
        with pytest.raises(RuntimeError, match="unverified"):
            w.set_poe_state(5, enabled=False)

    def test_real_disable_verifies(self, monkeypatch):

        clock = {"t": 0.0}
        rows = {5: {"state": "Disable", "class": "class0", "priority": "Low",
                    "powerup": "802.3at", "mw": 0}}
        w = self._web_with_rows(monkeypatch, rows, clock)
        assert w.set_poe_state(5, enabled=False)["state"] == "Disable"
