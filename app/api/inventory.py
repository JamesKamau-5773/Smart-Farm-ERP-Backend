from flask import Blueprint, jsonify, g, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from typing import Optional, Tuple
from sqlalchemy import desc, or_

from app.models.user import Role
from app.models.supply import FeedRecipe, RecipeIngredient, InventoryItem
from app.repositories.supply_repo import InventoryRepository
from app.services.feed_mixer_policy_service import FeedMixerPolicyService
from app.services.inventory_standards_service import InventoryStandardsService
from app.utils.decorators import require_tenant_context, role_required
from app.utils import get_tenant_id_from_context

inventory_bp = Blueprint('inventory', __name__)


def _parse_movement_payload(raw_type: Optional[str]) -> Tuple[str, str]:
    """
    Normalizes movement type from frontend-friendly terms and determines the
    correct reason code for the transaction.
    
    Returns:
        A Tuple of (transaction_type, reason_code).
    """
    raw = (raw_type or '').strip().upper()

    # Shrinkage & Loss
    if raw in {'SPOILAGE', 'SPILL', 'EXPIRED', 'DAMAGE', 'SHRINKAGE'}:
        return 'OUT', 'SHRINKAGE'

    # Standard Consumption
    if raw in {'ISSUE', 'DEDUCT', 'CONSUMPTION', 'CONSUME', 'OUTBOUND', 'USAGE', 'WITHDRAWAL'}:
        return 'OUT', 'CONSUMPTION'

    # Standard Restock
    if raw in {'RESTOCK', 'ADD', 'INBOUND', 'PURCHASE', 'RECEIPT'}:
        return 'IN', 'PURCHASE'

    # Direct type with default reason
    if raw in {'IN', 'OUT'}:
        return raw, 'STANDARD'

    raise ValueError(f"Unknown movement type: {raw_type}")


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


def _get_mix_share_defaults_by_mixer(tenant_id: int):
    """Resolve backend-owned default shares from the latest active recipe per mixer type."""
    defaults_by_mixer = {
        FeedMixerPolicyService.DAIRY_MEAL: {},
        FeedMixerPolicyService.MAIN_MEAL: {},
    }

    active_recipes = (
        FeedRecipe.query
        .filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(desc(FeedRecipe.id))
        .all()
    )
    recipe_by_type = {}
    for recipe in active_recipes:
        recipe_type = FeedMixerPolicyService.normalize_recipe_type(
            getattr(recipe, 'recipe_type', None),
            default=FeedMixerPolicyService.MAIN_MEAL,
        )
        if recipe_type not in recipe_by_type:
            recipe_by_type[recipe_type] = recipe

    for recipe_type, recipe in recipe_by_type.items():
        rows = RecipeIngredient.query.filter_by(tenant_id=tenant_id, recipe_id=recipe.id).all()
        defaults_by_mixer[recipe_type] = {
            row.inventory_item_id: float(row.inclusion_percentage or 0)
            for row in rows
        }

    return defaults_by_mixer


