"""cyd_qr unit tests — protocol framing against a fake serial port."""

from __future__ import annotations

from tollgate_lab.cyd_qr import QR_WINNING_CAP, CydError, CydQrClient


class FakeSerial:
    def __init__(self, replies: list[bytes]):
        self.replies = list(replies)
        self.written: list[bytes] = []

    def reset_input_buffer(self):
        pass

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def readline(self):
        return self.replies.pop(0) if self.replies else b""

    def close(self):
        pass


def _client(replies, monkeypatch):
    fake = FakeSerial(replies)
    monkeypatch.setattr("tollgate_lab.cyd_qr.serial.Serial", lambda *a, **k: fake)
    return CydQrClient("/dev/fake")


def test_id_roundtrip(monkeypatch):
    c = _client([b"CYDQR 1.0.0\n"], monkeypatch)
    assert c.id() == "CYDQR 1.0.0"
    assert c.ser.written[-1] == b"ID\n"


def test_show_qr_sends_hex_payload_and_parses_reply(monkeypatch):
    c = _client([b"RENDERED 29 6 2\n"], monkeypatch)
    modules, px = c.show_qr(b"AB")
    assert (modules, px) == (29, 6)
    assert c.ser.written[-1] == f"QRS {QR_WINNING_CAP} 4142\n".encode()


def test_no_reply_raises_cyd_error(monkeypatch):
    c = _client([], monkeypatch)
    try:
        c.id()
        raise AssertionError("expected CydError")
    except CydError as e:
        assert "no reply" in str(e)


def test_bad_render_reply_raises(monkeypatch):
    c = _client([b"ERROR something\n"], monkeypatch)
    try:
        c.show_qr(b"AB")
        raise AssertionError("expected CydError")
    except CydError as e:
        assert "render failed" in str(e)


def test_set_inverted_confirms_state(monkeypatch):
    c = _client([b"INVERTED 1\n"], monkeypatch)
    c.set_inverted(True)  # no raise

    c2 = _client([b"INVERTED 0\n", b"INVERTED 0\n"], monkeypatch)
    try:
        c2.set_inverted(True)
        raise AssertionError("expected CydError (stuck)")
    except CydError as e:
        assert "stuck" in str(e)
