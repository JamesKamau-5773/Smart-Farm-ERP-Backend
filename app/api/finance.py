from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required
from app.services.mpesa_service import MpesaService
from app.services.finance_service import FinanceService
from app.utils.decorators import role_required
from app.models.user import Role

finance_bp = Blueprint('finance', __name__)

@finance_bp.route('/unit-cost', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_unit_cost():
    """Retrieves the real-time cost of production per liter."""
    # Target date can be passed as a query parameter in future iterations
    return FinanceService.calculate_daily_unit_cost()

@finance_bp.route('/billing/stk-push', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def trigger_billing():
    """Initiates an M-Pesa STK Push to a customer."""
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    amount = data.get('amount')
    account_reference = data.get('account_reference', 'JivuMilk')
    description = data.get('description', 'Monthly Bill')

    if not phone_number or not amount:
        return jsonify({"error": "phone_number and amount are required."}), 400

    try:
        amount_int = int(amount)
        if amount_int <= 0:
            return jsonify({"error": "Amount must be greater than zero."}), 400
    except ValueError:
        return jsonify({"error": "Amount must be a valid number."}), 400

    return MpesaService.initiate_stk_push(phone_number, amount_int, account_reference, description)