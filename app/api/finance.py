from flask import Blueprint, request, jsonify, g
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.services.mpesa_service import MpesaService
from app.services.finance_service import FinanceService
from app.services.buyer_service import BuyerService, DuplicateBuyerError
from app.utils.decorators import role_required
from app.utils import get_tenant_id_from_context
from app.models.user import Role
from app.utils.jwt_payload import parse_public_int_id
from app.models.finance import Buyer, Customer, PaymentStatus, SalesLedger, Transaction, TransactionType, TransactionCategory
from app import db
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from typing import Any, Optional

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


def _parse_entity_id(value: Any, prefix: str) -> Optional[int]:
    """Safely parse a public ID (e.g., 'prefix_123') or a raw integer."""
    from app.utils.jwt_payload import parse_public_int_id
    if value is None:
        return None
    try:
        # Try parsing as "prefix_N" format first
        return parse_public_int_id(str(value), prefix)
    except (TypeError, ValueError):
        try:
            # Fallback to parsing as a raw integer
            return int(value)
        except (TypeError, ValueError):
            return None


def _serialize_customer(customer):
    return {
        'id': customer.id,
        'name': customer.name,
        'phone_number': customer.phone_number,
        'account_balance': float(customer.account_balance or 0),
        'daily_contract_liters': float(customer.daily_contract_liters or 0),
        'is_active': customer.is_active,
    }


def _get_buyer_unpaid_balance(buyer_id: int) -> float:
    """Calculate current balance from ledger (source of truth)."""
    result = db.session.query(
        func.coalesce(func.sum(SalesLedger.total_cost - SalesLedger.amount_paid), 0)
    ).filter(
        SalesLedger.buyer_id == buyer_id,
        SalesLedger.payment_status != PaymentStatus.PAID
    ).scalar()
    return float(result or 0)


def _serialize_buyer(row):
    """Delegate to BuyerService for consistent buyer serialization."""
    return BuyerService.serialize_buyer(row)


def _build_buyer_details(buyer):
    """Helper to build a buyer's detailed profile, summary, and consumption history."""
    sales = db.session.query(SalesLedger).filter_by(
        buyer_id=buyer.id,
        tenant_id=buyer.tenant_id
    ).order_by(SalesLedger.date.desc()).all()

    outstanding_balance = _get_buyer_unpaid_balance(buyer.id)
    total_liters = sum(float(s.liters_sold) for s in sales)
    
    # Calculate historical totals accurately from the immutable ledger.
    total_invoiced = sum(float(s.total_cost) for s in sales)
    total_paid = sum(float(s.amount_paid) for s in sales)

    consumption_breakdown = [
        {
            'date': s.date.isoformat(),
            'shift': s.shift or 'Morning',
            'liters': float(s.liters_sold),
            'rate': float(buyer.agreed_rate_per_liter),
            'amount': float(s.total_cost),  # Original invoice amount
            'amount_paid': float(s.amount_paid),
            'amount_outstanding': float(s.total_cost - s.amount_paid),
            'payment_status': s.payment_status,
        }
        for s in sales
    ]

    summary = {
        'outstanding_balance': round(outstanding_balance, 2),
        'total_invoiced': round(total_invoiced, 2),
        'total_paid': round(total_paid, 2),
        'liters_delivered': round(total_liters, 2),
    }

    return {
        'buyer': _serialize_buyer(buyer),
        'summary': summary,
        'consumption_breakdown': consumption_breakdown,
    }

def _serialize_transaction(tx, customer_name=None, buyer_name=None):
    counterparty_name = buyer_name or customer_name
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
        'customer_name': customer_name,
        'buyer_id': tx.buyer_id,
        'buyer_name': buyer_name,
        'counterparty_name': counterparty_name,
        'recorded_by': tx.recorded_by,
    }

