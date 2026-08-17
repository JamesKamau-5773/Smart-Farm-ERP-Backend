from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
from app import db
from app.models.finance import Customer, Delivery, Transaction, TransactionType, TransactionCategory
from app.models.user import Role
from app.utils import get_tenant_id_from_context
from app.utils.decorators import role_required
from datetime import datetime, timezone


finance_bp = Blueprint('finance', __name__)

# ==========================================
# SERIALIZERS
# ==========================================

def _serialize_customer(customer: Customer) -> dict:
    """Serializes a Customer object for API responses, matching frontend keys."""
    return {
        'id': customer.id,
        'name': customer.name,
        'phone_number': customer.phone_number,
        'daily_contract_liters': float(getattr(customer, 'daily_contract_liters', 0.0) or 0.0),
        'agreed_rate_per_liter': float(getattr(customer, 'agreed_rate_per_liter', 0.0) or 0.0),
        'account_balance': float(getattr(customer, 'account_balance', 0.0) or 0.0),
        'is_active': (getattr(customer, 'status', None) or 'Active') == 'Active',
    }

def _serialize_delivery(delivery: Delivery) -> dict:
    """Serializes a Delivery object for API responses."""
    delivery_date = getattr(delivery, 'date', None)
    return {
        'id': delivery.id,
        'liters_delivered': float(getattr(delivery, 'liters_delivered', 0.0) or 0.0),
        'personal_consumption_liters': float(getattr(delivery, 'personal_consumption_liters', 0.0) or 0.0),
        'date': delivery_date.isoformat() if delivery_date else None,
        'billable_liters': float(getattr(delivery, 'billable_liters', 0.0) or 0.0),
        'price_per_liter': float(getattr(delivery, 'price_per_liter', 0.0) or 0.0),
        'total_price': float(getattr(delivery, 'total_price', 0.0) or 0.0),
        'notes': getattr(delivery, 'notes', ''),
    }

def _serialize_transaction(transaction_tuple) -> dict:
    """Serializes a Transaction object for API responses."""
    if isinstance(transaction_tuple, Transaction):
        transaction = transaction_tuple
        customer_name = transaction.customer.name if transaction.customer else None
    else: # It's a tuple from a join
        transaction, customer_name = transaction_tuple

    transaction_date = getattr(transaction, 'timestamp', None)
    return {
        'id': transaction.id,
        'date': transaction_date.isoformat() if transaction_date else None,
        'description': getattr(transaction, 'description', None) or 'Payment',
        'transaction_type': getattr(transaction, 'transaction_type', None) or 'CREDIT',
        'category': getattr(transaction, 'category', None),
        'reference_code': getattr(transaction, 'reference_code', None),
        'customer_name': customer_name,
        'amount': float(getattr(transaction, 'amount', 0.0) or 0.0),
    }

# ==========================================
# ENDPOINTS
# ==========================================

