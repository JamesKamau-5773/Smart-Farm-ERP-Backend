import enum
from datetime import datetime, timezone

from sqlalchemy import event, inspect
from sqlalchemy.orm import object_session

from app import db


class TransactionType(str, enum.Enum):
    DEBIT = 'Debit'
    CREDIT = 'Credit'
    PAYMENT = 'Payment'
    EXPENSE = 'Expense'
    REVENUE = 'Revenue'


class TransactionCategory(str, enum.Enum):
    MILK_SALE = 'Milk Sale'
    LIVESTOCK_SALE = 'Livestock Sale'
    OTHER_INCOME = 'Other Income'
    PAYMENT = 'Payment'
    INVENTORY_WRITE_OFF = 'Inventory Write Off'
    OTHER = 'Other'
    FEED_PURCHASE = 'Feed Purchase'
    VET_FEES = 'Vet Fees'
    LABOR_WAGES = 'Labor / Wages'
    UTILITIES = 'Utilities'
    EQUIPMENT_MAINTENANCE = 'Equipment Maintenance'
    TRANSPORT = 'Transport'
    OPENING_BALANCE = 'Opening Balance'
    BUYER_PAYMENT = 'Buyer Payment'


class PaymentStatus(str, enum.Enum):
    UNPAID = 'UNPAID'
    PARTIALLY_PAID = 'PARTIALLY_PAID'
    PAID = 'PAID'


class TransactionStatus(str, enum.Enum):
    DRAFT = 'DRAFT'
    POSTED = 'POSTED'
    VOIDED = 'VOIDED'


class CostClass(str, enum.Enum):
    COGS = 'COGS'
    CUSTOMER_ACQUISITION = 'CUSTOMER_ACQUISITION'
    OPERATING = 'OPERATING'
    CAPITAL = 'CAPITAL'


class AnimalCostType(str, enum.Enum):
    PURCHASE = 'PURCHASE'
    CALF_FEED = 'CALF_FEED'
    HEIFER_FEED = 'HEIFER_FEED'
    BREEDING = 'BREEDING'
    VETERINARY = 'VETERINARY'
    LABOR = 'LABOR'
    HOUSING = 'HOUSING'
    OVERHEAD = 'OVERHEAD'
    OTHER = 'OTHER'


class ReceiptStatus(str, enum.Enum):
    ISSUED = 'ISSUED'
    VOIDED = 'VOIDED'


class Buyer(db.Model):
    __tablename__ = 'buyers'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    contact_person = db.Column(db.String(120))
    phone_number = db.Column(db.String(20), nullable=True)
    email = db.Column(db.String(120))
    whatsapp = db.Column(db.String(20), nullable=True)
    buyer_type = db.Column(db.String(50), nullable=False, default='Individual')
    farm_id = db.Column(db.Integer, nullable=True, index=True)
    agreed_rate_per_liter = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=True)
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=True)

    sales = db.relationship('SalesLedger', backref='buyer', lazy=True, cascade='all, delete-orphan')
    audit_logs = db.relationship('BuyerAuditLog', backref='buyer', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('tenant_id', 'name', name='_tenant_buyer_name_uc'),)


class BuyerAuditLog(db.Model):
    __tablename__ = 'buyer_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id'), nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False)
    previous_values = db.Column(db.JSON, nullable=True)
    new_values = db.Column(db.JSON, nullable=True)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    daily_contract_liters = db.Column(db.Numeric(10, 2), default=0.0)
    agreed_rate_per_liter = db.Column(db.Numeric(10, 2), default=0.0)
    account_balance = db.Column(db.Numeric(10, 2), default=0.0, nullable=False)
    status = db.Column(db.String(20), default='Active', nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    deliveries = db.relationship('Delivery', backref='customer', lazy=True, cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='customer', lazy=True, cascade='all, delete-orphan')

    __table_args__ = (db.UniqueConstraint('tenant_id', 'phone_number', name='_tenant_phone_uc'),)


class Delivery(db.Model):
    __tablename__ = 'deliveries'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    liters_delivered = db.Column(db.Numeric(10, 2), nullable=False)
    personal_consumption_liters = db.Column(db.Numeric(10, 2), default=0.0)
    billable_liters = db.Column(db.Numeric(10, 2), nullable=False)
    price_per_liter = db.Column(db.Numeric(10, 2), nullable=False)
    total_price = db.Column(db.Numeric(10, 2), nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint(
            'billable_liters = 0 OR price_per_liter > 0',
            name='ck_deliveries_billable_price_positive',
        ),
        db.CheckConstraint(
            'total_price = billable_liters * price_per_liter',
            name='ck_deliveries_total_matches_snapshot',
        ),
    )


class SalesLedger(db.Model):
    __tablename__ = 'sales_ledger'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    liters_sold = db.Column(db.Numeric(10, 2), nullable=False)
    price_per_liter = db.Column(db.Numeric(10, 2), nullable=False, default=0.0)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    amount_paid = db.Column(db.Numeric(12, 2), nullable=False, default=0.0)
    payment_status = db.Column(db.String(20), default=PaymentStatus.UNPAID, nullable=False)
    shift = db.Column(db.String(20), nullable=True, default='Morning')
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'buyer_id', 'date', name='uq_sales_ledger_tenant_buyer_date'),
        db.CheckConstraint("payment_status IN ('PAID', 'UNPAID', 'PARTIALLY_PAID')", name='ck_sales_ledger_payment_status_valid'),
    )


