from flask import current_app, g, has_app_context
from sqlalchemy import event
from sqlalchemy.ext.hybrid import hybrid_property

from app import db
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta

# --- Configuration Constants for Cow Status Derivation ---
CALF_AGE_THRESHOLD_MONTHS = 12
DRY_OFF_PERIOD_DAYS = 60
LACTATION_PERIOD_DAYS = 305

class BreedStatus:
    FOUNDATION = "Foundation"
    INTERMEDIATE = "Intermediate"
    APPENDIX = "Appendix"
    PEDIGREE = "Pedigree"

class CowStatus:
    CALF = "Calf"
    HEIFER = "Heifer"
    LACTATING = "Lactating"
    DRY = "Dry"

class Cow(db.Model):
    __tablename__ = 'cows'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    tag_number = db.Column(db.String(50), nullable=False, index=True)
    name = db.Column(db.String(100))
    breed_status = db.Column(db.String(50), default=BreedStatus.FOUNDATION, nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)

    # Genetic Tracking (Self-referential foreign key for lineage)
    dam_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=True)
    sire_name = db.Column(db.String(100), nullable=True)
    genetic_score = db.Column(db.Integer, nullable=True)
    birth_weight_kg = db.Column(db.Numeric(5, 2), nullable=True)
    photo_url = db.Column(db.String(255), nullable=True)

    # --- Fields for Status Derivation ---
    # This should be updated after each successful calving event.
    last_calving_date = db.Column(db.Date)
    # These fields are updated during pregnancy management.
    pregnancy_status = db.Column(db.String(50))  # e.g., 'Open', 'In-calf', 'Confirmed Pregnant'
    due_date = db.Column(db.Date)

    # Operational State
    is_hardlocked = db.Column(db.Boolean, default=False)
    # Defaults to Heifer (not Lactating) so newly registered animals that omit an
    # explicit status don't silently masquerade as milking cows in status-derived
    # views (herd counts, feeding-group planning) until someone reviews them.
    status = db.Column(db.String(50), default=CowStatus.HEIFER, nullable=False) # Renamed to 'status' to avoid conflict with derived property
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    lactation_cycles = db.relationship('LactationCycle', backref=db.backref('livestock', lazy=True), lazy=True, cascade='all, delete-orphan')
    medical_records = db.relationship('MedicalRecord', backref=db.backref('livestock', lazy=True), lazy=True, cascade='all, delete-orphan')
    breeding_logs = db.relationship('BreedingLog', backref=db.backref('livestock', lazy=True), lazy=True, cascade='all, delete-orphan')
    heat_observations = db.relationship('HeatObservation', backref=db.backref('livestock', lazy=True), lazy=True, cascade='all, delete-orphan')
    vet_visits = db.relationship('VetVisit', backref=db.backref('livestock', lazy=True), lazy=True, cascade='all, delete-orphan')
    timeline_events = db.relationship(
        'AnimalTimelineEvent',
        backref=db.backref('animal', lazy=True),
        lazy=True,
        cascade='all, delete-orphan',
    )
    yield_targets = db.relationship('AnimalYieldTarget', back_populates='cow', cascade='all, delete-orphan', lazy=True)

    genetic_profile = db.relationship(
        'GeneticProfile',
        back_populates='cow',
        uselist=False,
        cascade='all, delete-orphan'
    )

    __table_args__ = (
        # This partial unique index ensures that for any given tenant,
        # the tag_number is unique ONLY for active cows. This allows
        # tag numbers to be reused once a cow is soft-deleted (is_active=False).
        db.Index(
            'uq_cows_tenant_active_tag_number',
            'tenant_id', 'tag_number', unique=True, postgresql_where=db.text('is_active IS TRUE')
        ),
    )

    @hybrid_property
    def age_in_months(self):
        if not self.date_of_birth:
            return None
        today = date.today()
        delta = relativedelta(today, self.date_of_birth)
        return delta.years * 12 + delta.months

    @property
    def current_status(self):
        from app.services.cow_status_service import CowStatusService

        return CowStatusService.compute_current_status(self)

    @current_status.setter
    def current_status(self, value):
        self.status = value

    @property
    def last_calved(self):
        return self.last_calving_date

    @last_calved.setter
    def last_calved(self, value):
        self.last_calving_date = value

    @property
    def gender(self):
        return getattr(self, '_gender', 'Female')

    @gender.setter
    def gender(self, value):
        self._gender = value

