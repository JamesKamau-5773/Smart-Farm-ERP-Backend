from flask import Blueprint, jsonify, g, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.models.user import Role
from app.repositories.supply_repo import InventoryRepository
from app.utils.decorators import require_tenant_context, role_required
from app.utils.jwt_payload import parse_public_int_id

inventory_bp = Blueprint('inventory', __name__)


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