from __future__ import annotations
import math
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.user import Role
from app.services.nutrition_service import NutritionService
from app.services.animal_yield_target_service import AnimalYieldTargetService
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.group_feeding_plan_service import GroupFeedingPlanService
from app.services.feeding_group_recipe_policy_service import FeedingGroupRecipePolicyService
from app.services.recipe_formulation_service import RecipeFormulationService, FormulationInfeasibleError
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id
from app.models.supply import FeedRecipe, RecipeIngredient, Ingredient, FarmMeasurementUnit, InventoryItem
from app.repositories.supply_repo import InventoryRepository
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


def _parse_recipe_type(value, *, default=FeedMixerPolicyService.MAIN_MEAL):
    if value is None and default is None:
        return None
    recipe_type = FeedMixerPolicyService.normalize_recipe_type(value, default=default)
    if recipe_type is None:
        raise ValueError('recipe_type must be one of: dairy_meal, main_meal.')
    return recipe_type


def _parse_feeding_group(value, *, default=None):
    if value is None:
        return default
    return FeedingGroupRecipePolicyService.normalize_feeding_group(value)


def _parse_recipe_measurement_settings(data: dict, *, recipe_type: str, current=None) -> dict:
    quantity_basis = data.get(
        'quantity_basis',
        getattr(current, 'quantity_basis', None) or (
            'concentrate' if recipe_type == FeedMixerPolicyService.DAIRY_MEAL else 'total_ration'
        ),
    )
    if quantity_basis not in {'total_ration', 'concentrate'}:
        raise ValueError('quantity_basis must be total_ration or concentrate.')

    settings = {'quantity_basis': quantity_basis}
    for field in ('concentrate_kg_per_head_day', 'bulk_density_kg_per_litre', 'bucket_volume_litres', 'scoop_weight_kg'):
        raw_value = data.get(field, getattr(current, field, None))
        if raw_value in (None, ''):
            settings[field] = None
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            raise ValueError(f'{field} must be a positive number.')
        if value <= 0:
            raise ValueError(f'{field} must be a positive number.')
        settings[field] = value

    if bool(settings['bulk_density_kg_per_litre']) != bool(settings['bucket_volume_litres']):
        raise ValueError('bulk_density_kg_per_litre and bucket_volume_litres must be provided together.')
    return settings


def _validate_recipe_type_membership(*, tenant_id: int, recipe_type: str, ingredient_ids: list[int]):
    _, missing_ids, ineligible_ids = FeedMixerPolicyService.validate_items_for_recipe_type(
        tenant_id=tenant_id,
        ingredient_ids=ingredient_ids,
        recipe_type=recipe_type,
    )
    if missing_ids:
        raise ValueError(f'Ingredient(s) not found for tenant: {missing_ids}.')
    if ineligible_ids:
        raise ValueError(
            f'Ingredient(s) not eligible for recipe_type {recipe_type}: {ineligible_ids}. '
            'Use mixer eligibility from backend inventory payloads.'
        )


def _resolve_recipe_type(*, tenant_id: int, ingredient_ids: list[int], feeding_group: str | None, requested_recipe_type):
    inferred_recipe_type = None
    if requested_recipe_type in (None, ''):
        inferred_recipe_type = FeedMixerPolicyService.infer_unique_recipe_type(
            tenant_id=tenant_id,
            ingredient_ids=ingredient_ids,
        )

    return FeedingGroupRecipePolicyService.resolve_recipe_type(
        feeding_group=feeding_group,
        requested_recipe_type=requested_recipe_type or inferred_recipe_type,
    )


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