def _resolve_default_tenant_id():
    if has_app_context():
        tenant_public_id = getattr(g, 'tenant_id', None)
        if tenant_public_id:
            try:
                from app.utils.jwt_payload import parse_public_int_id

                return parse_public_int_id(tenant_public_id, 'tenant_')
            except (TypeError, ValueError):
                pass

    from app.models.tenant import Tenant

    tenant = Tenant.query.order_by(Tenant.id.asc()).first()
    return tenant.id if tenant else None


@event.listens_for(Cow, 'before_insert')
def set_cow_tenant(mapper, connection, target):
    if target.tenant_id is None:
        target.tenant_id = _resolve_default_tenant_id()


class AnimalYieldTarget(db.Model):
    __tablename__ = 'animal_yield_targets'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    target_liters = db.Column(db.Numeric(5, 2), nullable=False)
    times_to_feed_daily = db.Column(db.Integer, default=2, nullable=False)
    base_herd_feed_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    milking_topup_kg = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    status = db.Column(db.String(20), default='Active', nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    cow = db.relationship('Cow', back_populates='yield_targets')

    __table_args__ = (
        db.CheckConstraint('times_to_feed_daily IN (2, 3, 4)', name='ck_animal_yield_targets_times_to_feed_daily_valid'),
    )


class SemenInventory(db.Model):
    __tablename__ = 'semen_inventory'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    bull_name = db.Column(db.String(100), nullable=False)
    straw_code = db.Column(db.String(50), nullable=False)
    breed = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(100), nullable=True)
    cost = db.Column(db.Numeric(10, 2), nullable=True)
    stock_level = db.Column(db.Integer, nullable=False, default=0)
    traits_to_improve = db.Column(db.JSON, nullable=True)

    breeding_logs = db.relationship('BreedingLog', backref=db.backref('semen', lazy=True), lazy=True)

    __table_args__ = (
        db.UniqueConstraint('tenant_id', 'straw_code', name='uq_semen_inventory_tenant_straw_code'),
    )


class BreedingLog(db.Model):
    __tablename__ = 'breeding_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False, index=True)
    inventory_semen_id = db.Column(db.Integer, db.ForeignKey('semen_inventory.id'), nullable=True, index=True)
    external_sire_code = db.Column(db.String(100), nullable=True)
    provided_by = db.Column(db.String(20), nullable=False, default='FARM')
    sire_pta_scores = db.Column(db.JSON, nullable=True)
    insemination_date = db.Column(db.Date, nullable=False)
    insemination_time = db.Column(db.Time, nullable=True)
    certificate_number = db.Column(db.String(50), nullable=True)
    technician_name = db.Column(db.String(120), nullable=True)
    owner_name = db.Column(db.String(120), nullable=True)
    farm_location = db.Column(db.String(150), nullable=True)
    service_fee = db.Column(db.Numeric(10, 2), nullable=True)
    is_repeat_service = db.Column(db.Boolean, nullable=False, default=False)
    certificate_image_url = db.Column(db.String(255), nullable=True)
    expected_calving_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Pending')

    __table_args__ = (
        db.CheckConstraint(
            "provided_by IN ('FARM', 'VET')",
            name='ck_breeding_logs_provided_by_valid'
        ),
        db.CheckConstraint(
            "status IN ('Pending', 'Pregnant', 'Failed', 'Calved')",
            name='ck_breeding_logs_status_valid'
        ),
    )

    @property
    def cow(self):
        return self.livestock

    @property
    def semen_id(self):
        return self.inventory_semen_id

    @semen_id.setter
    def semen_id(self, value):
        self.inventory_semen_id = value


