from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity

from app.models.user import Role
from app.repositories.user_repo import UserRepository
from app.services.cooperative_service import CooperativeService
from app.utils.decorators import role_required
from app.utils.jwt_payload import normalize_tenant_type


tenant_bp = Blueprint('tenant', __name__)


def _member_manager(target_tenant_id=None):
    user_id = get_jwt_identity()
    user = UserRepository.get_by_id(int(user_id)) if user_id else None
    if not user:
        return None, (jsonify({'error': 'User not found.'}), 404)

    role = (user.role or '').strip().upper()
    tenant = getattr(user, 'tenant', None)
    is_single_farm_owner = role == Role.FARMER and normalize_tenant_type(getattr(tenant, 'tenant_type', None)) == 'single'
    if role not in {Role.SUPER_ADMIN, Role.ADMIN, Role.FARM_ADMIN} and not is_single_farm_owner:
        return None, (jsonify({'error': 'Member administration access is required.'}), 403)

    if target_tenant_id is not None:
        try:
            target_pk = int(str(target_tenant_id).replace('tenant_', '').strip())
        except (TypeError, ValueError):
            return None, (jsonify({'error': 'Invalid tenant id.'}), 400)

        if role != Role.SUPER_ADMIN and user.tenant_id != target_pk:
            return None, (jsonify({'error': 'Cannot manage members in another tenant.'}), 403)

    return user, None


def _assignable_roles_for(user):
    roles = set(Role.assignable_tenant_member_roles())
    if user.role == Role.FARM_ADMIN:
        roles.discard(Role.FARM_ADMIN)
    return roles


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
def invite_member(cooperative_id):
    user, error = _member_manager(cooperative_id)
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return CooperativeService.invite_member(cooperative_id, data, _assignable_roles_for(user))


@tenant_bp.route('/cooperatives/<cooperative_id>/members/bulk', methods=['POST'])
@jwt_required()
def import_members_csv(cooperative_id):
    user, error = _member_manager(cooperative_id)
    if error:
        return error
    file_storage = request.files.get('file') or request.files.get('csv_file')
    return CooperativeService.import_members_from_csv(cooperative_id, file_storage, _assignable_roles_for(user))


@tenant_bp.route('/members/invite', methods=['POST'])
@jwt_required()
def invite_current_tenant_member():
    user, error = _member_manager()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    return CooperativeService.invite_member(user.tenant_id, data, _assignable_roles_for(user))


@tenant_bp.route('/members/import', methods=['POST'])
@tenant_bp.route('/members/import-csv', methods=['POST'])
@jwt_required()
def import_current_tenant_members_csv():
    user, error = _member_manager()
    if error:
        return error
    file_storage = request.files.get('file') or request.files.get('csv_file')
    return CooperativeService.import_members_from_csv(user.tenant_id, file_storage, _assignable_roles_for(user))
