"""The canonical tollgate lifecycle (docs/SCENARIO-LAYER.md §2).

rig_up → wallet_fresh → actor_mints_token → client_connects →
gate_closed_asserted → payment_made → gate_open_asserted → session_asserted
→ (renewal_observed) → (wallet_drained → fallback_observed) →
evidence_written

Each step is a plain function over the composed roles; each emits an
evidence event and appends to the result. Optional phases are profile flags;
`wallet_fresh: drained` IS the S6 rule (the token is the only funding), not
new code. On step failure the run records it and stops — no partial
continues — but evidence is still written, like vm-testbed's story runner.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tollgate_lab.scenarios.contract import (
    CaptureResult,
    PayReceipt,
    ScenarioRoles,
    Usage,
)
from tollgate_lab.scenarios.evidence import LifecycleResult, StepRecord, write_evidence
from tollgate_lab.scenarios.profile import ScenarioProfile

log = logging.getLogger(__name__)

RENEWAL_TIMEOUT_S = 30.0
RENEWAL_POLL_INTERVAL_S = 1.0

BALANCE_KEY = "balance_sats"


class StepFailureError(Exception):
    """A lifecycle step's assertion did not hold."""


@dataclass
class StepContext:
    """Mutable state threaded through the steps of one run."""

    profile: ScenarioProfile
    artifact_dir: Path
    advertisement: dict[str, Any] | None = None
    receipt: PayReceipt | None = None
    capture_result: CaptureResult | None = None
    tollgate_ssid: str | None = None
    records: list[StepRecord] = field(default_factory=list)


StepFn = Callable[[ScenarioRoles, StepContext], None]


@dataclass(frozen=True)
class StepSpec:
    name: str
    run: StepFn
    gated_by: str | None = None  # profile.step_gates() key; None = always runs


def _rig_up(roles: ScenarioRoles, ctx: StepContext) -> None:
    adv = roles.gateway.advertisement()
    if not isinstance(adv, dict) or not adv:
        raise StepFailureError("gateway returned no advertisement")
    ctx.advertisement = adv
    ssid = adv.get("ssid")
    if not isinstance(ssid, str) or not ssid:
        raise StepFailureError(f"advertisement lacks a usable ssid: {adv!r}")
    ctx.tollgate_ssid = ssid


def _wallet_fresh(roles: ScenarioRoles, ctx: StepContext) -> None:
    status = roles.client.status()
    balance = status.get(BALANCE_KEY)
    if balance is None:
        raise StepFailureError(f"client status lacks '{BALANCE_KEY}': {status!r}")
    if ctx.profile.phases.wallet_fresh == "drained" and balance != 0:
        raise StepFailureError(f"wallet_fresh=drained but {BALANCE_KEY}={balance}")


def _actor_mints_token(roles: ScenarioRoles, ctx: StepContext) -> None:
    token = roles.gateway.mint_token(ctx.profile.payment.sats)
    if not token:
        raise StepFailureError("counterparty minted an empty token")
    roles.client.inject_token(token)


def _client_connects(roles: ScenarioRoles, ctx: StepContext) -> None:
    if ctx.tollgate_ssid is None:
        raise StepFailureError("rig_up did not record a tollgate ssid")
    roles.client.connect_wifi(ctx.tollgate_ssid)
    active = roles.client.active_ssid()
    if active != ctx.tollgate_ssid:
        raise StepFailureError(f"client reports ssid {active!r}, expected {ctx.tollgate_ssid!r}")


def _gate_closed_asserted(roles: ScenarioRoles, ctx: StepContext) -> None:
    if roles.gateway.external_reachable(roles.client):
        raise StepFailureError("external internet reachable before payment — gate is not closed")


def _payment_made(roles: ScenarioRoles, ctx: StepContext) -> None:
    receipt = roles.actor.pay(roles.client, roles.gateway)
    if receipt.sats <= 0:
        raise StepFailureError(f"payment receipt carries non-positive sats: {receipt!r}")
    ctx.receipt = receipt


def _gate_open_asserted(roles: ScenarioRoles, ctx: StepContext) -> None:
    if not roles.gateway.external_reachable(roles.client):
        raise StepFailureError("external internet unreachable after payment — gate did not open")


def _session_asserted(roles: ScenarioRoles, ctx: StepContext) -> None:
    usage = roles.gateway.usage(roles.client)
    if usage is None or usage.is_void:
        raise StepFailureError(f"no /usage session after payment: {usage!r}")
    if usage.allotment <= 0:
        raise StepFailureError(f"session allotment not positive: {usage!r}")
    state = roles.gateway.session_state(roles.client)
    if not state.is_active:
        raise StepFailureError(f"session state {state.state!r} after payment, expected 'active'")


def _renewal_observed(roles: ScenarioRoles, ctx: StepContext) -> None:
    before = roles.gateway.usage(roles.client)
    if before is None or before.is_void:
        raise StepFailureError(f"no /usage session before renewal window: {before!r}")
    deadline = time.monotonic() + RENEWAL_TIMEOUT_S
    while True:
        after = roles.gateway.usage(roles.client)
        if after is not None and _is_renewal(before, after):
            state = roles.gateway.session_state(roles.client)
            if state.is_active:
                return
            raise StepFailureError(f"renewed usage but session state {state.state!r}")
        if time.monotonic() >= deadline:
            raise StepFailureError(
                f"no renewal observed within {RENEWAL_TIMEOUT_S:.0f}s: "
                f"before={before!r} after={after!r}"
            )
        time.sleep(RENEWAL_POLL_INTERVAL_S)