def _serialize_item(item, *, mix_share_defaults_by_mixer=None, active_recipe_type=None):
    if mix_share_defaults_by_mixer is None:
        mix_share_defaults_by_mixer = {}

    policy = FeedMixerPolicyService.resolve_item_policy(item)
    defaults = FeedMixerPolicyService.apply_recipe_overrides(
        policy=policy,
        item_id=item.id,
        mix_share_defaults_by_mixer=mix_share_defaults_by_mixer,
    )
    active_mixer = FeedMixerPolicyService.normalize_recipe_type(
        active_recipe_type,
        default=FeedMixerPolicyService.MAIN_MEAL,
    )
    inclusion_percentage = float(defaults.get(active_mixer, 0))
    metadata = InventoryStandardsService.infer_item_metadata(
        tenant_id=item.tenant_id,
        name=item.name,
        category=item.category,
        energy_mj_per_kg=item.energy_mj_per_kg,
        protein_grams_per_kg=item.protein_grams_per_kg,
        fiber_grams_per_kg=item.fiber_grams_per_kg,
        cost_per_kg=item.cost_per_kg,
    )
    return {
        'id': item.id,
        'name': item.name,
        'sku': getattr(item, 'sku', None),
        'category': item.category,
        'unit': item.unit,
        'reorderLevel': float(item.minimum_threshold),
        'reorder_level': float(item.minimum_threshold),
        'currentStock': float(item.current_qty),
        'current_stock': float(item.current_qty),
        'currentQty': float(item.current_qty),
        'current_qty': float(item.current_qty),
        'stock': {
            'value': float(item.current_qty),
            'unit': item.unit,
        },
        # Backend-owned default share values for feed planner.
        'inclusion_percentage': inclusion_percentage,
        'inclusionPercent': inclusion_percentage,
        'inclusionPercentage': inclusion_percentage,
        'default_share_percent': inclusion_percentage,
        'default_percentage': inclusion_percentage,
        'percentage': inclusion_percentage,
        'energy_mj_per_kg': float(item.energy_mj_per_kg),
        'energyMjPerKg': float(item.energy_mj_per_kg),
        'protein_grams_per_kg': float(item.protein_grams_per_kg),
        'proteinGramsPerKg': float(item.protein_grams_per_kg),
        'fiber_grams_per_kg': float(item.fiber_grams_per_kg),
        'fiberGramsPerKg': float(item.fiber_grams_per_kg),
        'cost_per_kg': float(item.cost_per_kg),
        'costPerKg': float(item.cost_per_kg),
        'default_source': metadata.get('default_source'),
        'standards_version': metadata.get('standards_version'),
        'source_reference': metadata.get('source_reference'),
        'allowed_mixers': policy['allowed_mixers'],
        'role': policy['role'],
        'defaults': {
            FeedMixerPolicyService.DAIRY_MEAL: float(defaults.get(FeedMixerPolicyService.DAIRY_MEAL, 0)),
            FeedMixerPolicyService.MAIN_MEAL: float(defaults.get(FeedMixerPolicyService.MAIN_MEAL, 0)),
        },
        'inclusion_percentage_dairy_meal': float(defaults.get(FeedMixerPolicyService.DAIRY_MEAL, 0)),
        'inclusion_percentage_main_meal': float(defaults.get(FeedMixerPolicyService.MAIN_MEAL, 0)),
    }


def _parse_inventory_item_policy_payload(data, *, fallback_name=None, fallback_category=None):
    inferred = FeedMixerPolicyService.infer_policy_from_item(
        name=data.get('name', fallback_name),
        category=data.get('category', fallback_category),
    )
    allowed_mixers = FeedMixerPolicyService.normalize_allowed_mixers(
        data.get('allowed_mixers'),
        fallback=inferred['allowed_mixers'],
    )
    role = FeedMixerPolicyService.normalize_role(
        data.get('role'),
        allowed_mixers=allowed_mixers,
        fallback_name=data.get('name', fallback_name),
        fallback_category=data.get('category', fallback_category),
    )

    inclusion_percentage_dairy_meal = data.get('inclusion_percentage_dairy_meal', data.get('inclusionPercentageDairyMeal'))
    inclusion_percentage_main_meal = data.get('inclusion_percentage_main_meal', data.get('inclusionPercentageMainMeal'))

    return {
        'allowed_mixers': ','.join(allowed_mixers),
        'mixer_role': role,
        'inclusion_percentage_dairy_meal': float(inclusion_percentage_dairy_meal or 0),
        'inclusion_percentage_main_meal': float(inclusion_percentage_main_meal or 0),
    }


