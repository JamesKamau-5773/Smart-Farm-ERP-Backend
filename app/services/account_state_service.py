"""Derives the frontend-facing ``auth_state`` and ``account_flags`` for a user."""
from __future__ import annotations

from app.models.user import User
from app.repositories.social_account_repo import SocialAccountRepository
from app.services.session_service import AuthMethod


class AuthState:
    ACTIVE = 'ACTIVE'
    PASSWORD_RESET_REQUIRED = 'PASSWORD_RESET_REQUIRED'
    PHONE_VERIFICATION_REQUIRED = 'PHONE_VERIFICATION_REQUIRED'


class AccountStateService:
    @staticmethod
    def requires_phone_verification(user: User, auth_method: str) -> bool:
        # Only social sign-ins are gated; password users get the needs_phone nudge.
        return auth_method == AuthMethod.GOOGLE and not user.phone_verified

    @staticmethod
    def auth_state(user: User, auth_method: str) -> str:
        if user.requires_password_reset:
            return AuthState.PASSWORD_RESET_REQUIRED
        if AccountStateService.requires_phone_verification(user, auth_method):
            return AuthState.PHONE_VERIFICATION_REQUIRED
        return AuthState.ACTIVE

    @staticmethod
    def account_flags(user: User) -> dict:
        return {
            'needs_phone': user.needs_phone,
            'phone_verified': bool(user.phone_verified),
            'email_verified': bool(user.email_verified),
            'has_password': bool(user.has_password),
            'linked_providers': SocialAccountRepository.providers_for_user(user.id) if user.id else [],
        }

    @staticmethod
    def describe(user: User, auth_method: str) -> dict:
        return {
            'auth_state': AccountStateService.auth_state(user, auth_method),
            'account_flags': AccountStateService.account_flags(user),
        }
