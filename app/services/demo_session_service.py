"""Starts a session for the public demo account.

No credentials: the caller is anonymous. The session is issued by the same
AuthService.start_session as a password login, only with a shorter lifetime
and the ``demo`` auth method. There are no refresh tokens, so a demo session
ends when its token expires.
"""
from __future__ import annotations

from datetime import timedelta

from flask import current_app, jsonify

from app.services.auth_service import AuthService
from app.services.demo_account import DemoAccount
from app.services.session_service import AuthMethod


class DemoSessionService:
    @staticmethod
    def start():
        owner = DemoAccount.owner()
        if owner is None or not DemoAccount.is_demo_user(owner):
            return jsonify({
                'code': 'DEMO_UNAVAILABLE',
                'error': 'The demo is not available right now. Please try again later.',
            }), 503

        DemoSessionService._refresh_data_if_stale()

        return AuthService.start_session(
            owner,
            auth_method=AuthMethod.DEMO,
            expires_delta=timedelta(minutes=DemoAccount.session_minutes()),
        )

    @staticmethod
    def _refresh_data_if_stale():
        # Seed dates are relative to the day they were generated; the first demo
        # visitor of a new day regenerates them so the farm never looks stale.
        # A failure here must not block the demo; yesterday's data still works.
        from app.services.demo_seed_service import DemoSeedService

        try:
            DemoSeedService.refresh_if_stale()
        except Exception:
            current_app.logger.exception('Demo data refresh failed; serving existing data.')
