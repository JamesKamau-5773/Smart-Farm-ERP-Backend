from __future__ import annotations

import hashlib
import io

from flask import Blueprint, g, request, jsonify, render_template, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from decimal import Decimal, InvalidOperation
from app import db
from app.models.finance import Buyer, CostClass, Customer, Delivery, ReceiptAuditLog, SalesLedger, Transaction, TransactionStatus, TransactionType, TransactionCategory
from app.models.user import Role
from app.services.payment_service import PaymentService
from app.services.ledger_correction_service import LedgerCorrectionService
from app.services.buyer_service import BuyerService
from app.services.animal_cost_allocation_service import AnimalCostAllocationService
from app.services.receipt_service import ReceiptService
from app.utils import get_tenant_id_from_context
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from datetime import datetime, timezone
from weasyprint import HTML


finance_bp = Blueprint('finance', __name__)


DEFAULT_COST_CLASS_BY_CATEGORY = {
    TransactionCategory.FEED_PURCHASE: CostClass.COGS,
    TransactionCategory.VET_FEES: CostClass.COGS,
    TransactionCategory.LABOR_WAGES: CostClass.COGS,
    TransactionCategory.UTILITIES: CostClass.COGS,
    TransactionCategory.INVENTORY_WRITE_OFF: CostClass.COGS,
    TransactionCategory.EQUIPMENT_MAINTENANCE: CostClass.OPERATING,
    TransactionCategory.TRANSPORT: CostClass.OPERATING,
    TransactionCategory.OPENING_BALANCE: CostClass.OPERATING,
    TransactionCategory.OTHER: CostClass.OPERATING,
}


def _current_farm_id():
    value = getattr(g, 'farm_id', None)
    if value is None:
        return None
    try:
        return parse_public_int_id(str(value), 'farm_')
    except (TypeError, ValueError):
        return None


