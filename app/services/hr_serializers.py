"""API payloads for staff, payroll and advances.

HR payloads carry each field in both camelCase and snake_case, which older and
newer screens of the app read respectively.
"""
from __future__ import annotations

from decimal import Decimal

from app.models.hr import EMPLOYEE_STATUTORY_FIELDS, EMPLOYER_STATUTORY_FIELDS, STATUTORY_FIELDS, EmployeeLoanMovement, PayrollRun
from app.repositories.hr_repo import PayrollRepository
from app.services.employee_status_policy import EmployeeStatusPolicy

def _camel(name: str) -> str:
    head, *rest = name.split('_')
    return head + ''.join(part.title() for part in rest)


def _both(name: str, value) -> dict:
    return {_camel(name): value, name: value}


def _fields(**values) -> dict:
    payload = {}
    for name, value in values.items():
        payload.update(_both(name, value))
    return payload


def _float(value):
    return float(value) if isinstance(value, Decimal) else value


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _iso(value):
    return value.isoformat() if value else None


def period_id(year: int, month: int) -> str:
    return f'{year:04d}-{month:02d}'


class EmployeeSerializer:
    @staticmethod
    def serialize(employee) -> dict:
        user = employee.user
        return {
            'id': employee.id,
            'name': employee.full_name,
            'full_name': employee.full_name,
            'role': employee.role,
            'status': EmployeeStatusPolicy.current_status(employee),
            'page_access': user.page_access if user else None,
            'accountRole': user.role if user else None,
            **_fields(
                user_id=employee.user_id,
                account_status=employee.onboarding_status,
                onboarding_status=employee.onboarding_status,
                requires_password_reset=bool(user and user.requires_password_reset),
                invite_expires_at=_iso(employee.onboarding_invite_expires_at),
                base_salary=_float(employee.base_salary),
                loan_balance=_float(employee.loan_balance),
                monthly_deduction=_float(employee.monthly_deduction),
                leave_type=employee.leave_type,
                leave_start_date=_iso(employee.leave_start_date),
                leave_end_date=_iso(employee.leave_end_date),
                expected_return_date=_iso(employee.expected_return_date),
                actual_return_date=_iso(employee.actual_return_date),
                unpaid_leave_days_this_month=employee.unpaid_leave_days_this_month,
                medical_certifications=employee.medical_certifications or [],
                medical_notes=employee.medical_notes,
                return_verified_at=_iso(employee.return_verified_at),
                return_verification_decision=employee.return_verification_decision,
                return_verification_note=employee.return_verification_note,
                hire_date=_iso(employee.hire_date),
                id_number=employee.id_number,
                phone_number=employee.phone_number,
                contract_type=employee.contract_type,
                is_active=employee.is_active,
                id_card_doc_url=employee.id_card_doc_url,
                contract_doc_url=employee.contract_doc_url,
                created_at=_iso(employee.created_at),
                statutory_deductions_enabled=employee.statutory_deductions_enabled,
                end_date=_iso(employee.end_date),
                offboarding_reason=employee.offboarding_reason,
                offboarding_note=employee.offboarding_note,
                offboarded_at=_iso(employee.offboarded_at),
                is_offboarded=employee.end_date is not None,
            ),
        }


class PayrollRecordSerializer:
    @staticmethod
    def serialize(payroll) -> dict:
        gross = _float(payroll.base_salary) + _float(payroll.bonuses)
        return {
            'id': payroll.id,
            'bonuses': _float(payroll.bonuses),
            'deductions': _float(payroll.deductions),
            'status': payroll.status,
            'notes': payroll.notes,
            **_fields(
                staff_id=payroll.staff_id,
                staff_name=payroll.employee.full_name if payroll.employee else None,
                payroll_year=payroll.payroll_year,
                payroll_month=payroll.payroll_month,
                base_salary=_float(payroll.base_salary),
                gross_pay=gross,
                net_pay=_float(payroll.net_pay),
                payment_date=payroll.payment_date.isoformat(),
            ),
        }