class PaymentAllocation(db.Model):
    __tablename__ = 'payment_allocations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=False, index=True)
    sales_ledger_id = db.Column(db.Integer, db.ForeignKey('sales_ledger.id'), nullable=False, index=True)
    amount_applied = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farms.id'), nullable=True, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id'), nullable=True, index=True)
    transaction_type = db.Column(db.Enum(TransactionType, native_enum=False), nullable=False)
    category = db.Column(db.Enum(TransactionCategory, native_enum=False), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    item_name = db.Column(db.String(120), nullable=True)
    quantity = db.Column(db.Numeric(14, 3), nullable=True)
    cost_class = db.Column(db.Enum(CostClass, native_enum=False), nullable=True)
    description = db.Column(db.String(255))
    counterparty_name = db.Column(db.String(120))
    payment_method = db.Column(db.String(30))
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reference_code = db.Column(db.String(100), index=True)
    status = db.Column(db.String(20), nullable=False, default=TransactionStatus.POSTED.value)
    posted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    posted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    voided_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    void_reason = db.Column(db.String(255), nullable=True)
    corrected_from_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey('transactions.id', ondelete='RESTRICT'),
        nullable=True,
        unique=True,
        index=True,
    )

    payment_allocations = db.relationship('PaymentAllocation', backref='transaction', lazy=True, cascade='all, delete-orphan')
    correction_source = db.relationship(
        'Transaction',
        remote_side=[id],
        backref=db.backref('correction_replacement', uselist=False),
        foreign_keys=[corrected_from_transaction_id],
    )
    animal_cost_allocation = db.relationship(
        'AnimalCostAllocation',
        back_populates='transaction',
        uselist=False,
        cascade='all, delete-orphan',
    )
    receipt = db.relationship('Receipt', back_populates='transaction', uselist=False, lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'reference_code', name='uq_transactions_tenant_reference_code'),
        db.CheckConstraint(
            "(transaction_type = 'PAYMENT') = (category IN ('PAYMENT', 'BUYER_PAYMENT'))",
            name='ck_transactions_payment_classification',
        ),
    )


class TransactionAuditLog(db.Model):
    """Append-only audit trail for ledger state transitions."""
    __tablename__ = 'transaction_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id', ondelete='RESTRICT'), nullable=False, index=True)
    action = db.Column(db.String(30), nullable=False)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


@event.listens_for(TransactionAuditLog, 'before_update')
@event.listens_for(TransactionAuditLog, 'before_delete')
def prevent_transaction_audit_mutation(mapper, connection, target):
    raise ValueError('Transaction audit records are append-only.')


