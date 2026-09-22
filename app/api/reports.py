from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from app import db
from app.models.farm import Farm
from app.models.finance import Buyer, CostClass, Customer, Delivery, SalesLedger, Transaction, TransactionStatus, TransactionType
from app.models.supply import MilkLog
from app.models.user import Role
from app.services.animal_economics_service import AnimalEconomicsService
from app.utils import get_tenant_id_from_context
from app.utils.decorators import require_tenant_context, role_required

reports_bp = Blueprint('reports', __name__)


def _parse_date_param(param_name: str, default: date) -> date:
    """Safely parse a date from request arguments."""
    raw = request.args.get(param_name)
    if not raw:
        return default
    try:
        # Handles both 'YYYY-MM-DD' and full ISO 'YYYY-MM-DDTHH:MM:SS'
        return datetime.fromisoformat(raw.split('T')[0]).date()
    except (ValueError, TypeError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _month_span_inclusive(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 1
    month_count = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month) + 1
    return month_count if month_count > 0 else 1


def _classify_ltv_cac_ratio(ratio: float | None) -> str:
    if ratio is None:
        return 'unknown'
    if ratio < 1:
        return 'under_1_to_1_losing_money'
    if ratio < 2:
        return 'between_1_and_2_needs_improvement'
    if ratio < 3:
        return 'around_2_to_1_acceptable_for_expansion'
    if ratio <= 4:
        return 'between_3_and_4_highly_optimized'
    return 'above_4_strong_but_validate_assumptions'


def _build_dairy_unit_economics_for_tenant(
    *,
    tenant_id: int,
    start_date: date,
    end_date: date,
    marketing_spend_override: float | None = None,
    new_customers_override: int | None = None,
    lifespan_months_override: float | None = None,
) -> dict:
    month_span = _month_span_inclusive(start_date, end_date)

    liters_b2c = _safe_float(
        db.session.query(func.coalesce(func.sum(Delivery.billable_liters), 0)).filter(
            Delivery.tenant_id == tenant_id,
            Delivery.date.between(start_date, end_date),
        ).scalar()
    )
    liters_b2b = _safe_float(
        db.session.query(func.coalesce(func.sum(SalesLedger.liters_sold), 0)).filter(
            SalesLedger.tenant_id == tenant_id,
            SalesLedger.date.between(start_date, end_date),
        ).scalar()
    )
    total_liters_sold = liters_b2c + liters_b2b

    revenue_b2c = _safe_float(
        db.session.query(func.coalesce(func.sum(Delivery.total_price), 0)).filter(
            Delivery.tenant_id == tenant_id,
            Delivery.date.between(start_date, end_date),
        ).scalar()
    )
    revenue_b2b = _safe_float(
        db.session.query(func.coalesce(func.sum(SalesLedger.total_amount), 0)).filter(
            SalesLedger.tenant_id == tenant_id,
            SalesLedger.date.between(start_date, end_date),
        ).scalar()
    )
    total_revenue = revenue_b2c + revenue_b2b

    receivables_net = _safe_float(
        db.session.query(func.coalesce(func.sum(Customer.account_balance), 0)).filter(
            Customer.tenant_id == tenant_id,
            Customer.status == 'Active',
        ).scalar()
    )
    receivables_outstanding = _safe_float(
        db.session.query(func.coalesce(func.sum(Customer.account_balance), 0)).filter(
            Customer.tenant_id == tenant_id,
            Customer.status == 'Active',
            Customer.account_balance > 0,
        ).scalar()
    )
    customer_credit_total = abs(_safe_float(
        db.session.query(func.coalesce(func.sum(Customer.account_balance), 0)).filter(
            Customer.tenant_id == tenant_id,
            Customer.status == 'Active',
            Customer.account_balance < 0,
        ).scalar()
    ))

    production_cost_total = _safe_float(
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.status == TransactionStatus.POSTED.value,
            Transaction.cost_class == CostClass.COGS,
            func.date(Transaction.timestamp).between(start_date, end_date),
        ).scalar()
    )

    production_cost_per_liter = (production_cost_total / total_liters_sold) if total_liters_sold > 0 else 0.0
    realized_contribution_total = total_revenue - production_cost_total
    gross_margin_per_liter = (realized_contribution_total / total_liters_sold) if total_liters_sold > 0 else 0.0

    customer_economics = []
    customer_rows = db.session.query(
        Customer.id,
        Customer.name,
        Customer.status,
        func.min(Delivery.date),
        func.max(Delivery.date),
        func.coalesce(func.sum(Delivery.billable_liters), 0),
        func.coalesce(func.sum(Delivery.total_price), 0),
    ).join(Delivery, Delivery.customer_id == Customer.id).filter(
        Customer.tenant_id == tenant_id,
        Delivery.tenant_id == tenant_id,
        Delivery.date.between(start_date, end_date),
    ).group_by(Customer.id, Customer.name, Customer.status).all()
    buyer_rows = db.session.query(
        Buyer.id,
        Buyer.name,
        Buyer.is_active,
        func.min(SalesLedger.date),
        func.max(SalesLedger.date),
        func.coalesce(func.sum(SalesLedger.liters_sold), 0),
        func.coalesce(func.sum(SalesLedger.total_amount), 0),
    ).join(SalesLedger, SalesLedger.buyer_id == Buyer.id).filter(
        Buyer.tenant_id == tenant_id,
        SalesLedger.tenant_id == tenant_id,
        SalesLedger.date.between(start_date, end_date),
    ).group_by(Buyer.id, Buyer.name, Buyer.is_active).all()

    for account_type, rows in (('customer', customer_rows), ('buyer', buyer_rows)):
        for account_id, name, active_value, first_sale, last_sale, liters, revenue in rows:
            liters_value = _safe_float(liters)
            revenue_value = _safe_float(revenue)
            allocated_cost = liters_value * production_cost_per_liter
            customer_economics.append({
                'account_type': account_type,
                'account_id': account_id,
                'name': name,
                'is_active': active_value == 'Active' if account_type == 'customer' else bool(active_value),
                'first_sale_date': first_sale.isoformat() if first_sale else None,
                'last_sale_date': last_sale.isoformat() if last_sale else None,
                'liters_purchased': round(liters_value, 2),
                'revenue_kes': round(revenue_value, 2),
                'allocated_production_cost_kes': round(allocated_cost, 2),
                'realized_ltv_kes': round(revenue_value - allocated_cost, 2),
            })
    customer_economics.sort(key=lambda item: item['realized_ltv_kes'], reverse=True)

    b2c_customer_count = db.session.query(func.count(Customer.id)).filter(
        Customer.tenant_id == tenant_id,
        Customer.status == 'Active',
    ).scalar() or 0
    b2b_customer_count = db.session.query(func.count(Buyer.id)).filter(
        Buyer.tenant_id == tenant_id,
        Buyer.is_active.is_(True),
    ).scalar() or 0
    total_active_accounts = int(b2c_customer_count + b2b_customer_count)

    liters_per_month_per_account = (
        (total_liters_sold / month_span / total_active_accounts) if total_active_accounts > 0 else 0.0
    )

    # Tenant-level fallback: observed window length as proxy lifespan when no explicit override is provided.
    customer_lifespan_months = float(lifespan_months_override if lifespan_months_override is not None else month_span)

    realized_ltv = (realized_contribution_total / total_active_accounts) if total_active_accounts > 0 else 0.0
    forecast_ltv = liters_per_month_per_account * gross_margin_per_liter * customer_lifespan_months

    new_customers_in_range = db.session.query(func.count(Customer.id)).filter(
        Customer.tenant_id == tenant_id,
        func.date(Customer.created_at).between(start_date, end_date),
    ).scalar() or 0
    new_buyers_in_range = db.session.query(func.count(Buyer.id)).filter(
        Buyer.tenant_id == tenant_id,
        func.date(Buyer.created_at).between(start_date, end_date),
    ).scalar() or 0
    inferred_new_accounts = int(new_customers_in_range + new_buyers_in_range)
    new_accounts = int(new_customers_override) if new_customers_override is not None else inferred_new_accounts

    inferred_marketing_spend = _safe_float(
        db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.tenant_id == tenant_id,
            Transaction.transaction_type == TransactionType.EXPENSE,
            Transaction.status == TransactionStatus.POSTED.value,
            Transaction.cost_class == CostClass.CUSTOMER_ACQUISITION,
            func.date(Transaction.timestamp).between(start_date, end_date),
        ).scalar()
    )
    marketing_spend = float(marketing_spend_override) if marketing_spend_override is not None else inferred_marketing_spend

    cac = (marketing_spend / new_accounts) if new_accounts > 0 else None
    ltv_to_cac_ratio = (realized_ltv / cac) if cac and cac > 0 else None
    ratio_status = _classify_ltv_cac_ratio(ltv_to_cac_ratio)

    zero_price_delivery_count, zero_price_liters = db.session.query(
        func.count(Delivery.id),
        func.coalesce(func.sum(Delivery.billable_liters), 0),
    ).filter(
        Delivery.tenant_id == tenant_id,
        Delivery.date.between(start_date, end_date),
        Delivery.billable_liters > 0,
        Delivery.price_per_liter == 0,
    ).one()

    return {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'months': month_span,
        },
        'inputs': {
            'marketing_spend_kes': round(marketing_spend, 2),
            'new_customers_acquired': int(new_accounts),
            'customer_lifespan_months': round(customer_lifespan_months, 2),
            'acquisition_spend_source': 'override' if marketing_spend_override is not None else 'classified_acquisition_expenses',
            'new_customers_source': 'override' if new_customers_override is not None else 'inferred_created_accounts',
            'lifespan_source': 'override' if lifespan_months_override is not None else 'period_months_proxy',
        },
        'operational': {
            'active_accounts_total': total_active_accounts,
            'active_b2c_customers': int(b2c_customer_count),
            'active_b2b_buyers': int(b2b_customer_count),
            'liters_sold_total': round(total_liters_sold, 2),
            'liters_per_month_per_account': round(liters_per_month_per_account, 4),
            'revenue_total_kes': round(total_revenue, 2),
            'revenue_b2c_deliveries_kes': round(revenue_b2c, 2),
            'revenue_b2b_sales_kes': round(revenue_b2b, 2),
            'production_cost_total_kes': round(production_cost_total, 2),
            'production_cost_per_liter_kes': round(production_cost_per_liter, 4),
            'realized_contribution_total_kes': round(realized_contribution_total, 2),
            'gross_margin_per_liter_kes': round(gross_margin_per_liter, 4),
        },
        'receivables': {
            'current_net_balance_kes': round(receivables_net, 2),
            'current_outstanding_kes': round(receivables_outstanding, 2),
            'current_customer_credit_kes': round(customer_credit_total, 2),
            'as_of': date.today().isoformat(),
            'scope': 'current_account_balances_not_period_revenue',
        },
        'results': {
            'cac_kes': round(cac, 4) if cac is not None else None,
            'ltv_kes': round(realized_ltv, 4),
            'realized_ltv_kes': round(realized_ltv, 4),
            'forecast_ltv_kes': round(forecast_ltv, 4),
            'ltv_to_cac_ratio': round(ltv_to_cac_ratio, 4) if ltv_to_cac_ratio is not None else None,
            'benchmark_status': ratio_status,
        },
        'customer_economics': customer_economics,
        'data_quality': {
            'zero_price_delivery_count': int(zero_price_delivery_count),
            'zero_price_billable_liters': round(_safe_float(zero_price_liters), 2),
            'has_recorded_production_costs': production_cost_total > 0,
            'has_recorded_marketing_spend': marketing_spend > 0,
            'cost_allocation_method': 'classified_cogs_per_liter',
            'ltv_basis': 'observed_period_contribution_per_active_account',
        },
        'benchmarks': {
            'under_1_to_1': 'losing_money',
            'around_2_to_1': 'acceptable_for_expansion',
            'between_3_and_4': 'highly_optimized',
        },
    }


