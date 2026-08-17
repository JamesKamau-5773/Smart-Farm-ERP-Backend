from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func

from app import db
from app.models.finance import Delivery, SalesLedger
from app.models.supply import MilkLog
from app.models.user import Role
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