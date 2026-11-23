"""Two-factor authentication endpoints for the platform admin (SUPER_ADMIN).

POST /api/auth/mfa/enrollment          start: secret + otpauth:// URI (only while not enrolled)
POST /api/auth/mfa/enrollment/confirm  {"code"}: finish; returns 10 recovery codes once + a verified session
POST /api/auth/mfa/verify              {"code"} or {"recovery_code"}: returns a verified session

Logic lives in app/services/mfa_service.py.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from app import limiter
from app.services.mfa_service import MfaService
from app.utils.current_user import require_current_user
from app.utils.rate_limiting import authenticated_user_key

auth_mfa_bp = Blueprint('auth_mfa', __name__)


def _client_ip_key() -> str:
    return f'mfa-ip:{request.remote_addr}'


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@auth_mfa_bp.route('/mfa/enrollment', methods=['POST'])
@jwt_required()
@limiter.limit('10 per hour', key_func=authenticated_user_key)
def start_enrolment():
    return jsonify(MfaService.start_enrolment(require_current_user())), 200


@auth_mfa_bp.route('/mfa/enrollment/confirm', methods=['POST'])
@jwt_required()
@limiter.limit('5 per 5 minutes', key_func=authenticated_user_key)
@limiter.limit('20 per hour', key_func=_client_ip_key)
def confirm_enrolment():
    return MfaService.confirm_enrolment(
        require_current_user(),
        str(_body().get('code') or ''),
        claims=get_jwt() or {},
        ip_address=request.remote_addr,
    )


@auth_mfa_bp.route('/mfa/verify', methods=['POST'])
@jwt_required()
@limiter.limit('5 per 5 minutes', key_func=authenticated_user_key)
@limiter.limit('20 per hour', key_func=_client_ip_key)
def verify():
    body = _body()
    return MfaService.verify(
        require_current_user(),
        code=str(body.get('code') or '') or None,
        recovery_code=str(body.get('recovery_code') or '') or None,
        claims=get_jwt() or {},
        ip_address=request.remote_addr,
    )
