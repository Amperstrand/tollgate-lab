"""zyxel_stock — client for stock-firmware Zyxel GS1900 switches (V2.90 era).

Live-verified on GS1900-8HP #2 @ V2.90(AAHI.0), 2026-09-25. Everything here
was proven against the real switch; quirks are encoded, not documented away.

Two access paths:

  StockWeb   — the dispatcher.cgi web API (the ONLY write path on stock)
  StockCLI   — the read-only SSH CLI (enable via web first, see enable_ssh)

Quirks baked in (see also docs/stock-2.90-investigation.md):
- Login is two-phase: obfuscated-password POST -> one-time authId nonce ->
  login_chk POST -> HTTP_XSSID cookie. The authId MUST be stripped.
- Only ONE web session per user: a fresh login while another lives can
  return NotAuth — retry with a clean cookie jar.
- cmd=775 (PoE toggle) returns an ERROR PAGE for partial-field POSTs while
  STILL APPLYING the state change. Response bodies are never evidence;
  every write is verified by re-polling cmd=773.
- Omitted sibling fields in cmd=775 drift the port's config (observed:
  PD priority Low -> Critical). Writes therefore do read-modify-write with
  the FULL field set (recipe per jonbulica99/zyxel-poe-manager).
- The SSH CLI needs commands fed on stdin with short delays; a plain
  `ssh host 'command'` returns silently.

dispatcher.cgi cmd reference (ours live-verified *; others from
hugil/zyxel-mcp and jonbulica99/zyxel-poe-manager — verify before use):
  0 login page *      1 dashboard frameset *   3 menu tree *
  548/549 TELNET cfg/apply *   550/551 SSH cfg/apply *
  773/774/775 PoE status/form/toggle *         799 port status
  1283 VLAN list (ajax)      1290-1292 PVID list/edit/apply
  1293/1294 VLAN membership view/apply         2049 MAC table
  5899 save running->startup
"""

from __future__ import annotations

import http.cookiejar
import random
import re
import subprocess
import time
import urllib.request

SSH_KEX = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "HostKeyAlgorithms=+ssh-rsa",
    "-o",
    "KexAlgorithms=+diffie-hellman-group1-sha1",
    "-o",
    "ConnectTimeout=8",
]

#: Full-field cmd=775 POST payload — the read-modify-write sibling set.
#: portPriority/portPowerMode are NUMERIC ENUMS on the wire (learned the hard
#: way 2026-09-25: posting display strings drifts the port — power mode fell
#: back to 802.3af). Maps below convert the cmd=773 display strings.
PRIORITY_ENUM = {"Critical": "0", "High": "1", "Medium": "2", "Low": "3"}
POWERMODE_ENUM = {
    "802.3af": "0",
    "Legacy": "1",
    "Pre-802.3at": "2",
    "802.3at": "3",
}
POE_TOGGLE_FIELDS = {
    "portLimitMode": "0",
    "portRangeDetection": "",
    "poeTimeRange": "",
}


