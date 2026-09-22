from flask import Blueprint, g, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from app.models.user import Role
from app.services.milk_disposition_service import (
    MilkDispositionConflictError,
    MilkDispositionService,
    MilkDispositionValidationError,
)
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id


milk_dispositions_bp = Blueprint('milk_dispositions', __name__)


def _tenant_id():
    value = getattr(g, 'tenant_id', None) or (get_jwt() or {}).get('tenant_id')
    try:
        return parse_public_int_id(str(value), 'tenant_')
    except (TypeError, ValueError):
        return None


@milk_dispositions_bp.route('/api/production/milk-dispositions', methods=['POST'])
@jwt_required()
@role_required(Role.FARM_HAND, Role.FARMER)
def create_milk_disposition():
    tenant_id = _tenant_id()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    try:
        payload = MilkDispositionService.record_calf_feeding(
            tenant_id=tenant_id,
            user_id=get_jwt_identity(),
            data=request.get_json(silent=True) or {},
        )
        return jsonify({'message': 'Calf feeding recorded successfully.', 'disposition': payload}), 201
    except MilkDispositionConflictError as exc:
        return jsonify({'error': str(exc)}), 409
    except MilkDispositionValidationError as exc:
        return jsonify({'error': str(exc)}), 400


@milk_dispositions_bp.route('/api/production/milk-dispositions', methods=['GET'])
@jwt_required()
@role_required(Role.FARM_HAND, Role.FARMER)
def list_milk_dispositions():
    tenant_id = _tenant_id()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    try:
        items = MilkDispositionService.list_dispositions(
            tenant_id=tenant_id,
            disposition_date=request.args.get('date'),
            calf_id=request.args.get('calf_id'),
        )
        return jsonify({'items': items, 'count': len(items)}), 200
    except MilkDispositionValidationError as exc:
        return jsonify({'error': str(exc)}), 400
