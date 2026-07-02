from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from app.models.user import Role
from app.repositories.user_repo import UserRepository
from app.services.cooperative_service import CooperativeService
from app.utils.decorators import role_required
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
            "cooperative_id": claims.get('cooperative_id') or claims.get('tenant_id'),
            "tenant_name": claims.get('tenant_name'),
            "cooperative_name": claims.get('cooperative_name') or claims.get('tenant_name'),
            "tenant_type": tenant_type,
        }), 200

    return jsonify({
        "tenant_id": f"tenant_{tenant.id}",
        "cooperative_id": f"tenant_{tenant.id}",
        "tenant_name": tenant.name,
        "cooperative_name": tenant.name,
        "tenant_type": normalize_tenant_type(getattr(tenant, 'tenant_type', None)),
        "region": getattr(tenant, 'region', None),
        "registration_number": getattr(tenant, 'registration_number', None),
    }), 200


@tenant_bp.route('/cooperatives', methods=['POST'])
@jwt_required()
@role_required(Role.SUPER_ADMIN)
def create_cooperative():
    data = request.get_json(silent=True) or {}
    return CooperativeService.create_cooperative(data)


@tenant_bp.route('/cooperatives/<cooperative_id>/members', methods=['POST'])
@jwt_required()
@role_required(Role.ADMIN, Role.SUPER_ADMIN)
def invite_member(cooperative_id):
    data = request.get_json(silent=True) or {}
    return CooperativeService.invite_member(cooperative_id, data)


@tenant_bp.route('/cooperatives/<cooperative_id>/members/bulk', methods=['POST'])
@jwt_required()
@role_required(Role.ADMIN, Role.SUPER_ADMIN)
def import_members_csv(cooperative_id):
    file_storage = request.files.get('file') or request.files.get('csv_file')
    return CooperativeService.import_members_from_csv(cooperative_id, file_storage)
