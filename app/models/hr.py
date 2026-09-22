from datetime import datetime, timezone

from app import db


class EmployeeOnboardingStatus:
    NONE = 'NONE'
    INVITE_PENDING = 'INVITE_PENDING'
    PASSWORD_RESET_REQUIRED = 'PASSWORD_RESET_REQUIRED'
    ACTIVE = 'ACTIVE'
    DISABLED = 'DISABLED'

    ALL = {NONE, INVITE_PENDING, PASSWORD_RESET_REQUIRED, ACTIVE, DISABLED}


class Employee(db.Model):
    __tablename__ = 'employees'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, unique=True)
    user = db.relationship('User', backref=db.backref('employee_profile', uselist=False), foreign_keys=[user_id])
    onboarding_status = db.Column(db.String(30), nullable=False, default=EmployeeOnboardingStatus.NONE)
    onboarding_invite_nonce = db.Column(db.String(32), nullable=True)
    onboarding_invite_expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), nullable=True)
    id_number = db.Column(db.String(50), nullable=True)
    phone_number = db.Column(db.String(30), nullable=True)
    hire_date = db.Column(db.Date, nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    loan_balance = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    monthly_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    status = db.Column(db.String(20), default='ACTIVE', nullable=False)
    leave_type = db.Column(db.String(50), nullable=True)
    leave_start_date = db.Column(db.Date, nullable=True)
    leave_end_date = db.Column(db.Date, nullable=True)
    expected_return_date = db.Column(db.Date, nullable=True)
    actual_return_date = db.Column(db.Date, nullable=True)
    unpaid_leave_days_this_month = db.Column(db.Integer, nullable=False, default=0)
    medical_certifications = db.Column(db.JSON, nullable=True)
    medical_notes = db.Column(db.Text, nullable=True)
    return_verified_at = db.Column(db.DateTime(timezone=True), nullable=True)
    return_verification_decision = db.Column(db.String(20), nullable=True)
    return_verification_note = db.Column(db.Text, nullable=True)
    contract_type = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    id_card_doc_url = db.Column(db.String(255), nullable=True)
    contract_doc_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    payroll_entries = db.relationship('Payroll', backref='employee', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'id_number', name='uq_employees_tenant_id_number'),
        db.CheckConstraint(
            "onboarding_status IN ('NONE', 'INVITE_PENDING', 'PASSWORD_RESET_REQUIRED', 'ACTIVE', 'DISABLED')",
            name='ck_employees_onboarding_status_valid',
        ),
    )


class PayrollStatus:
    PENDING = 'Pending'
    PAID = 'Paid'


class PayrollRunStatus:
    DRAFT = 'Draft'
    FINALIZED = 'Finalized'
    PAID = 'Paid'
    CANCELLED = 'Cancelled'


class PayrollRun(db.Model):
    __tablename__ = 'payroll_runs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farms.id'), nullable=True, index=True)
    payroll_year = db.Column(db.Integer, nullable=False)
    payroll_month = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=PayrollRunStatus.DRAFT)
    generated_by = db.Column(db.Integer, nullable=True)
    finalized_by = db.Column(db.Integer, nullable=True)
    paid_by = db.Column(db.Integer, nullable=True)
    generated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=True)
    total_gross_pay = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total_net_pay = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    total_deductions = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    line_items = db.relationship(
        'PayrollRunLineItem',
        backref='payroll_run',
        lazy=True,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.CheckConstraint("status IN ('Draft', 'Finalized', 'Paid', 'Cancelled')", name='ck_payroll_runs_status_valid'),
        db.CheckConstraint('payroll_month >= 1 AND payroll_month <= 12', name='ck_payroll_runs_month_valid'),
        db.UniqueConstraint('tenant_id', 'payroll_year', 'payroll_month', name='uq_payroll_runs_period'),
    )


class PayrollRunLineItem(db.Model):
    __tablename__ = 'payroll_run_line_items'

    id = db.Column(db.Integer, primary_key=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=False, index=True)
    staff_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    staff_name = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(20), nullable=False)
    base_salary = db.Column(db.Numeric(12, 2), nullable=False)
    approved_leave_days = db.Column(db.Integer, nullable=False, default=0)
    overdue_penalty_days = db.Column(db.Integer, nullable=False, default=0)
    leave_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    overdue_penalty_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    advance_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    gross_pay = db.Column(db.Numeric(12, 2), nullable=False)
    net_pay = db.Column(db.Numeric(12, 2), nullable=False)
    loan_balance = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    monthly_deduction = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    leave_type = db.Column(db.String(50), nullable=True)
    leave_start_date = db.Column(db.Date, nullable=True)
    leave_end_date = db.Column(db.Date, nullable=True)
    expected_return_date = db.Column(db.Date, nullable=True)
    actual_return_date = db.Column(db.Date, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('payroll_run_id', 'staff_id', name='uq_payroll_run_staff'),
    )


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
