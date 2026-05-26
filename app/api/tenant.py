from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from app.repositories.user_repo import UserRepository
from app.utils.jwt_payload import normalize_tenant_type


tenant_bp = Blueprint('tenant', __name__)


@tenant_bp.route('/profile', methods=['GET'])
@jwt_required()
def profile():
    """Returns tenant metadata for the currently authenticated user."""
    user_id = get_jwt_identity()
    user = UserRepository.get_by_id(int(user_id)) if user_id else None
    if not user:
        return jsonify({"error": "User not found"}), 404

    tenant = getattr(user, 'tenant', None)
    claims = get_jwt() or {}

    if not tenant:
        # Fall back to JWT claims if DB tenant isn't available
        tenant_type = claims.get('tenant_type') or 'single'
        try:
            tenant_type = normalize_tenant_type(tenant_type)
        except ValueError:
            tenant_type = 'single'

        return jsonify({
            "tenant_id": claims.get('tenant_id'),
            "tenant_name": claims.get('tenant_name'),
            "tenant_type": tenant_type,
        }), 200

    return jsonify({
        "tenant_id": f"tenant_{tenant.id}",
        "tenant_name": tenant.name,
        "tenant_type": normalize_tenant_type(getattr(tenant, 'tenant_type', None)),
    }), 200
