from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from app.models.user import Role
from app.services.hr_service import HRService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id

hr_bp = Blueprint('hr', __name__)


def _get_tenant_id_from_claims():
    claims = get_jwt()
    tenant_public_id = claims.get('tenant_id')
    if not tenant_public_id:
        return None
    try:
        return parse_public_int_id(tenant_public_id, 'tenant_')
    except (TypeError, ValueError):
        return None


@hr_bp.route('/staff', methods=['POST'])
@hr_bp.route('/employees', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def register_staff():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return HRService.register_employee(tenant_id, data)


@hr_bp.route('/staff', methods=['GET'])
@hr_bp.route('/employees', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_staff():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return HRService.list_employees(tenant_id)


@hr_bp.route('/payroll', methods=['POST'])
@hr_bp.route('/payroll-records', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_payroll():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    return HRService.create_payroll(tenant_id, data)


@hr_bp.route('/payroll', methods=['GET'])
@hr_bp.route('/payroll-records', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_payroll():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return HRService.list_payroll(tenant_id)