class PayrollRunSerializer:
    @staticmethod
    def serialize(run: PayrollRun, line_items=None, *, include_lines: bool = True) -> dict:
        line_items = line_items if line_items is not None else PayrollRepository.get_run_line_items(run_id=run.id)

        def total(field):
            return sum((_decimal(getattr(item, field)) for item in line_items), Decimal('0'))

        statutory = {field: total(field) for field in STATUTORY_FIELDS}
        leave, overdue, advance = total('leave_deduction'), total('overdue_penalty_deduction'), total('advance_deduction')
        gross, net, deductions = _decimal(run.total_gross_pay), _decimal(run.total_net_pay), _decimal(run.total_deductions)
        staff_count = len(line_items)

        response = {
            'run': {
                'id': period_id(run.payroll_year, run.payroll_month),
                'payrollYear': run.payroll_year,
                'payrollMonth': run.payroll_month,
                'farmId': run.farm_id,
                'status': run.status,
                'generatedAt': _iso(run.generated_at),
                'generatedBy': run.generated_by,
                'finalizedAt': _iso(run.finalized_at),
                'paidAt': _iso(run.paid_at),
                'finalizedBy': run.finalized_by,
                'paidBy': run.paid_by,
                'staffCount': staff_count,
                'totalGrossPay': float(gross),
                'totalNetPay': float(net),
                'totalLeaveDeductions': float(leave),
                'totalOverduePenaltyDeductions': float(overdue),
                'totalAdvanceDeductions': float(advance),
                'totalDeductions': float(deductions),
                'notes': run.notes,
                **_fields(**{f'total_{field}': float(statutory[field]) for field in STATUTORY_FIELDS if field != 'taxable_pay'}),
                **_fields(total_employer_contributions=float(sum(statutory[field] for field in EMPLOYER_STATUTORY_FIELDS))),
            },
            'summary': {
                'staff_count': staff_count,
                'total_gross_pay': float(gross),
                'total_net_pay': float(net),
                'total_leave_deductions': float(leave),
                'total_overdue_penalty_deductions': float(overdue),
                'total_advance_deductions': float(advance),
                'total_deductions': float(deductions),
            },
        }
        if include_lines:
            response['lineItems'] = [PayrollRunSerializer.serialize_line(item) for item in line_items]
        return response

    @staticmethod
    def serialize_line(item) -> dict:
        return {
            'status': item.status,
            **_fields(
                staff_id=item.staff_id,
                staff_name=item.staff_name,
                base_salary=_float(item.base_salary),
                approved_leave_days=item.approved_leave_days,
                overdue_penalty_days=item.overdue_penalty_days,
                leave_deduction=_float(item.leave_deduction),
                advance_deduction=_float(item.advance_deduction),
                overdue_penalty_deduction=_float(item.overdue_penalty_deduction),
                gross_pay=_float(item.gross_pay),
                net_pay=_float(item.net_pay),
                loan_balance=_float(item.loan_balance),
                monthly_deduction=_float(item.monthly_deduction),
                leave_type=item.leave_type,
                leave_start_date=_iso(item.leave_start_date),
                leave_end_date=_iso(item.leave_end_date),
                expected_return_date=_iso(item.expected_return_date),
                actual_return_date=_iso(item.actual_return_date),
                days_paid=item.days_paid,
                statutory_rates_version=item.statutory_rates_version,
                total_statutory_deductions=float(sum(_decimal(getattr(item, field)) for field in EMPLOYEE_STATUTORY_FIELDS)),
                **{field: _float(_decimal(getattr(item, field))) for field in STATUTORY_FIELDS},
            ),
        }

    @staticmethod
    def serialize_summary_row(run: PayrollRun, staff_count: int) -> dict:
        return {
            'id': period_id(run.payroll_year, run.payroll_month),
            'payroll_year': run.payroll_year,
            'payroll_month': run.payroll_month,
            'status': run.status,
            'staff_count': int(staff_count),
            'total_gross_pay': float(run.total_gross_pay or 0),
            'total_deductions': float(run.total_deductions or 0),
            'total_net_pay': float(run.total_net_pay or 0),
            'generated_at': _iso(run.generated_at),
            'finalized_at': _iso(run.finalized_at),
            'paid_at': _iso(run.paid_at),
        }


class LoanMovementSerializer:
    @staticmethod
    def serialize(movement: EmployeeLoanMovement) -> dict:
        run = movement.payroll_run
        return {
            'id': movement.id,
            'kind': movement.kind,
            'amount': float(movement.amount),
            'balance_after': float(movement.balance_after),
            'date': movement.occurred_on.isoformat(),
            'note': movement.note,
            'payroll_run_id': period_id(run.payroll_year, run.payroll_month) if run else None,
            'ledger_transaction_id': movement.ledger_transaction_id,
            'recorded_by': movement.recorded_by,
            'created_at': _iso(movement.created_at),
        }
