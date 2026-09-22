from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import current_app, jsonify
from flask_jwt_extended import create_access_token, decode_token
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.farm import Farm
from app.models.hr import EmployeeOnboardingStatus
from app.models.tenant import Tenant
from app.models.user import User
from app.repositories.hr_repo import EmployeeRepository
from app.services.auth_service import AuthService
from app.services.audit_service import record_audit
from app.services.staff_account_service import StaffAccountService
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
        return create_access_token(
            identity=str(account.id),
            additional_claims={
                'purpose': AccountInvitationService.STAFF_INVITE_PURPOSE,
                'tenant_id': public_tenant_id(account.tenant_id),
                'employee_id': employee_id,
                'role': account.role,
                'nonce': nonce,
            },
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
    def claim_invite(token: str, password: str):
        if len(password or '') < 8:
            return jsonify({'error': 'password must be at least 8 characters.'}), 400

        try:
            decoded = decode_token(token)
        except Exception:
            return jsonify({'error': 'Invalid or expired invite token.'}), 400

        if decoded.get('purpose') not in {
            AccountInvitationService.STAFF_INVITE_PURPOSE,
            AccountInvitationService.LEGACY_MEMBER_INVITE_PURPOSE,
        }:
            return jsonify({'error': 'Invalid invite token.'}), 400

        try:
            account_id = int(decoded.get('sub'))
        except (TypeError, ValueError):
            return jsonify({'error': 'Invalid invite token subject.'}), 400

        account = db.session.get(User, account_id)
        if not account:
            return jsonify({'error': 'Account not found.'}), 404
        if account.is_active:
            return jsonify({'error': 'Account invitation has already been claimed.'}), 409
        if decoded.get('tenant_id') != public_tenant_id(account.tenant_id):
            return jsonify({'error': 'Invite tenant does not match account tenant.'}), 400

        employee = None
        if decoded.get('purpose') == AccountInvitationService.STAFF_INVITE_PURPOSE:
            employee = EmployeeRepository.get_by_id_for_tenant(decoded.get('employee_id'), account.tenant_id)
            now = datetime.now(timezone.utc)
            expires_at = employee.onboarding_invite_expires_at if employee else None
            if expires_at and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if (
                not employee
                or employee.user_id != account.id
                or employee.onboarding_status != EmployeeOnboardingStatus.INVITE_PENDING
                or employee.onboarding_invite_nonce != decoded.get('nonce')
                or not expires_at
                or expires_at <= now
            ):
                return jsonify({'error': 'Invalid, expired, or superseded invite token.'}), 400

        account.set_password(password)
        account.is_active = True
        account.requires_password_reset = False
        if employee:
            employee.onboarding_status = EmployeeOnboardingStatus.ACTIVE
            employee.onboarding_invite_nonce = None
            employee.onboarding_invite_expires_at = None
        db.session.commit()

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
