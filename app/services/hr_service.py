from __future__ import annotations
from datetime import date
from datetime import datetime, timezone
import calendar
from decimal import Decimal

from flask import jsonify

from app import db
from app.services.audit_service import record_audit
from app.repositories.hr_repo import EmployeeRepository, PayrollRepository


class HRService:
    VALID_STATUSES = {'ACTIVE', 'ON_LEAVE', 'OVERDUE', 'INACTIVE'}

    @staticmethod
    def _to_decimal(value):
        if value is None:
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _to_float(value):
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def _iso_date(value):
        return value.isoformat() if value else None

    @staticmethod
    def _iso_datetime(value):
        return value.isoformat() if value else None

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
    def _parse_int(value, field_name: str, *, minimum: int | None = None):
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
    def _normalize_status(value: str | None):
        if not value:
            return 'ACTIVE'
        normalized = str(value).strip().upper()
        if normalized not in HRService.VALID_STATUSES:
            raise ValueError("status must be one of ACTIVE, ON_LEAVE, OVERDUE, or INACTIVE.")
        return normalized

    @staticmethod
    def _current_status(employee):
        status = (employee.status or 'ACTIVE').upper()
        if status == 'ON_LEAVE' and employee.expected_return_date and not employee.actual_return_date:
            if employee.expected_return_date < date.today():
                return 'OVERDUE'
        return status

    @staticmethod
    def _synchronize_employee_status(employee):
        computed_status = HRService._current_status(employee)
        if employee.status != computed_status:
            employee.status = computed_status
            return True
        return False

    @staticmethod
    def _synchronize_employee_statuses(employees):
        changed = False
        for employee in employees:
            changed = HRService._synchronize_employee_status(employee) or changed
        if changed:
            db.session.commit()
        return changed

    @staticmethod
    def _compute_leave_days(employee, payroll_year: int, payroll_month: int):
        if employee.unpaid_leave_days_this_month:
            return int(employee.unpaid_leave_days_this_month)

        start_date = employee.leave_start_date
        end_date = employee.leave_end_date or employee.expected_return_date or employee.actual_return_date
        if not start_date or not end_date:
            return 0

        month_start = date(payroll_year, payroll_month, 1)
        month_end = date(payroll_year, payroll_month, calendar.monthrange(payroll_year, payroll_month)[1])
        overlap_start = max(start_date, month_start)
        overlap_end = min(end_date, month_end)
        if overlap_end < overlap_start:
            return 0
        return (overlap_end - overlap_start).days + 1

    @staticmethod
    def _compute_overdue_days(employee, payroll_year: int, payroll_month: int):
        if not employee.expected_return_date or employee.actual_return_date:
            return 0

        month_end = date(payroll_year, payroll_month, calendar.monthrange(payroll_year, payroll_month)[1])
        if employee.expected_return_date >= month_end:
            return 0
        return max((month_end - employee.expected_return_date).days, 0)

    @staticmethod
    def _serialize_employee(employee):
        status = HRService._current_status(employee)
        return {
            'id': employee.id,
            'name': employee.full_name,
            'full_name': employee.full_name,
            'role': employee.role,
            'status': status,
            'baseSalary': HRService._to_float(employee.base_salary),
            'base_salary': HRService._to_float(employee.base_salary),
            'loanBalance': HRService._to_float(employee.loan_balance),
            'loan_balance': HRService._to_float(employee.loan_balance),
            'monthlyDeduction': HRService._to_float(employee.monthly_deduction),
            'monthly_deduction': HRService._to_float(employee.monthly_deduction),
            'leaveType': employee.leave_type,
            'leave_type': employee.leave_type,
            'leaveStartDate': HRService._iso_date(employee.leave_start_date),
            'leave_start_date': HRService._iso_date(employee.leave_start_date),
            'leaveEndDate': HRService._iso_date(employee.leave_end_date),
            'leave_end_date': HRService._iso_date(employee.leave_end_date),
            'expectedReturnDate': HRService._iso_date(employee.expected_return_date),
            'expected_return_date': HRService._iso_date(employee.expected_return_date),
            'actualReturnDate': HRService._iso_date(employee.actual_return_date),
            'actual_return_date': HRService._iso_date(employee.actual_return_date),
            'unpaidLeaveDaysThisMonth': employee.unpaid_leave_days_this_month,
            'unpaid_leave_days_this_month': employee.unpaid_leave_days_this_month,
            'medicalCertifications': employee.medical_certifications or [],
            'medical_certifications': employee.medical_certifications or [],
            'medicalNotes': employee.medical_notes,
            'medical_notes': employee.medical_notes,
            'returnVerifiedAt': HRService._iso_datetime(employee.return_verified_at),
            'return_verified_at': HRService._iso_datetime(employee.return_verified_at),
            'returnVerificationDecision': employee.return_verification_decision,
            'return_verification_decision': employee.return_verification_decision,
            'returnVerificationNote': employee.return_verification_note,
            'return_verification_note': employee.return_verification_note,
            'hireDate': HRService._iso_date(employee.hire_date),
            'hire_date': HRService._iso_date(employee.hire_date),
            'idNumber': employee.id_number,
            'id_number': employee.id_number,
            'phoneNumber': employee.phone_number,
            'phone_number': employee.phone_number,
            'contractType': employee.contract_type,
            'contract_type': employee.contract_type,
            'isActive': employee.is_active,
            'is_active': employee.is_active,
            'idCardDocUrl': employee.id_card_doc_url,
            'id_card_doc_url': employee.id_card_doc_url,
            'contractDocUrl': employee.contract_doc_url,
            'contract_doc_url': employee.contract_doc_url,
            'createdAt': HRService._iso_datetime(employee.created_at),
            'created_at': HRService._iso_datetime(employee.created_at),
        }

    @staticmethod
    def _serialize_payroll_record(payroll):
        return {
            'id': payroll.id,
            'staffId': payroll.staff_id,
            'staff_id': payroll.staff_id,
            'staffName': payroll.employee.full_name if payroll.employee else None,
            'staff_name': payroll.employee.full_name if payroll.employee else None,
            'payrollYear': payroll.payroll_year,
            'payroll_year': payroll.payroll_year,
            'payrollMonth': payroll.payroll_month,
            'payroll_month': payroll.payroll_month,
            'baseSalary': HRService._to_float(payroll.base_salary),
            'base_salary': HRService._to_float(payroll.base_salary),
            'bonuses': HRService._to_float(payroll.bonuses),
            'deductions': HRService._to_float(payroll.deductions),
            'grossPay': HRService._to_float(payroll.base_salary) + HRService._to_float(payroll.bonuses),
            'gross_pay': HRService._to_float(payroll.base_salary) + HRService._to_float(payroll.bonuses),
            'netPay': HRService._to_float(payroll.net_pay),
            'net_pay': HRService._to_float(payroll.net_pay),
            'paymentDate': payroll.payment_date.isoformat(),
            'payment_date': payroll.payment_date.isoformat(),
            'status': payroll.status,
            'notes': payroll.notes,
        }

    @staticmethod
    def _build_payroll_run_line_item(employee, payroll_year: int, payroll_month: int):
        base_salary = HRService._to_decimal(employee.base_salary)
        loan_balance = HRService._to_decimal(employee.loan_balance)
        monthly_deduction = HRService._to_decimal(employee.monthly_deduction)

        approved_leave_days = HRService._compute_leave_days(employee, payroll_year, payroll_month)
        overdue_penalty_days = HRService._compute_overdue_days(employee, payroll_year, payroll_month)

        month_days = calendar.monthrange(payroll_year, payroll_month)[1]
        daily_rate = base_salary / Decimal(str(month_days))
        leave_deduction = (daily_rate * Decimal(str(approved_leave_days))).quantize(Decimal('0.01'))
        overdue_penalty_deduction = (daily_rate * Decimal(str(overdue_penalty_days))).quantize(Decimal('0.01'))
        advance_deduction = min(monthly_deduction, loan_balance).quantize(Decimal('0.01')) if loan_balance > 0 else Decimal('0.00')

        gross_pay = base_salary.quantize(Decimal('0.01'))
        net_pay = gross_pay - leave_deduction - overdue_penalty_deduction - advance_deduction
        if net_pay < 0:
            net_pay = Decimal('0.00')

        return {
            'staffId': employee.id,
            'staff_id': employee.id,
            'staffName': employee.full_name,
            'staff_name': employee.full_name,
            'status': HRService._current_status(employee),
            'baseSalary': HRService._to_float(base_salary),
            'base_salary': HRService._to_float(base_salary),
            'approvedLeaveDays': approved_leave_days,
            'approved_leave_days': approved_leave_days,
            'overduePenaltyDays': overdue_penalty_days,
            'overdue_penalty_days': overdue_penalty_days,
            'leaveDeduction': HRService._to_float(leave_deduction),
            'leave_deduction': HRService._to_float(leave_deduction),
            'advanceDeduction': HRService._to_float(advance_deduction),
            'advance_deduction': HRService._to_float(advance_deduction),
            'overduePenaltyDeduction': HRService._to_float(overdue_penalty_deduction),
            'overdue_penalty_deduction': HRService._to_float(overdue_penalty_deduction),
            'grossPay': HRService._to_float(gross_pay),
            'gross_pay': HRService._to_float(gross_pay),
            'netPay': HRService._to_float(net_pay),
            'net_pay': HRService._to_float(net_pay),
            'loanBalance': HRService._to_float(loan_balance),
            'loan_balance': HRService._to_float(loan_balance),
            'monthlyDeduction': HRService._to_float(monthly_deduction),
            'monthly_deduction': HRService._to_float(monthly_deduction),
            'leaveType': employee.leave_type,
            'leave_type': employee.leave_type,
            'leaveStartDate': HRService._iso_date(employee.leave_start_date),
            'leave_start_date': HRService._iso_date(employee.leave_start_date),
            'leaveEndDate': HRService._iso_date(employee.leave_end_date),
            'leave_end_date': HRService._iso_date(employee.leave_end_date),
            'expectedReturnDate': HRService._iso_date(employee.expected_return_date),
            'expected_return_date': HRService._iso_date(employee.expected_return_date),
            'actualReturnDate': HRService._iso_date(employee.actual_return_date),
            'actual_return_date': HRService._iso_date(employee.actual_return_date),
        }

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
            status = HRService._normalize_status(status_raw)
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

        # Persist the authoritative status immediately for newly registered staff.
        if HRService._synchronize_employee_status(employee):
            db.session.commit()

        return jsonify({
            'message': 'Employee registered successfully.',
            **HRService._serialize_employee(employee),
        }), 201

    @staticmethod
    def list_employees(tenant_id: int):
        employees = EmployeeRepository.list_by_tenant(tenant_id)
        HRService._synchronize_employee_statuses(employees)
        payload = [HRService._serialize_employee(employee) for employee in employees]
        return jsonify(payload), 200

    @staticmethod
    def get_employee(tenant_id: int, staff_id: int):
        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404
        if HRService._synchronize_employee_status(employee):
            db.session.commit()
        return jsonify(HRService._serialize_employee(employee)), 200

    @staticmethod
    def update_employee(tenant_id: int, staff_id: int, data: dict, *, actor_id: int | None = None):
        employee = EmployeeRepository.get_by_id_for_tenant(staff_id, tenant_id)
        if not employee:
            return jsonify({'error': 'Employee not found for this tenant.'}), 404

        old_state = HRService._serialize_employee(employee)

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
            try:
                loan_balance = HRService._to_decimal(data.get('loan_balance', data.get('loanBalance')))
                if loan_balance < 0:
                    return jsonify({'error': 'loan_balance cannot be negative.'}), 400
                employee.loan_balance = loan_balance
            except (TypeError, ValueError, ArithmeticError):
                return jsonify({'error': 'loan_balance must be numeric.'}), 400

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
                employee.status = HRService._normalize_status(data.get('status'))
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

        employee.status = HRService._current_status(employee)
        db.session.commit()

        if actor_id is not None:
            record_audit(
                user_id=actor_id,
                action='UPDATE_HR_STAFF',
                entity_type='Employee',
                entity_id=employee.id,
                old_value=old_state,
                new_value=HRService._serialize_employee(employee),
                ip_address=None,
            )
            db.session.commit()

        return jsonify(HRService._serialize_employee(employee)), 200

    @staticmethod
    def verify_return(tenant_id: int, staff_id: int, data: dict, *, actor_id: int | None = None):
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
        previous_state = HRService._serialize_employee(employee)

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
                new_value=HRService._serialize_employee(employee),
                ip_address=None,
            )
            db.session.commit()

        payload = HRService._serialize_employee(employee)
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
            **HRService._serialize_payroll_record(payroll),
        }), 201

    @staticmethod
    def list_payroll(tenant_id: int):
        payroll_entries = PayrollRepository.list_by_tenant(tenant_id)
        payload = [HRService._serialize_payroll_record(payroll) for payroll in payroll_entries]
        return jsonify(payload), 200

    @staticmethod
    def create_payroll_run(tenant_id: int, data: dict, *, generated_by=None, farm_id=None):
        payroll_year = data.get('payroll_year', data.get('payrollYear'))
        payroll_month = data.get('payroll_month', data.get('payrollMonth'))
        if payroll_year is None or payroll_month is None:
            return jsonify({'error': 'payroll_year and payroll_month are required.'}), 400

        try:
            payroll_year = int(payroll_year)
            payroll_month = int(payroll_month)
            if payroll_month < 1 or payroll_month > 12:
                return jsonify({'error': 'payroll_month must be between 1 and 12.'}), 400
        except (TypeError, ValueError):
            return jsonify({'error': 'payroll_year and payroll_month must be integers.'}), 400

        employees = EmployeeRepository.list_by_tenant(tenant_id)
        HRService._synchronize_employee_statuses(employees)
        line_items = [HRService._build_payroll_run_line_item(employee, payroll_year, payroll_month) for employee in employees]
        total_gross = sum(Decimal(str(item['grossPay'])) for item in line_items)
        total_net = sum(Decimal(str(item['netPay'])) for item in line_items)
        total_leave_deductions = sum(Decimal(str(item['leaveDeduction'])) for item in line_items)
        total_overdue_penalty_deductions = sum(Decimal(str(item['overduePenaltyDeduction'])) for item in line_items)
        total_advance_deductions = sum(Decimal(str(item['advanceDeduction'])) for item in line_items)
        total_deductions = total_leave_deductions + total_overdue_penalty_deductions + total_advance_deductions

        generated_at = datetime.now(timezone.utc)
        response = {
            'message': 'Payroll run generated successfully.',
            'run': {
                'id': f'{payroll_year:04d}-{payroll_month:02d}',
                'payrollYear': payroll_year,
                'payrollMonth': payroll_month,
                'generatedAt': generated_at.isoformat(),
                'generatedBy': generated_by,
                'farmId': farm_id,
                'staffCount': len(line_items),
                'totalGrossPay': float(total_gross),
                'totalNetPay': float(total_net),
                'totalLeaveDeductions': float(total_leave_deductions),
                'totalOverduePenaltyDeductions': float(total_overdue_penalty_deductions),
                'totalAdvanceDeductions': float(total_advance_deductions),
                'totalDeductions': float(total_deductions),
                'metadata': {
                    'tenantId': tenant_id,
                    'payrollYear': payroll_year,
                    'payrollMonth': payroll_month,
                    'calculationSource': 'server',
                },
            },
            'summary': {
                'staff_count': len(line_items),
                'total_gross_pay': float(total_gross),
                'total_net_pay': float(total_net),
                'total_leave_deductions': float(total_leave_deductions),
                'total_overdue_penalty_deductions': float(total_overdue_penalty_deductions),
                'total_advance_deductions': float(total_advance_deductions),
                'total_deductions': float(total_deductions),
            },
            'lineItems': line_items,
        }
        return jsonify(response), 200

    @staticmethod
    def list_payroll_runs(tenant_id: int):
        rows = PayrollRepository.list_by_tenant(tenant_id)
        grouped: dict[tuple[int, int], dict] = {}
        for row in rows:
            key = (row.payroll_year, row.payroll_month)
            if key not in grouped:
                grouped[key] = {
                    'id': f'{row.payroll_year:04d}-{row.payroll_month:02d}',
                    'payrollYear': row.payroll_year,
                    'payrollMonth': row.payroll_month,
                    'staffCount': 0,
                    'totalGrossPay': Decimal('0'),
                    'totalNetPay': Decimal('0'),
                    'generatedAt': HRService._iso_datetime(row.created_at),
                }
            grouped[key]['staffCount'] += 1
            grouped[key]['totalGrossPay'] += HRService._to_decimal(row.base_salary) + HRService._to_decimal(row.bonuses)
            grouped[key]['totalNetPay'] += HRService._to_decimal(row.net_pay)

        payload = []
        for _, run in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1]), reverse=True):
            payload.append({
                **run,
                'totalGrossPay': float(run['totalGrossPay']),
                'totalNetPay': float(run['totalNetPay']),
            })
        return jsonify(payload), 200

    @staticmethod
    def get_payroll_run(tenant_id: int, run_id: str):
        try:
            payroll_year_str, payroll_month_str = str(run_id).split('-', 1)
            payroll_year = int(payroll_year_str)
            payroll_month = int(payroll_month_str)
        except (ValueError, TypeError):
            return jsonify({'error': 'run_id must be in YYYY-MM format.'}), 400

        employees = EmployeeRepository.list_by_tenant(tenant_id)
        HRService._synchronize_employee_statuses(employees)
        line_items = [HRService._build_payroll_run_line_item(employee, payroll_year, payroll_month) for employee in employees]
        total_gross = sum(Decimal(str(item['grossPay'])) for item in line_items)
        total_net = sum(Decimal(str(item['netPay'])) for item in line_items)
        total_leave_deductions = sum(Decimal(str(item['leaveDeduction'])) for item in line_items)
        total_overdue_penalty_deductions = sum(Decimal(str(item['overduePenaltyDeduction'])) for item in line_items)
        total_advance_deductions = sum(Decimal(str(item['advanceDeduction'])) for item in line_items)
        total_deductions = total_leave_deductions + total_overdue_penalty_deductions + total_advance_deductions

        payload = {
            'run': {
                'id': f'{payroll_year:04d}-{payroll_month:02d}',
                'payrollYear': payroll_year,
                'payrollMonth': payroll_month,
                'staffCount': len(line_items),
                'totalGrossPay': float(total_gross),
                'totalNetPay': float(total_net),
                'totalLeaveDeductions': float(total_leave_deductions),
                'totalOverduePenaltyDeductions': float(total_overdue_penalty_deductions),
                'totalAdvanceDeductions': float(total_advance_deductions),
                'totalDeductions': float(total_deductions),
            },
            'summary': {
                'staff_count': len(line_items),
                'total_gross_pay': float(total_gross),
                'total_net_pay': float(total_net),
                'total_leave_deductions': float(total_leave_deductions),
                'total_overdue_penalty_deductions': float(total_overdue_penalty_deductions),
                'total_advance_deductions': float(total_advance_deductions),
                'total_deductions': float(total_deductions),
            },
            'lineItems': line_items,
        }
        return jsonify(payload), 200
