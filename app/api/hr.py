from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt
from io import BytesIO

from app.models.user import Role
from app.services.account_invitation_service import AccountInvitationService
from app.services.employee_advance_service import EmployeeAdvanceService
from app.services.employee_offboarding_service import EmployeeOffboardingService
from app.services.hr_serializers import EmployeeSerializer, LoanMovementSerializer
from app.services.hr_service import HRService
from app.services.payroll_run_service import PayrollRunService
from app.services.staffing_recommendation_service import StaffingRecommendationService
from app.services.page_access import normalize_page_access
from app.repositories.hr_repo import EmployeeRepository
from app.services.payroll_summary_service import PayrollSummaryService
from app.services.payslip_service import PayslipService
from app.utils.api_errors import ApiError
from app.utils.decorators import role_required
from app.utils.error_envelope import register_error_envelope
from app.utils.jwt_payload import parse_public_int_id

hr_bp = Blueprint('hr', __name__)
register_error_envelope(hr_bp)


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


def _actor_id():
    try:
        return int(get_jwt().get('sub'))
    except (TypeError, ValueError):
        return None


def _tenant_and_staff(staff_id):
    tenant_id = _get_tenant_id_from_claims()
    staff_pk = _parse_staff_id(staff_id)
    if tenant_id is None or staff_pk is None:
        raise ApiError('VALIDATION_ERROR', 'Valid tenant and staff id are required.')
    return tenant_id, staff_pk


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


@hr_bp.route('/staff/<staff_id>/page-access', methods=['PATCH'])
@hr_bp.route('/employees/<staff_id>/page-access', methods=['PATCH'])
@jwt_required()
@role_required(Role.FARMER)
def update_staff_page_access(staff_id):
    if str((get_jwt() or {}).get('role') or '').upper() != Role.FARMER:
        return jsonify({'error': 'Only the farm owner can change staff page access.'}), 403

    tenant_id = _get_tenant_id_from_claims()
    staff_pk = _parse_staff_id(staff_id)
    if tenant_id is None or staff_pk is None:
        return jsonify({'error': 'Valid tenant and staff id are required.'}), 400

    employee = EmployeeRepository.get_by_id_for_tenant(staff_pk, tenant_id)
    if not employee or not employee.user:
        return jsonify({'error': 'Linked staff account not found.'}), 404

    data = request.get_json(silent=True) or {}
    if 'page_access' not in data:
        return jsonify({'error': 'page_access is required.'}), 400
    try:
        employee.user.page_access = normalize_page_access(data['page_access'], employee.user.role)
    except ValueError as error:
        return jsonify({'error': str(error)}), 400

    from app import db
    db.session.commit()
    return jsonify({
        'employee_id': employee.id,
        'user_id': employee.user_id,
        'page_access': employee.user.page_access,
    }), 200


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
    return jsonify(PayrollRunService.create(tenant_id, data, generated_by=generated_by, farm_id=farm_id)), 200


