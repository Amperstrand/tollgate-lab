

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
