"""SPEC STUB — TIP-03 captive-portal payment actor.

Distilled from physical-router-test-automation's
``test_rig_phone_payment._pay_through_portal``. The body is a
NotImplementedError placeholder; this docstring is the porting spec.

State machine (each state must be asserted before advancing):

    portal_ready → token_typing → Purchase/Pay → authed/countdown

- **portal_ready** — the captive portal page is reachable and interactive
  (Playwright on the Debian container / phone browser). The portal URL
  comes from the profile's ``payment.portal`` key.
- **token_typing** — paste/type the Cashu token into the portal's payment
  field. The token is sourced from the counterparty wallet
  (``gateway.mint_token``) before the actor runs.
- **Purchase/Pay** — click Purchase, confirm on the Pay step; both buttons
  are template/text matches, tolerant of the portal's two-step layout.
- **authed/countdown** — the portal flips to an authorized page with a
  session countdown; only then may ``pay`` return a PayReceipt.
"""

from __future__ import annotations

from tollgate_lab.scenarios.contract import (
    ClientDriver,
    GatewayDriver,
    PayReceipt,
)

__all__ = ["PortalTip03Actor"]


class PortalTip03Actor:
    """PaymentActor driving the TIP-03 web portal via a browser session."""

    strategy = "portal_tip03"

    def __init__(self, *, portal: str) -> None:
        self._portal = portal

    def pay(self, client: ClientDriver, gateway: GatewayDriver) -> PayReceipt:
        """Drive portal_ready → token_typing → Purchase/Pay → authed.

        The browser session lives on the client device (phone browser or
        container Playwright); this actor orchestrates it and asserts each
        state transition before advancing, exactly like PRTA's
        ``_pay_through_portal``.
        """
        raise NotImplementedError(
            "port PRTA _pay_through_portal state machine "
            "(portal_ready → token_typing → Purchase/Pay → authed/countdown)"
        )