@reports_bp.route('/api/reports/milk-inventory', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_MANAGER, Role.ADMIN)
def milk_inventory_report():
    """
    Provides a historical report of milk produced vs. sold over a date range.
    """
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    end_date = _parse_date_param('end_date', date.today())
    start_date = _parse_date_param('start_date', end_date - timedelta(days=29))

    # 1. Get daily production of saleable milk
    production_data = db.session.query(
        func.date(MilkLog.timestamp).label('date'),
        func.sum(MilkLog.amount_liters).label('total_produced')
    ).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.is_saleable.is_(True),
        func.date(MilkLog.timestamp).between(start_date, end_date)
    ).group_by('date').all()

    # 2. Get daily sales to buyers
    buyer_sales_data = db.session.query(
        SalesLedger.date.label('date'),
        func.sum(SalesLedger.liters_sold).label('total_sold')
    ).filter(
        SalesLedger.tenant_id == tenant_id,
        SalesLedger.date.between(start_date, end_date)
    ).group_by('date').all()

    # 3. Get daily sales to customers (deliveries)
    customer_sales_data = db.session.query(
        Delivery.date.label('date'),
        func.sum(Delivery.billable_liters).label('total_sold')
    ).filter(
        Delivery.tenant_id == tenant_id,
        Delivery.date.between(start_date, end_date)
    ).group_by('date').all()

    # 4. Combine results in Python for flexibility
    report = {}
    for row in production_data:
        report.setdefault(row.date, {'produced': 0, 'sold': 0})['produced'] += float(row.total_produced)
    for row in buyer_sales_data:
        report.setdefault(row.date, {'produced': 0, 'sold': 0})['sold'] += float(row.total_sold)
    for row in customer_sales_data:
        report.setdefault(row.date, {'produced': 0, 'sold': 0})['sold'] += float(row.total_sold)

    # 5. Format for response and calculate summaries
    daily_records = []
    total_produced, total_sold = 0.0, 0.0

    for day, data in sorted(report.items(), key=lambda item: item[0], reverse=True):
        produced, sold = data['produced'], data['sold']
        daily_records.append({
            'date': day.isoformat(),
            'total_produced': round(produced, 2),
            'total_sold': round(sold, 2),
            'total_unsold': round(produced - sold, 2)
        })
        total_produced += produced
        total_sold += sold

    summary = {
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'total_produced': round(total_produced, 2),
        'total_sold': round(total_sold, 2),
        'total_unsold': round(total_produced - total_sold, 2)
    }

    return jsonify({'summary': summary, 'daily_records': daily_records}), 200