@finance_bp.route('/customers', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_customers():
    """Returns a paginated list of all customers for the tenant."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    customers = db.session.query(Customer).filter_by(tenant_id=tenant_id).order_by(Customer.name).all()
    items = [_serialize_customer(c) for c in customers]
    
    return jsonify({
        "items": items,
        "meta": {
            "page": 1,
            "pages": 1,
            "per_page": len(items) if len(items) > 0 else 20,
            "total": len(items)
        }
    }), 200


@finance_bp.route('/customers/<int:customer_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_customer(customer_id):
    """Returns a single customer by their ID."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400
        
    customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404
        
    return jsonify(_serialize_customer(customer)), 200


@finance_bp.route('/customers/<int:customer_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_customer(customer_id):
    """Updates a customer's details."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400
        
    customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404
        
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload.'}), 400

    # Match frontend keys directly to model attributes
    if 'daily_contract_liters' in data:
        customer.daily_contract_liters = data['daily_contract_liters']
    if 'agreed_rate_per_liter' in data:
        customer.agreed_rate_per_liter = data['agreed_rate_per_liter']
    if 'name' in data:
        customer.name = data['name']
    if 'phone_number' in data:
        customer.phone_number = data['phone_number']

    try:
        db.session.commit()
        return jsonify(_serialize_customer(customer)), 200
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Database integrity error.', 'details': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'An unexpected error occurred.', 'details': str(e)}), 500


@finance_bp.route('/deliveries', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_deliveries():
    """Returns a list of deliveries, optionally filtered by customer_id."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400
        
    customer_id = request.args.get('customer_id', type=int)
    if not customer_id:
        return jsonify({'error': 'customer_id query parameter is required.'}), 400
        
    deliveries = db.session.query(Delivery).filter_by(tenant_id=tenant_id, customer_id=customer_id).order_by(Delivery.date.desc()).all()
    items = [_serialize_delivery(d) for d in deliveries]
    
    return jsonify({
        "items": items,
        "meta": {
            "page": 1,
            "pages": 1,
            "per_page": len(items) if len(items) > 0 else 20,
            "total": len(items)
        }
    }), 200


@finance_bp.route('/ledger', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_ledger():
    """
    Returns a paginated list of transactions (ledger entries).
    If customer_id is provided, it filters for that customer.
    Otherwise, it returns all transactions for the tenant.
    """
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    customer_id = request.args.get('customer_id', type=int)

    # Start with a base query scoped to the tenant
    query = db.session.query(
        Transaction,
        Customer.name.label('customer_name')
    ).outerjoin(Customer, Transaction.customer_id == Customer.id).filter(Transaction.tenant_id == tenant_id)

    # If a customer_id is provided, add it to the filter
    if customer_id:
        query = query.filter(Transaction.customer_id == customer_id)

    # Apply ordering and pagination
    paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # The query now returns tuples of (Transaction, customer_name)
    items = [_serialize_transaction(t_tuple) for t_tuple in paginated_transactions.items]
    
    return jsonify({
        "items": items,
        "meta": {
            "page": paginated_transactions.page,
            "pages": paginated_transactions.pages,
            "per_page": paginated_transactions.per_page,
            "total": paginated_transactions.total
        }
    }), 200

@finance_bp.route('/deliveries', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def create_delivery():
    """Creates a new delivery record, updates customer balance, and logs a transaction."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400
        
    current_user_id = get_jwt_identity()

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload.'}), 400

    customer_id = data.get('customer_id')
    date_str = data.get('date')
    liters_delivered_raw = data.get('liters_delivered')
    personal_consumption_liters_raw = data.get('personal_consumption_liters', 0)
    notes = data.get('notes', '')

    # Input validation
    if not customer_id:
        return jsonify({'error': 'customer_id is required.'}), 400
    if not date_str:
        return jsonify({'error': 'date is required.'}), 400
    if liters_delivered_raw is None:
        return jsonify({'error': 'customer_id, date, and liters_delivered are required.'}), 400

    try:
        customer_id = int(customer_id)
        liters_delivered = Decimal(str(liters_delivered_raw))
        personal_consumption_liters = Decimal(str(personal_consumption_liters_raw))
        
        if liters_delivered <= 0:
            return jsonify({'error': 'liters_delivered must be greater than 0.'}), 400
        if personal_consumption_liters < 0:
            return jsonify({'error': 'personal_consumption_liters cannot be negative.'}), 400
        if personal_consumption_liters > liters_delivered:
            return jsonify({'error': 'personal_consumption_liters cannot exceed liters_delivered.'}), 400
    except (TypeError, ValueError, ArithmeticError):
        return jsonify({'error': 'customer_id, liters_delivered, and personal_consumption_liters must be valid numbers.'}), 400

    try:
        delivery_date = datetime.fromisoformat(date_str).date()
    except ValueError:
        return jsonify({'error': 'date must be in YYYY-MM-DD format.'}), 400

    customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).with_for_update().first()
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404

    # Calculate billable liters and total price
    billable_liters = liters_delivered - personal_consumption_liters
    price_per_liter = customer.agreed_rate_per_liter or Decimal('0.0')
    total_price = billable_liters * price_per_liter

    # Create Delivery record
    delivery = Delivery(
        tenant_id=tenant_id, customer_id=customer_id, date=delivery_date,
        liters_delivered=liters_delivered, personal_consumption_liters=personal_consumption_liters,
        billable_liters=billable_liters, price_per_liter=price_per_liter,
        total_price=total_price, notes=notes
    )
    db.session.add(delivery)

    # Create Transaction record for the delivery (customer owes money, so it's a DEBIT)
    transaction = Transaction(
        tenant_id=tenant_id, 
        customer_id=customer_id, 
        transaction_type=TransactionType.DEBIT,
        category=TransactionCategory.MILK_SALE, 
        amount=total_price,
        description=f"Milk delivery on {delivery_date.isoformat()} ({liters_delivered}L delivered, {billable_liters}L billed)",
        timestamp=datetime.now(timezone.utc),
        recorded_by=current_user_id
    )
    db.session.add(transaction)

    # Update customer's account balance
    customer.account_balance = (customer.account_balance or Decimal('0.0')) + total_price

    try:
        db.session.commit()
        return jsonify(_serialize_delivery(delivery)), 201
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Database integrity error.', 'details': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'An unexpected error occurred.', 'details': str(e)}), 500