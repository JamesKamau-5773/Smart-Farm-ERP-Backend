from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.medical_service import MedicalService
from app.utils.decorators import role_required
from app.models.user import Role

clinical_bp = Blueprint('clinical', __name__)

@clinical_bp.route('/cows/<int:cow_id>/medical', methods=['POST'])
@jwt_required()
@role_required(Role.VET)
def log_vet_visit(cow_id):
    """Only Veterinary Doctors can log clinical diagnoses."""
    vet_id = get_jwt_identity()
    data = request.get_json()
    return MedicalService.log_clinical_visit(cow_id, vet_id, data)

@clinical_bp.route('/cows/<int:cow_id>/hardlock', methods=['PUT'])
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