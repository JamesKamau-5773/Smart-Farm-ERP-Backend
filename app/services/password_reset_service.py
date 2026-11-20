from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify
from flask_jwt_extended import set_access_cookies

from app import db
from app.models.hr import EmployeeOnboardingStatus
from app.models.user import RevokedToken
from app.services.audit_service import record_audit
from app.services.auth_service import AuthService
from app.services.session_service import SessionService
from app.utils.auth_errors import WeakPasswordError
from app.utils.password_policy import PasswordPolicy


class PasswordResetService:
    @staticmethod
    def complete_required_reset(user, data: dict, claims: dict, *, ip_address=None):
        if not user.requires_password_reset:
            return jsonify({'error': 'A forced password reset is not required.'}), 409

        password = data.get('password') or ''
        confirm_password = data.get('confirm_password') or data.get('confirmPassword') or ''
        if password != confirm_password:
            return jsonify({'error': 'password and confirm_password must match.'}), 400
        violations = PasswordPolicy.violations(password, personal_values=PasswordPolicy.personal_values_for(user))
        if violations:
            return WeakPasswordError(violations).to_response()
        if user.check_password(password):
            return jsonify({'error': 'New password must differ from the temporary password.'}), 400

        user.set_password(password)
        user.requires_password_reset = False
        # The temporary password may have been shared; end every other session.
        SessionService.revoke_all_sessions(user)
        if user.employee_profile:
            user.employee_profile.onboarding_status = EmployeeOnboardingStatus.ACTIVE

        PasswordResetService._revoke_token(claims)
        record_audit(
            user_id=user.id,
            action='COMPLETE_PASSWORD_RESET',
            entity_type='User',
            entity_id=user.id,
            old_value={'requires_password_reset': True},
            new_value={'requires_password_reset': False},
            ip_address=ip_address,
        )
        db.session.commit()
        return PasswordResetService._new_session_response(user, claims, 'Password configured successfully.')

    @staticmethod
    def change_password(user, data: dict, claims: dict, *, ip_address=None):
        """A signed-in user changes their own password, or sets one if they sign in with Google only.

        Needs the current password when the account has one. Every other session ends; this one
        gets a fresh token, so the person stays signed in here.
        """
        if user.requires_password_reset:
            return jsonify({
                'code': 'PASSWORD_RESET_REQUIRED',
                'error': 'Set your password through the required reset first.',
            }), 409

        current = data.get('current_password') or data.get('currentPassword') or ''
        password = data.get('new_password') or data.get('newPassword') or ''
        confirm_password = data.get('confirm_password') or data.get('confirmPassword') or ''

        if user.has_password and not current:
            return _field_error('current_password', 'required', 'current_password is required.')
        if not password:
            return _field_error('new_password', 'required', 'new_password is required.')
        if password != confirm_password:
            return _field_error('confirm_password', 'mismatch', 'new_password and confirm_password must match.')
        if user.has_password and not user.check_password(current):
            record_audit(
                user_id=user.id, action='CHANGE_PASSWORD_FAILED', entity_type='User', entity_id=user.id,
                old_value=None, new_value={'reason': 'current_password_incorrect'}, ip_address=ip_address,
            )
            db.session.commit()
            return jsonify({
                'code': 'INVALID_CURRENT_PASSWORD',
                'error': 'Current password is incorrect.',
                'fields': {'current_password': 'invalid'},
            }), 400
        violations = PasswordPolicy.violations(password, personal_values=PasswordPolicy.personal_values_for(user))
        if violations:
            return WeakPasswordError(violations).to_response()
        if user.has_password and user.check_password(password):
            return _field_error('new_password', 'unchanged', 'New password must differ from the current one.')

        had_password = bool(user.has_password)
        user.set_password(password)
        SessionService.revoke_all_sessions(user)
        PasswordResetService._revoke_token(claims)
        record_audit(
            user_id=user.id,
            action='CHANGE_PASSWORD' if had_password else 'SET_PASSWORD',
            entity_type='User',
            entity_id=user.id,
            old_value={'has_password': had_password},
            new_value={'has_password': True},
            ip_address=ip_address,
        )
        db.session.commit()
        message = 'Password changed.' if had_password else 'Password set.'
        return PasswordResetService._new_session_response(user, claims, message)

    @staticmethod
    def _revoke_token(claims: dict) -> None:
        """Revokes the token this request was made with. The caller commits."""
        token_id = claims.get('jti')
        expires_at = claims.get('exp')
        if token_id and expires_at and not RevokedToken.query.filter_by(jti=token_id).first():
            db.session.add(RevokedToken(
                jti=token_id,
                expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            ))

    @staticmethod
    def _new_session_response(user, claims: dict, message: str):
        """A fresh token for this session after the password changed (all older ones are revoked)."""
        tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
        active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=None)
        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=farms,
            active_farm=active_farm,
            auth_method=SessionService.auth_method_from_claims(claims),
        )
        response = jsonify({
            'message': message,
            'access_token': access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 200


def _field_error(field: str, reason: str, message: str):
    return jsonify({'code': 'VALIDATION_ERROR', 'error': message, 'fields': {field: reason}}), 400
