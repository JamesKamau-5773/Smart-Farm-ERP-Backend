from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, or_
from uuid import uuid4

from flask import current_app, jsonify
from flask_jwt_extended import decode_token
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.account_invitation import AccountInvitation
from app.models.farm import Farm
from app.models.hr import EmployeeOnboardingStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.hr_repo import EmployeeRepository
from app.services.auth_service import AuthService
from app.services.audit_service import record_audit
from app.services.staff_account_service import StaffAccountService
from app.services.page_access import normalize_page_access
from app.utils.jwt_payload import public_tenant_id


class AccountInvitationService:
    INVITE_TOKEN_EXPIRY_HOURS = 48
    STAFF_INVITE_PURPOSE = 'staff_account_invite'
    LEGACY_MEMBER_INVITE_PURPOSE = 'member_invite'

    @staticmethod
    def _invite_url(token: str) -> str:
        frontend_base = current_app.config.get('FRONTEND_BASE_URL', '').rstrip('/')
        path = f'/claim-account?token={token}'
        return f'{frontend_base}{path}' if frontend_base else path

    @staticmethod
    def create_short_invite_token(
        account: User,
        *,
        purpose: str,
        expires_delta: timedelta,
        employee_id: int | None = None,
        employee_nonce: str | None = None,
    ) -> str:
        """Create a 128-bit opaque token and persist only its SHA-256 hash."""
        now = datetime.now(timezone.utc)
        AccountInvitation.query.filter_by(
            account_id=account.id,
            purpose=purpose,
            consumed_at=None,
        ).update({'consumed_at': now}, synchronize_session=False)

        token = secrets.token_urlsafe(16)
        invitation = AccountInvitation(
            token_hash=hashlib.sha256(token.encode('utf-8')).hexdigest(),
            account_id=account.id,
            tenant_id=account.tenant_id,
            purpose=purpose,
            employee_id=employee_id,
            employee_nonce=employee_nonce,
            expires_at=now + expires_delta,
        )
        db.session.add(invitation)
        return token

    @staticmethod
    def _serialize_account(user: User) -> dict:
        return {
            'id': user.id,
            'name': user.name,
            'username': user.username,
            'phone_number': user.phone_number,
            'role': user.role,
            'is_active': user.is_active,
            'requires_password_reset': user.requires_password_reset,
        }

    @staticmethod
    def _create_staff_invite_token(account: User, employee_id: int, nonce: str) -> str:
        return AccountInvitationService.create_short_invite_token(
            account,
            purpose=AccountInvitationService.STAFF_INVITE_PURPOSE,
            employee_id=employee_id,
            employee_nonce=nonce,
            expires_delta=timedelta(hours=AccountInvitationService.INVITE_TOKEN_EXPIRY_HOURS),
        )

    @staticmethod
    def _invite_response(account: User, employee_id: int, invite_token: str, status_code: int):
        return jsonify({
            'message': 'Employee account invitation created successfully.',
            'employee_id': employee_id,
            'account': AccountInvitationService._serialize_account(account),
            'invite_token': invite_token,
            'invite_url': AccountInvitationService._invite_url(invite_token),
            'claim_url': AccountInvitationService._invite_url(invite_token),
            'expires_in_hours': AccountInvitationService.INVITE_TOKEN_EXPIRY_HOURS,
            'expires_in_days': AccountInvitationService.INVITE_TOKEN_EXPIRY_HOURS // 24,
            'onboarding_status': EmployeeOnboardingStatus.INVITE_PENDING,
        }), status_code

    @staticmethod
    def invite_employee(tenant_id: int, employee_id: int, data: dict, *, actor_id=None, ip_address=None):
        employee = EmployeeRepository.get_by_id_for_tenant(employee_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        try:
            role = StaffAccountService.validate_role(data.get('role'))
        except ValueError as error:
            return jsonify({'error': str(error)}), 400

        if employee.user:
            if employee.user.is_active:
                return jsonify({'error': 'Employee already has an active linked account.'}), 409
            employee.user.role = role
            account = employee.user
            status_code = 200
        else:
            try:
                account = StaffAccountService.create_linked_account(
                    employee,
                    data,
                    role=role,
                    password=uuid4().hex,
                    is_active=False,
                    requires_password_reset=False,
                )
                status_code = 201
            except ValueError as error:
                return jsonify({'error': str(error)}), 400
            except LookupError as error:
                return jsonify({'error': str(error)}), 409

        try:
            account.page_access = normalize_page_access(data.get('page_access'), role)
        except ValueError as error:
            db.session.rollback()
            return jsonify({'error': str(error)}), 400

        employee.onboarding_status = EmployeeOnboardingStatus.INVITE_PENDING
        employee.onboarding_invite_nonce = uuid4().hex
        employee.onboarding_invite_expires_at = datetime.now(timezone.utc) + timedelta(
            hours=AccountInvitationService.INVITE_TOKEN_EXPIRY_HOURS
        )
        invite_token = AccountInvitationService._create_staff_invite_token(
            account,
            employee.id,
            employee.onboarding_invite_nonce,
        )

        try:
            if actor_id is not None:
                record_audit(
                    user_id=actor_id,
                    action='INVITE_STAFF_ACCOUNT',
                    entity_type='Employee',
                    entity_id=employee.id,
                    old_value=None,
                    new_value={'role': role, 'status': EmployeeOnboardingStatus.INVITE_PENDING},
                    ip_address=ip_address,
                )
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'Could not create account due to duplicate account details.'}), 409
        except Exception:
            db.session.rollback()
            return jsonify({'error': 'Could not create employee account invitation.'}), 500

        return AccountInvitationService._invite_response(account, employee.id, invite_token, status_code)

    @staticmethod
    def claim_invite(token: str, password: str, username: str | None = None):
        if len(password or '') < 8:
            return jsonify({'error': 'password must be at least 8 characters.'}), 400

        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        invitation = AccountInvitation.query.filter_by(token_hash=token_hash).with_for_update().first()
        decoded = None
        if invitation:
            if invitation.consumed_at:
                return jsonify({'error': 'Invalid, expired, or superseded invite token.'}), 400
            now = datetime.now(timezone.utc)
            expires_at = invitation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                return jsonify({'error': 'Invalid or expired invite token.'}), 400
            account_id = invitation.account_id
            purpose = invitation.purpose
            invite_tenant_id = public_tenant_id(invitation.tenant_id)
            employee_id = invitation.employee_id
            employee_nonce = invitation.employee_nonce
        else:
            # Existing JWT links remain usable until they expire.
            try:
                decoded = decode_token(token)
            except Exception:
                return jsonify({'error': 'Invalid or expired invite token.'}), 400

            purpose = decoded.get('purpose')
            if purpose not in {
                AccountInvitationService.STAFF_INVITE_PURPOSE,
                AccountInvitationService.LEGACY_MEMBER_INVITE_PURPOSE,
            }:
                return jsonify({'error': 'Invalid invite token.'}), 400
            try:
                account_id = int(decoded.get('sub'))
            except (TypeError, ValueError):
                return jsonify({'error': 'Invalid invite token subject.'}), 400
            invite_tenant_id = decoded.get('tenant_id')
            employee_id = decoded.get('employee_id')
            employee_nonce = decoded.get('nonce')

        account = db.session.get(User, account_id)
        if not account:
            return jsonify({'error': 'Account not found.'}), 404
        if account.is_active:
            return jsonify({'error': 'Account invitation has already been claimed.'}), 409
        if invite_tenant_id != public_tenant_id(account.tenant_id):
            return jsonify({'error': 'Invite tenant does not match account tenant.'}), 400

        if username is not None and not isinstance(username, str):
            return jsonify({'error': 'username must be text.'}), 400
        chosen_username = (username if username is not None else account.username or '').strip().lower()
        if not re.fullmatch(r'[a-z0-9._-]{3,32}', chosen_username):
            return jsonify({'error': 'username must be 3 to 32 characters using letters, numbers, periods, underscores, or hyphens.'}), 400
        username_conflicts = [func.lower(User.username) == chosen_username]
        if chosen_username.isdigit():
            username_conflicts.append(User.phone_number == AuthService._normalize_phone_number(chosen_username))
        username_taken = User.query.filter(User.id != account.id).filter(or_(*username_conflicts)).first()
        if username_taken:
            return jsonify({'error': 'That username is already in use. Choose another one.'}), 409

        employee = None
        if purpose == AccountInvitationService.STAFF_INVITE_PURPOSE:
            employee = EmployeeRepository.get_by_id_for_tenant(employee_id, account.tenant_id)
            now = datetime.now(timezone.utc)
            expires_at = employee.onboarding_invite_expires_at if employee else None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if (
                not employee
                or employee.user_id != account.id
                or employee.onboarding_status != EmployeeOnboardingStatus.INVITE_PENDING
                or employee.onboarding_invite_nonce != employee_nonce
                or not expires_at
                or expires_at <= now
            ):
                return jsonify({'error': 'Invalid, expired, or superseded invite token.'}), 400

        account.username = chosen_username
        account.set_password(password)
        account.is_active = True
        account.requires_password_reset = False
        if employee:
            employee.onboarding_status = EmployeeOnboardingStatus.ACTIVE
            employee.onboarding_invite_nonce = None
            employee.onboarding_invite_expires_at = None
        if invitation:
            invitation.consumed_at = datetime.now(timezone.utc)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({'error': 'That username is already in use. Choose another one.'}), 409

        tenant = db.session.get(Tenant, account.tenant_id)
        if not tenant:
            return jsonify({'error': 'Account tenant context is missing.'}), 400
        farms = list(tenant.farms or [])
        if not farms:
            farm = Farm(tenant_id=tenant.id, name=f'{tenant.name} Main Farm')
            db.session.add(farm)
            db.session.commit()
            farms = [farm]

        access_token, payload = AuthService._issue_token_and_payload(
            user=account,
            tenant=tenant,
            farms=farms,
            active_farm=farms[0],
        )
        return jsonify({
            'message': 'Account claimed successfully.',
            'access_token': access_token,
            **payload,
        }), 200
