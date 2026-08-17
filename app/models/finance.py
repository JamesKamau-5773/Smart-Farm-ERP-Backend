import enum
from datetime import datetime, timezone
from app import db


class TransactionType(str, enum.Enum):
    DEBIT = 'DEBIT'
    CREDIT = 'CREDIT'
    EXPENSE = 'EXPENSE'
    REVENUE = 'REVENUE'


class TransactionCategory(str, enum.Enum):
    MILK_SALE = 'MILK_SALE'
    PAYMENT = 'PAYMENT'
    INVENTORY_WRITE_OFF = 'INVENTORY_WRITE_OFF'
    OTHER = 'OTHER'


class Buyer(db.Model):
    __tablename__ = 'buyers'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    contact_person = db.Column(db.String(120))
    phone_number = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    sales = db.relationship('SalesLedger', backref='buyer', lazy=True, cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint('tenant_id', 'name', name='_tenant_buyer_name_uc'),)


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

    deliveries = db.relationship('Delivery', backref='customer', lazy=True, cascade="all, delete-orphan")
    transactions = db.relationship('Transaction', backref='customer', lazy=True, cascade="all, delete-orphan")

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


class SalesLedger(db.Model):
    __tablename__ = 'sales_ledger'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    liters_sold = db.Column(db.Numeric(10, 2), nullable=False)
    price_per_liter = db.Column(db.Numeric(10, 2), nullable=False)
    total_amount = db.Column(db.Numeric(12, 2), nullable=False)
    payment_status = db.Column(db.String(20), default='Unpaid', nullable=False) # e.g., Unpaid, Paid
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True, index=True)
    transaction_type = db.Column(db.Enum(TransactionType, native_enum=False), nullable=False)
    category = db.Column(db.Enum(TransactionCategory, native_enum=False), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    description = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    reference_code = db.Column(db.String(100), index=True)