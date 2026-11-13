"""Typed errors for authentication flows.

Services raise ``AuthError``; a global handler renders it as the
``{"code": ..., "error": ...}`` envelope documented in docs/AUTH_API_CONTRACT.md.
"""
from __future__ import annotations

from app.utils.api_errors import ApiError


class AuthError(ApiError):
    """An ``ApiError`` raised by the authentication flows."""


class WeakPasswordError(AuthError):
    def __init__(self, violations):
        super().__init__(
            'WEAK_PASSWORD',
            'Password does not meet the password policy.',
            400,
            violations=list(violations),
        )


def invalid_phone_error() -> AuthError:
    return AuthError('INVALID_PHONE', 'phone_number must be a valid phone number.')
