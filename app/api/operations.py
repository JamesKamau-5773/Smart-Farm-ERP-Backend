from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.services.production_service import ProductionService
from app.services.breeding_service import BreedingService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.user import Role

operations_bp = Blueprint('operations', __name__)


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None

@operations_bp.route('/cows/<int:cow_id>/milk', methods=['POST'])
@operations_bp.route('/livestock/<int:cow_id>/milk', methods=['POST'])
@jwt_required()
@role_required(Role.FARM_HAND, Role.FARMER) # Only Farm Hands and Farmer log the daily yield
def log_milk(cow_id):
    user_id = get_jwt_identity()
    data = request.get_json()
    
    amount = data.get('amount')
    session = data.get('session') # e.g., 'Morning' or 'Evening'
    
    if not amount or not session:
        return jsonify({"error": "Amount and Session parameters are required."}), 400
        
    try:
        amount_float = float(amount)
        if amount_float <= 0:
             return jsonify({"error": "Amount must be greater than 0."}), 400
    except ValueError:
        return jsonify({"error": "Amount must be a valid number."}), 400

    return ProductionService.log_daily_yield(cow_id, amount_float, session, user_id)


@operations_bp.route('/semen-inventory', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def add_semen_inventory():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.add_semen_inventory(tenant_id, data)


@operations_bp.route('/semen-inventory', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET, Role.FARM_HAND)
def list_semen_inventory():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    return BreedingService.list_semen_inventory(tenant_id)


@operations_bp.route('/breeding-logs', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def log_insemination():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.log_insemination(tenant_id, data)


@operations_bp.route('/breeding-logs/<int:log_id>/status', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def update_insemination_status(log_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    data = request.get_json() or {}
    return BreedingService.update_breeding_status(tenant_id, log_id, data)


@operations_bp.route('/breeding/performance', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.VET)
def get_bull_performance_summary():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant in token."}), 400

    return BreedingService.bull_performance_summary(tenant_id)