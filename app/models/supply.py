from __future__ import annotations
from datetime import datetime

from app import db

class ItemCategory:
    FEED = "Feed"
    SUPPLEMENT = "Supplement"
    EQUIPMENT = "Equipment"
    MEDICINE = "Medicine"

class InventoryItem(db.Model):
    """Master inventory record for stocked goods."""
    __tablename__ = 'inventory_items'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    current_qty = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    minimum_threshold = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    transactions = db.relationship(
        'InventoryTransaction',
        backref=db.backref('item', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='uq_inventory_items_tenant_name'),
    )

    def __init__(self, **kwargs):
        if 'unit_of_measure' in kwargs and 'unit' not in kwargs:
            kwargs['unit'] = kwargs.pop('unit_of_measure')
        if 'current_stock' in kwargs and 'current_qty' not in kwargs:
            kwargs['current_qty'] = kwargs.pop('current_stock')
        if 'min_threshold' in kwargs and 'minimum_threshold' not in kwargs:
            kwargs['minimum_threshold'] = kwargs.pop('min_threshold')
        kwargs.pop('unit_cost', None)
        super().__init__(**kwargs)

    @property
    def unit_of_measure(self):
        return self.unit

    @unit_of_measure.setter
    def unit_of_measure(self, value):
        self.unit = value

    @property
    def current_stock(self):
        return self.current_qty

    @current_stock.setter
    def current_stock(self, value):
        self.current_qty = value

    @property
    def min_threshold(self):
        return self.minimum_threshold

    @min_threshold.setter
    def min_threshold(self, value):
        self.minimum_threshold = value

    @property
    def requisitions(self):
        return self.transactions


class InventoryTransaction(db.Model):
    """Append-only ledger for stock movement."""
    __tablename__ = 'inventory_transactions'

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id'), nullable=False, index=True)
    transaction_type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    reference_note = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    transaction_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    __table_args__ = (
        db.CheckConstraint("transaction_type IN ('IN', 'OUT')", name='ck_inventory_transactions_type_valid'),
    )

    def __init__(self, **kwargs):
        if 'amount_used' in kwargs and 'quantity' not in kwargs:
            kwargs['quantity'] = kwargs.pop('amount_used')
        if 'timestamp' in kwargs and 'transaction_date' not in kwargs:
            kwargs['transaction_date'] = kwargs.pop('timestamp')
        if 'notes' in kwargs and 'reference_note' not in kwargs:
            kwargs['reference_note'] = kwargs.pop('notes')
        kwargs.pop('target_cow_id', None)
        super().__init__(**kwargs)

    @property
    def amount_used(self):
        return self.quantity

    @amount_used.setter
    def amount_used(self, value):
        self.quantity = value

    @property
    def timestamp(self):
        return self.transaction_date

    @timestamp.setter
    def timestamp(self, value):
        self.transaction_date = value

    @property
    def notes(self):
        return self.reference_note

    @notes.setter
    def notes(self, value):
        self.reference_note = value


# Backwards-compatible aliases while the codebase migrates off the old names.
StoreItem = InventoryItem
FeedRequisition = InventoryTransaction

class MilkSession:
    MORNING = "Morning"
    EVENING = "Evening"

class MilkLog(db.Model):
    """Tracks daily yield and flags anomalies or hardlocked milk."""
    __tablename__ = 'milk_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    amount_liters = db.Column(db.Numeric(10, 2), nullable=False)
    session = db.Column(db.String(20), nullable=False) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    butterfat_pct = db.Column(db.Numeric(5, 2), nullable=True)
    
    # Critical Commercial Flags
    is_saleable = db.Column(db.Boolean, default=True, nullable=False) 
    anomaly_flag = db.Column(db.Boolean, default=False, nullable=False) # True if yield dropped > 15%