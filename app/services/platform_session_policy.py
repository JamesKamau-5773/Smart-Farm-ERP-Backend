"""What a SUPER_ADMIN session may do. Applied to every request by
``app.middleware.enforce_platform_session``, before any endpoint runs.

* Before 2FA passes for this session: only finish 2FA, read /me, or log out
  (``MFA_REQUIRED``).
* After 2FA: only the auth endpoints and the platform endpoints below
  (``PLATFORM_SCOPE``). The platform tenant is never a farm, so farm routes are
  refused instead of quietly collecting records there.

The role is read live from the database; the token's claims are never trusted for it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PRE_MFA_ENDPOINTS = frozenset({
    'auth.me',
    'auth.logout',
    'auth.status',
    'auth_mfa.start_enrolment',
    'auth_mfa.confirm_enrolment',
    'auth_mfa.verify',
})

AUTH_ENDPOINT_PREFIXES = ('auth.', 'auth_mfa.', 'auth_recovery.', 'auth_verification.', 'auth_google.')

# Platform administration. Each is also protected by @platform_admin_required (or its service check).
PLATFORM_ENDPOINTS = frozenset({
    'tenant.profile',
    'tenant.create_cooperative',
    'tenant.invite_member',
    'tenant.import_members_csv',
    'tenant.issue_member_password_reset',
})


@dataclass(frozen=True)
class PlatformSessionDenial:
    status: int
    code: str
    message: str

    def body(self) -> dict:
        return {'code': self.code, 'error': self.message}


MFA_REQUIRED = PlatformSessionDenial(
    403, 'MFA_REQUIRED', 'Complete two-factor authentication to continue.',
)
PLATFORM_SCOPE = PlatformSessionDenial(
    403, 'PLATFORM_SCOPE', 'The platform admin account cannot use farm features.',
)


def denial_for(*, endpoint: Optional[str], path: str, method: str, mfa_verified: bool) -> Optional[PlatformSessionDenial]:
    """Why a SUPER_ADMIN session may not make this request, or None if it may."""
    endpoint = endpoint or ''
    if (method or '').upper() == 'OPTIONS' or not (path or '').startswith('/api/'):
        return None
    if endpoint in PRE_MFA_ENDPOINTS:
        return None
    if not mfa_verified:
        return MFA_REQUIRED
    if endpoint.startswith(AUTH_ENDPOINT_PREFIXES) or endpoint in PLATFORM_ENDPOINTS:
        return None
    return PLATFORM_SCOPE
