"""The single SUPER_ADMIN account: the only code that creates, moves or demotes it.

Every change runs inside ``super_admin_changes_allowed()``; the model guard in
app/models/user.py refuses the same change anywhere else. The partial unique
index ``uq_users_single_super_admin`` is the final guard against a second one.
"""
from __future__ import annotations

import getpass
import socket
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from sqlalchemy.exc import IntegrityError

from app import db
from app.models.user import Role, User
from app.services.audit_service import record_audit
from app.services.platform_tenant import PlatformTenant
from app.services.session_service import SessionService
from app.utils.phone import InvalidPhoneNumber, to_e164
from app.utils.super_admin_guard import SuperAdminChangeRefused, super_admin_changes_allowed


class SuperAdminExists(SuperAdminChangeRefused):
    """A super admin already exists; there can only be one."""


MIN_REASON_LENGTH = 10


@dataclass
class AccountChangePlan:
    """What a ``flask platform`` command would change, or why it refuses.

    ``changes`` are printed before anything happens (and are all a --dry-run does);
    ``apply`` makes exactly those changes in one transaction.
    """
    title: str
    changes: List[str] = field(default_factory=list)
    refusal: Optional[str] = None
    apply: Optional[Callable[[], None]] = None

    @property
    def refused(self) -> bool:
        return self.refusal is not None


def _cli_actor() -> dict:
    try:
        os_user = getpass.getuser()
    except Exception:  # pragma: no cover - no login name in some containers
        os_user = 'unknown'
    return {'actor': 'flask platform (server CLI)', 'os_user': os_user, 'host': socket.gethostname()}


def _check_reason(reason: str) -> Optional[str]:
    if len((reason or '').strip()) < MIN_REASON_LENGTH:
        return f'--reason must explain the change in at least {MIN_REASON_LENGTH} characters.'
    return None


def _describe(user: User) -> str:
    return f'user {user.id} ({user.username}, role {user.role}, tenant {user.tenant_id})'


@dataclass(frozen=True)
class NewSuperAdmin:
    username: str
    identifier: str
    name: str
    password: str
    phone_number: Optional[str] = None
    email: Optional[str] = None


