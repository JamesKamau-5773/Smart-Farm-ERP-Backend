"""Time-based one-time passwords (RFC 6238) from an authenticator app. No SMS.

``now`` can be passed in, so tests control the clock.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone
from typing import Optional

import pyotp

PERIOD_SECONDS = 30
DIGITS = 6
# Accept the previous and next 30-second step, for phone clocks that drift.
DRIFT_STEPS = 1


class TotpService:
    @staticmethod
    def new_secret() -> str:
        return pyotp.random_base32(length=32)

    @staticmethod
    def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
        """The otpauth:// URI the frontend renders as a QR code."""
        return pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD_SECONDS).provisioning_uri(
            name=account_name, issuer_name=issuer,
        )

    @staticmethod
    def current_step(now: Optional[datetime] = None) -> int:
        now = now or datetime.now(timezone.utc)
        return int(now.timestamp()) // PERIOD_SECONDS

    @staticmethod
    def code_at(secret: str, step: int) -> str:
        return pyotp.TOTP(secret, digits=DIGITS, interval=PERIOD_SECONDS).at(step * PERIOD_SECONDS)

    @staticmethod
    def matching_step(secret: str, code: str, *, last_used_step: Optional[int] = None,
                      now: Optional[datetime] = None) -> Optional[int]:
        """The time step this code belongs to, or None.

        A code for a step at or before ``last_used_step`` is refused, so a code
        (or an older one) can never be replayed.
        """
        code = ''.join(ch for ch in str(code or '') if ch.isdigit())
        if len(code) != DIGITS:
            return None
        current = TotpService.current_step(now)
        for step in range(current - DRIFT_STEPS, current + DRIFT_STEPS + 1):
            if last_used_step is not None and step <= last_used_step:
                continue
            if hmac.compare_digest(TotpService.code_at(secret, step), code):
                return step
        return None
