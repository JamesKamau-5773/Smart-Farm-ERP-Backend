from app import db
from datetime import datetime

class TransactionType:
    REVENUE = "Revenue"
    EXPENSE = "Expense"

class TransactionCategory:
    MILK_SALE = "Milk Sale"
    FEED_PURCHASE = "Feed Purchase"
    VET_FEES = "Veterinary Fees"
    LABOR = "Labor"
    MAINTENANCE = "Maintenance"

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
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    description = db.Column(db.String(255), nullable=True)

    # Optional Foreign Keys for granular auditing
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)