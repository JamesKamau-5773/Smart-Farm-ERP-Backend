from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required, get_jwt
from sqlalchemy import func

from app import db
from app.models.supply import InventoryItem, InventoryTransaction, MilkLog
from app.models.livestock import Cow
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

    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time())
    next_day = start_of_day + timedelta(days=1)

    milk_price = Decimal(str(current_app.config.get('STANDARD_MILK_PRICE_KES', 55.00)))

    try:
        milk_result = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
            MilkLog.tenant_id == tenant_id,
            MilkLog.timestamp >= start_of_day,
            MilkLog.timestamp < next_day,
        ).scalar()
        liters = Decimal(str(milk_result or 0))
        today_revenue = (liters * milk_price).quantize(Decimal('1'))

        feed_cost = db.session.query(func.coalesce(func.sum(InventoryTransaction.total_transaction_value), 0)).join(
            InventoryItem,
            InventoryTransaction.item_id == InventoryItem.id,
        ).filter(
            InventoryItem.tenant_id == tenant_id,
            InventoryTransaction.transaction_type == 'OUT',
            InventoryTransaction.transaction_date >= start_of_day,
            InventoryTransaction.transaction_date < next_day,
        ).scalar()
        feed_cost = Decimal(str(feed_cost or 0)).quantize(Decimal('1'))

        return jsonify({
            "today_revenue_kes": int(today_revenue),
            "today_feed_cost_kes": int(feed_cost),
            "net_margin_kes": int(today_revenue - feed_cost),
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

    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    next_day = start_of_day + timedelta(days=1)

    total_liters = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
    ).scalar() or 0

    feed_cost = db.session.query(func.coalesce(func.sum(InventoryTransaction.total_transaction_value), 0)).join(
        InventoryItem,
        InventoryTransaction.item_id == InventoryItem.id,
    ).filter(
        InventoryItem.tenant_id == tenant_id,
        InventoryTransaction.transaction_type == 'OUT',
        InventoryTransaction.transaction_date >= start_of_day,
        InventoryTransaction.transaction_date < next_day,
    ).scalar() or 0

    saleable_liters = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
        MilkLog.is_saleable.is_(True),
    ).scalar() or 0

    cows_milked = db.session.query(func.count(func.distinct(MilkLog.cow_id))).filter(
        MilkLog.tenant_id == tenant_id,
        MilkLog.timestamp >= start_of_day,
        MilkLog.timestamp < next_day,
    ).scalar() or 0

    avg_per_cow = float(total_liters) / int(cows_milked) if cows_milked else 0.0
    revenue_total = int(float(saleable_liters) * float(current_app.config.get('STANDARD_MILK_PRICE_KES', 55.0)))
    net_margin = revenue_total - int(feed_cost)
    profit_per_liter = net_margin / float(saleable_liters) if float(saleable_liters) > 0 else 0.0

    alert_count = db.session.query(func.count(Cow.id)).filter(
        Cow.is_active.is_(True),
        Cow.current_status.in_(['Calf', 'Heifer', 'Lactating', 'Dry']),
    ).scalar() or 0

    return jsonify({
        'date': today.isoformat(),
        'production_total_liters': float(total_liters),
        'saleable_liters': float(saleable_liters),
        'revenue_total_kes': revenue_total,
        'feed_cost_total_kes': int(feed_cost),
        'net_margin_kes': net_margin,
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
