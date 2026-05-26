from datetime import date
from decimal import Decimal

from flask import jsonify

from app.repositories.hr_repo import EmployeeRepository, PayrollRepository


class HRService:
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
    def register_employee(tenant_id: int, data: dict):
        full_name = (data.get('full_name') or '').strip()
        hire_date_raw = data.get('hire_date')
        base_salary_raw = data.get('base_salary')
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
        )

        return jsonify(
            {
                'message': 'Employee registered successfully.',
                'id': employee.id,
                'full_name': employee.full_name,
                'base_salary': HRService._to_float(employee.base_salary),
            }
        ), 201

    @staticmethod
    def list_employees(tenant_id: int):
        employees = EmployeeRepository.list_by_tenant(tenant_id)
        payload = [
            {
                'id': employee.id,
                'full_name': employee.full_name,
                'id_number': employee.id_number,
                'phone_number': employee.phone_number,
                'hire_date': employee.hire_date.isoformat(),
                'base_salary': HRService._to_float(employee.base_salary),
                'contract_type': employee.contract_type,
                'is_active': employee.is_active,
                'id_card_doc_url': employee.id_card_doc_url,
                'contract_doc_url': employee.contract_doc_url,
            }
            for employee in employees
        ]
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

        return jsonify(
            {
                'message': 'Payroll record created successfully.',
                'id': payroll.id,
                'staff_id': payroll.staff_id,
                'net_pay': HRService._to_float(payroll.net_pay),
                'status': payroll.status,
            }
        ), 201

    @staticmethod
    def list_payroll(tenant_id: int):
        payroll_entries = PayrollRepository.list_by_tenant(tenant_id)
        payload = [
            {
                'id': payroll.id,
                'staff_id': payroll.staff_id,
                'staff_name': payroll.employee.full_name if payroll.employee else None,
                'payroll_year': payroll.payroll_year,
                'payroll_month': payroll.payroll_month,
                'base_salary': HRService._to_float(payroll.base_salary),
                'bonuses': HRService._to_float(payroll.bonuses),
                'deductions': HRService._to_float(payroll.deductions),
                'net_pay': HRService._to_float(payroll.net_pay),
                'payment_date': payroll.payment_date.isoformat(),
                'status': payroll.status,
                'notes': payroll.notes,
            }
            for payroll in payroll_entries
        ]
        return jsonify(payload), 200
