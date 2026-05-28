from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required
from app.services.mpesa_service import MpesaService
from app.services.finance_service import FinanceService
from app.utils.decorators import role_required
from app.models.user import Role
from app.utils.jwt_payload import parse_public_int_id

finance_bp = Blueprint('finance', __name__)

@finance_bp.route('/unit-cost', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_unit_cost():
    """Retrieves the real-time cost of production per liter."""
    # Target date can be passed as a query parameter in future iterations
    tenant_id = None
    tenant_public_id = getattr(g, 'tenant_id', None)
    if tenant_public_id:
        try:
            tenant_id = parse_public_int_id(tenant_public_id, 'tenant_')
        except (TypeError, ValueError):
            tenant_id = None

    return FinanceService.calculate_daily_unit_cost(tenant_id=tenant_id)

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


@finance_bp.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    """
    Public webhook endpoint for Safaricom Daraja.
    Requires NO authentication, as Safaricom cannot pass our JWT.
    """
    payload = request.get_json()
    
    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    # Process the transaction asynchronously or directly
    MpesaService.process_stk_callback(payload)

    # CRITICAL: Always acknowledge receipt to Safaricom immediately
    safaricom_acknowledgement = {
        "ResultCode": 0,
        "ResultDesc": "Confirmation Received Successfully"
    }
    
    return jsonify(safaricom_acknowledgement), 200