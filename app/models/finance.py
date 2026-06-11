from app import db
from datetime import datetime, timezone

class TransactionType:
    REVENUE = "Revenue"
    EXPENSE = "Expense"

class TransactionCategory:
    MILK_SALE = "Milk Sale"
    FEED_PURCHASE = "Feed Purchase"
    VET_FEES = "Veterinary Fees"
    LABOR = "Labor"
    MAINTENANCE = "Maintenance"


class PaymentStatus:
    PAID = "PAID"
    UNPAID = "UNPAID"

class Customer(db.Model):
    """Tracks milk subscribers and their M-Pesa balances."""
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone_number = db.Column(db.String(15), unique=True, nullable=False, index=True) # Safaricom format: 2547XXXXXXXX
    account_balance = db.Column(db.Numeric(10, 2), default=0, nullable=False)
    daily_contract_liters = db.Column(db.Numeric(10, 2), default=0) # For subscription allocation
    is_active = db.Column(db.Boolean, default=True)

    transactions = db.relationship('Transaction', backref='customer', lazy=True)

class Transaction(db.Model):
    """The core double-entry ledger for all financial movements."""
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    transaction_type = db.Column(db.String(20), nullable=False) # Revenue or Expense
    category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    
    # M-Pesa tracking
    reference_code = db.Column(db.String(50), unique=True, nullable=True, index=True) 
    
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    description = db.Column(db.String(255), nullable=True)

    # Optional Foreign Keys for granular auditing
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)


class Buyer(db.Model):
    """Represents a milk buyer for tenant-scoped sales tracking."""
    __tablename__ = 'buyers'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    agreed_rate_per_liter = db.Column(db.Numeric(10, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    sales = db.relationship('SalesLedger', backref=db.backref('buyer', lazy=True), lazy=True, cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='uq_buyers_tenant_name'),
    )


class SalesLedger(db.Model):
    """Logs milk sales to buyers and payment status."""
    __tablename__ = 'sales_ledger'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('buyers.id', ondelete='RESTRICT'), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date(), index=True)
    liters_sold = db.Column(db.Numeric(10, 2), nullable=False)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False)
    payment_status = db.Column(db.String(10), nullable=False, default=PaymentStatus.UNPAID)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.CheckConstraint("payment_status IN ('PAID', 'UNPAID')", name='ck_sales_ledger_payment_status_valid'),
        db.UniqueConstraint('tenant_id', 'buyer_id', 'date', name='uq_sales_ledger_tenant_buyer_date'),
    )