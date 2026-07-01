from datetime import date

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models.hr import Employee, Payroll


class EmployeeRepository:
    @staticmethod
    def create(*, tenant_id: int, full_name: str, hire_date: date, base_salary, id_number=None, phone_number=None, contract_type=None, id_card_doc_url=None, contract_doc_url=None, role=None, loan_balance=0, monthly_deduction=0, status='ACTIVE', leave_type=None, leave_start_date=None, leave_end_date=None, expected_return_date=None, actual_return_date=None, unpaid_leave_days_this_month=0, medical_certifications=None, medical_notes=None, return_verified_at=None, return_verification_decision=None, return_verification_note=None) -> Employee:
        try:
            employee = Employee(
                tenant_id=tenant_id,
                full_name=full_name,
                role=role,
                id_number=id_number,
                phone_number=phone_number,
                hire_date=hire_date,
                base_salary=base_salary,
                loan_balance=loan_balance,
                monthly_deduction=monthly_deduction,
                status=status,
                leave_type=leave_type,
                leave_start_date=leave_start_date,
                leave_end_date=leave_end_date,
                expected_return_date=expected_return_date,
                actual_return_date=actual_return_date,
                unpaid_leave_days_this_month=unpaid_leave_days_this_month,
                medical_certifications=medical_certifications,
                medical_notes=medical_notes,
                return_verified_at=return_verified_at,
                return_verification_decision=return_verification_decision,
                return_verification_note=return_verification_note,
                contract_type=contract_type,
                id_card_doc_url=id_card_doc_url,
                contract_doc_url=contract_doc_url,
            )
            db.session.add(employee)
            db.session.commit()
            return employee
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while saving employee.")

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list:
        return Employee.query.filter_by(tenant_id=tenant_id).order_by(Employee.id.desc()).all()

    @staticmethod
    def get_by_id_for_tenant(employee_id: int, tenant_id: int) -> Employee:
        return Employee.query.filter_by(id=employee_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_by_id_number_for_tenant(tenant_id: int, id_number: str) -> Employee:
        return Employee.query.filter_by(tenant_id=tenant_id, id_number=id_number).first()


class PayrollRepository:
    @staticmethod
    def create(*, tenant_id: int, staff_id: int, payroll_year: int, payroll_month: int, base_salary, bonuses=0, deductions=0, net_pay=None, payment_date=None, status='Pending', notes=None) -> Payroll:
        try:
            payroll = Payroll(
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
                notes=notes,
            )
            db.session.add(payroll)
            db.session.commit()
            return payroll
        except SQLAlchemyError:
            db.session.rollback()
            raise Exception("Failed, Database error while saving payroll.")

    @staticmethod
    def list_by_tenant(tenant_id: int) -> list:
        return Payroll.query.filter_by(tenant_id=tenant_id).order_by(Payroll.payroll_year.desc(), Payroll.payroll_month.desc(), Payroll.id.desc()).all()

    @staticmethod
    def get_by_id_for_tenant(payroll_id: int, tenant_id: int) -> Payroll:
        return Payroll.query.filter_by(id=payroll_id, tenant_id=tenant_id).first()

    @staticmethod
    def get_monthly_snapshot(*, tenant_id: int, staff_id: int, payroll_year: int, payroll_month: int) -> Payroll:
        return Payroll.query.filter_by(
            tenant_id=tenant_id,
            staff_id=staff_id,
            payroll_year=payroll_year,
            payroll_month=payroll_month,
        ).first()
