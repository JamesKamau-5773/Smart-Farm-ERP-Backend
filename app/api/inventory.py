from flask import Blueprint, jsonify, g, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.models.user import Role
from app.repositories.supply_repo import InventoryRepository
from app.utils.decorators import require_tenant_context, role_required
from app.utils.jwt_payload import parse_public_int_id

inventory_bp = Blueprint('inventory', __name__)


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


def _serialize_item(item):
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
    }


def _serialize_movement(movement):
    return {
        'id': movement.id,
        'item_id': movement.item_id,
        'item_name': movement.item.name if movement.item else None,
        'quantity': float(movement.quantity),
        'movement_type': movement.transaction_type,
        'timestamp': movement.transaction_date.isoformat() if movement.transaction_date else None,
        'logged_by': movement.logged_by,
        'reference_note': movement.reference_note,
        'unit_cost': float(movement.unit_cost),
        'total_transaction_value': float(movement.total_transaction_value),
    }


def _get_tenant_id_from_context():
    tenant_public_id = getattr(g, 'tenant_id', None)
    if not tenant_public_id:
        return None

    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@inventory_bp.route('/api/v1/inventory/deduct', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def deduct_inventory():
    tenant_id = _get_tenant_id_from_context()
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

    note = data.get('reference_note') or 'Automated system deduction'
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
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    items = InventoryRepository.list_by_tenant(tenant_id)
    q = (request.args.get('q') or '').strip().lower()
    category = (request.args.get('category') or '').strip().lower()
    if q:
        items = [item for item in items if q in (item.name or '').lower() or q in (getattr(item, 'sku', '') or '').lower()]
    if category:
        items = [item for item in items if category == (item.category or '').lower()]
    page, per_page = _pagination_params()
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]
    return jsonify({'items': [_serialize_item(item) for item in page_items], 'meta': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page if total else 0}}), 200


@inventory_bp.route('/api/inventory/items', methods=['POST'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def create_inventory_item():
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    category = (data.get('category') or '').strip()
    unit = (data.get('unit') or '').strip()
    if not name or not category or not unit:
        return jsonify({'error': 'name, category, and unit are required.'}), 400
    item = InventoryRepository.create_item(
        tenant_id=tenant_id,
        name=name,
        sku=(data.get('sku') or '').strip() or None,
        category=category,
        unit=unit,
        current_qty=data.get('current_qty', data.get('currentStock', 0)),
        minimum_threshold=data.get('minimum_threshold', data.get('reorderLevel', 0)),
        energy_mj_per_kg=data.get('energy_mj_per_kg', 0),
        protein_grams_per_kg=data.get('protein_grams_per_kg', 0),
        fiber_grams_per_kg=data.get('fiber_grams_per_kg', 0),
        cost_per_kg=data.get('cost_per_kg', 0),
    )
    return jsonify(_serialize_item(item)), 201


@inventory_bp.route('/api/inventory/items/<int:item_id>', methods=['PATCH'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def update_inventory_item(item_id):
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    item = InventoryRepository.update_item(
        item_id=item_id,
        tenant_id=tenant_id,
        name=(data.get('name') or '').strip() if 'name' in data else None,
        sku=(data.get('sku') or '').strip() if 'sku' in data else None,
        category=(data.get('category') or '').strip() if 'category' in data else None,
        unit=(data.get('unit') or '').strip() if 'unit' in data else None,
        current_qty=data.get('current_qty', data.get('currentStock')) if ('current_qty' in data or 'currentStock' in data) else None,
        minimum_threshold=data.get('minimum_threshold', data.get('reorderLevel')) if ('minimum_threshold' in data or 'reorderLevel' in data) else None,
    )
    if not item:
        return jsonify({'error': 'Inventory item not found.'}), 404
    return jsonify(_serialize_item(item)), 200


@inventory_bp.route('/api/inventory/items/<int:item_id>', methods=['DELETE'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER)
def delete_inventory_item(item_id):
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    item = InventoryRepository.delete_item(item_id=item_id, tenant_id=tenant_id)
    if not item:
        return jsonify({'error': 'Inventory item not found.'}), 404
    return jsonify({'message': 'Inventory item deleted successfully.', 'deleted': _serialize_item(item)}), 200


@inventory_bp.route('/api/inventory/movements', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def list_inventory_movements():
    tenant_id = _get_tenant_id_from_context()
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
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    data = request.get_json() or {}
    item_id = data.get('item_id')
    movement_type = data.get('movement_type') or data.get('transaction_type')
    quantity = data.get('quantity')
    if not item_id or not movement_type or quantity is None:
        return jsonify({'error': 'item_id, movement_type, and quantity are required.'}), 400
    try:
        item, movement, is_low_stock = InventoryRepository.record_transaction(
            item_id=item_id,
            transaction_type=movement_type,
            quantity=quantity,
            unit_cost=data.get('unit_cost'),
            inventory_batch_id=data.get('inventory_batch_id'),
            logged_by=int(get_jwt_identity()),
            reference_note=data.get('reference_note'),
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'movement': _serialize_movement(movement), 'updatedItem': _serialize_item(item), 'lowStock': is_low_stock}), 201


@inventory_bp.route('/api/inventory/stock', methods=['GET'])
@jwt_required()
@require_tenant_context
@role_required(Role.FARMER, Role.FARM_HAND)
def inventory_stock_snapshot():
    tenant_id = _get_tenant_id_from_context()
    if tenant_id is None:
        return jsonify({"error": "Missing or invalid tenant context."}), 400
    items = InventoryRepository.list_stock_snapshot(tenant_id)
    flag = (request.args.get('flag') or '').strip().lower()
    rows = [
        {
            **_serialize_item(item),
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