def _build_bulk_feed_validation_errors(*, category: str, energy_mj_per_kg, protein_grams_per_kg, fiber_grams_per_kg, cost_per_kg):
    if (category or '').strip().lower() != 'bulk feed':
        return []

    values = {
        'energy_mj_per_kg': float(energy_mj_per_kg),
        'protein_grams_per_kg': float(protein_grams_per_kg),
        'fiber_grams_per_kg': float(fiber_grams_per_kg),
        'cost_per_kg': float(cost_per_kg),
    }
    if all(v == 0 for v in values.values()):
        return [
            {'field': 'energy_mj_per_kg', 'message': 'Bulk Feed requires a non-zero energy baseline.'},
            {'field': 'protein_grams_per_kg', 'message': 'Bulk Feed requires a non-zero protein baseline.'},
            {'field': 'fiber_grams_per_kg', 'message': 'Bulk Feed requires a non-zero fiber baseline.'},
            {'field': 'cost_per_kg', 'message': 'Bulk Feed requires a non-zero cost baseline.'},
        ]
    return []


def _serialize_movement(movement):
    return {
        'id': movement.id,
        'item_id': movement.item_id,
        'item_name': movement.item.name if movement.item else None,
        'quantity': float(movement.quantity),
        'movement_type': movement.transaction_type,
        'reason_code': movement.reason_code,
        'timestamp': movement.transaction_date.isoformat() if movement.transaction_date else None,
        'logged_by': movement.logged_by,
        'notes': movement.notes,
        'unit_cost': float(movement.unit_cost),
        'total_transaction_value': float(movement.total_transaction_value),
    }


def _link_inventory_loss_to_finance(movement, item):
    """Creates an Expense transaction in the main ledger for inventory write-offs."""
    from app.services.finance_service import FinanceService
    from app.models.finance import TransactionType, TransactionCategory

    loss_value = float(movement.quantity) * float(item.cost_per_kg)
    if loss_value > 0:
        desc = f"Inventory write-off for {item.name}: {movement.notes or movement.reason_code}"
        FinanceService.record_transaction(
            t_type=TransactionType.EXPENSE, category=TransactionCategory.INVENTORY_WRITE_OFF,
            amount=loss_value, user_id=int(get_jwt_identity()), ip_address=request.remote_addr, desc=desc
        )


