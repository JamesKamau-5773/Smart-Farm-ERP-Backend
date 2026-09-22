from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required

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


@breeding_bp.route('/heat-observations', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def record_heat_observation():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400
    return BreedingService.record_heat_observation(tenant_id, get_jwt_identity(), request.get_json() or {})


@breeding_bp.route('/heat-observations', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_heat_observations():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400
    return BreedingService.list_heat_observations(tenant_id, request.args.get('cow_id'))


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


@breeding_bp.route('/calving', methods=['POST'])
@breeding_bp.route('/cows/<int:cow_id>/calving', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def record_calving(cow_id=None):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    cow_identifier = cow_id or data.get('cow_id') or data.get('cowId') or data.get('animal_id')
    if not cow_identifier:
        return jsonify({"error": "cow_id is required."}), 400

    created_by = get_jwt_identity()
    try:
        created_by = int(created_by) if created_by is not None else None
    except (TypeError, ValueError):
        created_by = None

    from app.services.calving_service import CalvingService
    response_payload, status_code = CalvingService.record_calving(
        tenant_id=tenant_id,
        cow_id_or_tag=cow_identifier,
        data=data,
        user_id=created_by,
    )
    return jsonify(response_payload), status_code
