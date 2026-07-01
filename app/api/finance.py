from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.mpesa_service import MpesaService
from app.services.finance_service import FinanceService
from app.utils.decorators import role_required
from app.models.user import Role
from app.utils.jwt_payload import parse_public_int_id
from app.models.finance import Buyer, Customer, SalesLedger, Transaction, TransactionType, TransactionCategory
from app import db
from sqlalchemy import func

finance_bp = Blueprint('finance', __name__)


def _pagination_params():
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get('per_page', 20))
    except (TypeError, ValueError):
        per_page = 20
    per_page = min(max(per_page, 1), 200)
    return page, per_page


def _paginate_items(items):
    page, per_page = _pagination_params()
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if total else 0}


def _serialize_customer(customer):
    return {
        'id': customer.id,
        'name': customer.name,
        'phone_number': customer.phone_number,
        'account_balance': float(customer.account_balance or 0),
        'daily_contract_liters': float(customer.daily_contract_liters or 0),
        'is_active': customer.is_active,
    }


def _serialize_transaction(tx):
    return {
        'id': tx.id,
        'transaction_type': tx.transaction_type,
        'category': tx.category,
        'amount': float(tx.amount),
        'reference_code': tx.reference_code,
        'timestamp': tx.timestamp.isoformat() if tx.timestamp else None,
        'description': tx.description,
        'customer_id': tx.customer_id,
        'recorded_by': tx.recorded_by,
    }

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


@finance_bp.route('/customers', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_customers():
    customers = Customer.query.order_by(Customer.name.asc()).all()
    q = (request.args.get('q') or '').strip().lower()
    if q:
        customers = [customer for customer in customers if q in (customer.name or '').lower() or q in (customer.phone_number or '').lower()]
    rows, meta = _paginate_items([_serialize_customer(customer) for customer in customers])
    return jsonify({'items': rows, 'meta': meta}), 200


@finance_bp.route('/customers/<int:customer_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_customer(customer_id):
    customer = db.session.get(Customer, customer_id)
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404
    return jsonify(_serialize_customer(customer)), 200


@finance_bp.route('/ledger', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_ledger():
    rows = Transaction.query.order_by(Transaction.timestamp.desc(), Transaction.id.desc()).all()
    tx_type = (request.args.get('transaction_type') or '').strip().title()
    if tx_type in {'Revenue', 'Expense'}:
        rows = [row for row in rows if row.transaction_type == tx_type]
    payload, meta = _paginate_items([_serialize_transaction(row) for row in rows])
    return jsonify({'items': payload, 'meta': meta}), 200


@finance_bp.route('/ledger', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_ledger_entry():
    data = request.get_json() or {}
    tx_type = (data.get('transaction_type') or '').strip().title()
    category = (data.get('category') or '').strip().title()
    amount = data.get('amount')
    if tx_type not in {'Revenue', 'Expense'}:
        return jsonify({'error': 'transaction_type must be Revenue or Expense.'}), 400
    if not category or amount is None:
        return jsonify({'error': 'category and amount are required.'}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': 'amount must be greater than zero.'}), 400
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a valid number.'}), 400

    tx = Transaction(
        transaction_type=tx_type,
        category=category,
        amount=amount,
        reference_code=data.get('reference_code'),
        description=data.get('description'),
        customer_id=data.get('customer_id'),
        recorded_by=int(get_jwt_identity()),
    )
    db.session.add(tx)
    db.session.commit()
    return jsonify(_serialize_transaction(tx)), 201


@finance_bp.route('/buyers', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_buyers():
    tenant_id = None
    tenant_public_id = getattr(g, 'tenant_id', None)
    if tenant_public_id:
        try:
            tenant_id = parse_public_int_id(tenant_public_id, 'tenant_')
        except (TypeError, ValueError):
            tenant_id = None
    rows = Buyer.query.filter_by(tenant_id=tenant_id).order_by(Buyer.name.asc()).all() if tenant_id else Buyer.query.order_by(Buyer.name.asc()).all()
    q = (request.args.get('q') or '').strip().lower()
    if q:
        rows = [row for row in rows if q in (row.name or '').lower()]
    payload = [{
        'id': row.id,
        'name': row.name,
        'agreed_rate_per_liter': float(row.agreed_rate_per_liter),
        'is_active': row.is_active,
        'tenant_id': row.tenant_id,
    } for row in rows]
    payload, meta = _paginate_items(payload)
    return jsonify({'items': payload, 'meta': meta}), 200


@finance_bp.route('/buyers', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_buyer():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name or data.get('agreed_rate_per_liter') is None:
        return jsonify({'error': 'name and agreed_rate_per_liter are required.'}), 400
    tenant_id = None
    tenant_public_id = getattr(g, 'tenant_id', None)
    if tenant_public_id:
        tenant_id = parse_public_int_id(tenant_public_id, 'tenant_')
    buyer = Buyer(
        tenant_id=tenant_id,
        name=name,
        agreed_rate_per_liter=data.get('agreed_rate_per_liter'),
        is_active=bool(data.get('is_active', True)),
    )
    db.session.add(buyer)
    db.session.commit()
    return jsonify({'id': buyer.id, 'name': buyer.name}), 201


@finance_bp.route('/buyers/<int:buyer_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_buyer(buyer_id):
    buyer = db.session.get(Buyer, buyer_id)
    if not buyer:
        return jsonify({'error': 'Buyer not found.'}), 404
    return jsonify({'id': buyer.id, 'name': buyer.name, 'agreed_rate_per_liter': float(buyer.agreed_rate_per_liter), 'is_active': buyer.is_active, 'tenant_id': buyer.tenant_id}), 200


@finance_bp.route('/buyers/<int:buyer_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_buyer(buyer_id):
    buyer = db.session.get(Buyer, buyer_id)
    if not buyer:
        return jsonify({'error': 'Buyer not found.'}), 404
    data = request.get_json() or {}
    if 'name' in data:
        buyer.name = (data.get('name') or '').strip() or buyer.name
    if 'agreed_rate_per_liter' in data:
        buyer.agreed_rate_per_liter = data.get('agreed_rate_per_liter')
    if 'is_active' in data:
        buyer.is_active = bool(data.get('is_active'))
    db.session.commit()
    return jsonify({'id': buyer.id, 'name': buyer.name, 'agreed_rate_per_liter': float(buyer.agreed_rate_per_liter), 'is_active': buyer.is_active, 'tenant_id': buyer.tenant_id}), 200


@finance_bp.route('/customers', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_customer():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    phone_number = (data.get('phone_number') or '').strip()
    if not name or not phone_number:
        return jsonify({'error': 'name and phone_number are required.'}), 400
    customer = Customer(
        name=name,
        phone_number=phone_number,
        account_balance=data.get('account_balance', 0),
        daily_contract_liters=data.get('daily_contract_liters', 0),
        is_active=bool(data.get('is_active', True)),
    )
    db.session.add(customer)
    db.session.commit()
    return jsonify(_serialize_customer(customer)), 201


@finance_bp.route('/statements/<token>', methods=['GET'])
def get_statement(token):
    customer = Customer.query.filter_by(phone_number=token).first()
    if not customer:
        return jsonify({'error': 'Statement token invalid.'}), 404
    rows = Transaction.query.filter_by(customer_id=customer.id).order_by(Transaction.timestamp.desc()).all()
    return jsonify({'customer': _serialize_customer(customer), 'transactions': [_serialize_transaction(row) for row in rows]}), 200

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