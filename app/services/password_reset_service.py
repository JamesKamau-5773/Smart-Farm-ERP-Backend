from __future__ import annotations

from datetime import datetime, timezone

from flask import jsonify
from flask_jwt_extended import set_access_cookies

from app import db
from app.models.hr import EmployeeOnboardingStatus
from app.models.user import RevokedToken
from app.services.audit_service import record_audit
from app.services.auth_service import AuthService


class PasswordResetService:
    @staticmethod
    def complete_required_reset(user, data: dict, claims: dict, *, ip_address=None):
        if not user.requires_password_reset:
            return jsonify({'error': 'A forced password reset is not required.'}), 409

        password = data.get('password') or ''
        confirm_password = data.get('confirm_password') or data.get('confirmPassword') or ''
        if password != confirm_password:
            return jsonify({'error': 'password and confirm_password must match.'}), 400
        if len(password) < 8:
            return jsonify({'error': 'password must be at least 8 characters.'}), 400
        if user.check_password(password):
            return jsonify({'error': 'New password must differ from the temporary password.'}), 400

        user.set_password(password)
        user.requires_password_reset = False
        if user.employee_profile:
            user.employee_profile.onboarding_status = EmployeeOnboardingStatus.ACTIVE

        token_id = claims.get('jti')
        expires_at = claims.get('exp')
        if token_id and expires_at and not RevokedToken.query.filter_by(jti=token_id).first():
            db.session.add(RevokedToken(
                jti=token_id,
                expires_at=datetime.fromtimestamp(expires_at, tz=timezone.utc),
            ))
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

        tenant, farms = AuthService._ensure_default_tenant_and_farm(user)
        active_farm = AuthService._pick_active_farm(tenant=tenant, farms=farms, requested_farm_id=None)
        access_token, payload = AuthService._issue_token_and_payload(
            user=user,
            tenant=tenant,
            farms=farms,
            active_farm=active_farm,
        )
        response = jsonify({
            'message': 'Password configured successfully.',
            'access_token': access_token,
            **payload,
        })
        set_access_cookies(response, access_token)
        return response, 200