class AnimalCostAllocation(db.Model):
    """An animal-attributable cost backed by one posted ledger transaction."""
    __tablename__ = 'animal_cost_allocations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id', ondelete='RESTRICT'), nullable=False, unique=True)
    cost_type = db.Column(db.Enum(AnimalCostType, native_enum=False), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    occurred_on = db.Column(db.Date, nullable=False)
    attribution_method = db.Column(db.String(20), nullable=False, default='DIRECT')
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    transaction = db.relationship('Transaction', back_populates='animal_cost_allocation')
    cow = db.relationship('Cow', lazy=True)

    __table_args__ = (
        db.CheckConstraint('amount > 0', name='ck_animal_cost_allocations_amount_positive'),
        db.CheckConstraint("attribution_method IN ('DIRECT', 'ALLOCATED')", name='ck_animal_cost_allocations_attribution_method_valid'),
        db.Index('ix_animal_cost_allocations_tenant_cow_date', 'tenant_id', 'cow_id', 'occurred_on'),
    )


class Receipt(db.Model):
    __tablename__ = 'receipts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey('farms.id', ondelete='RESTRICT'), nullable=True, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id', ondelete='RESTRICT'), nullable=False, unique=True)
    receipt_number = db.Column(db.String(30), nullable=False)
    snapshot = db.Column(db.JSON, nullable=False)
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    issued_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=ReceiptStatus.ISSUED.value)
    currency = db.Column(db.String(3), nullable=False, default='KES')
    template_version = db.Column(db.String(20), nullable=False, default='1')
    document_sha256 = db.Column(db.String(64), nullable=True)
    document_content = db.Column(db.LargeBinary, nullable=True)
    voided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    voided_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    void_reason = db.Column(db.String(255), nullable=True)

    transaction = db.relationship('Transaction', back_populates='receipt')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'receipt_number', name='uq_receipts_tenant_number'),
        db.UniqueConstraint('tenant_id', 'id', name='uq_receipts_tenant_id'),
    )


@event.listens_for(Receipt, 'before_update')
def prevent_receipt_update(mapper, connection, target):
    state = inspect(target)
    mutable_on_void = {'status', 'voided_at', 'voided_by', 'void_reason'}
    changed = {attribute.key for attribute in state.attrs if attribute.history.has_changes()}
    artifact_fields = {'document_content', 'document_sha256', 'template_version'}
    session = object_session(target)
    previous_template_versions = state.attrs.template_version.history.deleted
    if (
        session is not None
        and session.info.get('allow_receipt_document_restyle')
        and changed
        and changed <= artifact_fields
        and previous_template_versions
        and str(target.template_version) > str(previous_template_versions[0])
    ):
        return
    if changed and changed <= artifact_fields:
        previous_document = state.attrs.document_content.history.deleted
        if previous_document and previous_document[0] is None and target.document_content and target.document_sha256:
            return
    if changed - mutable_on_void:
        raise ValueError('Issued receipt identity, snapshot, and artifact are immutable.')
    previous = state.attrs.status.history.deleted
    if (
        not state.attrs.status.history.has_changes()
        or not previous
        or previous[0] != ReceiptStatus.ISSUED.value
        or target.status != ReceiptStatus.VOIDED.value
        or not target.voided_at
        or not target.voided_by
        or not str(target.void_reason or '').strip()
    ):
        raise ValueError('Only the complete ISSUED to VOIDED receipt transition is allowed.')


@event.listens_for(Receipt, 'before_delete')
def prevent_receipt_delete(mapper, connection, target):
    raise ValueError('Issued receipts cannot be deleted.')


class ReceiptNumberSequence(db.Model):
    __tablename__ = 'receipt_number_sequences'

    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='RESTRICT'), primary_key=True)
    fiscal_year = db.Column(db.Integer, primary_key=True)
    next_number = db.Column(db.Integer, nullable=False, default=1)


class ReceiptAuditLog(db.Model):
    __tablename__ = 'receipt_audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False, index=True)
    receipt_id = db.Column(db.Integer, db.ForeignKey('receipts.id', ondelete='RESTRICT'), nullable=False, index=True)
    action = db.Column(db.String(30), nullable=False)
    performed_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


@event.listens_for(ReceiptAuditLog, 'before_update')
@event.listens_for(ReceiptAuditLog, 'before_delete')
def prevent_receipt_audit_mutation(mapper, connection, target):
    raise ValueError('Receipt audit records are append-only.')


__all__ = [
    'Buyer',
    'BuyerAuditLog',
    'Customer',
    'Delivery',
    'PaymentAllocation',
    'PaymentStatus',
    'Receipt',
    'ReceiptAuditLog',
    'ReceiptNumberSequence',
    'ReceiptStatus',
    'SalesLedger',
    'Transaction',
    'TransactionAuditLog',
    'TransactionCategory',
    'TransactionType',
    'TransactionStatus',
]