@nutrition_bp.route('/batches/<int:batch_id>/consumption-status', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_batch_consumption_status(batch_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return NutritionService.get_batch_consumption_status(tenant_id=tenant_id, batch_id=batch_id)


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


@nutrition_bp.route('/analytics/feed-cost-by-group', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def feed_cost_by_group():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return NutritionService.get_feed_cost_by_group(tenant_id=tenant_id)


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
    performance = NutritionService.get_recipe_performance(tenant_id=tenant_id)
    return jsonify([
        {
            'id': recipe.id,
            'tenant_id': recipe.tenant_id,
            'name': recipe.recipe_name,
            'target_protein_percentage': float(recipe.target_protein_percentage),
            'recipe_type': FeedMixerPolicyService.normalize_recipe_type(
                getattr(recipe, 'recipe_type', None),
                default=FeedMixerPolicyService.MAIN_MEAL,
            ),
            'feeding_group': getattr(recipe, 'feeding_group', None),
            'quantity_basis': recipe.quantity_basis,
            'concentrate_kg_per_head_day': float(recipe.concentrate_kg_per_head_day) if recipe.concentrate_kg_per_head_day is not None else None,
            'bulk_density_kg_per_litre': float(recipe.bulk_density_kg_per_litre) if recipe.bulk_density_kg_per_litre is not None else None,
            'bucket_volume_litres': float(recipe.bucket_volume_litres) if recipe.bucket_volume_litres is not None else None,
            'scoop_weight_kg': float(recipe.scoop_weight_kg) if recipe.scoop_weight_kg is not None else None,
            'is_active': recipe.is_active,
            'performance': performance.get(recipe.id),
            'ingredients': [
                {
                    'ingredient_id': ri.inventory_item_id,
                    'ingredientId': ri.inventory_item_id,
                    'inventory_item_id': ri.inventory_item_id,
                    'inventoryItemId': ri.inventory_item_id,
                    'ingredient_name': ri.inventory_item.name if ri.inventory_item else None,
                    'ingredientName': ri.inventory_item.name if ri.inventory_item else None,
                    'inclusion_percentage': float(ri.inclusion_percentage),
                    'inclusionPercentage': float(ri.inclusion_percentage),
                }
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
    payload_ingredients = data.get('ingredients', [])
    ingredient_ids = [
        ingredient.get('inventory_item_id')
        for ingredient in payload_ingredients
        if ingredient.get('inventory_item_id') is not None
    ]
    try:
        feeding_group = _parse_feeding_group(data.get('feeding_group'), default=None)
        recipe_type = _resolve_recipe_type(
            tenant_id=tenant_id,
            ingredient_ids=ingredient_ids,
            feeding_group=feeding_group,
            requested_recipe_type=data.get('recipe_type'),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    try:
        recipe_type_for_save = recipe_type
        _validate_recipe_type_membership(tenant_id=tenant_id, recipe_type=recipe_type_for_save, ingredient_ids=ingredient_ids)
        measurement_settings = _parse_recipe_measurement_settings(data, recipe_type=recipe_type_for_save)

        recipe = FeedRecipe(
            tenant_id=tenant_id,
            recipe_name=recipe_name,
            target_protein_percentage=data.get('target_protein_percentage', 0),
            recipe_type=recipe_type_for_save,
            feeding_group=feeding_group,
            **measurement_settings,
            is_active=bool(data.get('is_active', True)),
        )
        db.session.add(recipe)
        db.session.flush()
        for ingredient in payload_ingredients:
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
    except ValueError as exc:
        db.session.rollback()
        message = str(exc)
        status = 404 if message.startswith('Ingredient(s) not found for tenant:') else 400
        return jsonify({'error': message}), status
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
    if 'feeding_group' in data:
        try:
            recipe.feeding_group = _parse_feeding_group(data.get('feeding_group'), default=None)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    if 'recipe_type' in data or 'feeding_group' in data:
        try:
            recipe.recipe_type = FeedingGroupRecipePolicyService.resolve_recipe_type(
                feeding_group=recipe.feeding_group,
                requested_recipe_type=data.get('recipe_type', recipe.recipe_type),
            )
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
    if 'is_active' in data:
        recipe.is_active = bool(data.get('is_active'))
    try:
        measurement_settings = _parse_recipe_measurement_settings(data, recipe_type=recipe.recipe_type, current=recipe)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    for field, value in measurement_settings.items():
        setattr(recipe, field, value)
    db.session.commit()
    return jsonify({
        'id': recipe.id,
        'name': recipe.recipe_name,
        'is_active': recipe.is_active,
        'feeding_group': recipe.feeding_group,
        'recipe_type': recipe.recipe_type,
        'quantity_basis': recipe.quantity_basis,
        'concentrate_kg_per_head_day': float(recipe.concentrate_kg_per_head_day) if recipe.concentrate_kg_per_head_day is not None else None,
        'bulk_density_kg_per_litre': float(recipe.bulk_density_kg_per_litre) if recipe.bulk_density_kg_per_litre is not None else None,
        'bucket_volume_litres': float(recipe.bucket_volume_litres) if recipe.bucket_volume_litres is not None else None,
        'scoop_weight_kg': float(recipe.scoop_weight_kg) if recipe.scoop_weight_kg is not None else None,
    }), 200


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
        ]
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
    try:
        batch_size_kg = float(data.get('batch_size_kg'))
        target_protein_percent = float(data.get('target_protein_percent'))
    except (TypeError, ValueError):
        return jsonify({'error': 'batch_size_kg and target_protein_percent must be valid numbers.'}), 400
    ingredients = _normalize_recipe_ingredients(data.get('ingredients', []))
    recipe_type_raw = data.get('recipe_type')
    feeding_group_raw = data.get('feeding_group')

    # Validation
    if not math.isfinite(batch_size_kg) or batch_size_kg <= 0:
        return jsonify({'error': 'batch_size_kg is required and must be > 0.'}), 400
    if not math.isfinite(target_protein_percent) or target_protein_percent < 0 or target_protein_percent > 100:
        return jsonify({'error': 'target_protein_percent is required (0-100).'}), 400
    if not ingredients or len(ingredients) == 0:
        return jsonify({'error': 'At least one ingredient is required.'}), 400
    if any(ing.get('ingredient_id') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires ingredient_id (or ingredientId) as a number.'}), 400
    if any(ing.get('percentage') in (None, '') for ing in ingredients):
        return jsonify({'error': 'Each ingredient requires percentage as a number.'}), 400
    percentages = [ing['percentage'] for ing in ingredients]
    if any(not math.isfinite(percentage) or percentage < 0 or percentage > 100 for percentage in percentages):
        return jsonify({'error': 'Each ingredient percentage must be a finite number between 0 and 100.'}), 400
    total_percentage = sum(percentages)
    if total_percentage > 0 and not math.isclose(total_percentage, 100.0, abs_tol=0.01):
        return jsonify({'error': 'Ingredient percentages must total 100 (or all be zero for automatic seeding).'}), 400
    if len({ing['ingredient_id'] for ing in ingredients}) != len(ingredients):
        return jsonify({'error': 'Each ingredient may only appear once in a formulation.'}), 400

    try:
        feeding_group = _parse_feeding_group(feeding_group_raw, default=None)
        recipe_type = _resolve_recipe_type(
            tenant_id=tenant_id,
            ingredient_ids=[int(ing['ingredient_id']) for ing in ingredients],
            feeding_group=feeding_group,
            requested_recipe_type=recipe_type_raw,
        )
        ingredient_ids = [int(ing['ingredient_id']) for ing in ingredients]
        _validate_recipe_type_membership(
            tenant_id=tenant_id,
            recipe_type=recipe_type,
            ingredient_ids=ingredient_ids,
        )
        measurement_settings = _parse_recipe_measurement_settings(data, recipe_type=recipe_type)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        adjustments = RecipeFormulationService.suggest_ingredient_adjustments(
            tenant_id=tenant_id,
            batch_size_kg=batch_size_kg,
            base_ingredients=ingredients,
            target_protein_percent=target_protein_percent,
            recipe_type=recipe_type,
            feeding_group=feeding_group,
        )
        return jsonify(adjustments), 200
    except FormulationInfeasibleError as e:
        payload = {'error': str(e)}
        if e.target_protein_percent is not None:
            payload['target_protein_percent'] = round(float(e.target_protein_percent), 4)
        if e.minimum_achievable_protein_percent is not None:
            payload['minimum_achievable_protein_percent'] = round(float(e.minimum_achievable_protein_percent), 4)
        if e.maximum_achievable_protein_percent is not None:
            payload['maximum_achievable_protein_percent'] = round(float(e.maximum_achievable_protein_percent), 4)
        if getattr(e, 'limiting_ingredients', None):
            payload['limiting_ingredients'] = e.limiting_ingredients
        if getattr(e, 'max_feasible_mix', None):
            payload['max_feasible_mix'] = e.max_feasible_mix
            payload['hint'] = (
                'Available stock limits this batch. The max_feasible_mix shows the '
                'best mix possible with current stock; reduce the batch size or '
                'restock the limiting items to reach the protein goal.'
            )
        elif (
            e.minimum_achievable_protein_percent is not None
            and e.maximum_achievable_protein_percent is not None
        ):
            minimum = round(float(e.minimum_achievable_protein_percent), 4)
            maximum = round(float(e.maximum_achievable_protein_percent), 4)
            payload['achievable_protein_range'] = {
                'minimum_percent': minimum,
                'maximum_percent': maximum,
            }
            payload['hint'] = (
                f"With selected feeds, achievable protein target range is {minimum:g}% to {maximum:g}%."
            )
        return jsonify(payload), 422
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
            tenant_id=tenant_id,
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
        ]
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
    recipe_type_raw = data.get('recipe_type')
    feeding_group_raw = data.get('feeding_group')

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
        feeding_group = _parse_feeding_group(feeding_group_raw, default=None)
        recipe_type = _resolve_recipe_type(
            tenant_id=tenant_id,
            ingredient_ids=[int(ing['ingredient_id']) for ing in adjusted_ingredients],
            feeding_group=feeding_group,
            requested_recipe_type=recipe_type_raw,
        )
        ingredient_ids = [int(ing['ingredient_id']) for ing in adjusted_ingredients]
        _validate_recipe_type_membership(
            tenant_id=tenant_id,
            recipe_type=recipe_type,
            ingredient_ids=ingredient_ids,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    try:
        result = RecipeFormulationService.save_recipe_from_formulation(
            tenant_id=tenant_id,
            recipe_name=recipe_name,
            batch_size_kg=float(batch_size_kg),
            adjusted_ingredients=adjusted_ingredients,
            target_protein_percent=float(target_protein_percent),
            recipe_type=recipe_type,
            feeding_group=feeding_group,
            measurement_settings=measurement_settings,
            user_id=user_id,
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
    - batch_size_kg: number (optional; defaults to the herd's computed daily
      meal requirement from the feeding plan, or 500 when no plan exists)

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

    try:
        from app.services.herd_feeding_plan_service import HerdFeedingPlanService
        herd_plan = HerdFeedingPlanService.calculate_from_cow_targets(tenant_id=tenant_id)

        # Default the batch to the herd's computed daily meal requirement so the
        # mixer pre-fills the quantity the feeding plan actually calls for.
        daily_need_kg = float(herd_plan.get('total_meal_needed_kg') or 0)
        batch_size_kg = request.args.get('batch_size_kg', type=float)
        if not batch_size_kg or batch_size_kg <= 0:
            batch_size_kg = daily_need_kg if daily_need_kg > 0 else 500.0

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
            "daily_meal_need_kg": daily_need_kg,
            "suggested_protein_percent": suggested_protein_percent,
            "batch_size_kg": batch_size_kg,
            "suggested_ingredients": suggested_ingredients,
            "recipe_type": FeedMixerPolicyService.DAIRY_MEAL,
            "message": "Suggested feed mix based on Milk Lab yield targets.",
        }), 200

    except ValueError as e:
        return jsonify({'error': str(e), 'message': 'No yield targets found. Please set up yield targets in Milk Lab first.'}), 400
    except Exception as e:
        return jsonify({'error': 'Failed to get suggested mix.', 'details': str(e)}), 500


@nutrition_bp.route('/feeding-groups/profiles', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_feeding_group_profiles():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        return jsonify(GroupFeedingPlanService.get_profiles(tenant_id=tenant_id)), 200
    except Exception as exc:
        return jsonify({'error': 'Failed to fetch feeding group profiles.', 'details': str(exc)}), 500


@nutrition_bp.route('/feeding-groups/profiles/<string:feeding_group>', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER)
def upsert_feeding_group_profile(feeding_group):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    try:
        result = GroupFeedingPlanService.upsert_profile(
            tenant_id=tenant_id,
            feeding_group=feeding_group,
            payload=data,
        )
        return jsonify(result), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': 'Failed to save feeding group profile.', 'details': str(exc)}), 500


@nutrition_bp.route('/herd/feeding-plan/by-group', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def calculate_herd_feeding_plan_by_group():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        plan = GroupFeedingPlanService.calculate_plan_by_group(tenant_id=tenant_id)
        return jsonify(plan), 200
    except Exception as exc:
        return jsonify({'error': 'Failed to calculate group feeding plan.', 'details': str(exc)}), 500


@nutrition_bp.route('/feed-formulation/suggested-mix/by-group', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_suggested_mix_by_group():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    try:
        feeding_group = _parse_feeding_group(request.args.get('feeding_group'), default=None)
        if feeding_group is None:
            return jsonify({'error': 'feeding_group is required.'}), 400

        plan = GroupFeedingPlanService.calculate_plan_by_group(tenant_id=tenant_id)
        group_row = next((row for row in plan['groups'] if row['feeding_group'] == feeding_group), None)
        if group_row is None:
            return jsonify({'error': f'No planning row found for feeding_group {feeding_group}.'}), 404

        recipe_type = FeedingGroupRecipePolicyService.resolve_recipe_type(
            feeding_group=feeding_group,
            requested_recipe_type=request.args.get('recipe_type'),
        )
        batch_size_kg = request.args.get('batch_size_kg', type=float)
        if not batch_size_kg or batch_size_kg <= 0:
            batch_size_kg = float(group_row.get('daily_group_feed_kg') or 0) or 250.0

        rows = InventoryRepository.list_by_tenant(tenant_id)
        suggested_ingredients = []
        for row in rows:
            policy = FeedMixerPolicyService.resolve_item_policy(row)
            if recipe_type not in policy['allowed_mixers']:
                continue
            if float(row.protein_grams_per_kg or 0) <= 0:
                continue
            suggested_ingredients.append({
                'ingredient_id': row.id,
                'name': row.name,
                'percentage': float(policy['defaults'].get(recipe_type, 0)),
                'protein_grams_per_kg': float(row.protein_grams_per_kg),
                'allowed_mixers': policy['allowed_mixers'],
            })

        return jsonify({
            'feeding_group': feeding_group,
            'recipe_type': recipe_type,
            'headcount': group_row['headcount'],
            'daily_group_feed_kg': group_row['daily_group_feed_kg'],
            'suggested_protein_percent': group_row['target_protein_percent'],
            'batch_size_kg': batch_size_kg,
            'suggested_ingredients': suggested_ingredients,
            'message': f'Suggested mix for {feeding_group} cohort.',
        }), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        return jsonify({'error': 'Failed to get suggested mix by feeding group.', 'details': str(exc)}), 500


@nutrition_alias_bp.route('/api/v1/nutrition/feeding-groups/profiles', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_feeding_group_profiles_alias():
    return list_feeding_group_profiles()


@nutrition_alias_bp.route('/api/v1/nutrition/feeding-groups/profiles/<string:feeding_group>', methods=['PUT'])
@jwt_required()
@role_required(Role.FARMER)
def upsert_feeding_group_profile_alias(feeding_group):
    return upsert_feeding_group_profile(feeding_group)


@nutrition_alias_bp.route('/api/v1/nutrition/herd/feeding-plan/by-group', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def calculate_herd_feeding_plan_by_group_alias():
    return calculate_herd_feeding_plan_by_group()


@nutrition_alias_bp.route('/api/v1/nutrition/feed-formulation/suggested-mix/by-group', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_suggested_mix_by_group_alias():
    return get_suggested_mix_by_group()


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


@nutrition_alias_bp.route('/api/v1/nutrition/batches/<int:batch_id>/consumption-status', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def get_batch_consumption_status_alias(batch_id):
    return get_batch_consumption_status(batch_id)


@nutrition_alias_bp.route('/api/v1/feed-formulation/suggested-mix', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_suggested_feed_mix_alias():
    return get_suggested_feed_mix()


@nutrition_bp.route('/mixers/<string:recipe_type>/ingredients', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_mixer_ingredients(recipe_type):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    normalized_recipe_type = FeedMixerPolicyService.normalize_recipe_type(recipe_type, default=None)
    if normalized_recipe_type is None:
        return jsonify({'error': 'recipe_type must be one of: dairy_meal, main_meal.'}), 400

    rows = InventoryRepository.list_by_tenant(tenant_id)
    ingredients = []
    for row in rows:
        policy = FeedMixerPolicyService.resolve_item_policy(row)
        if normalized_recipe_type not in policy['allowed_mixers']:
            continue

        defaults = policy['defaults']
        ingredients.append({
            'id': row.id,
            'name': row.name,
            'category': row.category,
            'unit': row.unit,
            'stock': {
                'value': float(row.current_qty),
                'unit': row.unit,
            },
            'currentStock': float(row.current_qty),
            'current_qty': float(row.current_qty),
            'cost_per_kg': float(row.cost_per_kg),
            'costPerKg': float(row.cost_per_kg),
            'allowed_mixers': policy['allowed_mixers'],
            'role': policy['role'],
            'defaults': {
                FeedMixerPolicyService.DAIRY_MEAL: float(defaults.get(FeedMixerPolicyService.DAIRY_MEAL, 0)),
                FeedMixerPolicyService.MAIN_MEAL: float(defaults.get(FeedMixerPolicyService.MAIN_MEAL, 0)),
            },
            'inclusion_percentage_dairy_meal': float(defaults.get(FeedMixerPolicyService.DAIRY_MEAL, 0)),
            'inclusion_percentage_main_meal': float(defaults.get(FeedMixerPolicyService.MAIN_MEAL, 0)),
            'default_inclusion_percentage': float(defaults.get(normalized_recipe_type, 0)),
            'inclusion_percentage': float(defaults.get(normalized_recipe_type, 0)),
        })

    return jsonify({
        'recipe_type': normalized_recipe_type,
        'ingredients': ingredients,
        'total': len(ingredients),
    }), 200


@nutrition_bp.route('/mixers/ingredients', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_mixer_ingredients_query():
    recipe_type = (
        request.args.get('recipe_type')
        or request.args.get('mixer_type')
        or request.args.get('mixerType')
    )
    if not recipe_type:
        return jsonify({'error': 'recipe_type (or mixer_type/mixerType) is required.'}), 400

    return list_mixer_ingredients(recipe_type)


@nutrition_alias_bp.route('/api/v1/animals/<int:cow_id>/yield-target', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_cow_yield_target_alias(cow_id):
    return delete_cow_yield_target(cow_id)
