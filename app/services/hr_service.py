"""Employee records and the older one-off payroll records. Payroll runs live in PayrollRunService."""
from __future__ import annotations
from datetime import date
from datetime import datetime, timezone
from typing import Optional
from decimal import Decimal

from flask import jsonify

from app import db
from app.services.audit_service import record_audit
from app.repositories.hr_repo import EmployeeRepository, PayrollRepository
from app.services.employee_advance_service import EmployeeAdvanceService
from app.services.employee_status_policy import EmployeeStatusPolicy
from app.services.hr_serializers import EmployeeSerializer, PayrollRecordSerializer


class HRService:
    @staticmethod
    def _to_decimal(value):
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _parse_date(value, field_name: str, *, required: bool = False):
        if value in (None, ''):
            if required:
                raise ValueError(f'{field_name} is required.')
            return None
        try:
            return date.fromisoformat(str(value))
        except (TypeError, ValueError):
            raise ValueError(f'{field_name} must be in YYYY-MM-DD format.')

    @staticmethod
    def _parse_int(value, field_name: str, *, minimum: Optional[int] = None):
        if value in (None, ''):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise ValueError(f'{field_name} must be an integer.')
        if minimum is not None and parsed < minimum:
            raise ValueError(f'{field_name} must be greater than or equal to {minimum}.')
        return parsed

    @staticmethod
    def register_employee(tenant_id: int, data: dict):
        full_name = (data.get('full_name') or data.get('name') or '').strip()
        hire_date_raw = data.get('hire_date') or data.get('hireDate')
        base_salary_raw = data.get('base_salary', data.get('baseSalary'))
        id_number = (data.get('id_number') or '').strip() or None

        if not full_name or not hire_date_raw or base_salary_raw is None:
            return jsonify({'error': 'full_name, hire_date, and base_salary are required.'}), 400

        try:
            hire_date = date.fromisoformat(str(hire_date_raw))
        except (TypeError, ValueError):
            return jsonify({'error': 'hire_date must be in YYYY-MM-DD format.'}), 400

        if id_number:
            existing = EmployeeRepository.get_by_id_number_for_tenant(tenant_id, id_number)
            if existing:
                return jsonify({'error': 'An employee with this id_number already exists for this tenant.'}), 409

        try:
            base_salary = Decimal(str(base_salary_raw))
            if base_salary < 0:
                return jsonify({'error': 'base_salary cannot be negative.'}), 400
        except (TypeError, ValueError, ArithmeticError):
            return jsonify({'error': 'base_salary must be numeric.'}), 400

        role = (data.get('role') or '').strip() or None
        status_raw = data.get('status')
        try:
            status = EmployeeStatusPolicy.normalize(status_raw)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

        leave_start_date = None
        leave_end_date = None
        expected_return_date = None
        actual_return_date = None
        for field_name, raw_value in (
            ('leave_start_date', data.get('leave_start_date') or data.get('leaveStartDate')),
            ('leave_end_date', data.get('leave_end_date') or data.get('leaveEndDate')),
            ('expected_return_date', data.get('expected_return_date') or data.get('expectedReturnDate')),
            ('actual_return_date', data.get('actual_return_date') or data.get('actualReturnDate')),
        ):
            if raw_value is None:
                continue
            parsed_value = HRService._parse_date(raw_value, field_name)
            if field_name == 'leave_start_date':
                leave_start_date = parsed_value
            elif field_name == 'leave_end_date':
                leave_end_date = parsed_value
            elif field_name == 'expected_return_date':
                expected_return_date = parsed_value
            else:
                actual_return_date = parsed_value

        loan_balance = data.get('loan_balance', data.get('loanBalance', 0))
        monthly_deduction = data.get('monthly_deduction', data.get('monthlyDeduction', 0))
        unpaid_leave_days_this_month = data.get('unpaid_leave_days_this_month', data.get('unpaidLeaveDaysThisMonth', 0))

        try:
            loan_balance = HRService._to_decimal(loan_balance)
            monthly_deduction = HRService._to_decimal(monthly_deduction)
            unpaid_leave_days_this_month = HRService._parse_int(unpaid_leave_days_this_month, 'unpaid_leave_days_this_month', minimum=0) or 0
            if loan_balance < 0 or monthly_deduction < 0:
                return jsonify({'error': 'loan_balance and monthly_deduction cannot be negative.'}), 400
        except (TypeError, ValueError, ArithmeticError) as exc:
            return jsonify({'error': str(exc)}), 400

        medical_certifications = data.get('medical_certifications', data.get('medicalCertifications'))
        medical_notes = data.get('medical_notes', data.get('medicalNotes'))

        employee = EmployeeRepository.create(
            tenant_id=tenant_id,
            full_name=full_name,
            hire_date=hire_date,
            base_salary=base_salary,
            id_number=id_number,
            phone_number=data.get('phone_number'),
            contract_type=data.get('contract_type'),
            id_card_doc_url=data.get('id_card_doc_url'),
            contract_doc_url=data.get('contract_doc_url'),
            role=role,
            loan_balance=loan_balance,
            monthly_deduction=monthly_deduction,
            status=status,
            leave_type=data.get('leave_type', data.get('leaveType')),
            leave_start_date=leave_start_date,
            leave_end_date=leave_end_date,
            expected_return_date=expected_return_date,
            actual_return_date=actual_return_date,
            unpaid_leave_days_this_month=unpaid_leave_days_this_month,
            medical_certifications=medical_certifications,
            medical_notes=medical_notes,
            return_verification_decision=data.get('return_verification_decision', data.get('returnVerificationDecision')),
            return_verification_note=data.get('return_verification_note', data.get('returnVerificationNote')),
        )

        if 'statutory_deductions_enabled' in data or 'statutoryDeductionsEnabled' in data:
            employee.statutory_deductions_enabled = bool(data.get('statutory_deductions_enabled', data.get('statutoryDeductionsEnabled')))
        # Persist the authoritative status immediately for newly registered staff.
        EmployeeStatusPolicy.synchronize([employee])
        EmployeeAdvanceService.stage_opening_balance(employee)
        db.session.commit()

        return jsonify({
            'message': 'Employee registered successfully.',
            **EmployeeSerializer.serialize(employee),
        }), 201

    @staticmethod
    def list_employees(tenant_id: int):
        employees = EmployeeRepository.list_by_tenant(tenant_id)
        if EmployeeStatusPolicy.synchronize(employees):
            db.session.commit()
        payload = [EmployeeSerializer.serialize(employee) for employee in employees]
        return jsonify(payload), 200

    @staticmethod
    def get_employee(tenant_id: int, staff_id: int):
        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404
        if EmployeeStatusPolicy.synchronize([employee]):
            db.session.commit()
        return jsonify(EmployeeSerializer.serialize(employee)), 200

    @staticmethod
    def update_employee(tenant_id: int, staff_id: int, data: dict, *, actor_id: Optional[int] = None):
        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        old_state = EmployeeSerializer.serialize(employee)

        if 'full_name' in data or 'name' in data:
            employee.full_name = (data.get('full_name') or data.get('name') or employee.full_name).strip()

        if 'role' in data:
            employee.role = (data.get('role') or '').strip() or None

        if 'id_number' in data:
            employee.id_number = (data.get('id_number') or '').strip() or None

        if 'phone_number' in data:
            employee.phone_number = (data.get('phone_number') or '').strip() or None

        if 'hire_date' in data or 'hireDate' in data:
            try:
                employee.hire_date = HRService._parse_date(data.get('hire_date') or data.get('hireDate'), 'hire_date', required=True)
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

        if 'base_salary' in data or 'baseSalary' in data:
            try:
                base_salary = HRService._to_decimal(data.get('base_salary', data.get('baseSalary')))
                if base_salary < 0:
                    return jsonify({'error': 'base_salary cannot be negative.'}), 400
                employee.base_salary = base_salary
            except (TypeError, ValueError, ArithmeticError):
                return jsonify({'error': 'base_salary must be numeric.'}), 400

        if 'loan_balance' in data or 'loanBalance' in data:
            # Sending the unchanged balance is fine; changing it here would race with concurrent advances.
            try:
                loan_balance = HRService._to_decimal(data.get('loan_balance', data.get('loanBalance')))
            except (TypeError, ValueError, ArithmeticError):
                return jsonify({'error': 'loan_balance must be numeric.'}), 400
            if loan_balance != HRService._to_decimal(employee.loan_balance):
                return jsonify({
                    'code': 'BALANCE_CHANGE_REQUIRES_ADVANCE',
                    'error': 'Change the advance balance by issuing an advance or recording a repayment.',
                }), 400

        if 'statutory_deductions_enabled' in data or 'statutoryDeductionsEnabled' in data:
            employee.statutory_deductions_enabled = bool(data.get('statutory_deductions_enabled', data.get('statutoryDeductionsEnabled')))

        if 'monthly_deduction' in data or 'monthlyDeduction' in data:
            try:
                monthly_deduction = HRService._to_decimal(data.get('monthly_deduction', data.get('monthlyDeduction')))
                if monthly_deduction < 0:
                    return jsonify({'error': 'monthly_deduction cannot be negative.'}), 400
                employee.monthly_deduction = monthly_deduction
            except (TypeError, ValueError, ArithmeticError):
                return jsonify({'error': 'monthly_deduction must be numeric.'}), 400

        if 'status' in data:
            try:
                employee.status = EmployeeStatusPolicy.normalize(data.get('status'))
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

        if 'leave_type' in data or 'leaveType' in data:
            employee.leave_type = (data.get('leave_type') or data.get('leaveType') or '').strip() or None

        date_fields = (
            ('leave_start_date', 'leaveStartDate'),
            ('leave_end_date', 'leaveEndDate'),
            ('expected_return_date', 'expectedReturnDate'),
            ('actual_return_date', 'actualReturnDate'),
        )
        for snake_name, camel_name in date_fields:
            if snake_name in data or camel_name in data:
                try:
                    parsed = HRService._parse_date(data.get(snake_name, data.get(camel_name)), snake_name)
                except ValueError as exc:
                    return jsonify({'error': str(exc)}), 400
                setattr(employee, snake_name, parsed)

        if 'unpaid_leave_days_this_month' in data or 'unpaidLeaveDaysThisMonth' in data:
            try:
                employee.unpaid_leave_days_this_month = HRService._parse_int(
                    data.get('unpaid_leave_days_this_month', data.get('unpaidLeaveDaysThisMonth')),
                    'unpaid_leave_days_this_month',
                    minimum=0,
                ) or 0
            except ValueError as exc:
                return jsonify({'error': str(exc)}), 400

        if 'medical_certifications' in data or 'medicalCertifications' in data:
            employee.medical_certifications = data.get('medical_certifications', data.get('medicalCertifications'))

        if 'medical_notes' in data or 'medicalNotes' in data:
            employee.medical_notes = data.get('medical_notes', data.get('medicalNotes'))

        if 'return_verification_note' in data or 'returnVerificationNote' in data:
            employee.return_verification_note = data.get('return_verification_note', data.get('returnVerificationNote'))

        if 'return_verification_decision' in data or 'returnVerificationDecision' in data:
            employee.return_verification_decision = data.get('return_verification_decision', data.get('returnVerificationDecision'))

        employee.status = EmployeeStatusPolicy.current_status(employee)
        db.session.commit()

        if actor_id is not None:
            record_audit(
                user_id=actor_id,
                action='UPDATE_HR_STAFF',
                entity_type='Employee',
                entity_id=employee.id,
                old_value=old_state,
                new_value=EmployeeSerializer.serialize(employee),
                ip_address=None,
            )
            db.session.commit()

        return jsonify(EmployeeSerializer.serialize(employee)), 200

    @staticmethod
    def verify_return(tenant_id: int, staff_id: int, data: dict, *, actor_id: Optional[int] = None):
        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        returned = data.get('returned')
        if returned is None:
            return jsonify({'error': 'returned is required.'}), 400

        if isinstance(returned, str):
            returned = returned.strip().lower() in {'true', '1', 'yes', 'y'}
        else:
            returned = bool(returned)

        note = (data.get('note') or data.get('returnVerificationNote') or '').strip() or None
        previous_state = EmployeeSerializer.serialize(employee)

        employee.return_verified_at = datetime.now(timezone.utc)
        employee.return_verification_note = note

        if returned:
            employee.status = 'ACTIVE'
            employee.actual_return_date = date.today()
            employee.return_verification_decision = 'YES'
        else:
            employee.status = 'OVERDUE'
            employee.actual_return_date = None
            employee.return_verification_decision = 'NO'

        db.session.commit()

        if actor_id is not None:
            record_audit(
                user_id=actor_id,
                action='VERIFY_HR_RETURN',
                entity_type='Employee',
                entity_id=employee.id,
                old_value=previous_state,
                new_value=EmployeeSerializer.serialize(employee),
                ip_address=None,
            )
            db.session.commit()

        payload = EmployeeSerializer.serialize(employee)
        payload.update({
            'returnVerifiedAt': payload['returnVerifiedAt'],
            'returnVerificationDecision': payload['returnVerificationDecision'],
            'returnVerificationNote': payload['returnVerificationNote'],
        })
        return jsonify(payload), 200

    @staticmethod
    def create_payroll(tenant_id: int, data: dict):
        staff_id = data.get('staff_id')
        payroll_year = data.get('payroll_year')
        payroll_month = data.get('payroll_month')
        payment_date_raw = data.get('payment_date')

        if staff_id is None or payroll_year is None or payroll_month is None:
            return jsonify({'error': 'staff_id, payroll_year, and payroll_month are required.'}), 400

        try:
            staff_id = int(staff_id)
            payroll_year = int(payroll_year)
            payroll_month = int(payroll_month)
            if payroll_month < 1 or payroll_month > 12:
                return jsonify({'error': 'payroll_month must be between 1 and 12.'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'staff_id, payroll_year, and payroll_month must be integers.'}), 400

        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        existing = PayrollRepository.get_monthly_snapshot(
            tenant_id=tenant_id,
            staff_id=staff_id,
            payroll_year=payroll_year,
            payroll_month=payroll_month,
        )
        if existing:
            return jsonify({'error': 'Payroll already exists for this employee and period.'}), 409

        try:
            bonuses = HRService._to_decimal(data.get('bonuses', 0))
            deductions = HRService._to_decimal(data.get('deductions', 0))
            if bonuses < 0 or deductions < 0:
                return jsonify({'error': 'bonuses and deductions cannot be negative.'}), 400
        except (TypeError, ValueError, ArithmeticError):
            return jsonify({'error': 'bonuses and deductions must be numeric.'}), 400

        base_salary = HRService._to_decimal(data.get('base_salary', employee.base_salary))
        if base_salary < 0:
            return jsonify({'error': 'base_salary cannot be negative.'}), 400

        net_pay = base_salary + bonuses - deductions
        if net_pay < 0:
            net_pay = Decimal('0')

        if payment_date_raw:
            try:
                payment_date = date.fromisoformat(str(payment_date_raw))
            except (TypeError, ValueError):
                return jsonify({'error': 'payment_date must be in YYYY-MM-DD format.'}), 400
        else:
            payment_date = date(payroll_year, payroll_month, 1)

        status = (data.get('status') or 'Pending').strip().title()
        if status not in {'Pending', 'Paid'}:
            return jsonify({'error': 'status must be Pending or Paid.'}), 400

        payroll = PayrollRepository.create(
            tenant_id=tenant_id,
            staff_id=staff_id,
            payroll_year=payroll_year,
            payroll_month=payroll_month,
            base_salary=base_salary,
            bonuses=bonuses,
            deductions=deductions,
            net_pay=net_pay,
            payment_date=payment_date,
            status=status,
            notes=data.get('notes'),
        )

        return jsonify({
            'message': 'Payroll record created successfully.',
            **PayrollRecordSerializer.serialize(payroll),
        }), 201

    @staticmethod
    def list_payroll(tenant_id: int):
        payroll_entries = PayrollRepository.list_by_tenant(tenant_id)
        payload = [PayrollRecordSerializer.serialize(payroll) for payroll in payroll_entries]
        return jsonify(payload), 200
