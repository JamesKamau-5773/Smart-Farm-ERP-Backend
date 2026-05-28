from __future__ import annotations
from datetime import datetime, timezone

from app import db
from sqlalchemy import Computed

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
    energy_mj_per_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    protein_grams_per_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    fiber_grams_per_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    cost_per_kg = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

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
    unit_cost = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    total_transaction_value = db.Column(
        db.Numeric(12, 2),
        Computed('quantity * unit_cost', persisted=True),
        nullable=False,
    )
    inventory_batch_id = db.Column(db.Integer, db.ForeignKey('inventory_batches.id'), nullable=True, index=True)
    reference_note = db.Column(db.Text, nullable=True)
    logged_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    transaction_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

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


class InventoryBatch(db.Model):
    __tablename__ = 'inventory_batches'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False, index=True)
    supplier_name = db.Column(db.String(100), nullable=False)
    received_quantity_kg = db.Column(db.Numeric(10, 2), nullable=False)
    cost_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    quality_rating = db.Column(db.String(20), nullable=True)
    actual_protein_percentage = db.Column(db.Numeric(5, 2), nullable=False)
    received_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())

    transactions = db.relationship(
        'InventoryTransaction',
        backref=db.backref('inventory_batch', lazy=True),
        lazy=True,
    )

    __table_args__ = (
        db.CheckConstraint("quality_rating IN ('Excellent', 'Standard', 'Poor')", name='ck_inventory_batches_quality_rating_valid'),
        db.UniqueConstraint('tenant_id', 'item_id', 'supplier_name', 'received_date', name='uq_tenant_item_supplier_date'),
    )


class ExpenseLedger(db.Model):
    __tablename__ = 'expense_ledger'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    expense_date = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())


class FeedRecipe(db.Model):
    __tablename__ = 'feed_recipes'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    recipe_name = db.Column(db.String(100), nullable=False)
    target_protein_percentage = db.Column(db.Numeric(5, 2), nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    ingredients = db.relationship(
        'RecipeIngredient',
        backref=db.backref('recipe', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )


class RecipeIngredient(db.Model):
    __tablename__ = 'recipe_ingredients'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('feed_recipes.id', ondelete='CASCADE'), nullable=False, index=True)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False, index=True)
    inclusion_percentage = db.Column(db.Numeric(5, 2), nullable=False)

    inventory_item = db.relationship('InventoryItem', backref=db.backref('recipe_ingredients', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('recipe_id', 'inventory_item_id', name='uq_recipe_ingredient'),
    )


class FarmMeasurementUnit(db.Model):
    __tablename__ = 'farm_measurement_units'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey('inventory_items.id', ondelete='RESTRICT'), nullable=False, index=True)
    unit_name = db.Column(db.String(50), nullable=False)
    kg_equivalent = db.Column(db.Numeric(5, 2), nullable=False)

    inventory_item = db.relationship('InventoryItem', backref=db.backref('measurement_units', lazy=True))

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'item_id', 'unit_name', name='uq_tenant_item_unit'),
    )


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
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    amount_liters = db.Column(db.Numeric(10, 2), nullable=False)
    session = db.Column(db.String(20), nullable=False) 
    timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    recorded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    butterfat_pct = db.Column(db.Numeric(5, 2), nullable=True)
    
    # Critical Commercial Flags
    is_saleable = db.Column(db.Boolean, default=True, nullable=False) 
    anomaly_flag = db.Column(db.Boolean, default=False, nullable=False) # True if yield dropped > 15%