@reports_bp.route('/api/reports/dairy-unit-economics', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_MANAGER, Role.ADMIN)
def dairy_unit_economics_report():
    """Returns tenant-scoped dairy CAC/LTV/unit economics metrics for a date range."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    end_date = _parse_date_param('end_date', date.today())
    start_date = _parse_date_param('start_date', end_date - timedelta(days=89))
    if end_date < start_date:
        return jsonify({'error': 'end_date cannot be earlier than start_date.'}), 400

    marketing_spend_override = request.args.get('marketing_spend_kes', type=float)
    new_customers_override = request.args.get('new_customers_acquired', type=int)
    lifespan_months_override = request.args.get('customer_lifespan_months', type=float)

    report = _build_dairy_unit_economics_for_tenant(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        marketing_spend_override=marketing_spend_override,
        new_customers_override=new_customers_override,
        lifespan_months_override=lifespan_months_override,
    )

    return jsonify(report), 200


@reports_bp.route('/api/reports/dairy-unit-economics/by-farm', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_MANAGER, Role.ADMIN)
def dairy_unit_economics_by_farm_report():
    """
    Returns one row per farm with unit economics metrics.
    Note: financial and milk sales tables are currently tenant-scoped, so per-farm
    attribution is a mirrored tenant metric until farm_id is added to source tables.
    """
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    end_date = _parse_date_param('end_date', date.today())
    start_date = _parse_date_param('start_date', end_date - timedelta(days=89))
    if end_date < start_date:
        return jsonify({'error': 'end_date cannot be earlier than start_date.'}), 400

    farms = db.session.query(Farm).filter(Farm.tenant_id == tenant_id).order_by(Farm.id.asc()).all()
    tenant_report = _build_dairy_unit_economics_for_tenant(
        tenant_id=tenant_id,
        start_date=start_date,
        end_date=end_date,
        marketing_spend_override=request.args.get('marketing_spend_kes', type=float),
        new_customers_override=request.args.get('new_customers_acquired', type=int),
        lifespan_months_override=request.args.get('customer_lifespan_months', type=float),
    )

    rows = [
        {
            'farm_id': farm.id,
            'farm_name': farm.name,
            'is_active': bool(farm.is_active),
            'metrics': tenant_report,
            'attribution_limited': True,
            'attribution_note': 'Metrics are tenant-scoped because finance and milk sales records currently do not include farm_id.',
        }
        for farm in farms
    ]

    return jsonify({
        'period': tenant_report['period'],
        'farm_count': len(rows),
        'attribution_mode': 'tenant_scoped_mirrored_per_farm',
        'items': rows,
    }), 200


@reports_bp.route('/api/reports/dairy-unit-economics/calculator', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_MANAGER, Role.ADMIN)
def dairy_unit_economics_calculator():
    """Direct dairy unit economics calculator from explicit user inputs."""
    payload = request.get_json(silent=True) or {}

    required_fields = [
        'sales_marketing_spend_kes',
        'new_customers_acquired',
        'liters_purchased_per_month',
        'gross_margin_per_liter_kes',
        'customer_lifespan_months',
    ]
    missing = [field for field in required_fields if field not in payload]
    if missing:
        return jsonify({'error': f"Missing required fields: {', '.join(missing)}"}), 400

    try:
        sales_marketing_spend = float(payload['sales_marketing_spend_kes'])
        new_customers = int(payload['new_customers_acquired'])
        liters_per_month = float(payload['liters_purchased_per_month'])
        gross_margin_per_liter = float(payload['gross_margin_per_liter_kes'])
        lifespan_months = float(payload['customer_lifespan_months'])
    except (TypeError, ValueError):
        return jsonify({'error': 'All calculator inputs must be numeric.'}), 400

    if sales_marketing_spend < 0 or new_customers < 0 or liters_per_month < 0 or lifespan_months < 0:
        return jsonify({'error': 'Inputs cannot be negative.'}), 400

    cac = (sales_marketing_spend / new_customers) if new_customers > 0 else None
    ltv = liters_per_month * gross_margin_per_liter * lifespan_months
    ratio = (ltv / cac) if cac and cac > 0 else None

    return jsonify({
        'inputs': {
            'sales_marketing_spend_kes': round(sales_marketing_spend, 2),
            'new_customers_acquired': new_customers,
            'liters_purchased_per_month': round(liters_per_month, 4),
            'gross_margin_per_liter_kes': round(gross_margin_per_liter, 4),
            'customer_lifespan_months': round(lifespan_months, 4),
        },
        'results': {
            'cac_kes': round(cac, 4) if cac is not None else None,
            'ltv_kes': round(ltv, 4),
            'ltv_to_cac_ratio': round(ratio, 4) if ratio is not None else None,
            'benchmark_status': _classify_ltv_cac_ratio(ratio),
        },
        'benchmarks': {
            'under_1_to_1': 'losing_money',
            'around_2_to_1': 'acceptable_for_expansion',
            'between_3_and_4': 'highly_optimized',
        },
    }), 200


@reports_bp.route('/api/reports/animal-economics/<int:cow_id>', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_MANAGER, Role.ADMIN)
def animal_economics_report(cow_id: int):
    """Returns lifecycle economics for one animal without altering customer metrics."""
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant context.'}), 400

    try:
        report = AnimalEconomicsService().get_animal_economics(tenant_id=tenant_id, cow_id=cow_id)
    except LookupError:
        return jsonify({'error': 'Animal not found.'}), 404
    return jsonify(report), 200
