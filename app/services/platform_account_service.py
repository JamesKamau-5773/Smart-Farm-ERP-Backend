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

    # -- moving the super admin out of a farm tenant (flask platform move/split) ---------------------
    # Rows in these tables do not make a tenant a working farm: an empty farm shell created at
    # sign-up, and request-replay bookkeeping.
    _NOT_FARM_DATA = frozenset({'farms', 'idempotency_records'})

    @staticmethod
    def tenant_contents(tenant_id: int, *, excluding_user_id: Optional[int] = None) -> dict:
        """Row counts, per table, of everything scoped to this tenant (read-only)."""
        from sqlalchemy import func, select

        counts = {}
        for table in sorted(db.metadata.sorted_tables, key=lambda t: t.name):
            column = table.c.get('tenant_id')
            if column is None:
                continue
            query = select(func.count()).select_from(table).where(column == tenant_id)
            if table.name == 'users' and excluding_user_id is not None:
                query = query.where(table.c.id != excluding_user_id)
            count = db.session.execute(query).scalar()
            if count:
                counts[table.name] = count
        return counts

    @staticmethod
    def status() -> dict:
        """Read-only summary for operators (flask platform status)."""
        from app.services.mfa_service import MfaService

        platform = PlatformTenant.get()
        admins = User.query.filter_by(role=Role.SUPER_ADMIN).all()
        report = {'platform_tenant_id': platform.id if platform else None, 'super_admins': []}
        for admin in admins:
            report['super_admins'].append({
                'user_id': admin.id,
                'username': admin.username,
                'active': bool(admin.is_active),
                'tenant_id': admin.tenant_id,
                'in_platform_tenant': bool(platform and admin.tenant_id == platform.id),
                'mfa_enrolled': MfaService.is_enrolled(admin),
                'tenant_contents': PlatformAccountService.tenant_contents(admin.tenant_id, excluding_user_id=admin.id),
            })
        return report

    @staticmethod
    def _legacy_admin(plan: AccountChangePlan):
        admin = PlatformAccountService.super_admin()
        platform = PlatformTenant.get()
        if admin is None:
            plan.refusal = 'There is no super admin.'
        elif platform is None:
            plan.refusal = 'The platform tenant does not exist; run the database migrations first.'
        elif admin.tenant_id == platform.id:
            plan.refusal = 'The super admin is already in the platform tenant. Nothing to do.'
        return admin, platform

    @staticmethod
    def plan_move(reason: str) -> AccountChangePlan:
        from app.models.mfa import MfaSession

        plan = AccountChangePlan('Move the super admin account into the platform tenant')
        plan.refusal = _check_reason(reason)
        if plan.refused:
            return plan
        admin, platform = PlatformAccountService._legacy_admin(plan)
        if plan.refused:
            return plan

        contents = PlatformAccountService.tenant_contents(admin.tenant_id, excluding_user_id=admin.id)
        farm_data = {table: n for table, n in contents.items() if table not in PlatformAccountService._NOT_FARM_DATA}
        if farm_data:
            listing = ', '.join(f'{table}: {n}' for table, n in farm_data.items())
            plan.refusal = (f'Tenant {admin.tenant_id} holds farm data ({listing}). Moving the account would cut '
                            'that farm off from its owner. Use split-super-admin instead.')
            return plan

        source = admin.tenant_id
        plan.changes = [
            f'super admin {_describe(admin)}:',
            f'  tenant_id {source} -> {platform.id} (the platform tenant); page access cleared',
            '  every session ended (token_version + 1); two-factor enrolment kept',
            f'tenant {source} and its rows are left exactly as they are: '
            + (', '.join(f'{t}: {n}' for t, n in contents.items()) or 'no rows'),
            'audit entry SUPER_ADMIN_MOVED with the reason',
        ]

        def apply():
            with super_admin_changes_allowed():
                MfaSession.query.filter_by(user_id=admin.id).delete()
                admin.tenant_id = platform.id
                admin.page_access = None
                SessionService.revoke_all_sessions(admin)
                record_audit(
                    user_id=None, action='SUPER_ADMIN_MOVED', entity_type='User', entity_id=admin.id,
                    old_value={'tenant_id': source},
                    new_value={'tenant_id': platform.id, 'reason': reason.strip(), **_cli_actor()},
                    ip_address=None,
                )
                db.session.commit()

        plan.apply = apply
        return plan

    @staticmethod
    def plan_split(reason: str, *, username: str, name: str, email: Optional[str] = None,
                   password: Optional[str] = None) -> AccountChangePlan:
        """For a super admin whose account runs a real farm: the old account becomes that farm's
        FARMER (its data untouched) and a new account becomes the super admin in the platform tenant.

        ``password`` may be None for a dry run; it is required to apply.
        """
        from app.repositories.user_repo import UserRepository
        from app.services.mfa_service import MfaService
        from app.utils.password_policy import PasswordPolicy

        plan = AccountChangePlan('Split the super admin from its farm account')
        plan.refusal = _check_reason(reason)
        if plan.refused:
            return plan
        admin, platform = PlatformAccountService._legacy_admin(plan)
        if plan.refused:
            return plan

        username = (username or '').strip()
        email = (email or '').strip().lower() or None
        if not username:
            plan.refusal = '--username is required.'
        elif UserRepository.get_by_username(username):
            plan.refusal = f'The username {username!r} is already taken.'
        elif email and UserRepository.get_by_email_ci(email):
            plan.refusal = 'That email address is already used by another account.'
        elif password is not None and PasswordPolicy.violations(password, personal_values=[username, email or '']):
            plan.refusal = 'The password does not meet the password policy: ' + '; '.join(
                PasswordPolicy.violations(password, personal_values=[username, email or ''])
            )
        if plan.refused:
            return plan

        contents = PlatformAccountService.tenant_contents(admin.tenant_id, excluding_user_id=admin.id)
        plan.changes = [
            f'current super admin {_describe(admin)}:',
            f'  role SUPER_ADMIN -> FARMER; stays in tenant {admin.tenant_id}',
            '  two-factor secret and recovery codes deleted; every session ended',
            f'new super admin {username!r} ({name or username}):',
            f'  created in the platform tenant {platform.id} with role SUPER_ADMIN, no phone number'
            + (f', email {email}' if email else ''),
            '  must enrol two-factor authentication at first sign-in',
            f'tenant {admin.tenant_id} and its rows are left exactly as they are: '
            + (', '.join(f'{t}: {n}' for t, n in contents.items()) or 'no rows'),
            'audit entry SUPER_ADMIN_SPLIT with the reason',
        ]

        def apply():
            if password is None:
                raise ValueError('A password for the new super admin account is required.')
            with super_admin_changes_allowed():
                MfaService.clear(admin)
                admin.role = Role.FARMER
                SessionService.revoke_all_sessions(admin)
                db.session.flush()  # Frees the single-super-admin index for the new account.
                new_admin = PlatformAccountService.create_super_admin(NewSuperAdmin(
                    username=username, identifier=f'platform_{username}', name=(name or username).strip(),
                    password=password, email=email,
                ))
                record_audit(
                    user_id=None, action='SUPER_ADMIN_SPLIT', entity_type='User', entity_id=new_admin.id,
                    old_value={'super_admin_user_id': admin.id, 'tenant_id': admin.tenant_id},
                    new_value={
                        'super_admin_user_id': new_admin.id, 'former_account_role': Role.FARMER,
                        'reason': reason.strip(), **_cli_actor(),
                    },
                    ip_address=None,
                )
                db.session.commit()

        plan.apply = apply
        return plan
