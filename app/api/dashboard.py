from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, request, jsonify, current_app, g
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from app import db
from app.models.supply import InventoryItem, InventoryTransaction, MilkLog
from app.utils.decorators import require_tenant_context
from app.utils.jwt_payload import parse_public_int_id

dashboard_bp = Blueprint('dashboard', __name__)


def _get_current_tenant_id():
    tenant_public_id = getattr(g, 'tenant_id', None)
    if not tenant_public_id:
        return None

    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@dashboard_bp.route('/api/v1/dashboard/summary', methods=['GET'])
@jwt_required()
@require_tenant_context
def get_command_center_summary():
    tenant_id = request.args.get('tenant_id')

    if not tenant_id or not str(tenant_id).isdigit():
        return jsonify({"error": "Valid tenant_id is required"}), 400

    tenant_id = int(tenant_id)
    current_tenant_id = _get_current_tenant_id()
    if current_tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    if tenant_id != current_tenant_id:
        return jsonify({"error": "Tenant context mismatch."}), 403

    today = datetime.utcnow().date()
    start_of_day = datetime.combine(today, datetime.min.time())
    next_day = start_of_day + timedelta(days=1)

    milk_price = Decimal(str(current_app.config.get('STANDARD_MILK_PRICE_KES', 55.00)))

    try:
        milk_result = db.session.query(func.coalesce(func.sum(MilkLog.amount_liters), 0)).filter(
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
