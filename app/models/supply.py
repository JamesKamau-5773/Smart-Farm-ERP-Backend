from __future__ import annotations
from datetime import datetime, timezone

from app import db
from sqlalchemy import Computed, ForeignKeyConstraint, event, inspect

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
    sku = db.Column(db.String(80), nullable=True)
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
        db.UniqueConstraint('tenant_id', 'sku', name='uq_inventory_items_tenant_sku'),
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


class Ingredient(db.Model):
    """Catalog of feed ingredients used by formulation templates and batches."""
    __tablename__ = 'ingredients'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    current_cost_per_kg = db.Column(db.Numeric(14, 4), nullable=False)
    stock_quantity = db.Column(db.Numeric(14, 3), nullable=False, default=0)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='uq_ingredients_tenant_name'),
        db.UniqueConstraint('tenant_id', 'id', name='uq_ingredients_tenant_id'),
        db.CheckConstraint('current_cost_per_kg >= 0', name='ck_ingredients_current_cost_non_negative'),
        db.CheckConstraint('stock_quantity >= 0', name='ck_ingredients_stock_quantity_non_negative'),
        db.Index('ix_ingredients_tenant_name', 'tenant_id', 'name'),
    )


class FeedFormula(db.Model):
    """Reusable feed formulation template created per tenant."""
    __tablename__ = 'feed_formulas'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    ingredients = db.relationship(
        'FormulaIngredient',
        backref=db.backref('formula', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'name', name='uq_feed_formulas_tenant_name'),
        db.UniqueConstraint('tenant_id', 'id', name='uq_feed_formulas_tenant_id'),
        db.Index('ix_feed_formulas_tenant_created_at', 'tenant_id', 'created_at'),
    )


class FormulaIngredient(db.Model):
    """Tenant-safe recipe mapping between formulas and ingredients."""
    __tablename__ = 'formula_ingredients'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    formula_id = db.Column(db.Integer, nullable=False, index=True)
    ingredient_id = db.Column(db.Integer, nullable=False, index=True)
    default_weight = db.Column(db.Numeric(14, 3), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    ingredient = db.relationship(
        'Ingredient',
        primaryjoin='and_(FormulaIngredient.tenant_id == Ingredient.tenant_id, FormulaIngredient.ingredient_id == Ingredient.id)',
        foreign_keys='[FormulaIngredient.tenant_id, FormulaIngredient.ingredient_id]',
        overlaps='formula,ingredients',
        lazy=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ['tenant_id', 'formula_id'],
            ['feed_formulas.tenant_id', 'feed_formulas.id'],
            ondelete='CASCADE',
            name='fk_formula_ingredients_formula_tenant',
        ),
        ForeignKeyConstraint(
            ['tenant_id', 'ingredient_id'],
            ['ingredients.tenant_id', 'ingredients.id'],
            ondelete='RESTRICT',
            name='fk_formula_ingredients_ingredient_tenant',
        ),
        db.UniqueConstraint('tenant_id', 'formula_id', 'ingredient_id', name='uq_formula_ingredients_formula_ingredient'),
        db.CheckConstraint('default_weight > 0', name='ck_formula_ingredients_default_weight_positive'),
        db.Index('ix_formula_ingredients_tenant_formula', 'tenant_id', 'formula_id'),
    )