@finance_bp.route('/unit-cost', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_unit_cost():
    """Retrieves the real-time cost of production per liter."""
    from flask_jwt_extended import get_jwt
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        # Provide diagnostic information for debugging
        claims = get_jwt() or {}
        raw_tenant_id = getattr(g, 'tenant_id', 'NOT_SET')
        print(f"[unit-cost] DEBUG: g.tenant_id={raw_tenant_id}, JWT tenant_id={claims.get('tenant_id')}, user_id={claims.get('sub')}")
        return jsonify({
            'error': 'Missing or invalid tenant context.',
            'details': {
                'g_tenant_id': raw_tenant_id,
                'jwt_tenant_id': claims.get('tenant_id'),
                'user_id': claims.get('sub'),
            }
        }), 400

    return FinanceService.calculate_daily_unit_cost(tenant_id=tenant_id)


@finance_bp.route('/customers', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_customers():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    customers = Customer.query.filter_by(tenant_id=tenant_id).order_by(Customer.name.asc()).all()
    q = (request.args.get('q') or '').strip().lower()
    if q:
        customers = [customer for customer in customers if q in (customer.name or '').lower() or q in (customer.phone_number or '').lower()]
    rows, meta = _paginate_items([_serialize_customer(customer) for customer in customers])
    return jsonify({'items': rows, 'meta': meta}), 200


@finance_bp.route('/customers/<int:customer_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_customer(customer_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404
    return jsonify(_serialize_customer(customer)), 200


@finance_bp.route('/customers/<int:customer_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_customer(customer_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    
    customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).first()
    if not customer:
        return jsonify({'error': 'Customer not found.'}), 404

    try:
        db.session.delete(customer)
        db.session.commit()
        return jsonify({'message': f'Customer "{customer.name}" deleted successfully.'}), 200
    except IntegrityError:
        db.session.rollback()
        return jsonify({
            'error': 'Cannot delete customer. They have associated financial records (transactions). Consider deactivating them instead.',
        }), 409

@finance_bp.route('/ledger', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_ledger():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    rows = Transaction.query.filter_by(tenant_id=tenant_id).order_by(Transaction.timestamp.desc(), Transaction.id.desc()).all()
    tx_type = (request.args.get('transaction_type') or '').strip().title()
    if tx_type in {'Revenue', 'Expense'}:
        rows = [row for row in rows if row.transaction_type == tx_type]

    customer_ids = {row.customer_id for row in rows if row.customer_id is not None}
    buyer_ids = {row.buyer_id for row in rows if row.buyer_id is not None}

    customer_name_by_id = {}
    buyer_name_by_id = {}

    if customer_ids:
        customers = Customer.query.filter(Customer.id.in_(customer_ids), Customer.tenant_id == tenant_id).all()
        customer_name_by_id = {customer.id: customer.name for customer in customers}
    if buyer_ids:
        buyers = Buyer.query.filter(Buyer.id.in_(buyer_ids), Buyer.tenant_id == tenant_id).all()
        buyer_name_by_id = {buyer.id: buyer.name for buyer in buyers}

    serialized_rows = [
        _serialize_transaction(
            row,
            customer_name=customer_name_by_id.get(row.customer_id),
            buyer_name=buyer_name_by_id.get(row.buyer_id),
        )
        for row in rows
    ]
    payload, meta = _paginate_items(serialized_rows)

    # --- SQL AGGREGATION FOR SUMMARY ---
    # We query the database specifically for the sum, ignoring pagination limits
    income_result = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.tenant_id == tenant_id,
        Transaction.transaction_type == TransactionType.REVENUE
    ).scalar()
    
    expense_result = db.session.query(func.sum(Transaction.amount)).filter(
        Transaction.tenant_id == tenant_id,
        Transaction.transaction_type == TransactionType.EXPENSE
    ).scalar()

    # .scalar() returns None if there are no rows, so we fallback to 0.0
    total_income = float(income_result or 0.0)
    total_costs = float(expense_result or 0.0)
    total_profit = total_income - total_costs
    summary = {
        'transaction_count': len(rows),
        'total_income': round(total_income, 2),
        'total_costs': round(total_costs, 2),
        'total_profit': round(total_profit, 2),
    }

    return jsonify({'items': payload, 'meta': meta, 'summary': summary}), 200


@finance_bp.route('/ledger', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_ledger_entry():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    data = request.get_json() or {}
    
    # Accept both 'type' and 'transaction_type' fields; normalize to title case
    tx_type = (data.get('transaction_type') or data.get('type') or '').strip().title()
    category = (data.get('category') or '').strip().title()
    amount = data.get('amount')
    
    # Accept field name aliases
    description = data.get('description') or data.get('note')
    reference_code = data.get('reference_code') or data.get('reference')
    
    if tx_type not in {'Revenue', 'Expense'}:
        return jsonify({'error': 'transaction_type must be Revenue or Expense.'}), 400
    if not category or amount is None:
        return jsonify({'error': 'category and amount are required.'}), 400
    try:
        amount = float(amount)
        # Allow positive or negative amounts (for opening balances, reversals, etc.)
    except (TypeError, ValueError):
        return jsonify({'error': 'amount must be a valid number.'}), 400

    # Accept buyer_id (preferred) or customer_id, but not both
    # If buyer_id is provided, use it; otherwise use customer_id
    buyer_id = _parse_entity_id(data.get('buyer_id'), 'buyer_')
    customer_id = _parse_entity_id(data.get('customer_id'), 'customer_')

    # Prefer buyer_id over customer_id; if buyer_id is set, don't use customer_id
    if buyer_id is not None:
        customer_id = None

    # If this is a revenue entry for a buyer, it's a payment.
    # Delegate to the allocation service to ensure the buyer's debt is reduced.
    if tx_type == TransactionType.REVENUE and buyer_id is not None:
        try:
            allocation_result = BuyerService.allocate_payment(
                buyer_id=buyer_id,
                tenant_id=tenant_id,
                amount=amount,
                note=description,
                reference_code=reference_code,
                recorded_by=int(get_jwt_identity()),
            )
            tx = allocation_result['transaction']
            buyer = allocation_result['buyer']
            # Return a more detailed response consistent with the dedicated payment endpoint
            return jsonify({
                'message': 'Buyer payment logged and allocated successfully.',
                'buyer': _serialize_buyer(buyer),
                'payment': {
                    'buyer_id': buyer.id,
                    'buyer_name': buyer.name,
                    'amount_paid': float(tx.amount),
                    'amount_applied': allocation_result['applied_amount'],
                    'unallocated_credit': allocation_result['unallocated_credit'],
                    'previous_balance': allocation_result['previous_balance'],
                    'current_balance': allocation_result['current_balance'],
                    'allocations': allocation_result['allocations'],
                },
                'transaction': _serialize_transaction(tx, buyer_name=buyer.name),
            }), 201
        except ValueError as exc:
            message = str(exc)
            status = 404 if 'not found' in message.lower() else 400
            return jsonify({'error': message}), status

    buyer = None
    customer = None

    if buyer_id is not None:
        buyer = db.session.query(Buyer).filter_by(id=buyer_id, tenant_id=tenant_id).first()
        if not buyer:
            return jsonify({'error': f'Buyer with id {data.get("buyer_id")} not found for this tenant.'}), 404

    if customer_id is not None:
        customer = db.session.query(Customer).filter_by(id=customer_id, tenant_id=tenant_id).first()
        if not customer:
            return jsonify({'error': f'Customer with id {data.get("customer_id")} not found for this tenant.'}), 404

    tx = Transaction(
        tenant_id=tenant_id,
        transaction_type=tx_type,
        category=category,
        amount=amount,
        reference_code=reference_code,
        description=description,
        customer_id=customer_id,
        buyer_id=buyer_id,
        recorded_by=int(get_jwt_identity()),
    )
    db.session.add(tx)
    db.session.commit()

    customer_name = customer.name if customer else None
    buyer_name = buyer.name if buyer else None
    return jsonify(_serialize_transaction(tx, customer_name=customer_name, buyer_name=buyer_name)), 201


@finance_bp.route('/buyers', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_buyers():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    rows = Buyer.query.filter_by(tenant_id=tenant_id, is_active=True).order_by(Buyer.name.asc()).all()
    q = (request.args.get('q') or '').strip().lower()
    if q:
        rows = [row for row in rows if q in (row.name or '').lower() or q in (row.phone_number or '').lower()]
    serialized = [_serialize_buyer(row) for row in rows]
    total_unpaid = sum(item['current_balance'] for item in serialized)
    buyers_with_zero_balance = sum(1 for item in serialized if item['current_balance'] == 0)
    summary = {
        'active_buyers': len(rows),
        'total_unpaid_balance': round(total_unpaid, 2),
        'buyers_with_zero_balance': buyers_with_zero_balance,
    }
    payload, meta = _paginate_items(serialized)
    return jsonify({'items': payload, 'meta': meta, 'summary': summary}), 200


@finance_bp.route('/buyers', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_buyer():
    import logging
    logger = logging.getLogger(__name__)
    
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    data = request.get_json() or {}
    
    # Log the exact payload received
    logger.info(f"POST /buyers received payload: {data}")
    logger.info(f"opening_balance value: {data.get('opening_balance')} (type: {type(data.get('opening_balance')).__name__})")
    
    try:
        buyer = BuyerService.create_buyer(
            tenant_id=tenant_id,
            name=data.get('name'),
            agreed_rate_per_liter=data.get('agreed_rate_per_liter', data.get('rate_per_liter')),
            contact=data.get('phone_number', data.get('contact')),
            whatsapp=data.get('whatsapp'),
            buyer_type=data.get('buyer_type', data.get('type')),
            farm_id=data.get('farm_id'),
            opening_balance=data.get('opening_balance', data.get('balance')),
        )
        return jsonify(_serialize_buyer(buyer)), 201
    except DuplicateBuyerError as e:
        return jsonify({'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Error creating buyer: {str(e)}")
        return jsonify({'error': f'Failed to create buyer: {str(e)}'}), 500


@finance_bp.route('/buyers/<int:buyer_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_buyer(buyer_id):
    """Returns the buyer details."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    buyer = db.session.query(Buyer).filter_by(id=buyer_id, tenant_id=tenant_id).first()
    if not buyer:
        return jsonify({'error': 'Buyer not found.'}), 404

    details = _build_buyer_details(buyer)
    return jsonify(details), 200


@finance_bp.route('/buyers/<int:buyer_id>/payments', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def record_buyer_payment(buyer_id):
    """Apply a buyer payment to receivables and create a linked finance ledger entry."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    payload = request.get_json() or {}
    amount = payload.get('amount')
    note = (payload.get('note') or payload.get('description') or '').strip() or None
    reference_code = (payload.get('reference_code') or payload.get('reference') or '').strip() or None

    if amount is None:
        return jsonify({'error': 'amount is required.'}), 400

    try:
        # The service now handles transaction creation and allocation atomically.
        allocation_result = BuyerService.allocate_payment(
            buyer_id=buyer_id,
            tenant_id=tenant_id,
            amount=amount,
            note=note,
            reference_code=reference_code,
            recorded_by=int(get_jwt_identity()),
        )
    except ValueError as exc:
        message = str(exc)
        status = 404 if 'not found' in message.lower() else 400
        return jsonify({'error': message}), status
    
    buyer = allocation_result['buyer']
    tx = allocation_result['transaction']

    return jsonify({
        'buyer': _serialize_buyer(buyer),
        'payment': {
            'buyer_id': buyer.id,
            'buyer_name': buyer.name,
            'amount_paid': float(allocation_result['transaction'].amount),
            'amount_applied': allocation_result['applied_amount'],
            'unallocated_credit': allocation_result['unallocated_credit'],
            'previous_balance': allocation_result['previous_balance'],
            'current_balance': allocation_result['current_balance'],
            'allocations': allocation_result['allocations'],
        },
        'transaction': _serialize_transaction(tx, buyer_name=buyer.name),
    }), 201


@finance_bp.route('/buyers/<int:buyer_id>/statement', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_buyer_statement(buyer_id):
    """Returns complete buyer profile, summary, and consumption breakdown for statement pages."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    
    buyer = db.session.query(Buyer).filter_by(id=buyer_id, tenant_id=tenant_id).first()
    if not buyer:
        return jsonify({'error': 'Buyer not found.'}), 404
    details = _build_buyer_details(buyer)
    
    # Build complete response
    response = {
        'profile': {
            'buyer': {
                'id': buyer.id,
                'name': buyer.name,
                'contact': buyer.phone_number,
                'whatsapp': buyer.whatsapp,
            }
        },
        'summary': details['summary'],
        'consumption_breakdown': details['consumption_breakdown'],
    }
    
    return jsonify(response), 200


@finance_bp.route('/buyers/<int:buyer_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_buyer(buyer_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    data = request.get_json() or {}
    
    try:
        buyer = BuyerService.update_buyer(
            buyer_id=buyer_id,
            tenant_id=tenant_id,
            name=data.get('name'),
            contact=data.get('phone_number', data.get('contact')),
            whatsapp=data.get('whatsapp'),
            buyer_type=data.get('buyer_type', data.get('type')),
            agreed_rate_per_liter=data.get('agreed_rate_per_liter', data.get('rate_per_liter')),
            is_active=data.get('is_active'),
            # Reject these if provided
            balance=data.get('balance'),
            current_balance=data.get('current_balance'),
            payment_status=data.get('payment_status'),
        )
        return jsonify(_serialize_buyer(buyer)), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'not found' not in str(e).lower() else 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to update buyer'}), 500


@finance_bp.route('/buyers/<int:buyer_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_buyer(buyer_id):
    """Delete buyer with safety checks. Soft deletes if ledger exists, hard deletes if safe."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    
    try:
        force = request.args.get('force', 'false').lower() == 'true'
        was_hard_delete = BuyerService.delete_buyer(buyer_id, tenant_id, force=force)
        return jsonify({
            'success': True,
            'deleted_type': 'hard' if was_hard_delete else 'soft',
            'message': 'Hard deleted' if was_hard_delete else 'Soft deleted (deactivated)'
        }), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400 if 'not found' not in str(e).lower() else 404
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Failed to delete buyer'}), 500


@finance_bp.route('/customers', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_customer():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    phone_number = (data.get('phone_number') or '').strip()
    if not name or not phone_number:
        return jsonify({'error': 'name and phone_number are required.'}), 400
    try:
        customer = Customer(
            tenant_id=tenant_id,
            name=name,
            phone_number=phone_number,
            account_balance=data.get('account_balance', 0),
            daily_contract_liters=data.get('daily_contract_liters', 0),
            is_active=bool(data.get('is_active', True)),
        )
        db.session.add(customer)
        db.session.commit()
        return jsonify(_serialize_customer(customer)), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Customer phone_number already exists for this tenant.'}), 409


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