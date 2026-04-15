from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.production_service import ProductionService
from app.utils.decorators import role_required
from app.models.user import Role

operations_bp = Blueprint('operations', __name__)

@operations_bp.route('/cows/<int:cow_id>/milk', methods=['POST'])
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