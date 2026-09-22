from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func

from app import db
from app.services.finance_service import FinanceService
from app.models.supply import InventoryItem, InventoryTransaction, MilkLog
from app.models.livestock import Cow
from app.repositories.milk_disposition_repo import MilkInventoryRepository
from app.utils.jwt_payload import parse_public_int_id

dashboard_bp = Blueprint('dashboard', __name__)


def _parse_tenant_header(value):
    if not value:
        return None

    try:
        return parse_public_int_id(value, 'tenant_')
    except (TypeError, ValueError, AttributeError):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def _get_current_tenant_id():
    claims = get_jwt() or {}
    candidates = [
        getattr(g, 'tenant_id', None),
        claims.get('tenant_id'),
    ]

    for candidate in candidates:
        parsed = _parse_tenant_header(candidate)
        if parsed is not None:
            return parsed
    return None


def _resolve_tenant_id_from_context_or_header():
    tenant_id = _get_current_tenant_id()
    if tenant_id is None:
        return None, (jsonify({"error": "Missing or invalid tenant context."}), 403)

    header_tenant_id = _parse_tenant_header(request.headers.get('X-Tenant-ID'))
    if request.headers.get('X-Tenant-ID') and header_tenant_id is None:
        return None, (jsonify({"error": "Invalid X-Tenant-ID header."}), 400)

    if header_tenant_id is not None and header_tenant_id != tenant_id:
        return None, (jsonify({"error": "Tenant context mismatch."}), 403)

    return tenant_id, None


@dashboard_bp.route('/api/v1/dashboard/summary', methods=['GET'])
@jwt_required()
def get_command_center_summary():
    tenant_id, tenant_error = _resolve_tenant_id_from_context_or_header()
    if tenant_error:
        return tenant_error

    try:
        # Delegate financial calculations to the single source of truth, FinanceService.
        # This ensures both dashboards (/api/production/summary and /api/v1/dashboard/summary)
        # show the exact same financial metrics.
        financial_summary = FinanceService.get_daily_financial_summary(tenant_id)

        today_revenue = financial_summary['revenue_total_kes']
        feed_cost = financial_summary['feed_cost_total_kes']

        return jsonify({
            "today_revenue_kes": int(today_revenue),
            "today_feed_cost_kes": int(feed_cost),
            "today_total_costs_kes": int(financial_summary['total_costs_kes']),
            "net_margin_kes": int(financial_summary['net_margin_kes']),
        }), 200

    except Exception as e:
        current_app.logger.error(f"Dashboard aggregation failed for tenant {tenant_id}: {str(e)}")
        return jsonify({"error": "An internal server error occurred while generating the dashboard."}), 500


@dashboard_bp.route('/api/production/summary', methods=['GET'])
@jwt_required()
def get_production_summary():
    tenant_id, tenant_error = _resolve_tenant_id_from_context_or_header()
    if tenant_error:
        return tenant_error

    # Delegate financial calculations to the single source of truth.
    financial_summary = FinanceService.get_daily_financial_summary(tenant_id)
    revenue_total = financial_summary.get('revenue_total_kes', 0)
    feed_cost = financial_summary.get('feed_cost_total_kes', 0)
    total_costs = financial_summary.get('total_costs_kes', feed_cost)
    net_margin = financial_summary.get('net_margin_kes', 0)

    from app.models.finance import SalesLedger, Delivery

    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    next_day = start_of_day + timedelta(days=1)

    milk_inventory = MilkInventoryRepository.summary_for_date(tenant_id=tenant_id, inventory_date=today)
    total_liters = milk_inventory['produced_liters']
    saleable_liters = milk_inventory['medically_saleable_liters']

    # Calculate total milk sold today from both buyer and customer sales channels
    total_sold_buyers = db.session.query(func.coalesce(func.sum(SalesLedger.liters_sold), 0)).filter(
        SalesLedger.tenant_id == tenant_id,
        SalesLedger.date == today,
    ).scalar() or 0

    total_sold_customers = db.session.query(func.coalesce(func.sum(Delivery.billable_liters), 0)).filter(
        Delivery.tenant_id == tenant_id,
        Delivery.date == today,
    ).scalar() or 0

    total_sold = float(total_sold_buyers) + float(total_sold_customers)
    remaining_milk = float(milk_inventory['remaining_liters'])

    cows_milked = db.session.query(func.count(func.distinct(MilkLog.cow_id))).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
    ).scalar() or 0

    avg_per_cow = round(float(total_liters) / int(cows_milked), 1) if cows_milked else 0.0
    profit_per_liter = float(net_margin) / float(saleable_liters) if float(saleable_liters) > 0 else 0.0

    alert_count = db.session.query(func.count(Cow.id)).filter(
        Cow.is_active.is_(True),
        Cow.status.in_(['Calf', 'Heifer', 'Lactating', 'Dry']),
    ).scalar() or 0

    return jsonify({
        'date': today.isoformat(),
        'production_total_liters': float(total_liters),
        'saleable_liters': float(saleable_liters),
        'total_sold_liters': total_sold,
        'calf_fed_liters': float(milk_inventory['disposition_liters']),
        'personal_consumption_liters': float(
            milk_inventory['customer_delivery_liters'] - Decimal(str(total_sold_customers))
        ),
        'remaining_milk_liters': remaining_milk,
        'revenue_total_kes': float(revenue_total),
        'feed_cost_total_kes': float(feed_cost),
        'total_costs_kes': float(total_costs),
        'net_margin_kes': float(net_margin),
        'operational_alerts': int(alert_count),
        'cows_milked': int(cows_milked),
        'avg_per_cow': avg_per_cow,
        'profit_per_liter': profit_per_liter,
        # Frontend-friendly aliases for dashboard cards.
        'total_liters': float(total_liters),
        'total_milk_today': float(total_liters),
        'cowsMilked': int(cows_milked),
        'avgPerCow': avg_per_cow,
        'profitPerLiter': profit_per_liter,
    }), 200


@dashboard_bp.route('/api/dashboard', methods=['GET'])
@jwt_required()
def get_dashboard_alias():
    """Provides a simple, intuitive alias for the main production summary dashboard."""
    # This endpoint serves as a friendly alias for the more specific /api/production/summary route.
    return get_production_summary()