@hr_bp.route('/payroll/runs', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_payroll_runs():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    return jsonify(PayrollRunService.list_runs(tenant_id)), 200


@hr_bp.route('/payroll/runs/<string:run_id>', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def get_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    return jsonify(PayrollRunService.get(tenant_id, run_id)), 200


@hr_bp.route('/payroll/runs/<string:run_id>/finalize', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def finalize_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    actor_id = get_jwt().get('sub')
    return jsonify(PayrollRunService.finalize(
        tenant_id,
        run_id,
        actor_id=actor_id,
        farm_id=_get_farm_id_from_claims(),
    )), 200


@hr_bp.route('/payroll/runs/<string:run_id>/pay', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def pay_payroll_run(run_id):
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400
    actor_id = get_jwt().get('sub')
    data = request.get_json(silent=True) or {}
    return jsonify(PayrollRunService.pay(
        tenant_id,
        run_id,
        actor_id=actor_id,
        payment_reference=data.get('payment_reference', data.get('paymentReference')),
        farm_id=_get_farm_id_from_claims(),
    )), 200


@hr_bp.route('/payroll', methods=['GET'])
@hr_bp.route('/payroll-records', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_payroll():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        return jsonify({'error': 'Missing or invalid tenant in token.'}), 400

    return HRService.list_payroll(tenant_id)


@hr_bp.route('/staff/<staff_id>/offboard', methods=['POST'])
@hr_bp.route('/employees/<staff_id>/offboard', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def offboard_staff(staff_id):
    tenant_id, staff_pk = _tenant_and_staff(staff_id)
    employee = EmployeeOffboardingService.offboard(
        tenant_id, staff_pk, request.get_json(silent=True) or {}, actor_id=_actor_id(), ip_address=request.remote_addr,
    )
    return jsonify(EmployeeSerializer.serialize(employee)), 200


@hr_bp.route('/staff/<staff_id>', methods=['DELETE'])
@hr_bp.route('/employees/<staff_id>', methods=['DELETE'])
@jwt_required()
@role_required(Role.FARMER)
def delete_staff(staff_id):
    tenant_id, staff_pk = _tenant_and_staff(staff_id)
    EmployeeOffboardingService.delete(tenant_id, staff_pk, actor_id=_actor_id(), ip_address=request.remote_addr)
    return jsonify({'deleted': True, 'id': staff_pk}), 200


@hr_bp.route('/staff/<staff_id>/advances', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def list_staff_advances(staff_id):
    tenant_id, staff_pk = _tenant_and_staff(staff_id)
    employee, movements = EmployeeAdvanceService.history(tenant_id, staff_pk)
    return jsonify({
        'loan_balance': float(employee.loan_balance or 0),
        'monthly_deduction': float(employee.monthly_deduction or 0),
        'movements': [LoanMovementSerializer.serialize(movement) for movement in movements],
    }), 200


def _record_loan_movement(staff_id, record):
    tenant_id, staff_pk = _tenant_and_staff(staff_id)
    movement = record(tenant_id, staff_pk, request.get_json(silent=True) or {})
    return jsonify({
        'movement': LoanMovementSerializer.serialize(movement),
        'loan_balance': float(movement.balance_after),
    }), 201


@hr_bp.route('/staff/<staff_id>/advances', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def issue_staff_advance(staff_id):
    return _record_loan_movement(staff_id, lambda tenant_id, staff_pk, data: EmployeeAdvanceService.issue(
        tenant_id, staff_pk, data, actor_id=_actor_id(), farm_id=_get_farm_id_from_claims(),
    ))


@hr_bp.route('/staff/<staff_id>/advance-repayments', methods=['POST'])
@jwt_required()
@role_required(Role.FARMER)
def record_staff_advance_repayment(staff_id):
    return _record_loan_movement(staff_id, lambda tenant_id, staff_pk, data: EmployeeAdvanceService.repay(
        tenant_id, staff_pk, data, actor_id=_actor_id(),
    ))


@hr_bp.route('/payroll/runs/summary', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def payroll_run_summary():
    tenant_id = _get_tenant_id_from_claims()
    if tenant_id is None:
        raise ApiError('VALIDATION_ERROR', 'Missing or invalid tenant in token.')
    try:
        limit = min(max(int(request.args.get('limit', 24)), 1), 120)
    except (TypeError, ValueError):
        raise ApiError('VALIDATION_ERROR', 'limit must be a whole number.')
    return jsonify(PayrollSummaryService.summary(tenant_id, limit=limit)), 200


@hr_bp.route('/payroll/runs/<string:run_id>/payslips/<staff_id>.pdf', methods=['GET'])
@jwt_required()
@role_required(Role.FARMER)
def download_payslip(run_id, staff_id):
    tenant_id, staff_pk = _tenant_and_staff(staff_id)
    pdf, filename = PayslipService.render(tenant_id, run_id, staff_pk)
    return send_file(BytesIO(pdf), mimetype='application/pdf', as_attachment=True, download_name=filename)
