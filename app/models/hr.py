from datetime import datetime, timezone

from app import db


class EmployeeOnboardingStatus:
    NONE = 'NONE'
    INVITE_PENDING = 'INVITE_PENDING'
    PASSWORD_RESET_REQUIRED = 'PASSWORD_RESET_REQUIRED'
    ACTIVE = 'ACTIVE'
    DISABLED = 'DISABLED'

    ALL = {NONE, INVITE_PENDING, PASSWORD_RESET_REQUIRED, ACTIVE, DISABLED}


class OffboardingReason:
    RESIGNED = 'RESIGNED'
    CONTRACT_ENDED = 'CONTRACT_ENDED'
    DISMISSED = 'DISMISSED'
    REDUNDANCY = 'REDUNDANCY'
    RETIRED = 'RETIRED'
    DECEASED = 'DECEASED'
    OTHER = 'OTHER'

    ALL = {RESIGNED, CONTRACT_ENDED, DISMISSED, REDUNDANCY, RETIRED, DECEASED, OTHER}


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
    # PAYE, NSSF, SHIF and the Housing Levy; switched off only for staff the farm doesn't run through payroll tax.
    statutory_deductions_enabled = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    end_date = db.Column(db.Date, nullable=True)
    offboarding_reason = db.Column(db.String(30), nullable=True)
    offboarding_note = db.Column(db.Text, nullable=True)
    offboarded_at = db.Column(db.DateTime(timezone=True), nullable=True)
    offboarded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    payroll_entries = db.relationship('Payroll', backref='employee', lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'id_number', name='uq_employees_tenant_id_number'),
        db.CheckConstraint(
            "onboarding_status IN ('NONE', 'INVITE_PENDING', 'PASSWORD_RESET_REQUIRED', 'ACTIVE', 'DISABLED')",
            name='ck_employees_onboarding_status_valid',
        ),
        db.CheckConstraint(
            "offboarding_reason IS NULL OR offboarding_reason IN "
            "('RESIGNED', 'CONTRACT_ENDED', 'DISMISSED', 'REDUNDANCY', 'RETIRED', 'DECEASED', 'OTHER')",
            name='ck_employees_offboarding_reason_valid',
        ),
    )


class LoanMovementKind:
    ADVANCE = 'ADVANCE'
    REPAYMENT = 'REPAYMENT'
    PAYROLL_DEDUCTION = 'PAYROLL_DEDUCTION'

    ALL = {ADVANCE, REPAYMENT, PAYROLL_DEDUCTION}


class EmployeeLoanMovement(db.Model):
    """Append-only history of an employee's advance balance."""
    __tablename__ = 'employee_loan_movements'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    balance_after = db.Column(db.Numeric(12, 2), nullable=False)
    occurred_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=True)
    payroll_run_id = db.Column(db.Integer, db.ForeignKey('payroll_runs.id'), nullable=True, index=True)
    ledger_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    payroll_run = db.relationship('PayrollRun', lazy=True)

    __table_args__ = (
        db.CheckConstraint("kind IN ('ADVANCE', 'REPAYMENT', 'PAYROLL_DEDUCTION')", name='ck_employee_loan_movements_kind_valid'),
        db.CheckConstraint('amount > 0', name='ck_employee_loan_movements_amount_positive'),
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


# Statutory amounts stored on a payroll line.
STATUTORY_FIELDS = (
    'taxable_pay', 'paye', 'nssf_employee', 'nssf_employer',
    'shif', 'housing_levy_employee', 'housing_levy_employer',
)
# Deducted from the employee's pay; the employer amounts are paid on top.
EMPLOYEE_STATUTORY_FIELDS = ('paye', 'nssf_employee', 'shif', 'housing_levy_employee')
EMPLOYER_STATUTORY_FIELDS = ('nssf_employer', 'housing_levy_employer')


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
    # Days paid when the employee left during the period; NULL means the full period.
    days_paid = db.Column(db.Integer, nullable=True)
    taxable_pay = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    paye = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    nssf_employee = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    nssf_employer = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    shif = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    housing_levy_employee = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    housing_levy_employer = db.Column(db.Numeric(12, 2), nullable=False, default=0, server_default='0')
    statutory_rates_version = db.Column(db.String(20), nullable=True)
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
