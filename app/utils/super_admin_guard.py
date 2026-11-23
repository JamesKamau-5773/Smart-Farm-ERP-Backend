"""Who may create, move, demote, deactivate or delete the SUPER_ADMIN account.

The model guard in app/models/user.py refuses every such change unless it runs
inside ``super_admin_changes_allowed()``. Only PlatformAccountService opens that
scope: the bootstrap (when no super admin exists) and the server-side
``flask platform`` commands. No request handler does, so no API endpoint can
create, promote to, demote from or transfer the role.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_allowed: ContextVar[bool] = ContextVar('super_admin_changes_allowed', default=False)


class SuperAdminChangeRefused(ValueError):
    """A change to the SUPER_ADMIN account outside the permitted paths, or one that breaks its rules."""


@contextmanager
def super_admin_changes_allowed():
    token = _allowed.set(True)
    try:
        yield
    finally:
        _allowed.reset(token)


def super_admin_changes_are_allowed() -> bool:
    return _allowed.get()
