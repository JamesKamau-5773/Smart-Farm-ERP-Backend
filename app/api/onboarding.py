from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, jwt_required

from app.models.user import Role
from app.services.account_invitation_service import AccountInvitationService
from app.services.account_provisioning_service import AccountProvisioningService
from app.utils.decorators import role_required
from app.utils.jwt_payload import parse_public_int_id


onboarding_bp = Blueprint('onboarding', __name__)


def _request_context(data):
    claims = get_jwt() or {}
    try:
        tenant_id = parse_public_int_id(claims.get('tenant_id'), 'tenant_')
        actor_id = int(claims.get('sub'))
        employee_id = parse_public_int_id(data.get('employee_id') or data.get('employeeId'), 'staff_')
    except (TypeError, ValueError):
        return None
    return tenant_id, actor_id, employee_id


@onboarding_bp.route('/invite', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def invite_employee():
    data = request.get_json(silent=True) or {}
    context = _request_context(data)
    if context is None:
        return jsonify({'error': 'Valid tenant, actor, and employee_id are required.'}), 400
    tenant_id, actor_id, employee_id = context
    return AccountInvitationService.invite_employee(
        tenant_id,
        employee_id,
        data,
        actor_id=actor_id,
        ip_address=request.remote_addr,
    )


@onboarding_bp.route('/provision', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def provision_employee():
    data = request.get_json(silent=True) or {}
    context = _request_context(data)
    if context is None:
        return jsonify({'error': 'Valid tenant, actor, and employee_id are required.'}), 400
    tenant_id, actor_id, employee_id = context
    return AccountProvisioningService.provision_employee(
        tenant_id,
        employee_id,
        data,
        actor_id=actor_id,
        ip_address=request.remote_addr,
    )