@inventory_bp.route('/api/v1/inventory/deduct', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def deduct_inventory():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    data = request.get_json() or {}
    item_id = data.get('item_id')
    if not item_id:
        return jsonify({"error": "item_id is required."}), 400

    try:
        qty_to_deduct = float(data.get('quantity', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be a valid number."}), 400

    if qty_to_deduct <= 0:
        return jsonify({"error": "Deduction quantity must be greater than zero."}), 400

    note = data.get('notes') or 'Automated system deduction'
    user_id = data.get('logged_by') or get_jwt_identity()

    try:
        updated_item, is_low_stock = InventoryRepository.deduct_stock(
            item_id=item_id,
            amount=qty_to_deduct,
            user_id=user_id,
            notes=note,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404 if "not found" in str(exc).lower() else 400
    except Exception as exc:
        return jsonify({"error": "Transaction failed", "details": str(exc)}), 500

    return jsonify({
        "status": "success",
        "message": f"Deducted {qty_to_deduct} from {updated_item.name}",
        "new_balance": float(updated_item.current_qty),
        "unit": updated_item.unit,
        "reorder_alert": is_low_stock,
    }), 200


@inventory_bp.route('/api/inventory/items', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def list_inventory_items():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    query = InventoryItem.query.filter_by(tenant_id=tenant_id)

    mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
    requested_recipe_type = FeedMixerPolicyService.normalize_recipe_type(
        request.args.get('recipe_type'),
        default=None,
    )

    q = (request.args.get('q') or '').strip().lower()
    if q:
        search_term = f"%{q}%"
        query = query.filter(or_(
            InventoryItem.name.ilike(search_term),
            InventoryItem.sku.ilike(search_term)
        ))

    category = (request.args.get('category') or '').strip().lower()
    if category:
        query = query.filter(InventoryItem.category.ilike(category))

    if requested_recipe_type:
        query = query.filter(InventoryItem.allowed_mixers.contains(requested_recipe_type))

    # New flag filter for "quick select"
    flag = request.args.get('flag')
    limit = request.args.get('limit', default=None, type=int)

    if flag == 'low_stock':
        query = query.filter(InventoryItem.current_qty <= InventoryItem.minimum_threshold)
        query = query.order_by((InventoryItem.minimum_threshold - InventoryItem.current_qty).desc())
    else:
        query = query.order_by(InventoryItem.name.asc())

    # Handle limit for widget-like requests that don't need pagination.
    if limit:
        items = query.limit(limit).all()
        serialized_items = [_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer, active_recipe_type=requested_recipe_type) for item in items]
        return jsonify({'items': serialized_items}), 200

    # Standard pagination for list views.
    page, per_page = _pagination_params()
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)
    page_items = paginated.items
    serialized_items = [_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer, active_recipe_type=requested_recipe_type) for item in page_items]
    return jsonify({'items': serialized_items, 'meta': {'page': page, 'per_page': per_page, 'total': paginated.total, 'pages': paginated.pages if paginated.total else 0}}), 200


@inventory_bp.route('/api/v1/inventory/insights/quick-restock', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def get_quick_restock_items():
    """
    Returns a prioritized list of inventory items that are running low,
    suitable for a "quick select" or "restock alert" widget on the frontend.
    """
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    # 1. Fetch items where current_qty is at or below minimum_threshold (reorder_level)
    # 2. Order by how critically low they are (difference between threshold and current quantity)
    # 3. Limit to 5 results as per the request.
    query = InventoryItem.query.filter_by(tenant_id=tenant_id)\
        .filter(InventoryItem.current_qty <= InventoryItem.minimum_threshold)\
        .order_by((InventoryItem.minimum_threshold - InventoryItem.current_qty).desc())\
        .limit(5)

    items = query.all()
    mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
    serialized_items = [_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer, active_recipe_type=None) for item in items]

    return jsonify({'items': serialized_items}), 200


@inventory_bp.route('/api/inventory/items', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def create_inventory_item():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()
    unit = (data.get('unit') or '').strip()
    if not name or not category or not unit:
        return jsonify({'error': 'name, category, and unit are required.'}), 400
    try:
        policy_payload = _parse_inventory_item_policy_payload(data)
        standards_payload = InventoryStandardsService.apply_defaults(
            tenant_id=tenant_id,
            name=name,
            category=category,
            energy_mj_per_kg=data.get('energy_mj_per_kg', data.get('energyMjPerKg')),
            protein_grams_per_kg=data.get('protein_grams_per_kg', data.get('proteinGramsPerKg')),
            fiber_grams_per_kg=data.get('fiber_grams_per_kg', data.get('fiberGramsPerKg')),
            cost_per_kg=data.get('cost_per_kg', data.get('costPerKg')),
        )
        resolved_defaults = standards_payload['values']

        field_errors = _build_bulk_feed_validation_errors(
            category=category,
            energy_mj_per_kg=resolved_defaults['energy_mj_per_kg'],
            protein_grams_per_kg=resolved_defaults['protein_grams_per_kg'],
            fiber_grams_per_kg=resolved_defaults['fiber_grams_per_kg'],
            cost_per_kg=resolved_defaults['cost_per_kg'],
        )
        if field_errors:
            return jsonify({'error': 'Bulk Feed nutrition/cost values cannot all be zero.', 'field_errors': field_errors}), 400

        item = InventoryRepository.create_item(
            tenant_id=tenant_id,
            name=name,
            sku=(data.get('sku') or '').strip() or None,
            category=category,
            unit=unit,
            current_qty=data.get('current_qty', data.get('currentStock', 0)),
            minimum_threshold=data.get('minimum_threshold', data.get('reorderLevel', 0)),
            energy_mj_per_kg=resolved_defaults['energy_mj_per_kg'],
            protein_grams_per_kg=resolved_defaults['protein_grams_per_kg'],
            fiber_grams_per_kg=resolved_defaults['fiber_grams_per_kg'],
            cost_per_kg=resolved_defaults['cost_per_kg'],
            allowed_mixers=policy_payload['allowed_mixers'],
            mixer_role=policy_payload['mixer_role'],
            inclusion_percentage_dairy_meal=policy_payload['inclusion_percentage_dairy_meal'],
            inclusion_percentage_main_meal=policy_payload['inclusion_percentage_main_meal'],
        )
        mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
        return jsonify(_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer)), 201
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 409


@inventory_bp.route('/api/inventory/items/<int:item_id>', methods=['PATCH'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def update_inventory_item(item_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}

    name_for_defaults = (data.get('name') or '').strip() if 'name' in data else None
    category_for_defaults = (data.get('category') or '').strip() if 'category' in data else None
    if name_for_defaults is None or category_for_defaults is None:
        current_item = InventoryRepository.get_item(item_id, tenant_id=tenant_id)
        if not current_item:
            return jsonify({'error': 'Inventory item not found.'}), 404
        if name_for_defaults is None:
            name_for_defaults = current_item.name
        if category_for_defaults is None:
            category_for_defaults = current_item.category

    standards_payload = InventoryStandardsService.apply_defaults(
        tenant_id=tenant_id,
        name=name_for_defaults,
        category=category_for_defaults,
        energy_mj_per_kg=data.get('energy_mj_per_kg', data.get('energyMjPerKg')),
        protein_grams_per_kg=data.get('protein_grams_per_kg', data.get('proteinGramsPerKg')),
        fiber_grams_per_kg=data.get('fiber_grams_per_kg', data.get('fiberGramsPerKg')),
        cost_per_kg=data.get('cost_per_kg', data.get('costPerKg')),
    )
    resolved_defaults = standards_payload['values']

    should_update_nutrition = any(
        key in data
        for key in (
            'energy_mj_per_kg', 'energyMjPerKg',
            'protein_grams_per_kg', 'proteinGramsPerKg',
            'fiber_grams_per_kg', 'fiberGramsPerKg',
            'cost_per_kg', 'costPerKg',
            'name', 'category',
        )
    )

    if should_update_nutrition:
        field_errors = _build_bulk_feed_validation_errors(
            category=category_for_defaults,
            energy_mj_per_kg=resolved_defaults['energy_mj_per_kg'],
            protein_grams_per_kg=resolved_defaults['protein_grams_per_kg'],
            fiber_grams_per_kg=resolved_defaults['fiber_grams_per_kg'],
            cost_per_kg=resolved_defaults['cost_per_kg'],
        )
        if field_errors:
            return jsonify({'error': 'Bulk Feed nutrition/cost values cannot all be zero.', 'field_errors': field_errors}), 400

    policy_payload = _parse_inventory_item_policy_payload(
        data,
        fallback_name=name_for_defaults,
        fallback_category=category_for_defaults,
    )

    item = InventoryRepository.update_item(
        item_id=item_id,
        tenant_id=tenant_id,
        name=(data.get('name') or '').strip() if 'name' in data else None,
        sku=(data.get('sku') or '').strip() if 'sku' in data else None,
        category=(data.get('category') or '').strip() if 'category' in data else None,
        unit=(data.get('unit') or '').strip() if 'unit' in data else None,
        current_qty=data.get('current_qty', data.get('currentStock')) if ('current_qty' in data or 'currentStock' in data) else None,
        minimum_threshold=data.get('minimum_threshold', data.get('reorderLevel')) if ('minimum_threshold' in data or 'reorderLevel' in data) else None,
        energy_mj_per_kg=resolved_defaults['energy_mj_per_kg'] if should_update_nutrition else None,
        protein_grams_per_kg=resolved_defaults['protein_grams_per_kg'] if should_update_nutrition else None,
        fiber_grams_per_kg=resolved_defaults['fiber_grams_per_kg'] if should_update_nutrition else None,
        cost_per_kg=resolved_defaults['cost_per_kg'] if should_update_nutrition else None,
        allowed_mixers=policy_payload['allowed_mixers'] if ('allowed_mixers' in data or 'name' in data or 'category' in data) else None,
        mixer_role=policy_payload['mixer_role'] if ('role' in data or 'allowed_mixers' in data or 'name' in data or 'category' in data) else None,
        inclusion_percentage_dairy_meal=policy_payload['inclusion_percentage_dairy_meal'] if ('inclusion_percentage_dairy_meal' in data or 'inclusionPercentageDairyMeal' in data) else None,
        inclusion_percentage_main_meal=policy_payload['inclusion_percentage_main_meal'] if ('inclusion_percentage_main_meal' in data or 'inclusionPercentageMainMeal' in data) else None,
    )
    if not item:
        return jsonify({'error': 'Inventory item not found.'}), 404
    mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
    return jsonify(_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer)), 200


@inventory_bp.route('/api/inventory/items/<int:item_id>', methods=['DELETE'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def delete_inventory_item(item_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    item = InventoryRepository.delete_item(item_id=item_id, tenant_id=tenant_id)
    if not item:
        return jsonify({'error': 'Inventory item not found.'}), 404
    return jsonify({'message': 'Inventory item deleted successfully.', 'deleted': _serialize_item(item, mix_share_defaults_by_mixer={})}), 200


@inventory_bp.route('/api/inventory/movements', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def list_inventory_movements():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    movements = InventoryRepository.list_transactions_by_tenant(tenant_id)
    movement_type = (request.args.get('movement_type') or '').strip().upper()
    if movement_type in {'IN', 'OUT'}:
        movements = [movement for movement in movements if movement.transaction_type == movement_type]
    page, per_page = _pagination_params()
    total = len(movements)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = movements[start:end]
    return jsonify({'items': [_serialize_movement(movement) for movement in page_items], 'meta': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if total else 0}}), 200


@inventory_bp.route('/api/inventory/movements', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def create_inventory_movement():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    item_id = data.get('item_id')
    transaction_type_raw = data.get('transaction_type') or data.get('movement_type')
    quantity = data.get('quantity')

    try:
        movement_type, reason_code = _parse_movement_payload(transaction_type_raw)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not item_id or quantity is None:
        return jsonify({'error': 'item_id, transaction_type (or movement_type), and quantity are required.'}), 400

    try:
        item, movement, is_low_stock = InventoryRepository.record_transaction(
            item_id=item_id,
            transaction_type=movement_type,
            quantity=quantity,
            reason_code=reason_code,
            unit_cost=data.get('unit_cost'),
            inventory_batch_id=data.get('inventory_batch_id'),
            logged_by=int(get_jwt_identity()),
            notes=data.get('notes'),
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    # IDEAL LOCATION: This financial link should be inside the repository transaction
    # to ensure atomicity. It is here to demonstrate the complete concept.
    if reason_code == 'SHRINKAGE':
        _link_inventory_loss_to_finance(movement, item)

    mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
    return jsonify({'movement': _serialize_movement(movement), 'updatedItem': _serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer), 'lowStock': is_low_stock}), 201


@inventory_bp.route('/api/inventory/items/<int:item_id>/audit', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def process_stock_audit(item_id):
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    data = request.get_json() or {}
    physical_count_raw = data.get('physical_count')
    if physical_count_raw is None:
        return jsonify({'error': 'physical_count is required.'}), 400

    try:
        physical_count = float(physical_count_raw)
        if physical_count < 0:
            raise ValueError()
    except (TypeError, ValueError):
        return jsonify({'error': 'physical_count must be a non-negative number.'}), 400

    item = InventoryRepository.get_item(item_id, tenant_id)
    if not item:
        return jsonify({'error': 'Inventory item not found.'}), 404

    system_count = float(item.current_qty)
    discrepancy = physical_count - system_count

    if abs(discrepancy) < 0.01:
        return jsonify({"status": "matched", "adjustment": 0, "message": "Physical count matches system count."}), 200

    tx_type, reason, qty_to_record, notes = ('IN', 'AUDIT_GAIN', discrepancy, "Physical stock reconciliation - gain detected.") if discrepancy > 0 else ('OUT', 'AUDIT_LOSS', abs(discrepancy), "Physical stock reconciliation - loss detected.")

    try:
        item, movement, _ = InventoryRepository.record_transaction(item_id=item.id, transaction_type=tx_type, quantity=qty_to_record, reason_code=reason, notes=notes, logged_by=int(get_jwt_identity()), tenant_id=tenant_id)
        if reason == 'AUDIT_LOSS':
            _link_inventory_loss_to_finance(movement, item)
        return jsonify({"status": "reconciled", "adjustment": discrepancy, "new_balance": float(item.current_qty), "movement": _serialize_movement(movement)}), 200
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@inventory_bp.route('/api/v1/nutrition/ingredient-standards', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND, Role.VET)
def list_ingredient_standards():
    tenant_id = get_tenant_id_from_context()
    payload = InventoryStandardsService.list_standards(tenant_id=tenant_id)
    return jsonify(payload), 200


@inventory_bp.route('/api/v1/nutrition/ingredient-standards', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.SUPER_ADMIN)
def upsert_ingredient_standard():
    tenant_id = get_tenant_id_from_context()
    data = request.get_json() or {}
    canonical_name = (data.get('canonical_name') or data.get('name') or '').strip()
    if not canonical_name:
        return jsonify({'error': 'canonical_name is required.'}), 400

    required_fields = ['protein_grams_per_kg', 'energy_mj_per_kg', 'fiber_grams_per_kg']
    missing = [field for field in required_fields if data.get(field) is None]
    if missing:
        return jsonify({'error': 'Missing required fields.', 'field_errors': [{'field': field, 'message': 'This field is required.'} for field in missing]}), 400

    canonical = InventoryStandardsService.upsert_standard(
        canonical_name=canonical_name,
        synonyms=data.get('synonyms') or [],
        data=data,
        tenant_id=tenant_id,
        actor_id=int(get_jwt_identity()),
    )
    return jsonify({'message': 'Ingredient standard updated.', 'canonical_name': canonical, 'standards_version': data.get('standards_version') or InventoryStandardsService.STANDARDS_VERSION}), 200


@inventory_bp.route('/api/v1/nutrition/ingredient-standards/backfill', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.SUPER_ADMIN)
def backfill_ingredient_standards_to_inventory():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400

    payload = request.get_json(silent=True) or {}
    dry_run = bool(payload.get('dry_run', False))

    items = InventoryRepository.list_by_tenant(tenant_id)
    result = InventoryStandardsService.run_backfill_for_tenant(
        tenant_id=tenant_id,
        item_rows=items,
    )

    if dry_run:
        from app import db
        db.session.rollback()
        return jsonify({'message': 'Dry run complete.', 'dry_run': True, **result}), 200

    from app import db
    db.session.commit()
    return jsonify({'message': 'Backfill completed.', 'dry_run': False, **result}), 200


@inventory_bp.route('/api/inventory/stock', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def inventory_stock_snapshot():
    tenant_id = get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    items = InventoryRepository.list_stock_snapshot(tenant_id)
    mix_share_defaults_by_mixer = _get_mix_share_defaults_by_mixer(tenant_id)
    flag = (request.args.get('flag') or '').strip().lower()
    rows = [
        {
            **_serialize_item(item, mix_share_defaults_by_mixer=mix_share_defaults_by_mixer),
            'lowStock': float(item.current_qty) <= float(item.minimum_threshold),
            'critical': float(item.current_qty) <= float(item.minimum_threshold) * 0.5,
        }
        for item in items
    ]
    if flag == 'low':
        rows = [row for row in rows if row['lowStock']]
    elif flag == 'critical':
        rows = [row for row in rows if row['critical']]
    page, per_page = _pagination_params()
    total = len(rows)
    start = (page - 1) * per_page
    end = start + per_page
    return jsonify({'items': rows[start:end], 'meta': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if total else 0}}), 200