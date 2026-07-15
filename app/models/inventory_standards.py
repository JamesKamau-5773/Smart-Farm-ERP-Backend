from __future__ import annotations

from datetime import datetime, timezone

from app import db


class IngredientStandard(db.Model):
    __tablename__ = 'ingredient_standards'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    canonical_name = db.Column(db.String(120), nullable=False)

    protein_grams_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    energy_mj_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    fiber_grams_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    cost_per_kg = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    source_reference = db.Column(db.String(255), nullable=True)
    standards_version = db.Column(db.String(40), nullable=False, default='2026.07')
    effective_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'canonical_name', 'standards_version', name='uq_ing_std_tenant_name_version'),
        db.Index('ix_ing_std_tenant_name', 'tenant_id', 'canonical_name'),
    )


class IngredientStandardSynonym(db.Model):
    __tablename__ = 'ingredient_standard_synonyms'

    id = db.Column(db.Integer, primary_key=True)
    standard_id = db.Column(db.Integer, db.ForeignKey('ingredient_standards.id', ondelete='CASCADE'), nullable=False, index=True)
    synonym = db.Column(db.String(120), nullable=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    standard = db.relationship('IngredientStandard', backref=db.backref('synonyms', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('standard_id', 'synonym', name='uq_ing_std_synonym_per_standard'),
        db.Index('ix_ing_std_synonym_lookup', 'synonym'),
    )


class IngredientCategoryBaseline(db.Model):
    __tablename__ = 'ingredient_category_baselines'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    category = db.Column(db.String(80), nullable=False)

    protein_grams_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    energy_mj_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    fiber_grams_per_kg = db.Column(db.Numeric(10, 2), nullable=False)
    cost_per_kg = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    source_reference = db.Column(db.String(255), nullable=True)
    standards_version = db.Column(db.String(40), nullable=False, default='2026.07')
    effective_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'category', 'standards_version', name='uq_ing_baseline_tenant_category_version'),
        db.Index('ix_ing_baseline_tenant_category', 'tenant_id', 'category'),
    )


class IngredientStandardSyncJob(db.Model):
    __tablename__ = 'ingredient_standard_sync_jobs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=True, index=True)
    source = db.Column(db.String(120), nullable=False)
    status = db.Column(db.String(30), nullable=False, default='PENDING')
    started_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finished_at = db.Column(db.DateTime(timezone=True), nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
