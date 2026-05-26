from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required

from app.models.user import Role
from app.services.breeding_service import BreedingService
from app.utils.decorators import role_required, require_tenant_context
from app.utils.jwt_payload import parse_public_int_id
from flask_jwt_extended import get_jwt

breeding_bp = Blueprint('breeding', __name__)


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@breeding_bp.route('/insemination/<int:log_id>/outcome', methods=['PATCH'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.VET)
def update_insemination_outcome(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.update_insemination_outcome(tenant_id, log_id, data)
