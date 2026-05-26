from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.medical_service import MedicalService
from app.services.vet_visit_service import VetVisitService
from app.utils.decorators import role_required
from app.models.user import Role
from app.utils.jwt_payload import parse_public_int_id

clinical_bp = Blueprint('clinical', __name__)


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None

@clinical_bp.route('/cows/<int:cow_id>/medical', methods=['POST'])
@clinical_bp.route('/livestock/<int:cow_id>/medical', methods=['POST'])
@jwt_required()
@role_required(Role.VET)
def log_vet_visit(cow_id):
    """Only Veterinary Doctors can log clinical diagnoses."""
    vet_id = get_jwt_identity()
    data = request.get_json()
    return MedicalService.log_clinical_visit(cow_id, vet_id, data)

@clinical_bp.route('/cows/<int:cow_id>/hardlock', methods=['PUT'])
@clinical_bp.route('/livestock/<int:cow_id>/hardlock', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER)
def toggle_farmer_hardlock(cow_id):
    """Only Farmers can lock/unlock milk for commercial distribution."""
    data = request.get_json()
    
    if 'is_locked' not in data:
        return jsonify({"error": "is_locked boolean parameter is required."}), 400
        
    is_locked = bool(data.get('is_locked'))
    user_id = get_jwt_identity()
    ip_address = request.remote_addr
    return MedicalService.enforce_hardlock(cow_id, is_locked, user_id, ip_address)


@clinical_bp.route('/vet-visits', methods=['POST'])
@jwt_required()
@role_required(Role.VET)
def log_vet_visit_workflow():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    vet_id = get_jwt_identity()
    data = request.get_json() or {}
    return VetVisitService.log_visit(tenant_id, vet_id, data)


@clinical_bp.route('/vet-visits', methods=['GET'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def list_vet_visits_workflow():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return VetVisitService.list_visits(tenant_id)


@clinical_bp.route('/vet-visits/<int:visit_id>/follow-up/schedule', methods=['PUT'])
@jwt_required()
@role_required(Role.VET)
def schedule_vet_follow_up(visit_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return VetVisitService.schedule_follow_up(tenant_id, visit_id, data)


@clinical_bp.route('/vet-visits/<int:visit_id>/follow-up/complete', methods=['PUT'])
@jwt_required()
@role_required(Role.VET)
def complete_vet_follow_up(visit_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return VetVisitService.complete_follow_up(tenant_id, visit_id, data)


@clinical_bp.route('/vet-visits/follow-ups/pending', methods=['GET'])
@jwt_required()
@role_required(Role.VET, Role.FARMER)
def list_pending_vet_follow_ups():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return VetVisitService.list_pending_follow_ups(tenant_id)