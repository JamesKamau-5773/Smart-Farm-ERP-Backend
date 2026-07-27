from flask import Blueprint, request, jsonify
from app.services.mpesa_service import MpesaService
from app.models.finance import Customer, Transaction
from app import db

webhooks_bp = Blueprint('webhooks', __name__)


def _serialize_customer(customer):
    """Helper to serialize customer data. In a larger refactor, this could be shared."""
    return {
        'id': customer.id,
        'name': customer.name,
        'phone_number': customer.phone_number,
        'account_balance': float(customer.account_balance or 0),
        'daily_contract_liters': float(customer.daily_contract_liters or 0),
        'is_active': customer.is_active,
    }


def _serialize_transaction(tx):
    """Helper to serialize transaction data. In a larger refactor, this could be shared."""
    return {
        'id': tx.id,
        'transaction_type': tx.transaction_type,
        'category': tx.category,
        'amount': float(tx.amount),
        'reference_code': tx.reference_code,
        'timestamp': tx.timestamp.isoformat() if tx.timestamp else None,
        'date': tx.timestamp.date().isoformat() if tx.timestamp else None,
        'description': tx.description,
        'customer_id': tx.customer_id,
        'recorded_by': tx.recorded_by,
    }


@webhooks_bp.route('/statements/<token>', methods=['GET'])
def get_statement(token):
    customer = Customer.query.filter_by(phone_number=token).first()
    if not customer:
        return jsonify({'error': 'Statement token invalid.'}), 404
    rows = Transaction.query.filter_by(customer_id=customer.id).order_by(Transaction.timestamp.desc()).all()
    return jsonify({'customer': _serialize_customer(customer), 'transactions': [_serialize_transaction(row) for row in rows]}), 200


@webhooks_bp.route('/mpesa/callback', methods=['POST'])
def mpesa_callback():
    """
    Public webhook endpoint for Safaricom Daraja.
    Requires NO authentication, as Safaricom cannot pass our JWT.
    """
    payload = request.get_json()

    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    MpesaService.process_stk_callback(payload)

    safaricom_acknowledgement = {
        "ResultCode": 0,
        "ResultDesc": "Confirmation Received Successfully"
    }
    return jsonify(safaricom_acknowledgement), 200