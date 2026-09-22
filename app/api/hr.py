from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from app.models.user import Role
from app.services.account_invitation_service import AccountInvitationService
from app.services.hr_service import HRService
from app.services.staffing_recommendation_service import StaffingRecommendationService
from app.repositories.hr_repo import EmployeeRepository
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


def _get_farm_id_from_claims():
    farm_public_id = (get_jwt() or {}).get('farm_id')
    if not farm_public_id:
        return None
    try:
        return parse_public_int_id(farm_public_id, 'farm_')
    except (TypeError, ValueError):
        return None


def _parse_staff_id(staff_id):
    try:
        return parse_public_int_id(staff_id, 'staff_')
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


@hr_bp.route('/staff/<staff_id>/account-invite', methods=['POST'])
@hr_bp.route('/employees/<staff_id>/account-invite', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def invite_staff_account(staff_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    staff_pk = _parse_staff_id(staff_id)
    if staff_pk is None:
        return jsonify({'error': 'Missing or invalid staff id.'}), 400

    return AccountInvitationService.invite_employee(tenant_id, staff_pk, request.get_json(silent=True) or {})


@hr_bp.route('/staff/<staff_id>', methods=['GET'])
@hr_bp.route('/employees/<staff_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_staff(staff_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    staff_pk = _parse_staff_id(staff_id)
    if staff_pk is None:
        return jsonify({'error': 'Missing or invalid staff id.'}), 400

    return HRService.get_employee(tenant_id, staff_pk)


@hr_bp.route('/staff/<staff_id>', methods=['PATCH'])
@hr_bp.route('/employees/<staff_id>', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_staff(staff_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    staff_pk = _parse_staff_id(staff_id)
    if staff_pk is None:
        return jsonify({'error': 'Missing or invalid staff id.'}), 400

    data = request.get_json() or {}
    actor_id = get_jwt().get('sub')
    try:
        actor_id = int(actor_id) if actor_id is not None else None
    except (TypeError, ValueError):
        actor_id = None
    return HRService.update_employee(tenant_id, staff_pk, data, actor_id=actor_id)


@hr_bp.route('/staff/<staff_id>/verify-return', methods=['POST'])
@hr_bp.route('/employees/<staff_id>/verify-return', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def verify_staff_return(staff_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    staff_pk = _parse_staff_id(staff_id)
    if staff_pk is None:
        return jsonify({'error': 'Missing or invalid staff id.'}), 400

    data = request.get_json() or {}
    actor_id = get_jwt().get('sub')
    try:
        actor_id = int(actor_id) if actor_id is not None else None
    except (TypeError, ValueError):
        actor_id = None
    return HRService.verify_return(tenant_id, staff_pk, data, actor_id=actor_id)


@hr_bp.route('/staff', methods=['GET'])
@hr_bp.route('/employees', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_staff():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return HRService.list_employees(tenant_id)


@hr_bp.route('/staffing-recommendations', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def staffing_recommendations():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    employee_count = EmployeeRepository.count_active_by_tenant(tenant_id)
    return jsonify(StaffingRecommendationService.recommend(employee_count)), 200


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


@hr_bp.route('/payroll/runs', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def create_payroll_run():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    data = request.get_json() or {}
    claims = get_jwt()
    generated_by = claims.get('sub')
    farm_id = _get_farm_id_from_claims()
    return HRService.create_payroll_run(tenant_id, data, generated_by=generated_by, farm_id=farm_id)


@hr_bp.route('/payroll/runs', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_payroll_runs():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    return HRService.list_payroll_runs(tenant_id)


@hr_bp.route('/payroll/runs/<string:run_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    return HRService.get_payroll_run(tenant_id, run_id)


@hr_bp.route('/payroll/runs/<string:run_id>/finalize', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def finalize_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    actor_id = get_jwt().get('sub')
    return HRService.finalize_payroll_run(
        tenant_id,
        run_id,
        actor_id=actor_id,
        farm_id=_get_farm_id_from_claims(),
    )


@hr_bp.route('/payroll/runs/<string:run_id>/pay', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def pay_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    actor_id = get_jwt().get('sub')
    data = request.get_json(silent=True) or {}
    return HRService.pay_payroll_run(
        tenant_id,
        run_id,
        actor_id=actor_id,
        payment_reference=data.get('payment_reference', data.get('paymentReference')),
        farm_id=_get_farm_id_from_claims(),
    )


@hr_bp.route('/payroll', methods=['GET'])
@hr_bp.route('/payroll-records', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_payroll():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return HRService.list_payroll(tenant_id)