class HeatObservation(db.Model):
    __tablename__ = 'heat_observations'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    observed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    intensity = db.Column(db.String(20), nullable=False, default='MEDIUM')
    signs = db.Column(db.JSON, nullable=False, default=list)
    notes = db.Column(db.Text, nullable=True)
    next_window_start = db.Column(db.Date, nullable=False)
    next_window_end = db.Column(db.Date, nullable=False)
    breeding_log_id = db.Column(db.Integer, db.ForeignKey('breeding_logs.id', ondelete='SET NULL'), nullable=True, unique=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    breeding_log = db.relationship('BreedingLog', backref=db.backref('heat_observation', uselist=False, lazy=True))

    __table_args__ = (
        db.CheckConstraint("intensity IN ('LOW', 'MEDIUM', 'HIGH')", name='ck_heat_observations_intensity_valid'),
        db.CheckConstraint('next_window_end >= next_window_start', name='ck_heat_observations_window_valid'),
        db.Index('ix_heat_observations_tenant_cow_observed', 'tenant_id', 'cow_id', 'observed_at'),
    )

class LactationCycle(db.Model):
    __tablename__ = 'lactation_cycles'

    id = db.Column(db.Integer, primary_key=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    cycle_number = db.Column(db.Integer, nullable=False)

    # Biological State Machine Dates
    insemination_date = db.Column(db.Date, nullable=True)
    expected_calving_date = db.Column(db.Date, nullable=True)
    drying_date = db.Column(db.Date, nullable=True)
    steaming_date = db.Column(db.Date, nullable=True)

    actual_calving_date = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True)

    @property
    def cow(self):
        return self.livestock

class MedicalRecord(db.Model):
    __tablename__ = 'medical_records'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False)
    vet_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    visit_date = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    diagnosis = db.Column(db.Text, nullable=False)
    medication = db.Column(db.String(255), nullable=True)
    withdrawal_days_recommended = db.Column(db.Integer, default=0)
    remarks = db.Column(db.Text, nullable=True)

    @property
    def cow(self):
        return self.livestock


@event.listens_for(MedicalRecord, 'before_insert')
def set_medical_record_tenant(mapper, connection, target):
    if target.tenant_id is not None:
        return

    if has_app_context():
        tenant_public_id = getattr(g, 'tenant_id', None)
        if tenant_public_id:
            try:
                from app.utils.jwt_payload import parse_public_int_id

                target.tenant_id = parse_public_int_id(tenant_public_id, 'tenant_')
                return
            except (TypeError, ValueError):
                pass

    cow = db.session.get(Cow, target.cow_id) if target.cow_id is not None else None
    if cow is not None:
        target.tenant_id = cow.tenant_id


class VetVisit(db.Model):
    __tablename__ = 'vet_visits'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False, index=True)
    animal_id = db.Column(db.Integer, db.ForeignKey('cows.id'), nullable=False, index=True)
    vet_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    visit_date = db.Column(db.Date, nullable=False)
    reason_for_visit = db.Column(db.Text, nullable=False)
    diagnosis = db.Column(db.Text, nullable=True)
    medications = db.Column(db.JSON, nullable=True)
    recommendations = db.Column(db.Text, nullable=True)
    remarks = db.Column(db.Text, nullable=True)
    observations = db.Column(db.Text, nullable=True)
    follow_up_required = db.Column(db.Boolean, nullable=False, default=False)
    follow_up_date = db.Column(db.Date, nullable=True)
    follow_up_status = db.Column(db.String(20), nullable=False, default='Not Required')
    follow_up_completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.CheckConstraint(
            "follow_up_status IN ('Not Required', 'Pending', 'Scheduled', 'Completed', 'Overdue', 'Cancelled')",
            name='ck_vet_visits_follow_up_status_valid'
        ),
    )

    @property
    def cow(self):
        return self.livestock

    @property
    def livestock_id(self):
        return self.animal_id


class HerdsmanRoutineTemplate(db.Model):
    __tablename__ = 'herdsman_routine_template'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    task_title = db.Column(db.String(100), nullable=False)
    task_description = db.Column(db.Text, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    checklist_items = db.Column(db.JSON, nullable=True)
    display_order = db.Column(db.Integer, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

    task_logs = db.relationship('DailyTaskLog', backref=db.backref('routine', lazy=True), lazy=True)


class DailyTaskLog(db.Model):
    __tablename__ = 'daily_task_logs'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    routine_id = db.Column(db.Integer, db.ForeignKey('herdsman_routine_template.id', ondelete='RESTRICT'), nullable=False, index=True)
    herdsman_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='RESTRICT'), nullable=False, index=True)
    issue_tag = db.Column(db.String(100), nullable=False, default='None')
    status = db.Column(db.String(20), nullable=True)
    completed_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    herdsman = db.relationship('User', backref=db.backref('daily_task_logs', lazy=True))

    __table_args__ = (
        db.CheckConstraint("status IN ('Completed', 'Deviated')", name='ck_daily_task_logs_status_valid'),
    )


class AnimalTimelineEvent(db.Model):
    __tablename__ = 'animal_events'

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True)
    cow_id = db.Column(db.Integer, db.ForeignKey('cows.id', ondelete='CASCADE'), nullable=False, index=True)
    event_type = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)
    event_date = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    event_data = db.Column(db.JSON, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
