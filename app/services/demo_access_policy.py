"""What a demo session may do: read the demo farm, nothing else.

Applied to every request by ``app.middleware.enforce_demo_read_only`` (one
place, before any endpoint runs). Endpoints never check for demo sessions
themselves.

* Any state-changing method (POST, PUT, PATCH, DELETE, ...) is refused with
  ``DEMO_READ_ONLY``, except the few routes that only end or replace the
  session, or that act anonymously (signing in to a real account).
* Some GETs are refused with ``DEMO_FEATURE_UNAVAILABLE``: exports and
  downloads, workspace/member administration, and the Google account-linking
  flow (whose GET callback writes).

Tenant scoping is not handled here: a demo session carries the demo tenant in
its token and goes through the same tenant filters as everyone else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# Writes a demo session may still make. None of these act on the demo account's data.
WRITE_ALLOWED_ENDPOINTS = frozenset({
    'auth.logout',                  # ends this session (revokes only this token)
    'auth_demo.start_demo_session', # restarts the demo
    'auth.login',                   # leave the demo by signing in to a real account
    'auth.register',                # ... or creating one
    'auth.claim_account',
    'auth_google.google_signup',
})
WRITE_ALLOWED_ENDPOINT_PREFIXES = (
    'auth_recovery.',               # password recovery for a real account, by phone/email
)

# Paths that export or download data, or administer the workspace and its members.
_UNAVAILABLE_PATHS = re.compile(
    r'(/export/'
    r'|\.pdf$|/pdf$|\.csv$|/csv$|\.xlsx$|/download'
    r'|^/api/onboarding/'
    r'|^/api/tenant/(cooperatives|members|users)(/|$)'
    r')'
)
_GOOGLE_LINK_INTENT = 'link'


@dataclass(frozen=True)
class DemoDenial:
    status: int
    code: str
    message: str

    def body(self) -> dict:
        return {'code': self.code, 'error': self.message, 'demo': True}


READ_ONLY = DemoDenial(
    403, 'DEMO_READ_ONLY',
    'This is a read-only demo. Create a free account to record your own farm data.',
)
UNAVAILABLE = DemoDenial(
    403, 'DEMO_FEATURE_UNAVAILABLE',
    'This feature is not available in the demo. Create a free account to use it.',
)


def denial_for(*, method: str, endpoint: Optional[str], path: str,
               google_intent: Optional[str] = None) -> Optional[DemoDenial]:
    """Why a demo session may not make this request, or None if it may."""
    method = (method or '').upper()
    endpoint = endpoint or ''
    path = path or ''

    if method not in READ_METHODS:
        if endpoint in WRITE_ALLOWED_ENDPOINTS or endpoint.startswith(WRITE_ALLOWED_ENDPOINT_PREFIXES):
            return None
        return READ_ONLY

    if method == 'OPTIONS':
        return None
    if _UNAVAILABLE_PATHS.search(path):
        return UNAVAILABLE
    if endpoint.startswith('auth_google.') and google_intent == _GOOGLE_LINK_INTENT:
        return UNAVAILABLE
    return None