def _parse_optional_integer(value, field_name: str) -> int | None:
    if value in (None, ''):
        return None
    if isinstance(value, bool):
        raise ValueError(f'{field_name} must be a valid integer.')
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError(f'{field_name} must be a valid integer.')

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
        buyer = db.session.get(Buyer, transaction.buyer_id) if transaction.buyer_id else None
        buyer_name = buyer.name if buyer else None
    else: # It's a tuple from a join
        transaction, customer_name, buyer_name = transaction_tuple

    transaction_date = getattr(transaction, 'timestamp', None)
    counterparty_name = customer_name or buyer_name or transaction.counterparty_name
    receipt = transaction.receipt
    animal_cost_allocation = transaction.animal_cost_allocation
    return {
        'id': transaction.id,
        'date': transaction_date.isoformat() if transaction_date else None,
        'timestamp': transaction_date.isoformat() if transaction_date else None,
        'item_name': transaction.item_name,
        'quantity': float(transaction.quantity) if transaction.quantity is not None else None,
        'cost_class': transaction.cost_class.value if transaction.cost_class is not None else None,
        'description': getattr(transaction, 'description', None) or 'Payment',
        'transaction_type': getattr(transaction, 'transaction_type', None) or 'CREDIT',
        'category': getattr(transaction, 'category', None),
        'reference_code': getattr(transaction, 'reference_code', None),
        'customer_id': transaction.customer_id,
        'customer_name': customer_name,
        'buyer_id': transaction.buyer_id,
        'buyer_name': buyer_name,
        'counterparty_name': counterparty_name,
        'payment_method': transaction.payment_method,
        'status': transaction.status,
        'voided_at': transaction.voided_at.isoformat() if transaction.voided_at else None,
        'voided_by': transaction.voided_by,
        'void_reason': transaction.void_reason,
        'corrected_from_transaction_id': transaction.corrected_from_transaction_id,
        'replacement_transaction_id': transaction.correction_replacement.id if transaction.correction_replacement else None,
        'farm_id': transaction.farm_id,
        'amount': float(getattr(transaction, 'amount', 0.0) or 0.0),
        'animal_cost_allocation': {
            'cow_id': animal_cost_allocation.cow_id,
            'cost_type': animal_cost_allocation.cost_type.value,
            'attribution_method': animal_cost_allocation.attribution_method,
        } if animal_cost_allocation else None,
        'receipt_available': receipt is not None,
        'receipt': {
            'id': receipt.id,
            'receipt_number': receipt.receipt_number,
            'issued_at': receipt.issued_at.isoformat(),
        } if receipt else None,
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


@finance_bp.route('/customers/<int:customer_id>/payments', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def record_customer_payment(customer_id):
    """Records cash received separately from milk sales and delivery corrections."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    data = request.get_json() or {}
    payment_timestamp = datetime.now(timezone.utc)
    if data.get('date'):
        try:
            payment_date = datetime.fromisoformat(data['date']).date()
            payment_timestamp = datetime.combine(payment_date, payment_timestamp.timetz())
        except (TypeError, ValueError):
            return jsonify({'error': 'date must be in YYYY-MM-DD format.'}), 400
    try:
        customer, transaction = PaymentService.record_customer_payment(
            tenant_id=tenant_id,
            customer_id=customer_id,
            amount=data.get('amount'),
            reference_code=data.get('reference_code'),
            recorded_by=get_jwt_identity(),
            description=data.get('note'),
            payment_method=data.get('payment_method'),
            timestamp=payment_timestamp,
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'reference_code has already been recorded'}), 409

    return jsonify({
        'customer': _serialize_customer(customer),
        'transaction': _serialize_transaction(transaction),
    }), 201


@finance_bp.route('/buyers/<int:buyer_id>/payments', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def record_buyer_payment(buyer_id):
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400
    data = request.get_json() or {}
    try:
        result = BuyerService.allocate_payment(
            buyer_id=buyer_id,
            tenant_id=tenant_id,
            amount=data.get('amount'),
            note=data.get('note'),
            reference_code=data.get('reference_code'),
            recorded_by=int(get_jwt_identity()),
        )
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'reference_code has already been recorded'}), 409
    return jsonify({
        'buyer': BuyerService.serialize_buyer(result['buyer']),
        'transaction': _serialize_transaction(result['transaction']),
        'payment': {
            'amount': float(result['transaction'].amount),
            'applied_amount': result['applied_amount'],
            'previous_balance': result['previous_balance'],
            'current_balance': result['current_balance'],
            'allocations': result['allocations'],
        },
    }), 201


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
    Return ledger entries and authoritative accounting summaries for one scope.

    Account scope can be selected explicitly with account_type/account_id (or
    legacy customer_id), or by matching customer/buyer names with search_query.
    """
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    farm_id = _current_farm_id()
    search_query = str(request.args.get('search_query') or '').strip()
    account_type = str(request.args.get('account_type') or '').strip().lower()
    account_id_raw = request.args.get('account_id')
    legacy_customer_id = request.args.get('customer_id')

    if legacy_customer_id not in (None, ''):
        if account_type or account_id_raw not in (None, ''):
            return jsonify({'error': 'Use either customer_id or account_type/account_id, not both.'}), 400
        account_type = 'customer'
        account_id_raw = legacy_customer_id
    if search_query and (account_type or account_id_raw not in (None, '')):
        return jsonify({'error': 'Use either search_query or an explicit account scope, not both.'}), 400
    if bool(account_type) != (account_id_raw not in (None, '')):
        return jsonify({'error': 'account_type and account_id must be provided together.'}), 400
    if account_type and account_type not in ('customer', 'buyer'):
        return jsonify({'error': 'account_type must be customer or buyer.'}), 400

    account_id = None
    if account_id_raw not in (None, ''):
        try:
            account_id = _parse_optional_integer(account_id_raw, 'account_id')
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    customer_ids = None
    buyer_ids = None
    scope_mode = 'all'
    if account_type == 'customer':
        customer = Customer.query.filter_by(id=account_id, tenant_id=tenant_id).first()
        if not customer:
            return jsonify({'error': 'Customer not found.'}), 404
        customer_ids, buyer_ids, scope_mode = [customer.id], [], 'account'
    elif account_type == 'buyer':
        buyer_query = Buyer.query.filter_by(id=account_id, tenant_id=tenant_id)
        if farm_id is not None:
            buyer_query = buyer_query.filter(Buyer.farm_id == farm_id)
        buyer = buyer_query.first()
        if not buyer:
            return jsonify({'error': 'Buyer not found.'}), 404
        customer_ids, buyer_ids, scope_mode = [], [buyer.id], 'account'
    elif search_query:
        customer_ids = [row[0] for row in db.session.query(Customer.id).filter(
            Customer.tenant_id == tenant_id,
            Customer.name.ilike(f'%{search_query}%'),
        ).all()]
        buyer_search = db.session.query(Buyer.id).filter(
            Buyer.tenant_id == tenant_id,
            Buyer.name.ilike(f'%{search_query}%'),
        )
        if farm_id is not None:
            buyer_search = buyer_search.filter(Buyer.farm_id == farm_id)
        buyer_ids = [row[0] for row in buyer_search.all()]
        scope_mode = 'search'

    def apply_account_scope(scoped_query):
        if customer_ids is None and buyer_ids is None:
            return scoped_query
        account_predicates = []
        if customer_ids:
            account_predicates.append(Transaction.customer_id.in_(customer_ids))
        if buyer_ids:
            account_predicates.append(Transaction.buyer_id.in_(buyer_ids))
        return scoped_query.filter(or_(*account_predicates)) if account_predicates else scoped_query.filter(False)

    # Start with a base query scoped to the tenant
    query = db.session.query(
        Transaction,
        Customer.name.label('customer_name'),
        Buyer.name.label('buyer_name'),
    ).outerjoin(
        Customer, Transaction.customer_id == Customer.id
    ).outerjoin(
        Buyer, Transaction.buyer_id == Buyer.id
    ).filter(Transaction.tenant_id == tenant_id)

    if farm_id is not None:
        query = query.filter(Transaction.farm_id == farm_id)
    query = apply_account_scope(query)

    # Apply ordering and pagination
    paginated_transactions = query.order_by(Transaction.timestamp.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    # The query now returns tuples of (Transaction, customer_name)
    items = [_serialize_transaction(t_tuple) for t_tuple in paginated_transactions.items]

    recognized_income = case(
        (Transaction.transaction_type.in_((TransactionType.REVENUE, TransactionType.DEBIT)), Transaction.amount),
        (Transaction.transaction_type == TransactionType.CREDIT, -Transaction.amount),
        else_=0,
    )
    totals_query = db.session.query(
        func.coalesce(func.sum(case(
            (Transaction.status == TransactionStatus.POSTED.value, recognized_income),
            else_=0,
        )), 0),
        func.coalesce(func.sum(case(
            (
                (Transaction.transaction_type == TransactionType.EXPENSE)
                & (Transaction.status == TransactionStatus.POSTED.value),
                Transaction.amount,
            ),
            else_=0,
        )), 0),
        func.count(Transaction.id),
    ).filter(Transaction.tenant_id == tenant_id)
    if farm_id is not None:
        totals_query = totals_query.filter(Transaction.farm_id == farm_id)
    totals_query = apply_account_scope(totals_query)
    totals = totals_query.one()
    total_income, total_costs, transaction_count = totals

    customer_balances = db.session.query(
        func.coalesce(func.sum(case((Customer.account_balance > 0, Customer.account_balance), else_=0)), 0),
        func.coalesce(func.sum(case((Customer.account_balance < 0, -Customer.account_balance), else_=0)), 0),
    ).filter(Customer.tenant_id == tenant_id)
    if customer_ids is not None:
        customer_balances = customer_balances.filter(Customer.id.in_(customer_ids)) if customer_ids else customer_balances.filter(False)
    customer_receivables, customer_credit = customer_balances.one()

    buyer_receivables = db.session.query(
        func.coalesce(func.sum(case((SalesLedger.total_cost > 0, SalesLedger.total_cost), else_=0)), 0)
    ).join(Buyer, Buyer.id == SalesLedger.buyer_id).filter(
        SalesLedger.tenant_id == tenant_id,
        Buyer.tenant_id == tenant_id,
    )
    if farm_id is not None:
        buyer_receivables = buyer_receivables.filter(Buyer.farm_id == farm_id)
    if buyer_ids is not None:
        buyer_receivables = buyer_receivables.filter(Buyer.id.in_(buyer_ids)) if buyer_ids else buyer_receivables.filter(False)
    buyer_receivables = buyer_receivables.scalar() or Decimal('0')
    outstanding_receivables = customer_receivables + buyer_receivables

    return jsonify({
        "items": items,
        "summary": {
            "recognized_sales": float(total_income),
            "outstanding_receivables": float(outstanding_receivables),
            "customer_credit": float(customer_credit),
            "posted_costs": float(total_costs),
            "net_profit": float(total_income - total_costs),
            "ledger_records": transaction_count,
            "total_income": float(total_income),
            "total_costs": float(total_costs),
            "total_profit": float(total_income - total_costs),
            "transaction_count": transaction_count,
        },
        "summary_scope": {
            "mode": scope_mode,
            "account_type": account_type or None,
            "account_id": account_id,
            "search_query": search_query or None,
            "matched_customer_ids": customer_ids,
            "matched_buyer_ids": buyer_ids,
            "customer_balance_scope": "tenant",
        },
        "meta": {
            "page": paginated_transactions.page,
            "pages": paginated_transactions.pages,
            "per_page": paginated_transactions.per_page,
            "total": paginated_transactions.total
        }
    }), 200


@finance_bp.route('/ledger', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def create_ledger_entry():
    """Records money entering or leaving the farm."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    data = request.get_json() or {}
    try:
        transaction_type = TransactionType(data.get('transaction_type'))
    except (TypeError, ValueError):
        return jsonify({'error': 'transaction_type must be Revenue or Expense.'}), 400

    if transaction_type not in (TransactionType.REVENUE, TransactionType.EXPENSE):
        return jsonify({'error': 'Ledger entries must be Revenue or Expense.'}), 400

    try:
        category = TransactionCategory(data.get('category'))
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid transaction category.'}), 400

    allowed_categories = {
        TransactionType.REVENUE: {
            TransactionCategory.MILK_SALE,
            TransactionCategory.LIVESTOCK_SALE,
            TransactionCategory.OTHER_INCOME,
            TransactionCategory.OTHER,
        },
        TransactionType.EXPENSE: {
            TransactionCategory.FEED_PURCHASE,
            TransactionCategory.VET_FEES,
            TransactionCategory.LABOR_WAGES,
            TransactionCategory.UTILITIES,
            TransactionCategory.EQUIPMENT_MAINTENANCE,
            TransactionCategory.TRANSPORT,
            TransactionCategory.OPENING_BALANCE,
            TransactionCategory.INVENTORY_WRITE_OFF,
            TransactionCategory.OTHER,
        },
    }
    if category not in allowed_categories[transaction_type]:
        return jsonify({'error': f'{category.value} is not valid for {transaction_type.value} records.'}), 400

    cost_class = None
    if data.get('cost_class') not in (None, ''):
        try:
            cost_class = CostClass(data['cost_class'])
        except (TypeError, ValueError):
            return jsonify({'error': 'cost_class must be COGS, CUSTOMER_ACQUISITION, OPERATING, or CAPITAL.'}), 400
    if transaction_type == TransactionType.REVENUE and cost_class is not None:
        return jsonify({'error': 'cost_class is only valid for expense records.'}), 400
    if transaction_type == TransactionType.EXPENSE and cost_class is None:
        cost_class = DEFAULT_COST_CLASS_BY_CATEGORY[category]

    try:
        amount = Decimal(str(data.get('amount')))
    except (InvalidOperation, TypeError, ValueError):
        return jsonify({'error': 'amount must be a valid number.'}), 400
    if not amount.is_finite() or amount <= 0:
        return jsonify({'error': 'amount must be greater than 0.'}), 400

    customer = None
    buyer = None
    try:
        customer_id = _parse_optional_integer(data.get('customer_id'), 'customer_id')
        buyer_id = _parse_optional_integer(data.get('buyer_id'), 'buyer_id')
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    if customer_id is not None:
        customer = db.session.query(Customer).filter_by(
            id=customer_id, tenant_id=tenant_id
        ).first()
        if not customer:
            return jsonify({'error': 'Customer not found.'}), 404
    if buyer_id is not None:
        buyer = db.session.query(Buyer).filter_by(
            id=buyer_id, tenant_id=tenant_id
        ).first()
        if not buyer:
            return jsonify({'error': 'Buyer not found.'}), 404
    if customer and buyer:
        return jsonify({'error': 'Choose either a customer or a buyer, not both.'}), 400
    if transaction_type == TransactionType.EXPENSE and (customer or buyer):
        return jsonify({'error': 'Expense records must use paid_to instead of a customer or buyer.'}), 400
    if transaction_type == TransactionType.REVENUE and (customer or buyer):
        return jsonify({
            'error': 'Customer and buyer payments must be recorded through their payment endpoints, not as revenue.',
        }), 400

    supplied_counterparty = (
        data.get('paid_to')
        if transaction_type == TransactionType.EXPENSE
        else data.get('income_source')
    )
    counterparty_name = str(supplied_counterparty).strip() if supplied_counterparty else None
    item_name = str(data.get('item_name') or '').strip()
    quantity = None
    if data.get('quantity') not in (None, ''):
        try:
            quantity = Decimal(str(data.get('quantity')))
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({'error': 'quantity must be a valid number.'}), 400
        if not quantity.is_finite() or quantity <= 0:
            return jsonify({'error': 'quantity must be greater than 0.'}), 400
    if transaction_type == TransactionType.EXPENSE and not counterparty_name:
        return jsonify({'error': 'paid_to is required for an expense record.'}), 400
    if transaction_type == TransactionType.REVENUE and item_name:
        return jsonify({'error': 'item_name is only valid for expense records.'}), 400
    if transaction_type == TransactionType.REVENUE and quantity is not None:
        return jsonify({'error': 'quantity is only valid for expense records.'}), 400
    if transaction_type == TransactionType.REVENUE and not (customer or buyer or counterparty_name):
        return jsonify({'error': 'A customer, buyer, or income_source is required for an income record.'}), 400

    animal_id = data.get('animal_id')
    animal_cost_type = data.get('animal_cost_type')
    if (animal_id is None) != (animal_cost_type is None):
        return jsonify({'error': 'animal_id and animal_cost_type must be provided together.'}), 400
    if animal_id is not None and transaction_type != TransactionType.EXPENSE:
        return jsonify({'error': 'Only expense records can be allocated to an animal.'}), 400
    if animal_id is not None:
        try:
            animal_id = int(animal_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'animal_id must be a valid integer.'}), 400

    timestamp = datetime.now(timezone.utc)
    if data.get('date'):
        try:
            entered_date = datetime.fromisoformat(data['date']).date()
            timestamp = datetime.combine(entered_date, timestamp.timetz())
        except (TypeError, ValueError):
            return jsonify({'error': 'date must be in YYYY-MM-DD format.'}), 400

    transaction = Transaction(
        tenant_id=tenant_id,
        farm_id=_current_farm_id(),
        customer_id=customer.id if customer else None,
        buyer_id=buyer.id if buyer else None,
        transaction_type=transaction_type,
        category=category,
        amount=amount,
        item_name=item_name[:120] if item_name else None,
        quantity=quantity,
        cost_class=cost_class,
        description=(data.get('description') or '').strip() or None,
        counterparty_name=counterparty_name[:120] if counterparty_name else None,
        payment_method=(data.get('payment_method') or '').strip()[:30] or None,
        reference_code=(data.get('reference_code') or '').strip() or None,
        timestamp=timestamp,
        recorded_by=get_jwt_identity(),
        status=TransactionStatus.POSTED.value,
        posted_at=datetime.now(timezone.utc),
        posted_by=get_jwt_identity(),
    )

    try:
        db.session.add(transaction)
        db.session.flush()
        if animal_id is not None:
            AnimalCostAllocationService().create_for_transaction(
                tenant_id=tenant_id,
                cow_id=animal_id,
                cost_type=animal_cost_type,
                transaction=transaction,
            )
        if transaction_type == TransactionType.REVENUE:
            ReceiptService.issue(
                transaction,
                issued_by=int(get_jwt_identity()),
                farm_id=_current_farm_id(),
                ip_address=request.remote_addr,
            )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'reference_code has already been recorded.'}), 409

    return jsonify(_serialize_transaction(transaction)), 201


@finance_bp.route('/transactions/<int:transaction_id>/void-and-replace', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def void_and_replace_expense_transaction(transaction_id):
    """Correct an expense classification without mutating or deleting the posted record."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    data = request.get_json() or {}
    replacement_data = data.get('replacement')
    if replacement_data is None:
        replacement_data = {}
    if not isinstance(replacement_data, dict):
        return jsonify({'error': 'replacement must be an object.'}), 400
    try:
        original, replacement = LedgerCorrectionService.void_and_replace_expense(
            tenant_id=tenant_id,
            transaction_id=transaction_id,
            void_reason=data.get('void_reason'),
            corrected_by=int(get_jwt_identity()),
            category=replacement_data.get('category'),
            cost_class=replacement_data.get('cost_class'),
            ip_address=request.remote_addr,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        status_code = 404 if str(exc) == 'Transaction not found.' else 422
        return jsonify({'error': str(exc)}), status_code
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'The transaction was corrected concurrently. Refresh and try again.'}), 409

    return jsonify({
        'voided_transaction': _serialize_transaction(original),
        'replacement_transaction': _serialize_transaction(replacement),
    }), 201


@finance_bp.route('/transactions/<int:transaction_id>/receipt', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def issue_transaction_receipt(transaction_id):
    tenant_id = get_tenant_id_from_context()
    transaction = Transaction.query.filter_by(id=transaction_id, tenant_id=tenant_id).first()
    if not transaction:
        return jsonify({'error': 'Transaction not found.'}), 404
    try:
        receipt = ReceiptService.issue(
            transaction,
            issued_by=int(get_jwt_identity()),
            farm_id=_current_farm_id(),
            ip_address=request.remote_addr,
        )
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        transaction = Transaction.query.filter_by(id=transaction_id, tenant_id=tenant_id).first()
        if not transaction or not transaction.receipt:
            return jsonify({'error': 'Receipt issuance conflict.'}), 409
        receipt = transaction.receipt
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 422
    return jsonify(ReceiptService.serialize(receipt)), 200


@finance_bp.route('/receipts/<int:receipt_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def get_receipt(receipt_id):
    tenant_id = get_tenant_id_from_context()
    receipt = ReceiptService.get_for_tenant(receipt_id, tenant_id)
    if not receipt:
        return jsonify({'error': 'Receipt not found.'}), 404
    ReceiptService.record_access(receipt, 'VIEWED', int(get_jwt_identity()), request.remote_addr)
    db.session.commit()
    return jsonify(ReceiptService.serialize(receipt)), 200


@finance_bp.route('/receipts/<int:receipt_id>/pdf', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def download_receipt_pdf(receipt_id):
    tenant_id = get_tenant_id_from_context()
    receipt = ReceiptService.get_for_tenant(receipt_id, tenant_id)
    if not receipt:
        return jsonify({'error': 'Receipt not found.'}), 404
    if receipt.document_content is None:
        payload = ReceiptService.serialize(receipt)
        receipt.document_content = HTML(string=render_template('pdf/receipt.html', receipt=payload)).write_pdf()
        receipt.document_sha256 = hashlib.sha256(receipt.document_content).hexdigest()
    ReceiptService.record_access(receipt, 'DOWNLOADED', int(get_jwt_identity()), request.remote_addr)
    db.session.commit()
    return send_file(
        io.BytesIO(receipt.document_content),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{receipt.receipt_number}.pdf",
    )


@finance_bp.route('/receipts/<int:receipt_id>/void', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def void_receipt(receipt_id):
    tenant_id = get_tenant_id_from_context()
    receipt = ReceiptService.get_for_tenant(receipt_id, tenant_id)
    if not receipt:
        return jsonify({'error': 'Receipt not found.'}), 404
    try:
        ReceiptService.void(
            receipt,
            (request.get_json() or {}).get('void_reason'),
            int(get_jwt_identity()),
            request.remote_addr,
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 422
    return jsonify(ReceiptService.serialize(receipt)), 200


@finance_bp.route('/receipts/<int:receipt_id>/audit', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_receipt_audit(receipt_id):
    tenant_id = get_tenant_id_from_context()
    receipt = ReceiptService.get_for_tenant(receipt_id, tenant_id)
    if not receipt:
        return jsonify({'error': 'Receipt not found.'}), 404
    logs = ReceiptAuditLog.query.filter_by(tenant_id=tenant_id, receipt_id=receipt.id).order_by(ReceiptAuditLog.id).all()
    return jsonify({'items': [{
        'id': log.id,
        'action': log.action,
        'performed_by': log.performed_by,
        'ip_address': log.ip_address,
        'details': log.details,
        'created_at': log.created_at.isoformat(),
    } for log in logs]}), 200


@finance_bp.route('/customers', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_customer():
    """Creates a new customer record."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload.'}), 400

    name = data.get('name')
    phone_number = data.get('phone_number')

    if not name or not phone_number:
        return jsonify({'error': 'name and phone_number are required.'}), 400

    # Check for existing customer with the same phone number for this tenant
    existing_customer = db.session.query(Customer).filter_by(tenant_id=tenant_id, phone_number=phone_number).first()
    if existing_customer:
        return jsonify({'error': f'A customer with phone number {phone_number} already exists.'}), 409

    try:
        new_customer = Customer(
            tenant_id=tenant_id,
            name=name,
            phone_number=phone_number,
            daily_contract_liters=data.get('daily_contract_liters'),
            agreed_rate_per_liter=data.get('agreed_rate_per_liter'),
            account_balance=data.get('account_balance', 0),
            status='Active'  # Default to Active
        )
        db.session.add(new_customer)
        db.session.commit()
        return jsonify(_serialize_customer(new_customer)), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'A customer with this phone number already exists.'}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'An unexpected error occurred.', 'details': str(e)}), 500

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
    if billable_liters > 0 and price_per_liter <= 0:
        return jsonify({
            'error': 'Customer must have a positive agreed_rate_per_liter before recording a billable delivery.'
        }), 400
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


@finance_bp.route('/deliveries/<int:delivery_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_delivery(delivery_id):
    """Updates an existing delivery record and adjusts financial records accordingly."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    current_user_id = get_jwt_identity()
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON payload.'}), 400

    delivery = db.session.query(Delivery).filter_by(id=delivery_id, tenant_id=tenant_id).first()
    if not delivery:
        return jsonify({'error': 'Delivery not found.'}), 404

    try:
        with db.session.begin_nested():
            # Re-fetch with lock inside the transaction
            delivery = db.session.query(Delivery).filter_by(id=delivery_id, tenant_id=tenant_id).with_for_update().first()
            if not delivery:
                raise FileNotFoundError("Delivery not found inside transaction.")

            customer = db.session.query(Customer).filter_by(id=delivery.customer_id, tenant_id=tenant_id).with_for_update().first()
            if not customer:
                raise FileNotFoundError("Associated customer not found.")

            old_total_price = delivery.total_price

            # Update fields from payload
            if 'date' in data and data['date']:
                try:
                    delivery.date = datetime.fromisoformat(data['date']).date()
                except ValueError:
                    raise ValueError('date must be in YYYY-MM-DD format.')

            if 'liters_delivered' in data:
                delivery.liters_delivered = Decimal(str(data['liters_delivered']))

            if 'personal_consumption_liters' in data:
                delivery.personal_consumption_liters = Decimal(str(data['personal_consumption_liters']))

            if 'notes' in data:
                delivery.notes = data.get('notes', '')

            # Validation after updating
            if delivery.liters_delivered <= 0:
                raise ValueError('liters_delivered must be greater than 0.')
            if delivery.personal_consumption_liters < 0:
                raise ValueError('personal_consumption_liters cannot be negative.')
            if delivery.personal_consumption_liters > delivery.liters_delivered:
                raise ValueError('personal_consumption_liters cannot exceed liters_delivered.')

            # Recalculate financial values
            delivery.billable_liters = delivery.liters_delivered - delivery.personal_consumption_liters
            if delivery.billable_liters > 0 and delivery.price_per_liter <= 0:
                raise ValueError('Billable deliveries must have a positive price_per_liter.')
            new_total_price = delivery.billable_liters * delivery.price_per_liter
            delivery.total_price = new_total_price

            price_adjustment = new_total_price - old_total_price

            if not price_adjustment.is_zero():
                customer.account_balance = (customer.account_balance or Decimal('0.0')) + price_adjustment

                adjustment_transaction = Transaction(
                    tenant_id=tenant_id, customer_id=customer.id,
                    transaction_type=TransactionType.DEBIT if price_adjustment > 0 else TransactionType.CREDIT,
                    category=TransactionCategory.MILK_SALE, amount=abs(price_adjustment),
                    description=f"Adjustment for delivery #{delivery.id} on {delivery.date.isoformat()}",
                    timestamp=datetime.now(timezone.utc), recorded_by=current_user_id
                )
                db.session.add(adjustment_transaction)

        db.session.commit()
        return jsonify(_serialize_delivery(delivery)), 200

    except FileNotFoundError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 404
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except (TypeError, ArithmeticError):
        db.session.rollback()
        return jsonify({'error': 'Invalid numeric values for delivery details.'}), 400
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Database integrity error.', 'details': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'An unexpected error occurred during update.'}), 500


@finance_bp.route('/deliveries/<int:delivery_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_delivery(delivery_id):
    """Deletes a delivery record and reverses the financial impact."""
    tenant_id = get_tenant_id_from_context()
    if not tenant_id:
        return jsonify({'error': 'Tenant context is missing.'}), 400

    current_user_id = get_jwt_identity()

    # Quick check before starting a transaction
    delivery = db.session.query(Delivery).filter_by(id=delivery_id, tenant_id=tenant_id).first()
    if not delivery:
        return jsonify({'error': 'Delivery not found.'}), 404

    try:
        with db.session.begin_nested():
            # Re-fetch with lock inside the transaction
            delivery = db.session.query(Delivery).filter_by(id=delivery_id, tenant_id=tenant_id).with_for_update().first()
            if not delivery:
                raise FileNotFoundError("Delivery not found inside transaction.")

            customer = db.session.query(Customer).filter_by(id=delivery.customer_id, tenant_id=tenant_id).with_for_update().first()
            if not customer:
                raise FileNotFoundError("Associated customer not found.")

            reversal_amount = delivery.total_price

            if not reversal_amount.is_zero():
                customer.account_balance = (customer.account_balance or Decimal('0.0')) - reversal_amount

                reversal_transaction = Transaction(
                    tenant_id=tenant_id, customer_id=customer.id,
                    transaction_type=TransactionType.CREDIT,
                    category=TransactionCategory.MILK_SALE, amount=reversal_amount,
                    description=f"Reversal for deleted delivery #{delivery.id} on {delivery.date.isoformat()}",
                    timestamp=datetime.now(timezone.utc), recorded_by=current_user_id
                )
                db.session.add(reversal_transaction)

            db.session.delete(delivery)

        db.session.commit()
        return jsonify({'message': 'Delivery deleted and financial records reversed successfully.'}), 200

    except FileNotFoundError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 404
    except IntegrityError as e:
        db.session.rollback()
        return jsonify({'error': 'Database integrity error during reversal.', 'details': str(e)}), 409
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'An unexpected error occurred during deletion.'}), 500
