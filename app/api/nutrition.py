from __future__ import annotations
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.user import Role
from app.services.nutrition_service import NutritionService
from app.services.animal_yield_target_service import AnimalYieldTargetService
from app.services.recipe_formulation_service import RecipeFormulationService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.supply import FeedRecipe, RecipeIngredient, Ingredient, FarmMeasurementUnit, InventoryItem
from app import db
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

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


def _normalize_recipe_ingredients(raw_items):
    normalized = []
    for item in raw_items or []:
        if not isinstance(item, dict):
            continue
        ingredient_id = item.get('ingredient_id')
        if ingredient_id is None:
            ingredient_id = item.get('ingredientId')
        if ingredient_id is None:
            ingredient_id = item.get('id')
        if ingredient_id not in (None, ''):
            try:
                ingredient_id = int(ingredient_id)
            except (TypeError, ValueError):
                ingredient_id = None

        percentage = item.get('percentage')
        if percentage is None:
            percentage = item.get('inclusion_percentage')
        if percentage is None:
            percentage = item.get('inclusionPercentage')
        if percentage not in (None, ''):
            try:
                percentage = float(percentage)
            except (TypeError, ValueError):
                percentage = None

        normalized.append({
            'ingredient_id': ingredient_id,
            'percentage': percentage,
        })
    return normalized


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
    try:
        recipe = FeedRecipe(tenant_id=tenant_id, recipe_name=recipe_name, target_protein_percentage=data.get('target_protein_percentage', 0), is_active=bool(data.get('is_active', True)))
        db.session.add(recipe)
        db.session.flush()
        for ingredient in data.get('ingredients', []):
            inventory_item_id = ingredient.get('inventory_item_id')
            if inventory_item_id is None:
                db.session.rollback()
                return jsonify({'error': 'inventory_item_id is required for each ingredient.'}), 400
            inventory_item = InventoryItem.query.filter_by(id=inventory_item_id, tenant_id=tenant_id).first()
            if not inventory_item:
                db.session.rollback()
                return jsonify({'error': f'Inventory item {inventory_item_id} not found for this tenant.'}), 404
            db.session.add(RecipeIngredient(tenant_id=tenant_id, recipe_id=recipe.id, inventory_item_id=ingredient['inventory_item_id'], inclusion_percentage=ingredient['inclusion_percentage']))
        db.session.commit()
        return jsonify({'id': recipe.id, 'name': recipe.recipe_name}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Recipe already exists for this tenant.'}), 409


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
    try:
        unit = FarmMeasurementUnit(tenant_id=tenant_id, item_id=data['item_id'], unit_name=data['unit_name'], kg_equivalent=data['kg_equivalent'])
        db.session.add(unit)
        db.session.commit()
        return jsonify({'id': unit.id, 'item_id': unit.item_id, 'unit_name': unit.unit_name, 'kg_equivalent': float(unit.kg_equivalent)}), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Unit conversion already exists for this tenant.'}), 409


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


# ============================================================================
# Animal Yield Target Endpoints (Per-Cow Milk Production Targets)
# ============================================================================

@nutrition_bp.route('/animals/<int:cow_id>/yield-target', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def set_cow_yield_target(cow_id):
    """Set or update milk production target for a specific cow.
    
    Request body:
    {
        "target_liters": 2.5
    }
    
    Response 201:
    {
        "target_id": int,
        "cow_id": int,
        "tag_number": str,
        "target_liters": float,
        "status": "Active",
        "warnings": [str]
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    target_liters = data.get('target_liters')

    if target_liters is None:
        return jsonify({'error': 'target_liters is required.'}), 400

    try:
        result = AnimalYieldTargetService.set_yield_target(
            tenant_id=tenant_id,
            cow_id=cow_id,
            target_liters=target_liters
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to set yield target.', 'details': str(e)}), 500


@nutrition_alias_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND)
def set_cow_yield_target_alias(cow_id):
    return set_cow_yield_target(cow_id)


@nutrition_bp.route('/animals/<int:cow_id>/yield-target', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_cow_yield_target(cow_id):
    """Get milk production target for a specific cow.
    
    Response 200:
    {
        "target_id": int,
        "cow_id": int,
        "tag_number": str,
        "target_liters": float,
        "times_to_feed_daily": int,
        "base_herd_feed_kg": float,
        "milking_topup_kg": float,
        "status": "Active"
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        result = AnimalYieldTargetService.get_cow_target(
            tenant_id=tenant_id,
            cow_id=cow_id
        )
        if result is None:
            return jsonify({'error': 'Yield target not found for this cow.'}), 404
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'error': 'Failed to retrieve yield target.', 'details': str(e)}), 500


@nutrition_alias_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_cow_yield_target_alias(cow_id):
    return get_cow_yield_target(cow_id)


@nutrition_bp.route('/herd/yield-targets', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_herd_yield_targets():
    """List all active yield targets for the herd.
    
    Response 200:
    {
        "total_cows": int,
        "targets": [
            {
                "target_id": int,
                "cow_id": int,
                "tag_number": str,
                "cow_name": str,
                "target_liters": float,
                "times_to_feed_daily": int,
                "status": "Active"
            }
        ]
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        targets = AnimalYieldTargetService.list_herd_targets(tenant_id=tenant_id)
        return jsonify({
            'total_cows': len(targets),
            'targets': targets
        }), 200
    except Exception as e:
        return jsonify({'error': 'Failed to retrieve herd targets.', 'details': str(e)}), 500


@nutrition_alias_bp.route('/api/v1/herd/yield-targets', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_herd_yield_targets_alias():
    return list_herd_yield_targets()


@nutrition_bp.route('/herd/feeding-plan', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def calculate_herd_feeding_plan():
    """Calculate aggregated feeding plan based on per-cow yield targets.
    
    Query parameters (optional):
        baseline_herd_meal_kg: float (default 4.0)
        milking_frequency: int (2, 3, or 4) - leave null for auto
    
    Response 200:
    {
        "total_herd_target_liters": float,
        "total_meal_needed_kg": float,
        "base_herd_mix_kg": float,
        "extra_milking_topup_total_kg": float,
        "per_milking_session_kg": float,
        "suggested_yard_feedings": int,
        "used_milking_frequency": int,
        "farmer_reasoning": str,
        "number_of_cows": int,
        "per_cow_breakdown": [
            {
                "cow_id": int,
                "tag": str,
                "target_liters": float,
                "feed_allocation_kg": float,
                "topup_kg": float
            }
        ]
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    # Parse optional query parameters
    try:
        baseline_herd_meal_kg = float(request.args.get('baseline_herd_meal_kg', 4.0))
    except ValueError:
        return jsonify({'error': 'baseline_herd_meal_kg must be a valid number.'}), 400

    milking_frequency_str = request.args.get('milking_frequency')
    milking_frequency = None
    if milking_frequency_str is not None:
        try:
            milking_frequency = int(milking_frequency_str)
            if milking_frequency not in (2, 3, 4):
                return jsonify({'error': 'milking_frequency must be 2, 3, or 4.'}), 400
        except ValueError:
            return jsonify({'error': 'milking_frequency must be an integer.'}), 400

    try:
        plan = AnimalYieldTargetService.calculate_herd_feeding_plan(
            tenant_id=tenant_id,
            baseline_herd_meal_kg=baseline_herd_meal_kg,
            milking_frequency=milking_frequency,
            use_saved_targets=True
        )
        return jsonify(plan), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to calculate feeding plan.', 'details': str(e)}), 500


@nutrition_alias_bp.route('/api/v1/herd/feeding-plan', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def calculate_herd_feeding_plan_alias():
    return calculate_herd_feeding_plan()




# ============================================================================
# Recipe Formulation Endpoints - Protein Targeting & Ingredient Adjustment
# ============================================================================

@nutrition_bp.route('/recipes/formulate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def formulate_recipe_with_protein_target():
    """
    Calculate recipe with protein targeting and suggest ingredient adjustments.
    
    Body:
    {
        "batch_size_kg": number,
        "target_protein_percent": number,
        "ingredients": [
            {"ingredient_id": int, "percentage": number},
            ...
        ],
        "yield_target_id": int (optional, for linking to Milk Lab)
    }
    
    Response 200:
    {
        "current_protein_percent": number,
        "target_protein_percent": number,
        "adjustment_needed": number,
        "adjusted_ingredients": [
            {
                "ingredient_id": int,
                "name": str,
                "current_percentage": number,
                "adjusted_percentage": number,
                "adjustment": number,
                "protein_grams_per_kg": number
            },
            ...
        ],
        "projected_nutrition": {
            "batch_size_kg": number,
            "total_protein_grams": number,
            "average_protein_percent": number,
            "ingredients": [...]
        },
        "adjustment_strategy": str
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    batch_size_kg = data.get('batch_size_kg')
    target_protein_percent = data.get('target_protein_percent')
    ingredients = _normalize_recipe_ingredients(data.get('ingredients', []))
    yield_target_id = data.get('yield_target_id')

    # Validation
    if batch_size_kg is None or batch_size_kg <= 0:
        return jsonify({'error': 'batch_size_kg is required and must be > 0.'}), 400
    if target_protein_percent is None or target_protein_percent < 0 or target_protein_percent > 100:
        return jsonify({'error': 'target_protein_percent is required (0-100).'}), 400
    if not ingredients or len(ingredients) == 0:
        return jsonify({'error': 'At least one ingredient is required.'}), 400
    if any(ing.get('ingredient_id') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires ingredient_id (or ingredientId) as a number.'}), 400
    if any(ing.get('percentage') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires percentage as a number.'}), 400

    try:
        adjustments = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=tenant_id,
            batch_size_kg=float(batch_size_kg),
            base_ingredients=ingredients,
            target_protein_percent=float(target_protein_percent),
        )
        return jsonify(adjustments), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to formulate recipe.', 'details': str(e)}), 500


@nutrition_bp.route('/recipes/calculate-nutrition', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def calculate_recipe_nutrition():
    """
    Calculate current nutrition profile of a recipe.
    
    Body:
    {
        "batch_size_kg": number,
        "ingredients": [
            {"ingredient_id": int, "percentage": number},
            ...
        ]
    }
    
    Response 200:
    {
        "batch_size_kg": number,
        "ingredients": [...],
        "total_protein_grams": number,
        "average_protein_percent": number
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    batch_size_kg = data.get('batch_size_kg')
    ingredients = _normalize_recipe_ingredients(data.get('ingredients', []))

    if batch_size_kg is None or batch_size_kg <= 0:
        return jsonify({'error': 'batch_size_kg is required and must be > 0.'}), 400
    if not ingredients or len(ingredients) == 0:
        return jsonify({'error': 'At least one ingredient is required.'}), 400

    if any(ing.get('ingredient_id') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires ingredient_id (or ingredientId).'}), 400

    if any(ing.get('percentage') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires percentage.'}), 400

    try:
        nutrition = RecipeFormulationService.calculate_batch_protein_content(
            batch_size_kg=float(batch_size_kg),
            ingredients_with_percentages=ingredients,
        )
        return jsonify(nutrition), 200
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to calculate nutrition.', 'details': str(e)}), 500


@nutrition_bp.route('/recipes/auto-save', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def auto_save_recipe():
    """
    Save a formulated recipe to the database and mark as adopted.
    This automatically adopts the recipe for the herd.
    
    Body:
    {
        "recipe_name": str,
        "batch_size_kg": number,
        "target_protein_percent": number,
        "adjusted_ingredients": [
            {"ingredient_id": int, "percentage": number},
            ...
        ],
        "yield_target_id": int (optional, for linking to Milk Lab)
    }
    
    Response 201:
    {
        "recipe_id": int,
        "recipe_name": str,
        "target_protein_percent": number,
        "achieved_protein_percent": number,
        "batch_size_kg": number,
        "status": "ADOPTED",
        "message": str,
        "nutrition_summary": {...}
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    user_id = get_jwt_identity()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    recipe_name = data.get('recipe_name')
    batch_size_kg = data.get('batch_size_kg')
    target_protein_percent = data.get('target_protein_percent')
    adjusted_ingredients = _normalize_recipe_ingredients(data.get('adjusted_ingredients', []))
    yield_target_id = data.get('yield_target_id')

    # Validation
    if not recipe_name or recipe_name.strip() == '':
        return jsonify({'error': 'recipe_name is required.'}), 400
    if batch_size_kg is None or batch_size_kg <= 0:
        return jsonify({'error': 'batch_size_kg is required and must be > 0.'}), 400
    if target_protein_percent is None or target_protein_percent < 0 or target_protein_percent > 100:
        return jsonify({'error': 'target_protein_percent is required (0-100).'}), 400
    if not adjusted_ingredients or len(adjusted_ingredients) == 0:
        return jsonify({'error': 'At least one ingredient is required.'}), 400
    if any(ing.get('ingredient_id') in (None, '') for ing in adjusted_ingredients):
        return jsonify({'error': 'Each ingredient requires ingredient_id (or ingredientId) as a number.'}), 400
    if any(ing.get('percentage') in (None, '') for ing in adjusted_ingredients):
        return jsonify({'error': 'Each ingredient requires percentage as a number.'}), 400

    try:
        result = RecipeFormulationService.save_recipe_from_formulation(
            tenant_id=tenant_id,
            recipe_name=recipe_name,
            batch_size_kg=float(batch_size_kg),
            adjusted_ingredients=adjusted_ingredients,
            target_protein_percent=float(target_protein_percent),
            user_id=user_id,
            yield_target_id=yield_target_id,
        )
        return jsonify(result), 201
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to save recipe.', 'details': str(e)}), 500


@nutrition_bp.route('/feed-formulation/suggested-mix', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_suggested_feed_mix():
    """
    Get suggested feed mix based on Milk Lab yield targets.
    Returns pre-calculated ingredient mix and protein target from herd feeding plan.
    
    Query Parameters:
    - yield_target_id: int (optional, for specific yield target)
    - batch_size_kg: number (optional, default 500)
    
    Response 200:
    {
        "herd_total_target_liters": number,
        "suggested_protein_percent": number,
        "batch_size_kg": number,
        "suggested_ingredients": [
            {
                "ingredient_id": int,
                "name": str,
                "percentage": number,
                "protein_grams_per_kg": number
            },
            ...
        ],
        "message": str
    }
    """
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    batch_size_kg = request.args.get('batch_size_kg', 500, type=float)

    try:
        from app.services.herd_feeding_plan_service import HerdFeedingPlanService
        herd_plan = HerdFeedingPlanService.calculate_from_cow_targets(tenant_id=tenant_id)
        
        # For now, suggest a default protein target based on average of high-producing herds
        # In production, this could be calculated from actual feed recipe history
        suggested_protein_percent = 16.5  # Standard dairy meal protein
        
        # Get all active ingredients for suggestions
        ingredients = InventoryItem.query.filter_by(tenant_id=tenant_id).all()
        
        suggested_ingredients = []
        for ing in ingredients:
            if ing.protein_grams_per_kg > 0:  # Only include ingredients with protein data
                suggested_ingredients.append({
                    "ingredient_id": ing.id,
                    "name": ing.name,
                    "percentage": 0,  # Will be calculated by formulation engine
                    "protein_grams_per_kg": float(ing.protein_grams_per_kg),
                })

        return jsonify({
            "herd_total_target_liters": herd_plan["herd_total_target_liters"],
            "suggested_protein_percent": suggested_protein_percent,
            "batch_size_kg": batch_size_kg,
            "suggested_ingredients": suggested_ingredients,
            "message": "Suggested feed mix based on Milk Lab yield targets.",
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e), 'message': 'No yield targets found. Please set up yield targets in Milk Lab first.'}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to get suggested mix.', 'details': str(e)}), 500


@nutrition_alias_bp.route('/api/v1/recipes/formulate', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def formulate_recipe_with_protein_target_alias():
    return formulate_recipe_with_protein_target()


@nutrition_alias_bp.route('/api/v1/recipes/calculate-nutrition', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def calculate_recipe_nutrition_alias():
    return calculate_recipe_nutrition()


@nutrition_alias_bp.route('/api/v1/recipes/auto-save', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def auto_save_recipe_alias():
    return auto_save_recipe()


@nutrition_alias_bp.route('/api/v1/feed-formulation/suggested-mix', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_suggested_feed_mix_alias():
    return get_suggested_feed_mix()


@nutrition_alias_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_cow_yield_target_alias(cow_id):
    return delete_cow_yield_target(cow_id)