class PlatformAccountService:
    @staticmethod
    def super_admin() -> Optional[User]:
        return User.query.filter_by(role=Role.SUPER_ADMIN).first()

    @staticmethod
    def is_platform_super_admin(user: Optional[User]) -> bool:
        """The live database answer: the SUPER_ADMIN, active, in the platform tenant."""
        return bool(
            user is not None
            and user.role == Role.SUPER_ADMIN
            and user.is_active
            and PlatformTenant.is_platform(user.tenant)
        )

    @staticmethod
    def create_super_admin(details: NewSuperAdmin) -> User:
        """Creates the super admin in the platform tenant. Flushes; the caller commits.

        Raises SuperAdminExists when one already exists (checked here, and by the
        unique index if two requests race).
        """
        if PlatformAccountService.super_admin() is not None:
            raise SuperAdminExists('A super admin already exists.')
        tenant = PlatformTenant.get_or_create()
        user = User(
            tenant_id=tenant.id,
            identifier=details.identifier,
            username=details.username,
            name=details.name,
            phone_number=details.phone_number,
            email=details.email,
            role=Role.SUPER_ADMIN,
            is_active=True,
        )
        user.set_password(details.password)
        with super_admin_changes_allowed():
            db.session.add(user)
            try:
                db.session.flush()
            except IntegrityError as error:
                if 'uq_users_single_super_admin' in str(error.orig):
                    raise SuperAdminExists('A super admin already exists.') from error
                raise
        return user

    # -- server-side recovery commands (flask platform ...) -----------------------------------
    @staticmethod
    def plan_reset_2fa(reason: str) -> AccountChangePlan:
        from app.models.mfa import MfaSession, UserMfaCredential, UserMfaRecoveryCode
        from app.services.mfa_service import MfaService

        plan = AccountChangePlan('Reset the super admin\'s two-factor authentication')
        plan.refusal = _check_reason(reason)
        admin = PlatformAccountService.super_admin()
        if admin is None:
            plan.refusal = plan.refusal or 'There is no super admin.'
        if plan.refused:
            return plan

        enrolled = db.session.get(UserMfaCredential, admin.id) is not None
        codes = UserMfaRecoveryCode.query.filter_by(user_id=admin.id).count()
        sessions = MfaSession.query.filter_by(user_id=admin.id).count()
        plan.changes = [
            f'{_describe(admin)}:',
            f'  delete the authenticator secret ({"enrolled" if enrolled else "none on record"})',
            f'  delete {codes} recovery code(s) and {sessions} verified-session record(s)',
            '  end every signed-in session (token_version + 1)',
            '  the next sign-in must enrol two-factor authentication again',
            '  audit entry MFA_RESET with the reason',
        ]

        def apply():
            removed = MfaService.clear(admin)
            SessionService.revoke_all_sessions(admin)
            record_audit(
                user_id=None, action='MFA_RESET', entity_type='User', entity_id=admin.id, old_value=None,
                new_value={**removed, 'reason': reason.strip(), **_cli_actor()}, ip_address=None,
            )
            db.session.commit()

        plan.apply = apply
        return plan

    @staticmethod
    def plan_transfer(to_phone: str, reason: str) -> AccountChangePlan:
        from app.services.mfa_service import MfaService

        plan = AccountChangePlan('Transfer the super admin role')
        plan.refusal = _check_reason(reason)
        current = PlatformAccountService.super_admin()
        try:
            target = User.query.filter_by(phone_number=to_e164(to_phone)).first()
        except InvalidPhoneNumber:
            target = None
        platform = PlatformTenant.get()

        if plan.refused:
            return plan
        if current is None:
            plan.refusal = 'There is no super admin to transfer from.'
        elif platform is None or current.tenant_id != platform.id:
            plan.refusal = ('The super admin is not in the platform tenant yet. Run move-super-admin or '
                            'split-super-admin first.')
        elif target is None:
            plan.refusal = 'No account has that phone number.'
        elif target.id == current.id:
            plan.refusal = 'That account is already the super admin.'
        elif target.is_demo or (target.tenant and target.tenant.is_demo):
            plan.refusal = 'A demo account cannot become the super admin.'
        elif not target.is_active:
            plan.refusal = 'That account is deactivated.'
        elif getattr(target, 'employee_profile', None) is not None:
            plan.refusal = ('That account is linked to a staff record on a farm. Use an account that '
                            'belongs to no farm.')
        elif PlatformAccountService._is_last_administrator(target):
            plan.refusal = ('That account is the last owner or administrator of its farm; moving it would '
                            'leave the farm without one. Use another account.')
        if plan.refused:
            return plan

        plan.changes = [
            f'current super admin {_describe(current)}:',
            '  role SUPER_ADMIN -> FARMER, deactivated, stays in the platform tenant',
            '  two-factor secret and recovery codes deleted; every session ended',
            f'new super admin {_describe(target)}:',
            f'  moved from tenant {target.tenant_id} to the platform tenant {platform.id}; role -> SUPER_ADMIN',
            '  page access cleared; every session ended; must enrol two-factor authentication at next sign-in',
            'no farm record is changed',
            'audit entry SUPER_ADMIN_TRANSFERRED with the reason',
        ]

        def apply():
            from_tenant = target.tenant_id
            with super_admin_changes_allowed():
                MfaService.clear(current)
                current.role = Role.FARMER
                current.is_active = False
                SessionService.revoke_all_sessions(current)
                db.session.flush()  # Frees the single-super-admin index before the promotion.

                MfaService.clear(target)
                target.tenant_id = platform.id
                target.role = Role.SUPER_ADMIN
                target.page_access = None
                SessionService.revoke_all_sessions(target)
                record_audit(
                    user_id=None, action='SUPER_ADMIN_TRANSFERRED', entity_type='User', entity_id=target.id,
                    old_value={'super_admin_user_id': current.id, 'new_admin_previous_tenant_id': from_tenant},
                    new_value={'super_admin_user_id': target.id, 'reason': reason.strip(), **_cli_actor()},
                    ip_address=None,
                )
                db.session.commit()

        plan.apply = apply
        return plan

    @staticmethod
    def _is_last_administrator(user: User) -> bool:
        owner_roles = (Role.FARMER, Role.FARM_ADMIN, Role.ADMIN)
        if user.role not in owner_roles:
            return False
        others = User.query.filter(
            User.tenant_id == user.tenant_id, User.id != user.id, User.is_active.is_(True),
            User.role.in_(owner_roles),
        ).count()
        return others == 0
