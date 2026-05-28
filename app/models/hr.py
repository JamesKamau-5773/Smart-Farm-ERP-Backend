from datetime import datetime, timezone

from app import db


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    id_number = db.Column(db.String(50), nullable=True)
    phone_number = db.Column(db.String(30), nullable=True)
    hire_date = db.Column(db.Date, nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    contract_type = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    id_card_doc_url = db.Column(db.String(255), nullable=True)
    contract_doc_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    payroll_entries = db.relationship('Payroll', backref='employee', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'id_number', name='uq_employees_tenant_id_number'),
    )


class PayrollStatus:
    PENDING = 'Pending'
    PAID = 'Paid'


class Payroll(db.Model):
    __tablename__ = 'payroll'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    payroll_year = db.Column(db.Integer, nullable=False)
    payroll_month = db.Column(db.Integer, nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    bonuses = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    deductions = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    net_pay = db.Column(db.Numeric(12, 2), nullable=False)
    payment_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), default=PayrollStatus.PENDING, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint("status IN ('Pending', 'Paid')", name='ck_payroll_status_valid'),
        db.CheckConstraint('payroll_month >= 1 AND payroll_month <= 12', name='ck_payroll_month_valid'),
        db.UniqueConstraint('tenant_id', 'staff_id', 'payroll_year', 'payroll_month', name='uq_payroll_monthly_snapshot'),
    )