class FeedBatch(db.Model):
    """Immutable financial snapshot of a mixed physical batch."""
    __tablename__ = 'feed_batches'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    formula_id = db.Column(db.Integer, nullable=True, index=True)
    batch_name = db.Column(db.String(255), nullable=False)
    total_weight = db.Column(db.Numeric(14, 3), nullable=False)
    total_cost = db.Column(db.Numeric(14, 4), nullable=False)
    cost_per_kg = db.Column(db.Numeric(14, 4), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='ACTIVE')
    mixed_on = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    depleted_on = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    posted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    ingredients = db.relationship(
        'BatchIngredient',
        backref=db.backref('batch', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )
    consumption_events = db.relationship(
        'FeedBatchConsumptionEvent',
        backref=db.backref('batch', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ['tenant_id', 'formula_id'],
            ['feed_formulas.tenant_id', 'feed_formulas.id'],
            ondelete='RESTRICT',
            name='fk_feed_batches_formula_tenant',
        ),
        db.UniqueConstraint('tenant_id', 'id', name='uq_feed_batches_tenant_id'),
        db.CheckConstraint("status IN ('ACTIVE', 'DEPLETED', 'VOIDED')", name='ck_feed_batches_status_valid'),
        db.CheckConstraint('total_weight > 0', name='ck_feed_batches_total_weight_positive'),
        db.CheckConstraint('total_cost >= 0', name='ck_feed_batches_total_cost_non_negative'),
        db.CheckConstraint('cost_per_kg >= 0', name='ck_feed_batches_cost_per_kg_non_negative'),
        db.CheckConstraint('depleted_on IS NULL OR depleted_on >= mixed_on', name='ck_feed_batches_depleted_after_mixed'),
        db.Index('ix_feed_batches_tenant_status_mixed_on', 'tenant_id', 'status', 'mixed_on'),
    )


class BatchIngredient(db.Model):
    """Composition snapshot with locked ingredient cost for historical ROI analytics."""
    __tablename__ = 'batch_ingredients'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    batch_id = db.Column(db.Integer, nullable=False, index=True)
    ingredient_id = db.Column(db.Integer, nullable=False, index=True)
    weight = db.Column(db.Numeric(14, 3), nullable=False)
    percentage = db.Column(db.Numeric(5, 2), nullable=False)
    locked_cost_per_kg = db.Column(db.Numeric(14, 4), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    ingredient = db.relationship(
        'Ingredient',
        primaryjoin='and_(BatchIngredient.tenant_id == Ingredient.tenant_id, BatchIngredient.ingredient_id == Ingredient.id)',
        foreign_keys='[BatchIngredient.tenant_id, BatchIngredient.ingredient_id]',
        overlaps='batch,ingredients',
        lazy=True,
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ['tenant_id', 'batch_id'],
            ['feed_batches.tenant_id', 'feed_batches.id'],
            ondelete='CASCADE',
            name='fk_batch_ingredients_batch_tenant',
        ),
        ForeignKeyConstraint(
            ['tenant_id', 'ingredient_id'],
            ['ingredients.tenant_id', 'ingredients.id'],
            ondelete='RESTRICT',
            name='fk_batch_ingredients_ingredient_tenant',
        ),
        db.UniqueConstraint('tenant_id', 'batch_id', 'ingredient_id', name='uq_batch_ingredients_batch_ingredient'),
        db.CheckConstraint('weight > 0', name='ck_batch_ingredients_weight_positive'),
        db.CheckConstraint('percentage > 0 AND percentage <= 100', name='ck_batch_ingredients_percentage_range'),
        db.CheckConstraint('locked_cost_per_kg >= 0', name='ck_batch_ingredients_locked_cost_non_negative'),
    )


class FeedBatchConsumptionEvent(db.Model):
    """Consumption events used to deplete batches based on actual usage."""
    __tablename__ = 'feed_batch_consumption_events'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    batch_id = db.Column(db.Integer, nullable=False, index=True)
    consumed_weight = db.Column(db.Numeric(14, 3), nullable=False)
    consumed_on = db.Column(db.Date, nullable=False, default=lambda: datetime.now(timezone.utc).date())
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ['tenant_id', 'batch_id'],
            ['feed_batches.tenant_id', 'feed_batches.id'],
            ondelete='CASCADE',
            name='fk_feed_batch_consumption_events_batch_tenant',
        ),
        db.CheckConstraint('consumed_weight > 0', name='ck_feed_batch_consumption_events_weight_positive'),
        db.Index('ix_feed_batch_consumption_events_tenant_batch_date', 'tenant_id', 'batch_id', 'consumed_on'),
    )


@event.listens_for(FeedBatch, 'before_update')
def prevent_posted_batch_financial_mutation(mapper, connection, target):
    """Allow lifecycle updates, but freeze financial snapshot fields once posted."""
    if target.posted_at is None:
        return

    state = inspect(target)
    immutable_fields = {
        'tenant_id',
        'formula_id',
        'batch_name',
        'total_weight',
        'total_cost',
        'cost_per_kg',
        'mixed_on',
        'created_by',
        'created_at',
    }
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError('Posted feed batch financial snapshot is immutable.')


@event.listens_for(BatchIngredient, 'before_update')
def prevent_batch_ingredient_mutation(mapper, connection, target):
    """Batch composition rows are immutable once inserted."""
    state = inspect(target)
    immutable_fields = {
        'tenant_id',
        'batch_id',
        'ingredient_id',
        'weight',
        'percentage',
        'locked_cost_per_kg',
        'created_at',
    }
    if any(state.attrs[field].history.has_changes() for field in immutable_fields):
        raise ValueError('Batch ingredient snapshots are immutable.')


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
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    verified_at = db.Column(db.DateTime(timezone=True), nullable=True)


class MilkDropAlert(db.Model):
    """Manager review queue for low-milk events."""
    __tablename__ = 'milk_drop_alerts'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False, index=True)
    alert_date = db.Column(db.Date, nullable=False)
    missing_milk_liters = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='OPEN')
    reason = db.Column(db.Text, nullable=False)
    investigation_notes = db.Column(db.Text, nullable=True)
    selected_reasons = db.Column(db.JSON, nullable=True)
    investigated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    investigated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    __table_args__ = (
        db.CheckConstraint("status IN ('OPEN', 'INVESTIGATING', 'RESOLVED')", name='ck_milk_drop_alerts_status_valid'),
        db.Index('ix_milk_drop_alerts_tenant_status_date', 'tenant_id', 'status', 'alert_date'),
    )