def _is_renewal(before: Usage, after: Usage) -> bool:
    return after.allotment > before.allotment or (
        after.allotment >= before.allotment and after.used < before.used
    )


def _wallet_drained(roles: ScenarioRoles, ctx: StepContext) -> None:
    status = roles.client.status()
    balance = status.get(BALANCE_KEY)
    if balance is None:
        raise StepFailureError(f"client status lacks '{BALANCE_KEY}': {status!r}")
    if balance != 0:
        raise StepFailureError(f"wallet not drained: {BALANCE_KEY}={balance}")


def _fallback_observed(roles: ScenarioRoles, ctx: StepContext) -> None:
    state = roles.gateway.session_state(roles.client)
    if state.is_active:
        raise StepFailureError("session still active — fallback cannot have happened")
    if ctx.tollgate_ssid is None:
        raise StepFailureError("no tollgate ssid recorded; cannot assert fallback")
    active = roles.client.active_ssid()
    if active == ctx.tollgate_ssid:
        raise StepFailureError(f"client still on {active!r} — no fallback to another network")
    if roles.gateway.external_reachable(roles.client):
        raise StepFailureError("external internet reachable after fallback — gate should be closed")


def _evidence_written(roles: ScenarioRoles, ctx: StepContext) -> None:
    if roles.capture is None:
        return
    try:
        ctx.capture_result = roles.capture.stop()
    except Exception:
        log.warning("capture stop failed; evidence continues without video", exc_info=True)


CANONICAL_STEPS: tuple[StepSpec, ...] = (
    StepSpec("rig_up", _rig_up),
    StepSpec("wallet_fresh", _wallet_fresh),
    StepSpec("actor_mints_token", _actor_mints_token),
    StepSpec("client_connects", _client_connects),
    StepSpec("gate_closed_asserted", _gate_closed_asserted),
    StepSpec("payment_made", _payment_made),
    StepSpec("gate_open_asserted", _gate_open_asserted),
    StepSpec("session_asserted", _session_asserted),
    StepSpec("renewal_observed", _renewal_observed, gated_by="renewal_observed"),
    StepSpec("wallet_drained", _wallet_drained, gated_by="wallet_drained"),
    StepSpec("fallback_observed", _fallback_observed, gated_by="fallback_observed"),
    StepSpec("evidence_written", _evidence_written),
)


def run_lifecycle(
    roles: ScenarioRoles, profile: ScenarioProfile, artifact_dir: Path | str
) -> LifecycleResult:
    """Execute the canonical steps against the composed roles.

    Gated steps omitted by profile flags are simply not run (and not
    recorded); steps after a failure are recorded as SKIP and never
    executed. evidence_written always executes last, and the evidence files
    are written even for failed runs.
    """
    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = StepContext(profile=profile, artifact_dir=out_dir)
    gates = profile.step_gates()

    _capture_start(roles, out_dir)
    stopped = False
    for spec in CANONICAL_STEPS:
        if spec.gated_by is not None and not gates.get(spec.gated_by, False):
            continue
        if stopped and spec.name != "evidence_written":
            ctx.records.append(StepRecord(name=spec.name, status="SKIP", ts=_iso_now()))
            continue
        _capture_step(roles, spec.name)
        started = time.perf_counter()
        try:
            spec.run(roles, ctx)
            record = StepRecord(
                name=spec.name,
                status="PASS",
                ts=_iso_now(),
                duration_s=time.perf_counter() - started,
            )
        except Exception as exc:
            stopped = True
            record = StepRecord(
                name=spec.name,
                status="FAIL",
                ts=_iso_now(),
                duration_s=time.perf_counter() - started,
                error=_error_text(exc),
            )
            log.error("scenario step %s failed: %s", spec.name, record.error)
        ctx.records.append(record)

    ctx.records[-1] = _with_capture_artifacts(ctx.records[-1], ctx)
    paths = write_evidence(out_dir, story=profile.name, steps=ctx.records)
    log.info("scenario '%s' evidence: %s", profile.name, paths.result_json)
    return LifecycleResult(story=profile.name, steps=tuple(ctx.records))


def _with_capture_artifacts(record: StepRecord, ctx: StepContext) -> StepRecord:
    result = ctx.capture_result
    if result is None:
        return record
    hints: list[str] = []
    if result.video_path is not None:
        hints.append(_artifact_hint(result.video_path, ctx.artifact_dir))
    hints.extend(_artifact_hint(p, ctx.artifact_dir) for p in result.frame_paths)
    if not hints:
        return record
    return replace(record, artifacts=record.artifacts + tuple(hints))


def _artifact_hint(path: Path, artifact_dir: Path) -> str:
    try:
        return str(path.relative_to(artifact_dir))
    except ValueError:
        return str(path)


def _capture_start(roles: ScenarioRoles, artifact_dir: Path) -> None:
    if roles.capture is None:
        return
    try:
        roles.capture.start(artifact_dir)
    except Exception:
        log.warning("capture start failed; continuing without video", exc_info=True)


def _capture_step(roles: ScenarioRoles, name: str) -> None:
    if roles.capture is None:
        return
    try:
        roles.capture.step(name)
    except Exception:
        log.warning("capture step marker %r failed", name, exc_info=True)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _error_text(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= 500 else text[:497] + "..."
