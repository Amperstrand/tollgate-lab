# Scenario Layer — one tollgate story, every rig

Status: proposed (branch `scenario-layer`). Owner request 2026-09-27:
"phone, debian, omarchy — all more or less the same with slight
variations… real vs virtual too… make it DRY, modular, parameterized."

## Problem

The same tollgate lifecycle is hand-written three times:

| Stack | Language | Client focus | Best-in-class at | Duplicated |
|---|---|---|---|---|
| omarchy-cashu/vm-testbed | bash + python (vfind) | Omarchy UX panel | UX clicks (OpenCV+ydotool), wf-recorder video, DEMO/story split, result.json | lifecycle, evidence naming |
| physical-router-test-automation | python/pytest + Playwright | phone (adb), Debian container, browser | client×router matrix, `pay_via` marker, lib/ clients (U2Phone, EvidenceRecorder), assert helpers | lifecycle, evidence, token sourcing |
| fips-lab | python/pytest | BLE mesh | — | (infra only today) |

tollgate-lab already unifies device orchestration (labgrid drivers,
fixtures, provisioning). What is still copied everywhere is the
**scenario**: fund → connect → gate-closed → pay → gate-open → session →
renew → expire → fallback → evidence. That belongs here.

## Design

### 1. Driver contract (tollgate_lab/scenarios/contract.py)

Native `Protocol` classes (py≥3.11, no runtime deps beyond stdlib+pyyaml):

```python
class ClientDriver(Protocol):
    name: str
    def connect_wifi(self, ssid: str, *, timeout_s: int = 60) -> None: ...
    def active_ssid(self) -> str | None: ...
    def status(self) -> dict: ...                 # cashud /status shape
    def inject_token(self, token: str) -> None: ...  # clipboard/adb/type
    def open_wallet_ux(self) -> None: ...         # panel/app launch

class PaymentActor(Protocol):
    strategy: str                                  # ux_button|token_paste|portal_tip03|cli|skip
    def pay(self, client: ClientDriver, gateway: "GatewayDriver") -> PayReceipt: ...

class GatewayDriver(Protocol):
    def advertisement(self) -> dict: ...
    def usage(self, client: ClientDriver) -> Usage | None: ...
    def session_state(self, client: ClientDriver) -> SessionState: ...
    def external_reachable(self, client: ClientDriver) -> bool: ...
    def mint_token(self, sats: int) -> str: ...   # counterparty wallet

class CaptureDriver(Protocol):
    def start(self, artifact_dir: Path) -> None: ...
    def step(self, name: str) -> None: ...        # timeline event
    def stop(self) -> CaptureResult: ...          # paths + durations
```

### 2. Lifecycle (scenarios/lifecycle.py)

The canonical steps, each a plain function taking the composed roles,
each emitting an evidence event. Steps map 1:1 onto what the bash
stories and PRTA tests already assert:

`rig_up → wallet_fresh → actor_mints_token → client_connects →
gate_closed_asserted → payment_made → gate_open_asserted →
session_asserted → (renewal_observed) → (wallet_drained →
fallback_observed) → evidence_written`

Optional phases are profile flags (`renewal: true`, `drain_and_fallback:
true`) — S6's "token is the ONLY funding" rule is
`wallet_fresh: drained`, not new code.

### 3. Profiles (profiles/*.yaml)

```yaml
# omarchy-ux-real.yaml — the S5 shape
client:  {driver: omarchy_ux, vssh: "ssh -p 2222 …", templates: vm-testbed/host/templates}
payment: {actor: ux_button, template: btn-pay-tollgate.png}
gateway: {driver: http_module, base: "http://10.99.97.2:2121", token_source: fakewallet}
capture: {driver: wf_recorder, split_screen: true}
phases:  {renewal: true, drain_and_fallback: true}
```

Other launch profiles: `debian-container-real` (PRTA QEMU path),
`phone-adb-mt3000` (finale), `omarchy-ux-mock` (S1-S4), `phone-cuttlefish`.

### 4. Adapters — where each stack's "best" is kept, not rewritten

- `omarchy_ux` client: port of uilib semantics (vfind template match +
  ydotool via VSSH; re-open panel before each click — the 7ed5bdd
  lesson). Lives here so PRTA/fips tests can drive the Omarchy panel.
- `portal_tip03` actor: distilled from PRTA
  `test_rig_phone_payment._pay_through_portal` (state machine:
  portal_ready → token_typing → Purchase/Pay → authed/countdown).
- `http_module` gateway: vm-testbed's parse contracts (kind 10021/1022,
  `used/allotment`, `-1/-1`), identity-scoped probes **from inside the
  client** (the S5 lesson — host-side reads -1/-1 by design).
- `wf_recorder` + PRTA `EvidenceRecorder` wrap behind one CaptureDriver.

### 5. Evidence contract (scenarios/evidence.py)

`result.json` (today's story schema: pass/fail per step) PLUS a step
timeline `timeline.jsonl` consumable by test-films — video stays
first-class per the owner's requirement; a human must be able to watch
the capture and follow every step.

## Migration (collision-aware)

- **Phase 0 (now):** this doc + skeleton on branch `scenario-layer`.
  No active lane works in tollgate-lab — safe.
- **Phase 1:** omarchy adapter + `omarchy-ux-mock` profile proven
  against the ai-legion rig AFTER its current e2e+S6 work settles; S6's
  validated bash flow is the porting reference.
- **Phase 2:** PRTA phone/debian tests migrate to profiles — only when
  the finale/parity lanes are idle; their lib/ clients get thin adapter
  wrappers, tests keep their pytest markers.
- **Phase 3:** vm-testbed bash stories retire story-by-story; DEMO.sh's
  split-screen pipeline feeds test-films from timeline.jsonl.

Nothing in this branch changes existing tollgate-lab modules; the
package is additive (`scenarios/`, `profiles/`).
