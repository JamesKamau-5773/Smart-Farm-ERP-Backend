"""Phone (WhatsApp reverse OTP) and email verification endpoints."""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app import limiter
from app.services.email_verification_service import EmailVerificationService
from app.services.phone_verification_service import PhoneVerificationService
from app.utils.current_user import require_current_user
from app.utils.rate_limiting import authenticated_user_key, recovery_contact_key

auth_verification_bp = Blueprint('auth_verification', __name__)


@auth_verification_bp.route('/phone/verification', methods=['POST'])
@jwt_required()
@limiter.limit("3 per 10 minutes;10 per day", key_func=authenticated_user_key)
@limiter.limit("5 per 10 minutes", key_func=recovery_contact_key)
def start_phone_verification():
    data = request.get_json(silent=True) or {}
    result = PhoneVerificationService.start(
        require_current_user(), data.get('phone_number'), ip_address=request.remote_addr,
    )
    return jsonify(result), 201


@auth_verification_bp.route('/phone/verification/<verification_id>', methods=['GET'])
@jwt_required()
@limiter.limit("60 per minute", key_func=authenticated_user_key)
def phone_verification_status(verification_id):
    return jsonify(PhoneVerificationService.status(require_current_user(), verification_id)), 200


@auth_verification_bp.route('/email/verification', methods=['POST'])
@jwt_required()
@limiter.limit("3 per hour", key_func=authenticated_user_key)
def send_email_verification():
    result = EmailVerificationService.send(require_current_user(), ip_address=request.remote_addr)
    return jsonify(result), 202


@auth_verification_bp.route('/email/verification/confirm', methods=['POST'])
@limiter.limit("20 per 10 minutes")
def confirm_email_verification():
    data = request.get_json(silent=True) or {}
    return jsonify(EmailVerificationService.confirm(data.get('token') or '')), 200
