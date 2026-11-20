"""Forgot-password and reset-link endpoints (public)."""
from flask import Blueprint, jsonify, request

from app import limiter
from app.services.password_recovery_service import PasswordRecoveryService
from app.services.password_reset_link_service import PasswordResetLinkService
from app.utils.rate_limiting import recovery_contact_key

auth_recovery_bp = Blueprint('auth_recovery', __name__)


@auth_recovery_bp.route('/password/forgot/options', methods=['GET'])
def forgot_password_options():
    return jsonify(PasswordRecoveryService.options()), 200


@auth_recovery_bp.route('/password/forgot', methods=['POST'])
@limiter.limit("5 per hour")
@limiter.limit("3 per hour", key_func=recovery_contact_key)
def forgot_password():
    data = request.get_json(silent=True) or {}
    return jsonify(PasswordRecoveryService.request(data, ip_address=request.remote_addr)), 202


@auth_recovery_bp.route('/password/reset/validate', methods=['POST'])
@limiter.limit("20 per 10 minutes")
def validate_reset_token():
    data = request.get_json(silent=True) or {}
    return jsonify(PasswordResetLinkService.validate(data.get('token') or '')), 200


@auth_recovery_bp.route('/password/reset', methods=['POST'])
@limiter.limit("10 per 10 minutes")
def reset_password():
    data = request.get_json(silent=True) or {}
    result = PasswordResetLinkService.reset(
        data.get('token') or '',
        data.get('password') or '',
        data.get('confirm_password') or data.get('confirmPassword') or '',
        ip_address=request.remote_addr,
    )
    return jsonify(result), 200
