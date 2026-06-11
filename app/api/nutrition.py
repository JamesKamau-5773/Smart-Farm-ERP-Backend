from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.user import Role
from app.services.nutrition_service import NutritionService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id

"""
Nutrition API Contracts

POST /api/v1/nutrition/batches
- Body: {
        "batchName": str,
        "formulaId": int|null,
        "isSavedAsTemplate": bool,
        "formulaName": str,
        "totalWeight": number,
        "totalCost": number,
        "costPerKg": number,
        "ingredients": [{
            "ingredientId": int,
            "weight": number,
            "percentage": number|null,
            "lockedCostPerKg": number|null
        }]
    }
- Response 201: {
        "message": str,
        "batchId": int,
        "formulaId": int|null,
        "status": "ACTIVE"|"DEPLETED"|"VOIDED",
        "inventory": [{"ingredientId": int, "ingredientName": str, "weight": number, "remainingStock": number}]
    }

POST /api/v1/nutrition/batches/{batch_id}/consumption-events
- Body: {"consumedWeight": number, "consumedOn": "YYYY-MM-DD"}
- Response 200: {
        "message": str,
        "batchId": int,
        "batchStatus": "ACTIVE"|"DEPLETED",
        "consumedWeight": number,
        "totalConsumedWeight": number,
        "remainingWeight": number,
        "depletedOn": "YYYY-MM-DD"|null
    }

GET /api/v1/nutrition/analytics/feed-cost-efficiency?saleable_only=true|false
- Response 200: {
        "saleableOnly": bool,
        "rows": [{
            "batchId": int,
            "batchName": str,
            "mixedOn": "YYYY-MM-DD",
            "depletedOn": "YYYY-MM-DD"|null,
            "lagWindowStart": "YYYY-MM-DD",
            "lagWindowEnd": "YYYY-MM-DD",
            "totalBatchCost": number,
            "totalMilkLiters": number,
            "costPerLiter": number
        }]
    }

GET /api/v1/nutrition/analytics/active-batch-roi-trend-weekly?saleable_only=true|false
- Response 200: {
        "saleableOnly": bool,
        "rows": [{
            "weekStart": "YYYY-MM-DD",
            "activeBatches": int,
            "totalFeedCost": number,
            "totalMilkLiters": number,
            "feedCostPerLiter": number,
            "roiLitersPerKes": number
        }]
    }
"""

nutrition_bp = Blueprint('nutrition', __name__, url_prefix='/api/v1/nutrition')


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


def _parse_bool_query(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


@nutrition_bp.route('/batches', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def process_and_save_batch():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    user_id_raw = get_jwt_identity()
    try:
        user_id = int(user_id_raw) if user_id_raw is not None else None
    except (TypeError, ValueError):
        user_id = None

    data = request.get_json() or {}
    return NutritionService.process_and_save_batch(tenant_id=tenant_id, user_id=user_id, data=data)


@nutrition_bp.route('/batches/<int:batch_id>/consumption-events', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def record_batch_consumption_event(batch_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    user_id_raw = get_jwt_identity()
    try:
        user_id = int(user_id_raw) if user_id_raw is not None else None
    except (TypeError, ValueError):
        user_id = None

    data = request.get_json() or {}
    return NutritionService.record_consumption_event(
        tenant_id=tenant_id,
        batch_id=batch_id,
        user_id=user_id,
        data=data,
    )


@nutrition_bp.route('/analytics/feed-cost-efficiency', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def feed_cost_efficiency():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    saleable_only = _parse_bool_query(request.args.get('saleable_only'), default=False)
    return NutritionService.get_feed_cost_efficiency(tenant_id=tenant_id, saleable_only=saleable_only)


@nutrition_bp.route('/analytics/active-batch-roi-trend-weekly', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def active_batch_roi_trend_weekly():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    saleable_only = _parse_bool_query(request.args.get('saleable_only'), default=False)
    return NutritionService.get_weekly_active_batch_roi_trend(tenant_id=tenant_id, saleable_only=saleable_only)