def zyxel_encode(pw: str) -> str:
    """Replicate the login page's JS encode(): 321 chars, password reversed
    into every 5th position, length digits at offsets 123/289, rest random.
    (Older firmware used a 320/7th-position variant — see
    hugil/zyxel-mcp; ours is live-verified on V2.90(AAHI.0).)"""
    possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    text, ln, lenn, i = [], len(pw), len(pw), 1
    while i <= (321 - len(pw)):
        if i % 5 == 0 and ln > 0:
            ln -= 1
            text.append(pw[ln])
        elif i == 123:
            text.append("0" if lenn < 10 else str(lenn // 10))
        elif i == 289:
            text.append(str(lenn % 10))
        else:
            text.append(possible[random.randrange(len(possible))])
        i += 1
    return "".join(text)


class StockWeb:
    """Authenticated dispatcher.cgi session (the write path)."""

    def __init__(self, host: str, password: str, user: str = "admin"):
        self.base = f"http://{host}/cgi-bin/dispatcher.cgi"
        self.user, self.host = user, host
        self._login(password)

    def _login(self, password: str) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

        def post(data: str) -> str:
            req = urllib.request.Request(
                self.base,
                data=data.encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            return self.opener.open(req, timeout=8).read().decode("latin-1", "replace")

        for attempt in range(3):  # single-session limit -> NotAuth retries
            self.jar.clear()
            auth_id = post(
                f"username={self.user}&password={zyxel_encode(password)}&login=true;"
            ).strip()
            if not re.fullmatch(r"[0-9A-F]+", auth_id):
                raise RuntimeError(f"login phase 1 failed: {auth_id[:40]!r}")
            if "OK" in post(f"authId={auth_id}&login_chk=true"):
                self.xssid = self._xssid()
                return
            time.sleep(1 + attempt)
        raise RuntimeError("login failed (login_chk never OK — stale session?)")

    def _xssid(self) -> str:
        m = re.search(r'name="XSSID"\s+value="([0-9A-F]+)"', self.get(550))
        if not m:
            raise RuntimeError("no XSSID token on cmd=550")
        return m.group(1)

    def get(self, cmd: int) -> str:
        return (
            self.opener.open(f"{self.base}?cmd={cmd}", timeout=8)
            .read()
            .decode("latin-1", "replace")
        )

    def post_cmd(self, cmd: int, fields: dict[str, str]) -> str:
        data = "&".join(f"{k}={v}" for k, v in fields.items())
        req = urllib.request.Request(
            self.base,
            data=f"XSSID={self.xssid}&{data}&cmd={cmd}&sysSubmit=Apply".encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return self.opener.open(req, timeout=8).read().decode("latin-1", "replace")

    # -- PoE ----------------------------------------------------------------

    def poe_status(self) -> dict[int, dict]:
        """cmd=773 -> {port: {state, class_, priority, powerup, mw}}.
        THE truth source — never trust write responses."""
        rows = {}
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", self.get(773), re.S):
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
            ]
            if len(cells) >= 8 and cells[2].isdigit():
                mw = re.sub(r"[^0-9]", "", cells[7]) or "0"
                rows[int(cells[2])] = {
                    "state": cells[3],
                    "class": cells[4],
                    "priority": cells[5],
                    "powerup": cells[6],
                    "mw": int(mw),
                }
        return rows

    def set_poe_state(self, port: int, enabled: bool, priority: str | None = None) -> dict:
        """Full-field read-modify-write toggle, verified by re-poll.
        Sibling fields come from the CURRENT 773 row (converted to their
        wire enums) so nothing drifts; ``priority`` optionally overrides the
        PD priority (display string, e.g. "Low" — drift repair)."""
        cur = self.poe_status().get(port)
        if cur is None:
            raise RuntimeError(f"port {port} not present in cmd=773")
        try:
            pri = PRIORITY_ENUM[priority or cur["priority"]]
            mode = POWERMODE_ENUM[cur["powerup"]]
        except KeyError as e:
            raise RuntimeError(
                f"unknown PoE display value {e} (row={cur}) — refusing to "
                "POST a value that would drift the port"
            ) from None
        fields = {
            "portlist": str(port),
            "state": "1" if enabled else "0",
            "portPriority": pri,
            "portPowerMode": mode,
        }
        fields.update({k: v for k, v in POE_TOGGLE_FIELDS.items() if k not in fields})
        self.post_cmd(775, fields)
        deadline = time.monotonic() + 30
        want_mw = int(enabled)
        while time.monotonic() < deadline:
            row = self.poe_status().get(port, {})
            delivering = row.get("mw", 0) > 0
            if delivering == want_mw or (not enabled and row.get("state") == "Disable"):
                return row
            time.sleep(1.5)
        raise RuntimeError(f"poe toggle port {port} unverified: {row}")

    # -- services -----------------------------------------------------------

    def enable_ssh(self) -> bool:
        """cmd=550/551: enable the SSH service. Returns final checked state."""
        self.post_cmd(551, {"sshd": "1"})
        return re.search(r'name="sshd"[^>]*value="1"[^>]*checked', self.get(550)) is not None

    def enable_telnet(self) -> bool:
        self.post_cmd(549, {"telnetd": "1"})
        page = self.get(548)
        return re.search('name="telnetd"[^>]*value="1"[^>]*checked', page) is not None


class StockCLI:
    """Read-only SSH CLI (stdin-fed; see module docstring)."""

    def __init__(self, host: str, password: str, user: str = "admin"):
        self.argv = ["sshpass", "-p", password, "ssh", *SSH_KEX, f"{user}@{host}"]

    def run(self, commands: list[str], settle: float = 2.5) -> str:
        """Feed commands to the CLI with LOCAL delays (a bare `ssh host
        'cmd'` returns silently; the CLI needs a moment before each line)."""
        proc = subprocess.Popen(
            self.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert proc.stdin is not None
        for cmd in commands:
            time.sleep(settle)
            proc.stdin.write(cmd + "\n")
            proc.stdin.flush()
        time.sleep(settle)
        proc.stdin.write("exit\n")
        proc.stdin.flush()
        try:
            out, _ = proc.communicate(timeout=20 + settle * len(commands))
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return out or ""


def mac_address_table(host: str, password: str) -> dict[str, list[str]]:
    """CLI `show mac address-table` -> {mac: [ports]}."""
    out = StockCLI(host, password).run(["show mac address-table"])
    table: dict[str, list[str]] = {}
    for line in out.splitlines():
        m = re.match(r"\s*\d+\s*\|\s*([0-9A-F:]{17})\s*\|\s*\w+\s*\|\s*(\S+)", line)
        if m:
            table.setdefault(m.group(1).lower(), []).append(m.group(2))
    return table
