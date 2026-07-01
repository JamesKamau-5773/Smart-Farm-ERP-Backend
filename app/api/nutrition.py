from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.user import Role
from app.services.nutrition_service import NutritionService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.supply import FeedRecipe, RecipeIngredient, Ingredient, FarmMeasurementUnit
from app import db
from sqlalchemy import func

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
nutrition_alias_bp = Blueprint('nutrition_alias', __name__)


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


@nutrition_bp.route('/dashboard', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def nutrition_dashboard():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    active_recipes = FeedRecipe.query.filter_by(tenant_id=tenant_id, is_active=True).count()
    ingredient_count = Ingredient.query.filter_by(tenant_id=tenant_id).count()
    return jsonify({'tenant_id': tenant_id, 'active_recipes': active_recipes, 'ingredient_count': ingredient_count}), 200


@nutrition_alias_bp.route('/api/nutrition/dashboard', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def nutrition_dashboard_alias():
    return nutrition_dashboard()


@nutrition_bp.route('/recipes', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_recipes():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    recipes = FeedRecipe.query.filter_by(tenant_id=tenant_id).order_by(FeedRecipe.id.desc()).all()
    return jsonify([
        {
            'id': recipe.id,
            'tenant_id': recipe.tenant_id,
            'name': recipe.recipe_name,
            'target_protein_percentage': float(recipe.target_protein_percentage),
            'is_active': recipe.is_active,
            'ingredients': [
                {'ingredient_id': ri.inventory_item_id, 'inclusion_percentage': float(ri.inclusion_percentage)}
                for ri in recipe.ingredients
            ],
        }
        for recipe in recipes
    ]), 200


@nutrition_alias_bp.route('/api/feed/recipes', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_recipes_alias():
    return list_recipes()


@nutrition_bp.route('/recipes', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_recipe():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    data = request.get_json() or {}
    recipe_name = (data.get('name') or data.get('recipe_name') or '').strip()
    if not recipe_name:
        return jsonify({'error': 'name is required.'}), 400
    recipe = FeedRecipe(tenant_id=tenant_id, recipe_name=recipe_name, target_protein_percentage=data.get('target_protein_percentage', 0), is_active=bool(data.get('is_active', True)))
    db.session.add(recipe)
    db.session.flush()
    for ingredient in data.get('ingredients', []):
        db.session.add(RecipeIngredient(tenant_id=tenant_id, recipe_id=recipe.id, inventory_item_id=ingredient['inventory_item_id'], inclusion_percentage=ingredient['inclusion_percentage']))
    db.session.commit()
    return jsonify({'id': recipe.id, 'name': recipe.recipe_name}), 201


@nutrition_alias_bp.route('/api/feed/recipes', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_recipe_alias():
    return create_recipe()


@nutrition_bp.route('/recipes/<int:recipe_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_recipe(recipe_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    recipe = FeedRecipe.query.filter_by(id=recipe_id, tenant_id=tenant_id).first()
    if not recipe:
        return jsonify({'error': 'Recipe not found.'}), 404
    data = request.get_json() or {}
    if 'name' in data:
        recipe.recipe_name = (data.get('name') or '').strip() or recipe.recipe_name
    if 'target_protein_percentage' in data:
        recipe.target_protein_percentage = data.get('target_protein_percentage')
    if 'is_active' in data:
        recipe.is_active = bool(data.get('is_active'))
    db.session.commit()
    return jsonify({'id': recipe.id, 'name': recipe.recipe_name, 'is_active': recipe.is_active}), 200


@nutrition_alias_bp.route('/api/feed/recipes/<int:recipe_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_recipe_alias(recipe_id):
    return update_recipe(recipe_id)


@nutrition_bp.route('/recipes/<int:recipe_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_recipe(recipe_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    recipe = FeedRecipe.query.filter_by(id=recipe_id, tenant_id=tenant_id).first()
    if not recipe:
        return jsonify({'error': 'Recipe not found.'}), 404
    db.session.delete(recipe)
    db.session.commit()
    return jsonify({'message': 'Recipe deleted successfully.'}), 200


@nutrition_alias_bp.route('/api/feed/recipes/<int:recipe_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_recipe_alias(recipe_id):
    return delete_recipe(recipe_id)


@nutrition_bp.route('/feed/formulate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def formulate_feed():
    return process_and_save_batch()


@nutrition_alias_bp.route('/api/feed/formulate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def formulate_feed_alias():
    return formulate_feed()


@nutrition_bp.route('/units/conversions', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_units_conversions():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    units = FarmMeasurementUnit.query.filter_by(tenant_id=tenant_id).all()
    return jsonify([
        {'id': unit.id, 'item_id': unit.item_id, 'unit_name': unit.unit_name, 'kg_equivalent': float(unit.kg_equivalent)}
        for unit in units
    ]), 200


@nutrition_alias_bp.route('/api/units/conversions', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_units_conversions_alias():
    return list_units_conversions()


@nutrition_bp.route('/units/conversions', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_unit_conversion():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    data = request.get_json() or {}
    if not data.get('item_id') or not data.get('unit_name') or data.get('kg_equivalent') is None:
        return jsonify({'error': 'item_id, unit_name, and kg_equivalent are required.'}), 400
    unit = FarmMeasurementUnit(tenant_id=tenant_id, item_id=data['item_id'], unit_name=data['unit_name'], kg_equivalent=data['kg_equivalent'])
    db.session.add(unit)
    db.session.commit()
    return jsonify({'id': unit.id, 'item_id': unit.item_id, 'unit_name': unit.unit_name, 'kg_equivalent': float(unit.kg_equivalent)}), 201


@nutrition_alias_bp.route('/api/units/conversions', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_unit_conversion_alias():
    return create_unit_conversion()


@nutrition_bp.route('/feed/costing', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def feed_costing():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    rows = db.session.query(func.coalesce(func.sum(FeedRecipe.target_protein_percentage), 0)).filter(FeedRecipe.tenant_id == tenant_id).scalar() or 0
    return jsonify({'tenant_id': tenant_id, 'feed_costing_total': float(rows)}), 200


@nutrition_alias_bp.route('/api/feed/costing', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def feed_costing_alias():
    return feed_costing()
