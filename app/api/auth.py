from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.auth_service import AuthService
from app import limiter
from app.repositories.user_repo import UserRepository
from app.utils.jwt_payload import parse_public_int_id

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per 10 minutes")
@limiter.limit("5 per minute")  # Redis throttle: Max 10 attempts per IP
def login():
    # Some clients trigger preflight through wrapped decorators; keep login tolerant.
    if request.method == 'OPTIONS':
        return jsonify({"ok": True}), 200

    data = request.get_json(silent=True) or {}
    username_or_phone = (data.get('username') or data.get('phone_number') or '').strip()

    # Input Validation
    if not username_or_phone or not data.get('password'):
        return jsonify({"error": "phone_number (or username) and password are required"}), 400

    return AuthService.authenticate_user(
        username_or_phone,
        data['password'],
        farm_id=data.get('farm_id'),
    )


@auth_bp.route('/register', methods=['POST'])
@limiter.limit("5 per 10 minutes")
@limiter.limit("2 per minute")
def register():
    data = request.get_json(silent=True) or {}
    return AuthService.register_workspace(data)


@auth_bp.route('/switch-farm', methods=['POST'])
@jwt_required()
def switch_farm():
    data = request.get_json() or {}
    farm_id = data.get('farm_id')
    if not farm_id:
        return jsonify({"error": "farm_id is required"}), 400

    user_id = get_jwt_identity()
    return AuthService.switch_farm(user_id, farm_id)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    return AuthService.logout_user()


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def me():
    user_id = get_jwt_identity()
    user = UserRepository.get_by_id(int(user_id)) if user_id else None
    if not user:
        return jsonify({"error": "User not found"}), 404

    from flask_jwt_extended import get_jwt
    claims = get_jwt() or {}
    tenant = getattr(user, 'tenant', None)

    phone_number = AuthService._resolve_phone_number(user)

    return jsonify({
        'id': user.id,
        'name': user.name or user.username,
        'username': user.username,
        'phone_number': phone_number,
        'role': user.role,
        'is_active': user.is_active,
        'tenant_id': claims.get('tenant_id') or (f'tenant_{tenant.id}' if tenant else None),
        'tenant_name': claims.get('tenant_name') or (tenant.name if tenant else None),
        'tenant_type': claims.get('tenant_type') or (getattr(tenant, 'tenant_type', None) if tenant else None),
        'farm_id': claims.get('farm_id'),
        'farm_name': claims.get('farm_name'),
        'available_farms': claims.get('available_farms', []),
        'permissions': [user.role],
    }), 200


@auth_bp.route('/status', methods=['GET'])
# @jwt_required() # We will implement role decorators in the next sprint
def status():
    """A simple endpoint to verify if the server is responding to auth routes."""
    return jsonify({"status": "Auth Blueprint is active."}), 200
